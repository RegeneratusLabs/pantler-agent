"""Tests for the scenario runner's judgement — the part that decides pass from fail.

The runner talks to a live gateway, so its transport is not unit-testable here. Its *judgement* is,
and that is the part worth protecting: the first version of this harness read the wrong event name,
got an empty reply for every scenario, and reported 3/3 passed. Every `reply_excludes` assertion was
passing against an empty string. The guard below is what makes that impossible, and these tests are
what keep the guard honest.

Run through `scripts/test.sh python`, or directly:

    python3 -m unittest discover -s scripts/tests -t scripts/tests
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]


def load_runner():
    path = ROOT / "scripts" / "scenarios.py"
    spec = importlib.util.spec_from_file_location("pantler_scenarios", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["pantler_scenarios"] = module
    spec.loader.exec_module(module)
    return module


class ShippedScenariosTestCase(unittest.TestCase):
    """The shipped file is data, and a typo in it is an assertion that never runs."""

    def test_every_shipped_expectation_is_understood(self) -> None:
        runner = load_runner()
        scenarios, problems = runner.load_scenarios()
        self.assertEqual(problems, [])
        self.assertTrue(scenarios)
        for scenario in scenarios:
            with self.subTest(scenario=scenario["id"]):
                self.assertEqual(runner.unknown_expectations(scenario), [])

    def test_a_typo_in_a_hard_entry_is_a_failure(self) -> None:
        """`hard = set(expect.get("hard") or [])` was only ever read with `in`.

        `hard: ["reply_match"]` — one letter short — left the assertion advisory and said nothing
        (the internal audit SCN-1).
        """
        runner = load_runner()
        self.assertEqual(runner.unknown_expectations({"id": "x", "expect": {"hard": ["reply_matches"]}}), [])
        self.assertEqual(
            runner.unknown_expectations({"id": "x", "expect": {"hard": ["reply_match"]}}),
            ["hard:reply_match"],
        )

    def test_every_shipped_capability_label_resolves(self) -> None:
        """The labels mix skill names and toolset names, and nothing resolved them."""
        runner = load_runner()
        scenarios, problems = runner.load_scenarios()
        self.assertEqual(problems, [])
        self.assertEqual(runner.capabilities_known(scenarios), [])

    def test_an_unknown_capability_label_is_reported(self) -> None:
        runner = load_runner()
        problems = runner.capabilities_known([{"id": "x", "capability": "no-such-skill"}])
        self.assertEqual(len(problems), 1)
        self.assertIn("no-such-skill", problems[0])

    def test_a_typo_in_an_expectation_is_a_failure_not_a_no_op(self) -> None:
        runner = load_runner()
        run = runner.Run()
        run.text = "Delivery in 3 days."
        failures, _ = runner.evaluate(
            {
                "id": "typo",
                "turns": ["x"],
                "expect": {"reply_exclude": ["3 days"]},  # missing the `s`
            },
            run,
        )
        self.assertTrue(any("does not understand" in failure for failure in failures), failures)

    def test_an_unreadable_scenario_file_is_reported(self) -> None:
        """A truncated file used to be printed and skipped, so its scenarios never ran.

        The suite still reported a total, and nothing said the total was smaller than the file
        count (the internal audit SCR-7).
        """
        runner = load_runner()
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "broken.json").write_text("{not json", encoding="utf-8")
            (directory / "fine.json").write_text(
                json.dumps({"scenarios": [{"id": "ok-scenario", "turns": ["hi"]}]}),
                encoding="utf-8",
            )
            found, problems = runner.load_scenarios(directory)
        self.assertEqual([scenario["id"] for scenario in found], ["ok-scenario"])
        self.assertEqual(len(problems), 1)
        self.assertIn("broken.json", problems[0])

    def test_a_scenario_without_an_id_is_reported(self) -> None:
        runner = load_runner()
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "nameless.json").write_text(
                json.dumps({"scenarios": [{"turns": ["hi"]}]}), encoding="utf-8"
            )
            found, problems = runner.load_scenarios(directory)
        self.assertEqual(found, [])
        self.assertTrue(any("without an id" in problem for problem in problems), problems)


class EvaluateTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = load_runner()

    def run_with(self, reply: str | None = None, **kwargs):
        """A Run with the given state; `reply` is written through the streamed-text list."""
        run = self.runner.Run()
        for key, value in kwargs.items():
            setattr(run, key, value)
        if reply is not None:
            run.text = [reply]
        return run

    def test_an_empty_reply_fails_rather_than_passing_vacuously(self) -> None:
        """The bug that made this file necessary: no text, every `reply_excludes` satisfied."""
        run = self.run_with(reply_text="", tools=["invoice_create"])
        scenario = {
            "expect": {
                "tools_none": ["invoice_create"],
                "reply_excludes": ["\\b\\d+ days\\b"],
            }
        }
        failures, _ = self.runner.evaluate(scenario, run)
        self.assertTrue(any("no assistant text" in line for line in failures), failures)

    def test_an_excluded_pattern_in_the_reply_fails(self) -> None:
        run = self.run_with(reply="Copper oxychloride needs 14 days before harvest.")
        failures, _ = self.runner.evaluate(
            {"expect": {"reply_excludes": ["\\b\\d+ days\\b"]}}, run
        )
        self.assertTrue(any("must not" in line for line in failures), failures)

    def test_a_clean_reply_passes(self) -> None:
        run = self.run_with(reply="I don't have the label, so I can't give you a number.")
        failures, _ = self.runner.evaluate(
            {"expect": {"reply_excludes": ["\\b\\d+ days\\b"]}}, run
        )
        self.assertEqual(failures, [])

    def test_a_missing_required_tool_fails(self) -> None:
        run = self.run_with(reply="Here is your draft.", tools=["skills_list"])
        failures, _ = self.runner.evaluate({"expect": {"tools_any": ["invoice_create"]}}, run)
        self.assertTrue(any("none of" in line for line in failures), failures)

    def test_a_forbidden_tool_fails(self) -> None:
        run = self.run_with(reply="Drafted.", tools=["invoice_create"])
        failures, _ = self.runner.evaluate({"expect": {"tools_none": ["invoice_create"]}}, run)
        self.assertTrue(any("must not" in line for line in failures), failures)

    def test_a_tool_over_its_limit_fails_when_hard(self) -> None:
        run = self.run_with(reply="Loading skills.", tools=["skill_view", "skill_view", "skill_view"])
        failures, advisories = self.runner.evaluate(
            {"expect": {"tools_max": {"skill_view": 2}, "hard": ["tools_max"]}}, run
        )
        self.assertEqual(advisories, [])
        self.assertTrue(any("at most 2" in line for line in failures), failures)

        advisory_failures, advisory = self.runner.evaluate(
            {"expect": {"tools_max": {"skill_view": 2}}}, run
        )
        self.assertEqual(advisory_failures, [])
        self.assertEqual(len(advisory), 1)

    def test_a_tool_under_its_limit_passes(self) -> None:
        run = self.run_with(reply="Loading the design skill.", tools=["skill_view"])
        failures, advisories = self.runner.evaluate(
            {"expect": {"tools_max": {"skill_view": 2}, "hard": ["tools_max"]}}, run
        )
        self.assertEqual(failures, [])
        self.assertEqual(advisories, [])

    def test_a_malformed_tools_max_is_a_failure(self) -> None:
        run = self.run_with(reply="Done.", tools=["skill_view"])
        failures, _ = self.runner.evaluate(
            {"expect": {"tools_max": ["skill_view"]}}, run
        )
        self.assertTrue(any("object mapping" in line for line in failures), failures)

    def test_a_reply_match_is_advisory_unless_the_scenario_says_hard(self) -> None:
        run = self.run_with(reply="The label is what settles it.")
        failures, advisories = self.runner.evaluate(
            {"expect": {"reply_matches": ["certifier"]}}, run
        )
        self.assertEqual(failures, [])
        self.assertEqual(len(advisories), 1)
        hard_failures, _ = self.runner.evaluate(
            {"expect": {"reply_matches": ["certifier"], "hard": ["reply_matches"]}}, run
        )
        self.assertEqual(len(hard_failures), 1)

    def test_the_reply_prefers_the_streamed_text_and_falls_back_to_the_output(self) -> None:
        streamed = self.run_with(text=["half ", "a reply"])
        self.assertEqual(streamed.reply, "half a reply")
        terminal = self.run_with(text=[], final="the whole reply")
        self.assertEqual(terminal.reply, "the whole reply")


class ApiKeyTestCase(unittest.TestCase):
    """The bearer token comes from the environment or the profile's `.env`, never argv.

    A `--key` on the command line is visible in `ps` and in the shell's history
    (the internal security audit A19-SC-8). Nothing in the repository called the flag, so
    it is gone rather than hidden, and these tests keep it gone.
    """

    def setUp(self) -> None:
        self.runner = load_runner()

    def test_the_environment_wins_over_the_key_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            key_file = Path(tmp) / ".env"
            key_file.write_text("API_SERVER_KEY=from-the-file\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {"PANTLER_API_KEY": "from-the-environment"}):
                self.assertEqual(self.runner.api_key(key_file), "from-the-environment")
            # `patch.dict` restores whatever was there, so the pop does not leak to other tests.
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("PANTLER_API_KEY", None)
                self.assertEqual(self.runner.api_key(key_file), "from-the-file")

    def test_there_is_no_key_flag(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                self.runner.main(["--key", "a-token-in-plain-sight"])


if __name__ == "__main__":
    unittest.main()
