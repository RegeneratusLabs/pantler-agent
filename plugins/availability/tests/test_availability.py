"""The availability engine and its tool, tested on the things that would quietly go wrong.

Three properties matter more than the arithmetic here, and each has a test that would fail loudly:

* **No price ever reaches the list.** Availability is not a quotation. The test walks the serialised
  result for a currency symbol and for the catalogue's own price field, so a helpful future change
  that adds "…at $12/kg" fails rather than shipping.
* **Nothing is dropped.** An item nobody matched stays on the list, as spoken, with the note that
  says to promote it into the catalogue.
* **A quantity that was not said is not invented.** "a few punnets" is an approximate, flagged, and
  the list asks for a number rather than printing a plausible one.

    python3 -m unittest discover -s plugins/availability/tests -t plugins/availability/tests
"""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from fractions import Fraction
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parent
REPO = PLUGIN.parent.parent
sys.path.insert(0, str(REPO / "core" / "src"))
sys.path.insert(0, str(PLUGIN))

from pantler_core import price_book_from_json  # noqa: E402
from availabilityengine import build_list, parse_line  # noqa: E402

# The plugin's own copy. It used to read the demo's price book, so editing the demo changed a
# plugin's test inputs — and a price book is data the operator owns, which makes that a strange
# thing for a test to depend on (the internal audit SCR-7).
PRICEBOOK = HERE / "fixtures" / "pricebook.json"


def book():
    return price_book_from_json(PRICEBOOK)


class ParseLineTestCase(unittest.TestCase):
    def test_a_digit_quantity_with_a_unit_word(self) -> None:
        line = parse_line("twelve kilos of beans")
        self.assertEqual((line.quantity, line.unit, line.item_text), (12, "kg", "beans"))

    def test_a_number_word_keeps_its_own_count(self) -> None:
        line = parse_line("four dozen eggs")
        self.assertEqual((line.quantity, line.unit, line.item_text), (4, "dozen", "eggs"))

    def test_half_is_a_quantity_not_a_word_to_drop(self) -> None:
        line = parse_line("half a kilo of cos")
        self.assertEqual((line.quantity, line.unit), (1 / 2, "kg"))

    def test_a_mixed_number_keeps_its_whole_part(self) -> None:
        """"3 and a half punnets" is three and a half punnets of rocket, not half a punnet.

        The half-branch of the reader matched "half punnets" first and threw the three away,
        leaving it in the item name — so the customer-facing list carried the wrong quantity and
        an item called "3 and a rocket" (the internal audit PLUG-3).
        """
        line = parse_line("3 and a half punnets of rocket")
        self.assertEqual((line.quantity, line.unit, line.item_text), (Fraction(7, 2), "punnet", "rocket"))

        spelled = parse_line("two and a half kilos of beans")
        self.assertEqual(
            (spelled.quantity, spelled.unit, spelled.item_text), (Fraction(5, 2), "kg", "beans")
        )

    def test_a_half_with_no_whole_number_is_still_a_half(self) -> None:
        for text in ("half a punnet of rocket", "half punnet of rocket"):
            with self.subTest(text=text):
                line = parse_line(text)
                self.assertEqual((line.quantity, line.unit, line.item_text), (Fraction(1, 2), "punnet", "rocket"))

    def test_the_item_keeps_the_words_the_operator_used(self) -> None:
        """An adjective is part of a name, and the name is what the catalogue is searched with.

        `_clean` stripped `fresh`, `new` and `ready` wherever they appeared, so "fresh farm eggs"
        was looked up as "farm eggs" — a different product, and one the operator may not sell
        (the internal audit PLUG-16).
        """
        for spoken, expected in (
            ("2 dozen fresh farm eggs", "fresh farm eggs"),
            ("5 kg new potatoes", "new potatoes"),
            ("3 punnets of rocket", "rocket"),
        ):
            with self.subTest(spoken=spoken):
                self.assertEqual(parse_line(spoken).item_text, expected)

    def test_an_approximate_quantity_is_flagged_and_not_invented(self) -> None:
        line = parse_line("a few punnets of rocket")
        self.assertIsNone(line.quantity)
        self.assertEqual((line.unit, line.item_text, line.approximate), ("punnet", "rocket", "a few"))

    def test_a_bare_unit_at_the_start_is_the_unit(self) -> None:
        line = parse_line("boxes of cherries")
        self.assertEqual((line.quantity, line.unit, line.item_text), (None, "box", "cherries"))

    def test_a_unit_word_inside_an_item_name_is_not_eaten(self) -> None:
        """"Mixed Salad Box" is an item, so a trailing unit word stays where it is."""
        line = parse_line("salad box")
        self.assertEqual((line.unit, line.item_text), ("", "salad box"))

    def test_a_line_with_no_quantity_at_all_is_still_a_line(self) -> None:
        line = parse_line("zucchini")
        self.assertEqual((line.quantity, line.item_text), (None, "zucchini"))

    def test_a_number_too_large_to_convert_is_not_a_quantity(self) -> None:
        """A 400-digit quantity is an argument built to overflow a float, not a count.

        `Fraction(...)` reached `build._number`, whose float conversion raised `OverflowError`
        out of the tool (the internal security audit A19-PLUG-5). The line keeps the digits
        as spoken and gets the ordinary "no quantity" question instead.
        """
        line = parse_line("9" * 400 + ".9 punnets of rocket")
        self.assertIsNone(line.quantity)
        self.assertIn("9" * 20, line.item_text, "the digits were dropped rather than kept")
        self.assertIn("rocket", line.item_text)


