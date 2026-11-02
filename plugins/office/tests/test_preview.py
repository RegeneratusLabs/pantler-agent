"""The preview page: escaped, self-contained, and the finished form of the table."""

from __future__ import annotations

import unittest

from support import PLUGIN  # noqa: F401
from office.office_engine import preview, spec as spec_engine


def render(rows, columns, **extra):
    built = spec_engine.build({"sheet": "Spray", "columns": columns, "rows": rows, **extra})
    return preview.workbook_html(built, title="Spray summary", meta="Bellview Farm")


class Pages(unittest.TestCase):
    def test_a_cell_is_text_not_markup(self):
        page = render([["<script>alert(1)</script>", 1]], [{"header": "Block"}, {"header": "Rate"}])
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;script&gt;", page)

    def test_a_header_is_escaped_too(self):
        page = render([["x", 1]], [{"header": "<b>Block</b>"}, {"header": "Rate"}])
        self.assertNotIn("<b>Block</b>", page)
        self.assertIn("&lt;b&gt;Block&lt;/b&gt;", page)

    def test_nothing_is_loaded_from_anywhere(self):
        page = render([["x", 1]], [{"header": "Block"}, {"header": "Rate"}])
        self.assertNotIn("http://", page)
        self.assertNotIn("https://", page)
        self.assertNotIn("<script", page)
        self.assertNotIn("src=", page)

    def test_the_total_row_is_marked(self):
        page = render([["North", 2.5], ["South", 1.5]],
                      [{"header": "Block"}, {"header": "Rate", "type": "number", "total": True}])
        self.assertIn('class="total"', page)
        self.assertIn("4", page)

    def test_money_is_shown_with_its_symbol_and_cents(self):
        page = render([["Seed", 120.5]], [{"header": "Item"}, {"header": "Cost", "type": "money"}])
        self.assertIn("$120.50", page)

    def test_an_empty_sheet_still_renders(self):
        page = render([], [{"header": "Block"}])
        self.assertIn("<table>", page)

    def test_an_unknown_accent_falls_back(self):
        built = spec_engine.build({"columns": [{"header": "A"}], "rows": [["x"]]})
        page = preview.workbook_html(built, accent="javascript:alert(1)")
        self.assertNotIn("javascript", page)


if __name__ == "__main__":
    unittest.main()
