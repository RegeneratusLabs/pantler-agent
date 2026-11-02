"""Rows from the operator's store: the cents conversion, and never a write."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from support import PLUGIN, ROOT  # noqa: F401

from office.office_engine import records

PACKS = ROOT / "packs"


class Values(unittest.TestCase):
    def test_cents_become_dollars(self):
        self.assertEqual(records._value("money", 12050), 120.5)
        self.assertEqual(records._value("money", 5), 0.05)

    def test_a_text_field_stays_text(self):
        self.assertEqual(records._value("text", 12), "12")

    def test_a_number_field_rejects_a_boolean(self):
        self.assertEqual(records._value("number", True), None)

    def test_a_missing_value_is_missing(self):
        self.assertEqual(records._value("money", None), None)


class Store(unittest.TestCase):
    def setUp(self):
        from pantler_core import RecordBook

        self._scratch = tempfile.TemporaryDirectory(prefix="pantler-records-")
        self.book = RecordBook(Path(self._scratch.name) / "records.db", PACKS)
        self.book.save("block", {"name": "North paddock", "area_ha": 2.5})
        self.book.save("block", {"name": "South paddock", "area_ha": 1.5})

    def tearDown(self):
        self.book.close()
        self._scratch.cleanup()

    def test_the_fields_become_columns_and_the_records_rows(self):
        table = records.rows(self.book, "block")
        headers = [column["header"] for column in table["columns"]]
        self.assertIn("Name", headers)
        self.assertIn("Area", headers)
        self.assertEqual(table["count"], 2)
        self.assertEqual(sorted(row[headers.index("Name")] for row in table["rows"]),
                         ["North paddock", "South paddock"])

    def test_only_the_asked_for_fields(self):
        table = records.rows(self.book, "block", columns=["name"])
        self.assertEqual([column["key"] for column in table["columns"]], ["name"])
        self.assertEqual(sorted(row[0] for row in table["rows"]),
                         ["North paddock", "South paddock"])

    def test_an_unknown_field_is_named_with_the_ones_that_exist(self):
        with self.assertRaises(records.RecordsError) as caught:
            records.rows(self.book, "block", columns=["nope"])
        self.assertIn("no field nope", str(caught.exception))
        self.assertIn("name", str(caught.exception))

    def test_an_unknown_type_lists_the_store(self):
        with self.assertRaises(records.RecordsError) as caught:
            records.rows(self.book, "spaceship")
        self.assertIn("This store holds", str(caught.exception))

    def test_a_date_range_without_a_date_field_is_refused(self):
        with self.assertRaises(records.RecordsError) as caught:
            records.rows(self.book, "block", since="2026-01-01")
        self.assertIn("no date field", str(caught.exception))

    def test_reading_never_writes(self):
        before = (Path(self._scratch.name) / "records.db").read_bytes()
        records.rows(self.book, "block")
        after = (Path(self._scratch.name) / "records.db").read_bytes()
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
