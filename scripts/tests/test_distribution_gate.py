"""The distribution gate's own behaviour, on trees that are and are not shippable.

The gate is what stands between the payload and an operator's machine, and two of its rules are
*warnings*: the files a fresh install has to be given, which we deliberately do not ship
(the internal audit DIST-2). A warning nobody tests is a warning that quietly stops
firing, so these tests drive the real functions against the real payload.

DIST-7 used to belong to that list. The payload carries its own `LICENSE` now, so the gate must
*not* warn about it — a warning that outlives the fix is the mirror image of the bug above.

    python3 -m unittest discover -s scripts/tests -t scripts/tests
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_gate():
    path = ROOT / "scripts" / "check-distribution.py"
    spec = importlib.util.spec_from_file_location("pantler_check_distribution", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["pantler_check_distribution"] = module
    spec.loader.exec_module(module)
    return module


class OperatorOwesTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.gate = load_gate()
        self.gate.problems.clear()
        self.gate.warnings.clear()

    def tearDown(self) -> None:
        self.gate.problems.clear()
        self.gate.warnings.clear()

    def test_the_shipped_payload_warns_about_every_file_it_does_not_carry(self) -> None:
        self.gate.check_operator_owes()
        joined = "\n".join(self.gate.warnings)
        self.assertIn("pricebook.json", joined)
        self.assertIn("spraybook.json", joined)
        # DIST-7 is closed by shipping one: the manifest's `license: MIT` has a document beside
        # it, so the gate says nothing about it (and the licence travels with the payload).
        self.assertNotIn("LICENSE", joined)
        self.assertTrue((ROOT / "distribution" / "LICENSE").is_file(),
                        "the payload lost the licence DIST-7 was closed with")
        # A warning is not a failure: the payload is still shippable.
        self.assertEqual(self.gate.problems, [])

    def test_a_book_in_the_payload_silences_its_warning(self) -> None:
        original = self.gate.DISTRIBUTION
        with tempfile.TemporaryDirectory() as tmp:
            payload = Path(tmp)
            (payload / "pricebook.json").write_text("{}")
            self.gate.DISTRIBUTION = payload
            try:
                self.gate.check_operator_owes()
            finally:
                self.gate.DISTRIBUTION = original
        joined = "\n".join(self.gate.warnings)
        self.assertNotIn("no pricebook.json", joined)
        self.assertIn("spraybook.json", joined)

    def test_an_unreadable_file_is_a_problem_not_a_missing_one(self) -> None:
        """`read()` returned "" for any OSError, so unreadable read as absent (SCR-2)."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "unreadable"
            path.mkdir()
            self.gate.read(path)  # a directory is not a file: OSError, and not FileNotFoundError
        self.assertTrue(self.gate.problems, "an unreadable path was reported as nothing")


#: A suppression list naming real toolsets, in the block form. The shipped file carries no list at
#: all (see `test_the_honest_file_passes`); this shape is what an *operator's* own edit looks like,
#: and the gate still has to read it honestly when they write one.
DISABLING_CONFIG = """approvals:
  mode: manual
agent:
  disabled_toolsets:
    - browser
    - terminal
    - code_execution
    - computer_use
    - image_gen
    - delegation
    - connections
"""


