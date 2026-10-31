"""The pack contract — what a pack declares, and how the shell learns it.

A pack **declares**; the shell **renders**. Nothing here knows what an invoice is, and it
must stay that way: the moment the contract grows a concept from one domain, every other
domain has to fight it.

Manifests are **TOML**, read with the standard library's ``tomllib``. The engine's own files
are YAML because the engine owns them; this file is ours, and ``tomllib`` means the kernel
keeps its ``dependencies = []`` promise (pyproject.toml) rather than taking PyYAML to read
six keys.
"""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path
from typing import Any, Iterable

from .ids import format_sequential_id

# The field kinds the shell renders. Kept deliberately small: a pack that needs something
# genuinely bespoke contributes a component later, and that should stay the exception.
FIELD_KINDS = ("text", "longtext", "number", "money", "date", "enum", "reference")

SCREEN_KINDS = ("list",)

#: The one date spelling a record may hold — what a form and a transcript both write, and
#: what sorts as text as well as it sorts as a date.
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class PackError(Exception):
    """A manifest is missing, unreadable, or does not satisfy the contract."""


@dataclass(frozen=True)
class Field:
    name: str
    label: str
    kind: str = "text"
    required: bool = False
    options: tuple[str, ...] = ()
    reference: str = ""
    help: str = ""

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"name": self.name, "label": self.label, "kind": self.kind}
        if self.required:
            out["required"] = True
        if self.options:
            out["options"] = list(self.options)
        if self.reference:
            out["reference"] = self.reference
        if self.help:
            out["help"] = self.help
        return out


@dataclass(frozen=True)
class RecordType:
    type: str
    label: str
    plural: str
    fields: tuple[Field, ...] = ()
    #: Fields shown as a record's title in lists and links, joined by " · ". One name is the
    #: common case; more than one is how a type whose rows would otherwise read identically — two
    #: applications in different blocks on the same day — gets a distinguishing label. Defaults to
    #: the first field (the internal audit PACK-2).
    title_field: tuple[str, ...] = ()
    #: Allocate sequential ids from the store (INV-0001) instead of random ones.
    id_prefix: str = ""
    id_sequence: bool = False

    def field(self, name: str) -> Field | None:
        return next((f for f in self.fields if f.name == name), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "label": self.label,
            "plural": self.plural,
            "fields": [f.to_dict() for f in self.fields],
            "title_field": list(
                self.title_field or ((self.fields[0].name,) if self.fields else ("id",))
            ),
            "id_prefix": self.id_prefix,
            "id_sequence": self.id_sequence,
        }


@dataclass(frozen=True)
class Screen:
    id: str
    title: str
    kind: str
    record_type: str
    columns: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "kind": self.kind,
            "record_type": self.record_type,
            "columns": list(self.columns),
        }


@dataclass(frozen=True)
class Pack:
    id: str
    name: str
    version: str = "0.0.0"
    description: str = ""
    records: tuple[RecordType, ...] = ()
    screens: tuple[Screen, ...] = ()
    #: Where the manifest was read from, for diagnostics. Empty for a pack built in code.
    source: str = field(default="", compare=False)
    #: True for an operator-authored pack loaded from ``custom-packs/``. The flag is how the
    #: shell marks it and how ``record_save`` knows the type is the operator's own, not a
    #: shipped type whose checks have to stay in front of it.
    custom: bool = field(default=False, compare=False)

    def record_type(self, type: str) -> RecordType | None:
        return next((r for r in self.records if r.type == type), None)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "records": [r.to_dict() for r in self.records],
            "screens": [s.to_dict() for s in self.screens],
        }
        if self.custom:
            payload["custom"] = True
        return payload


# ------------------------------------------------------------------- loading


