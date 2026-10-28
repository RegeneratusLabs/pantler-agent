"""The spray engine: resolution, arithmetic, and the places it refuses to compute.

The tests that matter most are the refusals. Every other number here is a multiplication; the
product's claim is that a withholding period is never supplied by the assistant, so the cases below
pin that: a missing period leaves the field empty, a rate above the label maximum comes back as a
question rather than a clamp, and an unknown or ambiguous name is a question rather than a guess.

    python3 -m unittest discover -s plugins/spray/tests -t plugins/spray/tests
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parent
REPO = PLUGIN.parent.parent
sys.path.insert(0, str(REPO / "core" / "src"))
sys.path.insert(0, str(PLUGIN))

from sprayengine import SprayBook, record_application  # noqa: E402

BOOK = HERE / "fixtures" / "spraybook.json"


class CatalogueTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.book = SprayBook.from_json_file(BOOK)

    def test_exact_and_alias_resolution(self) -> None:
        self.assertEqual(self.book.resolve_block("North block").id, "BLK-001")
        self.assertEqual(self.book.resolve_block("the north").id, "BLK-001")
        self.assertEqual(self.book.resolve_input("copper").id, "INP-001")
        self.assertEqual(self.book.resolve_input("sulfur").id, "INP-002")

    def test_a_partial_name_resolves_when_only_one_thing_matches(self) -> None:
        self.assertEqual(self.book.resolve_input("oxychloride").id, "INP-001")

    def test_an_unknown_name_is_a_question_listing_what_is_known(self) -> None:
        from pantler_core import Unknown

        with self.assertRaises(Unknown) as caught:
            self.book.resolve_input("glyphosate")
        question = caught.exception.as_question()
        self.assertIn("glyphosate", question)
        self.assertIn("Copper oxychloride 500", question)

    def test_an_ambiguous_name_is_a_question_rather_than_a_pick(self) -> None:
        from pantler_core import Ambiguous

        book = SprayBook.from_dict(
            {
                "inputs": [
                    {"id": "A", "name": "Copper oxychloride 500"},
                    {"id": "B", "name": "Copper sulphate"},
                ]
            }
        )
        with self.assertRaises(Ambiguous) as caught:
            book.resolve_input("copper")
        self.assertIn("which did you mean", caught.exception.as_question())


class ApplicationTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.book = SprayBook.from_json_file(BOOK)

    def record(self, **overrides):
        params = dict(
            applied="2026-10-14",
            block="north block",
            product="copper",
            rate=2.5,
            rate_unit="kg/ha",
        )
        params.update(overrides)
        return record_application(self.book, **params)

    def test_rate_times_area_and_the_earliest_safe_date(self) -> None:
        result = self.record()
        self.assertTrue(result["success"], result)
        record = result["record"]
        self.assertEqual(record["block"], "BLK-001")
        self.assertEqual(record["input"], "INP-001")
        self.assertEqual(record["area_ha"], 3.5)
        self.assertEqual(result["product_used"], {"amount": 8.75, "unit": "kg"})
        self.assertEqual(record["withholding_days"], 1)
        self.assertEqual(record["earliest_safe_date"], "2026-10-15")
        self.assertEqual(result["registration"], "APVMA 12345 (label on file)")
        # Using the block's own area is worth saying out loud.
        self.assertTrue(any("area on file" in w for w in result["warnings"]))

    def test_an_explicit_area_wins_over_the_block_record(self) -> None:
        result = self.record(area_ha=1)
        self.assertEqual(result["record"]["area_ha"], 1)
        self.assertEqual(result["product_used"], {"amount": 2.5, "unit": "kg"})

    def test_a_product_with_no_withholding_period_leaves_it_empty(self) -> None:
        """The case the whole product argument rests on: never supply a label fact."""
        result = self.record(product="fish emulsion", rate=5, rate_unit="L/ha")
        self.assertTrue(result["success"], result)
        record = result["record"]
        self.assertIsNone(record["withholding_days"])
        self.assertIsNone(record["earliest_safe_date"])
        self.assertTrue(
            any("No withholding period is on file" in w for w in result["warnings"]), result
        )

    def test_a_rate_above_the_label_maximum_is_a_question_not_a_clamp(self) -> None:
        result = self.record(rate=4)
        self.assertEqual(result["record"]["rate"], 4)  # recorded as given, not adjusted
        self.assertTrue(result["questions"], result)
        self.assertIn("above the label maximum", result["questions"][0])
        self.assertTrue(any("above the maximum on file" in w for w in result["warnings"]))

    def test_a_rate_in_a_different_unit_is_not_compared(self) -> None:
        # Volume against a mass maximum is a genuine dimension mismatch: there is no conversion,
        # so the honest answer is that the two were not compared (A19-PLUG-4). The unit used to be
        # `g/ha` here, which is *not* a mismatch — the fix compares it with the `kg/ha` maximum,
        # and 2500 g/ha is under 3 kg/ha.
        result = self.record(rate=2500, rate_unit="mL/ha")
        self.assertTrue(result["success"], result)
        self.assertTrue(any("cannot compare" in w for w in result["warnings"]), result)
        self.assertEqual(result["questions"], [])

    def test_a_maximum_is_compared_across_compatible_area_units(self) -> None:
        """`25000 mL/ha` is 25 L/ha, and a `2.0 L/ha` maximum has to see it.

        The units were compared as strings, so a rate spelt differently from the label was never
        checked against it at all — the audit's 25,000 mL/ha went past a 2.0 L/ha ceiling with no
        warning and no question (the internal security audit A19-PLUG-4).
        """
        book = SprayBook.from_dict(
            {
                "blocks": [{"id": "B", "name": "Block", "area_ha": 2}],
                "inputs": [
                    {
                        "id": "I",
                        "name": "Oil",
                        "unit": "L",
                        "withholding_days": 7,
                        "max_rate": 2.0,
                        "max_rate_unit": "L/ha",
                    }
                ],
            }
        )
        over = record_application(
            book, applied="2026-01-01", block="block", product="oil", rate=25000, rate_unit="mL/ha"
        )
        self.assertTrue(over["success"], over)
        self.assertTrue(any("above the maximum on file" in w for w in over["warnings"]), over)
        self.assertTrue(over["questions"], "a rate over the label maximum produced no question")
        self.assertTrue(any("converting" in w for w in over["warnings"]), over)

        # The same quantity, written the other way up, gets the same answer: the comparison is of
        # the quantities, not of the spelling.
        under = record_application(
            book, applied="2026-01-01", block="block", product="oil", rate=1.5, rate_unit="L/ha"
        )
        self.assertEqual(under["questions"], [], under)

    def test_a_maximum_is_compared_across_compatible_mass_units(self) -> None:
        """`2500 g/ha` and `3 kg/ha` are a comparison, not a spelling difference (A19-PLUG-4)."""
        book = SprayBook.from_dict(
            {
                "blocks": [{"id": "B", "name": "Block", "area_ha": 2}],
                "inputs": [
                    {
                        "id": "I",
                        "name": "Copper",
                        "unit": "kg",
                        "withholding_days": 1,
                        "max_rate": 3,
                        "max_rate_unit": "kg/ha",
                    }
                ],
            }
        )
        under = record_application(
            book, applied="2026-01-01", block="block", product="copper", rate=2500, rate_unit="g/ha"
        )
        self.assertEqual(under["questions"], [], under)
        over = record_application(
            book, applied="2026-01-01", block="block", product="copper", rate=4000, rate_unit="g/ha"
        )
        self.assertTrue(any("above the maximum on file" in w for w in over["warnings"]), over)

    def test_a_per_hectare_rate_is_not_compared_with_a_concentration_rate(self) -> None:
        """`mL/100L` and `L/ha` are different sums, not different spellings of one (A19-PLUG-4)."""
        book = SprayBook.from_dict(
            {
                "blocks": [{"id": "B", "name": "Block", "area_ha": 2}],
                "inputs": [
                    {
                        "id": "I",
                        "name": "Oil",
                        "unit": "L",
                        "withholding_days": 7,
                        "max_rate": 2.0,
                        "max_rate_unit": "L/ha",
                    }
                ],
            }
        )
        result = record_application(
            book, applied="2026-01-01", block="block", product="oil", rate=100, rate_unit="mL/100L"
        )
        self.assertTrue(any("cannot compare" in w for w in result["warnings"]), result)

    def test_a_concentration_rate_says_what_it_cannot_compute(self) -> None:
        result = self.record(rate=100, rate_unit="mL/100L")
        self.assertTrue(result["success"], result)
        self.assertIsNone(result["product_used"])
        self.assertTrue(any("concentration rate" in w for w in result["warnings"]), result)

    def test_mass_and_volume_are_converted_to_the_unit_the_product_is_sold_in(self) -> None:
        book = SprayBook.from_dict(
            {
                "blocks": [{"id": "B", "name": "Block", "area_ha": 2}],
                "inputs": [
                    {"id": "I", "name": "Oil", "unit": "mL", "withholding_days": 0}
                ],
            }
        )
        result = record_application(
            book, applied="2026-01-01", block="block", product="oil", rate=1.5, rate_unit="L/ha"
        )
        self.assertEqual(result["product_used"], {"amount": 3000, "unit": "mL"})

    def test_relative_days_are_resolved_in_code(self) -> None:
        """"Yesterday" is a subtraction; it happens here, not in the model.

        Copper oxychloride has a 1-day withholding period on file, so the expected earliest safe
        date is one day after whichever day the word resolved to — which is the whole point of
        resolving it in code rather than trusting a model's date arithmetic.
        """
        from datetime import date as _date

        today = _date(2026, 10, 16)
        for word, applied, earliest in (
            ("yesterday", "2026-10-15", "2026-10-16"),
            ("today", "2026-10-16", "2026-10-17"),
        ):
            with self.subTest(word=word):
                result = record_application(
                    self.book,
                    applied=word,
                    block="north block",
                    product="copper",
                    rate=1,
                    rate_unit="kg/ha",
                    today=today,
                )
                self.assertTrue(result["success"], result)
                self.assertEqual(result["record"]["date"], applied)
                self.assertEqual(result["record"]["earliest_safe_date"], earliest)

    def test_an_unreadable_date_is_refused(self) -> None:
        result = self.record(applied="last Tuesday")
        self.assertFalse(result["success"])
        self.assertIn("date", result["question"])

    def test_an_unknown_rate_unit_lists_the_ones_that_work(self) -> None:
        result = self.record(rate_unit="cups/ha")
        self.assertFalse(result["success"])
        self.assertIn("kg/ha", result["question"])

    def test_an_unknown_block_or_product_is_a_question(self) -> None:
        for overrides in ({"block": "south forty"}, {"product": "glyphosate"}):
            with self.subTest(**overrides):
                result = self.record(**overrides)
                self.assertFalse(result["success"])
                self.assertTrue(result["question"])

    def test_a_block_with_no_area_asks_for_one_instead_of_guessing(self) -> None:
        book = SprayBook.from_dict(
            {
                "blocks": [{"id": "B", "name": "Block"}],
                "inputs": [{"id": "I", "name": "Oil", "unit": "L", "withholding_days": 7}],
            }
        )
        result = record_application(
            book, applied="2026-01-01", block="block", product="oil", rate=2, rate_unit="L/ha"
        )
        self.assertTrue(result["success"], result)
        self.assertIsNone(result["product_used"])
        self.assertTrue(any("How many hectares" in q for q in result["questions"]), result)

    def test_the_record_carries_the_fields_the_pack_declares(self) -> None:
        """The tool result is the record: its keys are the `application` type's fields."""
        pack = (REPO / "packs" / "farm" / "pack.toml").read_text()
        record = self.record()["record"]
        for field in (
            "date",
            "block",
            "input",
            "rate",
            "rate_unit",
            "area_ha",
            "operator",
            "withholding_days",
            "earliest_safe_date",
            "notes",
        ):
            self.assertIn(field, record, f"the record has no {field}")
            self.assertIn(f"name = \"{field}\"", pack, f"the pack declares no {field} field")


if __name__ == "__main__":
    unittest.main()
