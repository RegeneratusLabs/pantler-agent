"""The brand kit: what a business looks like, written down once and read by every later design.

This is the consistency mechanism. Without it every card restarts from a neutral palette and the
operator ends up with six unrelated looks. With it, the first conversation produces a small file —
a ground, an ink, an accent, a type pairing, a wordmark — and every card, page and label afterwards
reads that file instead of asking again.

Where there is no identity yet, `derive` turns the interview answers into three directions and the
operator picks one. Nothing here invents a name, a tagline or a colour: those come from the
operator, and a blank stays a question.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from . import layout as L
from . import palette as colour
from . import text as set_text
from .library import Direction, Library, Palette, TypePairing

STARTER = "starter"
CONFIRMED = "confirmed"

#: Posture answer -> directions that carry it, best first. Order is an opinion, and it is the point.
POSTURE_MAP = {
    "warm": ["03-pantry-shelf", "02-field-notes", "13-bistro-menu", "16-paper-bag", "04-long-table", "09-seasonal-almanac"],
    "clean": ["05-workbench", "12-green-grocer", "08-produce-catalogue", "14-trust-and-records", "15-dawn-run", "01-quiet-ledger"],
    "bold": ["06-bread-and-ledger", "10-harvest-festival", "07-market-chalk", "12-green-grocer", "15-dawn-run", "04-long-table"],
    "quiet": ["01-quiet-ledger", "14-trust-and-records", "11-apothecary", "05-workbench", "02-field-notes", "13-bistro-menu"],
    "playful": ["16-paper-bag", "07-market-chalk", "10-harvest-festival", "03-pantry-shelf", "06-bread-and-ledger", "12-green-grocer"],
}

POSTURES = tuple(POSTURE_MAP)


class BrandError(ValueError):
    """A brand kit that cannot be used: no name, an unreadable palette, a pairing that is not theirs."""


@dataclass
class Brand:
    name: str
    tagline: str = ""
    posture: list[str] = field(default_factory=list)
    direction: str = ""
    palette: str = ""
    type: str = ""
    colours: dict[str, str] = field(default_factory=dict)
    logo: dict = field(default_factory=dict)
    never: list[str] = field(default_factory=list)
    notes: str = ""
    sources: list[str] = field(default_factory=list)
    status: str = STARTER

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "tagline": self.tagline,
            "posture": list(self.posture),
            "direction": self.direction,
            "palette": self.palette,
            "type": self.type,
            "colours": dict(self.colours),
            "logo": dict(self.logo),
            "never": list(self.never),
            "notes": self.notes,
            "sources": list(self.sources),
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Brand":
        if not isinstance(data, dict):
            raise BrandError("a brand kit is an object")
        name = str(data.get("name") or "").strip()
        if not name:
            raise BrandError("a brand kit needs the business's name, in their words")
        return cls(
            name=name,
            tagline=str(data.get("tagline") or ""),
            posture=list(data.get("posture") or []),
            direction=str(data.get("direction") or ""),
            palette=str(data.get("palette") or ""),
            type=str(data.get("type") or ""),
            colours=dict(data.get("colours") or {}),
            logo=dict(data.get("logo") or {}),
            never=list(data.get("never") or []),
            notes=str(data.get("notes") or ""),
            sources=list(data.get("sources") or []),
            status=str(data.get("status") or STARTER),
        )


def validate(brand: Brand, library: Library) -> list[str]:
    """Everything wrong with a brand kit, as sentences. Empty means it can be used."""
    problems: list[str] = []
    if not brand.name:
        problems.append("there is no business name")
    if brand.direction:
        try:
            library.direction(brand.direction)
        except Exception as exc:
            problems.append(str(exc))
    if brand.palette:
        try:
            library.palette(brand.palette)
        except Exception as exc:
            problems.append(str(exc))
    if brand.type:
        try:
            library.pairing(brand.type)
        except Exception as exc:
            problems.append(str(exc))
    for key, value in (brand.colours or {}).items():
        if key not in {"ground", "ink", "accent", "accent2"}:
            problems.append(f"unknown colour role {key!r}")
            continue
        try:
            colour.parse(value)
        except colour.ColourError as exc:
            problems.append(str(exc))
    if brand.colours.get("ground") and brand.colours.get("ink"):
        ratio = colour.contrast(colour.parse(brand.colours["ink"]), colour.parse(brand.colours["ground"]))
        if ratio < colour.AA_TEXT:
            problems.append(f"ink on ground is {ratio:.2f}:1, below the 4.5:1 floor")
    if not brand.colours.get("accent"):
        problems.append("there is no accent colour; the card needs one decision, not a default")
    if brand.status not in (STARTER, CONFIRMED):
        problems.append(f"status must be {STARTER!r} or {CONFIRMED!r}")
    if brand.type:
        try:
            pairing = library.pairing(brand.type)
            for family in (pairing.display.family, pairing.text.family, pairing.label.family):
                library.fonts.licence_of(family)
        except Exception as exc:
            problems.append(str(exc))
    return problems


@dataclass
class Candidate:
    direction: Direction
    palette: Palette
    pairing: TypePairing
    reason: str

    def as_dict(self) -> dict:
        return {
            "direction": self.direction.id,
            "name": self.direction.name,
            "idea": self.direction.idea,
            "palette": self.palette.id,
            "colours": self.palette.as_dict(),
            "type": self.pairing.id,
            "display": self.pairing.display.family,
            "text": self.pairing.text.family,
            "reason": self.reason,
        }


def _score(direction: Direction, posture: str, kind: str) -> int:
    score = 0
    if posture and posture in direction.posture:
        score += 4
    if kind:
        needle = kind.lower()
        if any(needle in suit.lower() or suit.lower() in needle for suit in direction.suits):
            score += 3
    return score


def derive(answers: dict, library: Library) -> list[Candidate]:
    """Three directions from the interview. The operator chooses; nothing is auto-applied."""
    posture = str(answers.get("posture") or "").strip().lower()
    kind = str(answers.get("kind") or "").strip()
    avoid = {str(item).strip().lower() for item in answers.get("avoid_directions") or []}

    ordered: list[str] = []
    if posture in POSTURE_MAP:
        ordered.extend(POSTURE_MAP[posture])
    ordered.extend(direction_id for direction_id in library.directions if direction_id not in ordered)

    ranked = sorted(
        (library.direction(direction_id) for direction_id in ordered),
        key=lambda direction: (-_score(direction, posture, kind), ordered.index(direction.id)),
    )

    chosen: list[Candidate] = []
    for direction in ranked:
        if direction.id in avoid or direction.id in {candidate.direction.id for candidate in chosen}:
            continue
        palette = library.palette(direction.palette)
        pairing = library.pairing(direction.type)
        reason = (
            f"{direction.name}: {direction.idea}"
            + (f" It is built for {', '.join(direction.suits[:2])}." if direction.suits else "")
        )
        chosen.append(Candidate(direction, palette, pairing, reason))
        if len(chosen) == 3:
            break
    return chosen


def _paragraph(canvas: L.Canvas, value: str, top: float, face, size: float, fill: str,
               width: float | None = None, leading: float = 1.45) -> float:
    """Wrap a paragraph to the column and return the y after its last line."""
    # 2% of safety: our metrics ignore kerning, so a renderer that applies it can run a hair wide.
    lines = set_text.wrap(value, face, size, (width or canvas.content_width) * 0.98)
    y = top
    for line in lines:
        canvas.text(canvas.content_left, y, line, face, size, fill, role="body")
        y += size * leading
    return y


# ---------------------------------------------------------------------------- boards
def board(candidate: Candidate, library: Library, name: str, tagline: str = "",
          index: int = 1) -> L.Composition:
    """One direction, at a glance: the name, the type, the colours, and the argument."""
    width, height = 1080, 1350
    canvas = L.Canvas(width, height, candidate.palette.ground)
    spec = L.Spec(
        template="brand-board",
        direction=candidate.direction,
        palette=candidate.palette,
        pairing=candidate.pairing,
        content={"headline": name},
        image=None,
        out=Path("."),
        width=width,
        height=height,
        brand={},
    )
    sizes = L.type_sizes(canvas)
    label = candidate.pairing.face_for("label", library.fonts)
    display = candidate.pairing.face_for("display", library.fonts)
    text_face = candidate.pairing.face_for("text", library.fonts)

    canvas.tracked(canvas.content_left, canvas.margin, f"DIRECTION {index:02d}", label,
                   sizes["eyebrow"], L.accent_ink(spec), tracking=0.22)
    y, _ = L.headline_block(spec, canvas, library, name,
                            canvas.margin + sizes["eyebrow"] * 2.0,
                            canvas.content_width, sizes["display"] * 0.72,
                            sizes["display_min"], max_lines=2)
    if tagline:
        canvas.text(canvas.content_left, y + canvas.short * 0.02, tagline, text_face,
                    sizes["body"], spec.ink, role="body")
        y += sizes["body"] * 1.8

    # The palette, as chips with their own hex: a colour nobody can name is a colour nobody reuses.
    chip_top = y + canvas.short * 0.05
    chip_w = (canvas.content_width - canvas.short * 0.03 * 3) / 4
    for index_chip, (role, value) in enumerate(
        (("ground", candidate.palette.ground), ("ink", candidate.palette.ink),
         ("accent", candidate.palette.accent), ("accent2", candidate.palette.accent2))
    ):
        x = canvas.content_left + index_chip * (chip_w + canvas.short * 0.03)
        chip_h = canvas.short * 0.11
        canvas.rect(x, chip_top, chip_w, chip_h, value)
        # The ground chip is the ground; it needs an edge to be a chip at all.
        for edge in ((x, chip_top, chip_w, 1.0), (x, chip_top + chip_h - 1.0, chip_w, 1.0),
                     (x, chip_top, 1.0, chip_h), (x + chip_w - 1.0, chip_top, 1.0, chip_h)):
            canvas.rect(*edge, L.hairline(spec))
        canvas.text(x, chip_top + canvas.short * 0.125, value.upper(), label, sizes["small"] * 0.9,
                    spec.ink, tracking=0.06, role="label")
        canvas.text(x, chip_top + canvas.short * 0.155, role, label, sizes["small"] * 0.82,
                    colour.to_hex(colour.mix(colour.parse(spec.ink), colour.parse(candidate.palette.ground), 0.25)),
                    tracking=0.12, role="label")

    # The type specimen: the same sentence in the three roles.
    specimen_top = chip_top + canvas.short * 0.22
    canvas.rule(specimen_top - canvas.short * 0.03, height=canvas.short * 0.0015,
                fill=L.hairline(spec))
    canvas.text(canvas.content_left, specimen_top, candidate.direction.name, display,
                sizes["display"] * 0.34, spec.ink, tracking=candidate.pairing.tracking_for("display"),
                role="specimen")
    canvas.text(canvas.content_left, specimen_top + sizes["display"] * 0.44,
                "Lettuce, broccoli, cauliflower — picked this morning.", text_face,
                sizes["body"] * 0.9, spec.ink, role="specimen")
    canvas.tracked(canvas.content_left, specimen_top + sizes["display"] * 0.44 + sizes["body"] * 1.9,
                   "WEEK OF 19 OCTOBER", label, sizes["small"] * 0.9, spec.ink, tracking=0.16)

    # The argument, in one paragraph, at the size a paragraph should be.
    argument = candidate.direction.idea
    _paragraph(canvas, argument, specimen_top + canvas.short * 0.245, text_face,
               sizes["small"] * 1.05, spec.ink)

    footer = f"{candidate.direction.id}  ·  {candidate.palette.id}  ·  {candidate.pairing.id}"
    canvas.rule(height - canvas.margin - sizes["small"] * 2.0,
                height=canvas.short * 0.0015, fill=L.hairline(spec))
    canvas.tracked(canvas.content_left, height - canvas.margin - sizes["small"] * 1.2,
                   footer, label, sizes["small"] * 0.88, spec.ink, tracking=0.12)
    return L.Composition(width, height, candidate.palette.ground, canvas.ops,
                         {"kind": "brand-board", "direction": candidate.direction.id},
                         canvas.safe, canvas.margin, canvas.notes)


def sheet(brand: Brand, library: Library) -> L.Composition:
    """The usage sheet: the colours, the type, the mark, and the rules somebody has to follow."""
    width, height = 1240, 1754  # A4 at 150 dpi
    palette = library.palette(brand.palette) if brand.palette else library.palette(
        library.direction(brand.direction).palette if brand.direction else "neutral-stone"
    )
    pairing = library.pairing(brand.type) if brand.type else library.pairing("young-serif-barlow")
    ground = brand.colours.get("ground") or palette.ground
    ink = brand.colours.get("ink") or palette.ink
    accent = brand.colours.get("accent") or palette.accent
    accent2 = brand.colours.get("accent2") or palette.accent2

    canvas = L.Canvas(width, height, ground)
    spec = L.Spec(
        template="brand-sheet", direction=library.direction(brand.direction) if brand.direction
        else next(iter(library.directions.values())),
        palette=Palette("operator", "Operator", "operator", ground, ink, accent, accent2, ""),
        pairing=pairing, content={}, image=None, out=Path("."), width=width, height=height,
        brand=brand.to_dict(),
    )
    sizes = L.type_sizes(canvas)
    display = pairing.face_for("display", library.fonts)
    text_face = pairing.face_for("text", library.fonts)
    label = pairing.face_for("label", library.fonts)

    canvas.tracked(canvas.content_left, canvas.margin, "BRAND SHEET", label,
                   sizes["eyebrow"], spec.ink, tracking=0.24)
    y, _ = L.headline_block(spec, canvas, library, brand.name,
                            canvas.margin + sizes["eyebrow"] * 2.2, canvas.content_width,
                            sizes["display"] * 0.62, sizes["display_min"], max_lines=2)
    if brand.tagline:
        canvas.text(canvas.content_left, y + 8, brand.tagline, text_face, sizes["body"], spec.ink)
        y += sizes["body"] * 1.7

    # colour
    y += canvas.short * 0.05
    canvas.tracked(canvas.content_left, y, "COLOUR", label, sizes["small"], spec.ink, tracking=0.2)
    y += sizes["small"] * 2.0
    chip_w = (canvas.content_width - canvas.short * 0.028 * 3) / 4
    for index, (role, value) in enumerate((("ground", ground), ("ink", ink),
                                           ("accent", accent), ("accent2", accent2))):
        x = canvas.content_left + index * (chip_w + canvas.short * 0.028)
        canvas.rect(x, y, chip_w, canvas.short * 0.10, value)
        # The ground chip is the ground; without an edge it is invisible on its own sheet.
        canvas.rect(x, y, chip_w, 1.0, L.hairline(spec))
        canvas.rect(x, y + canvas.short * 0.10 - 1.0, chip_w, 1.0, L.hairline(spec))
        canvas.rect(x, y, 1.0, canvas.short * 0.10, L.hairline(spec))
        canvas.rect(x + chip_w - 1.0, y, 1.0, canvas.short * 0.10, L.hairline(spec))
        canvas.text(x, y + canvas.short * 0.115, value.upper(), label, sizes["small"] * 0.9,
                    spec.ink, tracking=0.06)
        canvas.text(x, y + canvas.short * 0.145, role, label, sizes["small"] * 0.82,
                    colour.to_hex(colour.mix(colour.parse(spec.ink), colour.parse(ground), 0.25)),
                    tracking=0.12)
    ratio = colour.contrast(colour.parse(ink), colour.parse(ground))
    canvas.text(canvas.content_left, y + canvas.short * 0.185,
                f"ink on ground {ratio:.1f}:1  ·  accent on ground "
                f"{colour.contrast(colour.parse(accent), colour.parse(ground)):.1f}:1",
                text_face, sizes["small"] * 0.95, spec.ink)

    # type
    y += canvas.short * 0.26
    canvas.tracked(canvas.content_left, y, "TYPE", label, sizes["small"], spec.ink, tracking=0.2)
    y += sizes["small"] * 1.9
    canvas.text(canvas.content_left, y, brand.name, display, canvas.short * 0.075, spec.ink,
                tracking=pairing.tracking_for("display"), role="specimen")
    y += canvas.short * 0.095
    y = _paragraph(canvas, "Headline, body and label in their own roles. Never set a paragraph in "
                           "the display face.", y, text_face, sizes["body"] * 0.95, spec.ink)
    y += sizes["body"] * 0.6
    canvas.tracked(canvas.content_left, y, f"{pairing.display.family} · {pairing.text.family} · "
                                           f"{pairing.label.family}", label, sizes["small"] * 0.9,
                   spec.ink, tracking=0.08)

    # rules
    y += canvas.short * 0.06
    canvas.rule(y, height=canvas.short * 0.0015, fill=L.hairline(spec))
    y += canvas.short * 0.028
    canvas.tracked(canvas.content_left, y, "USAGE", label, sizes["small"], spec.ink, tracking=0.2)
    y += sizes["small"] * 1.8
    rules = [
        "Clear space around the mark: half its height on every side.",
        f"Minimum sizes: mark 24 px, horizontal lockup 120 px wide, stacked 88 px wide.",
        f"Ground {ground.upper()}, ink {ink.upper()}, accent {accent.upper()} — and nothing else.",
        "No rotation, skew, shadow, outline or gradient. No recolouring the mark.",
        "Wheat or a light accent is decoration; it is never body text.",
    ]
    if brand.never:
        rules.append("Never: " + "; ".join(brand.never) + ".")
    for line in rules:
        y = _paragraph(canvas, line, y, text_face, sizes["small"] * 1.02, spec.ink,
                       leading=1.55)
        y += sizes["small"] * 0.28

    # the honest footer
    status = "starter identity" if brand.status == STARTER else "confirmed identity"
    canvas.rule(height - canvas.margin - sizes["small"] * 3.0,
                height=canvas.short * 0.0015, fill=L.hairline(spec))
    _paragraph(canvas, f"{status} · type is embedded in the SVG; ask for outlined vectors before "
                       "a print supplier cuts plates.",
               height - canvas.margin - sizes["small"] * 3.4, text_face, sizes["small"] * 0.92,
               spec.ink)
    _paragraph(canvas, "Pantler has not run a trademark search. Have the mark checked before you "
                       "register or print it.",
               height - canvas.margin - sizes["small"] * 1.6, text_face, sizes["small"] * 0.92,
               spec.ink)
    return L.Composition(width, height, ground, canvas.ops, {"kind": "brand-sheet"},
                         canvas.safe, canvas.margin, canvas.notes)


def lockup(brand: Brand, library: Library, layout: str = "horizontal") -> L.Composition:
    """A wordmark lockup at a size a printer can use. Type-led, one colour, no effects."""
    pairing = library.pairing(brand.type) if brand.type else library.pairing("young-serif-barlow")
    display = pairing.face_for("display", library.fonts)
    label = pairing.face_for("label", library.fonts)
    ink = brand.colours.get("ink") or "#1B2420"
    ground = brand.colours.get("ground") or "#F7EFDF"
    name = brand.name
    case = str((brand.logo or {}).get("case") or "title")
    text = {"lower": name.lower(), "upper": name.upper(), "title": name}[case if case in
                                                                        {"lower", "upper", "title"} else "title"]

    if layout == "monogram":
        size = 512
        canvas = L.Canvas(size, size, ink)
        initials = str((brand.logo or {}).get("monogram") or "".join(
            word[0] for word in name.split()[:2]
        )).upper()[:2]
        face = display
        measured = face.width(initials, size * 0.34, 0.04)
        canvas.text((size - measured) / 2, size * 0.30, initials, face, size * 0.34, ground,
                    tracking=0.04)
        return L.Composition(size, size, ink, canvas.ops, {"kind": "lockup", "layout": "monogram"},
                             canvas.safe, canvas.margin, [])

    if layout == "stacked":
        width, height = 1200, 900
        canvas = L.Canvas(width, height, ground)
        measured = display.width(text, height * 0.17, pairing.tracking_for("display"))
        canvas.text((width - measured) / 2, height * 0.36, text, display, height * 0.17, ink,
                    tracking=pairing.tracking_for("display"))
        if brand.tagline:
            small = label.width(brand.tagline.upper(), height * 0.032, 0.18)
            canvas.tracked((width - small) / 2, height * 0.58, brand.tagline, label,
                           height * 0.032, ink, tracking=0.18)
        return L.Composition(width, height, ground, canvas.ops, {"kind": "lockup", "layout": "stacked"},
                             canvas.safe, canvas.margin, [])

    width, height = 1600, 480
    canvas = L.Canvas(width, height, ground)
    display_size = height * 0.30
    measured = display.width(text, display_size, pairing.tracking_for("display"))
    canvas.text((width - measured) / 2, height * 0.20, text, display, display_size, ink,
                tracking=pairing.tracking_for("display"))
    if brand.tagline:
        tag = brand.tagline.upper()
        small = label.width(tag, height * 0.035, 0.2)
        canvas.tracked((width - small) / 2, height * 0.62, tag, label, height * 0.035, ink,
                       tracking=0.2)
    return L.Composition(width, height, ground, canvas.ops, {"kind": "lockup", "layout": "horizontal"},
                         canvas.safe, canvas.margin, [])


def save(brand: Brand, path: Path) -> Path:
    if not (brand.name or "").strip():
        raise BrandError("a brand kit is not saved without the business's name")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(brand.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def load(path: Path) -> Brand:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BrandError(f"{path} does not exist") from exc
    except json.JSONDecodeError as exc:
        raise BrandError(f"{path} is not valid JSON: {exc}") from exc
    return Brand.from_dict(data)
