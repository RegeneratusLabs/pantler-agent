"""The claims lint, tested on the sentences that decide whether it is trustworthy.

A lint earns its place by being right about the two cases that matter: the claim that must never be
written (a health claim), and the ordinary word that must not be stripped ("green beans", "fresh
bread"). Everything else is vocabulary. The tests below pin both, plus the two behaviours that are
easy to get wrong and expensive to get wrong: health always beats every other verdict, and the tool
never rewrites the copy it is given.

    python3 -m unittest discover -s plugins/claims/tests -t plugins/claims/tests
"""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parent
REPO = PLUGIN.parent.parent
sys.path.insert(0, str(REPO / "core" / "src"))
sys.path.insert(0, str(PLUGIN))

from claimsengine import check, report  # noqa: E402


class VocabularyTestCase(unittest.TestCase):
    def categories(self, text: str) -> set[str]:
        return {finding.category for finding in check(text)}

    def test_a_health_claim_is_found_and_refused(self) -> None:
        result = report("Our garlic boosts immunity and helps you lose weight.")
        self.assertEqual(result["verdict"], "refuse")
        self.assertEqual(result["counts"].get("health"), 2)
        self.assertIn("Take it out", result["note"])

    def test_health_outranks_every_other_verdict(self) -> None:
        """One health claim makes the whole piece a refusal, whatever else is in it."""
        result = report("Certified organic, carbon neutral, and it cures colds.")
        self.assertEqual(result["verdict"], "refuse")

    def test_a_certification_claim_names_the_certificate_record(self) -> None:
        result = report("Certified organic garlic.")
        finding = result["findings"][0]
        self.assertEqual(finding["category"], "certification")
        self.assertEqual(finding["verdict"], "needs_evidence")
        self.assertIn("certificate record", finding["needs"])
        self.assertIn("record_find", finding["needs"])

    def test_an_environmental_claim_names_empco_and_the_accc_shape(self) -> None:
        result = report("Our packaging is compostable and the farm is carbon neutral.")
        self.assertEqual(result["verdict"], "needs_evidence")
        self.assertEqual(result["counts"].get("environmental"), 2)
        self.assertIn("2024/825", result["findings"][0]["needs"])
        self.assertIn("misleading", result["findings"][0]["needs"])

    def test_a_provenance_claim_asks_where_the_boundary_is(self) -> None:
        result = report("Locally grown, farm fresh tomatoes.")
        self.assertEqual(result["counts"].get("provenance"), 2)
        self.assertIn("boundary", result["findings"][0]["needs"])

    def test_a_comparative_claim_asks_what_it_is_better_than(self) -> None:
        result = report("The best tomatoes at the market.")
        self.assertEqual(result["verdict"], "needs_substantiation")
        self.assertIn("better than", result["findings"][0]["needs"])


