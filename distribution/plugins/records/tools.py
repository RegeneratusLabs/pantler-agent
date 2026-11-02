"""The record tools: read and write the operator's own records, through the kernel.

The gap this closes is not a feature. A tool that computed a spray record and returned it looked
like it had recorded something — the assistant said "Recorded", the screen showed the figures, and
nothing was written anywhere. That is invariant 4's exact failure (*nothing claims more than it
did*), and it is worth stating plainly because the wrong version passed every test it had.

`RecordBook` is the fix, and it is the kernel's: validate against the pack's type, allocate the id
from the store's sequence, insert. The same object the BFF uses, so a record made in a conversation
and one typed into a screen are the same record rather than two implementations that agree today.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tomllib
from datetime import date
from pathlib import Path
from typing import Any, Callable

from pantler_core import (
    FIELD_KINDS,
    PackError,
    RecordBook,
    RecordBookError,
    pack_from_dict,
    render_pack_toml,
)

from . import schemas

TOOLSET = "records"
CAPABILITY_KEY = "capability_enabled"

#: The shipped record types `record_save` may write. Everything else a shipped pack declares is
#: written by the app or by the tool that holds the checks, and not from a conversation: `consent`
#: is what the consent gate reads, `invoice`/`invoice_line` carry a number and a status the
#: operator must be able to trust, and `campaign` belongs to the app beside them
#: (the internal security audit A19-PLUG-1, A19-PLUG-2, A19-DIST-8). `application` is out
#: for the same reason: its `block`/`input` references and its withholding fields are exactly what
#: `spray_record` derives from the catalogue and the store.
#:
#: A type declared by the operator's own custom pack is also writable. It cannot shadow a shipped
#: type — the merged registry refuses a duplicate — and it carries no shipped checks to get behind.
WRITABLE_TYPES = ("certificate", "block", "harvest", "input")

#: Names a custom type and its fields may use. Deliberately narrower than "anything TOML accepts":
#: these names become JSON keys, URLs and SQL parameters, and the operator should be able to read
#: them. Lowercase start, then lowercase letters, digits and underscores.
_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

_CTX = None
_STATE: dict[str, Any] = {"book": None}


def _fail(message: str, **extra) -> str:
    payload: dict[str, Any] = {"success": False, "error": message}
    payload.update(extra)
    return json.dumps(payload, default=str)


def _setting(key: str, default: Any = None) -> Any:
    """One key of this plugin's own config, read the way the engine exposes it."""
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
    """The refusal when this capability is off, or None when it may act."""
    value = _setting(CAPABILITY_KEY, True)
    if value is False or (
        isinstance(value, str) and value.strip().lower() in ("false", "off", "no")
    ):
        return _fail(
            "Records are switched off in Capabilities. Switch them back on there and ask me again."
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
    """`(store, packs, custom_packs)` from config, then the environment, then beside the profile.

    The custom tree is the operator's own schema, outside the distribution-owned `packs/`; a
    missing directory is a normal answer and loads as empty.
    """
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
            "no record store configured: set plugins.entries.records.settings.store_path and "
            "settings.packs_dir in "
            "config.yaml, or PANTLER_STORE and PANTLER_PACKS, or run beside HERMES_HOME"
        )
    store, packs, custom = paths
    if not packs.is_dir():
        # The basename, not the path: an absolute operator path in a tool result is an oracle for
        # model-chosen paths and tells the model about a filesystem it has no business in
        # (the internal security audit A19-PLUG-12).
        raise RecordBookError(f"no packs directory named {packs.name!r} at the configured place")
    if not store.parent.is_dir():
        raise RecordBookError(
            f"no directory named {store.parent.name!r} to hold the record store"
        )
    _STATE["book"] = RecordBook(store, packs, custom)
    return _STATE["book"]


def record_types(params: dict, **kwargs) -> str:
    if (refusal := _switched_off()) is not None:
        return refusal
    try:
        book = _book()
        rows = []
        for pack in book.registry.packs:
            for record in pack.records:
                rows.append(
                    {
                        "type": record.type,
                        "label": record.label,
                        "pack": pack.id,
                        "custom": book.is_custom_type(record.type),
                        "id_prefix": record.id_prefix,
                        "fields": [
                            {
                                "name": field.name,
                                "label": field.label,
                                "kind": field.kind,
                                "required": field.required,
                                **({"options": list(field.options)} if field.options else {}),
                            }
                            for field in record.fields
                        ],
                    }
                )
    except (RecordBookError, OSError) as exc:
        return _fail(str(exc))
    return json.dumps({"success": True, "types": rows}, default=str)


