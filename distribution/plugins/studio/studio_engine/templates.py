"""The card templates — composition, in code, against the operator's own words.

Each template is a function from a validated `Spec` to a `Composition`. They are deliberately few
and opinionated: one idea per card, the headline set by search rather than by wrapping, one accent,
a footer that always lands on the same optical line. A template that can hold anything is a template
that makes everything look the same.

What changes between a `day` card and a `list` card is where the eye goes second, not just which
words are dropped in. That is the whole difference between a designed card and a filled-in one.
"""

from __future__ import annotations

from . import layout as L
from . import palette as colour
from .library import Library
from .text import fit_lines, width


def _sizes(canvas: L.Canvas) -> dict[str, float]:
    return L.type_sizes(canvas)


def _header(canvas: L.Canvas, spec: L.Spec, library: Library, sizes: dict) -> float:
    """Eyebrow at the top-left, the business name at the top-right. Returns the y below it."""
    top = canvas.margin
    if spec.content.get("eyebrow"):
        L.label_line(spec, canvas, library, spec.content["eyebrow"], top, sizes["eyebrow"],
                     tracking=0.22)
    brand_name = str(spec.brand.get("name") or "").strip()
    if brand_name:
        face = spec.pairing.face_for("label", library.fonts)
        canvas.text_right(
            canvas.content_right,
            top,
            brand_name,
            face,
            sizes["small"],
            colour.to_hex(colour.mix(colour.parse(spec.ink), colour.parse(spec.ground), 0.25)),
            tracking=0.1,
            role="label",
        )
    return top + sizes["eyebrow"] * 1.25


def _footer(canvas: L.Canvas, spec: L.Spec, library: Library, sizes: dict, text: str) -> None:
    """A hairline and a tracked line, both on the same optical line every time."""
    if not text:
        return
    face = spec.pairing.face_for("label", library.fonts)
    small = sizes["small"]
    baseline_top = canvas.height - canvas.margin - small * 1.05
    rule_y = baseline_top - small * 0.95
    canvas.rule(rule_y, height=max(1.0, canvas.short * 0.0015), fill=L.hairline(spec))
    canvas.tracked(canvas.content_left, baseline_top, text, face, small, spec.ink, tracking=0.16)


def _items(spec: L.Spec, canvas: L.Canvas, library: Library, sizes: dict,
           items: list[str], top: float, bottom: float) -> None:
    """Rows with a hairline between them, sized to the space they actually have."""
    count = len(items)
    if count == 0:
        return
    available = bottom - top
    # Rows keep a typographic rhythm rather than stretching to fill the card; the leftover space
    # belongs above the footer, where it reads as breathing room.
    row_height = min(available / count, sizes["body"] * 2.45)
    probe = spec.pairing.face_for("text", library.fonts)
    body = min(sizes["body"], row_height * 0.5)
    if body < sizes["body_min"]:
        raise L.LayoutError(
            f"{count} lines do not fit this card; a feed card holds about six. Split the list "
            "across a carousel rather than shrinking it to nothing."
        )
    for index, item in enumerate(items):
        row_top = top + index * row_height
        left, _, right = item.partition("|")
        left, right = left.strip(), right.strip()
        fitted = fit_lines([left], probe, canvas.content_width - (canvas.content_width * 0.28 if right else 0),
                           body, sizes["body_min"])
        if not fitted.fits:
            canvas.notes.append(f"item {index + 1} is wider than its column")
        text_top = row_top + (row_height - probe.line_height(fitted.size)) / 2
        canvas.text(canvas.content_left, text_top, left, probe, fitted.size, spec.ink, role="item")
        if right:
            label = spec.pairing.face_for("label", library.fonts)
            small = min(sizes["small"], fitted.size * 0.82)
            canvas.text_right(canvas.content_right, text_top + (fitted.size - small) * 0.18,
                              right, label, small, L.accent_ink(spec), tracking=0.02, role="meta")
        if index < count - 1:
            canvas.rule(row_top + row_height - max(1.0, canvas.short * 0.0012),
                        height=max(1.0, canvas.short * 0.0012), fill=L.hairline(spec))


