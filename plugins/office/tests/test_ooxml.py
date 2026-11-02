"""The last mile: the computed total goes into the formula, and the file says who made it."""

from __future__ import annotations

import unittest
import zipfile
from pathlib import Path

from support import PLUGIN  # noqa: F401
from office.office_engine import ooxml

_MAIN = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
_REL = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'

WORKBOOK = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<workbook {_MAIN} {_REL}><sheets>'
            f'<sheet name="Spray" sheetId="1" r:id="rId1"/></sheets></workbook>')
RELS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/></Relationships>')
CORE = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/'
        'core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/'
        'XMLSchema-instance"><dc:creator>openpyxl</dc:creator>'
        '<dcterms:created xsi:type="dcterms:W3CDTF">2026-01-01T00:00:00Z</dcterms:created>'
        '<dcterms:modified xsi:type="dcterms:W3CDTF">2026-01-01T00:00:00Z</dcterms:modified>'
        '</cp:coreProperties>')
APP = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
       '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/'
       'extended-properties"><Application>Microsoft Excel Compatible / Openpyxl 3.1.5'
       '</Application></Properties>')
STYLES = b"<styleSheet/>"
SHEET = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
         f'<worksheet {_MAIN}><sheetData>'
         f'<row r="1"><c r="A1" t="inlineStr"><is><t>Block</t></is></c></row>'
         f'<row r="2"><c r="B2" t="n"><v>2.5</v></c></row>'
         f'<row r="4"><c r="B4"><f>SUM(B2:B2)</f><v></v></c>'
         f'<c r="C4"><f>MIN(B2:B2)</f></c>'
         f'<c r="D4"><f>MAX(B2:B2)</f><v>99</v></c>'
         f'<c r="E4" t="inlineStr"><is><t>kept as it is</t></is></c></row>'
         f'</sheetData></worksheet>')


def make_package(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as package:
        package.writestr("xl/workbook.xml", WORKBOOK)
        package.writestr("xl/_rels/workbook.xml.rels", RELS)
        package.writestr("xl/worksheets/sheet1.xml", SHEET)
        package.writestr("xl/styles.xml", STYLES)
        package.writestr("docProps/core.xml", CORE)
        package.writestr("docProps/app.xml", APP)


class Finalise(unittest.TestCase):
    def setUp(self):
        import tempfile

        self._scratch = tempfile.TemporaryDirectory(prefix="pantler-ooxml-")
        self.path = Path(self._scratch.name) / "book.xlsx"
        make_package(self.path)

    def tearDown(self):
        self._scratch.cleanup()

    def test_the_value_lands_beside_the_formula(self):
        report = ooxml.finalise(self.path, cached={"Spray!B4": 4.0, "Spray!C4": 2.5})
        self.assertEqual(report["missed"], [])
        with zipfile.ZipFile(self.path) as package:
            sheet = package.read("xl/worksheets/sheet1.xml").decode()
        self.assertIn("<f>SUM(B2:B2)</f><v>4</v>", sheet)
        self.assertIn("<f>MIN(B2:B2)</f><v>2.5</v>", sheet)

    def test_a_cell_that_already_has_a_value_is_left_alone(self):
        report = ooxml.finalise(self.path, cached={"Spray!D4": 1.0})
        self.assertEqual(report["skipped"], ["Spray!D4"])
        with zipfile.ZipFile(self.path) as package:
            sheet = package.read("xl/worksheets/sheet1.xml").decode()
        self.assertIn("<f>MAX(B2:B2)</f><v>99</v>", sheet)

    def test_a_cell_that_is_not_there_is_reported(self):
        report = ooxml.finalise(self.path, cached={"Spray!Z99": 1.0})
        self.assertEqual(report["missed"], ["Spray!Z99"])

    def test_an_unknown_sheet_is_reported(self):
        report = ooxml.finalise(self.path, cached={"Nowhere!B4": 1.0})
        self.assertEqual(report["missed"], ["Nowhere!B4"])

    def test_the_creator_becomes_the_business(self):
        ooxml.finalise(self.path, creator="Bellview Farm", title="Spray", stamp="2026-11-01T00:00:00Z")
        with zipfile.ZipFile(self.path) as package:
            core = package.read("docProps/core.xml").decode()
            app = package.read("docProps/app.xml").decode()
        self.assertIn("<dc:creator", core)
        self.assertIn("Bellview Farm", core)
        self.assertNotIn("openpyxl", core)
        self.assertIn("<dc:title", core)
        self.assertIn("Spray", core)
        self.assertIn("2026-11-01T00:00:00Z", core)
        self.assertNotIn("2026-01-01T00:00:00Z", core)
        self.assertIn("<Application>Pantler</Application>", app)

    def test_every_other_part_is_copied_through(self):
        with zipfile.ZipFile(self.path) as package:
            before = package.read("xl/styles.xml")
        ooxml.finalise(self.path, cached={"Spray!B4": 4.0}, creator="Bellview Farm")
        with zipfile.ZipFile(self.path) as package:
            after = package.read("xl/styles.xml")
        self.assertEqual(before, after)

    def test_nothing_to_do_is_not_an_error(self):
        report = ooxml.finalise(self.path, cached={}, application="")
        self.assertFalse(report["written"])
        self.assertEqual(report["missed"], [])


if __name__ == "__main__":
    unittest.main()
