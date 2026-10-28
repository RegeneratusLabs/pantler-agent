#!/usr/bin/env python3
"""Render a type-only card to an exact PNG size, with the layout checks printed.

This is the `design` skill's renderer. It is deliberately small and local: system fonts, a
flat ground, one ink and one accent, no network and no template engine. It covers the two
shapes most small-business posts need:

* a **day card** — a headline and one big line (`--day "Every Thursday"`);
* a **list card** — a headline and a short list of items.

Examples:

    python3 render_card.py --out output/design/boxes.png \
        --headline "Local veggie boxes" --day "Every Thursday"

    python3 render_card.py --out output/design/this-week.png \
        --eyebrow AVAILABILITY --headline "This week" \
        --items "Lettuce,Broccoli,Cauliflower" --footer "WEEK OF 19 OCTOBER"

    python3 render_card.py --out output/design/tall.png --size 1080x1350 \
        --headline "The first of the season" --day "At the market Saturday"

The palette is a neutral starter, not the operator's brand. Pass their ink, ground and accent
when they have them. The script prints every measurement it asserted and exits non-zero if one
fails; read the PNG back with `vision_analyze` before handing it over.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

#: Neutral starter colours. Ink on this ground is 14.0:1; an operator's palette replaces it.
CREAM = "#F7F3EA"
INK = "#1F2933"
ACCENT = "#B4552D"

#: Faces, best first. A product machine may have Lato, DejaVu or Liberation; Windows has Arial.
_FACE_CANDIDATES = {
    "black": (
        "Lato-Black.ttf",
        "DejaVuSans-Bold.ttf",
        "LiberationSans-Bold.ttf",
        "Arial Bold.ttf",
        "arialbd.ttf",
    ),
    "bold": (
        "Lato-Bold.ttf",
        "DejaVuSans-Bold.ttf",
        "LiberationSans-Bold.ttf",
        "Arial Bold.ttf",
        "arialbd.ttf",
    ),
    "medium": (
        "Lato-Medium.ttf",
        "DejaVuSans.ttf",
        "LiberationSans-Regular.ttf",
        "Arial.ttf",
        "arial.ttf",
    ),
}

_FONT_DIRS = (
    "/usr/share/fonts/truetype/lato",
    "/usr/share/fonts/truetype/dejavu",
    "/usr/share/fonts/truetype/liberation",
    "/usr/local/share/fonts",
    "/Library/Fonts",
    "/System/Library/Fonts",
    "C:/Windows/Fonts",
)


class RenderError(RuntimeError):
    """A layout or palette problem the caller has to fix before the card can ship."""


def _parse_colour(text: str) -> tuple[int, int, int]:
    value = text.strip().lstrip("#")
    if len(value) != 6:
        raise RenderError(f"{text!r} is not a six-digit hex colour")
    try:
        return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError as exc:
        raise RenderError(f"{text!r} is not a six-digit hex colour") from exc


def _luminance(rgb: tuple[int, int, int]) -> float:
    def channel(value: int) -> float:
        c = value / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = rgb
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    first, second = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (first + 0.05) / (second + 0.05)


def _font_file(role: str, font_dir: str | None = None) -> Path:
    roots = [Path(font_dir).expanduser()] if font_dir else []
    roots.extend(Path(directory) for directory in _FONT_DIRS)
    for directory in roots:
        for name in _FACE_CANDIDATES[role]:
            candidate = directory / name
            if candidate.is_file():
                return candidate
    raise RenderError(
        "no usable font found. Pass --font-dir with a directory containing Lato, DejaVu or "
        "Liberation; do not download a font at render time."
    )


class Face:
    """A font file and the sizes rendered from it."""

    def __init__(self, path: Path):
        self.path = path

    def at(self, size: int) -> ImageFont.FreeTypeFont:
        return ImageFont.truetype(str(self.path), size)


def _measure(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> float:
    return draw.textlength(text, font=font)


def _tracked(
    draw: ImageDraw.ImageDraw,
    xy: tuple[float, float],
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: tuple[int, int, int],
    tracking: float,
) -> float:
    x, y = xy
    for char in text:
        draw.text((x, y), char, font=font, fill=fill)
        x += draw.textlength(char, font=font) + tracking
    return x - tracking - xy[0]


def _tracked_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, tracking: float) -> float:
    return sum(draw.textlength(char, font=font) + tracking for char in text) - tracking


def _fit(
    draw: ImageDraw.ImageDraw,
    face: Face,
    text: str,
    max_width: float,
    start: int,
    floor: int,
    step: int = 2,
) -> tuple[ImageFont.FreeTypeFont, int]:
    size = start
    while size > floor:
        font = face.at(size)
        if _measure(draw, text, font) <= max_width:
            return font, size
        size -= step
    return face.at(floor), floor


def _wrap_balanced(
    draw: ImageDraw.ImageDraw,
    face: Face,
    text: str,
    max_width: float,
    start: int,
    floor: int,
) -> tuple[list[str], ImageFont.FreeTypeFont, int]:
    """One or two measured lines; on a tie the longer line goes first."""
    font, size = _fit(draw, face, text, max_width, start, floor)
    if _measure(draw, text, font) <= max_width:
        return [text], font, size
    words = text.split()
    best: list[str] | None = None
    best_key: tuple[float, int] | None = None
    probe = face.at(start)
    for index in range(1, len(words)):
        lines = [" ".join(words[:index]), " ".join(words[index:])]
        first = _measure(draw, lines[0], probe)
        second = _measure(draw, lines[1], probe)
        key = (abs(first - second), 0 if first >= second else 1)
        if best_key is None or key < best_key:
            best, best_key = lines, key
    if best is None:
        return [text], font, size
    size = start
    while size > floor:
        candidate = face.at(size)
        if max(_measure(draw, line, candidate) for line in best) <= max_width:
            return best, candidate, size
        size -= 2
    return best, face.at(floor), floor


def _blocks(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    eyebrow: str,
    headline: str,
    footer: str,
    ink: tuple[int, int, int],
    accent: tuple[int, int, int],
    hair: tuple[int, int, int],
    margin: int,
    font_dir: str | None,
) -> dict:
    content_width = width - 2 * margin
    eyebrow_face = Face(_font_file("bold", font_dir)).at(26)
    footer_face = Face(_font_file("bold", font_dir)).at(24)
    headline_face = Face(_font_file("black", font_dir))

    lines, headline_font, headline_size = _wrap_balanced(
        draw, headline_face, headline, content_width, 148, 80
    )
    ascent, descent = headline_font.getmetrics()
    line_height = ascent + descent
    pitch = line_height + 6

    top = margin
    if eyebrow:
        _tracked(draw, (margin, top), eyebrow.upper(), eyebrow_face, ink, 4.6)
    headline_top = top + (eyebrow_face.size + 36 if eyebrow else 0)
    for index, line in enumerate(lines):
        draw.text((margin - 5, headline_top + index * pitch), line, font=headline_font, fill=ink)
    headline_bottom = headline_top + (len(lines) - 1) * pitch + line_height
    rule_one = headline_bottom + 38
    draw.rectangle([margin, rule_one, width - margin, rule_one + 3], fill=accent)

    footer_y = height - margin - footer_face.size - 4
    rule_two = footer_y - 40
    draw.rectangle([margin, rule_two, width - margin, rule_two + 1], fill=hair)
    footer_width = (
        _tracked(draw, (margin, footer_y), footer.upper(), footer_face, ink, 4.2) if footer else 0
    )

    return {
        "width": width,
        "height": height,
        "content_width": content_width,
        "margin": margin,
        "headline_font": headline_font,
        "headline_size": headline_size,
        "lines": lines,
        "rule_one": rule_one,
        "rule_two": rule_two,
        "footer_y": footer_y,
        "footer_width": footer_width,
        "footer_face": footer_face,
        "band_top": rule_one + 3,
        "band_bottom": rule_two,
    }


def render(
    *,
    out: str | Path,
    headline: str,
    day: str | None = None,
    items: list[str] | tuple[str, ...] = (),
    eyebrow: str = "",
    footer: str = "",
    size: tuple[int, int] = (1080, 1080),
    ground: str = CREAM,
    ink: str = INK,
    accent: str = ACCENT,
    margin: int | None = None,
    font_dir: str | None = None,
) -> bool:
    """Render one card and print every check. Returns False if any check failed."""
    width, height = size
    if width < 320 or height < 320:
        raise RenderError("the card must be at least 320 pixels on each side")
    if day and items:
        raise RenderError("choose one band: --day for a schedule card, or --items for a list")
    if not day and not items:
        raise RenderError("nothing to put in the band: pass --day or --items")

    ground_rgb = _parse_colour(ground)
    ink_rgb = _parse_colour(ink)
    accent_rgb = _parse_colour(accent)
    ratio = contrast(ink_rgb, ground_rgb)
    if ratio < 4.5:
        raise RenderError(
            f"ink on ground is {ratio:.2f}:1; a card needs at least 4.5:1. "
            "Choose a darker ink or a lighter ground."
        )
    margin = margin if margin is not None else max(44, round(min(width, height) * 0.102))
    hair = tuple(round((a + b) / 2) for a, b in zip(ground_rgb, ink_rgb))

    image = Image.new("RGB", (width, height), ground_rgb)
    draw = ImageDraw.Draw(image)
    geometry = _blocks(
        draw, width, height, eyebrow, headline, footer, ink_rgb, accent_rgb, hair, margin, font_dir
    )

    checks: list[tuple[str, bool]] = []
    content_width = geometry["content_width"]
    rule_one = geometry["rule_one"]
    rule_two = geometry["rule_two"]

    widest_headline = max(_measure(draw, line, geometry["headline_font"]) for line in geometry["lines"])
    checks.append(
        (
            f"headline {geometry['lines']} at {geometry['headline_size']}px, widest "
            f"{widest_headline:.0f} <= {content_width}",
            widest_headline <= content_width,
        )
    )

    if day:
        day_face = Face(_font_file("black", font_dir))
        day_font, day_size = _fit(draw, day_face, day, content_width, 96, 44)
        ascent, descent = day_font.getmetrics()
        day_height = ascent + descent
        gap = (rule_two - (rule_one + 3) - day_height) / 2
        day_y = rule_one + 3 + gap
        draw.text((margin - 4, day_y), day, font=day_font, fill=ink_rgb)
        day_width = _measure(draw, day, day_font)
        top_gap = day_y - (rule_one + 3)
        bottom_gap = rule_two - (day_y + day_height)
        checks.extend(
            [
                (f"day {day!r} at {day_size}px, width {day_width:.0f} <= {content_width}", day_width <= content_width),
                (
                    f"gap rule->day {top_gap:.1f} == gap day->rule {bottom_gap:.1f}",
                    abs(top_gap - bottom_gap) <= 1,
                ),
            ]
        )
    else:
        rows = list(items)
        list_top = rule_one + 3 + 42
        list_bottom = rule_two - 42
        pitch = (list_bottom - list_top) / len(rows)
        item_face = Face(_font_file("medium", font_dir))
        item_font: ImageFont.FreeTypeFont | None = None
        item_size = 0
        for candidate in range(52, 29, -2):
            font = item_face.at(candidate)
            ascent, descent = font.getmetrics()
            clearance = (pitch - (ascent + descent)) / 2 - 1
            widest = max(_measure(draw, row, font) for row in rows)
            if clearance >= 8 and margin + widest <= width - margin:
                item_font, item_size = font, candidate
                break
        if item_font is None:
            raise RenderError(
                f"{len(rows)} rows do not fit between the rules at any workable size "
                f"(pitch {pitch:.1f}px); shorten the list or the footer"
            )
        ascent, descent = item_font.getmetrics()
        text_height = ascent + descent
        for index, row in enumerate(rows):
            row_top = list_top + pitch * index
            if index:
                draw.rectangle([margin, int(row_top) - 1, width - margin, int(row_top)], fill=hair)
            baseline = row_top + (pitch - text_height) / 2 + ascent * 0.06
            draw.text((margin, baseline), row, font=item_font, fill=ink_rgb)
        first_top = list_top + (pitch - text_height) / 2
        last_bottom = list_top + pitch * (len(rows) - 1) + (pitch - text_height) / 2 + text_height
        widest_item = max(_measure(draw, row, item_font) for row in rows)
        checks.extend(
            [
                (f"list rows {len(rows)} at {item_size}px", item_size > 0),
                (
                    f"gap rule->first text {first_top - (rule_one + 3):.1f} == gap last text->rule "
                    f"{rule_two - last_bottom:.1f}",
                    abs((first_top - (rule_one + 3)) - (rule_two - last_bottom)) <= 1,
                ),
                (
                    f"hairline clearance {(pitch - text_height) / 2 - 1:.1f} >= 8",
                    (pitch - text_height) / 2 - 1 >= 8,
                ),
                (f"widest item edge {margin + widest_item:.0f} <= {width - margin}", margin + widest_item <= width - margin),
            ]
        )

    checks.extend(
        [
            (f"size {width}x{height}", image.size == (width, height)),
            (f"contrast ink on ground {ratio:.2f}:1 >= 4.5", ratio >= 4.5),
            (
                f"footer width {geometry['footer_width']:.0f} <= {content_width}",
                geometry["footer_width"] <= content_width,
            ),
            (
                f"footer inside margin (bottom {geometry['footer_y'] + geometry['footer_face'].size} "
                f"<= {height - margin + 2})",
                geometry["footer_y"] + geometry["footer_face"].size <= height - margin + 2,
            ),
        ]
    )

    out_path = Path(out).expanduser()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path)

    print(f"wrote {out_path}")
    for label, ok in checks:
        print(f"  {'ok  ' if ok else 'FAIL'} {label}")
    print("  read the PNG back and confirm every word appears exactly as the operator wrote it")
    return all(ok for _, ok in checks)


def _parse_size(text: str) -> tuple[int, int]:
    value = text.lower().replace(" ", "")
    if "x" not in value:
        raise argparse.ArgumentTypeError("--size must be WIDTHxHEIGHT, e.g. 1080x1350")
    first, _, second = value.partition("x")
    try:
        width, height = int(first), int(second)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("--size must be WIDTHxHEIGHT, e.g. 1080x1350") from exc
    return width, height


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", required=True, help="PNG path, e.g. output/design/boxes.png")
    parser.add_argument("--headline", required=True)
    parser.add_argument("--day", default=None, help="one big line instead of a list")
    parser.add_argument("--items", default="", help="comma-separated list rows")
    parser.add_argument("--eyebrow", default="")
    parser.add_argument("--footer", default="")
    parser.add_argument("--size", type=_parse_size, default=(1080, 1080))
    parser.add_argument("--ground", default=CREAM)
    parser.add_argument("--ink", default=INK)
    parser.add_argument("--accent", default=ACCENT)
    parser.add_argument("--margin", type=int, default=None)
    parser.add_argument("--font-dir", default=None)
    args = parser.parse_args(argv)
    items = [item.strip() for item in args.items.split(",") if item.strip()]
    try:
        ok = render(
            out=args.out,
            headline=args.headline,
            day=args.day or None,
            items=items,
            eyebrow=args.eyebrow,
            footer=args.footer,
            size=args.size,
            ground=args.ground,
            ink=args.ink,
            accent=args.accent,
            margin=args.margin,
            font_dir=args.font_dir,
        )
    except RenderError as exc:
        print(f"render_card: {exc}", file=sys.stderr)
        return 2
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
