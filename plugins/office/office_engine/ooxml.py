"""The last mile on a workbook we wrote: the computed total, and who the file says it is.

Two edits, one rewrite of the package.

**The total.** `openpyxl` writes a formula without its result — literally `<f>SUM(B2:B3)</f><v></v>`.
Every reader that does not calculate shows empty until somebody opens the file in Excel; a tool that
reported that would look broken. Pantler's rule is that the code computes the number (invariant 1),
so the number belongs in the file the code wrote: `<v>4</v>` beside the formula, computed in
`spec.py` in `Decimal`.

**The identity.** `openpyxl` signs every workbook as `openpyxl` (and the extended properties as
"Microsoft Excel Compatible / Openpyxl 3.1.5"). That is our internals showing in a document the
operator sends to their accountant. The creator becomes the business, the title the workbook's own,
and the application "Pantler".

Both are targeted byte edits on the parts that carry them; every other part is copied through
untouched. Nothing is re-serialised, because a re-serialised OOXML part is how a package starts
prompting Word to repair it.
"""

from __future__ import annotations

import os
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_DOC = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG = "http://schemas.openxmlformats.org/package/2006/relationships"

_CELL = re.compile(rb'<c r="([A-Z]+[0-9]+)"[^>]*>.*?</c>', re.S)
_EMPTY_VALUE = re.compile(rb"<v\s*/>|<v></v>")
_CREATOR = re.compile(rb"(<dc:creator[^>]*>)(.*?)(</dc:creator>)", re.S)
_TITLE = re.compile(rb"(<dc:title[^>]*>)(.*?)(</dc:title>)", re.S)
_STAMP = re.compile(rb"(<dcterms:(?:created|modified)[^>]*>)(.*?)(</dcterms:(?:created|modified)>)", re.S)
_APPLICATION = re.compile(rb"(<Application>)(.*?)(</Application>)", re.S)

CORE = "docProps/core.xml"
APP = "docProps/app.xml"


class OoxmlError(RuntimeError):
    """The package could not be read or patched. The caller reports it; it never guesses."""


def finalise(path: Path, *, cached: dict[str, float] | None = None,
             creator: str = "", title: str = "", application: str = "Pantler",
             stamp: str = "") -> dict:
    """Write cached totals and the document's identity. Returns what it could and could not do."""
    path = Path(path)
    cached = cached or {}
    replaced: dict[str, bytes] = {}
    missed: list[str] = []
    skipped: list[str] = []
    notes: list[str] = []

    groups = _groups(cached)
    parts = _sheet_parts(path) if groups else {}
    try:
        package = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as exc:
        raise OoxmlError(f"the workbook is not a readable package: {exc}") from exc

    with package:
        names = package.namelist()
        for sheet, values in groups.items():
            part = parts.get(sheet)
            if part is None or part not in names:
                missed.extend(f"{sheet}!{ref}" for ref in values)
                continue
            patched, missing, existing = _patch_cells(package.read(part), values)
            missed.extend(f"{sheet}!{ref}" for ref in missing)
            skipped.extend(f"{sheet}!{ref}" for ref in existing)
            if patched is not None:
                replaced[part] = patched

        if CORE in names and (creator or title or stamp):
            patched, changed = _patch_core(package.read(CORE), creator=creator, title=title,
                                           stamp=stamp)
            if patched is not None:
                replaced[CORE] = patched
                notes.extend(changed)
        if APP in names and application:
            patched, changed = _patch_app(package.read(APP), application)
            if patched is not None:
                replaced[APP] = patched
                notes.extend(changed)

        if not replaced:
            return {"missed": missed, "skipped": skipped, "notes": notes, "written": False}

        temporary = path.with_name(path.name + ".finalise.tmp")
        try:
            with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as out:
                for name in names:
                    out.writestr(name, replaced.get(name, package.read(name)))
        except OSError as exc:
            raise OoxmlError(f"the workbook could not be rewritten: {exc}") from exc
    os.replace(temporary, path)
    return {"missed": missed, "skipped": skipped, "notes": notes, "written": True}


# ------------------------------------------------------------------ cells

def _groups(cached: dict[str, float]) -> dict[str, dict[str, float]]:
    groups: dict[str, dict[str, float]] = {}
    for key, value in (cached or {}).items():
        sheet, separator, ref = str(key).partition("!")
        if separator and sheet and ref:
            groups.setdefault(sheet, {})[ref] = value
    return groups


