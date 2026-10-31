"""The invoice tools.

Every tool here is a thin adapter: it takes what the model extracted from the operator's
words, hands it to ``pantler_core``, and renders the result — or the question the
ledger refused to answer. No arithmetic, no lookup and no rounding happens in this
file. That separation is invariant 1 of the design notes.

**Nothing here is outbound, and nothing here is gated.** There is no send tool and no
approval hook: money handling is not a centred feature of the product, and when we build
it, it belongs in a pack rather than in the core plugin. Everything registered here only
reads or drafts.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable

from pantler_core import (
    Ambiguous,
    Ledger,
    LedgerError,
    PackError,
    PriceBookError,
    QuantityMustBePositive,
    RecordBook,
    RecordBookError,
    Store,
    StoreError,
    UnitMismatch,
    Unknown,
    format_money,
    format_sequential_id,
    load_packs,
    price_book_from_json,
)

# The capability the operator sees is "invoicing", not "records": the toolset name is what the
# Capabilities page offers as a switch, and one switch must mean one thing. The generic record
# tools live in plugins/records/ under `records` — the two meet in the store, not in a name.
TOOLSET = "invoicing"

#: The invoice-number prefix. One string, in one place: `format_sequential_id` renders it.
_INVOICE_PREFIX = "INV"

_STATE: dict[str, Any] = {"ctx": None, "ledger": None, "store": None, "pricebook_stamp": None}

# ---------------------------------------------------------------- configuration


# The live half of this capability's switch. The engine's plugin list is restart-grade — its
# own CLI says "there is no un-wire primitive, so a running gateway keeps the plugin's handlers
# until restart" — so a tool that is already registered stays callable until then. This key is
# read on every call, which is what lets the handler refuse instead of acting.
CAPABILITY_KEY = "capability_enabled"


def _setting(ctx: Any, key: str, default: Any = None) -> Any:
    """One key of this plugin's own config, read the way the engine exposes it.

    The engine's API is `ctx.get_config(key, default)` — plugin-relative and one key at a time
    — while older surfaces handed over the whole block as a dict. Both are tried, and a reader
    that raises is a shape we do not have rather than a reason to fail the call.
    """
    getter = getattr(ctx, "get_config", None)
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
    block = getattr(ctx, "config", None)
    if isinstance(block, dict):
        return block.get(key, default)
    return default


def _switched_off() -> str | None:
    """The refusal when this capability is off, or None when it may act.

    The sentence alone classified as `ok` in the shell — it matches no question prefix and ends in
    a full stop — so a switched-off capability was drawn as a normal result. It is an envelope
    with `success: false` and the sentence in `question`, which is what the shell reads
    (the internal audit CON-5, PLUG-15).
    """
    ctx = _STATE.get("ctx")
    if ctx is None:
        return None
    value = _setting(ctx, CAPABILITY_KEY, True)
    if value is False or (isinstance(value, str) and value.strip().lower() in ("false", "off", "no")):
        message = (
            "Invoicing is switched off in Capabilities. Switch it back on there and ask me again."
        )
        return json.dumps({"success": False, "message": message, "question": message})
    return None


def _price_book_path(ctx: Any) -> Path | None:
    for key in ("pricebook_path", "price_book", "pricebook"):
        raw = _setting(ctx, key)
        if raw:
            return Path(os.path.expanduser(os.path.expandvars(str(raw))))
    env = os.environ.get("PANTLER_PRICEBOOK", "").strip()
    if env:
        return Path(os.path.expanduser(os.path.expandvars(env)))
    profile = _profile_dir()
    if profile is not None and (profile / "pricebook.json").is_file():
        return profile / "pricebook.json"
    home = os.environ.get("HERMES_HOME", "").strip()
    if home:
        candidate = Path(home) / "pricebook.json"
        return candidate
    return None


def _packs_dir() -> Path | None:
    """Where the record types live: config, then the environment, then beside the profile.

    The same resolution the three record-writing plugins use, kept identical on purpose — a
    fresh install has `packs/` beside `config.yaml` and nothing configured, and a working copy
    has `PANTLER_PACKS` (the internal audit DIST-1).
    """
    configured = str(_setting(_STATE.get("ctx"), "packs_dir") or os.environ.get("PANTLER_PACKS") or "").strip()
    if configured:
        return Path(os.path.expanduser(os.path.expandvars(configured)))
    profile = _profile_dir()
    if profile is not None and (profile / "packs").is_dir():
        return profile / "packs"
    home = os.environ.get("HERMES_HOME", "").strip()
    if home and (Path(home) / "packs").is_dir():
        return Path(home) / "packs"
    return None


def _book():
    """The record book for the money types, or None when this install cannot hold records."""
    if _STATE.get("book") is not None:
        return _STATE["book"]
    store = _STATE.get("store")
    if store is None:
        store = _store()
        _STATE["store"] = store
    packs = _packs_dir()
    if store is None or packs is None or not packs.is_dir():
        return None
    try:
        _STATE["book"] = RecordBook.over(store, load_packs(packs))
    except (PackError, StoreError):
        # A store that cannot be read is not a reason to refuse the arithmetic: the draft is
        # still worth showing, and the caller says it was not saved.
        return None
    return _STATE["book"]


def _profile_dir() -> Path | None:
    """The profile this plugin is installed in, or None when it is not in one.

    A profile install puts the payload's `plugins/` at `<profile>/plugins/`, so this file's
    second parent up is the profile root — the directory holding `config.yaml`. That file is
    the test: a plugin loaded from a working copy must not decide the checkout is a profile.
    Kept identical in `pantler`, `records`, `consent` and `spray`, which resolve their paths
    the same way (the internal audit DIST-1).
    """
    candidate = Path(__file__).resolve().parents[2]
    return candidate if (candidate / "config.yaml").is_file() else None


def _store():
    """The record store: the invoice number's sequence, and now the invoice itself.

    The number was always reserved here — a counter that restarts at 1 hands the same number to a
    different invoice after a restart, which is a compliance problem rather than a cosmetic one
    (the internal backend audit §1.2). The draft that number belongs to is saved here too, in the
    `money` pack's `invoice` and `invoice_line` types
    (the internal audit PLUG-1, PLUG-14). Returns None when this install has no store, and
    the ledger then says both its numbers and its drafts are a fixture's.
    """
    configured = str(_setting(_STATE.get("ctx"), "store_path") or os.environ.get("PANTLER_STORE") or "").strip()
    if configured:
        path = Path(os.path.expanduser(os.path.expandvars(configured)))
    else:
        profile = _profile_dir()
        home = os.environ.get("HERMES_HOME", "").strip()
        if profile is not None:
            path = profile / "records.db"
        elif home:
            path = Path(home) / "records.db"
        else:
            return None
    if not path.parent.is_dir():
        return None
    try:
        return Store(path)
    except StoreError:
        return None


def _ledger() -> Ledger:
    ctx = _STATE["ctx"]
    path = _price_book_path(ctx)
    if path is None:
        raise PriceBookError(
            "no price book configured: set plugins.entries.pantler.pricebook_path "
            "in config.yaml, or PANTLER_PRICEBOOK, or place pricebook.json in HERMES_HOME"
        )
    if not path.is_file():
        # The basename rather than the operator's whole path: the message reaches the transcript,
        # and an absolute path there is a file-existence oracle for model-chosen paths
        # (the internal security audit A19-PLUG-12).
        raise PriceBookError(f"price book not found: {path.name}")

    # Re-read when the operator's price book changes: the old cache was keyed on nothing, so an
    # edited price or a corrected tax rate was invisible until the gateway restarted
    # (the internal audit PLUG-14).
    cached = _STATE.get("ledger")
    stamp = f"{path}:{path.stat().st_mtime_ns}"
    if cached is not None and _STATE.get("pricebook_stamp") == stamp:
        return cached

    store = _STATE.get("store")
    if store is None:
        store = _store()
        _STATE["store"] = store

    def next_number() -> str:
        assert store is not None
        return format_sequential_id(_INVOICE_PREFIX, store.next_sequence("invoice"))

    ledger = Ledger(
        price_book_from_json(path),
        invoice_prefix=_INVOICE_PREFIX,
        jurisdiction=os.environ.get("PANTLER_JURISDICTION", ""),
        number_source=next_number if store is not None else None,
    )
    _STATE["ledger"] = ledger
    _STATE["pricebook_stamp"] = stamp
    return ledger


# ---------------------------------------------------------------------- schemas

_CREATE_SCHEMA = {
    "name": "invoice_create",
    "description": (
        "Create a DRAFT invoice for a customer. Nothing is sent. Resolves the customer, "
        "the items, the unit conversions, the prices and the tax from the price book, and saves "
        "the draft in the money pack so it survives a restart — the result says whether it was "
        "saved, and never claims it was when it was not. If the operator's words are ambiguous "
        "it asks which one they meant instead of choosing."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "customer": {"type": "string", "description": "Customer as the operator said it, e.g. 'Bellview CSA'."},
            "lines": {
                "type": "array",
                "minItems": 1,
                "description": "One entry per thing being billed.",
                "items": {
                    "type": "object",
                    "properties": {
                        "item": {"type": "string", "description": "Item as the operator said it, e.g. 'beans'."},
                        "quantity": {
                            "anyOf": [{"type": "number"}, {"type": "string"}],
                            "description": "How many. '12', '0.5' and '4' are all fine.",
                        },
                        "unit": {
                            "type": "string",
                            "description": "Unit as the operator said it, e.g. 'kilos', 'dozen'. Omit only if the operator gave no unit.",
                        },
                    },
                    "required": ["item", "quantity"],
                },
            },
            "notes": {"type": "string", "description": "Any note the operator asked for."},
        },
        "required": ["customer", "lines"],
    },
}

_SHOW_SCHEMA = {
    "name": "invoice_show",
    "description": "Show a draft invoice by its number, e.g. INV-0001.",
    "parameters": {
        "type": "object",
        "properties": {"number": {"type": "string", "description": "Invoice number."}},
        "required": ["number"],
    },
}


# --------------------------------------------------------------------- handlers


def _question(exc: LedgerError) -> str:
    return f"I need to check one thing before I bill this. {exc.as_question()}"


def _stored_invoice(number: str) -> dict[str, Any] | None:
    """The saved invoice and its lines, in the same shape the draft path returns.

    A saved invoice is the durable answer, so it is read first: a draft the operator has since
    corrected in the store must not be shown from a stale in-memory copy.

    It is resolved by its **envelope id**, and the record's own `number` field has to agree with
    that id. The store's id *is* the number — `_save_draft` writes the number as the record id —
    so the two are one fact, and a record whose `number` names a different invoice is not that
    invoice. Searching the caller-writable `number` field instead showed a forgery written by
    anything else that can save a record: the pack requires the field, so a second record could
    claim INV-0001 and be shown in the genuine invoice's place
    (the internal security audit A19-PLUG-1).
    """
    book = _book()
    if book is None:
        return None
    try:
        header = book.get("invoice", number)
        if header is None:
            return None
        data = dict(header.data)
        if str(data.get("number") or header.id) != number:
            # One number, two records. Neither is safe to show as the ledger's own, so the
            # answer is the not-found sentence and the operator sees the conflict in the app.
            return None
        lines = book.find("invoice_line", where={"invoice": number}, limit=200)
    except (RecordBookError, StoreError):
        return None
    return {
        "number": str(data.get("number") or header.id),
        "customer": str(data.get("customer") or ""),
        "currency": str(data.get("currency") or ""),
        "status": str(data.get("status") or "draft"),
        "tax_excluded": not data.get("tax_cents"),
        "tax_label": str(data.get("tax_label") or "Tax"),
        "subtotal_cents": int(data.get("subtotal_cents") or 0),
        "tax_cents": int(data.get("tax_cents") or 0),
        "total_cents": int(data.get("total_cents") or 0),
        "lines": [
            {
                "quantity": _quantity_text(line.data.get("quantity")),
                "unit": str(line.data.get("unit") or ""),
                "description": str(line.data.get("description") or ""),
                "unit_price": format_money(
                    int(line.data.get("unit_price_cents") or 0),
                    str(data.get("currency") or ""),
                ),
                "amount": format_money(
                    int(line.data.get("amount_cents") or 0), str(data.get("currency") or "")
                ),
            }
            for line in sorted(lines, key=lambda row: row.data.get("position") or 0)
        ],
    }


def _quantity_text(value: Any) -> str:
    """A stored quantity as the draft wrote it: `2`, not `2.0`."""
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return str(value or "")
    return str(int(number)) if number == int(number) else f"{number:g}"


#: The largest line quantity this tool will hand to the ledger. It is a count or a measure a
#: business could mean; `1e400` is not one. The bound is here, in front of every write, because
#: the conversion used to raise `OverflowError` *after* the invoice header had been stored — one
#: burnt invoice number and an orphan record per hostile call
#: (the internal security audit A19-PLUG-5).
_MAX_QUANTITY = 1e9


def _quantity_problem(raw: Any) -> str | None:
    """None when the ledger may have this quantity, else the half-sentence that says why not.

    `float` is the test rather than any arithmetic: `"1e400"` is an infinity, a JSON `1e400` is
    one before it arrives, a 400-digit integer raises `OverflowError`, and `"1/0"` is not a
    number at all — all four used to reach the ledger and escape as a traceback
    (the internal security audit A19-PLUG-5).
    """
    try:
        number = float(raw)
    except (TypeError, ValueError, OverflowError):
        return f"I couldn't read {raw!r} as a quantity. How many should it be?"
    if number != number or number in (float("inf"), float("-inf")):
        return f"{raw!r} is not a quantity I can put on an invoice. How many should it be?"
    if abs(number) > _MAX_QUANTITY:
        return (
            f"{raw!r} is larger than any quantity I will put on an invoice. How many should it "
            f"be?"
        )
    return None


def _stored_summary(invoice: dict[str, Any]) -> str:
    """The prose a stored invoice answers with — the same sentences the draft path uses."""
    lines = "\n".join(
        f"  • {line['quantity']} {line['unit']} {line['description']} "
        f"@ {line['unit_price']} = {line['amount']}"
        for line in invoice["lines"]
    )
    tax = (
        f"{invoice['tax_label']}: not applied — no rate configured, so this total excludes it."
        if invoice["tax_excluded"]
        else f"{invoice['tax_label']}: {format_money(invoice['tax_cents'], invoice['currency'])}"
    )
    return (
        f"{invoice['number']} for {invoice['customer']} ({invoice['status']}):\n{lines}\n"
        f"  Subtotal: {format_money(invoice['subtotal_cents'], invoice['currency'])}\n"
        f"  {tax}\n"
        f"  Total: {format_money(invoice['total_cents'], invoice['currency'])}\n"
        f"Saved in the money pack. It is a draft unless its status says otherwise."
    )


def _save_draft(invoice: Any) -> str | None:
    """Write the draft into the money pack. The record id is the invoice number.

    The number is allocated by the same store sequence either way, so passing it as the record id
    cannot produce a second number: `RecordBook.save` moves the counter past an id the caller
    supplies (the internal audit K14). Lines are separate records pointing at the header,
    which is what the kernel's flat field kinds allow and what makes a line correctable on its
    own.

    Returns the invoice number when it was written, and None when this install has nowhere to
    write it — the caller says which of the two happened.
    """
    book = _book()
    if book is None:
        return None
    # Every quantity is converted *before* the header is written. The conversion used to happen
    # inside the line loop, so a quantity the float conversion could not take raised an
    # `OverflowError` after the number had been consumed and the header stored — an orphan record
    # with the invoice number burnt (the internal security audit A19-PLUG-5).
    try:
        quantities = [_saveable_quantity(line.quantity) for line in invoice.lines]
    except RecordBookError as exc:
        _STATE["save_error"] = str(exc)
        return None
    try:
        book.save(
            "invoice",
            {
                "number": invoice.number,
                "customer": invoice.customer_name,
                "date": invoice.issued_on.isoformat() if invoice.issued_on else "",
                "status": invoice.status,
                "currency": invoice.currency,
                "tax_label": invoice.tax_label,
                "subtotal_cents": invoice.subtotal_cents,
                "tax_cents": invoice.tax_cents,
                "total_cents": invoice.total_cents,
                "notes": invoice.notes,
            },
            record_id=invoice.number,
        )
        for position, line in enumerate(invoice.lines, start=1):
            book.save(
                "invoice_line",
                {
                    "invoice": invoice.number,
                    "position": position,
                    "description": line.description,
                    "quantity": quantities[position - 1],
                    "unit": line.unit,
                    "unit_price_cents": line.unit_price_cents,
                    "amount_cents": line.amount_cents,
                },
            )
    except (RecordBookError, StoreError) as exc:
        # The draft is still shown; what failed is the saving, and saying so is the honest half.
        _STATE["save_error"] = str(exc)
        return None
    _STATE["save_error"] = None
    return invoice.number


def _saveable_quantity(value: Any) -> float:
    """One line quantity as the record stores it, or a `RecordBookError` saying why not."""
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError, ZeroDivisionError) as exc:
        raise RecordBookError(f"the quantity {value!r} cannot be written: {exc}") from exc


def _handle_invoice_create(args: dict, **_: Any) -> str:
    if (refusal := _switched_off()) is not None:
        return refusal
    customer = str(args.get("customer") or "").strip()
    raw_lines = args.get("lines") or []
    if not customer:
        return "I need to check one thing before I bill this. Which customer is this invoice for?"
    if not raw_lines:
        return "I need to check one thing before I bill this. What should I put on the invoice?"

    requested: list[tuple[str, Any, str | None]] = []
    for raw in raw_lines:
        if not isinstance(raw, dict):
            continue
        item = str(raw.get("item") or "").strip()
        # A quantity the model did not extract is a question, not a one. The schema marks it
        # required, so this only fires when something has already gone wrong — and defaulting
        # to 1 puts a price on a line the operator never asked for
        # (the internal audit PLUG-9).
        if raw.get("quantity") is None or raw.get("quantity") == "":
            return (
                "I need to check one thing before I bill this. How many "
                f"{item or 'of those'} should I put on the invoice?"
            )
        problem = _quantity_problem(raw["quantity"])
        if problem is not None:
            # Nothing has been read, reserved or written at this point: the refusal comes before
            # the ledger and before the store (the internal security audit A19-PLUG-5).
            return f"I need to check one thing before I bill this. {item or 'That line'}: {problem}"
        requested.append(
            (
                item,
                raw["quantity"],
                (str(raw["unit"]).strip() or None) if raw.get("unit") else None,
            )
        )
    if not requested:
        return "I need to check one thing before I bill this. What should I put on the invoice?"

    try:
        invoice = _ledger().create_draft(customer, requested, notes=str(args.get("notes") or ""))
    except (Ambiguous, Unknown, UnitMismatch, QuantityMustBePositive) as exc:
        return _question(exc)
    except LedgerError as exc:
        return f"I couldn't build that invoice: {exc}"
    except PriceBookError as exc:
        return f"I can't reach the price book: {exc}"
    except (ValueError, KeyError, OverflowError, ZeroDivisionError) as exc:
        # The last two are the shapes a hostile number takes on its way through the ledger: the
        # quantity check above refuses them first, and this is the backstop that keeps either from
        # leaving as a traceback (the internal security audit A19-PLUG-5).
        return f"I couldn't build that invoice: {exc}"

    lines = "\n".join(
        f"  • {line.quantity_text()} {line.unit} {line.description} "
        f"@ {invoice.money(line.unit_price_cents)} = {invoice.money(line.amount_cents)}"
        for line in invoice.lines
    )
    tax = (
        f"{invoice.tax_label}: not applied — no rate configured, so this total excludes it."
        if invoice.tax_excluded
        else f"{invoice.tax_label}: {invoice.money(invoice.tax_cents)}"
    )
    ledger = _ledger()
    saved = _save_draft(invoice)
    if saved is not None:
        durability = (
            f"Saved as {saved} in the money pack, so it survives a restart and the number will "
            "not be issued again."
        )
    elif ledger.numbers_are_durable:
        durability = (
            "The number is reserved in the record store, so it will not be issued again — but "
            "the money pack is not loaded, so the draft itself is in this conversation's memory. "
            "Add `packs/money` to packs_dir to keep it."
        )
    else:
        durability = (
            "No record store is configured, so this number is not reserved: restarting the "
            f"gateway would issue {invoice.number} again, and the draft would go with it."
        )
    message = (
        f"Draft {invoice.number} for {invoice.customer_name}:\n{lines}\n"
        f"  Subtotal: {invoice.money(invoice.subtotal_cents)}\n  {tax}\n"
        f"  Total: {invoice.money(invoice.total_cents)}\n"
        f"It is a draft and has not been sent. Sending is not built yet. {durability}"
    )
    return json.dumps(
        {
            "success": True,
            "message": message,
            "saved": saved is not None,
            **({"save_error": _STATE["save_error"]} if _STATE.get("save_error") else {}),
            "invoice": {
                "number": invoice.number,
                "customer": invoice.customer_name,
                "currency": invoice.currency,
                "status": invoice.status,
                "tax_excluded": invoice.tax_excluded,
                "tax_label": invoice.tax_label,
                "subtotal_cents": invoice.subtotal_cents,
                "tax_cents": invoice.tax_cents,
                "total_cents": invoice.total_cents,
                # The rendered text as well as the cents: the kernel owns money formatting, and
                # a second implementation in the shell is how two renderings start to differ.
                "subtotal": invoice.money(invoice.subtotal_cents),
                "tax": None if invoice.tax_excluded else invoice.money(invoice.tax_cents),
                "total": invoice.money(invoice.total_cents),
                "lines": [
                    {
                        "quantity": line.quantity_text(),
                        "unit": line.unit,
                        "description": line.description,
                        "unit_price": invoice.money(line.unit_price_cents),
                        "amount": invoice.money(line.amount_cents),
                    }
                    for line in invoice.lines
                ],
            },
            "note": (
                "A draft, and nothing has been sent. Read the figures back to the operator; do "
                "not recalculate them."
            ),
        },
        default=str,
    )


def _handle_invoice_show(args: dict, **_: Any) -> str:
    """The same shape as `invoice_create`: `success`, `message`, and the draft when there is one.

    A question and a not-found are `success: false` with the sentence the model should say, so a
    caller never has to decide whether prose is an answer or a refusal
    (the internal audit PLUG-15).
    """
    if (refusal := _switched_off()) is not None:
        return json.dumps({"success": False, "message": refusal, "refusal": refusal})
    number = str(args.get("number") or "").strip()
    if not number:
        message = "Which invoice number should I show?"
        return json.dumps({"success": False, "message": message, "question": message})

    stored = _stored_invoice(number)
    if stored is not None:
        return json.dumps(
            {
                "success": True,
                "message": _stored_summary(stored),
                "saved": True,
                "invoice": stored,
            },
            default=str,
        )

    invoice = _ledger().invoices.get(number)
    if invoice is None:
        known = ", ".join(sorted(_ledger().invoices)) or "none yet"
        message = f"I don't have an invoice {number}. Drafts so far: {known}."
        return json.dumps({"success": False, "message": message, "question": message})
    return json.dumps(
        {
            "success": True,
            "message": invoice.summary(),
            "invoice": {
                "number": invoice.number,
                "customer": invoice.customer_name,
                "currency": invoice.currency,
                "status": invoice.status,
                "tax_excluded": invoice.tax_excluded,
                "tax_label": invoice.tax_label,
                "subtotal_cents": invoice.subtotal_cents,
                "tax_cents": invoice.tax_cents,
                "total_cents": invoice.total_cents,
                # The rendered text as well as the cents: the kernel owns money formatting, and
                # a second implementation in the shell is how two renderings start to differ.
                "subtotal": invoice.money(invoice.subtotal_cents),
                "tax": None if invoice.tax_excluded else invoice.money(invoice.tax_cents),
                "total": invoice.money(invoice.total_cents),
                "lines": [
                    {
                        "quantity": line.quantity_text(),
                        "unit": line.unit,
                        "description": line.description,
                        "unit_price": invoice.money(line.unit_price_cents),
                        "amount": invoice.money(line.amount_cents),
                    }
                    for line in invoice.lines
                ],
            },
        },
        default=str,
    )


_TOOLS: tuple[tuple[str, dict, Callable[..., str], str], ...] = (
    ("invoice_create", _CREATE_SCHEMA, _handle_invoice_create, "🧾"),
    ("invoice_show", _SHOW_SCHEMA, _handle_invoice_show, "🔎"),
)


def register(ctx: Any) -> None:
    _STATE["ctx"] = ctx
    for name, schema, handler, emoji in _TOOLS:
        ctx.register_tool(name=name, toolset=TOOLSET, schema=schema, handler=handler, emoji=emoji)
