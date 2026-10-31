"""The bundled skill and the distribution's discoverable copy must not drift.

A skill registered by a plugin is namespaced and read-only and does **not** reach the system
prompt's skill index; the copy the distribution installs under `distribution/skills/` is the
one that does ([`../../README.md`](../../README.md)). The plugin keeps a bundled copy so it
stays self-contained, which means two copies of one file — and two copies kept in step by
hand are two copies that drift. This test is what keeps them identical.
"""
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(PLUGIN))
NAME = "soil-amendment-engine"
BUNDLED = os.path.join(PLUGIN, "skills", NAME, "SKILL.md")
SHIPPED = os.path.join(REPO, "distribution", "skills", NAME, "SKILL.md")


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


class TestBundledSkill(unittest.TestCase):

    def test_both_copies_exist(self):
        self.assertTrue(os.path.isfile(BUNDLED), f"bundled skill missing: {BUNDLED}")
        self.assertTrue(os.path.isfile(SHIPPED), f"distribution skill missing: {SHIPPED}")

    def test_copies_are_identical(self):
        self.assertEqual(
            _read(BUNDLED), _read(SHIPPED),
            "the bundled skill and the distribution skill have drifted; "
            "edit one and copy it to the other",
        )

    def test_frontmatter_names_the_directory_and_declares_mit(self):
        """The spec requires `name` to match the parent directory; the house rules add MIT."""
        text = _read(SHIPPED)
        self.assertTrue(text.startswith("---\n"), "SKILL.md must open with frontmatter")
        frontmatter = text.split("---\n", 2)[1]
        name = re.search(r"^name:\s*(\S+)\s*$", frontmatter, re.MULTILINE)
        self.assertIsNotNone(name, "frontmatter declares no name")
        self.assertEqual(name.group(1), NAME)
        self.assertEqual(name.group(1), os.path.basename(os.path.dirname(SHIPPED)))
        self.assertRegex(frontmatter, r"(?m)^license:\s*MIT\s*$", "frontmatter must declare MIT")


if __name__ == "__main__":
    unittest.main()
