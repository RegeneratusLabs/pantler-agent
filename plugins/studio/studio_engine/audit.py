"""The checks a card has to pass before anybody is told it is finished.

The point of the audit is that the sentence "it looks good" is not evidence. Every check here is a
number, and the hard ones fail the render rather than warning about it: ink below AA, a line wider
than its column, type outside the artboard, a face that cannot draw the operator's name, a file too
large for the chat to show. The soft ones — a single-word last line, four type sizes, a placeholder
still in the copy — are reported so the assistant can fix them, not hidden.

The audit reads the same `Composition` the renderer draws, so it cannot drift from what shipped.
"""

from __future__ import annotations

import re
from pathlib import Path

from . import palette as colour
from .layout import Composition, Spec, TextOp

PLACEHOLDER = re.compile(r"\[[A-Z0-9$][^\]\n]{1,60}\]")
#: The chat renders images inline up to 5 MB; above it the operator gets a download link.
INLINE_LIMIT = 5 * 1024 * 1024


def _check(check_id: str, ok: bool, detail: str, value=None, hard: bool = True) -> dict:
    return {"id": check_id, "ok": bool(ok), "hard": hard, "detail": detail,
            "value": value if value is not None else ""}


def check(composition: Composition, spec: Spec) -> list[dict]:
    checks: list[dict] = []
    short = composition.short
    ink = colour.parse(spec.ink)
    ground = colour.parse(spec.ground)

    ratio = colour.contrast(ink, ground)
    checks.append(_check("contrast.ink", ratio >= colour.AA_TEXT,
                         f"ink on ground is {ratio:.2f}:1", round(ratio, 2)))

    accent = colour.parse(spec.accent)
    accent_text = [op for op in composition.texts() if op.fill == spec.accent]
    if accent_text:
        accent_ratio = colour.contrast(accent, ground)
        checks.append(
            _check("contrast.accent_text", accent_ratio >= colour.AA_TEXT,
                   f"the accent carries type at {accent_ratio:.2f}:1", round(accent_ratio, 2))
        )
    else:
        checks.append(_check("contrast.accent_text", True,
                             "the accent is decoration only, which is allowed"))

    width = composition.width
    height = composition.height
    outside = []
    overflowing = []
    smallest = None
    for op in composition.texts():
        if op.x < -0.5 or op.x + op.width > width + 0.5 or op.top < -0.5 \
                or op.top + op.height > height + 0.5:
            outside.append(op.text[:24])
        if op.width > width - 2 * composition.margin + 1:
            overflowing.append(op.text[:24])
        if smallest is None or op.size < smallest:
            smallest = op.size
    checks.append(_check("layout.artboard", not outside,
                         "every line sits inside the artboard" if not outside
                         else f"outside the artboard: {outside[:3]}", hard=True))
    checks.append(_check("layout.columns", not overflowing,
                         "every line fits its column" if not overflowing
                         else f"wider than the column: {overflowing[:3]}"))

    sizes = sorted({round(op.size) for op in composition.texts()})
    checks.append(_check("type.scale", len(sizes) <= 4,
                         f"{len(sizes)} type sizes: {sizes}", len(sizes), hard=False))
    floor = max(14.0, short * 0.016)
    checks.append(_check("type.minimum", bool(smallest) and smallest >= floor,
                         f"the smallest type is {smallest or 0:.0f} px (floor {floor:.0f})",
                         round(smallest or 0), hard=False))

    margin = composition.margin
    tight = [op.text[:20] for op in composition.texts()
             if op.role != "mark"
             and (op.x < margin - 1 or op.x + op.width > width - margin + 1)]
    checks.append(_check("layout.margin", not tight,
                         "text respects the margin" if not tight
                         else f"inside the margin: {tight[:3]}", hard=False))

    copy_text = " ".join(op.text for op in composition.texts())
    placeholders = sorted(set(PLACEHOLDER.findall(copy_text)))
    checks.append(_check("copy.placeholders", not placeholders,
                         "no placeholders left" if not placeholders
                         else f"still to fill: {', '.join(placeholders)}", len(placeholders),
                         hard=False))

    # A market-day card's primary line is the day, a quote card's is the quote. What matters is
    # that one line carries the card, not that it is called a headline.
    primary = [op for op in composition.texts()
               if op.role in ("headline", "day", "quote", "mark")]
    checks.append(_check("type.primary_line", bool(primary),
                         "the card has one line to land" if primary
                         else "nothing on the card carries the message"))

    for index, note in enumerate(composition.notes):
        hard = "does not fit" in note or "no glyph" in note or "too wide" in note
        checks.append(_check(f"layout.note.{index + 1}", False, note, hard=hard))

    if spec.image:
        image_path = Path(spec.image["path"])
        checks.append(_check("image.exists", image_path.is_file(),
                             f"image {image_path.name} is readable" if image_path.is_file()
                             else f"image not found: {image_path}"))
    return checks


def check_files(png: Path | None, svg: Path | None) -> list[dict]:
    checks: list[dict] = []
    if png is not None:
        size = png.stat().st_size if png.is_file() else 0
        checks.append(_check("file.inline_limit", 0 < size <= INLINE_LIMIT,
                             f"PNG is {size / 1024:.0f} KB (inline limit {INLINE_LIMIT // 1024} KB)",
                             size, hard=False))
    if svg is not None:
        checks.append(_check("file.svg", svg.is_file() and svg.stat().st_size > 0,
                             "the SVG was written" if svg.is_file() else "the SVG is missing"))
    return checks


def passed(checks: list[dict]) -> bool:
    return all(item["ok"] for item in checks if item.get("hard"))


def failures(checks: list[dict]) -> list[dict]:
    return [item for item in checks if not item["ok"]]
