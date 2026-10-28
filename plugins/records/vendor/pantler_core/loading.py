"""Loading a price book from configuration.

The operator's customers, prices and tax rate are data, not code. This module is the
only place they enter the library, and it validates rather than coerces: a malformed
price book raises instead of half-loading, because a partially loaded price book is a
wrong-answer generator.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .catalog import Customer, Item, PriceBook
from .units import UNITS


class PriceBookError(ValueError):
    """The price book on disk is malformed."""


def _require(mapping: Mapping[str, Any], key: str, where: str) -> Any:
    if key not in mapping:
        raise PriceBookError(f"{where}: missing required key {key!r}")
    return mapping[key]


def price_book_from_dict(data: Mapping[str, Any]) -> PriceBook:
    if not isinstance(data, Mapping):
        raise PriceBookError(f"price book must be a mapping, got {type(data).__name__}")

    currency = str(data.get("currency", "AUD")).upper()
    tax_label = str(data.get("tax_label", "Tax"))
    tax_rate_bp = data.get("tax_rate_bp")
    if tax_rate_bp is not None:
        tax_rate_bp = int(tax_rate_bp)
        if not 0 <= tax_rate_bp <= 10_000:
            raise PriceBookError(f"tax_rate_bp must be between 0 and 10000, got {tax_rate_bp}")

    book = PriceBook(currency=currency, tax_rate_bp=tax_rate_bp, tax_label=tax_label)

    for i, raw in enumerate(data.get("customers", [])):
        where = f"customers[{i}]"
        book.add_customer(
            Customer(
                id=str(_require(raw, "id", where)),
                name=str(_require(raw, "name", where)),
                aliases=tuple(str(a) for a in raw.get("aliases", [])),
                email=str(raw.get("email", "")),
                terms_days=int(raw.get("terms_days", 14)),
            )
        )

    for i, raw in enumerate(data.get("items", [])):
        where = f"items[{i}]"
        unit = str(_require(raw, "unit", where))
        if unit not in UNITS:
            raise PriceBookError(
                f"{where}: unknown unit {unit!r}; known units are {', '.join(sorted(UNITS))}"
            )
        price = int(_require(raw, "unit_price_cents", where))
        if price < 0:
            raise PriceBookError(f"{where}: unit_price_cents must not be negative, got {price}")
        book.add_item(
            Item(
                id=str(_require(raw, "id", where)),
                name=str(_require(raw, "name", where)),
                unit=unit,
                unit_price_cents=price,
                aliases=tuple(str(a) for a in raw.get("aliases", [])),
            )
        )

    if not book.customers:
        raise PriceBookError("price book has no customers")
    if not book.items:
        raise PriceBookError("price book has no items")
    return book


def price_book_from_json(path: str | Path) -> PriceBook:
    raw = Path(path).read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PriceBookError(f"{path}: not valid JSON: {exc}") from exc
    return price_book_from_dict(data)
