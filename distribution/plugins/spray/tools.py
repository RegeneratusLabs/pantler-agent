"""The spray tools: resolve, compute, or say what has to be settled first.

Every handler is a thin adapter. The arithmetic lives in ``sprayengine``, which imports the kernel's
errors and unit table and nothing else. Nothing here is outbound, and nothing here invents a number:
a missing withholding period leaves the field empty and comes back as a warning the assistant can
say out loud (invariant 1, and the reason the skill drafts says so twice).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable

from pantler_core import Ambiguous, RecordBook, RecordBookError, Unknown

from . import schemas
from .sprayengine import SprayBook, record_application

TOOLSET = "spray"
CAPABILITY_KEY = "capability_enabled"

_CTX = None
_STATE: dict[str, Any] = {"book": None, "records": None, "stamp": None}


def _fail(message: str, **extra) -> str:
    payload: dict[str, Any] = {"success": False, "error": message}
    payload.update(extra)
    return json.dumps(payload, default=str)


def _setting(key: str, default: Any = None) -> Any:
    """One key of this plugin's own config, read the way the engine exposes it.

    `ctx.get_config(key, default)` is the engine's own reader — plugin-relative, one key at a time,
    re-read on every call. An older surface handed over the whole block, so both are tried; a
    reader that raises is a shape we do not have rather than a reason to fail the call.
    """
    getter = getattr(_CTX, "get_config", None)
    if callable(getter):
        try:
            return getter(key, default)
        except TypeError:
            pass
        except Exception:
            return default
        try:
            block = getter()
        except Exception:
            block = None
        if isinstance(block, dict):
            return block.get(key, default)
    block = getattr(_CTX, "config", None)
    if isinstance(block, dict):
        return block.get(key, default)
    return default


def _switched_off() -> str | None:
    """The refusal when this capability is off, or None when it may act.

    The engine's plugin list is restart-grade — "there is no un-wire primitive, so a running gateway
    keeps the plugin's handlers until restart" — so the live half of the switch is this key, read on
    every call, or a tool registered before the switch stays callable in an open conversation.
    """
    value = _setting(CAPABILITY_KEY, True)
    if value is False or (
        isinstance(value, str) and value.strip().lower() in ("false", "off", "no")
    ):
        return _fail(
            "Spray records are switched off in Capabilities. Switch them back on there and ask "
            "me again."
        )
    return None


def _catalogue_path() -> Path | None:
    configured = _setting("catalogue_path") or _setting("spray_book") or _setting("catalogue")
    if configured:
        return Path(os.path.expanduser(os.path.expandvars(str(configured))))
    env = os.environ.get("PANTLER_SPRAYBOOK", "").strip()
    if env:
        return Path(os.path.expanduser(os.path.expandvars(env)))
    home = os.environ.get("HERMES_HOME", "").strip()
    if home:
        return Path(home) / "spraybook.json"
    return None


def _book_stamp() -> str:
    """What the spray book is built from, and when each source last changed.

    The store is SQLite in WAL mode, so a write lands in `<store>-wal` before the database file
    itself: both mtimes are in the stamp, or a withholding period corrected in the app while this
    process is running would not move it (the internal security audit A19-PLUG-11).
    """
    parts: list[str] = []
    paths = _store_paths()
    if paths is not None:
        store = str(paths[0])
        for suffix in ("", "-wal"):
            try:
                parts.append(f"{store}{suffix}:{os.stat(f'{store}{suffix}').st_mtime_ns}")
            except OSError:
                parts.append(f"{store}{suffix}:-")
    path = _catalogue_path()
    if path is not None:
        try:
            parts.append(f"{path}:{path.stat().st_mtime_ns}")
        except OSError:
            parts.append(f"{path}:-")
    return "|".join(parts)


def _book() -> SprayBook:
    """The blocks and inputs, from the records if the store has any, else from the JSON file.

    The records win, and the file is the fallback, because the records are what the app writes and
    what the assistant can also write. Keeping both silently was the fault a live conversation found:
    a block set up in the app was invisible to this tool while a block in the file was invisible to
    every other one. The result says which source it used, so a name that resolves in one place and
    not the other is visible to the operator instead of mysterious.

    The book is re-read when the store or the file behind it changes. Caching it for the life of
    the process meant a withholding period corrected in the app (7 days to 21) was invisible until
    the gateway restarted, and the stale figure is what the record printed as an earliest safe
    harvest date (the internal security audit A19-PLUG-11).
    """
    stamp = _book_stamp()
    if _STATE["book"] is not None and _STATE.get("stamp") == stamp:
        return _STATE["book"]

    records = _records()
    if records is not None:
        from_records = SprayBook.from_records(records)
        if from_records.blocks or from_records.inputs:
            _STATE["source"] = from_records.source
            _STATE["book"] = from_records
            _STATE["stamp"] = stamp
            return from_records

    path = _catalogue_path()
    if path is None or not path.is_file():
        if records is not None:
            _STATE["book"] = SprayBook(source="the records (empty)")
            _STATE["stamp"] = stamp
            return _STATE["book"]
        raise RuntimeError(
            "no spray book: set up your blocks and inputs in the app, or point "
            "plugins.entries.spray.settings.catalogue_path at a spray book JSON file"
        )
    book = SprayBook.from_json_file(path)
    # The basename, not the path: this string reaches the transcript, and an absolute path there
    # is a file-existence oracle for model-chosen paths
    # (the internal security audit A19-PLUG-12).
    book = SprayBook(blocks=book.blocks, inputs=book.inputs, source=f"the file {path.name}")
    _STATE["source"] = book.source
    _STATE["book"] = book
    _STATE["stamp"] = stamp
    return book


def _profile_dir() -> Path | None:
    """The profile this plugin is installed in, or None when it is not in one.

    A profile install puts the payload's `plugins/` at `<profile>/plugins/`, so this file's
    second parent up is the profile root — the directory holding `config.yaml`. That file is
    the test: a plugin loaded from a working copy (whose layout is `plugins/<name>/` inside a
    checkout) must not decide the checkout is a profile and start writing a record store into
    it. Kept identical in `records`, `consent` and `spray`, which resolve their paths the same
    way (the internal audit DIST-1).
    """
    candidate = Path(__file__).resolve().parents[2]
    return candidate if (candidate / "config.yaml").is_file() else None


def _store_paths() -> tuple[Path, Path, Path | None] | None:
    """`(store, packs, custom_packs)` — the app's record store and the installed packs, or None."""
    home = os.environ.get("HERMES_HOME", "").strip()
    store = str(_setting("store_path") or os.environ.get("PANTLER_STORE") or "").strip()
    packs = str(_setting("packs_dir") or os.environ.get("PANTLER_PACKS") or "").strip()
    custom = str(
        _setting("custom_packs_dir") or os.environ.get("PANTLER_CUSTOM_PACKS") or ""
    ).strip()
    profile = _profile_dir()
    if not store and profile is not None:
        # The payload ships no store: one beside the profile's config is where the operator's
        # records belong, and it needs no `plugins.entries` block to work.
        store = str(profile / "records.db")
    if not packs and profile is not None and (profile / "packs").is_dir():
        # The payload ships `packs/`, so a fresh install reads the types it shipped with.
        packs = str(profile / "packs")
    if not custom and profile is not None:
        custom = str(profile / "custom-packs")
    if not store and home:
        store = str(Path(home) / "records.db")
    if not packs and home:
        packs = str(Path(home) / "packs")
    if not custom and home:
        custom = str(Path(home) / "custom-packs")
    if not store or not packs:
        return None
    return (
        Path(os.path.expanduser(os.path.expandvars(store))),
        Path(os.path.expanduser(os.path.expandvars(packs))),
        Path(os.path.expanduser(os.path.expandvars(custom))) if custom else None,
    )


