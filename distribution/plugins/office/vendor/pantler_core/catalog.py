"""The price book: customers, items and the deterministic rules that resolve them.

Resolution is deliberately dumb and total. Tiers are tried in a fixed order and the
first tier that produces any match decides: exactly one match is the answer, more
than one is an :class:`Ambiguous` the assistant must ask about, none falls through to
the next tier. There is no scoring and no similarity threshold, so the same words
always produce the same answer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence

from .errors import Ambiguous, Unknown
from .units import UNITS, Unit, normalize


@dataclass(frozen=True)
class Customer:
    id: str
    name: str
    aliases: tuple[str, ...] = ()
    email: str = ""
    terms_days: int = 14

    def keys(self) -> Iterable[str]:
        yield normalize(self.id)
        yield normalize(self.name)
        for a in self.aliases:
            yield normalize(a)


@dataclass(frozen=True)
class Item:
    id: str
    name: str
    unit: str  # the unit this price is quoted in
    unit_price_cents: int
    aliases: tuple[str, ...] = ()

    @property
    def price_unit(self) -> Unit:
        return UNITS[self.unit]

    def keys(self) -> Iterable[str]:
        yield normalize(self.id)
        yield normalize(self.name)
        for a in self.aliases:
            yield normalize(a)


def _resolve(
    kind: str, query: str, entries: Sequence, display, ident
) -> object:
    """Resolve *query* against *entries* by the fixed tier order. Never guesses."""
    q = normalize(query)
    if not q:
        raise Unknown(kind, query, [display(e) for e in entries])

    for key in ("id", "name", "alias"):
        hits = []
        for e in entries:
            keys = list(e.keys())
            if key == "id" and keys and keys[0] == q:
                hits.append(e)
            elif key == "name" and len(keys) > 1 and keys[1] == q:
                hits.append(e)
            elif key == "alias" and q in keys[2:]:
                hits.append(e)
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            raise Ambiguous(kind, query, [ident(h) for h in hits], [display(h) for h in hits])

    hits = [e for e in entries if any(k.startswith(q) for k in (normalize(e.name),))]
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        raise Ambiguous(kind, query, [ident(h) for h in hits], [display(h) for h in hits])

    hits = [e for e in entries if q in normalize(e.name).split()]
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        raise Ambiguous(kind, query, [ident(h) for h in hits], [display(h) for h in hits])

    raise Unknown(kind, query, [display(e) for e in sorted(entries, key=display)])


@dataclass
class PriceBook:
    """Every customer and price the business quotes from, plus the tax rate to apply.

    ``tax_rate_bp`` is basis points (1000 = 10.00%). It is ``None`` until a human
    configures it: the design notes forbids copying a rate from the web, and this package will
    not invent one.
    """

    currency: str = "AUD"
    tax_rate_bp: int | None = None
    tax_label: str = "GST"
    customers: list[Customer] = field(default_factory=list)
    items: list[Item] = field(default_factory=list)

    # -- resolution ---------------------------------------------------------

    def customer(self, query: str) -> Customer:
        return _resolve("customer", query, self.customers, lambda c: c.name, lambda c: c.id)

    def item(self, query: str) -> Item:
        return _resolve("item", query, self.items, lambda i: i.name, lambda i: i.id)

    def unit(self, query: str) -> Unit:
        from .units import resolve_unit

        return resolve_unit(query)

    # -- construction helpers ----------------------------------------------

    def add_customer(self, customer: Customer) -> Customer:
        self.customers.append(customer)
        return customer

    def add_item(self, item: Item) -> Item:
        self.items.append(item)
        return item
