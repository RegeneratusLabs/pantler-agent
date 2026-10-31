"""Sequential ids, formatted in one place.

`INV-0001`, `BLK-0007`, `CERT-0012`: every pack's records and the money example's drafts are
numbered the same way, and the shape of that number is the interface between whatever allocated
it and whatever reads it. Two copies of the format string is how they stop agreeing — which is
what this module exists to prevent (it was `format_record_id`'s docstring before it was a
shared function). The *sequence* that supplies the number lives in the store; only the rendering
lives here.
"""

from __future__ import annotations

DEFAULT_WIDTH = 4


def format_sequential_id(prefix: str, number: int, *, width: int = DEFAULT_WIDTH) -> str:
    """``("INV", 1)`` → ``"INV-0001"``.

    A number wider than the padding is not truncated: `INV-10000` is what a busy year produces,
    and a five-digit invoice number that printed as four would collide with an earlier one.
    """
    return f"{prefix}-{number:0{width}d}"
