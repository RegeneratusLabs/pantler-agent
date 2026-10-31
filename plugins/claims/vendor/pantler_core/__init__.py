"""pantler-core — the kernel.

The deterministic half of pantler, and deliberately not the domain half. It holds:

* the **record store** (:mod:`store`) — generic, knows record types but not meanings;
* the **pack contract** (:mod:`packs`) — what a pack declares, and how the shell learns it;
* **primitives** every pack needs — unit conversion (:mod:`units`), and the resolution
  errors (:mod:`errors`) that make "ask instead of guess" expressible.

Money, spray records, jobs and the rest are packs (``packs/``), not kernel. See
the front-end design §3. Nothing here imports an agent engine, an LLM client or a
transport.

The money code below (``catalog``, ``invoice``, ``loading``) is still in the kernel and is
the next thing to move out: it is the worked example that will prove the pack contract, and
it is the reason the pack contract must be wide enough to express it.
"""

from __future__ import annotations

from .catalog import Customer, Item, PriceBook
from .errors import Ambiguous, LedgerError, QuantityMustBePositive, UnitMismatch, Unknown
from .ids import format_sequential_id
from .invoice import Invoice, Ledger, Line, format_money, round_half_up
from .loading import PriceBookError, price_book_from_dict, price_book_from_json
from .recordbook import RecordBook, RecordBookError
from .packs import (
    FIELD_KINDS,
    SCREEN_KINDS,
    Field,
    Pack,
    PackError,
    PackRegistry,
    RecordType,
    Screen,
    format_record_id,
    load_pack,
    load_packs,
    pack_from_dict,
    render_pack_toml,
    validate_record,
)
from .store import Record, Store, StoreError, iter_records, open_store
from .units import UNITS, Unit, convert, resolve_unit

__all__ = [
    # resolution errors
    "Ambiguous",
    "LedgerError",
    "QuantityMustBePositive",
    "UnitMismatch",
    "Unknown",
    # units
    "UNITS",
    "Unit",
    "convert",
    "resolve_unit",
    # the pack contract
    "FIELD_KINDS",
    "SCREEN_KINDS",
    "Field",
    "Pack",
    "PackError",
    "PackRegistry",
    "RecordType",
    "Screen",
    "format_record_id",
    "format_sequential_id",
    "load_pack",
    "load_packs",
    "pack_from_dict",
    "render_pack_toml",
    "validate_record",
    # the store
    "Record",
    "Store",
    "StoreError",
    "iter_records",
    "open_store",
    # the money code, still in the kernel until it moves to packs/money
    "Customer",
    "Invoice",
    "Item",
    "Ledger",
    "Line",
    "PriceBook",
    "PriceBookError",
    "format_money",
    "price_book_from_dict",
    "price_book_from_json",
    "round_half_up",
]

__version__ = "0.0.1"