def _required_fields(book: RecordBook | None, type_name: str) -> list[dict[str, Any]]:
    """Every required field of a type, with the machine name the model must pass."""
    if book is None:
        return []
    try:
        record_type = book.record_type(type_name)
    except RecordBookError:
        return []
    return [
        {
            "name": field.name,
            "label": field.label,
            "kind": field.kind,
            **({"options": list(field.options)} if field.options else {}),
        }
        for field in record_type.fields
        if field.required
    ]


def record_save(params: dict, **kwargs) -> str:
    if (refusal := _switched_off()) is not None:
        return refusal
    type_name = str(params.get("type") or "").strip()
    fields = params.get("fields")
    if not type_name or not isinstance(fields, dict):
        return _fail("a record needs a `type` and a `fields` object")
    if type_name == "capture":
        return _fail(
            "captures are written by capture_save, not record_save. Call capture_save with the "
            "operator's words; then use the typed record's own tool and capture_link."
        )
    if type_name not in WRITABLE_TYPES:
        # The store would accept any declared type, which made this one call able to forge the
        # record a compliance gate reads (the internal security audit A19-PLUG-1, PLUG-2).
        # A type the operator declared in their own custom pack is different: it has no shipped
        # check to get behind, and the merged registry has already refused any name collision.
        try:
            book = _book()
        except RecordBookError as exc:
            return _fail(str(exc))
        if not book.is_custom_type(type_name):
            return _fail(
                f"{type_name!r} is not a record this tool writes. It writes: "
                f"{', '.join(WRITABLE_TYPES)}, and any type the operator has defined in their "
                f"own custom packs. A consent, a campaign and an invoice are recorded in the "
                f"app, and a spray application comes from the spray tool, so the checks behind "
                f"them stay in front of them."
            )
    try:
        book = _book()
        record = book.save(type_name, fields)
    except RecordBookError as exc:
        # The pack's problems, verbatim — they read well ("Whose certificate is required") but
        # they name the field's *label*, and the model has to pass the machine name. So the
        # refusal carries both: the sentence for the operator and the fields to ask for.
        return _fail(str(exc), required=_required_fields(_STATE["book"], type_name))
    except OSError as exc:
        return _fail(str(exc))
    return json.dumps(
        {
            "success": True,
            "id": record.id,
            "type": record.type,
            "pack": record.pack,
            "record": record.data,
            "saved_at": record.updated_at,
            "empty_fields": _empty_optional(book, type_name, record.data),
        },
        default=str,
    )


def _empty_optional(
    book: RecordBook | None, type_name: str, data: dict[str, Any]
) -> list[dict[str, str]]:
    """The declared fields this record left empty — the gaps worth asking about.

    Measured, not guessed: the certificate scenario spent 407,000 input tokens because the record
    it had just written was missing `evidence`, and the assistant went looking through the file
    tree to fill the gap. An incomplete record invites a hunt; naming the gap turns the hunt into a
    question. Only the *optional* fields are listed — a required one cannot be missing, since the
    pack would have refused the save.
    """
    if book is None:
        return []
    try:
        record_type = book.record_type(type_name)
    except RecordBookError:
        return []
    return [
        {"name": field.name, "label": field.label}
        for field in record_type.fields
        if not field.required and data.get(field.name) in (None, "", [], {})
    ]


