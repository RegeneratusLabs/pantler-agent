"""The consent gate as a tool: one lookup, one refusal, no judgement.

Thin adapter over `consentengine`. It reads the same record store the app writes, so a consent the
operator recorded in the app is a consent this gate can see.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable

from pantler_core import RecordBook, RecordBookError

from . import schemas
from .consentengine import check_send

TOOLSET = "consent"
CAPABILITY_KEY = "capability_enabled"

_CTX = None
_STATE: dict[str, Any] = {"book": None}


def _fail(message: str, **extra) -> str:
    payload: dict[str, Any] = {"success": False, "error": message}
    payload.update(extra)
    return json.dumps(payload, default=str)


def _setting(key: str, default: Any = None) -> Any:
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
    """A gate that is switched off must say so — it must never quietly allow the send."""
    value = _setting(CAPABILITY_KEY, True)
    if value is False or (
        isinstance(value, str) and value.strip().lower() in ("false", "off", "no")
    ):
        return _fail(
            "Consent checking is switched off in Capabilities, so nobody here has been checked "
            "against a consent record. Switch it back on before anything is sent — or check the "
            "records yourself, in the app."
        )
    return None


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


def _paths() -> tuple[Path, Path, Path | None] | None:
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


def _book() -> RecordBook:
    if _STATE["book"] is not None:
        return _STATE["book"]
    paths = _paths()
    if paths is None:
        raise RecordBookError(
            "no record store configured: set plugins.entries.consent.store_path and packs_dir in "
            "config.yaml, or PANTLER_STORE and PANTLER_PACKS"
        )
    store, packs, custom = paths
    if not packs.is_dir():
        # The basename, not the path: the refusal reaches the transcript, and an absolute
        # operator path there is a file-existence oracle for model-chosen paths
        # (the internal security audit A19-PLUG-12).
        raise RecordBookError(
            f"no packs directory named {packs.name!r} at the configured place"
        )
    _STATE["book"] = RecordBook(store, packs, custom)
    return _STATE["book"]


def consent_check(params: dict, **kwargs) -> str:
    if (refusal := _switched_off()) is not None:
        return refusal
    raw = params.get("recipients")
    if isinstance(raw, str):
        recipients = [part.strip() for part in raw.split(",") if part.strip()]
    elif isinstance(raw, list):
        recipients = [str(item) for item in raw if str(item).strip()]
    else:
        return _fail("give me the people as `recipients`: one entry per person")
    if not recipients:
        return _fail("no recipients given, so there is nothing to check")
    purpose = str(params.get("purpose") or "").strip()
    if not purpose:
        # A gate that can be skipped by saying nothing is not a gate. The engine refuses an
        # unstated place as well; this is the sentence the model gets, with the reason and the
        # shape of the answer it needs (the internal security audit A19-PLUG-9).
        return _fail(
            "Which place is this message going to? A consent is for one place — the newsletter, "
            "the website, the stall board — and it is checked against the place, so name it and "
            "ask me again. Nothing has been checked."
        )
    try:
        book = _book()
        result = check_send(
            book,
            recipients,
            purpose=purpose,
            draft=str(params.get("draft") or ""),
        )
    except RecordBookError as exc:
        return _fail(str(exc))
    except OSError as exc:
        return _fail(str(exc))
    return json.dumps(
        {
            "success": True,
            "send_allowed": result.allowed,
            "decisions": [decision.as_dict() for decision in result.decisions],
            "draft_checks": result.checks,
            "refusals": result.refusals,
            "questions": result.questions,
            "note": (
                "Every recipient must be `allowed` before anything is sent. A `no_record` or "
                "`withdrawn` decision is a refusal: say what is missing rather than sending."
            ),
        },
        default=str,
    )


_TOOLS: tuple[tuple[str, dict, Callable[..., str]], ...] = (
    ("consent_check", schemas.CONSENT_CHECK, consent_check),
)
