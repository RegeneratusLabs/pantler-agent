"""Errors the ledger raises instead of guessing.

Invariant 1 of the design notes: low confidence becomes a question, never a guess. Every
resolution failure in this package is one of these, and every one carries enough
structure for the assistant to ask a precise question rather than a vague one.
"""

from __future__ import annotations

from typing import Sequence


class LedgerError(Exception):
    """Base class for every refusal this package makes."""


class Unknown(LedgerError):
    """Nothing matched the operator's words."""

    def __init__(self, kind: str, query: str, known: Sequence[str] = ()):
        self.kind = kind
        self.query = query
        self.known = tuple(known)
        super().__init__(f"no {kind} matches {query!r}")

    def as_question(self) -> str:
        article = "an" if self.kind[:1].lower() in "aeiou" else "a"
        if not self.known:
            return f"I don't have {article} {self.kind} called {self.query!r}."
        listing = ", ".join(self.known[:12])
        more = "" if len(self.known) <= 12 else f" (and {len(self.known) - 12} more)"
        return (
            f"I don't have {article} {self.kind} called {self.query!r}. "
            f"Known {self.kind}s: {listing}{more}."
        )


class Ambiguous(LedgerError):
    """More than one thing matched. The operator must choose; we never pick."""

    def __init__(self, kind: str, query: str, candidates: Sequence[str], ask: Sequence[str] = ()):
        self.kind = kind
        self.query = query
        self.candidates = tuple(candidates)
        self._ask = tuple(ask) or self.candidates
        super().__init__(f"{len(self.candidates)} {kind}s match {query!r}")

    def as_question(self) -> str:
        options = "; ".join(f"{a} ({b})" for a, b in zip(self._ask, self.candidates))
        return f"{self.query!r} could be more than one {self.kind} — which did you mean: {options}?"


class UnitMismatch(LedgerError):
    """A quantity was given in a unit that cannot measure this item."""

    def __init__(self, item: str, given: str, expected: str, dimension: str):
        self.item = item
        self.given = given
        self.expected = expected
        self.dimension = dimension
        super().__init__(f"{item} is sold by {expected}, not {given}")

    def as_question(self) -> str:
        return (
            f"{self.item} is sold by {self.expected}, so I can't bill it in {self.given}. "
            f"How many {self.expected}?"
        )


class QuantityMustBePositive(LedgerError):
    """A line was asked for with nothing — or less than nothing — on it.

    A structured refusal rather than the bare `ValueError` this used to be, because the
    assistant has to be able to *ask*: "how many?" is a question, and a question is this
    package's answer to an input it cannot use (the internal audit K7).
    """

    def __init__(self, item: str, quantity: object):
        self.item = item
        self.quantity = quantity
        super().__init__(f"a quantity for {item} has to be more than nothing, got {quantity!r}")

    def as_question(self) -> str:
        return (
            f"I can't bill {self.item} for {self.quantity!r}. How many should I put on the line?"
        )
