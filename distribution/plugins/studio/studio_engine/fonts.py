"""Read a TrueType face well enough to lay type out exactly.

The layout has to be identical whether the card is finally drawn by Pillow or photographed by a
browser, so measurement cannot come from either of them. It comes from the font file itself: the
`cmap` tells us which glyph a character maps to, `hmtx` how wide that glyph is, and `head` how many
font units make an em. Advancing through a string is then arithmetic, and the same arithmetic feeds
both renderers.

This is deliberately a small subset — horizontal metrics, the Unicode cmap, ascent and descent. No
shaping, no kerning, no ligatures. A food business's card is not a paragraph of Devanagari, and a
font parser that tries to be HarfBuzz is a font parser that is wrong in new ways. Unsupported
characters are reported so the caller can refuse to render tofu.
"""

from __future__ import annotations

import json
import struct
from functools import lru_cache
from pathlib import Path


class FontError(RuntimeError):
    """A face that cannot be read, or a family that is not licensed for this plugin."""


def _u16(data: bytes, offset: int) -> int:
    return struct.unpack_from(">H", data, offset)[0]


def _s16(data: bytes, offset: int) -> int:
    return struct.unpack_from(">h", data, offset)[0]


def _u32(data: bytes, offset: int) -> int:
    return struct.unpack_from(">I", data, offset)[0]


def _tables(data: bytes) -> dict[str, tuple[int, int]]:
    """The table directory: tag -> (offset, length)."""
    if len(data) < 12:
        raise FontError("not a font file")
    version = _u32(data, 0)
    if version not in (0x00010000, 0x74727565):  # 1.0, 'true'
        raise FontError("not a TrueType font (a CFF/OpenType face needs outlining first)")
    count = _u16(data, 4)
    tables: dict[str, tuple[int, int]] = {}
    for index in range(count):
        base = 12 + index * 16
        tag = data[base : base + 4].decode("latin-1")
        tables[tag] = (_u32(data, base + 8), _u32(data, base + 12))
    return tables


def _cmap(data: bytes, start: int, length: int) -> dict[int, int]:
    """Codepoint -> glyph id, from the best Unicode subtable the file carries."""
    table = data[start : start + length]
    count = _u16(table, 2)
    subtables = []
    for index in range(count):
        base = 4 + index * 8
        platform = _u16(table, base)
        encoding = _u16(table, base + 2)
        offset = _u32(table, base + 4)
        if 0 <= offset < len(table) - 2:
            subtables.append((platform, encoding, offset))

    # Prefer a full-repertoire Unicode table, then the BMP one.
    def rank(entry: tuple[int, int, int]) -> int:
        platform, encoding, offset = entry
        fmt = _u16(table, offset)
        if platform == 3 and encoding == 10 and fmt == 12:
            return 0
        if platform == 0 and fmt == 12:
            return 1
        if platform == 3 and encoding == 1 and fmt == 4:
            return 2
        if platform == 0 and fmt == 4:
            return 3
        return 9

    for platform, encoding, offset in sorted(subtables, key=rank):
        fmt = _u16(table, offset)
        if fmt == 12:
            return _cmap12(table, offset)
        if fmt == 4:
            return _cmap4(table, offset)
    raise FontError("no Unicode cmap subtable (format 4 or 12)")


def _cmap4(table: bytes, offset: int) -> dict[int, int]:
    segments = _u16(table, offset + 6) // 2
    ends = offset + 14
    starts = ends + segments * 2 + 2
    deltas = starts + segments * 2
    ranges = deltas + segments * 2
    mapping: dict[int, int] = {}
    for index in range(segments):
        last = _u16(table, ends + index * 2)
        first = _u16(table, starts + index * 2)
        delta = _s16(table, deltas + index * 2)
        if first > last:
            continue
        range_offset = _u16(table, ranges + index * 2)
        for code in range(first, last + 1):
            if code == 0xFFFF:
                continue
            if range_offset == 0:
                glyph = (code + delta) & 0xFFFF
            else:
                position = ranges + index * 2 + range_offset + (code - first) * 2
                if position + 2 > len(table):
                    continue
                glyph = _u16(table, position)
                if glyph:
                    glyph = (glyph + delta) & 0xFFFF
            if glyph:
                mapping[code] = glyph
    return mapping


def _cmap12(table: bytes, offset: int) -> dict[int, int]:
    groups = _u32(table, offset + 12)
    mapping: dict[int, int] = {}
    for index in range(groups):
        base = offset + 16 + index * 12
        first = _u32(table, base)
        last = _u32(table, base + 4)
        glyph = _u32(table, base + 8)
        for code in range(first, min(last, 0x10FFFF) + 1):
            mapping[code] = glyph + (code - first)
    return mapping


