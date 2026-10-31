"""The ledger: drafts, lines and totals, in integer cents.

This is the only place an amount is computed. Inputs are exact (``Fraction``
quantities, integer-cent prices) and there is exactly one rounding step, at the line
amount. Totals are sums of already-rounded lines, so a total always equals the sum of
what is printed on the document.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from fractions import Fraction
from typing import Callable, Sequence

from .catalog import Customer, Item, PriceBook
from .errors import LedgerError, QuantityMustBePositive
from .ids import format_sequential_id
from .units import convert


def round_half_up(value: Fraction) -> int:
    """Round an exact fraction to whole cents, halves away from zero."""
    sign = -1 if value < 0 else 1
    value = abs(value)
    whole, remainder = divmod(value.numerator, value.denominator)
    if 2 * remainder >= value.denominator:
        whole += 1
    return sign * whole


_SYMBOLS = {"AUD": "$", "NZD": "$", "USD": "$", "GBP": "£", "EUR": "€"}


def format_money(cents: int, currency: str = "AUD") -> str:
    symbol = _SYMBOLS.get(currency.upper(), "")
    body = f"{abs(cents) // 100:,}.{abs(cents) % 100:02d}"
    return f"{'-' if cents < 0 else ''}{symbol}{body}" + ("" if symbol else f" {currency.upper()}")


@dataclass(frozen=True)
class Line:
    item_id: str
    description: str
    quantity: Fraction  # in the item's pricing unit
    unit: str
    unit_price_cents: int
    amount_cents: int

    def quantity_text(self) -> str:
        q = self.quantity
        if q.denominator == 1:
            return str(q.numerator)
        return f"{float(q):g}"


@dataclass
class Invoice:
    number: str
    customer_id: str
    customer_name: str
    currency: str
    lines: list[Line] = field(default_factory=list)
    tax_rate_bp: int | None = None
    tax_label: str = "Tax"
    subtotal_cents: int = 0
    tax_cents: int = 0
    total_cents: int = 0
    tax_excluded: bool = False
    status: str = "draft"
    issued_on: date | None = None
    notes: str = ""

    def money(self, cents: int) -> str:
        return format_money(cents, self.currency)

    def summary(self) -> str:
        out = [f"{self.number} — {self.customer_name} ({self.status})"]
        for line in self.lines:
            out.append(
                f"  {line.quantity_text()} {line.unit} × {line.description} "
                f"@ {self.money(line.unit_price_cents)} = {self.money(line.amount_cents)}"
            )
        out.append(f"  Subtotal: {self.money(self.subtotal_cents)}")
        if self.tax_excluded:
            out.append(f"  {self.tax_label}: not applied (no rate configured)")
        else:
            rate = (self.tax_rate_bp or 0) / 100
            out.append(f"  {self.tax_label} ({rate:g}%): {self.money(self.tax_cents)}")
        out.append(f"  Total: {self.money(self.total_cents)}")
        return "\n".join(out)


class Ledger:
    """Holds the price book and the invoices written against it.

    The drafts live in memory: this is the worked example that proves the resolution rules, not
    the durable store. What it must not do is *number* them in memory — a counter that starts at
    1 again after a restart hands the same invoice number to a different invoice, which is a
    compliance problem rather than a cosmetic one (the internal backend audit §1.2). So a caller with
    a store passes `number_source`, and every number comes from the sequence that survives a
    restart. Without one, the counter is a fixture's counter and `numbers_are_durable` says so.
    """

    def __init__(
        self,
        price_book: PriceBook,
        *,
        invoice_prefix: str = "INV",
        next_number: int = 1,
        jurisdiction: str = "",
        number_source: Callable[[], str] | None = None,
    ):
        self.book = price_book
        self.invoice_prefix = invoice_prefix
        self._next = next_number
        self._number_source = number_source
        self.jurisdiction = jurisdiction
        self.invoices: dict[str, Invoice] = {}

    @property
    def numbers_are_durable(self) -> bool:
        """Whether this ledger's numbers survive the process. False is a fixture, not an install."""
        return self._number_source is not None

    def _number(self) -> str:
        if self._number_source is not None:
            return self._number_source()
        number = format_sequential_id(self.invoice_prefix, self._next)
        self._next += 1
        return number

    def create_draft(
        self,
        customer_query: str,
        requested: Sequence[tuple[str, Fraction | int | float | str, str | None]],
        *,
        notes: str = "",
        issued_on: date | None = None,
        tax_rate_bp: int | None = None,
    ) -> Invoice:
        """Resolve intent into a draft invoice, or raise with a precise question.

        ``requested`` is a sequence of ``(item, quantity, unit)`` triples exactly as the
        model extracted them. Every one of the three is resolved here, deterministically.
        """
        customer: Customer = self.book.customer(customer_query)
        rate = self.book.tax_rate_bp if tax_rate_bp is None else tax_rate_bp

        lines: list[Line] = []
        for item_query, raw_qty, unit_query in requested:
            item: Item = self.book.item(item_query)
            quantity = _as_fraction(raw_qty)
            if quantity <= 0:
                # A structured refusal, so the assistant asks "how many?" instead of saying it
                # could not build the invoice (the internal audit K7).
                raise QuantityMustBePositive(item.name, raw_qty)
            if unit_query:
                given = self.book.unit(unit_query)
                price_unit = item.price_unit
                if given.dimension != price_unit.dimension:
                    from .errors import UnitMismatch

                    raise UnitMismatch(item.name, given.code, price_unit.code, price_unit.dimension)
                quantity = convert(quantity, given, price_unit)
            amount = round_half_up(quantity * item.unit_price_cents)
            lines.append(
                Line(
                    item_id=item.id,
                    description=item.name,
                    quantity=quantity,
                    unit=item.unit,
                    unit_price_cents=item.unit_price_cents,
                    amount_cents=amount,
                )
            )

        subtotal = sum(line.amount_cents for line in lines)
        tax_excluded = rate is None
        tax = 0 if tax_excluded else round_half_up(Fraction(subtotal * rate, 10_000))

        invoice = Invoice(
            number=self._number(),
            customer_id=customer.id,
            customer_name=customer.name,
            currency=self.book.currency,
            lines=lines,
            tax_rate_bp=rate,
            tax_label=self.book.tax_label,
            subtotal_cents=subtotal,
            tax_cents=tax,
            total_cents=subtotal + tax,
            tax_excluded=tax_excluded,
            issued_on=issued_on,
            notes=notes,
        )
        # One number, one invoice. A plain assignment here meant a second record claiming an
        # existing number replaced the first in this mapping — the exact behaviour the store's
        # primary key was built to stop (store.py, `create`) — so the ledger refuses instead
        # (the internal security audit A19-KERN-8).
        if invoice.number in self.invoices:
            raise LedgerError(f"invoice number {invoice.number} has already been issued")
        self.invoices[invoice.number] = invoice
        return invoice


def _as_fraction(value: Fraction | int | float | str) -> Fraction:
    """A quantity as an exact fraction.

    A float is a decimal the caller meant — `0.5` is half a kilo, not the binary fraction
    nearest to it — so it is read back as the simplest fraction that matches to six decimal
    places. That is a deliberate, bounded rescue rather than a silent loss: the alternative is
    `Fraction(0.1)` being 3602879701896397/36028797018963968, which would print as
    `0.1000000000000000055511151231257827` on a document
    (the internal audit K8). A string is exact and preferred; the tools pass the model's
    words through as one wherever they can.
    """
    if isinstance(value, Fraction):
        return value
    if isinstance(value, str):
        return Fraction(value.strip())
    if isinstance(value, float):
        return Fraction(value).limit_denominator(1_000_000)
    return Fraction(value)