def record_find(params: dict, **kwargs) -> str:
    if (refusal := _switched_off()) is not None:
        return refusal
    type_name = str(params.get("type") or "").strip()
    if not type_name:
        return _fail("which record type should I read?")
    where = params.get("where") if isinstance(params.get("where"), dict) else None
    # `int(params.get("limit") or 10)` used to be the whole of it: a list raised TypeError, an
    # infinity raised OverflowError, a negative number silently returned one record and 0 meant
    # ten (the internal audit PLUG-8, PLUG-16).
    raw_limit = params.get("limit")
    if raw_limit is None or raw_limit == "":
        limit = 10
    else:
        try:
            if isinstance(raw_limit, bool):
                raise ValueError
            limit = int(raw_limit)
        except (TypeError, ValueError, OverflowError):
            return _fail(f"limit has to be a whole number, got {raw_limit!r}")
        if not 1 <= limit <= 200:
            return _fail(f"limit has to be between 1 and 200, got {limit}")
    try:
        book = _book()
        records = book.find(
            type_name,
            limit=limit,
            where=where,
            contains=str(params.get("contains") or ""),
        )
    except RecordBookError as exc:
        return _fail(str(exc))
    except (OSError, ValueError) as exc:
        return _fail(str(exc))
    return json.dumps(
        {
            "success": True,
            "type": type_name,
            "count": len(records),
            # The envelope's id wins: `r.data` is the operator's fields, and a pack that ever
            # declares an `id` field would otherwise shadow the store's (PLUG-16).
            "records": [{**r.data, "id": r.id} for r in records],
            "note": (
                "An empty list means the operator holds no such record. Say that; do not answer "
                "from memory."
            ),
        },
        default=str,
    )



# ------------------------------------------------------------------- captures
#
# A capture is not a typed record. It is the operator's words, kept immediately, so a sentence
# that would need three questions before a `record_save` can succeed is not lost in the meantime.
# The typed record still goes through the tool that owns its checks, and `capture_link` only points
# at a record that already exists.

_CAPTURE_STATUSES = ("captured", "promoted", "dismissed")
_CAPTURE_SOURCES = ("chat", "voice", "import", "other")


def _capture_record(book: RecordBook, capture_id: str):
    record = book.get("capture", capture_id)
    if record is None:
        raise RecordBookError(f"no capture with id {capture_id}", "not_found")
    return record


