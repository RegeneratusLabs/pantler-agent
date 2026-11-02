"""The three tools, end to end, against a temporary workspace and the real vendored scripts."""

from __future__ import annotations

import json
import os
import subprocess
import unittest
from pathlib import Path

from support import INTERPRETER, ROOT, ToolCase, PLUGIN  # noqa: F401

SPEC = {
    "title": "Spray summary 2026",
    "sheet": "Spray 2026",
    "columns": [
        {"header": "Block", "key": "block"},
        {"header": "Rate (L/ha)", "key": "rate", "type": "number", "total": True},
        {"header": "Cost", "key": "cost", "type": "money", "total": True},
        {"header": "Applied", "key": "applied", "type": "date"},
    ],
    "rows": [
        {"block": "North paddock", "rate": 2.5, "cost": 120.50, "applied": "2026-10-14"},
        {"block": "South paddock", "rate": 1.5, "cost": 80.25, "applied": "2026-10-15"},
    ],
}


@unittest.skipUnless(INTERPRETER, "no interpreter with the office libraries")
class Creating(ToolCase):
    def test_a_workbook_its_preview_and_its_pdf(self):
        result = self.call(self.tools.xlsx_create, {"spec": SPEC})
        self.assertTrue(result["success"], result)
        workbook = Path(result["resolved_path"])
        self.assertTrue(workbook.is_file())
        self.assertEqual(workbook.suffix, ".xlsx")
        self.assertIn(str(workbook.with_suffix(".html")), result["files_written"])
        self.assertTrue(Path(result["preview_path"]).is_file())
        self.assertIn("Spray 2026: 2 rows, 4 columns, 2 totals", " ".join(result["checks"]))

    def test_the_totals_are_a_formula_and_a_value(self):
        result = self.call(self.tools.xlsx_create, {"spec": SPEC, "pdf": False})
        read = self.call(self.tools.office_read, {"path": result["resolved_path"],
                                                  "part": "formulas"})
        figures = {item["formula"]: item["cached"] for item in read["result"]["formulas"]}
        self.assertEqual(figures["=SUM(B3:B4)"], 4)
        self.assertEqual(figures["=SUM(C3:C4)"], 200.75)

    def test_the_creator_is_the_business_and_the_app_is_pantler(self):
        import zipfile

        result = self.call(self.tools.xlsx_create, {"spec": SPEC, "pdf": False})
        with zipfile.ZipFile(result["resolved_path"]) as package:
            core = package.read("docProps/core.xml").decode()
            app = package.read("docProps/app.xml").decode()
        self.assertIn("Bellview Farm", core)
        self.assertNotIn("openpyxl", core)
        self.assertIn("<Application>Pantler</Application>", app)

    def test_no_pdf_when_asked_not_to(self):
        result = self.call(self.tools.xlsx_create, {"spec": SPEC, "pdf": False})
        self.assertNotIn("pdf_path", result)

    def test_an_out_path_inside_the_workspace_is_honoured(self):
        result = self.call(self.tools.xlsx_create, {"spec": SPEC, "pdf": False,
                                                    "out": "output/book.xlsx"})
        # The temp workspace can sit under a Windows 8.3 short name (RUNNER~1), so compare the
        # file's identity rather than the spelling of the directory.
        self.assertTrue(
            os.path.samefile(Path(result["resolved_path"]), self.workspace / "output" / "book.xlsx")
        )

    def test_an_out_path_outside_the_workspace_is_refused(self):
        result = self.call(self.tools.xlsx_create, {"spec": SPEC, "out": "/tmp/elsewhere.xlsx"})
        self.assertFalse(result["success"])
        self.assertIn("outside this business's workspace", result["error"])

    def test_a_spec_that_is_a_string_is_refused(self):
        result = self.call(self.tools.xlsx_create, {"spec": "make me a spreadsheet"})
        self.assertFalse(result["success"])
        self.assertIn("object", result["error"])

    def test_the_second_workbook_of_the_day_does_not_overwrite_the_first(self):
        first = self.call(self.tools.xlsx_create, {"spec": SPEC, "pdf": False})
        second = self.call(self.tools.xlsx_create, {"spec": SPEC, "pdf": False})
        self.assertNotEqual(first["resolved_path"], second["resolved_path"])


