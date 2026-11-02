"""Tests for the EAL certificate-of-analysis reader, run against synthetic fixtures.

No real client data is used anywhere in this repository.

Run with the standard library:

    python3 -m unittest discover -s tests -t tests -v
"""
import glob
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from soilengine.eal import CoATooLarge, MAX_ROWS, MAX_SAMPLES, read_coa  # noqa: E402

FIX = os.path.join(HERE, "fixtures")
ALL = sorted(glob.glob(os.path.join(FIX, "*.csv")))

MULTI = os.path.join(FIX, "example-soil-multi-sample.csv")
SINGLE = os.path.join(FIX, "example-soil-single-sample.csv")
BARE = os.path.join(FIX, "example-soil-no-texture-no-depth.csv")
PLANT = os.path.join(FIX, "example-plant-tissue.csv")


class TestLabReader(unittest.TestCase):

    def test_fixtures_present(self):
        self.assertGreaterEqual(len(ALL), 4,
                                f"expected the fixture set, found {len(ALL)} files")

    def test_every_fixture_parses(self):
        for path in ALL:
            with self.subTest(fixture=os.path.basename(path)):
                coa = read_coa(path)
                self.assertTrue(coa.samples)
                for s in coa.samples:
                    self.assertTrue(s.results,
                                    f"{path} sample {s.sample_id} has no results")

    def test_layout_a_report_id_and_multiple_samples(self):
        coa = read_coa(MULTI)
        self.assertEqual(coa.job, "E26-00-9999")
        self.assertEqual(coa.pack_code, "EALT1")
        self.assertEqual(coa.test_type, "soil")
        self.assertEqual([s.sample_id for s in coa.samples],
                         ["North Paddock", "South Block", "Deep Profile"])

    def test_layout_b_method_first_single_sample(self):
        coa = read_coa(SINGLE)
        self.assertIsNone(coa.report_id)
        self.assertEqual(coa.test_type, "soil")
        self.assertEqual(len(coa.samples), 1)
        # method-first column order must not shift the values
        self.assertAlmostEqual(coa.samples[0].value("pH (H2O)"), 6.98, places=6)
        self.assertAlmostEqual(
            coa.samples[0].value("Exchangeable Calcium", "cmol+/kg"), 9.48, places=6)

    def test_parameter_names_repeat_and_only_the_unit_disambiguates(self):
        """'Calcium' is a base saturation percentage AND a total acid-extractable reserve;
        'Exchangeable Calcium' is reported in three different units. Keys must be
        (name, unit) - matching on name alone silently reads one scale as another."""
        coa = read_coa(MULTI)
        s = coa.samples[0]
        self.assertAlmostEqual(s.value("Calcium", "%"), 67.0, places=6)
        self.assertAlmostEqual(s.value("Calcium", "mg/kg"), 3200.0, places=6)
        self.assertAlmostEqual(s.value("Exchangeable Calcium", "cmol+/kg"), 10.4, places=6)
        self.assertAlmostEqual(s.value("Exchangeable Calcium", "mg/kg"), 2080.0, places=6)
        self.assertAlmostEqual(s.value("Exchangeable Calcium", "kg/ha"), 5200.0, places=6)

    def test_below_lor_is_not_treated_as_zero(self):
        coa = read_coa(SINGLE)
        r = coa.samples[0].get("Boron - CaCl2 extractable", "mg/kg")
        self.assertEqual(r.status, "below_lor")
        self.assertIsNone(r.value)
        # LOR/2 is substituted for balance arithmetic only
        self.assertAlmostEqual(
            coa.samples[0].value_or_lor_half("Boron - CaCl2 extractable", "mg/kg"),
            0.05, places=6)

    def test_a_decimal_comma_is_not_a_thousands_separator(self):
        """`"1,5"` used to become 15.0 and `"12,50"` 1250.0, with status "ok".

        A 10–100× error on a number every rate downstream depends on
        (the internal audit PLUG-10).
        """
        from soilengine.eal import _parse_value

        self.assertEqual(_parse_value("1,5"), (1.5, "ok"))
        self.assertEqual(_parse_value("12,50"), (12.5, "ok"))
        self.assertEqual(_parse_value("1,234"), (1234.0, "ok"))
        self.assertEqual(_parse_value("1,234.5"), (1234.5, "ok"))
        # A comma that is neither: reported, not guessed at.
        self.assertEqual(_parse_value("1,23,4"), (None, "unreadable"))

    def test_a_below_lor_cell_keeps_its_own_limit(self):
        """The `<0.1` cell's own number is the limit of reporting.

        It used to be discarded in favour of the LOR column, so an empty column left no LOR/2 to
        substitute and a disagreeing one substituted a different magnitude
        (the internal audit PLUG-10).
        """
        rows = [
            "Report ID,E26-00-0000_TEST_1,,",
            "Client Sample ID:,,,Block 1",
            "Parameter,Unit,Method Reference,LOR,---",
            # The LOR column is empty and the cell carries its own limit, which is the case the
            # old reader could not handle.
            "Boron - CaCl2 extractable,mg/kg,Inhouse S37,,<0.1",
        ]
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "lor.csv"
            path.write_text("\n".join(rows) + "\n", encoding="utf-8")
            coa = read_coa(str(path))
        sample = coa.samples[0]
        result = sample.get("Boron - CaCl2 extractable", "mg/kg")
        self.assertEqual(result.status, "below_lor")
        self.assertIsNone(result.value)
        self.assertEqual(sample.value_or_lor_half("Boron - CaCl2 extractable", "mg/kg"), 0.05)

    def test_a_metre_deep_sample_is_read_as_metres(self):
        """`2m` read as 2 cm made every kg/ha figure 50× light (the internal audit PLUG-10)."""
        from soilengine.physical import parse_depth_cm

        for raw, expected in (("2m", 200.0), ("1.5m", 150.0), ("0-2m", 200.0), ("2 m", 200.0)):
            with self.subTest(raw=raw):
                depth, explicit, _note = parse_depth_cm(raw)
                self.assertEqual(depth, expected)
                self.assertTrue(explicit)

    def test_carbon_without_nitrogen_is_not_a_plant_panel(self):
        """`A or B and C and D` parses as `A or (B and C and D)`, and the `D` was unreachable.

        With the grouping made explicit, "Total Carbon" on its own is not enough to call a report
        a plant panel — soil reports carry organic carbon too
        (the internal audit PLUG-16).
        """
        rows = [
            "Report ID,E26-00-0000_TEST_1,,",
            "Client Sample ID:,,,Block 1",
            "Parameter,Unit,Method Reference,LOR,---",
            "Total Carbon,%,Inhouse S4a,<0.02,1.8",
        ]
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "carbon-only.csv"
            path.write_text("\n".join(rows) + "\n", encoding="utf-8")
            coa = read_coa(str(path))
            self.assertEqual(coa.test_type, "unknown")

    def test_plant_tissue_is_classified_as_plant(self):
        coa = read_coa(PLANT)
        self.assertEqual(coa.test_type, "plant")

    def test_texture_and_depth_are_preserved_verbatim(self):
        coa = read_coa(MULTI)
        self.assertEqual(coa.samples[0].meta.get("Sample Depth"), "15cm")
        self.assertEqual(coa.samples[2].meta.get("Sample Depth"), "45cm")

    def test_no_texture_fixture_reports_placeholder_texture(self):
        coa = read_coa(BARE)
        r = coa.samples[0].get("Basic Texture")
        self.assertEqual(r.raw, "---")

    def test_a_negative_reading_is_unreadable_and_named(self):
        """A cell of `-999999` became a 1,000,069 ppm deficit and a 25,001,725 kg/ha dose.

        `soil.py` computes `max(0.0, ideal - actual)` and cannot see the sign, so a negative
        concentration is not a measurement: it is unreadable, like a comma that is neither
        separator nor decimal, and the parse warnings name it
        (the internal security audit A19-PLUG-6).
        """
        from soilengine.eal import _parse_value

        self.assertEqual(_parse_value("-999999"), (None, "unreadable"))
        self.assertEqual(_parse_value("-0.5"), (None, "unreadable"))

        rows = [
            "Report ID,E26-00-0000_TEST_1,,",
            "Client Sample ID:,,,Block 1",
            "Parameter,Unit,Method Reference,LOR,---",
            "Mehlich Phosphorus,mg/kg,Inhouse S7,<10,-999999",
            "pH (H2O),,,,6.2",
        ]
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "negative.csv"
            path.write_text("\n".join(rows) + "\n", encoding="utf-8")
            coa = read_coa(str(path))
        result = coa.samples[0].get("Mehlich Phosphorus", "mg/kg")
        self.assertEqual(result.status, "unreadable")
        self.assertIsNone(result.value)
        self.assertTrue(
            any("negative reading" in w for w in coa.warnings), coa.warnings
        )
        # The rest of the row is still read: one bad cell is not a bad report.
        self.assertAlmostEqual(coa.samples[0].value("pH (H2O)"), 6.2, places=6)

    def _wide_csv(self, path, columns, rows=1):
        header = ["Parameter", "Unit", "Method Reference", "LOR"] + [
            f"S{i}" for i in range(columns)
        ]
        lines = [
            "Report ID,E26-00-0000_TEST_1,",
            "Client Sample ID:,,",
            ",".join(header),
        ]
        for i in range(rows):
            lines.append(
                ",".join([f"Parameter {i:05d}", "mg/kg", "Inhouse S1", "<1"] + ["1.5"] * columns)
            )
        Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_a_certificate_with_too_many_samples_is_refused_with_the_count(self):
        """The audit's crafted file had 40,000 value columns and produced a 226 MB result.

        (the internal security audit A19-PLUG-7)
        """
        columns = MAX_SAMPLES + 70
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "wide.csv"
            self._wide_csv(path, columns)
            with self.assertRaises(CoATooLarge) as caught:
                read_coa(str(path))
        self.assertIn(str(columns), str(caught.exception))
        self.assertIn(str(MAX_SAMPLES), str(caught.exception))

    def test_a_certificate_with_too_many_rows_is_refused_with_the_count(self):
        rows = MAX_ROWS + 100
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "long.csv"
            self._wide_csv(path, 1, rows=rows)
            with self.assertRaises(CoATooLarge) as caught:
                read_coa(str(path))
        self.assertIn(str(MAX_ROWS), str(caught.exception))

    def test_a_file_inside_the_caps_still_parses(self):
        # The cap is a ceiling, not the new normal: an ordinary file is unaffected.
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "ok.csv"
            self._wide_csv(path, 3, rows=50)
            coa = read_coa(str(path))
        self.assertEqual(len(coa.samples), 3)

    def test_unparsed_numeric_looking_values_are_reported(self):
        bad = []
        for path in ALL:
            coa = read_coa(path)
            for s in coa.samples:
                for (p, u), r in s.results.items():
                    if r.status == "missing" and r.raw and r.raw.strip() not in (
                            "", "---", "N/A", "na", "-"):
                        if not any(ch.isalpha() for ch in r.raw):
                            bad.append((os.path.basename(path), s.sample_id, p, u, r.raw))
        self.assertFalse(bad, f"unparsed numeric-looking values: {bad[:10]}")


if __name__ == "__main__":
    unittest.main()