def load_pack(path: str | Path) -> Pack:
    """Read and validate one ``pack.toml``. Raises :class:`PackError` with the reason."""
    manifest = Path(path)
    if manifest.is_dir():
        manifest = manifest / "pack.toml"
    if not manifest.is_file():
        raise PackError(f"no pack manifest at {manifest}")

    try:
        raw = tomllib.loads(manifest.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise PackError(f"{manifest}: invalid TOML: {exc}") from exc
    except RecursionError as exc:
        # TOML may nest arrays arbitrarily; the parser recurses, so a hostile manifest is a
        # crash rather than a refusal without this (the internal security audit A19-KERN-3).
        raise PackError(f"{manifest}: nested too deeply to be a manifest") from exc
    except OSError as exc:
        raise PackError(f"{manifest}: cannot read: {exc}") from exc

    return pack_from_dict(raw, source=str(manifest))


def _entries(raw: dict[str, Any], key: str, where: str) -> list[dict[str, Any]]:
    """`raw[key]` as a list of mappings, or a `PackError` naming the manifest.

    "Valid TOML of the wrong shape" is a plausible typo (`records = "spray"`, an inline table,
    a mistyped `screens`), and every consumer below calls `.get` on the entries. Without this it
    surfaced as an `AttributeError` from deep inside the parser — which the BFF does not catch,
    so a pack being edited took every request down instead of leaving the previous registry
    serving (the internal security audit A19-KERN-3).
    """
    value = raw.get(key, [])
    if value is None:
        return []
    if not isinstance(value, list):
        raise PackError(f"{where}: '{key}' has to be a list of tables, got {type(value).__name__}")
    for index, entry in enumerate(value):
        if not isinstance(entry, dict):
            raise PackError(
                f"{where}: '{key}[{index}]' has to be a table, got {type(entry).__name__}"
            )
    return list(value)


def pack_from_dict(raw: dict[str, Any], *, source: str = "") -> Pack:
    pack_id = str(raw.get("id") or "").strip()
    if not pack_id:
        raise PackError(f"{source or 'pack'}: 'id' is required")

    where = source or pack_id
    record_entries = _entries(raw, "records", where)
    records = tuple(_record_type_from_dict(entry, pack_id, source) for entry in record_entries)
    # Two entries with one type name is a manifest bug that would otherwise surface as the
    # registry reporting the pack as claiming a type from itself — a message that sends the
    # reader looking for a second pack (the internal audit K4).
    seen: dict[str, int] = {}
    for entry in record_entries:
        name = str(entry.get("type") or "").strip()
        seen[name] = seen.get(name, 0) + 1
    duplicated = sorted(name for name, count in seen.items() if count > 1)
    if duplicated:
        raise PackError(
            f"{source or pack_id}: record type {duplicated[0]!r} is declared more than once"
        )
    known = {r.type: r for r in records}

    screens = tuple(
        _screen_from_dict(entry, pack_id, known, source) for entry in _entries(raw, "screens", where)
    )

    return Pack(
        id=pack_id,
        name=str(raw.get("name") or pack_id),
        version=str(raw.get("version") or "0.0.0"),
        description=str(raw.get("description") or ""),
        records=records,
        screens=screens,
        source=source,
    )


def _record_type_from_dict(entry: dict[str, Any], pack_id: str, source: str) -> RecordType:
    type_name = str(entry.get("type") or "").strip()
    if not type_name:
        raise PackError(f"{source or pack_id}: a record entry has no 'type'")

    fields = tuple(
        _field_from_dict(f, type_name, source)
        for f in _entries(entry, "fields", f"{source or pack_id}: record '{type_name}'")
    )
    if not fields:
        raise PackError(f"{source or pack_id}: record '{type_name}' declares no fields")

    title_field = _title_field_from(entry.get("title_field"), type_name, source, pack_id,
                                    {f.name for f in fields})

    return RecordType(
        type=type_name,
        label=str(entry.get("label") or type_name),
        plural=str(entry.get("plural") or f"{entry.get('label') or type_name}s"),
        fields=fields,
        title_field=title_field,
        id_prefix=str(entry.get("id_prefix") or ""),
        # Not `bool(...)`: the string "false" is truthy, so a manifest that spelled it out
        # silently switched the type to store-allocated sequence ids
        # (the internal security audit A19-KERN-4).
        id_sequence=_flag(entry, "id_sequence", f"{source or pack_id}: record '{type_name}'"),
    )


def _title_field_from(raw: Any, type_name: str, source: str, pack_id: str,
                      field_names: set[str]) -> tuple[str, ...]:
    """`title_field` as one name or a list of them, each of which must be a declared field."""
    if raw is None or raw == "":
        return ()
    if isinstance(raw, str):
        names = (raw,)
    elif isinstance(raw, (list, tuple)):
        for name in raw:
            if not isinstance(name, str):
                raise PackError(
                    f"{source or pack_id}: record '{type_name}' title_field has to be a field "
                    f"name or a list of them, got {name!r}"
                )
        names = tuple(raw)
    else:
        raise PackError(
            f"{source or pack_id}: record '{type_name}' title_field has to be a field name or a "
            f"list of them, got {raw!r}"
        )
    for name in names:
        if name not in field_names:
            raise PackError(
                f"{source or pack_id}: record '{type_name}' title_field {name!r} is not a field"
            )
    return names


def _flag(entry: dict[str, Any], key: str, where: str) -> bool:
    """A boolean manifest key, with the spellings YAML-ish hands write, or a refusal."""
    value = entry.get(key, False)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("true", "yes", "on", "1"):
            return True
        if lowered in ("false", "no", "off", "0", ""):
            return False
    raise PackError(f"{where}: '{key}' has to be true or false, got {value!r}")


def _field_from_dict(entry: dict[str, Any], type_name: str, source: str) -> Field:
    name = str(entry.get("name") or "").strip()
    if not name:
        raise PackError(f"{source or type_name}: a field of '{type_name}' has no 'name'")

    kind = str(entry.get("kind") or "text")
    if kind not in FIELD_KINDS:
        raise PackError(
            f"{source or type_name}: field '{name}' has kind {kind!r}; expected one of {', '.join(FIELD_KINDS)}"
        )

    # A string is iterable, so `options = "dry,wet"` used to become one option per *character*:
    # the enum silently accepted "d" and rejected "dry" (the internal security audit
    # A19-KERN-4).
    raw_options = entry.get("options", ())
    if raw_options is None:
        raw_options = ()
    if isinstance(raw_options, str) or not isinstance(raw_options, (list, tuple)):
        raise PackError(
            f"{source or type_name}: field '{name}' options has to be a list of strings"
        )
    options = tuple(str(o) for o in raw_options)
    if kind == "enum" and not options:
        raise PackError(f"{source or type_name}: enum field '{name}' declares no options")

    reference = str(entry.get("reference") or "")
    if kind == "reference" and not reference:
        raise PackError(f"{source or type_name}: reference field '{name}' does not say what it references")

    return Field(
        name=name,
        label=str(entry.get("label") or name),
        kind=kind,
        required=bool(entry.get("required", False)),
        options=options,
        reference=reference,
        help=str(entry.get("help") or ""),
    )


def _screen_from_dict(
    entry: dict[str, Any], pack_id: str, known: dict[str, RecordType], source: str
) -> Screen:
    screen_id = str(entry.get("id") or "").strip()
    if not screen_id:
        raise PackError(f"{source or pack_id}: a screen entry has no 'id'")

    kind = str(entry.get("kind") or "list")
    if kind not in SCREEN_KINDS:
        raise PackError(
            f"{source or pack_id}: screen '{screen_id}' has kind {kind!r}; expected one of {', '.join(SCREEN_KINDS)}"
        )

    record_type = str(entry.get("record_type") or "").strip()
    if record_type not in known:
        raise PackError(
            f"{source or pack_id}: screen '{screen_id}' refers to record type {record_type!r}, "
            f"which this pack does not declare"
        )

    # A column that is not a declared field renders as an empty cell for ever, and the
    # manifest is the only place that could have caught it (the internal audit K3).
    # `title_field` has been checked since the contract existed; this is the same check for
    # the list's columns.
    declared = {f.name for f in known[record_type].fields}
    raw_columns = entry.get("columns", ())
    if isinstance(raw_columns, str) or not isinstance(raw_columns, (list, tuple)):
        raise PackError(
            f"{source or pack_id}: screen '{screen_id}' columns has to be a list of field names"
        )
    columns = tuple(str(c) for c in raw_columns)
    for column in columns:
        if column not in declared:
            raise PackError(
                f"{source or pack_id}: screen '{screen_id}' lists column {column!r}, which "
                f"'{record_type}' does not declare"
            )

    return Screen(
        id=screen_id,
        title=str(entry.get("title") or screen_id),
        kind=kind,
        record_type=record_type,
        columns=columns,
    )


# ------------------------------------------------------------------ registry


class PackRegistry:
    """Every pack the install knows about, and the record types they own."""

    def __init__(self, packs: Iterable[Pack] = ()):
        self._packs: dict[str, Pack] = {}
        self._types: dict[str, RecordType] = {}
        self._owner: dict[str, str] = {}
        for pack in packs:
            self.add(pack)

    def add(self, pack: Pack) -> None:
        if pack.id in self._packs:
            raise PackError(f"pack {pack.id!r} is already registered")
        for record_type in pack.records:
            # Two packs claiming one type would make the store ambiguous, and the failure
            # would show up as data mysteriously moving between screens.
            if record_type.type in self._types:
                raise PackError(
                    f"record type {record_type.type!r} is claimed by both "
                    f"{self._owner[record_type.type]!r} and {pack.id!r}"
                )
            self._types[record_type.type] = record_type
            self._owner[record_type.type] = pack.id
        self._packs[pack.id] = pack

    @property
    def packs(self) -> list[Pack]:
        return list(self._packs.values())

    @property
    def record_types(self) -> list[RecordType]:
        return list(self._types.values())

    def pack(self, pack_id: str) -> Pack | None:
        return self._packs.get(pack_id)

    def record_type(self, type: str) -> RecordType | None:
        return self._types.get(type)

    def owner(self, type: str) -> str | None:
        return self._owner.get(type)

    def to_dict(self) -> list[dict[str, Any]]:
        return [pack.to_dict() for pack in self._packs.values()]


def load_packs(directory: str | Path, *, custom_dir: str | Path | None = None) -> PackRegistry:
    """Load every ``<dir>/<pack>/pack.toml``. Missing directories are empty registries.

    ``custom_dir`` is the operator's own pack tree. It is loaded after the shipped tree, marked
    ``custom=True``, and a type or pack id it duplicates is refused by the registry — a custom
    pack can add a new kind of record, never shadow a shipped one.
    """
    packs = _packs_in(directory)
    if custom_dir is not None:
        packs.extend(_packs_in(custom_dir, custom=True))
    return PackRegistry(packs)


def _packs_in(directory: str | Path, *, custom: bool = False) -> list[Pack]:
    root = Path(directory)
    if not root.is_dir():
        return []

    packs: list[Pack] = []
    for child in sorted(root.iterdir()):
        if child.is_dir() and (child / "pack.toml").is_file():
            pack = load_pack(child)
            packs.append(replace(pack, custom=True) if custom else pack)
    return packs


def _toml_string(value: str) -> str:
    """A TOML basic string. JSON's escaping is a subset TOML accepts for these characters."""
    return json.dumps(str(value), ensure_ascii=False)


def _toml_array(values: Iterable[str]) -> str:
    return "[" + ", ".join(_toml_string(value) for value in values) + "]"


def render_pack_toml(pack: Pack) -> str:
    """Render a pack back to TOML for the operator's ``custom-packs/`` tree.

    This is deliberately a writer for the declaration subset we accept, not a general TOML
    emitter: ids, names, field kinds, enum options, screens. It is the inverse of
    :func:`pack_from_dict` for that subset, and the custom-record tool round-trips through both
    before it writes anything.
    """
    lines = [
        f"id = {_toml_string(pack.id)}",
        f"name = {_toml_string(pack.name)}",
        f"version = {_toml_string(pack.version)}",
    ]
    if pack.description:
        lines.append(f"description = {_toml_string(pack.description)}")

    for record in pack.records:
        lines.extend(["", "[[records]]", f"type = {_toml_string(record.type)}",
                      f"label = {_toml_string(record.label)}",
                      f"plural = {_toml_string(record.plural)}"])
        if len(record.title_field) == 1:
            lines.append(f"title_field = {_toml_string(record.title_field[0])}")
        elif record.title_field:
            lines.append(f"title_field = {_toml_array(record.title_field)}")
        if record.id_prefix:
            lines.append(f"id_prefix = {_toml_string(record.id_prefix)}")
        if record.id_sequence:
            lines.append("id_sequence = true")

        for field in record.fields:
            lines.extend(["", "  [[records.fields]]",
                          f"  name = {_toml_string(field.name)}",
                          f"  label = {_toml_string(field.label)}",
                          f"  kind = {_toml_string(field.kind)}"])
            if field.required:
                lines.append("  required = true")
            if field.options:
                lines.append(f"  options = {_toml_array(field.options)}")
            if field.reference:
                lines.append(f"  reference = {_toml_string(field.reference)}")
            if field.help:
                lines.append(f"  help = {_toml_string(field.help)}")

    for screen in pack.screens:
        lines.extend(["", "[[screens]]", f"id = {_toml_string(screen.id)}",
                      f"title = {_toml_string(screen.title)}",
                      f"kind = {_toml_string(screen.kind)}",
                      f"record_type = {_toml_string(screen.record_type)}",
                      f"columns = {_toml_array(screen.columns)}"])

    return "\n".join(lines).rstrip() + "\n"


# ------------------------------------------------------------------- ids


def format_record_id(record_type: RecordType, number: int) -> str:
    """Render a sequential id for a record type, e.g. ``INV-0001``.

    The rendering itself is :func:`pantler_core.ids.format_sequential_id`, shared with the money
    example's drafts so that the two cannot drift; this is the pack-aware door onto it, which
    knows that a type's prefix defaults to its name in capitals.
    """
    return format_sequential_id(record_type.id_prefix or record_type.type.upper(), number)


# ---------------------------------------------------------------- validation


def validate_record(record_type: RecordType, data: dict[str, Any]) -> list[str]:
    """Check ``data`` against a declared record type. Returns human-readable problems.

    Deliberately returns *all* the problems rather than raising on the first: a form that
    reports one error at a time is a form nobody finishes.
    """
    problems: list[str] = []

    if not isinstance(data, dict):
        return ["record data must be an object"]

    declared = {f.name for f in record_type.fields}
    for key in data:
        if key not in declared:
            problems.append(f"{key!r} is not a field of {record_type.type}")

    for spec in record_type.fields:
        value = data.get(spec.name)
        missing = value is None or (isinstance(value, str) and not value.strip())

        if missing:
            if spec.required:
                problems.append(f"{spec.label} is required")
            continue

        if spec.kind == "money":
            # Money is an integer number of cents everywhere else in this package, and the
            # store keeps whatever it is handed. A float that reached here would be stored as
            # one and then met `format_money`, which divides it — `12.0 // 100` is `0.0`, so a
            # twelve-dollar invoice would print as nothing (the internal audit K1).
            if isinstance(value, bool) or not isinstance(value, int):
                problems.append(f"{spec.label} must be a whole number of cents")
        elif spec.kind == "number":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                problems.append(f"{spec.label} must be a number")
        elif spec.kind == "date":
            # A date is the string a form and a transcript both write: `YYYY-MM-DD`. Anything
            # else — "next tuesday", "16/10/2026" — is not a date this store can sort or a
            # compliance record can be audited against (the internal audit K2).
            if not isinstance(value, str):
                problems.append(f"{spec.label} must be a date as YYYY-MM-DD")
            elif not _ISO_DATE_RE.match(value):
                problems.append(f"{spec.label} must be a date as YYYY-MM-DD")
            else:
                try:
                    date.fromisoformat(value)
                except ValueError:
                    problems.append(f"{spec.label} is not a real date")
        elif spec.kind == "enum":
            if value not in spec.options:
                problems.append(f"{spec.label} must be one of: {', '.join(spec.options)}")
        elif spec.kind == "reference":
            if not isinstance(value, str):
                problems.append(f"{spec.label} must be a {spec.reference} id")
        elif not isinstance(value, str):
            problems.append(f"{spec.label} must be text")

    return problems
