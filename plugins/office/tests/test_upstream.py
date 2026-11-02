"""The vendored scripts are the pinned engine's, and this is how that stays true.

`UPSTREAM.sha256` records what was copied. A file that changes without the manifest changing is
either an edit nobody wrote down or a re-sync nobody finished, and either one turns the provenance
page into fiction. This test is the mechanical half of a policy whose other half is prose.
"""

from __future__ import annotations

import hashlib
import unittest
from pathlib import Path

from support import PLUGIN  # noqa: F401  (puts `plugins/` on sys.path)

UPSTREAM = PLUGIN / "office_engine" / "upstream"
MANIFEST = PLUGIN / "UPSTREAM.sha256"


def recorded() -> dict[str, str]:
    entries: dict[str, str] = {}
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, _, name = line.partition(" ")
        entries[name.strip()] = digest.strip()
    return entries


class Vendored(unittest.TestCase):
    def test_every_recorded_file_is_here_and_unchanged(self):
        entries = recorded()
        self.assertTrue(entries, "UPSTREAM.sha256 is empty")
        for name, digest in entries.items():
            path = UPSTREAM / name
            self.assertTrue(path.is_file(), f"{name} is in the manifest but not on disk")
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(actual, digest,
                             f"{name} no longer matches the pin. If this was a deliberate re-sync, "
                             f"update UPSTREAM.sha256 and PROVENANCE.md in the same commit.")

    def test_nothing_ships_that_the_manifest_does_not_name(self):
        entries = set(recorded())
        shipped = {path.name for path in UPSTREAM.glob("*.py")}
        self.assertEqual(shipped, entries,
                         "a script in upstream/ is not in the manifest, so nothing records where it "
                         "came from")

    def test_the_upstream_licence_travels(self):
        licence = PLUGIN / "LICENSE.engine"
        self.assertTrue(licence.is_file())
        text = licence.read_text(encoding="utf-8")
        self.assertIn("MIT License", text)
        self.assertIn("Nous Research", text)

    def test_the_provenance_page_names_the_pin(self):
        page = (PLUGIN / "PROVENANCE.md").read_text(encoding="utf-8")
        self.assertIn("bf0203a794a07aac3ff764972ab9087baa4e4f4e", page)
        for name in recorded():
            self.assertIn(name, page)


if __name__ == "__main__":
    unittest.main()
