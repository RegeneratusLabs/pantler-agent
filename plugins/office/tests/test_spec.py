"""The spec translator: our small schema in, the engine's schema and the totals out."""

from __future__ import annotations

import sys
import unittest

from support import PLUGIN  # noqa: F401  (puts `plugins/` on sys.path)

from office.office_engine import spec as spec_engine


class Builds(unittest.TestCase):
    def test_a_simple_sheet(self):
        built = spec_engine.build({
            "sheet": "Spray",
            "columns": [{"header": "Block"}, {"header": "Rate", "type": "number", "total": True}],
            "rows": [["North", 2.5], ["South", 1.5]],
        })
        sheet = built.engine["sheets"][0]
        self.assertEqual(sheet["name"], "Spray")
        self.assertEqual(sheet["rows"][0][0]["value"], "Block")
        self.assertEqual(sheet["rows"][0][0]["fill"], "F1F1EF")
        self.assertEqual(sheet["rows"][1][1], {"value": 2.5, "format": "General"})
        self.assertEqual(sheet["freeze_panes"], "A2")
        self.assertEqual(sheet["autofilter"], "A1:B3")
        self.assertTrue(built.engine["full_calc_on_load"])

    def test_totals_are_a_formula_and_a_value(self):
        built = spec_engine.build({
            "sheet": "Money",
            "columns": [{"header": "Item"}, {"header": "Cost", "key": "cost", "type": "money",
                                             "total": True}],
            "rows": [{"cost": 120.50}, {"cost": 80.25}],
        })
        total = built.engine["sheets"][0]["rows"][-1][1]
        self.assertEqual(total["formula"], "SUM(B2:B3)")
        self.assertEqual(built.cached["Money!B4"], 200.75)
        self.assertEqual(built.sheets[0]["rows"][-1][1], "$200.75")

    def test_cents_add_up_like_cents(self):
        built = spec_engine.build({
            "sheet": "Cents",
            "columns": [{"header": "Cost", "type": "money", "total": True}],
            "rows": [[0.1], [0.2]],
        })
        self.assertEqual(built.cached["Cents!A4"], 0.3)

    def test_no_totals_unless_asked(self):
        built = spec_engine.build({
            "columns": [{"header": "Year", "type": "number"}],
            "rows": [[2025], [2026]],
        })
        self.assertEqual(built.cached, {})
        self.assertEqual(len(built.engine["sheets"][0]["rows"]), 3)

    def test_a_title_shifts_the_table_and_the_totals(self):
        built = spec_engine.build({
            "title": "Spray summary",
            "sheet": "Spray",
            "columns": [{"header": "Rate", "type": "number", "total": True}],
            "rows": [[1], [2]],
        })
        sheet = built.engine["sheets"][0]
        self.assertEqual(sheet["rows"][0][0]["value"], "Spray summary")
        self.assertNotIn("merges", sheet)   # one column is not a range worth merging
        self.assertEqual(sheet["freeze_panes"], "A3")
        self.assertEqual(sheet["autofilter"], "A2:A4")
        self.assertEqual(sheet["rows"][-1][0], {"formula": "SUM(A3:A4)", "format": "General",
                                                "bold": True})
        self.assertEqual(built.cached["Spray!A5"], 3)

    def test_percent_is_stored_as_a_fraction_and_shown_as_a_share(self):
        built = spec_engine.build({
            "columns": [{"header": "Rate", "type": "percent"}],
            "rows": [[0.155]],
        })
        self.assertEqual(built.engine["sheets"][0]["rows"][1][0]["value"], 0.155)
        self.assertEqual(built.engine["sheets"][0]["rows"][1][0]["format"], "0.0%")
        self.assertEqual(built.sheets[0]["rows"][0][0], "15.5%")

    def test_integer_column(self):
        built = spec_engine.build({"columns": [{"header": "Count", "type": "integer"}],
                                   "rows": [[12.0]]})
        self.assertEqual(built.engine["sheets"][0]["rows"][1][0]["value"], 12)
        self.assertEqual(built.sheets[0]["rows"][0][0], "12")

    def test_a_list_row_must_line_up(self):
        with self.assertRaises(spec_engine.SpecError) as caught:
            spec_engine.build({"columns": [{"header": "A"}, {"header": "B"}], "rows": [["only"]]})
        self.assertIn("row 1 has 1 value", str(caught.exception))

    def test_an_unknown_key_is_named(self):
        with self.assertRaises(spec_engine.SpecError) as caught:
            spec_engine.build({"columns": [{"header": "A"}], "rows": [{"nope": 1}]})
        self.assertIn("nope", str(caught.exception))

    def test_an_unknown_type_is_a_question(self):
        with self.assertRaises(spec_engine.SpecError) as caught:
            spec_engine.build({"columns": [{"header": "A", "type": "currency"}]})
        self.assertIn("use one of", str(caught.exception))

    def test_two_columns_cannot_share_a_key(self):
        with self.assertRaises(spec_engine.SpecError):
            spec_engine.build({"columns": [{"header": "A", "key": "x"},
                                           {"header": "B", "key": "x"}]})

    def test_a_reserved_sheet_character_is_refused(self):
        with self.assertRaises(spec_engine.SpecError) as caught:
            spec_engine.build({"sheet": "A/B", "columns": [{"header": "A"}]})
        self.assertIn("reserves", str(caught.exception))

    def test_totals_naming_an_unknown_column(self):
        with self.assertRaises(spec_engine.SpecError):
            spec_engine.build({"columns": [{"header": "A"}], "totals": ["zzz"]})

    def test_a_boolean_is_not_a_number(self):
        with self.assertRaises(spec_engine.SpecError):
            spec_engine.build({"columns": [{"header": "A", "type": "number"}], "rows": [[True]]})

    def test_two_sheets(self):
        built = spec_engine.build({"sheets": [
            {"name": "One", "columns": [{"header": "A"}], "rows": [["x"]]},
            {"name": "Two", "columns": [{"header": "B"}], "rows": [["y"]]},
        ]})
        self.assertEqual([sheet["name"] for sheet in built.engine["sheets"]], ["One", "Two"])

    def test_sheet_names_are_unique(self):
        with self.assertRaises(spec_engine.SpecError):
            spec_engine.build({"sheets": [
                {"name": "Same", "columns": [{"header": "A"}]},
                {"name": "Same", "columns": [{"header": "B"}]},
            ]})

    def test_widths_are_bounded(self):
        built = spec_engine.build({
            "columns": [{"header": "A", "width": 500}, {"header": "B", "width": 1},
                        {"header": "A long header for a column"}],
            "rows": [["x" * 100, "y", "z"]],
        })
        widths = built.engine["sheets"][0]["column_widths"]
        self.assertEqual(widths["A"], 60.0)
        self.assertEqual(widths["B"], 6.0)
        self.assertEqual(widths["C"], 28.0)   # the header decides; a 100-char value is column A


if __name__ == "__main__":
    unittest.main()
