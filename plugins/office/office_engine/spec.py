"""The spec the model may write, translated into the spec the vendored script understands.

Two reasons this module exists instead of letting the model write the engine's own JSON.

1. **The surface stays small and ours.** The upstream `xlsx_create.py` accepts charts, conditional
   formats, tables, validations and protection. None of that is reachable from a conversation until
   a later phase widens this schema deliberately — a capability is added, not leaked.
2. **The numbers are ours.** A total is written as a formula *and* as the value computed here, so
   the workbook is right before any spreadsheet opens it (`ooxml.py` puts the value back into the
   package). The model supplies rows; it never supplies a total.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

DEFAULT_CURRENCY = "$"

#: What a column may be. Everything else is refused by name, so a typo becomes a question.
TYPES = ("text", "number", "integer", "money", "percent", "date")

_NUMBER_FORMATS = {
    "money": '"%s"#,##0.00',
    "integer": "#,##0",
    "percent": "0.0%",
    "date": "yyyy-mm-dd",
    "number": "General",
    "text": "General",
}

_KEY = re.compile(r"^[a-z][a-z0-9_]{0,40}$")


class SpecError(ValueError):
    """The spec cannot be built as asked. The message names the row/column, never guesses."""


@dataclass
class Built:
    """Everything the tool layer needs after a successful build."""

    engine: dict
    cached: dict[str, float]
    sheets: list[dict] = field(default_factory=list)
    checks: list[str] = field(default_factory=list)


def build(spec: dict, *, currency: str = DEFAULT_CURRENCY) -> Built:
    """Translate one workbook spec. Raises `SpecError` with a sentence a person can act on."""
    if not isinstance(spec, dict):
        raise SpecError("the workbook spec must be an object")
    currency = (currency or DEFAULT_CURRENCY).strip() or DEFAULT_CURRENCY
    sheets = _sheets_of(spec)
    engine_sheets: list[dict] = []
    cached: dict[str, float] = {}
    preview: list[dict] = []
    checks: list[str] = []

    names: set[str] = set()
    for index, sheet in enumerate(sheets, start=1):
        built = _sheet(sheet, index=index, currency=currency)
        if built["name"].lower() in names:
            raise SpecError(f"two sheets are both named {built['name']!r}; sheet names are unique "
                            f"in a workbook")
        names.add(built["name"].lower())
        engine_sheets.append(built["engine"])
        cached.update(built["cached"])
        preview.append(built["preview"])
        checks.append(f"{built['name']}: {built['rows']} rows, {built['columns']} columns"
                      + (f", {built['totals']} totals" if built["totals"] else ""))

    engine = {"full_calc_on_load": True, "sheets": engine_sheets}
    if spec.get("title"):
        engine["title"] = str(spec["title"])[:120]
    return Built(engine=engine, cached=cached, sheets=preview, checks=checks)


# ------------------------------------------------------------------ structure

def _sheets_of(spec: dict) -> list[dict]:
    sheets = spec.get("sheets")
    if sheets is None:
        sheets = [spec]
    if not isinstance(sheets, list) or not sheets:
        raise SpecError("a workbook needs at least one sheet")
    for sheet in sheets:
        if not isinstance(sheet, dict):
            raise SpecError("each sheet must be an object with `columns` and `rows`")
    return sheets


def _sheet(sheet: dict, *, index: int, currency: str) -> dict:
    name = str(sheet.get("name") or sheet.get("sheet") or f"Sheet{index}").strip() or f"Sheet{index}"
    if len(name) > 31:
        raise SpecError(f"sheet name {name!r} is longer than Excel's 31 characters")
    if any(character in name for character in "[]:*?/\\"):
        raise SpecError(f"sheet name {name!r} contains a character Excel reserves: [ ] : * ? / \\")

    columns = _columns(sheet)
    rows = _rows(sheet, columns)
    title = str(sheet.get("title") or "").strip()
    last_column = _column_letter(len(columns))

    offset = 2 if title else 1              # title row, then the header
    header_row = offset
    first_data = offset + 1
    last_data = offset + len(rows)
    total_keys = _totals(sheet, columns)

    engine_rows: list[list] = []
    display_rows: list[list[str]] = []
    cached: dict[str, float] = {}
    totals_record: dict[str, object] = {}

    if title:
        engine_rows.append([{"value": title, "bold": True, "font_size": 14}] + [None] * (len(columns) - 1))
        display_rows.append([title] + [""] * (len(columns) - 1))

    engine_rows.append([{"value": column["header"], "bold": True, "fill": "F1F1EF"} for column in columns])
    display_rows.append([column["header"] for column in columns])

    for row_index, row in enumerate(rows, start=first_data):
        cells = [_cell(column, value) for column, value in zip(columns, row)]
        engine_rows.append(cells)
        display_rows.append([_display(column, value, currency) for column, value in zip(columns, row)])

    total_row = None
    if total_keys:
        total_row = last_data + 1
        cells: list = []
        labels: list[str] = []
        for position, column in enumerate(columns, start=1):
            if column["key"] in total_keys:
                letter = _column_letter(position)
                formula = f"SUM({letter}{first_data}:{letter}{last_data})"
                value = _sum(column, rows, position)
                cells.append({"formula": formula, "format": column["format"], "bold": True})
                cached[f"{name}!{letter}{total_row}"] = value
                labels.append(_display(column, value, currency))
                totals_record[column["key"]] = value
            else:
                cells.append({"value": "Total" if position == 1 else None, "bold": True})
                labels.append("Total" if position == 1 else "")
        engine_rows.append(cells)
        display_rows.append(labels)

    engine: dict = {
        "name": name,
        "rows": engine_rows,
        "column_widths": {_column_letter(position): width
                          for position, width in enumerate(_widths(columns, rows), start=1)},
    }
    freeze = sheet.get("freeze", True)
    if freeze:
        engine["freeze_panes"] = f"A{header_row + 1}"
    if sheet.get("filter", True) and last_data >= first_data:
        engine["autofilter"] = f"A{header_row}:{last_column}{last_data}"
    if title and len(columns) > 1:
        engine["merges"] = [f"A1:{last_column}1"]
    extra_merges = sheet.get("merges") or []
    if extra_merges:
        if not all(isinstance(item, str) and re.fullmatch(r"[A-Z]{1,3}\d+(:[A-Z]{1,3}\d+)?", item)
                   for item in extra_merges):
            raise SpecError("`merges` entries look like 'A1:C1'")
        engine["merges"] = list(engine.get("merges") or []) + list(extra_merges)

    # The preview's rows start at the header, so its total-row number is relative to them — not
    # the sheet's. The sheet may carry a title row above the header; the page does not count it.
    preview = {"name": name, "title": title, "columns": [column["header"] for column in columns],
               "rows": display_rows[2 if title else 1:],
               "total_row": (len(rows) + 1) if total_keys else None}
    return {"name": name, "engine": engine, "cached": cached, "preview": preview,
            "rows": len(rows), "columns": len(columns), "totals": len(total_keys)}


def _columns(sheet: dict) -> list[dict]:
    raw = sheet.get("columns")
    if not isinstance(raw, list) or not raw:
        raise SpecError("a sheet needs `columns`: one object per column, with at least `header`")
    columns: list[dict] = []
    seen: set[str] = set()
    for position, entry in enumerate(raw, start=1):
        if isinstance(entry, str):
            entry = {"header": entry}
        if not isinstance(entry, dict):
            raise SpecError(f"column {position} must be an object or a header string")
        header = str(entry.get("header") or "").strip()
        if not header:
            raise SpecError(f"column {position} has no `header`")
        kind = str(entry.get("type") or "text").strip().lower()
        if kind not in TYPES:
            raise SpecError(f"column {position} ({header!r}) has type {kind!r}; use one of "
                            f"{', '.join(TYPES)}")
        key = str(entry.get("key") or _slug(header))
        if not _KEY.match(key):
            raise SpecError(f"column {position} key {key!r} must be lowercase letters, digits and "
                            f"underscores, starting with a letter")
        if key in seen:
            raise SpecError(f"two columns share the key {key!r}; a row is keyed by it")
        seen.add(key)
        columns.append({
            "header": header,
            "key": key,
            "type": kind,
            "format": str(entry.get("format") or _NUMBER_FORMATS[kind]),
            "width": entry.get("width"),
            "total": bool(entry.get("total") is True),
        })
    return columns


def _rows(sheet: dict, columns: list[dict]) -> list[list]:
    raw = sheet.get("rows")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise SpecError("`rows` must be a list")
    out: list[list] = []
    keys = [column["key"] for column in columns]
    for position, row in enumerate(raw, start=1):
        if isinstance(row, dict):
            unknown = sorted(set(row) - set(keys))
            if unknown:
                raise SpecError(f"row {position} has value(s) for {', '.join(unknown)}, which no "
                                f"column names; the columns are {', '.join(keys)}")
            out.append([row.get(key) for key in keys])
        elif isinstance(row, (list, tuple)):
            if len(row) != len(columns):
                raise SpecError(f"row {position} has {len(row)} value(s) for {len(columns)} "
                                f"columns; a list row must line up with the columns")
            out.append(list(row))
        else:
            raise SpecError(f"row {position} is neither an object nor a list")
    return out


def _totals(sheet: dict, columns: list[dict]) -> set[str]:
    requested = sheet.get("totals")
    if requested is False:
        return set()
    if isinstance(requested, list):
        keys = [str(item) for item in requested]
        unknown = [key for key in keys if key not in {column["key"] for column in columns}]
        if unknown:
            raise SpecError(f"`totals` names {', '.join(unknown)}, which no column has")
        return set(keys)
    if requested is not None and not isinstance(requested, bool):
        raise SpecError("`totals` is a list of column keys, or false")
    return {column["key"] for column in columns if column["total"]}


def _widths(columns: list[dict], rows: list[list]) -> list[float]:
    widths = []
    for position, column in enumerate(columns):
        given = column.get("width")
        if isinstance(given, (int, float)) and given > 0:
            widths.append(min(60.0, max(6.0, float(given))))
            continue
        longest = len(column["header"])
        for row in rows:
            value = row[position]
            if value is not None:
                longest = max(longest, len(str(value)))
        widths.append(min(48.0, max(9.0, float(longest) + 2)))
    return widths


# ------------------------------------------------------------------ values

def _cell(column: dict, value):
    if value is None or value == "":
        return None
    kind = column["type"]
    if kind == "text":
        return {"value": str(value)}
    if kind == "date":
        if not isinstance(value, str):
            raise SpecError(f"{column['header']!r} is a date column; give dates as ISO strings")
        return {"value": value, "type": "date", "format": column["format"]}
    number = _decimal(value, column)
    payload: dict = {"value": float(number), "format": column["format"]}
    if kind == "integer":
        payload["value"] = int(number)
    return payload


def _decimal(value, column: dict) -> Decimal:
    if isinstance(value, bool):
        raise SpecError(f"{column['header']!r} is a number column; true/false is not a number")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise SpecError(f"{column['header']!r} expects a number, not {value!r}") from None
    if not number.is_finite():
        raise SpecError(f"{column['header']!r} expects a finite number, not {value!r}")
    if column["type"] == "money":
        return number.quantize(Decimal("0.01"))
    return number


def _sum(column: dict, rows: list[list], position: int) -> float:
    """The total the spreadsheet will show, computed here so the file carries it before it opens.

    Decimal, not float, so a column of cents adds up to cents: 0.1 + 0.2 is 0.30 in the cached
    value and in the preview, whatever a float would have said.
    """
    total = Decimal("0")
    index = position - 1
    for row in rows:
        value = row[index]
        if value is None or value == "" or isinstance(value, bool):
            continue
        total += Decimal(str(value))
    if column["type"] == "money":
        total = total.quantize(Decimal("0.01"))
    return float(total)


def _display(column: dict, value, currency: str) -> str:
    if value is None or value == "":
        return ""
    kind = column["type"]
    if kind == "text" or kind == "date":
        return str(value)
    number = Decimal(str(value))
    if kind == "money":
        amount = number.quantize(Decimal("0.01"))
        sign = "-" if amount < 0 else ""
        return f"{sign}{currency}{abs(amount):,.2f}"
    if kind == "integer":
        return f"{int(number):,}"
    if kind == "percent":
        return f"{number * 100:.1f}%"
    if number == number.to_integral_value():
        return f"{int(number):,}"
    return f"{number:.4f}".rstrip("0").rstrip(".")


def _slug(header: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", header.strip().lower()).strip("_")
    if not slug or not slug[0].isalpha():
        slug = f"c_{slug}" if slug else "column"
    return slug[:40]


def _column_letter(position: int) -> str:
    letters = ""
    while position > 0:
        position, remainder = divmod(position - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters
