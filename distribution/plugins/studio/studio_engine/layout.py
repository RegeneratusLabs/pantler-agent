"""The artboard: margins, type scale, and the operations both renderers draw.

A layout is a list of absolute operations — a baseline for every line of type, a rectangle in
pixels, an image crop — plus the measurements the audit re-checks. Nothing here is a template;
templates are in `templates.py` and they only place blocks on this canvas. That split is what makes
"the model never supplies geometry" enforceable: there is no way to pass a coordinate in.

Text is positioned by its *top*, and the baseline is derived from the face's own ascent, because
that is the only way a serif and a condensed grotesque sit on the same optical line.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import palette as colour
from .fonts import Face
from .library import Direction, Library, Palette, TypePairing
from .text import balanced, char_positions, fit_lines, largest_fitting, missing_glyphs


class LayoutError(ValueError):
    """A spec the renderer will not draw: missing content, an impossible size, a broken palette."""


# ---------------------------------------------------------------------------- operations
@dataclass
class TextOp:
    x: float
    top: float
    baseline: float
    text: str
    face_id: str
    family: str
    size: float
    fill: str
    tracking: float = 0.0
    width: float = 0.0
    height: float = 0.0
    chars: list[tuple[str, float]] | None = None
    role: str = "text"

    @property
    def box(self) -> tuple[float, float, float, float]:
        return (self.x, self.top, self.width, self.height)


@dataclass
class RectOp:
    x: float
    y: float
    w: float
    h: float
    fill: str
    opacity: float = 1.0
    radius: float = 0.0


@dataclass
class ImageOp:
    x: float
    y: float
    w: float
    h: float
    path: str
    opacity: float = 1.0
    focus: tuple[float, float] = (0.5, 0.5)


@dataclass
class Composition:
    width: int
    height: int
    ground: str
    ops: list = field(default_factory=list)
    meta: dict = field(default_factory=dict)
    safe: tuple[float, float, float, float] = (0, 0, 0, 0)
    margin: float = 0.0
    notes: list[str] = field(default_factory=list)

    @property
    def short(self) -> int:
        return min(self.width, self.height)

    def texts(self) -> list[TextOp]:
        return [op for op in self.ops if isinstance(op, TextOp)]

    def images(self) -> list[ImageOp]:
        return [op for op in self.ops if isinstance(op, ImageOp)]

    def colours(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for op in self.ops:
            fill = getattr(op, "fill", None)
            if fill:
                counts[fill] = counts.get(fill, 0) + 1
        return counts


# ---------------------------------------------------------------------------- the canvas
class Canvas:
    def __init__(self, width: int, height: int, ground: str):
        self.width = int(width)
        self.height = int(height)
        self.ground = ground
        self.ops: list = []
        self.notes: list[str] = []
        self.short = min(self.width, self.height)
        self.margin = int(round(self.short * 0.095))
        # Story surfaces carry platform chrome; a headline under it is a headline nobody sees.
        self.safe = (
            self.margin * 0.6,
            self.margin * 0.6,
            self.width - self.margin * 1.2,
            self.height - self.margin * 1.2,
        )

    # ------------------------------------------------------------------ geometry
    @property
    def content_width(self) -> float:
        return self.width - 2 * self.margin

    @property
    def content_left(self) -> float:
        return float(self.margin)

    @property
    def content_right(self) -> float:
        return float(self.width - self.margin)

    def set_story_safe(self, top: float, bottom: float) -> None:
        self.safe = (self.margin * 0.6, top, self.width - self.margin * 1.2, self.height - top - bottom)

    def rule(self, y: float, width: float | None = None, x: float | None = None,
             height: float = 2.0, fill: str = "") -> RectOp:
        op = RectOp(
            x=float(x if x is not None else self.margin),
            y=float(y),
            w=float(width if width is not None else self.content_width),
            h=float(height),
            fill=fill or self.ground,
        )
        self.ops.append(op)
        return op

    def rect(self, x: float, y: float, w: float, h: float, fill: str, opacity: float = 1.0) -> RectOp:
        op = RectOp(x=float(x), y=float(y), w=float(w), h=float(h), fill=fill, opacity=opacity)
        self.ops.append(op)
        return op

    def image(self, path: str, x: float, y: float, w: float, h: float,
              focus: tuple[float, float] = (0.5, 0.5), opacity: float = 1.0) -> ImageOp:
        op = ImageOp(x=float(x), y=float(y), w=float(w), h=float(h), path=path,
                     focus=focus, opacity=opacity)
        self.ops.append(op)
        return op

    # ------------------------------------------------------------------ type
    def text(
        self,
        x: float,
        top: float,
        value: str,
        face: Face,
        size: float,
        fill: str,
        tracking: float = 0.0,
        role: str = "text",
        tracking_em: bool = True,
    ) -> TextOp:
        """One line of type, placed by its top and measured by the face."""
        space = tracking if tracking_em else tracking / size if size else 0.0
        width = face.width(value, size, space)
        op = TextOp(
            x=float(x),
            top=float(top),
            baseline=float(top + face.ascent(size)),
            text=value,
            face_id=face.id,
            family=face.family,
            size=float(size),
            fill=fill,
            tracking=float(space),
            width=width,
            height=face.line_height(size),
            chars=char_positions(value, face, size, space) if space else None,
            role=role,
        )
        self.ops.append(op)
        return op

    def tracked(
        self,
        x: float,
        top: float,
        value: str,
        face: Face,
        size: float,
        fill: str,
        tracking: float = 0.18,
        role: str = "label",
    ) -> TextOp:
        return self.text(x, top, value.upper(), face, size, fill, tracking=tracking, role=role)

    def text_right(
        self,
        right: float,
        top: float,
        value: str,
        face: Face,
        size: float,
        fill: str,
        tracking: float = 0.0,
        role: str = "text",
    ) -> TextOp:
        width = face.width(value, size, tracking)
        return self.text(right - width, top, value, face, size, fill, tracking=tracking, role=role)

    def right_of(self, op: TextOp, gap: float = 0.0) -> float:
        return op.x + op.width + gap

    def shift(self, dy: float) -> None:
        """Move everything drawn so far, for optical centring after the block is measured."""
        if not dy:
            return
        for op in self.ops:
            if isinstance(op, TextOp):
                op.top += dy
                op.baseline += dy
            else:
                op.y += dy


# ---------------------------------------------------------------------------- spec
CONTENT_KEYS = {
    "eyebrow",
    "headline",
    "items",
    "day",
    "footer",
    "quote",
    "attribution",
    "venue",
    "time",
    "price",
    "price_note",
    "note",
    "kicker",
    "number",
}

SPEC_KEYS = {"template", "direction", "palette", "type", "brand", "content", "image", "out", "size", "title"}


@dataclass
class Spec:
    template: str
    direction: Direction
    palette: Palette
    pairing: TypePairing
    content: dict
    image: dict | None
    out: Path
    width: int
    height: int
    brand: dict
    title: str = ""
    physical: tuple[float, float] | None = None

    @property
    def ink(self) -> str:
        return self.palette.ink

    @property
    def ground(self) -> str:
        return self.palette.ground

    @property
    def accent(self) -> str:
        return self.palette.accent

    @property
    def accent2(self) -> str:
        return self.palette.accent2


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise LayoutError(message)


def resolve(spec: dict, library: Library, brand: dict | None = None) -> Spec:
    """Validate a brief and turn it into what a template needs. Unknown keys are refused."""
    _require(isinstance(spec, dict), "the brief must be an object")
    unknown = sorted(set(spec) - SPEC_KEYS)
    _require(not unknown, f"unknown brief key(s): {', '.join(unknown)}")

    template_id = str(spec.get("template") or "").strip()
    _require(bool(template_id), "the brief needs a template; ask design_templates for the list")
    template = library.template(template_id)

    brand = dict(brand or {})
    direction_id = str(spec.get("direction") or brand.get("direction") or "").strip()
    _require(bool(direction_id), "the brief needs a direction; ask design_templates for the list")
    direction = library.direction(direction_id)

    brand_colours = brand.get("colours") if isinstance(brand.get("colours"), dict) else {}
    explicit = brand_colours or None
    palette_block = spec.get("palette")
    if isinstance(palette_block, dict):
        palette = Palette(
            id="operator",
            name="Operator palette",
            group="operator",
            ground=str(palette_block.get("ground") or brand_colours.get("ground") or ""),
            ink=str(palette_block.get("ink") or brand_colours.get("ink") or ""),
            accent=str(
                palette_block.get("accent")
                or brand_colours.get("accent")
                or palette_block.get("ink")
                or brand_colours.get("ink")
                or ""
            ),
            accent2=str(
                palette_block.get("accent2")
                or brand_colours.get("accent2")
                or palette_block.get("accent")
                or brand_colours.get("accent")
                or ""
            ),
            note="supplied by the operator",
        )
        _require(bool(palette.ground and palette.ink), "a palette needs `ground` and `ink`")
        for field_name in ("ground", "ink", "accent", "accent2"):
            colour.parse(getattr(palette, field_name))
        if colour.contrast(colour.parse(palette.ink), colour.parse(palette.ground)) < colour.AA_TEXT:
            raise LayoutError(
                "the operator's ink on ground is below 4.5:1; choose a darker ink or a lighter "
                "ground rather than shipping a card that cannot be read"
            )
    elif explicit:
        base = library.palette(str(brand.get("palette") or direction.palette))
        palette = Palette(
            id=base.id,
            name=base.name,
            group=base.group,
            ground=str(explicit.get("ground") or base.ground),
            ink=str(explicit.get("ink") or base.ink),
            accent=str(explicit.get("accent") or base.accent),
            accent2=str(explicit.get("accent2") or base.accent2),
            note=base.note,
        )
        if colour.contrast(colour.parse(palette.ink), colour.parse(palette.ground)) < colour.AA_TEXT:
            raise LayoutError(
                "the brand's ink on ground is below 4.5:1; fix the brand kit before designing "
                "with it"
            )
    else:
        palette = library.palette(str(brand.get("palette") or direction.palette))

    pairing_id = str(spec.get("type") or brand.get("type") or direction.type)
    pairing = library.pairing(pairing_id)

    content = spec.get("content") or {}
    _require(isinstance(content, dict), "`content` must be an object")
    unknown_content = sorted(set(content) - CONTENT_KEYS)
    _require(not unknown_content, f"unknown content key(s): {', '.join(unknown_content)}")
    for key, value in content.items():
        if key == "items":
            _require(isinstance(value, list), "`items` is a list of lines")
            _require(all(isinstance(item, str) for item in value), "every item is a string")
        else:
            _require(isinstance(value, str), f"`{key}` is a string")

    for needed in template.get("requires") or []:
        _require(
            bool(content.get(needed)),
            f"template {template_id!r} needs content.{needed} — ask the operator for it; "
            "do not invent it",
        )

    width, height = template["sizes"][0]
    physical: tuple[float, float] | None = None
    size_block = spec.get("size")
    print_block = template.get("print")
    if isinstance(size_block, list) and len(size_block) == 2:
        width, height = int(size_block[0]), int(size_block[1])
    elif isinstance(print_block, dict) and print_block.get("mm"):
        # A print template says its finished size in millimetres; the pixels are derived at its dpi
        # so the artboard is the physical thing, not a number somebody chose.
        mm = print_block["mm"]
        dpi = float(print_block.get("dpi") or 300)
        physical = (float(mm[0]), float(mm[1]))
        width = int(round(float(mm[0]) / 25.4 * dpi))
        height = int(round(float(mm[1]) / 25.4 * dpi))
    _require(width >= 320 and height >= 320, "an artboard is at least 320 px on each side")
    if not isinstance(size_block, list) and not print_block:
        _require(
            (width, height) in [tuple(size) for size in template["sizes"]],
            f"template {template_id!r} is drawn at {template['sizes']}; pass `size` to override",
        )

    image = spec.get("image")
    if image is not None:
        _require(isinstance(image, dict), "`image` must be an object")
        unknown_image = sorted(set(image) - {"path", "fit", "focus", "treatment"})
        _require(not unknown_image, f"unknown image key(s): {', '.join(unknown_image)}")
        _require(bool(image.get("path")), "an image needs a `path`")
        image = {
            "path": str(image["path"]),
            "fit": image.get("fit", "cover"),
            "focus": tuple(image.get("focus") or (0.5, 0.5)),
            "treatment": image.get("treatment", "none"),
        }

    out = Path(str(spec.get("out") or "")).expanduser()
    _require(bool(str(out)), "the brief needs an `out` directory")

    return Spec(
        template=template_id,
        direction=direction,
        palette=palette,
        pairing=pairing,
        content={key: value for key, value in content.items() if value not in (None, "", [])},
        image=image,
        out=out,
        width=width,
        height=height,
        brand=brand,
        title=str(spec.get("title") or ""),
        physical=physical,
    )


# ---------------------------------------------------------------------------- shared blocks
def type_sizes(canvas: Canvas) -> dict[str, float]:
    """One scale, derived from the short side. Three sizes, never five.

    The eyebrow and the footer are the same size on purpose: tracked capitals at two nearby sizes
    read as a mistake, not as hierarchy.
    """
    short = canvas.short
    label = max(18.0, short * 0.0195)
    return {
        "display": short * 0.142,
        "display_min": short * 0.058,
        "day": short * 0.082,
        "day_min": short * 0.050,
        "body": short * 0.031,
        "body_min": short * 0.024,
        "eyebrow": label,
        "small": label,
    }


def accent_ink(spec: Spec) -> str:
    """The accent, or the ink when the accent cannot carry text at AA."""
    if colour.contrast(colour.parse(spec.accent), colour.parse(spec.ground)) >= colour.AA_TEXT:
        return spec.accent
    return spec.ink


def hairline(spec: Spec) -> str:
    return colour.to_hex(colour.mix(colour.parse(spec.ink), colour.parse(spec.ground), 0.72))


def headline_block(
    spec: Spec,
    canvas: Canvas,
    library: Library,
    text: str,
    top: float,
    max_width: float,
    max_size: float,
    min_size: float,
    max_lines: int = 3,
    fill: str | None = None,
    tracking: float | None = None,
) -> tuple[float, list[TextOp]]:
    """Set a headline and return the y after its last line."""
    face = spec.pairing.face_for("display", library.fonts)
    track = spec.pairing.tracking_for("display") if tracking is None else tracking
    max_size = max(min_size, max_size * spec.pairing.scale)
    fitted = balanced(
        text, face, max_width, max_size, min_size, max_lines=max_lines, tracking=track
    )
    colour_fill = fill or spec.ink
    x = canvas.content_left
    ops: list[TextOp] = []
    cursor = top
    bottom = top
    for line in fitted.lines:
        op = canvas.text(x, cursor, line, face, fitted.size, colour_fill, tracking=track,
                         role="headline")
        ops.append(op)
        # Display leading is optical, not the font's default: a serif's full line box at 145 px
        # leaves a gap you could park a car in. 1.06 em clears every descender we ship.
        cursor = op.top + fitted.size * 1.06
        bottom = op.baseline + face.descent(fitted.size)
    if not fitted.fits:
        canvas.notes.append(
            f"headline does not fit at the minimum legible size by {fitted.overflow:.0f} px"
        )
    if fitted.widows:
        canvas.notes.append("the headline ends on a single word")
    missing = missing_glyphs(text, face)
    if missing:
        canvas.notes.append(
            "the display face has no glyph for: " + ", ".join(repr(char) for char in missing)
        )
    return bottom, ops


def body_lines(
    spec: Spec,
    canvas: Canvas,
    library: Library,
    lines: list[str],
    top: float,
    max_width: float,
    size: float,
    fill: str | None = None,
    tracking: float | None = None,
) -> tuple[float, list[TextOp]]:
    face = spec.pairing.face_for("text", library.fonts)
    track = spec.pairing.tracking_for("text") if tracking is None else tracking
    fitted = fit_lines(lines, face, max_width, size, size)
    ops: list[TextOp] = []
    pitch = size * 1.55
    y = top
    for line in fitted.lines:
        op = canvas.text(canvas.content_left, y, line, face, fitted.size, fill or spec.ink,
                         tracking=track, role="body")
        ops.append(op)
        y += pitch
    if not fitted.fits:
        canvas.notes.append(f"a list line is {fitted.overflow:.0f} px wider than the column")
    return y, ops


def label_line(
    spec: Spec,
    canvas: Canvas,
    library: Library,
    text: str,
    top: float,
    size: float,
    fill: str | None = None,
    x: float | None = None,
    tracking: float = 0.18,
) -> TextOp:
    face = spec.pairing.face_for("label", library.fonts)
    return canvas.tracked(
        canvas.content_left if x is None else x,
        top,
        text,
        face,
        size,
        fill or spec.ink,
        tracking=tracking,
    )
