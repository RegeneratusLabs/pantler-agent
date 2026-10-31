"""The profile-key repair tool: fill missing values, rotate on request, never print the secret."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "sync-profile-keys.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("pantler_sync_profile_keys", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["pantler_sync_profile_keys"] = module
    spec.loader.exec_module(module)
    return module


class SyncProfileKeysTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.profiles = self.root / "profiles"
        self.install = self.profiles / "pantler"
        self.install.mkdir(parents=True)
        (self.install / "config.yaml").write_text("model: {}\n", encoding="utf-8")
        (self.install / ".env").write_text("API_SERVER_KEY=test\n", encoding="utf-8")
        self.tool = load_tool()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def profile(self, name: str, env: str = "") -> Path:
        path = self.profiles / name
        path.mkdir()
        (path / "config.yaml").write_text("model: {}\n", encoding="utf-8")
        if env:
            (path / ".env").write_text(env, encoding="utf-8")
        return path

    def run_tool(self, *args: str) -> tuple[int, str]:
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            code = self.tool.main(
                ["--profiles-root", str(self.profiles), *args]
            )
        return code, output.getvalue()

    def test_fills_a_missing_key_and_keeps_an_existing_one(self) -> None:
        (self.install / ".env").write_text("COMPOSIO_API_KEY=ak_install\n", encoding="utf-8")
        first = self.profile("first", "API_SERVER_KEY=one\n")
        second = self.profile("second", "COMPOSIO_API_KEY=ak_second\n")

        code, output = self.run_tool()

        self.assertEqual(code, 0)
        self.assertIn("COMPOSIO_API_KEY=ak_install", (first / ".env").read_text())
        self.assertEqual((first / ".env").stat().st_mode & 0o777, 0o600)
        self.assertIn("COMPOSIO_API_KEY=ak_second", (second / ".env").read_text())
        self.assertNotIn("ak_install", output)

    def test_force_rotates_an_existing_key(self) -> None:
        (self.install / ".env").write_text("COMPOSIO_API_KEY=ak_new\n", encoding="utf-8")
        first = self.profile("first", "COMPOSIO_API_KEY=ak_old\n")

        code, _ = self.run_tool("--force")

        self.assertEqual(code, 0)
        self.assertIn("COMPOSIO_API_KEY=ak_new", (first / ".env").read_text())
        self.assertNotIn("ak_old", (first / ".env").read_text())

    def test_deployment_environment_wins(self) -> None:
        (self.install / ".env").write_text("COMPOSIO_API_KEY=ak_file\n", encoding="utf-8")
        first = self.profile("first", "API_SERVER_KEY=one\n")

        with patch.dict(os.environ, {"PANTLER_COMPOSIO_API_KEY": "ak_deployment"}):
            code, _ = self.run_tool()

        self.assertEqual(code, 0)
        self.assertIn("COMPOSIO_API_KEY=ak_deployment", (first / ".env").read_text())

    def test_no_source_is_a_refusal_not_a_crash(self) -> None:
        first = self.profile("first", "API_SERVER_KEY=one\n")
        with patch.dict(os.environ, {"PANTLER_COMPOSIO_API_KEY": ""}):
            code, output = self.run_tool()

        self.assertEqual(code, 2)
        self.assertIn("no value", output)
        self.assertNotIn("COMPOSIO_API_KEY", (first / ".env").read_text())

    def test_dry_run_writes_nothing(self) -> None:
        (self.install / ".env").write_text("COMPOSIO_API_KEY=ak_install\n", encoding="utf-8")
        first = self.profile("first", "API_SERVER_KEY=one\n")

        code, output = self.run_tool("--dry-run")

        self.assertEqual(code, 0)
        self.assertIn("would set COMPOSIO_API_KEY", output)
        self.assertNotIn("COMPOSIO_API_KEY", (first / ".env").read_text())


if __name__ == "__main__":
    unittest.main()
