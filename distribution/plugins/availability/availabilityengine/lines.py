"""Turning a spoken line into an item phrase, a quantity and a unit — deterministically.

This is the half of the prior art that was worth keeping: code reads *what was said* and says what
it could not read, and the model never does the arithmetic or the matching. The rules are
deliberately narrow. A number word, a digit, a fraction, a unit the kernel knows — and everything
else is left as spoken and flagged, because a list that quietly drops "a few punnets of rocket" is
worse than one that shows it with a question beside it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from fractions import Fraction

from pantler_core import Unknown
from pantler_core.units import normalize, resolve_unit

# Spelled numbers up to twenty, the tens, and the halves an operator actually says out loud.
_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
    "eighty": 80, "ninety": 90,
}
_HALF = {"half": Fraction(1, 2), "half a": Fraction(1, 2)}

#: The largest quantity a spoken line may carry. A digit string longer than this is not something a
#: farm said — it is a number built to overflow the float conversion in `build._number`, which is
#: how a hostile line escaped the tool as an `OverflowError`
#: (the internal security audit A19-PLUG-5). A quantity beyond it stays in the item text as
#: spoken and the line is asked about, rather than being silently dropped.
MAX_QUANTITY = Fraction(10 ** 9)
_APPROXIMATE = {
    "a few", "a couple", "couple", "some", "a bit", "a handful", "handful", "plenty",
    "lots", "a lot", "several", "a dozen or so",
}
_NUMBER = r"(?:\d+(?:\.\d+)?|" + "|".join(sorted(_WORDS, key=len, reverse=True)) + r"|half)"
# The `and a half` is *named* so the reader can tell it apart from the number itself: it is the
# tail of a mixed number, and the quantity is one half more than the number it follows.
_PATTERN = re.compile(
    rf"(?P<qty>{_NUMBER})(?P<fraction>\s+and\s+a\s+half)?\s*(?P<unit>[A-Za-z]{{1,12}})?\b",
    re.I,
)
# "3 and a", "two and a": a `half` right after one of these belongs to that number and is not a
# half by itself. `_MIXED_NUMBER` decides whether the half-branch below may claim it.
_MIXED_NUMBER_TAIL = re.compile(r"(?:\d+(?:\.\d+)?|[A-Za-z]+)\s+and\s+a\s*$", re.I)
_FRACTION_PATTERN = re.compile(r"\bhalf\s+(?:a\s+)?(?P<unit>[A-Za-z]{1,12})\b", re.I)


@dataclass(frozen=True)
class SpokenLine:
    """One line as it was said, plus what could be read out of it."""

    raw: str
    item_text: str
    quantity: Fraction | None = None
    unit: str = ""
    approximate: str = ""

    @property
    def has_quantity(self) -> bool:
        return self.quantity is not None


def parse_line(raw: str) -> SpokenLine:
    """Read a quantity and a unit out of one spoken line, and keep the rest as the item."""
    text = " ".join(str(raw).split()).strip(" .;,")
    if not text:
        return SpokenLine(raw=str(raw), item_text="")

    approximate = ""
    for phrase in sorted(_APPROXIMATE, key=len, reverse=True):
        if re.search(rf"\b{re.escape(phrase)}\b", text, re.I):
            approximate = phrase
            text = re.sub(rf"\b{re.escape(phrase)}\b", " ", text, flags=re.I)
            break

    quantity: Fraction | None = None
    unit = ""
    remainder = text

    half = _FRACTION_PATTERN.search(text)
    if (
        half is not None
        and _known_unit(half.group("unit"))
        and not _MIXED_NUMBER_TAIL.search(text[: half.start()])
    ):
        quantity, unit = Fraction(1, 2), _unit_code(half.group("unit"))
        remainder = text[: half.start()] + " " + text[half.end() :]
    else:
        match = _PATTERN.search(text)
        if match is not None:
            word = match.group("qty").casefold()
            value = _WORDS.get(word)
            if value is not None:
                quantity = Fraction(value)
            elif word == "half":
                quantity = Fraction(1, 2)
            else:
                quantity = Fraction(word)
            tail = text[match.end() :]
            if match.group("fraction"):
                # The pattern already swallowed it: "3 and a half punnets" is three and a half,
                # not three. Reading only the tail meant this branch never fired for the phrasing
                # it was written for, and the half-branch above then claimed the "half" and
                # discarded the three (the internal audit PLUG-3).
                quantity += Fraction(1, 2)
            elif re.match(r"\s*and\s+a\s+half\b", tail, re.I):
                quantity += Fraction(1, 2)
                tail = re.sub(r"^\s*and\s+a\s+half\b", "", tail, flags=re.I)
            spoken_unit = (match.group("unit") or "").strip()
            if spoken_unit and _known_unit(spoken_unit):
                unit = _unit_code(spoken_unit)
            elif spoken_unit and not _known_unit(spoken_unit):
                # The word after the number is part of the item ("12 cherry tomatoes") or a unit
                # nobody knows ("12 punnets-ish"). Either way, the number is a count of something
                # and the word stays with the item.
                tail = f"{spoken_unit} {tail}"
            remainder = text[: match.start()] + " " + tail

    if quantity is not None and abs(quantity) > MAX_QUANTITY:
        # A digit string no farm could mean. It is left in the item text as spoken and the line
        # becomes a question about the quantity, which is the list's own refusal shape; converting
        # it in `build._number` would raise `OverflowError` out of the tool
        # (the internal security audit A19-PLUG-5). Nothing is dropped.
        quantity, unit, remainder = None, "", text

    # A bare unit word with no number in front of it — "punnets of rocket" — is still the unit,
    # and it is lifted only at the *start* of the line: an item can end in a unit word ("Mixed
    # Salad Box"), so a trailing one stays where it is rather than being eaten.
    if unit == "":
        leading = re.match(r"^(?P<unit>[A-Za-z]{1,12})\s+(?:of\s+)?(?P<rest>.+)$", remainder.strip())
        if leading is not None and _known_unit(leading.group("unit")):
            unit = _unit_code(leading.group("unit"))
            remainder = leading.group("rest")

    item = _clean(remainder)
    if not item:
        item = _clean(text)
    return SpokenLine(
        raw=str(raw).strip(),
        item_text=item,
        quantity=quantity,
        unit=unit,
        approximate=approximate,
    )


def _clean(text: str) -> str:
    """The item as it was spoken, less the preposition the parse left in front of it.

    It used to strip `of|the|some|fresh|ready|new` *anywhere*, which renamed the operator's
    product: "fresh farm eggs" became "farm eggs", "new potatoes" became "potatoes", and "ready
    to eat salad" became "to eat salad", which then matched nothing in their catalogue
    (the internal audit PLUG-16). An adjective is part of a name, and a name is what the
    catalogue is searched with.
    """
    cleaned = re.sub(r"^(?:of|the)\s+", "", text.strip(), flags=re.I)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .,;:-")
    return cleaned


def _known_unit(word: str) -> bool:
    try:
        resolve_unit(word)
    except Unknown:
        return False
    return True


def _unit_code(word: str) -> str:
    try:
        return resolve_unit(word).code
    except Unknown:
        return normalize(word)