class ConfigScannerTestCase(unittest.TestCase):
    """`nested_list` returned any list under the parent, so the config gate passed on nothing.

    The gate reads YAML with hand-rolled scanners because CI installs nothing, and the scanner
    used to reset its span only when it saw the *wanted* key, so a decoy list under `agent:` handed
    `check_config` names the engine does not read (the internal security audit A19-SC-1). The
    gate no longer requires a suppression list — the shipped file suppresses nothing — but the
    scanner must still read one honestly when an operator writes it, and the validity check must
    still fail on a name the engine would ignore.
    """

    def setUp(self) -> None:
        self.gate = load_gate()
        self.gate.problems.clear()
        self.gate.warnings.clear()

    def tearDown(self) -> None:
        self.gate.problems.clear()
        self.gate.warnings.clear()

    def problems_for(self, config: str) -> list[str]:
        """`check_config`'s findings against a payload that carries this `config.yaml`."""
        original = self.gate.DISTRIBUTION
        with tempfile.TemporaryDirectory() as tmp:
            payload = Path(tmp)
            (payload / "config.yaml").write_text(config)
            self.gate.DISTRIBUTION = payload
            try:
                self.gate.check_config()
                return list(self.gate.problems)
            finally:
                self.gate.DISTRIBUTION = original
                self.gate.problems.clear()

    def test_the_honest_file_passes(self) -> None:
        self.gate.check_config()
        self.assertEqual(self.gate.problems, [])
        text = (self.gate.DISTRIBUTION / "config.yaml").read_text()
        self.assertIsNone(
            self.gate.nested_list(text, "agent", "disabled_toolsets"),
            "the shipped config suppresses a toolset again: the surface is the operator's to "
            "switch, not the install's to remove",
        )

    def test_the_shipped_config_enables_clarify_with_the_composite(self) -> None:
        """The API-server surface names the composite plus `clarify`, not an enumerated list.

        `clarify` is deliberately absent from `hermes-api-server`; naming the composite keeps
        every toolset the engine's default loads (and whatever it adds next), and `clarify` is
        the one addition the app can answer. An enumerated list would freeze the surface, and a
        missing `clarify` would silently take the question card away from a fresh install.
        """
        text = (self.gate.DISTRIBUTION / "config.yaml").read_text()
        toolsets = self.gate.nested_list(text, "platform_toolsets", "api_server")
        self.assertIsNotNone(
            toolsets,
            "distribution/config.yaml has no `platform_toolsets.api_server` list; the engine's "
            "API-server default omits `clarify`, so a fresh install would have no question card",
        )
        self.assertIn("hermes-api-server", toolsets or [])
        self.assertIn("clarify", toolsets or [])

    def test_the_shipped_hint_asks_for_markdown(self) -> None:
        """The shell renders markdown, so the api_server hint must not forbid it again.

        `config.yaml` is preserved on `profile update`, which is why the app also sends the
        format instruction with every turn (`onboarding/personalities.ts`). A fresh install still
        reads this hint, though, and the old "Prose is plain text" sentence was the instruction
        the model actually followed.
        """
        text = (self.gate.DISTRIBUTION / "config.yaml").read_text()
        self.assertIn("which renders markdown", text)
        self.assertNotIn("Prose is plain text", text)

    def test_a_suppression_list_of_real_toolsets_passes(self) -> None:
        """An operator may switch a capability off; a list naming real toolsets is their call."""
        self.assertEqual(self.problems_for(DISABLING_CONFIG), [])

    def test_a_name_the_engine_does_not_know_fails(self) -> None:
        """A typo is warned about and ignored, so the capability stays on while the file reads off."""
        problems = self.problems_for(DISABLING_CONFIG.replace("- browser", "- browzer"))
        self.assertTrue(problems, "a name the engine ignores left the gate green")
        self.assertTrue(any("browzer" in problem for problem in problems), problems)

    def test_a_config_that_suppresses_nothing_passes(self) -> None:
        """No `agent:` block at all is the shipped shape, and it is not a failure."""
        self.assertEqual(self.problems_for("approvals:\n  mode: manual\n"), [])

    def test_an_empty_list_passes(self) -> None:
        self.assertEqual(
            self.problems_for("approvals:\n  mode: manual\nagent:\n  disabled_toolsets: []\n"), []
        )

    def test_an_inline_list_passes(self) -> None:
        inline = DISABLING_CONFIG.replace(
            "  disabled_toolsets:\n    - browser\n    - terminal\n    - code_execution\n"
            "    - computer_use\n    - image_gen\n    - delegation\n    - connections\n",
            "  disabled_toolsets: [browser, terminal, code_execution, computer_use, image_gen, "
            "delegation, connections]\n",
        )
        self.assertNotEqual(inline, DISABLING_CONFIG)
        self.assertEqual(self.problems_for(inline), [])

    def test_the_scanner_still_tells_absent_from_empty(self) -> None:
        """The scanner's contract: `None` means "no such key", `[]` means an empty one.

        The gate now treats both as "suppresses nothing", but the distinction is what lets it tell
        the shipped shape from an operator's explicit empty list, so it stays asserted.
        """
        self.assertIsNone(self.gate.nested_list(DISABLING_CONFIG, "agent", "enabled_toolsets"))
        self.assertIsNone(self.gate.nested_list(DISABLING_CONFIG, "nobody", "disabled_toolsets"))
        self.assertEqual(self.gate.nested_list("agent:\n  disabled_toolsets: []\n", "agent", "disabled_toolsets"), [])


class DeclaredToolsTestCase(unittest.TestCase):
    """A plugin's registration is read from every source file, and unreadable means failure.

    The check opened `plugin/tools.py` and `continue`d when it found no `_TOOLS` table, so
    `soil-amendment` — which registers both its tools by name in `__init__.py` — was never
    compared with `provides_tools`, and neither would be a plugin that moved its table
    (the internal security audit A19-SC-9).
    """

    def setUp(self) -> None:
        self.gate = load_gate()
        self.gate.problems.clear()
        self.gate.warnings.clear()

    def tearDown(self) -> None:
        self.gate.problems.clear()
        self.gate.warnings.clear()

    def problems_for(self, files: dict[str, str]) -> list[str]:
        """`check_declared_tools` against a scratch `plugins/` tree carrying these files."""
        original = self.gate.ROOT
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for relative, text in files.items():
                path = root / "plugins" / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
            self.gate.ROOT = root
            try:
                self.gate.check_declared_tools()
                return list(self.gate.problems)
            finally:
                self.gate.ROOT = original
                self.gate.problems.clear()

    def test_the_shipped_plugins_pass(self) -> None:
        self.gate.check_declared_tools()
        self.assertEqual(self.gate.problems, [])

    def test_registration_in_another_module_is_compared(self) -> None:
        problems = self.problems_for(
            {
                "gadget/plugin.yaml": "name: gadget\nprovides_tools:\n  - one\n",
                "gadget/__init__.py": (
                    "def register(ctx):\n"
                    '    ctx.register_tool(name="one", schema={}, handler=f)\n'
                    '    ctx.register_tool(\n        name="two",\n        schema={},\n'
                    "        handler=g,\n    )\n"
                ),
            }
        )
        self.assertTrue(any("'two'" in problem for problem in problems), problems)

    def test_a_registration_nothing_can_parse_fails_instead_of_skipping(self) -> None:
        problems = self.problems_for(
            {
                "phantom/plugin.yaml": "name: phantom\nprovides_tools:\n  - one\n",
                "phantom/__init__.py": (
                    "def register(ctx):\n"
                    "    for name in TOOL_NAMES:\n"
                    "        ctx.register_tool(name=name, schema={}, handler=f)\n"
                ),
            }
        )
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("registers tools but no `_TOOLS` table", problems[0])

    def test_a_plugin_that_registers_no_tools_is_not_a_problem(self) -> None:
        problems = self.problems_for(
            {
                "skills-only/plugin.yaml": "name: skills-only\ndescription: no tools\n",
                "skills-only/__init__.py": 'def register(ctx):\n    ctx.register_skill("x", "S")\n',
            }
        )
        self.assertEqual(problems, [])


if __name__ == "__main__":
    unittest.main()