def _patch_cells(xml: bytes, values: dict[str, float]) -> tuple[bytes | None, list[str], list[str]]:
    seen: set[str] = set()
    already: set[str] = set()

    def replace(match: re.Match) -> bytes:
        cell = match.group(0)
        ref = match.group(1).decode("ascii")
        if ref not in values:
            return cell
        seen.add(ref)
        if _EMPTY_VALUE.search(cell):
            return _EMPTY_VALUE.sub(b"<v>" + _number(values[ref]) + b"</v>", cell, count=1)
        if b"<v>" in cell or b"<is>" in cell:
            already.add(ref)          # somebody already put a value here; never contradict it
            return cell
        if b"<f" not in cell:
            return cell
        close = cell.rindex(b"</c>")
        return cell[:close] + b"<v>" + _number(values[ref]) + b"</v>" + cell[close:]

    patched = _CELL.sub(replace, xml)
    missing = [ref for ref in values if ref not in seen and ref not in already]
    if patched == xml:
        return None, missing, sorted(already)
    return patched, missing, sorted(already)


def _number(value: float) -> bytes:
    text = f"{float(value):.10g}"
    if text.endswith(".0"):
        text = text[:-2]
    return text.encode("ascii")


# ------------------------------------------------------------------ properties

def _patch_core(xml: bytes, *, creator: str, title: str, stamp: str) -> tuple[bytes | None, list[str]]:
    notes: list[str] = []
    patched = xml
    if creator:
        value = escape(creator).encode("utf-8")
        if _CREATOR.search(patched):
            patched = _CREATOR.sub(lambda m: m.group(1) + value + m.group(3), patched, count=1)
            notes.append("creator")
        elif b"</cp:coreProperties>" in patched:
            insert = (b'<dc:creator xmlns:dc="http://purl.org/dc/elements/1.1/">'
                      + value + b"</dc:creator>")
            patched = patched.replace(b"</cp:coreProperties>", insert + b"</cp:coreProperties>", 1)
            notes.append("creator")
    if title:
        value = escape(title).encode("utf-8")
        if _TITLE.search(patched):
            patched = _TITLE.sub(lambda m: m.group(1) + value + m.group(3), patched, count=1)
            notes.append("title")
        elif b"</cp:coreProperties>" in patched:
            insert = b'<dc:title xmlns:dc="http://purl.org/dc/elements/1.1/">' + value + b"</dc:title>"
            patched = patched.replace(b"</cp:coreProperties>", insert + b"</cp:coreProperties>", 1)
            notes.append("title")
    if stamp:
        value = escape(stamp).encode("utf-8")
        if _STAMP.search(patched):
            patched = _STAMP.sub(lambda m: m.group(1) + value + m.group(3), patched)
            notes.append("timestamp")
    if patched == xml:
        return None, notes
    return patched, notes


def _patch_app(xml: bytes, application: str) -> tuple[bytes | None, list[str]]:
    if not application:
        return None, []
    value = escape(application).encode("utf-8")
    if _APPLICATION.search(xml):
        patched = _APPLICATION.sub(lambda m: m.group(1) + value + m.group(3), xml, count=1)
    else:
        return None, []
    if patched == xml:
        return None, []
    return patched, ["application"]


# ------------------------------------------------------------------ package

def _sheet_parts(path: Path) -> dict[str, str]:
    """Sheet name → package part name, from the workbook and its relationships."""
    try:
        with zipfile.ZipFile(path) as package:
            workbook = ET.fromstring(package.read("xl/workbook.xml"))
            rels = ET.fromstring(package.read("xl/_rels/workbook.xml.rels"))
    except (KeyError, zipfile.BadZipFile, ET.ParseError, OSError):
        return {}

    targets = {}
    for relationship in rels.findall(f"{{{_PKG}}}Relationship"):
        identifier = relationship.get("Id")
        target = relationship.get("Target") or ""
        if identifier and target:
            targets[identifier] = _normalise(target)

    parts: dict[str, str] = {}
    for sheet in workbook.findall(f".//{{{_MAIN}}}sheet"):
        name = sheet.get("name")
        identifier = sheet.get(f"{{{_DOC}}}id")
        if name and identifier and identifier in targets:
            parts[name] = targets[identifier]
    return parts


def _normalise(target: str) -> str:
    if target.startswith("/"):
        return target.lstrip("/")
    if target.startswith("../"):
        return target[3:]
    return f"xl/{target}"
