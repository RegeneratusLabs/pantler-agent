"""The record book: one way to write a record, from either side of the seam.

The property worth testing is not "it saves" — the old in-memory ledger saved too. It is that what
it saves **survives the process**: a second book, opened on the same file, sees the record the
first one wrote. That is the difference between a record and a message, and it is what the invoice
path got wrong for long enough to be written down as a known gap.

    python3 -m unittest discover -s core/tests -t core/tests
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pantler_core import RecordBook, RecordBookError

REPO = Path(__file__).resolve().parents[2]
PACKS = REPO / "packs"


class RecordBookTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.path = Path(self._dir.name) / "records.db"
        self.book = RecordBook(self.path, PACKS)

    def tearDown(self) -> None:
        self.book.close()
        self._dir.cleanup()

    def certificate(self, **overrides) -> dict:
        fields = {"holder": "our business", "scheme": "ACO", "expires": "2027-03-31"}
        fields.update(overrides)
        return fields

    def test_a_saved_record_survives_the_process_that_wrote_it(self) -> None:
        saved = self.book.save("certificate", self.certificate())
        self.book.close()
        reopened = RecordBook(self.path, PACKS)
        try:
            again = reopened.get("certificate", saved.id)
            self.assertIsNotNone(again)
            assert again is not None
            self.assertEqual(again.data["scheme"], "ACO")
        finally:
            reopened.close()
        self.book = RecordBook(self.path, PACKS)  # so tearDown has something to close

    def test_ids_are_allocated_from_the_store_and_do_not_repeat(self) -> None:
        first = self.book.save("certificate", self.certificate())
        second = self.book.save("certificate", self.certificate(scheme="NASAA"))
        self.assertEqual((first.id, second.id), ("CERT-0001", "CERT-0002"))
        self.book.close()
        reopened = RecordBook(self.path, PACKS)
        try:
            third = reopened.save("certificate", self.certificate(scheme="USDA NOP"))
            self.assertEqual(third.id, "CERT-0003", "a restart must not restart the sequence")
        finally:
            reopened.close()
        self.book = RecordBook(self.path, PACKS)

    def test_every_problem_comes_back_at_once(self) -> None:
        with self.assertRaises(RecordBookError) as caught:
            self.book.save("application", {"date": "2026-10-16"})
        message = str(caught.exception)
        for field in ("Block", "Product", "Rate"):
            self.assertIn(field, message, message)

    def test_an_unknown_type_lists_the_installed_ones(self) -> None:
        with self.assertRaises(RecordBookError) as caught:
            self.book.save("unicorn", {})
        self.assertIn("certificate", str(caught.exception))

    def test_find_filters_by_field_and_by_word(self) -> None:
        self.book.save("certificate", self.certificate())
        self.book.save(
            "certificate",
            self.certificate(holder="a supplier", scheme="NASAA", supplier_name="Green Acres"),
        )
        ours = self.book.find("certificate", where={"holder": "our business"})
        self.assertEqual([r.data["scheme"] for r in ours], ["ACO"])
        named = self.book.find("certificate", contains="green acres")
        self.assertEqual([r.data["scheme"] for r in named], ["NASAA"])
        self.assertEqual(self.book.find("certificate", contains="nothing here"), [])

    def test_the_store_is_not_told_what_a_certificate_means(self) -> None:
        """The kernel validates against the pack and stores JSON — nothing more, by design."""
        saved = self.book.save("certificate", self.certificate(notes="renew in March"))
        self.assertIsInstance(saved.data, dict)
        self.assertEqual(saved.data["notes"], "renew in March")
        self.assertEqual(saved.pack, "farm")


if __name__ == "__main__":
    unittest.main()