@unittest.skipUnless(INTERPRETER, "no interpreter with the office libraries")
class Reading(ToolCase):
    def make(self, code: str, name: str) -> Path:
        path = self.workspace / name
        # The snippet is passed to `python -c`, so a Windows path's backslashes must be escaped
        # before they land inside a string literal: `C:\Users` is a `\U` escape to Python.
        injected = str(path).replace("\\", "\\\\").replace("'", "\\'")
        done = subprocess.run([INTERPRETER, "-c", code.replace("PATH", injected)],
                              capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr)
        return path

    def test_a_word_document(self):
        path = self.make(
            "from docx import Document\n"
            "d = Document()\n"
            "d.add_heading('Organic audit pack', 1)\n"
            "d.add_paragraph('Bellview Farm')\n"
            "t = d.add_table(rows=2, cols=2)\n"
            "t.cell(0, 0).text = 'Item'\n"
            "t.cell(1, 0).text = 'Kale'\n"
            "d.save('PATH')\n", "pack.docx")
        structure = self.call(self.tools.office_read, {"path": str(path), "part": "summary"})
        self.assertTrue(structure["success"], structure)
        self.assertEqual(structure["result"]["outline"][0]["text"], "Organic audit pack")
        self.assertEqual(structure["result"]["table_count"], 1)
        content = self.call(self.tools.office_read, {"path": str(path), "part": "content"})
        self.assertIn("Bellview Farm", content["result"]["body"])

    def test_a_deck(self):
        path = self.make(
            "from pptx import Presentation\n"
            "p = Presentation()\n"
            "s = p.slides.add_slide(p.slide_layouts[0])\n"
            "s.shapes.title.text = 'Market day'\n"
            "p.save('PATH')\n", "deck.pptx")
        outline = self.call(self.tools.office_read, {"path": str(path), "part": "summary"})
        self.assertTrue(outline["success"], outline)
        self.assertIn("Market day", json.dumps(outline["result"]))

    def test_a_workbook_reads_back_what_was_written(self):
        created = self.call(self.tools.xlsx_create, {"spec": SPEC, "pdf": False})
        rows = self.call(self.tools.office_read, {"path": created["resolved_path"],
                                                  "part": "content"})
        self.assertEqual(rows["result"]["sheet"], "Spray 2026")
        self.assertIn("North paddock", json.dumps(rows["result"]["rows"]))

    def test_max_rows_caps_what_is_returned(self):
        created = self.call(self.tools.xlsx_create, {"spec": SPEC, "pdf": False})
        rows = self.call(self.tools.office_read, {"path": created["resolved_path"],
                                                  "part": "content", "max_rows": 2})
        self.assertEqual(len(rows["result"]["rows"]), 2)
        self.assertIn("first 2 rows", rows["note"])

    def test_a_csv_is_not_an_office_document(self):
        path = self.workspace / "list.csv"
        path.write_text("a,b\n1,2\n")
        result = self.call(self.tools.office_read, {"path": str(path)})
        self.assertFalse(result["success"])
        self.assertIn("reads .xlsx, .docx and .pptx", result["error"])

    def test_a_formula_request_on_a_word_document_is_refused(self):
        path = self.make("from docx import Document\nDocument().save('PATH')\n", "empty.docx")
        result = self.call(self.tools.office_read, {"path": str(path), "part": "formulas"})
        self.assertFalse(result["success"])
        self.assertIn("can be read as", result["error"])

    def test_a_file_outside_the_workspace_is_refused(self):
        # `/etc/passwd` is not an absolute path on Windows, so the refusal (and its sentence)
        # comes from a different check. Use a path that is outside on the platform under test,
        # and assert the half both refusals share.
        outside = "C:\\Windows\\win.ini" if os.name == "nt" else "/etc/passwd"
        result = self.call(self.tools.office_read, {"path": outside})
        self.assertFalse(result["success"])
        self.assertIn("outside this business's workspace", result["error"])


