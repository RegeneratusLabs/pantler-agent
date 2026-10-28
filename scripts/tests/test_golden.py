"""Tests for the golden conversation's judgement.

`scripts/golden.py` promised "a pass/fail on what the invoice tools did" in its docstring and
returned 0 whatever happened: a run that failed, an approval nobody expected, and an invoice reply
that read as sent were all printed and ignored (the internal audit SCR-6). The transport is
not unit-testable here; the judgement is, and these tests are what keep it honest.

    python3 -m unittest discover -s scripts/tests -t scripts/tests
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]


def load_golden():
    path = ROOT / "scripts" / "golden.py"
    spec = importlib.util.spec_from_file_location("pantler_golden", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["pantler_golden"] = module
    spec.loader.exec_module(module)
    return module


def terminal(kind: str, **fields) -> dict:
    return {"event": kind, **fields}


class JudgementTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.golden = load_golden()

    def judged(self, *events) -> object:
        report = self.golden.Report()
        for event in events:
            report.feed(event)
        report.judge()
        return report

    def test_a_completed_run_passes(self) -> None:
        report = self.judged(
            {"event": "tool.started", "tool": "invoice_create"},
            terminal("run.completed", output="Draft INV-0001 for Bellview CSA, not sent."),
        )
        self.assertEqual(report.failures, [])

    def test_a_failed_run_fails_and_carries_the_engines_reason(self) -> None:
        report = self.judged(
            terminal("run.failed", error="HTTP 401: This API key has expired.")
        )
        self.assertEqual(len(report.failures), 1)
        self.assertIn("HTTP 401", report.failures[0])
        self.assertIn("FAILED", report.summary())

    def test_an_approval_request_is_a_failure(self) -> None:
        """Nothing this plugin registers is outbound, so a park here means the surface changed."""
        report = self.judged(
            {"event": "approval.request", "description": "send an email"},
            terminal("run.completed", output="done"),
        )
        self.assertTrue(any("approval" in failure for failure in report.failures), report.failures)

    def test_an_invoice_reply_that_reads_as_sent_fails(self) -> None:
        report = self.judged(
            {"event": "tool.started", "tool": "invoice_create"},
            terminal("run.completed", output="Sent INV-0001 to Bellview CSA."),
        )
        self.assertTrue(any("draft" in failure for failure in report.failures), report.failures)

    def test_an_invoice_tool_with_no_reply_fails(self) -> None:
        report = self.judged(
            {"event": "tool.started", "tool": "invoice_create"},
            terminal("run.completed", output=""),
        )
        self.assertTrue(any("nothing" in failure for failure in report.failures), report.failures)

    def test_a_run_with_no_invoice_tool_is_not_judged_on_invoice_words(self) -> None:
        report = self.judged(
            {"event": "tool.started", "tool": "records_find"},
            terminal("run.completed", output="No records."),
        )
        self.assertEqual(report.failures, [])


class ApiKeyTestCase(unittest.TestCase):
    """The bearer token comes from the environment or `--key-file`, never argv.

    A `--key` on the command line is visible in `ps` and the shell's history; `test.sh` and the
    docs never passed it, so it is gone (the internal security audit A19-SC-8).
    """

    def setUp(self) -> None:
        self.golden = load_golden()

    def test_the_environment_wins_over_the_key_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            key_file = Path(tmp) / ".env"
            key_file.write_text("API_SERVER_KEY=from-the-file\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {"PANTLER_API_KEY": "from-the-environment"}):
                self.assertEqual(self.golden.api_key(key_file), "from-the-environment")
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("PANTLER_API_KEY", None)
                self.assertEqual(self.golden.api_key(key_file), "from-the-file")

    def test_a_missing_key_file_is_an_empty_key_not_a_traceback(self) -> None:
        self.assertEqual(self.golden.api_key(Path("/nonexistent/.env")), "")

    def test_the_profile_is_derived_from_the_key_file(self) -> None:
        self.assertEqual(
            self.golden.profile_for(Path("/home/x/.hermes-dev/profiles/pantler/.env")), "pantler"
        )
        self.assertEqual(self.golden.profile_for(Path("/home/x/.hermes-dev/.env")), "")
        self.assertEqual(
            self.golden.api_base("http://127.0.0.1:8644/", "pantler"),
            "http://127.0.0.1:8644/p/pantler",
        )
        self.assertEqual(self.golden.api_base("http://127.0.0.1:8644", ""), "http://127.0.0.1:8644")

    def test_there_is_no_key_flag(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                self.golden.main(["--key", "a-token-in-plain-sight"])


if __name__ == "__main__":
    unittest.main()