class BuildListTestCase(unittest.TestCase):
    def build(self, *lines: str) -> dict:
        return build_list(book(), list(lines))

    def test_the_list_is_unpriced_end_to_end(self) -> None:
        """The property that makes it an availability list rather than a quotation."""
        result = self.build("twelve kilos of beans", "four dozen eggs", "two boxes of cherries")
        serialised = json.dumps(result)
        self.assertFalse(result["priced"])
        self.assertNotIn("$", serialised)
        self.assertNotIn("unit_price_cents", serialised)
        self.assertNotIn("1200", serialised)

    def test_an_unmatched_item_is_kept_and_offered_for_promotion(self) -> None:
        result = self.build("a few punnets of rocket")
        line = result["lines"][0]
        self.assertEqual(line["status"], "unmatched")
        self.assertIn("rocket", line["display"])
        self.assertTrue(any("Not in the catalogue" in note for note in line["notes"]))
        self.assertEqual(result["counts"]["unmatched"], 1)
        # And it is on the list the operator would send, not hidden in the detail.
        self.assertIn("rocket", " ".join(result["list"]).casefold())

    def test_a_missing_quantity_becomes_a_question_the_operator_can_answer(self) -> None:
        result = self.build("a few punnets of rocket")
        self.assertEqual(result["counts"]["without_quantity"], 1)
        self.assertTrue(any("No quantity was said" in note for note in result["lines"][0]["notes"]))
        self.assertIn("quantity to confirm", result["lines"][0]["display"])

    def test_an_alias_resolves_without_a_question(self) -> None:
        result = self.build("tomatoes")
        line = result["lines"][0]
        self.assertEqual(line["status"], "matched")  # the catalogue's own alias
        self.assertEqual(line["item"], "Cherry Tomatoes")
        self.assertEqual(result["questions"], [])

    def test_a_spoken_unit_that_differs_from_the_catalogue_is_left_as_said(self) -> None:
        result = self.build("three kilos of cherry tomatoes")
        line = result["lines"][0]
        self.assertEqual(line["status"], "matched")
        self.assertEqual(line["quantity"], 3)
        self.assertTrue(any("catalogue lists this by" in note for note in line["notes"]))

    def test_an_alias_resolves_to_the_catalogue_name(self) -> None:
        result = self.build("two kilos of courgettes")
        self.assertEqual(result["lines"][0]["item"], "Zucchini")
        self.assertEqual(result["lines"][0]["item_id"], "ITM-003")

    def test_a_genuinely_ambiguous_name_asks_rather_than_picking(self) -> None:
        """Two catalogue items, one word: the tool never chooses between them."""
        from pantler_core import price_book_from_dict

        book_with_two = price_book_from_dict(
            {
                "currency": "AUD",
                "tax_rate_bp": 1000,
                "customers": [
                    {"id": "C1", "name": "Someone", "terms_days": 7},
                ],
                # Both start with the word asked for, so they tie at the same resolution tier and
                # the kernel refuses to choose (its own tier order is id, name, alias, prefix,
                # word — a prefix hit beats a word hit, which is why "tomato" alone against
                # "Tomato Passata" resolves rather than asking).
                "items": [
                    {"id": "A", "name": "Tomato Passata", "unit": "each", "unit_price_cents": 900},
                    {"id": "B", "name": "Tomato Sauce", "unit": "each", "unit_price_cents": 800},
                ],
            }
        )
        result = build_list(book_with_two, ["six boxes of tomato"])
        self.assertEqual(result["lines"][0]["status"], "ambiguous")
        self.assertTrue(result["questions"], result)
        self.assertIn("which did you mean", result["questions"][0])
        self.assertEqual(sorted(result["lines"][0]["candidates"]), ["A", "B"])

    def test_the_counts_add_up_to_what_was_said(self) -> None:
        result = self.build("twelve kilos of beans", "rocket", "four dozen eggs")
        counts = result["counts"]
        self.assertEqual(counts["said"], 3)
        self.assertEqual(counts["matched"] + counts["unmatched"] + counts["ambiguous"], 3)

    def test_a_blank_line_is_reported_rather_than_silently_skipped(self) -> None:
        result = self.build("twelve kilos of beans", "   ")
        self.assertEqual(result["counts"]["said"], 2)
        self.assertEqual(result["lines"][1]["status"], "empty")

    def test_an_absurd_quantity_is_answered_with_a_question_not_a_traceback(self) -> None:
        """The list survives a line no farm wrote, and says what it could not read.

        (the internal security audit A19-PLUG-5)
        """
        result = self.build("9" * 400 + ".9 punnets of rocket")
        self.assertTrue(result["success"], result)
        self.assertEqual(result["counts"]["without_quantity"], 1)
        self.assertTrue(
            any("No quantity was said" in note for note in result["lines"][0]["notes"]), result
        )
        self.assertIn("9" * 20, result["lines"][0]["said"])
        json.dumps(result)  # every number in the answer is serialisable

    def test_the_serialiser_cannot_raise_on_a_hostile_fraction(self) -> None:
        """A caller-built `Fraction` beyond a float is converted, not raised."""
        from availabilityengine.build import _number

        self.assertIsInstance(_number(Fraction(10 ** 400, 3)), int)