@unittest.skipUnless(INTERPRETER, "no interpreter with the office libraries")
class Editing(ToolCase):
    def make_book(self) -> Path:
        created = self.call(self.tools.xlsx_create, {"spec": SPEC, "pdf": False})
        return Path(created["resolved_path"])

    def test_set_cells_writes_a_copy(self):
        source = self.make_book()
        before = source.read_bytes()
        result = self.call(self.tools.xlsx_edit, {
            "path": str(source), "op": "set_cells", "cells": {"A3": "North block"}})
        self.assertTrue(result["success"], result)
        self.assertNotEqual(result["resolved_path"], str(source))
        self.assertEqual(source.read_bytes(), before)
        rows = self.call(self.tools.office_read, {"path": result["resolved_path"],
                                                  "part": "content"})
        self.assertIn("North block", json.dumps(rows["result"]["rows"]))

    def test_a_number_looking_string_is_reported_as_stored_as_a_number(self):
        source = self.make_book()
        result = self.call(self.tools.xlsx_edit, {
            "path": str(source), "op": "set_cells", "cells": {"A3": "007"}})
        self.assertTrue(result["success"], result)
        self.assertIn("stored as a number", " ".join(result["changes"]))

    def test_appending_rows(self):
        source = self.make_book()
        result = self.call(self.tools.xlsx_edit, {
            "path": str(source), "op": "append_rows",
            "rows": [["East paddock", 1.0, 10.5, "2026-10-16"]]})
        self.assertTrue(result["success"], result)
        self.assertIn("1 row(s) appended", " ".join(result["changes"]))
        rows = self.call(self.tools.office_read, {"path": result["resolved_path"],
                                                  "part": "content"})
        self.assertIn("East paddock", json.dumps(rows["result"]["rows"]))
        self.assertTrue(result["not_done"])

    def test_renaming_a_sheet(self):
        source = self.make_book()
        result = self.call(self.tools.xlsx_edit, {
            "path": str(source), "op": "rename_sheet", "from": "Spray 2026", "to": "Spray"})
        self.assertTrue(result["success"], result)
        summary = self.call(self.tools.office_read, {"path": result["resolved_path"],
                                                     "part": "summary"})
        self.assertEqual(summary["result"]["sheets"][0]["name"], "Spray")

    def test_editing_in_place_is_refused(self):
        source = self.make_book()
        result = self.call(self.tools.xlsx_edit, {
            "path": str(source), "op": "set_cells", "cells": {"A3": "x"}, "out": str(source)})
        self.assertFalse(result["success"])
        self.assertIn("overwrite the original", result["error"])

    def test_an_unknown_operation_is_named(self):
        source = self.make_book()
        result = self.call(self.tools.xlsx_edit, {"path": str(source), "op": "delete_sheet"})
        self.assertFalse(result["success"])
        self.assertIn("set_cells, append_rows or rename_sheet", result["error"])

    def test_a_cell_reference_is_checked(self):
        source = self.make_book()
        result = self.call(self.tools.xlsx_edit, {
            "path": str(source), "op": "set_cells", "cells": {"not-a-cell": 1}})
        self.assertFalse(result["success"])
        self.assertIn("cell reference", result["error"])

    def test_a_word_document_is_not_edited_here(self):
        path = self.workspace / "letter.docx"
        path.write_bytes(b"PK\x03\x04")
        result = self.call(self.tools.xlsx_edit, {"path": str(path), "op": "set_cells",
                                                  "cells": {"A1": 1}})
        self.assertFalse(result["success"])
        self.assertIn("edits .xlsx", result["error"])


@unittest.skipUnless(INTERPRETER, "no interpreter with the office libraries")
class Source(ToolCase):
    def test_rows_come_from_the_store(self):
        from pantler_core import RecordBook

        store = self.workspace / "records.db"
        book = RecordBook(store, ROOT / "packs")
        book.save("block", {"name": "North paddock", "area_ha": 2.5})
        book.save("block", {"name": "South paddock", "area_ha": 1.5})
        book.close()
        self.tools._CTX.settings.update({"store_path": str(store),
                                         "packs_dir": str(ROOT / "packs")})
        result = self.call(self.tools.xlsx_create, {
            "spec": {"title": "Blocks"},
            "source": {"kind": "records", "type": "block"}, "pdf": False})
        self.assertTrue(result["success"], result)
        rows = self.call(self.tools.office_read, {"path": result["resolved_path"],
                                                  "part": "content"})
        text = json.dumps(rows["result"]["rows"])
        self.assertIn("North paddock", text)
        self.assertIn("South paddock", text)

    def test_an_unknown_record_type_is_refused(self):
        from pantler_core import RecordBook

        store = self.workspace / "records.db"
        RecordBook(store, ROOT / "packs").close()
        self.tools._CTX.settings.update({"store_path": str(store),
                                         "packs_dir": str(ROOT / "packs")})
        result = self.call(self.tools.xlsx_create, {
            "spec": {"title": "x"}, "source": {"kind": "records", "type": "spaceship"},
            "pdf": False})
        self.assertFalse(result["success"])
        self.assertIn("This store holds", result["error"])


class Switched(ToolCase):
    settings = {"capability_enabled": False}

    def test_every_tool_says_it_is_off(self):
        for handler in (self.tools.office_read, self.tools.xlsx_create, self.tools.xlsx_edit):
            result = self.call(handler, {"path": "x.xlsx", "spec": {}, "op": "set_cells"})
            self.assertFalse(result["success"])
            self.assertIn("switched off in Capabilities", result["error"])


if __name__ == "__main__":
    unittest.main()