def _records() -> RecordBook | None:
    """The record store, or None when this install has none configured.

    None is a real answer rather than a failure: the arithmetic is still worth doing, and the tool
    says plainly that nothing was written. What it must never do is compute a record and let the
    assistant say "recorded" — that is a claim the system cannot back.
    """
    if _STATE["records"] is not None:
        return _STATE["records"]
    paths = _store_paths()
    if paths is None:
        return None
    store, packs, custom = paths
    if not packs.is_dir() or not store.parent.is_dir():
        return None
    _STATE["records"] = RecordBook(store, packs, custom)
    return _STATE["records"]


def spray_record(params: dict, **kwargs) -> str:
    if (refusal := _switched_off()) is not None:
        return refusal
    try:
        book = _book()
    except (OSError, RuntimeError, ValueError) as exc:
        return _fail(str(exc))
    try:
        result = record_application(
            book,
            applied=str(params.get("applied") or ""),
            block=str(params.get("block") or ""),
            product=str(params.get("product") or ""),
            rate=params.get("rate") if params.get("rate") is not None else "",
            rate_unit=str(params.get("rate_unit") or ""),
            area_ha=params.get("area_ha"),
            operator=str(params.get("operator") or ""),
            notes=str(params.get("notes") or ""),
        )
    except (OverflowError, ZeroDivisionError, ValueError) as exc:
        # `1e400`, `1/0` and a JSON infinity are arguments, not rates: the engine bounds them and
        # answers with a refusal, and this keeps anything that still escapes from reaching the
        # model as a traceback (the internal security audit A19-PLUG-5).
        return _fail(f"I couldn't read those numbers: {exc}. What rate was actually applied?")
    if result.get("success") and params.get("dry_run"):
        # Computed, not written. The audit's finding was that a rate above the label maximum was
        # saved *and* questioned in the same answer, with no way to check first
        # (the internal audit PLUG-13).
        result["saved"] = False
        result["dry_run"] = True
        result.setdefault("note", "")
        result["note"] = (
            "Nothing was written: this was a dry run. Read the figures and the questions back to "
            "the operator, and call again with dry_run false once they have confirmed."
        )
    elif result.get("success"):
        result = _save(result)
        source = str(_STATE.get("source") or "")
        if source.startswith("the file"):
            # Visible rather than silent: the operator may have set the block up in the app, and
            # this tool resolved against a file instead.
            result.setdefault("warnings", []).append(
                f"Resolved against {source}, not your records. Blocks and inputs you set up in the "
                f"app are not in it — add them there and this tool will use them."
            )
        result["spray_book_source"] = source
    return json.dumps(result, default=str)


