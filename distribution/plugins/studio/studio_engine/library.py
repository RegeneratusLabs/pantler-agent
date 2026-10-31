"""The shipped library: researched directions, palettes, type pairings and template metadata.

The point of a library rather than a prompt is that a model asked to invent a look returns the
average of every look it has seen. Here the look is already decided by somebody who looked at this
market — a market stall, a label, a produce box, a pantry shelf — and the model's job is to choose
one that carries the operator's words and then fill it honestly.

Everything in `library/` is authored for this product. Nothing is copied from another project; the
public repos that informed the method are named in PROVENANCE.md and none of their text ships.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from . import palette as colour
from .fonts import Library as FontLibrary, FontError


class LibraryError(ValueError):
    """A direction, palette or pairing the library does not carry."""


@dataclass(frozen=True)
class TypeRole:
    family: str
    weight: int
    tracking: float = 0.0


@dataclass(frozen=True)
class TypePairing:
    id: str
    display: TypeRole
    text: TypeRole
    label: TypeRole
    note: str
    #: Display sizes are multiplied by this: a monospaced face at 150 px is a wall, not a headline.
    scale: float = 1.0

    def face_for(self, role: str, fonts: FontLibrary):
        chosen = {"display": self.display, "text": self.text, "label": self.label}[role]
        return fonts.face_for(chosen.family, chosen.weight)

    def tracking_for(self, role: str) -> float:
        return {"display": self.display, "text": self.text, "label": self.label}[role].tracking


@dataclass(frozen=True)
class Palette:
    id: str
    name: str
    group: str
    ground: str
    ink: str
    accent: str
    accent2: str
    note: str

    def as_dict(self) -> dict[str, str]:
        return {
            "ground": self.ground,
            "ink": self.ink,
            "accent": self.accent,
            "accent2": self.accent2,
        }


@dataclass(frozen=True)
class Direction:
    id: str
    name: str
    idea: str
    suits: tuple[str, ...]
    palette: str
    type: str
    photo: str
    posture: tuple[str, ...]
    rules: tuple[str, ...]


class Library:
    def __init__(self, root: Path, fonts_dir: Path | None = None):
        self.root = Path(root)
        # `library/` sits inside the plugin, `fonts/` beside it: <plugin>/fonts, <plugin>/library.
        self.fonts = FontLibrary(fonts_dir or self.root.parent.parent / "fonts")
        self.directions = self._directions()
        self.palettes = self._palettes()
        self.pairings = self._pairings()
        self.templates = self._templates()
        page_data = self._read("pages.json")
        self.page_kinds: dict[str, str] = dict(page_data["kinds"])
        self.pages: dict[str, dict] = {entry["id"]: entry for entry in page_data["blueprints"]}

    # ------------------------------------------------------------------ loading
    def _read(self, name: str) -> dict:
        path = self.root / name
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:  # pragma: no cover - a broken install
            raise LibraryError(f"{path} is missing from the installation") from exc
        except json.JSONDecodeError as exc:
            raise LibraryError(f"{path} is not valid JSON: {exc}") from exc

    def _directions(self) -> dict[str, Direction]:
        raw = self._read("directions.json")
        result: dict[str, Direction] = {}
        for entry in raw["directions"]:
            result[entry["id"]] = Direction(
                id=entry["id"],
                name=entry["name"],
                idea=entry["idea"],
                suits=tuple(entry.get("suits") or ()),
                palette=entry["palette"],
                type=entry["type"],
                photo=entry.get("photo", "optional"),
                posture=tuple(entry.get("posture") or ()),
                rules=tuple(entry.get("rules") or ()),
            )
        return result

    def _palettes(self) -> dict[str, Palette]:
        raw = self._read("palettes.json")
        result: dict[str, Palette] = {}
        for entry in raw["palettes"]:
            palette = Palette(
                id=entry["id"],
                name=entry["name"],
                group=entry.get("group", "other"),
                ground=entry["ground"],
                ink=entry["ink"],
                accent=entry["accent"],
                accent2=entry.get("accent2", entry["accent"]),
                note=entry.get("note", ""),
            )
            # A palette that fails the product's own floor is a broken library, not a warning.
            ratio = colour.contrast(colour.parse(palette.ink), colour.parse(palette.ground))
            if ratio < colour.AA_TEXT:
                raise LibraryError(
                    f"palette {palette.id!r} sets ink on ground at {ratio:.2f}:1; the library "
                    f"floor is {colour.AA_TEXT}:1"
                )
            result[palette.id] = palette
        return result

    def _pairings(self) -> dict[str, TypePairing]:
        raw = self._read("type-pairs.json")
        result: dict[str, TypePairing] = {}
        for entry in raw["pairings"]:
            pairing = TypePairing(
                id=entry["id"],
                display=TypeRole(**entry["display"]),
                text=TypeRole(**entry["text"]),
                label=TypeRole(**entry["label"]),
                note=entry.get("note", ""),
                scale=float(entry.get("scale") or 1.0),
            )
            for role in ("display", "text", "label"):
                try:
                    self.fonts.face_for(
                        getattr(pairing, role).family, getattr(pairing, role).weight
                    )
                except FontError as exc:
                    raise LibraryError(f"pairing {pairing.id!r}: {exc}") from exc
            result[pairing.id] = pairing
        return result

    def _templates(self) -> dict[str, dict]:
        raw = self._read("templates.json")
        return {entry["id"]: entry for entry in raw["templates"]}

    # ------------------------------------------------------------------ lookup
    def page(self, page_id: str) -> dict:
        if page_id not in self.pages:
            raise LibraryError(
                f"unknown blueprint {page_id!r}; ask design_templates for the list"
            )
        return self.pages[page_id]

    def template(self, template_id: str) -> dict:
        if template_id not in self.templates:
            raise LibraryError(
                f"unknown template {template_id!r}; ask design_templates for the list"
            )
        return self.templates[template_id]

    def direction(self, direction_id: str) -> Direction:
        if direction_id not in self.directions:
            raise LibraryError(
                f"unknown direction {direction_id!r}; ask design_templates for the list"
            )
        return self.directions[direction_id]

    def palette(self, palette_id: str) -> Palette:
        if palette_id not in self.palettes:
            raise LibraryError(f"unknown palette {palette_id!r}")
        return self.palettes[palette_id]

    def pairing(self, pairing_id: str) -> TypePairing:
        if pairing_id not in self.pairings:
            raise LibraryError(f"unknown type pairing {pairing_id!r}")
        return self.pairings[pairing_id]

    # ------------------------------------------------------------------ browsing
    def describe(self) -> dict:
        """One line each — enough to choose from without loading the whole library into a prompt."""
        return {
            "directions": [
                {
                    "id": d.id,
                    "name": d.name,
                    "idea": d.idea,
                    "suits": list(d.suits),
                    "palette": d.palette,
                    "type": d.type,
                    "photo": d.photo,
                }
                for d in self.directions.values()
            ],
            "templates": [
                {
                    "id": t["id"],
                    "name": t["name"],
                    "surface": t["surface"],
                    "sizes": t["sizes"],
                    "needs": t["needs"],
                    "best_for": t["best_for"],
                }
                for t in self.templates.values()
            ],
            "palettes": [
                {"id": p.id, "name": p.name, "group": p.group, **p.as_dict()}
                for p in self.palettes.values()
            ],
            "type_pairs": [
                {"id": p.id, "display": p.display.family, "text": p.text.family, "note": p.note}
                for p in self.pairings.values()
            ],
            "pages": [
                {
                    "id": page["id"],
                    "name": page["name"],
                    "sections": page["sections"],
                    "requires": page["requires"],
                    "best_for": page["best_for"],
                }
                for page in self.pages.values()
            ],
            "page_sections": self.page_kinds,
            "fonts": {
                "families": self.fonts.families(),
                "faces": self.fonts.all_face_ids(),
            },
        }
