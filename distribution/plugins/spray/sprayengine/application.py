"""Turning what was said into an application record: the arithmetic, and the refusals.

Every number on the record is computed here, from the catalogue's operator-entered facts and the
words the operator used. Two rules shape the whole module:

* **Nothing is assumed about a withholding period.** If the input record has one, it is copied onto
  the application and the earliest safe harvest is dated from it. If it does not, the field is left
  empty and a warning says so — because an assistant that supplies a plausible number for a label
  fact is the failure this product exists to avoid (the skills and plugins notes §2.6).
* **The record freezes what it was given.** The withholding period is copied, not referenced, so a
  later edit to the input cannot rewrite what the rule was on the day of spraying.

The result is shaped like the `application` record in `packs/farm/pack.toml` — the tool result *is*
the record (invariant 2), and the shell renders it without knowing what a spray is.
"""

from __future__ import annotations

from datetime import date as _date, timedelta
from fractions import Fraction

from pantler_core import Ambiguous, Unknown
from pantler_core.units import convert, resolve_unit

from .catalogue import AREA_RATE_UNITS, CONCENTRATION_RATE_UNITS, RATE_UNITS, SprayBook

#: Each rate unit this module knows, as `(canonical base, how many base units one of it is)`.
#: A rate applied in `mL/ha` and a maximum recorded in `L/ha` are the same quantity, and comparing
#: their unit *strings* meant the conversion never happened and the label maximum was never
#: checked: 25,000 mL/ha — 25 L/ha — sailed past a 2.0 L/ha ceiling
#: (the internal security audit A19-PLUG-4). The bases are per hectare for area rates and
#: per 100 L for concentration rates, which is the split `RATE_UNITS` already makes.
_RATE_BASES: dict[str, tuple[str, Fraction]] = {
    "L/ha": ("L/ha", Fraction(1)),
    "mL/ha": ("L/ha", Fraction(1, 1000)),
    "kg/ha": ("kg/ha", Fraction(1)),
    "g/ha": ("kg/ha", Fraction(1, 1000)),
    "mL/100L": ("mL/100L", Fraction(1)),
    "g/100L": ("g/100L", Fraction(1)),
}

#: The largest magnitude this module will put on a record. A JSON `1e400` is an infinity, a
#: 400-digit integer overflows the float conversion in `_number`, and `"1/0"` is not a number at
#: all — all three used to leave as an `OverflowError` or a `ZeroDivisionError` rather than a
#: refusal (the internal security audit A19-PLUG-5). No rate or area a business could mean
#: comes within orders of magnitude of this.
_MAX_MAGNITUDE = Fraction(10 ** 12)


