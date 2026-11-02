"""Rows from the operator's own record store, for a workbook.

The point of this module is invariant 1: an accountant's workbook must not be a transcription of
what the model thinks it read. The store is the ledger, `RecordBook` is the deterministic reader the
rest of the product uses, and the numbers that arrive here are the stored ones.

Two facts about that store shape this file, and both are easy to get wrong:

* **Money is integer cents.** A `money` field holds cents; a spreadsheet cell holds dollars. The
  conversion happens here, once, in `Decimal`, so a twelve-dollar invoice is `12.00` rather than
  `1200` or `0.12`.
* **A date is the string `YYYY-MM-DD`.** It sorts as text and as a date, which is why `--since` and
  `--until` are plain string comparisons against the field the pack declares.

The book is opened by the caller (which owns the plugin's path configuration) and is only ever read
with `find`. Nothing in this module writes.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pantler_core import RecordBook, RecordBookError

#: The pack's field kinds, mapped to the workbook column types this phase understands.
_KINDS = {
    "text": "text",
    "longtext": "text",
    "enum": "text",
    "reference": "text",
    "number": "number",
    "money": "money",
    "date": "date",
}

MAX_ROWS = 500


class RecordsError(RuntimeError):
    """The store cannot answer this request. The message names the reason, never guesses."""


def rows(book: RecordBook, type_name: str, *, limit: int = 200,
         columns: list[str] | None = None, since: str = "", until: str = "") -> dict:
    """One record type as `{columns, rows, count}` for the workbook spec."""
    name = str(type_name or "").strip()
    if not name:
        raise RecordsError("which record type should the workbook hold?")
    try:
        record_type = book.record_type(name)
    except RecordBookError as exc:
        available = ", ".join(book.types()) or "none"
        raise RecordsError(f"{exc}. This store holds: {available}") from exc

    declared = list(record_type.fields)
    if columns:
        wanted = [str(item).strip() for item in columns if str(item).strip()]
        unknown = [item for item in wanted if item not in {field.name for field in declared}]
        if unknown:
            raise RecordsError(
                f"{name} has no field {', '.join(unknown)}; it declares "
                f"{', '.join(field.name for field in declared) or 'no fields'}"
            )
        chosen = [field for field in declared if field.name in wanted]
    else:
        chosen = declared

    try:
        found = book.find(name, limit=min(max(1, int(limit)), MAX_ROWS))
    except RecordBookError as exc:
        raise RecordsError(str(exc)) from exc

    date_field = next((field for field in chosen if field.kind == "date"), None)
    if (since or until) and date_field is None:
        raise RecordsError(f"{name} has no date field, so a date range cannot be applied to it")
    kept = []
    for record in found:
        data = record.data or {}
        if date_field is not None:
            value = str(data.get(date_field.name) or "")
            if since and value and value < since:
                continue
            if until and value and value > until:
                continue
        kept.append(record)

    out_columns = [{"header": field.label or field.name, "key": field.name,
                    "type": _KINDS.get(field.kind, "text")} for field in chosen]
    out_rows = [[_value(field.kind, (record.data or {}).get(field.name)) for field in chosen]
                for record in kept]
    return {
        "type": name,
        "label": record_type.label,
        "columns": out_columns,
        "rows": out_rows,
        "count": len(out_rows),
        "limit": limit,
        "truncated": len(out_rows) >= min(max(1, int(limit)), MAX_ROWS),
    }


def _value(kind: str, value: Any):
    if value is None:
        return None
    if kind == "money":
        try:
            return float((Decimal(int(value)) / Decimal(100)).quantize(Decimal("0.01")))
        except (TypeError, ValueError):
            return None
    if kind == "number":
        return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None
    if kind == "date":
        return str(value)
    return str(value)