class Face:
    """One font file, its metrics, and the advance of any string at any size."""

    def __init__(self, face_id: str, family: str, weight: int, path: Path):
        self.id = face_id
        self.family = family
        self.weight = weight
        self.path = Path(path)
        data = self.path.read_bytes()
        tables = _tables(data)
        for required in ("head", "hhea", "maxp", "cmap", "hmtx"):
            if required not in tables:
                raise FontError(f"{self.path.name} has no {required!r} table")

        head, _ = tables["head"]
        self.units_per_em = _u16(data, head + 18) or 1000

        hhea, _ = tables["hhea"]
        self.ascender = _s16(data, hhea + 4)
        self.descender = _s16(data, hhea + 6)  # negative, by convention
        self.line_gap = _s16(data, hhea + 8)
        long_metrics = _u16(data, hhea + 34)

        maxp, _ = tables["maxp"]
        glyphs = _u16(data, maxp + 4)

        _, cmap_length = tables["cmap"]
        self.cmap = _cmap(data, tables["cmap"][0], cmap_length)

        hmtx, hmtx_length = tables["hmtx"]
        advances: list[int] = []
        last = 0
        for index in range(min(glyphs, long_metrics)):
            position = hmtx + index * 4
            if position + 4 > hmtx + hmtx_length:
                break
            last = _u16(data, position)
            advances.append(last)
        while len(advances) < glyphs:
            advances.append(last)
        self.advances = advances

        # Cap and x height make optical alignment possible; they are optional in the spec.
        self.cap_height = 0.70 * self.units_per_em
        self.x_height = 0.50 * self.units_per_em
        if "OS/2" in tables:
            os2, os2_length = tables["OS/2"]
            if os2_length >= 90 and _u16(data, os2) >= 2:
                cap = _s16(data, os2 + 88)
                xheight = _s16(data, os2 + 86)
                if 0 < cap <= self.units_per_em:
                    self.cap_height = cap
                if 0 < xheight <= self.units_per_em:
                    self.x_height = xheight

        self._missing: set[str] = set()

    # ---------------------------------------------------------------- metrics
    def advance_units(self, text: str) -> int:
        total = 0
        for char in text:
            glyph = self.cmap.get(ord(char))
            if glyph is None:
                self._missing.add(char)
                glyph = 0
            total += self.advances[glyph] if glyph < len(self.advances) else 0
        return total

    def width(self, text: str, size: float, tracking: float = 0.0) -> float:
        """Width in pixels. `tracking` is extra space per gap, in ems."""
        base = self.advance_units(text) * size / self.units_per_em
        if tracking and len(text) > 1:
            base += tracking * size * (len(text) - 1)
        return base

    def size_for_width(self, text: str, width: float, tracking: float = 0.0) -> float:
        units = self.advance_units(text)
        if units <= 0:
            return 0.0
        per_px = units / self.units_per_em
        if tracking and len(text) > 1:
            per_px += tracking * (len(text) - 1)
        return width / per_px if per_px else 0.0

    def line_height(self, size: float) -> float:
        return (self.ascender - self.descender + self.line_gap) * size / self.units_per_em

    def ascent(self, size: float) -> float:
        return self.ascender * size / self.units_per_em

    def descent(self, size: float) -> float:
        return -self.descender * size / self.units_per_em

    def cap(self, size: float) -> float:
        return self.cap_height * size / self.units_per_em

    def xheight(self, size: float) -> float:
        return self.x_height * size / self.units_per_em

    def missing(self) -> set[str]:
        return set(self._missing)

    def covers(self, text: str) -> bool:
        return all(ord(char) in self.cmap for char in text)


class Library:
    """The licensed faces this plugin ships, read from `fonts/fonts.json`."""

    def __init__(self, fonts_dir: Path):
        self.dir = Path(fonts_dir)
        self.manifest = json.loads((self.dir / "fonts.json").read_text(encoding="utf-8"))
        self._faces: dict[str, Face] = {}
        self._by_family: dict[str, list[dict]] = {}
        for entry in self.manifest["faces"]:
            self._by_family.setdefault(entry["family"], []).append(entry)

    def families(self) -> dict[str, dict]:
        return dict(self.manifest["families"])

    def licence_of(self, family: str) -> str:
        metadata = self.manifest["families"].get(family) or {}
        licence = metadata.get("licence") or ""
        if not licence or not (self.dir / "LICENSES" / licence).is_file():
            raise FontError(
                f"family {family!r} has no licence file in fonts/LICENSES; an unlicensed face "
                "is not used on an operator's card"
            )
        return licence

    def face(self, face_id: str) -> Face:
        if face_id in self._faces:
            return self._faces[face_id]
        for entry in self.manifest["faces"]:
            if entry["id"] != face_id:
                continue
            path = self.dir / entry["file"]
            if not path.is_file():
                raise FontError(f"{entry['file']} is missing from {self.dir}")
            self.licence_of(entry["family"])
            face = Face(entry["id"], entry["family"], int(entry["weight"]), path)
            self._faces[face_id] = face
            return face
        raise FontError(f"unknown face {face_id!r}; the licensed faces are in fonts/fonts.json")

    def face_for(self, family: str, weight: int = 400) -> Face:
        entries = self._by_family.get(family)
        if not entries:
            raise FontError(f"unknown family {family!r}")
        best = min(entries, key=lambda entry: abs(int(entry["weight"]) - weight))
        return self.face(best["id"])

    def all_face_ids(self) -> list[str]:
        return [entry["id"] for entry in self.manifest["faces"]]


@lru_cache(maxsize=32)
def _cached(face_id: str, path: str, family: str, weight: int) -> Face:
    return Face(face_id, family, weight, Path(path))


def load(face_id: str, fonts_dir: Path | None = None) -> Face:
    """One face, cached. The directory is resolved by the caller so tests can point at a copy."""
    base = Path(fonts_dir) if fonts_dir else Path(__file__).resolve().parent.parent / "fonts"
    library = Library(base)
    return library.face(face_id)
