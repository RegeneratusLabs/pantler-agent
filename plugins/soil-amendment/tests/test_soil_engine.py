"""Physical basis and soil arithmetic tests, against synthetic fixtures.

Run with the standard library:

    python3 -m unittest discover -s tests -t tests -v
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from soilengine import constants as K  # noqa: E402,F401
from soilengine import physical as P  # noqa: E402
from soilengine import profile as prof  # noqa: E402
from soilengine.eal import read_coa  # noqa: E402
from soilengine.soil import analyse_sample, ideal_bs_row, ideal_ppm_for  # noqa: E402

FIX = os.path.join(HERE, "fixtures")
MULTI = os.path.join(FIX, "example-soil-multi-sample.csv")
SINGLE = os.path.join(FIX, "example-soil-single-sample.csv")
BARE = os.path.join(FIX, "example-soil-no-texture-no-depth.csv")


# A single default profile is loaded once per module and shared by every test below.
PROFILE = None


def setUpModule():
    global PROFILE
    PROFILE = prof.load_profile("default")


def tearDownModule():
    global PROFILE
    PROFILE = None


class TestSoilEngine(unittest.TestCase):

    def setUp(self):
        self.profile = PROFILE

    # ------------------------------------------------------------ bulk density

    def test_bulk_density_falls_as_clay_content_rises(self):
        """Clay soils have better aggregation and more pore space than sands, so they hold
        LESS mass per unit volume. Raising a nutrient by 1 ppm in a light sandy soil
        therefore takes MORE product than in a clay."""
        sand = P.bulk_density_for_texture("Sand", self.profile)[0]
        loam = P.bulk_density_for_texture("Loam", self.profile)[0]
        clay = P.bulk_density_for_texture("Clay", self.profile)[0]
        self.assertTrue(sand > loam > clay)
        self.assertGreater(P.ppm_to_kgha_factor(15, sand),
                           P.ppm_to_kgha_factor(15, clay))

    def test_bulk_density_from_profile(self):
        for texture, expected in [
            ("Sand", 1.65), ("Sandy Loam", 1.55), ("Loam", 1.50), ("Clay Loam", 1.45),
            ("Clay", 1.35),
        ]:
            with self.subTest(texture=texture, expected=expected):
                bd, _note = P.bulk_density_for_texture(texture, self.profile)
                self.assertEqual(bd, expected)

    def test_unknown_texture_is_not_guessed(self):
        for raw in ("---", "", None, "Purple"):
            with self.subTest(texture=raw):
                bd, _ = P.bulk_density_for_texture(raw, self.profile)
                self.assertIsNone(bd)

    def test_approximate_bucket_mapping_is_disclosed(self):
        bd, note = P.bulk_density_for_texture("Sandy Soil", self.profile)
        self.assertEqual(bd, 1.55)
        self.assertIn("bucket", note)

    # ------------------------------------------------------------ depth

    def test_depth_formats(self):
        for raw, expected in [
            ("15cm", 15.0), ("150mm", 15.0), ("0-15", 15.0), ("150", 15.0),
            ("0.0-0.15", 15.0), ("30cm", 30.0), ("0-300mm", 30.0), ("Sub 1m", 100.0),
            ("50-250mm", 25.0), ("15-20 cm", 20.0),
        ]:
            with self.subTest(raw=raw, expected=expected):
                depth, _explicit, _note = P.parse_depth_cm(raw, self.profile)
                self.assertAlmostEqual(depth, expected, places=6)

    def test_explicit_unit_is_recorded(self):
        self.assertIs(P.parse_depth_cm("15cm", self.profile)[1], True)
        self.assertIs(P.parse_depth_cm("150mm", self.profile)[1], True)
        self.assertIs(P.parse_depth_cm("150", self.profile)[1], False)

    def test_missing_depth_falls_back(self):
        depth, explicit, note = P.parse_depth_cm("---", self.profile)
        self.assertAlmostEqual(depth, 15.0, places=6)
        self.assertIs(explicit, False)
        self.assertIn("assumed", note)

    # ------------------------------------------------------------ the factor

    def test_factor_formula(self):
        self.assertAlmostEqual(P.ppm_to_kgha_factor(15.0, 1.50), 2.25, places=6)
        self.assertAlmostEqual(P.ppm_to_kgha_factor(15.0, 1.45), 2.175, places=6)
        self.assertAlmostEqual(P.ppm_to_kgha_factor(30.0, 1.45), 4.35, places=6)

    def test_factor_derived_from_texture_and_depth(self):
        factor, detail = P.resolve_factor("Clay Loam", "15cm", self.profile)
        self.assertAlmostEqual(factor, 2.175, places=6)
        self.assertEqual(detail["source"], "texture and depth")
        self.assertIs(detail["depth_is_typical"], True)

    def test_legacy_constant_can_still_be_reproduced(self):
        factor, detail = P.resolve_factor("Clay Loam", "15cm", self.profile,
                                          override_factor=2.5)
        self.assertAlmostEqual(factor, 2.5, places=6)
        self.assertEqual(detail["source"], "operator override")

    def test_measured_density_beats_the_table(self):
        factor, detail = P.resolve_factor("Clay", "15cm", self.profile, override_bd=1.62)
        self.assertAlmostEqual(factor, 2.43, places=6)

    def test_deep_sample_is_flagged(self):
        factor, detail = P.resolve_factor("Clay", "Sub 1m", self.profile)
        self.assertAlmostEqual(factor, 13.5, places=6)
        self.assertIs(detail["depth_is_typical"], False)

    # ------------------------------------------------------------ soil state

    def test_computed_base_saturation_matches_reported(self):
        coa = read_coa(MULTI)
        for s in coa.samples:
            a = analyse_sample(s, self.profile)
            for el in ("Ca", "Mg", "K", "Na"):
                c = a.cations[el]
                if c.bs_pct is None or c.bs_pct_lab is None:
                    continue
                with self.subTest(sample=s.sample_id, element=el):
                    self.assertLess(abs(c.bs_pct - c.bs_pct_lab), 0.6,
                                    f"{s.sample_id} {el}: {c.bs_pct} vs {c.bs_pct_lab}")

    def test_cation_sum_and_exchange_capacity(self):
        coa = read_coa(MULTI)
        a = analyse_sample(coa.samples[0], self.profile)
        self.assertAlmostEqual(a.tec, 15.5, places=6)
        self.assertAlmostEqual(a.cec_measured, 14.55, places=2)
        ca, mg, k, na, al = (a.cations[e].meq for e in ("Ca", "Mg", "K", "Na", "Al"))
        self.assertAlmostEqual(a.cec_measured, ca + mg + k + na + al, places=6)

    def test_ideal_ppm_formula(self):
        self.assertAlmostEqual(ideal_ppm_for(15.5, "Ca", 68.0), 2108.0, places=6)
        self.assertAlmostEqual(ideal_ppm_for(15.5, "Mg", 12.0), 223.2, places=6)

    def test_exchange_capacity_band_boundaries(self):
        self.assertEqual(ideal_bs_row(2.9, profile=self.profile)["ca_mg_label"], "3:1")
        self.assertEqual(ideal_bs_row(3.0, profile=self.profile)["ca_mg_label"], "3.4:1")
        self.assertEqual(ideal_bs_row(35.0, profile=self.profile)["ca_mg_label"], "7:1")

    def test_high_k_class_lifts_only_potassium(self):
        gen = ideal_bs_row(15.0, "generic", self.profile)["elements"]
        hik = ideal_bs_row(15.0, "high_k", self.profile)["elements"]
        self.assertEqual(gen["K"], (3.0, 5.0))
        self.assertEqual(hik["K"], (4.0, 7.0))
        for el in ("Ca", "Mg", "Na"):
            with self.subTest(element=el):
                self.assertEqual(gen[el], hik[el])

    def test_total_acid_reserves_do_not_produce_a_deficit(self):
        """Molybdenum and cobalt appear as total acid-extractable reserves, which are two
        orders of magnitude above an available-test target. Deriving a deficit from them
        would hide a real deficiency."""
        coa = read_coa(MULTI)
        a = analyse_sample(coa.samples[0], self.profile)
        for el in ("Mo", "Co"):
            with self.subTest(element=el):
                d = a.elements[el]
                self.assertEqual(d["status"], "reserve_only")
                self.assertIsNone(d["deficit"])
                self.assertIn("reserve_ppm", d)

    def test_sodium_and_aluminium_are_not_deficiencies(self):
        coa = read_coa(MULTI)
        a = analyse_sample(coa.samples[0], self.profile)
        self.assertNotIn("Na", a.elements)
        self.assertNotIn("Al", a.elements)

    def test_placeholder_texture_and_depth_are_flagged(self):
        a = analyse_sample(read_coa(BARE).samples[0], self.profile)
        self.assertIs(a.factor_detail["bulk_density_is_default"], True)
        self.assertIs(a.factor_detail["depth_is_explicit"], False)
        self.assertAlmostEqual(a.ppm_to_kgha, 2.25, places=6)


if __name__ == "__main__":
    unittest.main()
