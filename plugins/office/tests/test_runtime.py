"""The process boundary: what the child sees, and what a broken script tells the operator."""

from __future__ import annotations

import os
import unittest
from unittest import mock

from support import INTERPRETER, PLUGIN  # noqa: F401

from office.office_engine import runtime


class Environment(unittest.TestCase):
    def test_the_operators_secrets_are_not_passed_on(self):
        fake = {
            "PATH": "/usr/bin", "HOME": "/home/op", "LANG": "en_AU.UTF-8",
            "HERMES_HOME": "/home/op/.hermes", "PANTLER_STORE": "/home/op/records.db",
            "OPENAI_API_KEY": "sk-live", "ANTHROPIC_API_KEY": "sk-ant",
            "GITHUB_TOKEN": "ghp_x", "AWS_SECRET_ACCESS_KEY": "aws",
            "COMPOSIO_API_KEY": "ak_1", "MY_SECRET": "s", "PYTHONPATH": "/somewhere",
        }
        with mock.patch.dict(os.environ, fake, clear=True):
            kept = runtime.environment()
        for key in ("HERMES_HOME", "PANTLER_STORE", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
                    "GITHUB_TOKEN", "AWS_SECRET_ACCESS_KEY", "COMPOSIO_API_KEY", "MY_SECRET",
                    "PYTHONPATH"):
            self.assertNotIn(key, kept)
        self.assertEqual(kept["PATH"], "/usr/bin")
        self.assertEqual(kept["HOME"], "/home/op")


class Results(unittest.TestCase):
    def test_empty_output_is_an_error(self):
        with self.assertRaises(runtime.OfficeError):
            runtime._json(b"")

    def test_prose_is_an_error_that_quotes_it(self):
        with self.assertRaises(runtime.OfficeError) as caught:
            runtime._json(b"Traceback (most recent call last)")
        self.assertIn("Traceback", str(caught.exception))

    def test_an_array_is_not_a_result(self):
        with self.assertRaises(runtime.OfficeError):
            runtime._json(b"[1, 2, 3]")

    def test_an_unknown_script_is_named(self):
        with self.assertRaises(runtime.OfficeError) as caught:
            runtime.script("nope.py")
        self.assertIn("nope.py", str(caught.exception))

    def test_the_failure_message_prefers_the_scripts_own_json(self):
        class Done:
            returncode = 1
            stderr = b'{"ok": false, "error": "the sheet name is taken"}\n'

        self.assertIn("the sheet name is taken", runtime._failure("x.py", Done()))

    def test_the_failure_message_falls_back_to_stderr(self):
        class Done:
            returncode = 2
            stderr = b"boom\nboom again\n"

        message = runtime._failure("x.py", Done())
        self.assertIn("exit 2", message)
        self.assertIn("boom again", message)


@unittest.skipUnless(INTERPRETER, "no interpreter with the office libraries")
class Interpreter(unittest.TestCase):
    def test_find_python_returns_one_that_imports_the_libraries(self):
        chosen = runtime.find_python()
        self.assertTrue(os.path.isfile(chosen))
        self.assertTrue(runtime._probe(chosen))

    def test_a_bad_explicit_interpreter_is_refused_with_the_reason(self):
        with mock.patch.dict(os.environ, {"PANTLER_OFFICE_PYTHON": "/bin/false"}):
            with self.assertRaises(runtime.OfficeError) as caught:
                runtime.find_python()
        self.assertIn("PANTLER_OFFICE_PYTHON", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
