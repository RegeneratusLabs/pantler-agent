#!/usr/bin/env python3
"""Render the design library to a contact sheet, so somebody can look at all of it at once.

    scripts/design-gallery.py            # render to output/design/gallery
    scripts/design-gallery.py --check    # also fail if any card has a hard check failing
    scripts/design-gallery.py --out DIR

This is the proof that the library is not a set of half-working templates: every template is drawn
with real words, every direction is drawn against the same words, and the PNGs are laid on one sheet
for a human (or a vision model) to judge. It uses the studio engine directly, so it runs in the
repository without the engine process; the PNG step needs Pillow, and without it the SVGs are still
written and the sheet is skipped with a sentence.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "plugins" / "studio"
sys.path.insert(0, str(PLUGIN))

from studio_engine import audit, brand as brand_kit, layout, raster, render, svg, templates  # noqa: E402
from studio_engine.library import Library  # noqa: E402

#: One honest brief per template, the sort of thing an operator actually says.
CASES = [
    ("feed-square-day", "01-quiet-ledger",
     {"eyebrow": "Availability", "headline": "Local veggie boxes", "day": "Every Thursday",
      "footer": "BELLVIEW FARM · WEEK OF 19 OCTOBER"}),
    ("feed-square-list", "03-pantry-shelf",
     {"eyebrow": "This week", "headline": "What's ready",
      "items": ["Lettuce | 12", "Broccoli | 8", "Cauliflower | 6", "Silverbeet | 10"],
      "footer": "ORDER BY WEDNESDAY"}),
    ("portrait-availability", "08-produce-catalogue",
     {"eyebrow": "Availability", "headline": "This week at the market",
      "items": ["Lettuce | 12", "Broccoli | 8", "Cauliflower | 6", "Silverbeet | 10",
                "Kale | 5", "Radish | 4"], "footer": "WEEK OF 19 OCTOBER"}),
    ("story-announcement", "09-seasonal-almanac",
     {"eyebrow": "Now picking", "headline": "The first of the season",
      "day": "At the market Saturday", "footer": "BELLVIEW FARM"}),
    ("market-day", "06-bread-and-ledger",
     {"eyebrow": "Market day", "day": "Saturday", "time": "7am – 1pm",
      "venue": "Pomona markets", "headline": "Garlic, honey and preserves",
      "footer": "BELLVIEW FARM"}),
    ("quote-card", "04-long-table",
     {"eyebrow": "From a customer",
      "quote": "The best garlic I've cooked with all year — I've already ordered more.",
      "attribution": "M. Nguyen, regular since 2023", "footer": "BELLVIEW FARM"}),
    ("price-board", "11-apothecary",
     {"eyebrow": "Prices", "headline": "This week's list",
      "items": ["Hardneck garlic | $18/kg", "Honey 500g | $14", "Preserves | $12",
                "Eggs, dozen | $9"], "price_note": "Prices include GST · cash or card",
      "footer": "BELLVIEW FARM"}),
    ("carousel-cover", "16-paper-bag",
     {"eyebrow": "Three ways with garlic", "number": "01",
      "headline": "Start with the hardneck", "footer": "SWIPE"}),
    ("poster-a3", "06-bread-and-ledger",
     {"eyebrow": "Garlic season", "headline": "Hardneck, picked this week",
      "day": "At the market Saturday", "time": "7am – 1pm", "venue": "Pomona markets",
      "footer": "BELLVIEW FARM"}),
    ("sign-a3", "07-market-chalk",
     {"eyebrow": "Market day", "day": "Saturday", "time": "7am – 1pm",
      "venue": "Pomona markets", "headline": "Garlic, honey and preserves",
      "footer": "BELLVIEW FARM"}),
    ("menu-a4", "13-bistro-menu",
     {"eyebrow": "The stall", "headline": "This week",
      "items": ["Hardneck garlic | $18/kg", "Honey 500g | $14", "Preserves | $12",
                "Eggs, dozen | $9"], "price_note": "Prices include GST · cash or card",
      "footer": "BELLVIEW FARM"}),
    ("label-proof", "11-apothecary",
     {"eyebrow": "Label proof", "headline": "Bellview hardneck garlic", "footer": "BELLVIEW FARM"}),
]

#: The same words, drawn through every direction — the test of whether a library is a library.
DIRECTION_CASES = {
    "direction-{direction}": {"eyebrow": "The library", "headline": "One card, sixteen ways",
                              "day": "Every Thursday", "footer": "DIRECTIONS"}
}


def render_one(lib: Library, template: str, direction: str, content: dict, out: Path) -> dict:
    spec = {"template": template, "direction": direction, "content": content, "out": str(out)}
    report = render.job(spec, out.parent, lib)
    return report


def contact_sheet(images: list[tuple[str, Path]], out: Path, thumb: int = 420) -> None:
    from PIL import Image, ImageDraw, ImageFont

    columns = 3
    gap = 20
    label = 34
    rows = (len(images) + columns - 1) // columns
    width = columns * thumb + (columns + 1) * gap
    height = rows * (thumb + label) + (rows + 1) * gap
    sheet = Image.new("RGB", (width, height), (20, 22, 22))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype(str(PLUGIN / "fonts" / "Barlow-Medium.ttf"), 20)
    except Exception:  # pragma: no cover - a broken install
        font = ImageFont.load_default()
    for index, (name, path) in enumerate(images):
        row, column = divmod(index, columns)
        x = gap + column * (thumb + gap)
        y = gap + row * (thumb + label + gap)
        with Image.open(path) as source:
            image = source.convert("RGB")
            image.thumbnail((thumb, thumb), Image.LANCZOS)
        sheet.paste(image, (x, y))
        draw.text((x + 2, y + thumb + 8), name, font=font, fill=(236, 231, 222))
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, "PNG", optimize=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(ROOT / "output" / "design" / "gallery"))
    parser.add_argument("--check", action="store_true",
                        help="exit non-zero if any card fails a hard check")
    args = parser.parse_args()

    lib = Library(PLUGIN / "studio_engine" / "library")
    # Absolute, so `render.job` writes here rather than under its own workspace fallback.
    out = Path(args.out).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)

    results: list[dict] = []
    failures = 0
    for template_id, direction, content in CASES:
        report = render_one(lib, template_id, direction, content, out / template_id)
        results.append(report)
        if not report["ok"]:
            failures += 1
            print(f"FAIL {template_id}: {[c['id'] for c in report['failures']]}")

    for direction in lib.directions:
        template_id, content = next(iter(DIRECTION_CASES.items()))
        report = render_one(lib, "feed-square-list", direction,
                            {"headline": "One card, sixteen ways", "eyebrow": "The library",
                             "items": ["Quiet ledger", "Field notes", "Pantry shelf", "Long table"],
                             "footer": direction.upper()}, out / f"direction-{direction}")
        results.append(report)
        if not report["ok"]:
            failures += 1
            print(f"FAIL direction {direction}: {[c['id'] for c in report['failures']]}")

    pngs = [("card", Path(report["files"]["png"])) for report in results if report["files"]["png"]]
    if pngs and raster.available():
        contact_sheet(pngs, out / "contact-sheet.png")
        print(f"wrote {out / 'contact-sheet.png'}")
    else:
        print("no PNGs were produced; the SVGs are in the same directories")

    print(f"{len(results)} cards, {failures} with a hard check failing")
    return 1 if (args.check and failures) else 0


if __name__ == "__main__":
    raise SystemExit(main())
