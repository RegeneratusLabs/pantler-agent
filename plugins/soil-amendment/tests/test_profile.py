"""Profile tests - the deployment-specific layer.

The package must ship with no vendor product names, and a deployment must be able to
supply its own inputs without touching code.

Run with the standard library:

    python3 -m unittest discover -s tests -t tests -v
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
sys.path.insert(0, PLUGIN)

from soilengine import profile as prof  # noqa: E402
from soilengine.eal import read_coa  # noqa: E402
from soilengine.recommend import Context, recommend  # noqa: E402
from soilengine.soil import analyse_sample  # noqa: E402

FIX = os.path.join(HERE, "fixtures")
MULTI = os.path.join(FIX, "example-soil-multi-sample.csv")
PKG = PLUGIN


VENDOR_PATTERNS = [
    r"\bnts\b", r"nutri-?tech", r"nutri-life", r"\blife ?force\b", r"soil therapy",
    r"soil value", r"dia-life", r"cal-tech", r"triple ten", r"brix-?fix",
    r"tsunami", r"micro-force", r"\bmend\b", r"brewstar", r"bioplex", r"\bbio-n\b",
    r"\bbio-p\b", r"gyp-life", r"tri-kelp", r"tricho-shield", r"b-sub",
    r"root & shoot", r"worm juice", r"sea.?change", r"platform®", r"nutrient farming",
    r"soluble humate", r"fulvic 1400", r"\bchook\b", r"fast fulvic", r"nutri-store",
    r"nutri-mate", r"nutri-score",
]


def _vendor_hits(text: str) -> list[str]:
    import re
    low = text.lower()
    return [p for p in VENDOR_PATTERNS if re.search(p, low)]


class TestProfile(unittest.TestCase):

    def _tmp_dir(self):
        """A fresh temporary directory, cleaned up when the test ends."""
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        return d

    def test_default_profile_loads(self):
        p = prof.load_profile("default")
        self.assertTrue(p.raw)
        self.assertFalse(p.warnings)
        for key in ("ideal_ppm", "max_kg_ha_yr", "product_selections", "messages"):
            self.assertIn(key, p.raw)

    def test_missing_profile_is_reported_not_silently_defaulted(self):
        p = prof.load_profile("does-not-exist")
        self.assertEqual(p.raw, {})
        self.assertTrue(p.warnings and "not found" in p.warnings[0])

    def test_profiles_are_json_so_the_package_stays_dependency_free(self):
        """No YAML parser is used anywhere: json is stdlib."""
        d = os.path.join(PKG, "profiles")
        files = [f for f in os.listdir(d) if not f.startswith(".")]
        self.assertTrue(files and all(f.endswith(".json") for f in files), files)

    def test_shipped_profile_has_no_vendor_branding(self):
        """The packaged profile must be whitelabel: no company, product-brand or
        trademark strings."""
        d = os.path.join(PKG, "profiles")
        for f in os.listdir(d):
            if not f.endswith(".json"):
                continue
            with open(os.path.join(d, f), encoding="utf-8") as fh:
                text = fh.read()
            hits = _vendor_hits(text)
            self.assertFalse(hits, f"vendor strings {hits} found in profiles/{f}")

    def test_engine_source_has_no_vendor_branding(self):
        """The shipped engine must carry no vendor product names or proprietary shorthand.
        Word boundaries matter here: 'constants' must not trip an 'nts' check, and
        'nutrient' is ordinary agronomic vocabulary, not a brand."""
        for f in sorted(os.listdir(os.path.join(PKG, "soilengine"))):
            if not f.endswith(".py"):
                continue
            with open(os.path.join(PKG, "soilengine", f), encoding="utf-8") as fh:
                text = fh.read()
            hits = _vendor_hits(text)
            self.assertFalse(hits, f"vendor strings {hits} found in soilengine/{f}")

    def test_whitelabel_check_actually_catches_a_vendor_string(self):
        """Guard the guard: the detector must fire on a real brand mention."""
        self.assertTrue(_vendor_hits("Apply NTS Soft Rock at 500 kg/ha"))
        self.assertTrue(_vendor_hits("Nutri-Life 4/20 and Soil Therapy"))
        self.assertFalse(_vendor_hits(
            "The constants module holds agronomic nutrient values."))

    def test_a_deployment_can_swap_in_its_own_products(self):
        """The whole point of the profile layer: change products and ceilings without
        editing engine code."""
        p = prof.load_profile("default")
        raw = json.loads(json.dumps(p.raw))
        raw["name"] = "acme"
        raw["product_selections"]["phosphorus"]["with_calcium_need"] = {
            "product": "ACME Rock Phosphate 500", "element_pct": 11.0, "ca_pct": 22.0,
            "note": "Preferred combined source.",
        }
        raw["max_kg_ha_yr"]["ACME Rock Phosphate 500"] = [11.0, 900.0]
        path = os.path.join(self._tmp_dir(), "acme.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(raw))

        # A deployment's own file, through the operator door: `allow_path` is for the CLI and
        # the operator's configured setting, never for a name the model supplies (A19-PLUG-3).
        acme = prof.load_profile(path, allow_path=True)
        self.assertEqual(acme.name, "acme")

        coa = read_coa(MULTI)
        a = analyse_sample(coa.samples[0], acme)
        rec = recommend(a, Context(crop="Example"), acme)
        p_am = [am for am in rec.amendments if am.element == "P"][0]
        self.assertEqual(p_am.product, "ACME Rock Phosphate 500")
        self.assertEqual(p_am.element_pct, 11.0)

    def test_profile_can_override_message_text(self):
        p = prof.load_profile("default")
        raw = json.loads(json.dumps(p.raw))
        raw["messages"]["codes"]["mg_excess"] = "Custom wording for this deployment."
        path = os.path.join(self._tmp_dir(), "custom.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(raw))
        custom = prof.load_profile(path, allow_path=True)

        coa = read_coa(MULTI)
        rec = recommend(analyse_sample(coa.samples[0], custom), Context(), custom)
        flag = [f for f in rec.flags if f["code"] == "mg_excess"][0]
        self.assertEqual(flag["text"], "Custom wording for this deployment.")

    def test_profile_can_relabel_the_report(self):
        p = prof.load_profile("default")
        self.assertTrue(p.text("report_title"))
        self.assertNotIn("{", p.text("report_title"), "title is not a format template")

    def test_missing_required_section_is_warned_about(self):
        path = os.path.join(self._tmp_dir(), "incomplete.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"name": "incomplete"}))
        p = prof.load_profile(path, allow_path=True)
        self.assertGreaterEqual(len(p.warnings), 3)

    def test_a_model_supplied_name_cannot_be_a_path(self):
        """The profile was any path that was a file: `../../../etc/hostname` opened.

        A profile chooses the product table and the annual application ceilings, so a
        caller-chosen path is every ceiling check gone while the answer still says the ceilings
        were applied (the internal security audit A19-PLUG-3).
        """
        for name in (
            "/etc/hostname",
            "../../../etc/hostname",
            "../default",
            "profiles/default",
            "./default",
        ):
            with self.subTest(profile=name):
                p = prof.load_profile(name)
                self.assertEqual(p.raw, {}, p.raw)
                self.assertTrue(p.warnings, name)
                self.assertIn("not a name", p.warnings[0])

    def test_a_deployment_profile_can_still_be_loaded_by_name_from_a_directory(self):
        """The name door stays open: a deployment ships its own `profiles/*.json`."""
        d = self._tmp_dir()
        with open(os.path.join(d, "acme.json"), "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"name": "acme", "label": "ACME"}))
        p = prof.load_profile("acme", directory=d)
        self.assertEqual(p.name, "acme")
        self.assertEqual(p.label, "ACME")

    def test_a_missing_profile_does_not_echo_an_absolute_path(self):
        """The warning can reach the transcript, so it names `profiles/`, not the filesystem."""
        p = prof.load_profile("does-not-exist-either")
        self.assertTrue(p.warnings)
        self.assertIn("profiles/", p.warnings[0])
        self.assertNotIn(PKG, p.warnings[0])

    def test_a_non_object_profile_is_refused_cleanly(self):
        """A JSON array root used to reach `Profile.thresholds` as an `AttributeError`.

        (the internal security audit A19-PLUG-3)
        """
        path = os.path.join(self._tmp_dir(), "array.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("[1, 2, 3]")
        p = prof.load_profile(path, allow_path=True)
        self.assertEqual(p.raw, {})
        self.assertTrue(any("not an object" in w for w in p.warnings), p.warnings)
        # Every accessor a caller uses answers, rather than raising on the shape.
        self.assertEqual(p.thresholds, {})
        self.assertEqual(p.max_rates, {})
        self.assertEqual(p.selections, {})
        self.assertEqual(p.ideal_ppm, {})

    def test_a_malformed_ceiling_is_dropped_rather_than_raised_on(self):
        """`tuple(300.0)` in `max_rates` was an uncaught `TypeError` (A19-PLUG-3)."""
        p = prof.load_profile("default")
        raw = json.loads(json.dumps(p.raw))
        raw["max_kg_ha_yr"] = {
            "Good": [10.0, 300.0],
            "Scalar": 250.0,
            "Short": [10.0],
            "Text": ["a", "b"],
            "Infinite": [0.0, float("inf")],
            "Negative": [0.0, -5.0],
        }
        path = os.path.join(self._tmp_dir(), "ceilings.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(raw))
        loaded = prof.load_profile(path, allow_path=True)
        rates = loaded.max_rates
        self.assertEqual(rates["Good"], (0.0, 300.0))
        self.assertEqual(rates["Scalar"], (0.0, 250.0))
        for bad in ("Short", "Text", "Infinite", "Negative"):
            with self.subTest(entry=bad):
                self.assertNotIn(bad, rates)


if __name__ == "__main__":
    unittest.main()