def _save(result: dict) -> dict:
    """Write the computed record, and be honest about whether it went anywhere."""
    try:
        book = _records()
    except RecordBookError as exc:
        book = None
        result.setdefault("warnings", []).append(f"The record store could not be opened: {exc}")
    if book is None:
        result["saved"] = False
        result.setdefault("warnings", []).append(
            "Nothing was written: this install has no record store configured. The figures above "
            "are computed but not recorded — say so rather than saying it was saved."
        )
        return result
    payload = dict(result["record"])
    payload.pop("block_name", None)
    payload.pop("input_name", None)
    try:
        stored = book.save("application", payload)
    except RecordBookError as exc:
        result["saved"] = False
        result.setdefault("warnings", []).append(f"Nothing was written: {exc}")
        return result
    result["saved"] = True
    result["id"] = stored.id
    result["summary"] = f"{stored.id}: {result['summary']}"
    return result


def spray_inputs(params: dict, **kwargs) -> str:
    """The label facts on file — including which ones are missing, which is the useful half."""
    if (refusal := _switched_off()) is not None:
        return refusal
    try:
        book = _book()
    except (OSError, RuntimeError, ValueError) as exc:
        return _fail(str(exc))
    rows = []
    for product in book.inputs:
        missing = [
            name
            for name, value in (
                ("withholding period", product.withholding_days),
                ("re-entry period", product.re_entry_hours),
                ("label reference", product.registration),
                ("maximum rate", product.max_rate),
            )
            if value in (None, "")
        ]
        rows.append(
            {
                "name": product.name,
                "unit": product.unit,
                "withholding_days": product.withholding_days,
                "re_entry_hours": product.re_entry_hours,
                "registration": product.registration,
                "max_rate": product.max_rate,
                "max_rate_unit": product.max_rate_unit,
                "missing": missing,
            }
        )
    return json.dumps(
        {
            "success": True,
            "blocks": [{"name": b.name, "area_ha": b.area_ha, "certified": b.certified} for b in book.blocks],
            "inputs": rows,
            "note": (
                "A missing withholding period is a question for the label, not for you: say which "
                "products are missing one and offer to add it once the operator reads it out."
            ),
        },
        default=str,
    )


_TOOLS: tuple[tuple[str, dict, Callable[..., str]], ...] = (
    ("spray_record", schemas.SPRAY_RECORD, spray_record),
    ("spray_inputs", schemas.SPRAY_INPUTS, spray_inputs),
)
