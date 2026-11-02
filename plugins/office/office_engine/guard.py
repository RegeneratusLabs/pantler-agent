"""Look at an Office file before a parser does.

The operators of small businesses are sent files by customers, certifiers, accountants and
strangers. Every one of them is untrusted input, and the libraries that read them carry the XML
expansion surface — openpyxl's own documentation says it does not guard against entity expansion
unless `defusedxml` is installed, and `defusedxml` is deliberately **not** in this closure (its
licence is unmapped by the scanner's database, and a gate that cannot read a licence is a gate
nobody can trust).

So this module is the defence instead of that library, and it runs before any parser: the OLE
signature (an encrypted or legacy file we cannot read), the entry names (a zip that writes outside
its own directory), the declared sizes (a zip that expands past what this machine should spend), a
macro part (we write and read office documents, never macro-enabled ones), and a DOCTYPE anywhere in
any XML part — the whole part is read up to a hard cap, not just its first page, because a prolog
can be padded. A part larger than the cap is refused rather than sampled: everything this tool
accepts, it has looked at entirely.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

MAX_BYTES = 50 * 1024 * 1024
MAX_ENTRIES = 5000
MAX_UNCOMPRESSED = 200 * 1024 * 1024
#: The most any single XML part may be. The whole part is read and scanned for a DOCTYPE, so this
#: is also the memory ceiling of that scan.
MAX_PART = 8 * 1024 * 1024
_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

MACRO_SUFFIXES = (".xlsm", ".docm", ".pptm", ".xltm", ".dotm", ".potm", ".xlsb")
LEGACY_SUFFIXES = (".doc", ".xls", ".ppt", ".vsd")


class GuardError(RuntimeError):
    """This file is refused, with the reason. The caller reports the sentence, never hides it."""


def check(path: Path) -> dict:
    """Refuse an unreadable or hostile container. Returns `{bytes, entries}` when it is safe."""
    path = Path(path)
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise GuardError(f"the file could not be read: {exc.strerror or exc}") from exc
    suffix = path.suffix.lower()
    if suffix in MACRO_SUFFIXES:
        raise GuardError(
            f"a {suffix} file carries macros, and this product writes and reads office documents "
            f"without them. Save it as {suffix.replace('m', 'x', 1) if suffix != '.xlsb' else '.xlsx'} "
            f"and try again."
        )
    if suffix in LEGACY_SUFFIXES:
        raise GuardError(
            f"a {suffix} file is the old binary format, not Office Open XML; it cannot be read "
            f"here. Re-save it as {suffix}x in Word, Excel or LibreOffice and try again."
        )
    if size > MAX_BYTES:
        raise GuardError(f"that file is {size // (1024 * 1024)} MB; the limit is "
                         f"{MAX_BYTES // (1024 * 1024)} MB")
    try:
        with path.open("rb") as handle:
            head = handle.read(8)
    except OSError as exc:
        raise GuardError(f"the file could not be opened: {exc.strerror or exc}") from exc
    if head == _OLE:
        raise GuardError(
            "that is an encrypted or legacy Office file (an OLE container), not an Open XML "
            "package, so it cannot be read here. Remove the password or re-save it as .docx/.xlsx."
        )
    if head[:2] != b"PK":
        raise GuardError("that file is not a zip package, so it is not an Office document")

    try:
        with zipfile.ZipFile(path) as package:
            infos = package.infolist()
            names = [info.filename for info in infos]
            total = sum(info.file_size for info in infos)
            if len(infos) > MAX_ENTRIES:
                raise GuardError(f"that package has {len(infos)} parts; the limit is {MAX_ENTRIES}")
            if total > MAX_UNCOMPRESSED:
                raise GuardError(f"that package expands to {total // (1024 * 1024)} MB; the limit "
                                 f"is {MAX_UNCOMPRESSED // (1024 * 1024)} MB")
            for name in names:
                if name.startswith("/") or ".." in Path(name).parts:
                    raise GuardError("that package contains an entry that points outside itself; "
                                     "it is not a document this tool will open")
                lowered = name.lower()
                if "vbaproject" in lowered:
                    raise GuardError("that document contains a macro project; this product does "
                                     "not open macro-enabled documents")
                if lowered in ("encryptioninfo", "encryptedpackage"):
                    raise GuardError("that document is encrypted; remove the password and try again")
            for info in infos:
                lowered = info.filename.lower()
                if not (lowered.endswith(".xml") or lowered.endswith(".rels")):
                    continue
                declared = info.file_size
                if declared > MAX_PART:
                    raise GuardError(
                        f"one part of that document ({info.filename}) is "
                        f"{declared // (1024 * 1024)} MB; the limit for a single part is "
                        f"{MAX_PART // (1024 * 1024)} MB"
                    )
                with package.open(info) as handle:
                    body = handle.read(MAX_PART + 1)
                if len(body) > MAX_PART:
                    raise GuardError(f"one part of that document ({info.filename}) is larger than "
                                     f"it declares; it is refused rather than read")
                if b"<!doctype" in body.lower():
                    raise GuardError(
                        f"one part of that document ({info.filename}) declares a document type, "
                        f"which is how an XML bomb starts. It is refused rather than parsed."
                    )
    except zipfile.BadZipFile as exc:
        raise GuardError(f"that file is not a readable zip package: {exc}") from exc
    return {"bytes": size, "entries": len(infos)}
