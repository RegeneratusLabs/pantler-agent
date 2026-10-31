"""Assembling the list: resolve each line against the catalogue, keep what did not match.

Two decisions shape this module, and both come from the prior art
(the skills and plugins notes §2.6) rather than from taste:

* **The list is unpriced.** Availability is what the operator has, not what it costs. Putting a
  price beside a line turns a field walk into a quotation, and a quotation is a different document
  with different rules. This module never reads `unit_price_cents`, and the tool says so.
* **Nothing is dropped.** An item nobody matched is kept exactly as it was said, flagged, and
  offered for promotion into the catalogue later. Silently dropping "a few punnets of rocket"
  because the catalogue calls it "Rocket" is how a customer turns up for something that is not
  there — and the reverse, a list that omits it, is how a sale is lost without anybody noticing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction

from pantler_core import Ambiguous, PriceBook, Unknown

from .lines import SpokenLine, parse_line


@dataclass
class ListLine:
    """One line of the list: what was said, what it resolved to, and what is unresolved."""

    raw: str
    spoken_item: str
    status: str  # matched | unmatched | ambiguous | empty
    item_id: str = ""
    item_name: str = ""
    quantity: Fraction | None = None
    unit: str = ""
    catalogue_unit: str = ""
    candidates: tuple[str, ...] = ()
    notes: list[str] = field(default_factory=list)

    def display(self) -> str:
        """The customer-facing line: what it is and how much, with no price anywhere."""
        name = self.item_name or self.spoken_item or self.raw
        quantity = ""
        if self.quantity is not None:
            amount = _number(self.quantity)
            quantity = f"{amount} {self.unit}".strip()
        return f"{name} — {quantity}" if quantity else f"{name} — quantity to confirm"


def build_list(
    book: PriceBook,
    lines: list[str],
    *,
    title: str = "",
    include_unmatched: bool = True,
) -> dict:
    """Resolve spoken lines into a list, with the questions and the gaps made visible."""
    built: list[ListLine] = []
    questions: list[str] = []
    warnings: list[str] = []

    for raw in lines:
        spoken = parse_line(raw)
        if not spoken.item_text:
            built.append(ListLine(raw=spoken.raw, spoken_item="", status="empty"))
            continue
        line = _resolve(book, spoken)
        if line.status == "ambiguous":
            questions.append(
                f"{spoken.item_text!r} could be more than one catalogue item — which did you "
                f"mean: {'; '.join(line.candidates)}?"
            )
        elif line.status == "unmatched":
            line.notes.append(
                "Not in the catalogue. Kept on the list as spoken — add it to the price book to "
                "price it later."
            )
        if line.quantity is None:
            line.notes.append(
                "No quantity was said. Ask before this goes out: a list without a quantity is a "
                "promise the operator has not made."
            )
        if not line.unit and line.catalogue_unit:
            line.unit = line.catalogue_unit
        built.append(line)

    usable = [line for line in built if line.status in ("matched", "unmatched")]
    if not include_unmatched:
        usable = [line for line in usable if line.status == "matched"]
        if len(usable) != len([b for b in built if b.status in ("matched", "unmatched")]):
            warnings.append("Unmatched items were left off at the caller's request.")

    return {
        "success": True,
        "priced": False,
        "title": title or "Availability",
        "lines": [
            {
                "said": line.raw,
                "item": line.item_name or line.spoken_item,
                "item_id": line.item_id,
                "status": line.status,
                "quantity": None if line.quantity is None else _number(line.quantity),
                "unit": line.unit,
                "candidates": list(line.candidates),
                "notes": line.notes,
                "display": line.display(),
            }
            for line in built
        ],
        "list": [line.display() for line in usable],
        "counts": {
            "said": len(built),
            "matched": len([line for line in built if line.status == "matched"]),
            "unmatched": len([line for line in built if line.status == "unmatched"]),
            "ambiguous": len([line for line in built if line.status == "ambiguous"]),
            "without_quantity": len([line for line in built if line.quantity is None]),
        },
        "questions": questions,
        "warnings": warnings,
        "note": (
            "This list carries no prices by design: availability is what the operator has, not "
            "what it costs. Nothing was dropped — unmatched items are kept as spoken so the "
            "operator can promote them into the catalogue."
        ),
    }


def _resolve(book: PriceBook, spoken: SpokenLine) -> ListLine:
    try:
        item = book.item(spoken.item_text)
    except Ambiguous as exc:
        return ListLine(
            raw=spoken.raw,
            spoken_item=spoken.item_text,
            status="ambiguous",
            quantity=spoken.quantity,
            unit=spoken.unit,
            candidates=tuple(exc.candidates),
        )
    except Unknown:
        return ListLine(
            raw=spoken.raw,
            spoken_item=spoken.item_text,
            status="unmatched",
            quantity=spoken.quantity,
            unit=spoken.unit,
        )
    line = ListLine(
        raw=spoken.raw,
        spoken_item=spoken.item_text,
        status="matched",
        item_id=item.id,
        item_name=item.name,
        quantity=spoken.quantity,
        unit=spoken.unit,
        catalogue_unit=item.unit,
    )
    if spoken.unit and spoken.unit != item.unit:
        line.notes.append(
            f"Said in {spoken.unit}; the catalogue lists this by {item.unit}. Left as said — "
            f"converting it is a tool's job, and the customer is reading the list."
        )
    if spoken.approximate:
        line.notes.append(
            f"Approximate ({spoken.approximate!r}): the quantity is as said, not a count."
        )
    return line


def _number(value: Fraction) -> float | int:
    """A JSON-friendly quantity.

    Quantities are bounded in `lines.parse_line` before they reach here, so the float conversion
    cannot overflow. The guard is for a caller that hands `build_list` its own `Fraction`: a
    number too large for a float must not turn the whole list into a traceback
    (the internal security audit A19-PLUG-5).
    """
    if value.denominator == 1:
        return int(value)
    try:
        return round(float(value), 3)
    except OverflowError:
        return int(value)
