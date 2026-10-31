"""Units and exact quantity arithmetic.

Quantities are ``Fraction`` so that "half a kilo" and "four dozen" stay exact until
the single rounding step at the invoice line. Prices are integer cents everywhere;
this module never produces a float.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from .errors import Unknown, UnitMismatch


@dataclass(frozen=True)
class Unit:
    """A unit of measure, expressed as a multiple of its dimension's base unit."""

    code: str
    name: str
    dimension: str
    per_base: Fraction  # how many base units one of this unit is worth
    aliases: tuple[str, ...] = ()

    def to_base(self, quantity: Fraction) -> Fraction:
        return quantity * self.per_base

    def from_base(self, quantity: Fraction) -> Fraction:
        return quantity / self.per_base


_UNIT_LIST = (
    Unit("kg", "kilogram", "mass", Fraction(1), ("kilo", "kilos", "kilogram", "kilograms", "kg")),
    Unit("g", "gram", "mass", Fraction(1, 1000), ("gram", "grams", "g")),
    Unit("t", "tonne", "mass", Fraction(1000), ("tonne", "tonnes", "ton", "tons", "t")),
    Unit("each", "each", "count", Fraction(1), ("each", "ea", "unit", "units", "piece", "pieces")),
    Unit("dozen", "dozen", "count", Fraction(12), ("dozen", "dozens", "dz")),
    Unit("punnet", "punnet", "count", Fraction(1), ("punnet", "punnets", "pnt")),
    Unit("bunch", "bunch", "count", Fraction(1), ("bunch", "bunches", "bnch")),
    Unit("box", "box", "count", Fraction(1), ("box", "boxes", "carton", "cartons")),
    Unit("L", "litre", "volume", Fraction(1), ("litre", "litres", "liter", "liters", "l")),
    Unit("mL", "millilitre", "volume", Fraction(1, 1000), ("millilitre", "millilitres", "ml")),
)

UNITS: dict[str, Unit] = {u.code: u for u in _UNIT_LIST}

_BY_WORD: dict[str, Unit] = {}
for _u in _UNIT_LIST:
    _BY_WORD[_u.code.casefold()] = _u
    for _a in _u.aliases:
        _BY_WORD[_a.casefold()] = _u


def normalize(text: str) -> str:
    """One normalisation for every lookup in this package. Casefold, collapse spaces."""
    return " ".join(str(text).split()).casefold()


def resolve_unit(text: str) -> Unit:
    """Resolve a spoken unit word to a :class:`Unit`, or raise :class:`Unknown`."""
    key = normalize(text).rstrip(".")
    if key in _BY_WORD:
        return _BY_WORD[key]
    raise Unknown("unit", text, sorted({u.code for u in _UNIT_LIST}))


def convert(quantity: Fraction, frm: Unit, to: Unit) -> Fraction:
    """Convert between two units of the same dimension, exactly."""
    if frm.dimension != to.dimension:
        raise UnitMismatch(to.name, frm.code, to.code, frm.dimension)
    return to.from_base(frm.to_base(quantity))
