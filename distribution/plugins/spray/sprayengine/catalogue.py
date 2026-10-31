"""The spray book: the inputs and blocks an application can refer to.

This is the same shape as the price book, and for the same reason: it is **operator-entered fact**.
A withholding period, a label maximum and a block's area are things somebody read off a label or a
map — not things an assistant may supply. The catalogue's job is to resolve the operator's words to
those facts, and to say which words it could not resolve rather than guessing.

Resolution never picks: it is exact, then alias, then substring, and anything with more than one
candidate raises :class:`pantler_core.Ambiguous`, whose `as_question()` is the sentence to ask. The
kernel already has those two errors and their wording, because the same discipline is what an
invoice's customer lookup does (the design notes §3, invariant 1).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from pantler_core import Ambiguous, Unknown
from pantler_core.units import normalize

# The rate units this product understands. Area rates are per hectare; concentration rates are per
# 100 litres of spray mix. They are different sums — one multiplies by the area, the other needs a
# spray volume nobody has given us — and conflating them is how a tank gets the wrong dose.
AREA_RATE_UNITS = ("L/ha", "mL/ha", "kg/ha", "g/ha")
CONCENTRATION_RATE_UNITS = ("mL/100L", "g/100L")
RATE_UNITS = AREA_RATE_UNITS + CONCENTRATION_RATE_UNITS


@dataclass(frozen=True)
class Block:
    id: str
    name: str
    area_ha: float | None = None
    certified: str = ""
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class Input:
    id: str
    name: str
    unit: str = ""
    withholding_days: int | None = None
    re_entry_hours: int | None = None
    registration: str = ""
    max_rate: float | None = None
    max_rate_unit: str = ""
    aliases: tuple[str, ...] = ()
    notes: str = ""


@dataclass(frozen=True)
class SprayBook:
    blocks: tuple[Block, ...] = ()
    inputs: tuple[Input, ...] = ()
    source: str = field(default="", compare=False)

    # ------------------------------------------------------------------ loading

    @classmethod
    def from_dict(cls, data: dict, source: str = "") -> SprayBook:
        blocks = tuple(
            Block(
                id=str(entry.get("id") or ""),
                name=str(entry.get("name") or "").strip(),
                area_ha=_opt_float(entry.get("area_ha")),
                certified=str(entry.get("certified") or ""),
                aliases=_aliases(entry),
            )
            for entry in (data.get("blocks") or [])
        )
        inputs = tuple(
            Input(
                id=str(entry.get("id") or ""),
                name=str(entry.get("name") or "").strip(),
                unit=str(entry.get("unit") or ""),
                withholding_days=_opt_int(entry.get("withholding_days")),
                re_entry_hours=_opt_int(entry.get("re_entry_hours")),
                registration=str(entry.get("registration") or ""),
                max_rate=_opt_float(entry.get("max_rate")),
                max_rate_unit=str(entry.get("max_rate_unit") or ""),
                aliases=_aliases(entry),
                notes=str(entry.get("notes") or ""),
            )
            for entry in (data.get("inputs") or [])
        )
        return cls(blocks=blocks, inputs=inputs, source=source)

    @classmethod
    def from_json_file(cls, path: str | Path) -> SprayBook:
        text = Path(path).read_text(encoding="utf-8")
        return cls.from_dict(json.loads(text), source=str(path))

    @classmethod
    def from_records(cls, book) -> SprayBook:
        """Read the blocks and the inputs out of the record store — the operator's own records.

        This is the authoritative source, and the JSON file is the fallback. The two existed side by
        side for two rounds, which produced the fault a live conversation found out loud: a "north
        block" in the spray book and no such block in the records, so the assistant could see the
        block in one tool and not the other. One set of facts, entered once, in the place the app
        writes them.

        `book` is a `pantler_core.RecordBook`; the parameter is untyped so this module keeps needing
        nothing but the kernel's public surface.
        """
        blocks = tuple(
            Block(
                id=record.id,
                name=str((record.data or {}).get("name") or "").strip(),
                area_ha=_opt_float((record.data or {}).get("area_ha")),
                certified=str((record.data or {}).get("certified") or ""),
            )
            for record in book.find("block", limit=500)
        )
        inputs = tuple(
            Input(
                id=record.id,
                name=str((record.data or {}).get("name") or "").strip(),
                unit=str((record.data or {}).get("unit") or ""),
                withholding_days=_opt_int((record.data or {}).get("withholding_days")),
                re_entry_hours=_opt_int((record.data or {}).get("re_entry_hours")),
                registration=str((record.data or {}).get("registration") or ""),
                max_rate=_opt_float((record.data or {}).get("max_rate")),
                max_rate_unit=str((record.data or {}).get("max_rate_unit") or ""),
                notes=str((record.data or {}).get("notes") or ""),
            )
            for record in book.find("input", limit=500)
        )
        return cls(
            blocks=blocks,
            inputs=inputs,
            source=f"the records ({len(blocks)} block(s), {len(inputs)} input(s))",
        )

    # ------------------------------------------------------------------ resolving

    def resolve_block(self, query: str) -> Block:
        return _resolve("block", query, self.blocks)

    def resolve_input(self, query: str) -> Input:
        return _resolve("input", query, self.inputs)

    # ------------------------------------------------------------------ reading

    def block_names(self) -> list[str]:
        return [block.name for block in self.blocks]

    def input_names(self) -> list[str]:
        return [product.name for product in self.inputs]


def _resolve(kind: str, query: str, entries) -> object:
    """Exact, then alias, then substring — and never a pick between candidates."""
    wanted = normalize(query)
    if not wanted:
        raise Unknown(kind, query, [entry.name for entry in entries])

    exact = [e for e in entries if normalize(e.name) == wanted or wanted in _norm(e.aliases)]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise Ambiguous(kind, query, [e.name for e in exact])

    # A substring either way: "copper" for "Copper oxychloride 500", or the operator's shorthand.
    partial = [
        e
        for e in entries
        if wanted in normalize(e.name)
        or normalize(e.name) in wanted
        or any(
            wanted in normalize(alias) or normalize(alias) in wanted for alias in e.aliases
        )
    ]
    if len(partial) == 1:
        return partial[0]
    if len(partial) > 1:
        raise Ambiguous(kind, query, [e.name for e in partial])
    raise Unknown(kind, query, [entry.name for entry in entries])


def _norm(values) -> tuple[str, ...]:
    return tuple(normalize(value) for value in values)


def _aliases(entry: dict) -> tuple[str, ...]:
    raw = entry.get("aliases") or []
    return tuple(str(alias).strip() for alias in raw if str(alias).strip())


def _opt_int(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _opt_float(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