class BoundariesTestCase(unittest.TestCase):
    def test_a_longer_phrase_wins_over_its_parts(self) -> None:
        """"certified organic" is one finding, not a `certified` and an `organic`."""
        findings = check("certified organic")
        self.assertEqual([f.phrase.casefold() for f in findings], ["certified organic"])

    def test_a_word_inside_another_word_is_not_a_claim(self) -> None:
        for text in ("a bestowed award", "the greenhouse", "curesy nonsense", "organicism"):
            with self.subTest(text=text):
                self.assertEqual(check(text), [], text)

    def test_an_inflected_health_claim_is_still_a_health_claim(self) -> None:
        """The sentence that came back "clear".

        "Our tea will boost your immune system and prevent disease." matched nothing: the
        vocabulary spelled out `boosts`/`immunity`/`prevents`, and the draft used `boost`,
        `immune system` and `prevent` (the internal audit PLUG-4).
        """
        result = report("Our tea will boost your immune system and prevent disease.")
        self.assertEqual(result["verdict"], "refuse")
        self.assertFalse(result["clear"])
        self.assertTrue(all(f["category"] == "health" for f in result["findings"]))
        self.assertEqual(len(result["findings"]), 3, result["findings"])

    def test_every_old_inflection_still_matches(self) -> None:
        """The vocabulary lists base forms now; the matcher supplies the rest.

        These are the entries that were spelled out one inflection at a time. If any of them
        stops matching, the trim that made the list readable lost a claim.
        """
        for phrase in (
            "cures", "cured", "heals", "healing", "prevents", "prevents disease",
            "boosts immunity", "immune boosting", "immunity", "detox", "detoxifies", "superfood",
            "clinically proven", "medicinal", "therapeutic", "anti-inflammatory", "antioxidant",
            "lowers cholesterol", "blood pressure", "aids digestion", "good for your gut",
            "prevents cancer", "treats", "remedy", "kills bacteria", "antibacterial", "boosts",
            "helps you lose weight", "sugar free", "keto friendly", "doctor recommended",
        ):
            with self.subTest(phrase=phrase):
                self.assertTrue(check(phrase), phrase)

    def test_a_hyphen_and_a_space_are_the_same_word(self) -> None:
        for text in ("anti-inflammatory", "anti inflammatory", "ecofriendly is not this"):
            with self.subTest(text=text):
                findings = check(text)
                if text.startswith("anti"):
                    self.assertTrue(findings, text)

    def test_a_low_confidence_word_does_not_decide_the_verdict(self) -> None:
        """The vocabulary marks "natural" low *for the assistant to judge in context*.

        The verdict ignored confidence, so ordinary copy came back `needs_evidence` with a note
        saying "the claim comes out" — advice to rewrite a sentence over a word the lint itself
        only half believed (the internal audit PLUG-16).
        """
        result = report("Natural yoghurt.")
        self.assertEqual(result["verdict"], "clear")
        self.assertFalse(result["clear"], "the finding is still reported")
        self.assertEqual(result["findings"][0]["confidence"], "low")
        self.assertIn("read them in context", result["note"])

        # A word the lint is sure about still decides it.
        self.assertEqual(report("Certified organic garlic.")["verdict"], "needs_evidence")

    def test_unicode_obfuscation_does_not_hide_a_claim(self) -> None:
        """A claim is a claim in any spelling.

        The lint split on an ASCII `[\\s-]+` and never normalised, so it answered `clear` for a
        soft hyphen, a zero-width space, a Cyrillic lookalike and the two non-ASCII hyphens
        (the internal security audit A19-PLUG-8).
        """
        for label, text in (
            ("soft hyphen", "This tea supports your imm\u00adune system."),
            ("zero-width space", "This tea supports your imm\u200bune system."),
            ("Cyrillic у", "This tea supports your immune s\u0443stem."),
            ("non-breaking hyphen", "This is anti\u2011inflammatory."),
            ("full-width hyphen", "This is anti\uff0dinflammatory."),
        ):
            with self.subTest(spelling=label):
                result = report(text)
                self.assertEqual(result["verdict"], "refuse", result)
                self.assertFalse(result["clear"], result)
                self.assertTrue(result["findings"], result)

    def test_a_folded_claim_is_reported_under_its_plain_spelling(self) -> None:
        result = report("This tea supports your imm\u00adune system.")
        self.assertEqual([f["phrase"] for f in result["findings"]], ["immune system"])

    def test_a_findings_offsets_stay_in_the_text_that_was_passed(self) -> None:
        """The context a reviewer reads is the operator's own copy, obfuscation and all."""
        text = "\u200bimm\u00adune system"
        findings = check(text)
        self.assertEqual(len(findings), 1, findings)
        span = text[findings[0].start : findings[0].end]
        self.assertEqual(span.replace("\u00ad", ""), "immune system")
        result = report(
            "Come to the market on Saturday morning and try our imm\u00adune system tea, "
            "which is certified organic and grown without sprays."
        )
        by_phrase = {f["phrase"].casefold(): f for f in result["findings"]}
        self.assertIn("market", by_phrase["immune system"]["in_context"])

    def test_an_ordinary_product_word_is_flagged_low_not_high(self) -> None:
        """A lint that cannot say "this might be nothing" gets switched off."""
        result = report("Fresh green beans, picked today.")
        by_phrase = {finding["phrase"].casefold(): finding for finding in result["findings"]}
        self.assertEqual(by_phrase["green"]["confidence"], "low")
        self.assertEqual(by_phrase["fresh"]["confidence"], "low")
        self.assertEqual(by_phrase["picked today"]["confidence"], "high")

    def test_findings_carry_the_context_they_were_found_in(self) -> None:
        result = report("Come to the market on Saturday for our certified organic garlic.")
        self.assertIn("certified organic", result["findings"][0]["in_context"])

    def test_clean_copy_says_what_it_is_not(self) -> None:
        result = report("Tomatoes, beans and eggs at the market on Saturday.")
        self.assertTrue(result["clear"])
        self.assertEqual(result["verdict"], "clear")
        self.assertIn("not a guarantee", result["note"])

    def test_it_is_not_legal_advice_and_says_so(self) -> None:
        self.assertIn("not legal advice", report("anything")["not_legal_advice"])


class PluginTestCase(unittest.TestCase):
    class Ctx:
        def __init__(self, **settings):
            self.settings, self.tools = settings, []

        def register_tool(self, **kw):
            self.tools.append(kw)

        def get_config(self, key=None, default=None):
            return dict(self.settings) if key is None else self.settings.get(key, default)

    def load(self, **settings):
        for name in [n for n in sys.modules if n == "claims_plugin" or n.startswith("claims_plugin.")]:
            del sys.modules[name]
        spec = importlib.util.spec_from_file_location(
            "claims_plugin", PLUGIN / "__init__.py", submodule_search_locations=[str(PLUGIN)]
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules["claims_plugin"] = module
        spec.loader.exec_module(module)
        ctx = self.Ctx(**settings)
        module.register(ctx)
        return ctx

    def call(self, ctx, params):
        return json.loads(next(t["handler"] for t in ctx.tools if t["name"] == "claim_check")(params))

    def test_one_tool_under_its_own_toolset(self) -> None:
        ctx = self.load()
        self.assertEqual([t["name"] for t in ctx.tools], ["claim_check"])
        self.assertEqual({t["toolset"] for t in ctx.tools}, {"claims"})

    def test_the_schema_forbids_rewriting(self) -> None:
        ctx = self.load()
        description = ctx.tools[0]["schema"]["description"]
        self.assertIn("DO NOT REWRITE", description)
        self.assertIn("REFUSED", description)

    def test_a_check_comes_back_as_findings(self) -> None:
        ctx = self.load()
        result = self.call(ctx, {"text": "Eco-friendly and locally grown."})
        self.assertTrue(result["success"], result)
        self.assertEqual(result["verdict"], "needs_evidence")
        self.assertTrue(result["findings"])

    def test_empty_copy_is_refused_rather_than_passed(self) -> None:
        ctx = self.load()
        result = self.call(ctx, {"text": "   "})
        self.assertFalse(result["success"])
        self.assertIn("copy to check", result["error"])

    def test_a_switched_off_capability_says_nothing_was_checked(self) -> None:
        ctx = self.load(capability_enabled=False)
        result = self.call(ctx, {"text": "certified organic"})
        self.assertFalse(result["success"])
        self.assertIn("nothing here has been checked", result["error"])


if __name__ == "__main__":
    unittest.main()