class PluginTestCase(unittest.TestCase):
    class Ctx:
        def __init__(self, **settings):
            self.settings, self.tools = settings, []

        def register_tool(self, **kw):
            self.tools.append(kw)

        def get_config(self, key=None, default=None):
            return dict(self.settings) if key is None else self.settings.get(key, default)

    def load(self, **settings):
        for name in [n for n in sys.modules if n == "availability_plugin" or n.startswith("availability_plugin.")]:
            del sys.modules[name]
        spec = importlib.util.spec_from_file_location(
            "availability_plugin", PLUGIN / "__init__.py",
            submodule_search_locations=[str(PLUGIN)],
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules["availability_plugin"] = module
        spec.loader.exec_module(module)
        ctx = self.Ctx(**settings)
        module.register(ctx)
        return module, ctx

    def call(self, ctx, params):
        handler = next(tool["handler"] for tool in ctx.tools if tool["name"] == "availability_list")
        return json.loads(handler(params))

    def test_one_tool_under_its_own_toolset(self) -> None:
        _, ctx = self.load(pricebook_path=str(PRICEBOOK))
        self.assertEqual([t["name"] for t in ctx.tools], ["availability_list"])
        self.assertEqual({t["toolset"] for t in ctx.tools}, {"availability"})

    def test_the_schema_forbids_adding_prices(self) -> None:
        _, ctx = self.load(pricebook_path=str(PRICEBOOK))
        description = ctx.tools[0]["schema"]["description"]
        self.assertIn("NO PRICES", description)

    def test_a_list_comes_back_from_spoken_lines(self) -> None:
        _, ctx = self.load(pricebook_path=str(PRICEBOOK))
        result = self.call(ctx, {"lines": ["twelve kilos of beans", "a few punnets of rocket"]})
        self.assertTrue(result["success"], result)
        self.assertEqual(result["counts"]["said"], 2)
        self.assertNotIn("$", json.dumps(result))

    def test_a_switched_off_capability_refuses(self) -> None:
        _, ctx = self.load(pricebook_path=str(PRICEBOOK), capability_enabled=False)
        result = self.call(ctx, {"lines": ["beans"]})
        self.assertFalse(result["success"])
        self.assertIn("switched off in Capabilities", result["error"])

    def test_no_catalogue_says_where_one_goes(self) -> None:
        _, ctx = self.load()
        result = self.call(ctx, {"lines": ["beans"]})
        self.assertFalse(result["success"])
        self.assertIn("catalogue", result["error"])

    def test_lines_may_arrive_as_one_blob(self) -> None:
        _, ctx = self.load(pricebook_path=str(PRICEBOOK))
        result = self.call(ctx, {"lines": "twelve kilos of beans\nfour dozen eggs\n"})
        self.assertEqual(result["counts"]["said"], 2)


if __name__ == "__main__":
    unittest.main()