def _image_band(spec: L.Spec, canvas: L.Canvas, height_ratio: float) -> float:
    """A photograph across the top, text below it. No scrim, no guesswork about a busy image."""
    if not spec.image:
        return float(canvas.margin)
    band = canvas.height * height_ratio
    canvas.image(spec.image["path"], 0, 0, canvas.width, band,
                 focus=tuple(spec.image.get("focus") or (0.5, 0.5)))
    return band + canvas.margin


def _image_bleed(spec: L.Spec, canvas: L.Canvas) -> str:
    """A full-bleed photograph with a scrim, and the ink that survives it."""
    if not spec.image:
        return spec.ink
    canvas.image(spec.image["path"], 0, 0, canvas.width, canvas.height,
                 focus=tuple(spec.image.get("focus") or (0.5, 0.5)))
    direction, alpha = colour.scrim_for(colour.parse(spec.ground), (128, 128, 128))
    canvas.rect(0, 0, canvas.width, canvas.height, colour.to_hex(direction), opacity=alpha)
    canvas.notes.append(
        "type sits on a photograph with a scrim; read the render back before handing it over"
    )
    return spec.ink


# ------------------------------------------------------------------ feed, square
def feed_square_day(spec: L.Spec, library: Library) -> L.Composition:
    canvas = L.Canvas(spec.width, spec.height, spec.ground)
    sizes = _sizes(canvas)
    if spec.image:
        _image_bleed(spec, canvas)
    top = _header(canvas, spec, library, sizes)
    y, _ = L.headline_block(
        spec, canvas, library, spec.content["headline"],
        top + canvas.short * 0.045,
        canvas.content_width,
        sizes["display"],
        sizes["display_min"],
        max_lines=3,
    )
    rule_y = y + canvas.short * 0.03
    canvas.rule(rule_y, width=canvas.content_width * 0.32, height=canvas.short * 0.0055,
                fill=spec.accent)
    day = spec.content.get("day") or ""
    if day:
        face = spec.pairing.face_for("display", library.fonts)
        fitted = fit_lines([day], face, canvas.content_width, sizes["day"], sizes["day_min"],
                           tracking=spec.pairing.tracking_for("display"))
        day_top = max(rule_y + canvas.short * 0.05, canvas.height * 0.60)
        canvas.text(canvas.content_left, day_top, day, face, fitted.size, L.accent_ink(spec),
                    tracking=spec.pairing.tracking_for("display"), role="day")
        if not fitted.fits:
            canvas.notes.append("the day line is wider than the card")
    _footer(canvas, spec, library, sizes, spec.content.get("footer") or "")
    return L.Composition(canvas.width, canvas.height, spec.ground, canvas.ops,
                         {"template": spec.template, "direction": spec.direction.id},
                         canvas.safe, canvas.margin, canvas.notes)


def feed_square_list(spec: L.Spec, library: Library) -> L.Composition:
    canvas = L.Canvas(spec.width, spec.height, spec.ground)
    sizes = _sizes(canvas)
    bleed = bool(spec.image)
    if bleed:
        _image_bleed(spec, canvas)
    top = _header(canvas, spec, library, sizes)
    y, _ = L.headline_block(
        spec, canvas, library, spec.content["headline"],
        top + canvas.short * 0.04,
        canvas.content_width,
        sizes["display"] * 0.82,
        sizes["display_min"],
        max_lines=2,
    )
    footer_text = spec.content.get("footer") or ""
    footer_rule = canvas.height - canvas.margin - sizes["small"] * 2.0
    items_top = max(y + canvas.short * 0.055, canvas.height * 0.40)
    _items(spec, canvas, library, sizes, list(spec.content.get("items") or []),
           items_top, footer_rule - canvas.short * 0.03)
    _footer(canvas, spec, library, sizes, footer_text)
    return L.Composition(canvas.width, canvas.height, spec.ground, canvas.ops,
                         {"template": spec.template, "direction": spec.direction.id},
                         canvas.safe, canvas.margin, canvas.notes)


# ------------------------------------------------------------------ feed, portrait
def portrait_availability(spec: L.Spec, library: Library) -> L.Composition:
    canvas = L.Canvas(spec.width, spec.height, spec.ground)
    sizes = _sizes(canvas)
    if spec.image:
        _image_bleed(spec, canvas)
    top = _header(canvas, spec, library, sizes)
    y, _ = L.headline_block(
        spec, canvas, library, spec.content["headline"],
        top + canvas.short * 0.04,
        canvas.content_width,
        sizes["display"] * 0.92,
        sizes["display_min"],
        max_lines=2,
    )
    rule_y = y + canvas.short * 0.028
    canvas.rule(rule_y, width=canvas.content_width * 0.22, height=canvas.short * 0.0045,
                fill=spec.accent)
    footer_text = spec.content.get("footer") or ""
    footer_rule = canvas.height - canvas.margin - sizes["small"] * 2.0
    items = list(spec.content.get("items") or [])
    items_top = rule_y + canvas.short * 0.045
    if len(items) >= 5:
        _two_columns(spec, canvas, library, sizes, items, items_top,
                     footer_rule - canvas.short * 0.03)
    else:
        _items(spec, canvas, library, sizes, items, items_top,
               footer_rule - canvas.short * 0.03)
    _footer(canvas, spec, library, sizes, footer_text)
    return L.Composition(canvas.width, canvas.height, spec.ground, canvas.ops,
                         {"template": spec.template, "direction": spec.direction.id},
                         canvas.safe, canvas.margin, canvas.notes)


def _two_columns(spec: L.Spec, canvas: L.Canvas, library: Library, sizes: dict,
                 items: list[str], top: float, bottom: float) -> None:
    half = (len(items) + 1) // 2
    columns = [items[:half], items[half:]]
    gutter = canvas.short * 0.045
    column_width = (canvas.content_width - gutter) / 2
    probe = spec.pairing.face_for("text", library.fonts)
    rows = max(len(column) for column in columns)
    row_height = min((bottom - top) / max(1, rows), sizes["body"] * 3.0)
    body = min(sizes["body"] * 0.92, row_height * 0.5)
    if body < sizes["body_min"]:
        raise L.LayoutError("the list is too long for two columns; split it into a carousel")
    label = spec.pairing.face_for("label", library.fonts)
    for index, column in enumerate(columns):
        x = canvas.content_left + index * (column_width + gutter)
        for row, entry in enumerate(column):
            item, _, quantity = entry.partition("|")
            item, quantity = item.strip(), quantity.strip()
            limit = column_width - (column_width * 0.3 if quantity else 0)
            fitted = fit_lines([item], probe, limit, body, sizes["body_min"])
            y = top + row * row_height + (row_height - probe.line_height(fitted.size)) / 2
            canvas.text(x, y, item, probe, fitted.size, spec.ink, role="item")
            if quantity:
                small = min(sizes["small"], fitted.size * 0.82)
                canvas.text_right(x + column_width, y + (fitted.size - small) * 0.18, quantity,
                                  label, small, L.accent_ink(spec), role="meta")
            if not fitted.fits:
                canvas.notes.append(f"a list line in column {index + 1} is too wide")


# ------------------------------------------------------------------ story
def story_announcement(spec: L.Spec, library: Library) -> L.Composition:
    canvas = L.Canvas(spec.width, spec.height, spec.ground)
    canvas.set_story_safe(canvas.height * 0.13, canvas.height * 0.18)
    sizes = _sizes(canvas)
    if spec.image:
        _image_bleed(spec, canvas)
    top = max(float(canvas.safe[1]), canvas.height * 0.16)
    if spec.content.get("eyebrow"):
        L.label_line(spec, canvas, library, spec.content["eyebrow"], top, sizes["eyebrow"],
                     tracking=0.22)
    y, _ = L.headline_block(
        spec, canvas, library, spec.content["headline"],
        top + sizes["eyebrow"] * 1.6,
        canvas.content_width,
        canvas.short * 0.165,
        sizes["display_min"],
        max_lines=4,
    )
    canvas.rule(y + canvas.short * 0.035, width=canvas.content_width * 0.28,
                height=canvas.short * 0.006, fill=spec.accent)
    day = spec.content.get("day") or ""
    if day:
        face = spec.pairing.face_for("display", library.fonts)
        fitted = fit_lines([day], face, canvas.content_width, sizes["day"] * 1.1, sizes["day_min"])
        canvas.text(canvas.content_left, canvas.height * 0.70, day, face, fitted.size,
                    L.accent_ink(spec), tracking=spec.pairing.tracking_for("display"), role="day")
    footer = spec.content.get("footer") or ""
    if footer:
        face = spec.pairing.face_for("label", library.fonts)
        canvas.tracked(canvas.content_left, canvas.height * 0.86, footer, face,
                       sizes["small"], spec.ink, tracking=0.16)
    return L.Composition(canvas.width, canvas.height, spec.ground, canvas.ops,
                         {"template": spec.template, "direction": spec.direction.id},
                         canvas.safe, canvas.margin, canvas.notes)


# ------------------------------------------------------------------ market day
def market_day(spec: L.Spec, library: Library) -> L.Composition:
    canvas = L.Canvas(spec.width, spec.height, spec.ground)
    sizes = _sizes(canvas)
    top = _header(canvas, spec, library, sizes)
    face = spec.pairing.face_for("display", library.fonts)
    day = spec.content["day"]
    fitted = fit_lines([day], face, canvas.content_width,
                       canvas.short * 0.26 * spec.pairing.scale, canvas.short * 0.09)
    day_top = top + canvas.short * 0.10
    canvas.text(canvas.content_left, day_top, day, face, fitted.size, L.accent_ink(spec),
                tracking=spec.pairing.tracking_for("display"), role="day")
    y = day_top + face.line_height(fitted.size) + canvas.short * 0.012
    label = spec.pairing.face_for("label", library.fonts)
    meta = [value for value in (spec.content.get("time"), spec.content.get("venue")) if value]
    for index, value in enumerate(meta):
        canvas.text(canvas.content_left, y + index * sizes["small"] * 1.55, value, label,
                    sizes["small"] * 0.98, spec.ink, tracking=0.03, role="meta")
    y += len(meta) * sizes["small"] * 1.85 + canvas.short * 0.03
    canvas.rule(y, width=canvas.content_width * 0.18, height=canvas.short * 0.004,
                fill=spec.accent)
    headline = spec.content.get("headline")
    if headline:
        L.headline_block(spec, canvas, library, headline, y + canvas.short * 0.03,
                         canvas.content_width, sizes["body"] * 1.25, sizes["body"],
                         max_lines=2)
    _footer(canvas, spec, library, sizes, spec.content.get("footer") or "")
    return L.Composition(canvas.width, canvas.height, spec.ground, canvas.ops,
                         {"template": spec.template, "direction": spec.direction.id},
                         canvas.safe, canvas.margin, canvas.notes)


# ------------------------------------------------------------------ quote
def quote_card(spec: L.Spec, library: Library) -> L.Composition:
    canvas = L.Canvas(spec.width, spec.height, spec.ground)
    sizes = _sizes(canvas)
    top = _header(canvas, spec, library, sizes)
    mark_face = spec.pairing.face_for("display", library.fonts)
    canvas.text(canvas.content_left - canvas.short * 0.008, top + canvas.short * 0.015, "\u201c",
                mark_face, canvas.short * 0.16, spec.accent, role="mark")
    quote = spec.content["quote"]
    y, _ = L.headline_block(
        spec, canvas, library, quote,
        top + canvas.short * 0.155,
        canvas.content_width,
        canvas.short * 0.072,
        canvas.short * 0.040,
        max_lines=5,
        tracking=spec.pairing.tracking_for("display"),
    )
    # A five-line quote on a 4:5 card leaves a void under the attribution if it starts where the
    # header ends. Centre the block in the space it actually has, once its height is known.
    attribution = spec.content.get("attribution") or ""
    block_bottom = y + (canvas.short * 0.055 if attribution else 0)
    slack = (canvas.height - canvas.margin - sizes["small"] * 2.4) - block_bottom
    if slack > canvas.height * 0.10:
        canvas.shift(min(slack * 0.5, canvas.height * 0.16))
        y += min(slack * 0.5, canvas.height * 0.16)
    if attribution:
        face = spec.pairing.face_for("label", library.fonts)
        canvas.rule(y + canvas.short * 0.02, width=canvas.content_width * 0.14,
                    height=canvas.short * 0.0035, fill=spec.accent)
        canvas.tracked(canvas.content_left, y + canvas.short * 0.04, attribution, face,
                       sizes["small"], spec.ink, tracking=0.16)
    _footer(canvas, spec, library, sizes, spec.content.get("footer") or "")
    return L.Composition(canvas.width, canvas.height, spec.ground, canvas.ops,
                         {"template": spec.template, "direction": spec.direction.id},
                         canvas.safe, canvas.margin, canvas.notes)


# ------------------------------------------------------------------ price board
def price_board(spec: L.Spec, library: Library) -> L.Composition:
    canvas = L.Canvas(spec.width, spec.height, spec.ground)
    sizes = _sizes(canvas)
    top = _header(canvas, spec, library, sizes)
    headline = spec.content.get("headline")
    y = top
    if headline:
        y, _ = L.headline_block(spec, canvas, library, headline, top + canvas.short * 0.02,
                                canvas.content_width, canvas.short * 0.10,
                                canvas.short * 0.05, max_lines=2)
    note = spec.content.get("price_note") or spec.content.get("note") or ""
    face = spec.pairing.face_for("text", library.fonts)
    label = spec.pairing.face_for("label", library.fonts)
    rows = list(spec.content.get("items") or [])
    if not rows:
        raise L.LayoutError("a price board needs `items` as 'Item | price' lines")
    top_rows = y + canvas.short * 0.05
    bottom = canvas.height - canvas.margin - (sizes["small"] * 3.4 if note else 0)
    row_height = (bottom - top_rows) / len(rows)
    if row_height < sizes["body_min"] * 1.4:
        raise L.LayoutError("too many price rows for one board; split it into two")
    size = min(canvas.short * 0.040, row_height * 0.52)
    for index, row in enumerate(rows):
        item, _, price = row.partition("|")
        item, price = item.strip(), price.strip()
        row_top = top_rows + index * row_height
        text_top = row_top + (row_height - face.line_height(size)) / 2
        canvas.text(canvas.content_left, text_top, item, face, size, spec.ink, role="item")
        if price:
            canvas.text_right(canvas.content_right, text_top + (size - size * 0.9) * 0.1,
                              price, label, size * 0.9, L.accent_ink(spec), role="meta")
        canvas.rule(row_top + row_height - canvas.short * 0.0012,
                    height=canvas.short * 0.0012, fill=L.hairline(spec))
    if note:
        canvas.text(canvas.content_left, canvas.height - canvas.margin - sizes["small"] * 1.5,
                    note, face, sizes["small"], spec.ink, role="note")
    return L.Composition(canvas.width, canvas.height, spec.ground, canvas.ops,
                         {"template": spec.template, "direction": spec.direction.id},
                         canvas.safe, canvas.margin, canvas.notes)


# ------------------------------------------------------------------ carousel cover
def carousel_cover(spec: L.Spec, library: Library) -> L.Composition:
    """A cover, not a slide: the title at the top, the numeral at the foot as a marker."""
    canvas = L.Canvas(spec.width, spec.height, spec.ground)
    sizes = _sizes(canvas)
    top = _header(canvas, spec, library, sizes)
    number = str(spec.content.get("number") or "").strip()
    y, _ = L.headline_block(
        spec, canvas, library, spec.content["headline"],
        top + canvas.short * 0.055,
        canvas.content_width * 0.92,
        canvas.short * 0.175,
        sizes["display_min"],
        max_lines=4,
    )
    canvas.rule(y + canvas.short * 0.035, width=canvas.content_width * 0.26,
                height=canvas.short * 0.006, fill=spec.accent)
    if number:
        face = spec.pairing.face_for("display", library.fonts)
        number_size = canvas.short * 0.30
        canvas.text_right(canvas.content_right, canvas.height * 0.62, number, face,
                          number_size,
                          colour.to_hex(colour.mix(colour.parse(spec.accent),
                                                   colour.parse(spec.ground), 0.18)),
                          tracking=0.0, role="number")
    footer = spec.content.get("footer") or ""
    if footer:
        _footer(canvas, spec, library, sizes, footer)
    return L.Composition(canvas.width, canvas.height, spec.ground, canvas.ops,
                         {"template": spec.template, "direction": spec.direction.id},
                         canvas.safe, canvas.margin, canvas.notes)


# ------------------------------------------------------------------ print
def _print_margin(canvas: L.Canvas, ratio: float = 0.07) -> None:
    """Print margins are proportionally smaller than a phone card's: the sheet is the medium."""
    canvas.margin = int(round(canvas.short * ratio))


def poster_a3(spec: L.Spec, library: Library) -> L.Composition:
    """A3 portrait: the poster that goes on the gate, the window, the back of the stall."""
    canvas = L.Canvas(spec.width, spec.height, spec.ground)
    _print_margin(canvas)
    sizes = _sizes(canvas)
    top = _header(canvas, spec, library, sizes)
    y, _ = L.headline_block(
        spec, canvas, library, spec.content["headline"],
        top + canvas.short * 0.045,
        canvas.content_width,
        canvas.short * 0.155,
        canvas.short * 0.060,
        max_lines=3,
    )
    canvas.rule(y + canvas.short * 0.030, width=canvas.content_width * 0.30,
                height=canvas.short * 0.0045, fill=spec.accent)
    day = spec.content.get("day") or ""
    label = spec.pairing.face_for("label", library.fonts)
    meta = [value for value in (spec.content.get("time"), spec.content.get("venue")) if value]
    meta_height = len(meta) * sizes["small"] * 1.55
    if day:
        face = spec.pairing.face_for("display", library.fonts)
        fitted = fit_lines([day], face, canvas.content_width,
                           canvas.short * 0.090 * spec.pairing.scale, canvas.short * 0.045)
        # The day belongs at the foot of the poster, above the footer, not floating in the middle:
        # anchor the block to the bottom and only move it up if the headline has grown into it.
        footer_top = canvas.height - canvas.margin - sizes["small"] * 1.05
        anchored = footer_top - sizes["small"] * 0.95 - canvas.short * 0.05 - meta_height \
            - face.line_height(fitted.size)
        day_top = max(y + canvas.short * 0.06, anchored)
        canvas.text(canvas.content_left, day_top, day, face, fitted.size, L.accent_ink(spec),
                    tracking=spec.pairing.tracking_for("display"), role="day")
        y = day_top + face.line_height(fitted.size)
    for index, value in enumerate(meta):
        canvas.text(canvas.content_left, y + canvas.short * 0.012 + index * sizes["small"] * 1.55,
                    value, label, sizes["small"] * 1.12, spec.ink, tracking=0.03, role="meta")
    _footer(canvas, spec, library, sizes, spec.content.get("footer") or "")
    return L.Composition(canvas.width, canvas.height, spec.ground, canvas.ops,
                         {"template": spec.template, "direction": spec.direction.id},
                         canvas.safe, canvas.margin, canvas.notes)


def sign_a3(spec: L.Spec, library: Library) -> L.Composition:
    """A3 landscape, read at three metres: the day is the design."""
    canvas = L.Canvas(spec.width, spec.height, spec.ground)
    _print_margin(canvas)
    sizes = _sizes(canvas)
    top = canvas.margin
    if spec.content.get("eyebrow"):
        L.label_line(spec, canvas, library, spec.content["eyebrow"], top, sizes["eyebrow"],
                     tracking=0.22)
    face = spec.pairing.face_for("display", library.fonts)
    day = spec.content["day"]
    fitted = fit_lines([day], face, canvas.content_width,
                       canvas.short * 0.32 * spec.pairing.scale, canvas.short * 0.10)
    day_top = top + sizes["eyebrow"] * 2.0
    canvas.text(canvas.content_left, day_top, day, face, fitted.size, spec.ink,
                tracking=spec.pairing.tracking_for("display"), role="day")
    y = day_top + face.line_height(fitted.size) + canvas.short * 0.015
    canvas.rule(y, width=canvas.content_width * 0.22, height=canvas.short * 0.006, fill=spec.accent)
    y += canvas.short * 0.035
    label = spec.pairing.face_for("label", library.fonts)
    meta = [value for value in (spec.content.get("time"), spec.content.get("venue")) if value]
    for index, value in enumerate(meta):
        # A sign read at three metres needs the venue at roughly 14 mm, not 10 mm: the rule of
        # thumb is about 1 mm of cap height per 300 mm of viewing distance, doubled for comfort.
        canvas.text(canvas.content_left, y + index * sizes["small"] * 1.85, value, label,
                    sizes["small"] * 1.45, spec.ink, tracking=0.02, role="meta")
    y += len(meta) * sizes["small"] * 1.55 + canvas.short * 0.03
    headline = spec.content.get("headline")
    if headline:
        L.headline_block(spec, canvas, library, headline, y, canvas.content_width * 0.8,
                         canvas.short * 0.070, canvas.short * 0.030, max_lines=2)
    _footer(canvas, spec, library, sizes, spec.content.get("footer") or "")
    return L.Composition(canvas.width, canvas.height, spec.ground, canvas.ops,
                         {"template": spec.template, "direction": spec.direction.id},
                         canvas.safe, canvas.margin, canvas.notes)


def menu_a4(spec: L.Spec, library: Library) -> L.Composition:
    """A4 portrait: a menu, with prices aligned to one edge and no box around anything."""
    canvas = L.Canvas(spec.width, spec.height, spec.ground)
    _print_margin(canvas, 0.08)
    sizes = _sizes(canvas)
    top = _header(canvas, spec, library, sizes)
    y, _ = L.headline_block(
        spec, canvas, library, spec.content["headline"],
        top + canvas.short * 0.03, canvas.content_width, canvas.short * 0.085,
        canvas.short * 0.040, max_lines=2,
    )
    canvas.rule(y + canvas.short * 0.02, width=canvas.content_width,
                height=canvas.short * 0.0018, fill=L.hairline(spec))
    rows = list(spec.content.get("items") or [])
    if not rows:
        raise L.LayoutError("a menu needs `items` as 'Dish | price' lines")
    note = spec.content.get("price_note") or ""
    face = spec.pairing.face_for("text", library.fonts)
    label = spec.pairing.face_for("label", library.fonts)
    top_rows = y + canvas.short * 0.05
    bottom = canvas.height - canvas.margin - (sizes["small"] * 3.2 if note else 0)
    row_height = min((bottom - top_rows) / len(rows), canvas.short * 0.075)
    if row_height < sizes["body_min"] * 1.5:
        raise L.LayoutError("too many menu rows for one page; split it into two")
    size = min(canvas.short * 0.036, row_height * 0.48)
    for index, row in enumerate(rows):
        dish, _, price = row.partition("|")
        dish, price = dish.strip(), price.strip()
        row_top = top_rows + index * row_height
        text_top = row_top + (row_height - face.line_height(size)) / 2
        canvas.text(canvas.content_left, text_top, dish, face, size, spec.ink, role="item")
        if price:
            canvas.text_right(canvas.content_right, text_top, price, label, size * 0.92,
                              L.accent_ink(spec), role="meta")
    if note:
        # Above the footer's rule, not on it: the footer owns the last line of the page.
        canvas.text(canvas.content_left, canvas.height - canvas.margin - sizes["small"] * 3.7,
                    note, face, sizes["small"], spec.ink, role="note")
    _footer(canvas, spec, library, sizes, spec.content.get("footer") or "")
    return L.Composition(canvas.width, canvas.height, spec.ground, canvas.ops,
                         {"template": spec.template, "direction": spec.direction.id},
                         canvas.safe, canvas.margin, canvas.notes)


