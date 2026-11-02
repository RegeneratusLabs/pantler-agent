"""Refusing a hostile or unreadable container before a parser sees it."""

from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from support import PLUGIN  # noqa: F401
from office.office_engine import guard

_SHEET = ('<?xml version="1.0" encoding="UTF-8"?>'
          '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"/>')


def build(path: Path, entries: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as package:
        for name, body in entries.items():
            package.writestr(name, body)
    return path


class Refusals(unittest.TestCase):
    def setUp(self):
        self._scratch = tempfile.TemporaryDirectory(prefix="pantler-guard-")
        self.root = Path(self._scratch.name)

    def tearDown(self):
        self._scratch.cleanup()

    def refused(self, path: Path) -> str:
        with self.assertRaises(guard.GuardError) as caught:
            guard.check(path)
        return str(caught.exception)

    def test_a_plain_package_passes(self):
        path = build(self.root / "ok.xlsx", {"xl/worksheets/sheet1.xml": _SHEET})
        info = guard.check(path)
        self.assertEqual(info["entries"], 1)
        self.assertGreater(info["bytes"], 0)

    def test_a_doctype_part_is_refused(self):
        path = build(self.root / "bomb.xlsx", {
            "xl/worksheets/sheet1.xml": b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY a "b">]>'
                                        b"<worksheet/>",
        })
        self.assertIn("document type", self.refused(path))

    def test_a_doctype_hidden_behind_a_long_prolog_is_still_found(self):
        path = build(self.root / "padded.xlsx", {
            "xl/worksheets/sheet1.xml": b'<?xml version="1.0"?><!--' + b"x" * 8000 +
                                        b'--><!DOCTYPE lolz [<!ENTITY a "b">]><worksheet/>',
        })
        self.assertIn("document type", self.refused(path))

    def test_a_part_larger_than_the_cap_is_refused(self):
        path = build(self.root / "huge.xlsx", {"xl/worksheets/sheet1.xml": b"<x/>"})
        original = guard.MAX_PART
        guard.MAX_PART = 3
        try:
            self.assertIn("limit for a single part", self.refused(path))
        finally:
            guard.MAX_PART = original

    def test_a_macro_project_is_refused(self):
        path = build(self.root / "macro.xlsx", {"xl/vbaProject.bin": b"\x00"})
        self.assertIn("macro", self.refused(path))

    def test_an_entry_pointing_outside_is_refused(self):
        path = build(self.root / "slip.xlsx", {"../evil.xml": b"<x/>"})
        self.assertIn("outside itself", self.refused(path))

    def test_an_absolute_entry_is_refused(self):
        path = build(self.root / "abs.xlsx", {"/etc/passwd": b"x"})
        self.assertIn("outside itself", self.refused(path))

    def test_an_ole_container_is_refused(self):
        path = self.root / "old.xlsx"
        path.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64)
        self.assertIn("OLE container", self.refused(path))

    def test_a_macro_enabled_suffix_is_refused_before_opening(self):
        path = self.root / "book.xlsm"
        path.write_bytes(b"PK\x03\x04")
        self.assertIn("macros", self.refused(path))

    def test_a_legacy_binary_suffix_is_refused(self):
        path = self.root / "book.xls"
        path.write_bytes(b"PK\x03\x04")
        self.assertIn("old binary format", self.refused(path))

    def test_a_file_that_is_not_a_zip_is_refused(self):
        path = self.root / "notes.xlsx"
        path.write_text("this is not a workbook")
        self.assertIn("not a zip package", self.refused(path))

    def test_too_many_entries_is_refused(self):
        path = build(self.root / "many.xlsx", {f"part{i}.xml": b"<x/>" for i in range(4)})
        original = guard.MAX_ENTRIES
        guard.MAX_ENTRIES = 3
        try:
            self.assertIn("parts", self.refused(path))
        finally:
            guard.MAX_ENTRIES = original

    def test_a_missing_file_is_refused_with_its_reason(self):
        self.assertIn("could not be read", self.refused(self.root / "absent.xlsx"))


if __name__ == "__main__":
    unittest.main()
