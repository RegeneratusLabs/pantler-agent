"""Every pack in `packs/` must load — the kernel's own contract, applied to what we ship.

`packs-fixtures/example/` is a contract fixture and `packs/farm/` is the first real pack — the
fixture sits outside `packs/`, which is what an operator's BFF loads
(the internal audit PACK-1). A pack that does not
parse is not a small problem: the BFF serves `/api/packs` from whatever loads, so a malformed
`pack.toml` removes a pack's records and screens from the shell with no error anybody sees. This
costs nothing to run and reads the real files rather than a fixture.

    python3 -m unittest discover -s scripts/tests -t scripts/tests
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "core" / "src"))

from pantler_core import load_pack  # noqa: E402


class PacksLoadTestCase(unittest.TestCase):
    def test_the_packs_directory_holds_at_least_one_pack(self) -> None:
        manifests = sorted((ROOT / "packs").glob("*/pack.toml"))
        self.assertTrue(manifests, "packs/ carries no pack.toml at all")

    def test_every_pack_manifest_loads(self) -> None:
        roots = [ROOT / "packs", ROOT / "packs-fixtures"]
        for root in roots:
            for manifest in sorted(root.glob("*/pack.toml")):
                with self.subTest(pack=f"{root.name}/{manifest.parent.name}"):
                    pack = load_pack(manifest)
                    self.assertTrue(pack.id, f"{manifest} has no id")
                    self.assertTrue(pack.records, f"{pack.id} declares no record types")

    def test_the_fixture_is_not_in_the_shipped_pack_root(self) -> None:
        """`packs/` is what an operator's BFF loads; the contract fixture is not that.

        While the fixture sat in `packs/`, the development app offered a `note` record type and a
        "Notes" screen that no part of the product defines
        (the internal audit PACK-1).
        """
        shipped = {path.parent.name for path in (ROOT / "packs").glob("*/pack.toml")}
        self.assertNotIn("example", shipped)
        self.assertTrue((ROOT / "packs-fixtures" / "example" / "pack.toml").is_file())

    def test_the_farm_pack_declares_the_spray_slice(self) -> None:
        """The Phase 0 slice, asserted where it is declared rather than where it is used."""
        pack = load_pack(ROOT / "packs" / "farm" / "pack.toml")
        self.assertEqual(pack.id, "farm")
        types = {record.type for record in pack.records}
        self.assertLessEqual({"block", "input", "application", "harvest"}, types)

        application = pack.record_type("application")
        assert application is not None
        fields = {field.name: field for field in application.fields}
        for name in ("date", "block", "input", "rate", "rate_unit"):
            self.assertIn(name, fields, f"the application record has no {name}")
        # The label fact and the frozen copy agree by design: one is entered, one is recorded.
        self.assertIn("withholding_days", {f.name for f in pack.record_type("input").fields})
        self.assertIn("earliest_safe_date", fields)
        self.assertEqual(fields["block"].kind, "reference")
        self.assertEqual(fields["block"].reference, "block")

    def test_the_trade_pack_declares_the_records_two_skills_asked_for(self) -> None:
        """Both records exist because a shipped skill said nobody had them.

        `reviews-and-testimonials` refuses to file a consent in a `notes` field — "that is inventing
        storage" — and `campaign-calendar` says no pack holds a campaign. If either record is renamed
        or a required field disappears, those skills start describing machinery that is not there.
        """
        pack = load_pack(ROOT / "packs" / "trade" / "pack.toml")
        self.assertEqual(pack.id, "trade")

        consent = pack.record_type("consent")
        assert consent is not None
        fields = {field.name for field in consent.fields}
        for name in ("who", "what", "where_used", "given_on", "how", "kept_where"):
            self.assertIn(name, fields, f"the consent record has no {name}")
        required = {field.name for field in consent.fields if field.required}
        # A consent with no *what* or no *where* is not a consent, so both are compulsory.
        self.assertEqual(required, {"who", "what", "where_used"})

        campaign = pack.record_type("campaign")
        assert campaign is not None
        self.assertIn("status", {field.name for field in campaign.fields})

    def test_no_record_type_is_declared_twice(self) -> None:
        """The store keys records by type, so two packs claiming one type would merge silently."""
        seen: dict[str, str] = {}
        for manifest in sorted((ROOT / "packs").glob("*/pack.toml")):
            pack = load_pack(manifest)
            for record in pack.records:
                with self.subTest(type=record.type):
                    self.assertNotIn(
                        record.type, seen, f"{record.type} is declared by {seen.get(record.type)} too"
                    )
                    seen[record.type] = pack.id

    def test_screens_point_at_record_types_that_exist(self) -> None:
        for manifest in sorted((ROOT / "packs").glob("*/pack.toml")):
            pack = load_pack(manifest)
            types = {record.type for record in pack.records}
            for screen in pack.screens:
                with self.subTest(pack=pack.id, screen=screen.id):
                    self.assertIn(screen.record_type, types)


if __name__ == "__main__":
    unittest.main()