def record_application(
    book: SprayBook,
    *,
    applied: str,
    block: str,
    product: str,
    rate: float | str,
    rate_unit: str,
    area_ha: float | str | None = None,
    operator: str = "",
    notes: str = "",
    today: _date | None = None,
) -> dict:
    """Compute one application record, or explain what must be settled first.

    `today` exists so "yesterday" can be tested without freezing the clock.
    """
    warnings: list[str] = []
    questions: list[str] = []

    applied_date = _parse_date(applied, today)
    if applied_date is None:
        return _refused(
            f"I could not read {applied!r} as a date. Say the day, or 'today' or 'yesterday'."
        )

    try:
        the_block = book.resolve_block(block)
    except (Unknown, Ambiguous) as exc:
        return _refused(exc.as_question())
    try:
        the_input = book.resolve_input(product)
    except (Unknown, Ambiguous) as exc:
        return _refused(exc.as_question())

    if rate_unit not in RATE_UNITS:
        return _refused(
            f"{rate_unit!r} is not a rate unit I know. Use one of: {', '.join(RATE_UNITS)}."
        )
    try:
        the_rate = Fraction(str(rate))
    except (ValueError, ZeroDivisionError, OverflowError, TypeError):
        return _refused(f"I could not read {rate!r} as a rate. What rate was applied?")
    if abs(the_rate) > _MAX_MAGNITUDE:
        # Bounded before any arithmetic: this is the shape `1e400` takes on its way to `_number`,
        # which converts to a float and raises `OverflowError`
        # (the internal security audit A19-PLUG-5).
        return _refused(
            f"{rate!r} is not a rate anyone applied. What rate was actually applied?"
        )
    if the_rate <= 0:
        # A negative rate produced a negative "product used" on a compliance record, and a zero
        # one recorded nothing applied. The kernel refuses a non-positive invoice quantity for
        # the same reason (the internal audit PLUG-11).
        return _refused(
            f"A rate has to be more than nothing, and {_number(the_rate)} {rate_unit} is not. "
            f"What rate was actually applied?"
        )

    area = _fraction_or_none(area_ha) if area_ha not in (None, "") else _fraction_or_none(
        the_block.area_ha
    )
    asked_for_area = False
    if area is not None and area <= 0:
        questions.append(
            f"An area has to be more than nothing, and {_number(area)} ha is not. How many "
            f"hectares was {the_block.name} treated over?"
        )
        area = None
        asked_for_area = True  # one question, not two about the same missing number
    if area is None and not asked_for_area:
        questions.append(
            f"How many hectares was {the_block.name} treated over? {the_block.name} has no area "
            f"on file, and without one I cannot work out how much product was used."
        )
    elif area_ha in (None, "") and the_block.area_ha is not None:
        warnings.append(
            f"No area was given, so I used {the_block.name}'s area on file "
            f"({_number(Fraction(str(the_block.area_ha)))} ha)."
        )

    used = _product_used(the_input, the_rate, rate_unit, area, warnings)

    if the_input.max_rate is not None:
        ceilings = _ceiling_check(the_input, the_rate, rate_unit, warnings)
        if ceilings:
            questions.append(ceilings)

    withholding = the_input.withholding_days
    earliest = None
    if withholding is None:
        warnings.append(
            f"No withholding period is on file for {the_input.name}, so the record leaves it "
            f"empty. Read it off the label and add it to the input record — I will not supply one."
        )
    else:
        earliest = (applied_date + timedelta(days=withholding)).isoformat()

    if rate_unit in CONCENTRATION_RATE_UNITS:
        warnings.append(
            f"{rate_unit} is a concentration rate, so it says nothing about total product used "
            f"without the spray volume. The rate is recorded as given."
        )

    record = {
        "date": applied_date.isoformat(),
        "block": the_block.id,
        "block_name": the_block.name,
        "input": the_input.id,
        "input_name": the_input.name,
        "rate": _number(the_rate),
        "rate_unit": rate_unit,
        "area_ha": None if area is None else _number(area),
        "operator": operator.strip(),
        "withholding_days": withholding,
        "earliest_safe_date": earliest,
        "notes": notes.strip(),
    }
    return {
        "success": True,
        "record_type": "application",
        "record": record,
        "product_used": used,
        "registration": the_input.registration,
        "re_entry_hours": the_input.re_entry_hours,
        "summary": _summary(record, used, the_input),
        "warnings": warnings,
        "questions": questions,
    }


def _product_used(product, rate: Fraction, rate_unit: str, area: Fraction | None, warnings) -> dict | None:
    """`rate × area`, expressed in the unit the product is sold in. None when it cannot be."""
    if rate_unit in CONCENTRATION_RATE_UNITS:
        return None
    if area is None:
        return None
    amount = rate * area
    unit = rate_unit.split("/")[0]
    target = product.unit or unit
    if unit != target:
        try:
            amount = convert(amount, resolve_unit(unit), resolve_unit(target))
        except Exception:
            warnings.append(
                f"The rate is in {unit} and {product.name} is sold by {target}; I have recorded "
                f"the rate as given and cannot express the total in {target}."
            )
            return {"amount": _number(amount), "unit": unit}
    return {"amount": _number(amount), "unit": target}


