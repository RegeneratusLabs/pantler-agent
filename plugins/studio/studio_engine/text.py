"""Text measurement and the line breaks that make a card look composed.

Every headline on a card is set by choosing a size and a split, and both are arithmetic. The
default a model reaches for — one long line, or a narrow column that wraps into six — is what makes
a card read as a slide someone typed into. So the split is searched rather than left to the
renderer: a balanced two- or three-line headline, no single word stranded on the last line, and a
measured refusal when the words cannot be set legibly at all.

Widths come from `fonts.Face`, never from a renderer, so the SVG and the PNG agree to the pixel.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field

from .fonts import Face

#: A line of display type below this is a poster nobody can read at arm's length.
MIN_DISPLAY_PX = 24


@dataclass
class Fitted:
    """The result of fitting a string into a box: what to draw and whether it actually fits."""

    lines: list[str]
    size: float
    fits: bool
    overflow: float = 0.0
    widows: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def widest(self) -> float:
        return self.overflow


def width(text: str, face: Face, size: float, tracking: float = 0.0) -> float:
    return face.width(text, size, tracking)


def largest_fitting(
    text: str,
    face: Face,
    max_width: float,
    max_size: float,
    min_size: float,
    tracking: float = 0.0,
) -> float:
    """The largest size at which `text` sits on one line, or the floor."""
    raw = face.size_for_width(text, max_width, tracking)
    return max(min_size, min(max_size, raw))


def wrap(text: str, face: Face, size: float, max_width: float, tracking: float = 0.0) -> list[str]:
    """Greedy wrap. Used for body copy, where even lines are not worth a search."""
    words = text.split()
    if not words:
        return []
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if width(candidate, face, size, tracking) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _splits(count: int, parts: int) -> list[tuple[int, ...]]:
    if parts <= 1:
        return [()]
    return list(itertools.combinations(range(1, count), parts - 1))


def _lines_for(words: list[str], cuts: tuple[int, ...]) -> list[str]:
    boundaries = (0, *cuts, len(words))
    return [" ".join(words[start:end]) for start, end in zip(boundaries, boundaries[1:])]


def balanced(
    text: str,
    face: Face,
    max_width: float,
    max_size: float,
    min_size: float,
    max_lines: int = 3,
    tracking: float = 0.0,
    step: float = 2.0,
) -> Fitted:
    """The best size and split: big enough to carry the card, few enough lines to read as one idea.

    The search scores every split at every size. A size term rewards presence; a line term and an
    orphan penalty punish the three-line stack with a single word at the end that a greedy wrapper
    produces. On a 1080 card "Local veggie boxes" comes out as two lines at about 130 px rather
    than three at 153 — which is the difference between a poster and a paragraph.
    """
    words = text.split()
    if not words:
        return Fitted(lines=[], size=min_size, fits=True)

    size = max_size
    best: tuple[float, Fitted] | None = None
    while size >= min_size:
        for parts in range(1, min(max_lines, len(words)) + 1):
            for cuts in _splits(len(words), parts):
                lines = _lines_for(words, cuts)
                widths = [width(line, face, size, tracking) for line in lines]
                if any(value > max_width for value in widths):
                    continue
                spread = (max(widths) - min(widths)) / max_width
                orphan = 1 if (len(lines) > 1 and len(lines[-1].split()) == 1) else 0
                short_last = 1 if (len(lines) > 1 and widths[-1] < widths[0] * 0.5) else 0
                score = (
                    (size / max_size)
                    - 0.12 * (len(lines) - 1)
                    - 0.16 * orphan
                    - 0.05 * short_last
                    - 0.04 * spread
                )
                if best is None or score > best[0]:
                    best = (
                        score,
                        Fitted(
                            lines=lines,
                            size=size,
                            fits=True,
                            overflow=max(0.0, max(widths) - max_width),
                            widows=bool(orphan),
                        ),
                    )
        if best is not None and (size / max_size) < best[0] - 0.2:
            break
        size -= step

    if best is not None:
        return best[1]

    # Nothing fits even at the floor: set it at the floor and let the audit refuse it. Refusing to
    # render is the caller's decision; this layer says exactly how far past the edge it is.
    return Fitted(
        lines=wrap(text, face, min_size, max_width, tracking),
        size=min_size,
        fits=False,
        overflow=width(text, face, min_size, tracking) - max_width,
        notes=["does not fit at the minimum legible size"],
    )


def fit_lines(
    lines: list[str],
    face: Face,
    max_width: float,
    max_size: float,
    min_size: float,
    tracking: float = 0.0,
) -> Fitted:
    """Shrink a fixed set of lines until the widest fits. For list items, prices and footers."""
    if not lines:
        return Fitted(lines=[], size=min_size, fits=True)
    size = max_size
    while size > min_size:
        widths = [width(line, face, size, tracking) for line in lines]
        if max(widths) <= max_width:
            return Fitted(lines=lines, size=size, fits=True)
        size -= 1
    widths = [width(line, face, size, tracking) for line in lines]
    return Fitted(
        lines=lines,
        size=min_size,
        fits=max(widths) <= max_width,
        overflow=max(0.0, max(widths) - max_width),
    )


def char_positions(text: str, face: Face, size: float, tracking: float = 0.0) -> list[tuple[str, float]]:
    """Each character and the x offset it starts at, for tracked labels.

    Tracked capitals are set letter by letter rather than as one string: a browser and Pillow
    disagree by a fraction of a pixel on word spacing, and a label that drifts is a label that
    looks hand-assembled.
    """
    positions: list[tuple[str, float]] = []
    cursor = 0.0
    for index, char in enumerate(text):
        positions.append((char, cursor))
        glyph = face.cmap.get(ord(char))
        advance = face.advances[glyph] if glyph is not None and glyph < len(face.advances) else 0
        cursor += advance * size / face.units_per_em
        if index < len(text) - 1:
            cursor += tracking * size
    return positions


def missing_glyphs(text: str, face: Face) -> list[str]:
    """Characters the face cannot draw. A name in a script the font lacks is a question, not tofu."""
    return sorted({char for char in text if ord(char) not in face.cmap and not char.isspace()})


def title_case_guard(text: str) -> list[str]:
    """Report words that look like a product name shouted or a stray capital, not to rewrite them."""
    notes: list[str] = []
    words = text.split()
    upper = [word for word in words if len(word) > 3 and word.isupper() and not word.isdigit()]
    if len(upper) > 2:
        notes.append("more than two all-capital words; the headline may read as shouting")
    return notes