def label_proof(spec: L.Spec, library: Library) -> L.Composition:
    """A label front, as a proof: the product and the space the particulars need.

    The particulars themselves are not this template's to invent. It reserves the block, names the
    fields, and leaves a bracketed placeholder for each so the report says exactly what is still
    missing before anybody prints.
    """
    canvas = L.Canvas(spec.width, spec.height, spec.ground)
    _print_margin(canvas, 0.075)
    sizes = _sizes(canvas)
    top = _header(canvas, spec, library, sizes)
    y, _ = L.headline_block(
        spec, canvas, library, spec.content["headline"],
        top + canvas.short * 0.06, canvas.content_width, canvas.short * 0.150,
        canvas.short * 0.070, max_lines=2,
    )
    canvas.rule(y + canvas.short * 0.03, width=canvas.content_width * 0.26,
                height=canvas.short * 0.005, fill=spec.accent)
    label = spec.pairing.face_for("label", library.fonts)
    text_face = spec.pairing.face_for("text", library.fonts)
    fields = ["NET WEIGHT", "INGREDIENTS", "PRODUCER", "LOT / DATE MARK", "STORAGE"]
    block_top = max(y + canvas.short * 0.10, canvas.height * 0.52)
    pitch = (canvas.height - canvas.margin - sizes["small"] * 5.0 - block_top) / len(fields)
    pitch = min(pitch, canvas.short * 0.085)
    for index, field in enumerate(fields):
        row = block_top + index * pitch
        canvas.tracked(canvas.content_left, row, field, label, sizes["small"] * 0.92,
                       spec.ink, tracking=0.14)
        canvas.text(canvas.content_left, row + sizes["small"] * 1.05, f"[{field}]", text_face,
                    sizes["small"] * 1.02, spec.ink, role="body")
        canvas.rule(row + pitch - canvas.short * 0.006, height=canvas.short * 0.0012,
                    fill=L.hairline(spec))
    canvas.text(canvas.content_left, canvas.height - canvas.margin - sizes["small"] * 4.0,
                "PROOF ONLY — the particulars come from the labelling checklist, not from this "
                "template.", text_face, sizes["small"] * 0.95, spec.ink, role="note")
    _footer(canvas, spec, library, sizes, spec.content.get("footer") or "")
    return L.Composition(canvas.width, canvas.height, spec.ground, canvas.ops,
                         {"template": spec.template, "direction": spec.direction.id},
                         canvas.safe, canvas.margin, canvas.notes)


TEMPLATES = {
    "feed-square-day": feed_square_day,
    "feed-square-list": feed_square_list,
    "portrait-availability": portrait_availability,
    "story-announcement": story_announcement,
    "market-day": market_day,
    "quote-card": quote_card,
    "price-board": price_board,
    "carousel-cover": carousel_cover,
    "poster-a3": poster_a3,
    "sign-a3": sign_a3,
    "menu-a4": menu_a4,
    "label-proof": label_proof,
}


def compose(spec: L.Spec, library: Library) -> L.Composition:
    try:
        render = TEMPLATES[spec.template]
    except KeyError as exc:  # pragma: no cover - resolve() refuses an unknown template first
        raise L.LayoutError(f"no renderer for template {spec.template!r}") from exc
    composition = render(spec, library)
    composition.meta.update(
        {
            "palette": spec.palette.id,
            "type": spec.pairing.id,
            "face": spec.pairing.display.family,
        }
    )
    return composition
