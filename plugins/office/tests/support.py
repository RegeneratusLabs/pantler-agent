"""Shared setup for the office plugin's tests: a workspace, a fake context, an interpreter.

The plugin's tools need three things the engine normally provides: a context that answers the
capability switch, a workspace to write into, and an interpreter that has the office libraries.
Here they are made explicit, and the dependency check is its own failing test rather than a silent
skip — a suite that quietly does nothing is worse than one that says what to install.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = Path(__file__).resolve().parents[1]
if str(PLUGIN.parent) not in sys.path:
    sys.path.insert(0, str(PLUGIN.parent))

PROBE = "import docx, openpyxl, pptx, lxml, xlsxwriter"
PROVISION = ("run `./scripts/dev-sync.sh` (or `uv pip install -r plugins/office/requirements.txt`) "
             "so the engine's interpreter has the office libraries")


def _has_office(interpreter: str) -> bool:
    try:
        done = subprocess.run([interpreter, "-c", PROBE], capture_output=True, timeout=60,
                              stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def find_interpreter() -> str | None:
    """The interpreter the vendored scripts can run under, chosen once for the whole suite."""
    chosen = os.environ.get("PANTLER_OFFICE_PYTHON", "").strip()
    if chosen and _has_office(chosen):
        return chosen
    candidates = [sys.executable]
    installs = ROOT / ".hermes-dev" / "installs"
    if installs.is_dir():
        venvs = sorted(installs.glob("*/environments/*/venv"),
                       key=lambda path: path.stat().st_mtime, reverse=True)
        for venv in venvs:
            for name in ("bin/python3", "bin/python", "Scripts/python.exe"):
                candidate = venv / name
                if candidate.is_file():
                    candidates.append(str(candidate))
                    break
    for candidate in candidates:
        if candidate and _has_office(candidate):
            os.environ["PANTLER_OFFICE_PYTHON"] = candidate
            return candidate
    return None


INTERPRETER = find_interpreter()


class Ctx:
    """The slice of the engine's context the tools actually read."""

    def __init__(self, settings: dict | None = None):
        self.settings = dict(settings or {})

    def get_config(self, key=None, default=None):
        return self.settings.get(key, default)


class ToolCase(unittest.TestCase):
    """A test with a temporary workspace, a fake context and the plugin's handlers wired."""

    settings: dict = {}

    def setUp(self) -> None:
        from office import tools

        self.tools = tools
        self._scratch = tempfile.TemporaryDirectory(prefix="pantler-office-test-")
        self.workspace = Path(self._scratch.name) / "workspace"
        (self.workspace / "output").mkdir(parents=True)
        self._previous_ctx = getattr(tools, "_CTX", None)
        settings = {"workspace_dir": str(self.workspace), "business_name": "Bellview Farm",
                    "currency": "$"}
        settings.update(self.settings)
        tools._CTX = Ctx(settings)

    def tearDown(self) -> None:
        self.tools._CTX = self._previous_ctx
        self._scratch.cleanup()

    def call(self, handler, params: dict) -> dict:
        import json

        raw = handler(params)
        return json.loads(raw)


class DependencyTest(unittest.TestCase):
    def test_office_libraries_are_installed(self):
        self.assertIsNotNone(INTERPRETER, "no interpreter has the office libraries; " + PROVISION)