def _ceiling_check(product, rate: Fraction, rate_unit: str, warnings) -> str | None:
    """Compare the rate with the label maximum on file — like dimensions only, never a clamp."""
    if not product.max_rate_unit:
        # A maximum with no unit is not a maximum in the rate's unit: comparing them invented a
        # ceiling (500 g/ha against `max_rate: 2.5` warned "2.5 g/ha") and, worse, could pass a
        # rate the label does not allow (the internal audit PLUG-12).
        warnings.append(
            f"{product.name} has a maximum rate on file with no unit beside it, so I cannot "
            f"compare it with {_number(rate)} {rate_unit}. Recorded as given — check the label."
        )
        return None
    declared = Fraction(str(product.max_rate))
    applied = _comparable(rate, rate_unit)
    ceiling = _comparable(declared, product.max_rate_unit)
    if applied is None or ceiling is None or applied[0] != ceiling[0]:
        # A genuine dimension mismatch — a mass rate against a volume one, or a per-100 L
        # concentration against a per-hectare rate. There is no conversion to hide behind, and
        # inventing one is how a ceiling stops meaning anything
        # (the internal security audit A19-PLUG-4).
        warnings.append(
            f"{product.name} has a maximum rate on file in {product.max_rate_unit}, and this was "
            f"applied in {rate_unit}; I cannot compare the two, so I have not."
        )
        return None
    if rate_unit != product.max_rate_unit:
        # Compatible, but spelt differently: say that the comparison happened and in what terms,
        # so a reader is not looking for a warning that never came.
        warnings.append(
            f"{product.name}'s maximum is recorded in {product.max_rate_unit} and this was "
            f"applied in {rate_unit}; the two are the same kind of rate, so I compared them after "
            f"converting ({_number(applied[1])} {applied[0]} against "
            f"{_number(ceiling[1])} {ceiling[0]})."
        )
    if applied[1] > ceiling[1]:
        warnings.append(
            f"The rate given ({_number(rate)} {rate_unit}) is above the maximum on file for "
            f"{product.name} ({_number(declared)} {product.max_rate_unit or rate_unit}). "
            f"Recorded as given — check the label."
        )
        return (
            f"{_number(rate)} {rate_unit} is above the label maximum on file for "
            f"{product.name}. Is that the rate that was actually applied?"
        )
    return None


def _comparable(rate: Fraction, unit: str) -> tuple[str, Fraction] | None:
    """`(canonical base, rate in that base)`, or None when the unit is not one this module knows."""
    entry = _RATE_BASES.get(unit)
    if entry is None:
        return None
    base, factor = entry
    return base, rate * factor


def _summary(record: dict, used: dict | None, product) -> str:
    parts = [
        f"{record['input_name']} at {record['rate']} {record['rate_unit']} "
        f"on {record['block_name']} ({record['date']})"
    ]
    if used:
        parts.append(f"{used['amount']} {used['unit']} used")
    if record["earliest_safe_date"]:
        parts.append(
            f"earliest safe harvest {record['earliest_safe_date']} "
            f"({record['withholding_days']} days from the label)"
        )
    else:
        parts.append("no withholding period on file, so no earliest safe date")
    if product.registration:
        parts.append(f"label: {product.registration}")
    return "; ".join(parts) + "."


def _refused(question: str) -> dict:
    return {"success": False, "question": question, "warnings": [], "questions": [question]}


# The words an operator actually uses for a day. Resolving them here rather than in the model keeps
# the arithmetic in one place: "yesterday" is a subtraction, and a subtraction is exactly what a
# language model should not be doing on a compliance record.
_RELATIVE_DAYS = {
    "today": 0,
    "this morning": 0,
    "this afternoon": 0,
    "yesterday": -1,
    "last night": -1,
    "the day before yesterday": -2,
}


def _parse_date(value: str, today: _date | None = None) -> _date | None:
    text = " ".join(str(value).split()).casefold().rstrip(".")
    if text in _RELATIVE_DAYS:
        return (today or _date.today()) + timedelta(days=_RELATIVE_DAYS[text])
    try:
        return _date.fromisoformat(text)
    except (TypeError, ValueError):
        return None


def _fraction_or_none(value) -> Fraction | None:
    if value is None or value == "":
        return None
    try:
        number = Fraction(str(value))
    except (ValueError, ZeroDivisionError, OverflowError, TypeError):
        return None
    if abs(number) > _MAX_MAGNITUDE:
        # None reads as "no area given", so the caller asks for the hectares rather than recording
        # an infinity: a JSON `1e400` reached `_number` and left as an `OverflowError`
        # (the internal security audit A19-PLUG-5).
        return None
    return number


def _number(value: Fraction) -> float | int:
    """A JSON-friendly number: an int when the fraction is whole, else a rounded float."""
    if value.denominator == 1:
        return int(value)
    try:
        return round(float(value), 4)
    except OverflowError:
        # A backstop, not a path: every rate and area is bounded before it gets here. `float`
        # cannot hold the value and the integer part can, so the record still serialises rather
        # than the handler seeing a traceback (the internal security audit A19-PLUG-5).
        return int(value)