def _iso_day(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return None


def capture_save(params: dict, **kwargs) -> str:
    if (refusal := _switched_off()) is not None:
        return refusal
    text = str(params.get("text") or "").strip()
    if not text:
        return _fail("what should I capture? Pass the operator's words in `text`.")
    if len(text) > 4000:
        return _fail("a capture has to fit in 4000 characters; keep the operator's words and leave the rest in the chat.")
    source = str(params.get("source") or "chat").strip().lower()
    warnings: list[str] = []
    if source not in _CAPTURE_SOURCES:
        warnings.append(f"source {source!r} is not one of {', '.join(_CAPTURE_SOURCES)}; saved as chat")
        source = "chat"
    occurred_on = _iso_day(params.get("occurred_on"))
    if params.get("occurred_on") and occurred_on is None:
        warnings.append("occurred_on was not YYYY-MM-DD; left blank and the capture time is kept")
    fields: dict[str, Any] = {
        "text": text,
        "status": "captured",
        "source": source,
    }
    if occurred_on:
        fields["occurred_on"] = occurred_on
    tags = str(params.get("tags") or "").strip()
    if tags:
        fields["tags"] = tags
    try:
        book = _book()
        record = book.save("capture", fields)
    except RecordBookError as exc:
        return _fail(str(exc))
    except OSError as exc:
        return _fail(str(exc))
    payload: dict[str, Any] = {
        "success": True,
        "id": record.id,
        "type": "capture",
        "pack": record.pack,
        "record": record.data,
        "saved_at": record.updated_at,
        "note": (
            "Captured. If it becomes a typed record, use that record's own tool and then "
            "capture_link with this id. Do not call a capture a record."
        ),
    }
    if warnings:
        payload["warnings"] = warnings
    return json.dumps(payload, default=str)


def capture_link(params: dict, **kwargs) -> str:
    if (refusal := _switched_off()) is not None:
        return refusal
    capture_id = str(params.get("capture_id") or "").strip()
    record_type = str(params.get("record_type") or "").strip()
    record_id = str(params.get("record_id") or "").strip()
    if not capture_id or not record_type or not record_id:
        return _fail("capture_link needs capture_id, record_type and record_id")
    if record_type == "capture":
        return _fail("a capture cannot be linked to another capture; link it to the typed record it became")
    try:
        book = _book()
        capture = _capture_record(book, capture_id)
        target = book.get(record_type, record_id)
        if target is None:
            return _fail(f"no {record_type} with id {record_id}; create the typed record first")
        data = dict(capture.data)
        if data.get("status") == "promoted" and (
            data.get("record_type") != record_type or data.get("record_id") != record_id
        ):
            return _fail(
                f"{capture_id} is already linked to {data.get('record_type')} {data.get('record_id')}; "
                "do not relink it"
            )
        data["status"] = "promoted"
        data["record_type"] = record_type
        data["record_id"] = record_id
        updated = book.update("capture", capture_id, data)
    except RecordBookError as exc:
        return _fail(str(exc))
    except OSError as exc:
        return _fail(str(exc))
    return json.dumps(
        {
            "success": True,
            "id": updated.id,
            "type": "capture",
            "record": updated.data,
            "linked_to": {"type": record_type, "id": record_id},
            "saved_at": updated.updated_at,
        },
        default=str,
    )


def capture_dismiss(params: dict, **kwargs) -> str:
    if (refusal := _switched_off()) is not None:
        return refusal
    capture_id = str(params.get("capture_id") or "").strip()
    if not capture_id:
        return _fail("capture_dismiss needs capture_id")
    try:
        book = _book()
        capture = _capture_record(book, capture_id)
        data = dict(capture.data)
        if data.get("status") == "promoted":
            return _fail(f"{capture_id} is already promoted to a record; leave it linked rather than dismissing it")
        data["status"] = "dismissed"
        updated = book.update("capture", capture_id, data)
    except RecordBookError as exc:
        return _fail(str(exc))
    except OSError as exc:
        return _fail(str(exc))
    return json.dumps(
        {"success": True, "id": updated.id, "type": "capture", "record": updated.data, "saved_at": updated.updated_at},
        default=str,
    )


# ------------------------------------------------------- custom record types
#
# A new kind of record is a pack type in the same store, not a skill, a CSV or a second
# database. The two tools below are the only path that writes one: propose (read-only),
# then create (approval-gated). The merged registry refuses a type or pack id that a shipped
# pack already owns.


def _slug(value: Any, what: str) -> str:
    text = str(value or "").strip().lower()
    if not _NAME_RE.match(text):
        raise RecordBookError(
            f"{what} has to start with a lowercase letter and use only lowercase letters, "
            f"numbers or underscores (got {value!r})"
        )
    return text


def _custom_type_pack(params: dict[str, Any]):
    """Validate a proposed custom type and return `(pack, custom_dir, raw_dict)`.

    Raises `RecordBookError` with a sentence the model can pass on. Nothing is written here.
    """
    type_name = _slug(params.get("type"), "the record type name")
    label = str(params.get("label") or "").strip()
    if not label:
        raise RecordBookError("a custom record type needs a label")
    plural = str(params.get("plural") or f"{label}s").strip()

    raw_fields = params.get("fields")
    if not isinstance(raw_fields, list) or not raw_fields:
        raise RecordBookError("a custom record type needs at least one field")
    fields: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, entry in enumerate(raw_fields, 1):
        if not isinstance(entry, dict):
            raise RecordBookError(f"field {index} has to be an object")
        name = _slug(entry.get("name"), f"field {index}'s name")
        if name in seen:
            raise RecordBookError(f"field {name!r} is declared twice")
        seen.add(name)
        field_label = str(entry.get("label") or "").strip()
        if not field_label:
            raise RecordBookError(f"field {name!r} needs a label")
        kind = str(entry.get("kind") or "text").strip().lower()
        if kind not in FIELD_KINDS:
            raise RecordBookError(
                f"field {name!r} has kind {kind!r}; use one of {', '.join(FIELD_KINDS)}"
            )
        field: dict[str, Any] = {"name": name, "label": field_label, "kind": kind}
        if entry.get("required") is True:
            field["required"] = True
        if kind == "enum":
            options = entry.get("options")
            if not isinstance(options, list) or not options:
                raise RecordBookError(f"enum field {name!r} needs an options list")
            field["options"] = [str(option) for option in options]
        if kind == "reference":
            reference = str(entry.get("reference") or "").strip()
            if not reference:
                raise RecordBookError(f"reference field {name!r} needs a target type")
            field["reference"] = reference
        if entry.get("help"):
            field["help"] = str(entry["help"])
        fields.append(field)

    raw_columns = params.get("columns")
    if raw_columns is None:
        columns = [field["name"] for field in fields[:3]]
    elif isinstance(raw_columns, list) and raw_columns:
        columns = [str(column) for column in raw_columns]
    else:
        raise RecordBookError("columns has to be a non-empty list of field names")
    declared = {field["name"] for field in fields}
    unknown = [column for column in columns if column not in declared]
    if unknown:
        raise RecordBookError(
            f"column {unknown[0]!r} is not one of the fields: {', '.join(sorted(declared))}"
        )

    prefix = str(params.get("id_prefix") or "").strip().upper()
    if not prefix:
        prefix = re.sub(r"[^A-Za-z0-9]", "", type_name).upper()[:3] or "REC"
    if not re.match(r"^[A-Z0-9]{1,8}$", prefix):
        raise RecordBookError("id_prefix has to be up to 8 uppercase letters or numbers")

    raw = {
        "id": f"custom-{type_name}",
        "name": label,
        "version": "1.0.0",
        "description": f"Operator-defined {label.lower()} records.",
        "records": [
            {
                "type": type_name,
                "label": label,
                "plural": plural,
                "title_field": columns[0] if len(columns) == 1 else columns,
                "id_prefix": prefix,
                "id_sequence": True,
                "fields": fields,
            }
        ],
        "screens": [
            {
                "id": type_name,
                "title": plural,
                "kind": "list",
                "record_type": type_name,
                "columns": columns,
            }
        ],
    }
    try:
        pack = pack_from_dict(raw, source=f"custom type {type_name}")
    except PackError as exc:
        raise RecordBookError(f"that is not a valid record type: {exc}") from exc

    book = _book()
    if book.registry.record_type(type_name) is not None:
        raise RecordBookError(
            f"a record type called {type_name!r} already exists; use record_types to see it"
        )
    if book.registry.pack(raw["id"]) is not None:
        raise RecordBookError(f"a custom pack called {raw['id']!r} already exists")

    paths = _paths()
    if paths is None or paths[2] is None:
        raise RecordBookError(
            "no custom-packs directory is configured; set "
            "plugins.entries.records.settings.custom_packs_dir "
            "or PANTLER_CUSTOM_PACKS"
        )
    return pack, paths[2], raw


def record_type_propose(params: dict, **kwargs) -> str:
    if (refusal := _switched_off()) is not None:
        return refusal
    try:
        pack, _custom_dir, raw = _custom_type_pack(params)
    except (RecordBookError, OSError) as exc:
        return _fail(str(exc))
    return json.dumps(
        {
            "success": True,
            "proposal": raw,
            "type": pack.records[0].type,
            "label": pack.records[0].label,
            "fields": [
                {"name": field.name, "label": field.label, "kind": field.kind}
                for field in pack.records[0].fields
            ],
            "message": (
                "Proposed only; nothing has been written. Show the fields to the operator, let "
                "them change them, and call record_type_create once they agree. Do not create a "
                "CSV, spreadsheet or second database."
            ),
        },
        default=str,
    )


def record_type_create(params: dict, **kwargs) -> str:
    if (refusal := _switched_off()) is not None:
        return refusal
    try:
        pack, custom_dir, raw = _custom_type_pack(params)
    except (RecordBookError, OSError) as exc:
        return _fail(str(exc))

    text = render_pack_toml(pack)
    try:
        round_trip = pack_from_dict(tomllib.loads(text), source="custom pack round-trip")
    except (PackError, tomllib.TOMLDecodeError) as exc:
        return _fail(f"I could not render that record type safely: {exc}")

    type_name = round_trip.records[0].type
    dest_dir = custom_dir / type_name
    dest = dest_dir / "pack.toml"
    if dest.exists() or dest_dir.exists():
        return _fail(f"a custom pack for {type_name!r} is already there; nothing was changed")
    tmp = dest_dir / "pack.toml.tmp"
    try:
        dest_dir.mkdir(parents=True, exist_ok=False)
        tmp.write_text(text, encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, dest)
    except OSError as exc:
        shutil.rmtree(dest_dir, ignore_errors=True)
        return _fail(f"I could not write the custom pack: {exc}")

    # The registry is cached on the book; drop it so the next call sees the new type.
    _STATE["book"] = None
    try:
        book = _book()
        created = book.record_type(type_name)
    except RecordBookError as exc:
        return _fail(f"the custom pack was written but could not be loaded: {exc}")
    if created is None:
        return _fail("the custom pack was written but the new type did not load")

    return json.dumps(
        {
            "success": True,
            "type": type_name,
            "label": created.label,
            "pack": raw["id"],
            "custom": True,
            "message": (
                f"Created the custom record type {created.label!r}. It uses the same records "
                f"database. Use record_save with type {type_name!r}."
            ),
        },
        default=str,
    )


_BLOCKED_WRITE = (
    "Record definitions and record data go through record_type_propose / record_type_create "
    "and record_save. Do not create or edit a pack file, the records database or a separate "
    "database/spreadsheet: the record store is the one place the operator's records live."
)


def _protected_paths() -> list[Path]:
    paths = _paths()
    if paths is None:
        return []
    store, packs, custom = paths
    roots = [store, packs]
    if custom is not None:
        roots.append(custom)
    resolved: list[Path] = []
    for path in roots:
        try:
            resolved.append(path.resolve())
        except OSError:
            resolved.append(path)
    return resolved


def _under(path: Path, roots: list[Path]) -> bool:
    try:
        candidate = path.resolve()
    except OSError:
        candidate = path
    for root in roots:
        try:
            candidate.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def _terminal_writes_protected(command: str) -> bool:
    lower = command.lower()
    if not any(
        token in lower
        for token in ("custom-packs", "records.db", "/packs/", "pack.toml")
    ):
        return False
    return any(
        marker in lower
        for marker in (
            ">", ">>", "tee ", "cp ", "mv ", "rm ", "sqlite3", "python", "cat >",
            "open(", "connect(",
        )
    )


def pre_tool_call(tool_name: str, args: dict[str, Any] | None = None, **kwargs):
    """Approve a custom-type write; guard the pack/store paths from direct writes.

    The engine's approval gate is the human decision for a new schema. The path guard is a
    safety net, not a sandbox: the positive path is `record_type_create`, and the tool is the
    only thing that writes the custom pack.
    """
    args = args or {}
    if tool_name == "record_type_create":
        try:
            pack, _custom_dir, _raw = _custom_type_pack(args)
        except (RecordBookError, OSError) as exc:
            return {"action": "block", "message": str(exc)}
        fields = ", ".join(field.label for field in pack.records[0].fields[:8])
        if len(pack.records[0].fields) > 8:
            fields += ", …"
        return {
            "action": "approve",
            "message": (
                f"Create the custom record type “{pack.records[0].label}” with fields: {fields}. "
                f"It will live in your custom packs and use the same records database."
            ),
            "rule_key": "records.custom_type",
        }

    if tool_name in ("write_file", "patch"):
        raw_path = args.get("path") or args.get("file_path")
        if raw_path:
            try:
                if _under(Path(str(raw_path)), _protected_paths()):
                    return {"action": "block", "message": _BLOCKED_WRITE}
            except OSError:
                pass

    if tool_name in ("terminal", "execute_code"):
        command = str(args.get("command") or args.get("code") or args.get("source") or "")
        if _terminal_writes_protected(command):
            return {"action": "block", "message": _BLOCKED_WRITE}
    return None


_TOOLS: tuple[tuple[str, dict, Callable[..., str]], ...] = (
    ("record_save", schemas.RECORD_SAVE, record_save),
    ("capture_save", schemas.CAPTURE_SAVE, capture_save),
    ("capture_link", schemas.CAPTURE_LINK, capture_link),
    ("capture_dismiss", schemas.CAPTURE_DISMISS, capture_dismiss),
    ("record_find", schemas.RECORD_FIND, record_find),
    ("record_types", schemas.RECORD_TYPES, record_types),
    ("record_type_propose", schemas.RECORD_TYPE_PROPOSE, record_type_propose),
    ("record_type_create", schemas.RECORD_TYPE_CREATE, record_type_create),
)
