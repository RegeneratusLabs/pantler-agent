"""Amendment algorithm tests, plus locked regression values for fixture sample 1.

Run with the standard library:

    python3 -m unittest discover -s tests -t tests -v
"""
import glob
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from soilengine import profile as prof  # noqa: E402
from soilengine.eal import read_coa  # noqa: E402
from soilengine.recommend import Context, recommend  # noqa: E402
from soilengine.soil import analyse_sample  # noqa: E402

FIX = os.path.join(HERE, "fixtures")
MULTI = os.path.join(FIX, "example-soil-multi-sample.csv")
ALL = sorted(glob.glob(os.path.join(FIX, "*.csv")))


# A single default profile is loaded once per module and shared by every test below.
PROFILE = None


def setUpModule():
    global PROFILE
    PROFILE = prof.load_profile("default")


def tearDownModule():
    global PROFILE
    PROFILE = None


def analyse(idx=0, crop_class="generic", **kw):
    return analyse_sample(read_coa(MULTI).samples[idx], profile=prof.load_profile("default"),
                          crop_class=crop_class, **kw)


class TestRecommend(unittest.TestCase):

    def setUp(self):
        self.profile = PROFILE

    # ------------------------------------------------------------ ordering

    def test_phosphorus_is_calculated_before_calcium(self):
        for path in ALL:
            coa = read_coa(path)
            if coa.test_type != "soil":
                continue
            for s in coa.samples:
                with self.subTest(fixture=os.path.basename(path), sample=s.sample_id):
                    rec = recommend(analyse_sample(s, self.profile), None, self.profile)
                    steps = [am.step for am in rec.amendments]
                    self.assertEqual(steps, sorted(steps),
                                     f"steps out of order in {path}: {steps}")

    def test_calcium_is_netted_against_the_phosphorus_input(self):
        """A combined phosphorus and calcium source carries ~20% calcium. If that is not
        deducted, the calcium requirement is over-applied - which is exactly the error the
        ordering rule exists to prevent."""
        a = analyse(0)
        rec = recommend(a, Context(crop="Example"), self.profile)
        soft = [am for am in rec.amendments if am.element == "P"][0]
        self.assertGreater(soft.ca_ppm_supplied, 0)

        ca_def = a.cations["Ca"].ideal_ppm_max - a.cations["Ca"].ppm
        self.assertLess(ca_def, soft.ca_ppm_supplied,
                        "fixture should have Ca covered by step 1")
        ca = [am for am in rec.amendments if am.element == "Ca"][0]
        self.assertEqual(ca.product, "(none)")
        self.assertIn("ca_covered_by_earlier_inputs", ca.rule_codes)

    # ------------------------------------------------------------ caps

    def test_no_product_exceeds_its_maximum(self):
        for path in ALL:
            coa = read_coa(path)
            if coa.test_type != "soil":
                continue
            for s in coa.samples:
                with self.subTest(fixture=os.path.basename(path), sample=s.sample_id):
                    rec = recommend(analyse_sample(s, self.profile), None, self.profile)
                    for am in rec.amendments:
                        cap = self.profile.max_rates.get(am.product)
                        if cap:
                            self.assertLessEqual(
                                am.product_kg_ha, cap[1] + 1e-9,
                                f"{am.product} {am.product_kg_ha} exceeds {cap[1]}")

    def test_a_product_the_profile_names_with_no_ceiling_is_named_back(self):
        """A missing ceiling used to be 1e9 kg/ha, which is no ceiling at all.

        The audit's crafted profile allowed 10,227,978 kg/ha of MAP while the answer still said
        the annual ceilings had been applied (the internal security audit A19-PLUG-3). A
        product the profile *selects* but sets no ceiling for is now named in a flag, whether or
        not this particular sample uses it.
        """
        import copy

        profile = copy.deepcopy(self.profile)
        del profile.raw["max_kg_ha_yr"]["MAP"]
        rec = recommend(analyse(0), Context(crop="Example"), profile)
        named = [f for f in rec.flags if f["code"] == "ceiling_missing"]
        self.assertTrue(any("MAP" in f["text"] for f in named), named)
        # The flag is loud: it is an action, and its text says what was done.
        flag = [f for f in named if "MAP" in f["text"]][0]
        self.assertEqual(flag["severity"], "action")
        self.assertIn("0 kg/ha", flag["text"])

    def test_a_used_product_with_no_ceiling_is_held_at_zero(self):
        """The safe direction: no ceiling, no product — never an implied 1e9 kg/ha."""
        import copy

        profile = copy.deepcopy(self.profile)
        del profile.raw["max_kg_ha_yr"]["Soft rock phosphate"]
        rec = recommend(analyse(0), Context(crop="Example"), profile)
        line = next(am for am in rec.amendments if am.element == "P")
        self.assertEqual(line.product, "Soft rock phosphate")
        self.assertEqual(line.product_kg_ha, 0.0)
        self.assertTrue(line.capped)
        self.assertTrue(
            any("Soft rock phosphate" in f["text"] for f in rec.flags
                if f["code"] == "ceiling_missing")
        )

    def test_total_calcium_stays_under_the_annual_ceiling(self):
        ceiling = self.profile.get("max_ca_ppm_per_year")
        for path in ALL:
            coa = read_coa(path)
            if coa.test_type != "soil":
                continue
            for s in coa.samples:
                with self.subTest(fixture=os.path.basename(path), sample=s.sample_id):
                    rec = recommend(analyse_sample(s, self.profile), None, self.profile)
                    # One field, one meaning: every line that supplies calcium records it, the
                    # calcium line included (the internal audit PLUG-7).
                    total = sum(x.ca_ppm_supplied for x in rec.amendments)
                    self.assertLessEqual(total, ceiling + 1e-6,
                                         f"total Ca {total:.0f} ppm over the ceiling")

    def test_a_product_used_by_two_steps_meets_one_annual_maximum(self) -> None:
        """One product, two jobs, one ceiling.

        A deployment that buys lime for both the calcium and the potassium job gets two lines of
        it; each used to be capped against the full annual maximum, so the pair could apply twice
        what the label allows — and the per-line assertion above cannot see it, because each line
        is within the limit (the internal audit PLUG-6). The sample is the single-sample
        fixture with its calcium lowered, so the calcium step fires.
        """
        import copy
        import tempfile

        source = os.path.join(FIX, "example-soil-single-sample.csv")
        with open(source, encoding="utf-8") as handle:
            text = handle.read()
        text = text.replace(
            "Exchangeable Calcium,cmol+/kg,<0.05,9.48", "Exchangeable Calcium,cmol+/kg,<0.05,4.00"
        )
        profile = copy.deepcopy(self.profile)
        lime = {"product": "Lime (fine)", "element_pct": 40.0, "note": ""}
        profile.raw["product_selections"]["calcium"]["low_ph"] = lime
        profile.raw["product_selections"]["potassium"] = dict(lime)
        profile.raw["max_kg_ha_yr"]["Lime (fine)"] = [40.0, 400.0]

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = os.path.join(tmp, "synthetic.csv")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(text)
            coa = read_coa(path)
            for s in coa.samples:
                program = recommend(analyse_sample(s, profile), None, profile)
                lines = [am.product for am in program.amendments]
                twice = {name for name in lines if lines.count(name) > 1}
                self.assertEqual(twice, {"Lime (fine)"}, "the synthetic case did not reproduce")
                total = sum(am.product_kg_ha for am in program.amendments
                            if am.product == "Lime (fine)")
                self.assertLessEqual(total, 400.0 + 1e-9, f"lime {total:.1f} kg/ha")
                self.assertGreater(total, 0.0)

    def test_a_program_that_reaches_the_ceiling_defers_the_calcium_it_cannot_apply(self) -> None:
        """The ceiling has to bind on the *program*, not on the calcium line.

        Gypsum is the high-pH calcium source and the sulfur source at once, so the two together
        used to pass a ceiling each of them respected: 818.7 ppm against 800. The fixture here
        makes the ceiling reachable — the same samples, a profile whose annual ceiling is low —
        so the enforcement has something to do (the internal audit PLUG-7).
        """
        import copy

        ceiling = 120.0
        low = copy.deepcopy(self.profile)
        low.raw["max_ca_ppm_per_year"] = ceiling
        over = 0
        for path in ALL:
            coa = read_coa(path)
            if coa.test_type != "soil":
                continue
            for s in coa.samples:
                with self.subTest(fixture=os.path.basename(path), sample=s.sample_id):
                    rec = recommend(analyse_sample(s, low), None, low)
                    total = sum(x.ca_ppm_supplied for x in rec.amendments)
                    self.assertLessEqual(total, ceiling + 0.5, f"total Ca {total:.1f} ppm")
                    over += sum(1 for f in rec.flags if f["code"] == "ca_program_ceiling")
        self.assertGreater(over, 0, "no fixture reached the ceiling, so nothing was tested")

    def test_deferred_calcium_is_reported_not_dropped(self):
        for path in ALL:
            coa = read_coa(path)
            if coa.test_type != "soil":
                continue
            for s in coa.samples:
                with self.subTest(fixture=os.path.basename(path), sample=s.sample_id):
                    rec = recommend(analyse_sample(s, self.profile), None, self.profile)
                    for am in rec.amendments:
                        if am.deferred_ppm > 0:
                            self.assertTrue(am.capped)
                            self.assertTrue(any(f["code"] in ("ca_annual_ceiling", "ca_max_rate")
                                                for f in rec.flags))

    def test_sulfur_is_netted_against_the_nitrogen_input(self):
        """Ammonium sulfate supplies 24% sulfur, so the sulfur product requirement must be
        the remainder, not the full deficit."""
        a = analyse(0)
        rec = recommend(a, Context(), self.profile)
        n = [am for am in rec.amendments if am.element == "N"][0]
        s_am = [am for am in rec.amendments if am.element == "S"]
        if s_am:
            expected = a.elements["S"]["deficit"] - n.s_ppm_supplied
            self.assertAlmostEqual(s_am[0].deficit_ppm, expected, places=6)

    # ------------------------------------------------------------ context

    def test_legume_omits_nitrogen(self):
        a = analyse(0)
        self.assertTrue(any(am.element == "N"
                            for am in recommend(a, Context(), self.profile).amendments))
        leg = recommend(a, Context(is_legume=True), self.profile)
        self.assertFalse(any(am.element == "N" for am in leg.amendments))
        self.assertTrue(any(f["code"] == "legume_omit_n" for f in leg.flags))

    def test_copper_fungicide_history_omits_copper(self):
        a = analyse(0)
        self.assertTrue(any(am.element == "Cu"
                            for am in recommend(a, Context(), self.profile).amendments))
        cu = recommend(a, Context(copper_fungicide_history=True), self.profile)
        self.assertFalse(any(am.element == "Cu" for am in cu.amendments))
        self.assertTrue(any(f["code"] == "copper_history" for f in cu.flags))

    def test_certification_flag(self):
        rec = recommend(analyse(0), Context(certification="organic"), self.profile)
        self.assertTrue(any(f["code"] == "certification_check" for f in rec.flags))

    def test_equipment_constraint_flag(self):
        rec = recommend(analyse(0),
                        Context(has_foliar=True, foliar_handles_wettable=False),
                        self.profile)
        self.assertTrue(any(f["code"] == "equipment_constraint" for f in rec.flags))

    def test_all_flags_have_text_from_the_profile(self):
        """Every code that fires must resolve to something a reader can understand."""
        for path in ALL:
            coa = read_coa(path)
            if coa.test_type != "soil":
                continue
            for s in coa.samples:
                with self.subTest(fixture=os.path.basename(path), sample=s.sample_id):
                    rec = recommend(analyse_sample(s, self.profile), Context(), self.profile)
                    for f in rec.flags + rec.ratio_flags:
                        self.assertTrue(f["text"], f"empty text for code {f['code']}")

    # ------------------------------------------------------------ regression

    def test_regression_sample_1(self):
        """Locked values for the first synthetic fixture sample. Clay Loam at 15 cm gives
        a factor of 2.175. If a change moves any of these, decide whether it was intended
        before touching the test."""
        a = analyse(0)
        self.assertAlmostEqual(a.factor_detail["bulk_density"], 1.45, places=6)
        self.assertAlmostEqual(a.ppm_to_kgha, 2.175, places=6)

        rec = recommend(a, Context(crop="Example"), self.profile)
        got = {am.element: am for am in rec.amendments if am.product != "(none)"}

        self.assertEqual(got["P"].product, "Soft rock phosphate")
        self.assertAlmostEqual(got["P"].product_kg_ha, 606.58, places=2)
        self.assertAlmostEqual(got["P"].ca_ppm_supplied, 55.78, places=2)

        self.assertAlmostEqual(got["K"].deficit_ppm, 91.25, places=6)
        self.assertAlmostEqual(got["K"].product_kg_ha, 300.0, places=6)
        self.assertAlmostEqual(got["K"].product_kg_ha_uncapped, 472.54, places=2)
        self.assertIs(got["K"].capped, True)

        self.assertAlmostEqual(got["N"].product_kg_ha, 300.0, places=2)
        self.assertAlmostEqual(got["N"].s_ppm_supplied, 33.103, places=2)

        self.assertAlmostEqual(got["S"].deficit_ppm, 10.897, places=2)
        self.assertAlmostEqual(got["S"].product_kg_ha, 158.0, places=2)

        self.assertAlmostEqual(got["Mn"].deficit_ppm, 58.7, places=6)
        self.assertAlmostEqual(got["Mn"].product_kg_ha, 30.0, places=6)
        self.assertIs(got["Mn"].capped, True)

    def test_regression_deep_sample_is_flagged(self):
        rec = recommend(analyse(2), Context(), self.profile)
        codes = [f["code"] for f in rec.flags]
        self.assertIn("depth_atypical", codes)
        depth_flag = [f for f in rec.flags if f["code"] == "depth_atypical"][0]
        self.assertIn("45 cm", depth_flag["text"])

    def test_codes_are_semantic_not_vendor_specific(self):
        """Rule codes are what a narrative layer keys off, so they must be descriptive and
        must not carry a vendor's internal shorthand."""
        rec = recommend(analyse(0), Context(), self.profile)
        for code in rec.codes():
            with self.subTest(code=code):
                self.assertEqual(code, code.lower())
                self.assertTrue(code.replace("_", "").isalnum())


if __name__ == "__main__":
    unittest.main()
