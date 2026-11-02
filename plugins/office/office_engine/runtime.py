"""Run one vendored script, with the engine's own interpreter and none of the operator's secrets.

The five scripts in `upstream/` are plain CLIs: a spec path in, JSON on stdout. This module is the
only place that starts a process, so the safety rules are in one place rather than five:

* **The interpreter is the engine's.** In the product that is `sys.executable` — the environment
  that `scripts/dev-sync.sh` and the desktop payload staged the office libraries into. On a dev
  machine whose test runner is a bare interpreter, it falls back to the engine's own venv, and if
  neither has the libraries it says exactly what to run instead of failing one import at a time.
* **The environment is scrubbed.** A workbook script has no business seeing `HERMES_*`,
  `PANTLER_*`, an API key or a token. It gets `PATH`, a temporary directory, a locale and its
  platform's basics.
* **Time and output are bounded.** A hostile or broken file must not hang the gateway or fill its
  memory through a pipe.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

UPSTREAM = Path(__file__).resolve().parent / "upstream"

#: What every vendored script imports. Probing once is what turns "no such module" into one
#: actionable sentence instead of a traceback from inside somebody else's argparse.
_PROBE = "import docx, openpyxl, pptx, lxml, xlsxwriter"

PROVISION = (
    "the office libraries are not installed in this machine's engine environment; run "
    "`./scripts/dev-sync.sh` (or `uv pip install -r plugins/office/requirements.txt`) and try again"
)

MAX_OUTPUT = 2 * 1024 * 1024
DEFAULT_TIMEOUT = 180.0

#: Keys a child never needs. Prefixes rather than a list of exact names, because a new provider
#: key should be excluded the day it lands rather than the day someone remembers this file.
_SECRET_PREFIXES = (
    "HERMES_", "PANTLER_", "COMPOSIO_", "OPENAI_", "ANTHROPIC_", "DEEPSEEK_", "GEMINI_",
    "GOOGLE_", "AWS_", "AZURE_", "GITHUB_", "GH_", "STRIPE_", "XERO_", "SMTP_",
)
_SECRET_SUFFIXES = ("_TOKEN", "_KEY", "_SECRET", "_PASSWORD", "_CREDENTIALS")
_SECRET_NAMES = frozenset({"SSH_AUTH_SOCK", "AWS_SESSION_TOKEN", "PYTHONPATH", "PYTHONHOME"})

_python_cache: dict[str, bool] = {}


class OfficeError(RuntimeError):
    """A vendored script refused, failed, or could not be run. The caller reports it, never hides it."""


def environment() -> dict[str, str]:
    """The child's environment: enough to run Python, nothing that belongs to the operator."""
    kept: dict[str, str] = {}
    for key, value in os.environ.items():
        if key in _SECRET_NAMES:
            continue
        if key.startswith(_SECRET_PREFIXES):
            continue
        if key.upper().endswith(_SECRET_SUFFIXES):
            continue
        kept[key] = value
    return kept


def _executable(path: str | Path) -> bool:
    candidate = Path(path)
    return candidate.is_file() and os.access(candidate, os.X_OK)


def _probe(interpreter: str) -> bool:
    cached = _python_cache.get(interpreter)
    if cached is not None:
        return cached
    ok = False
    if _executable(interpreter):
        try:
            done = subprocess.run(
                [interpreter, "-c", _PROBE],
                capture_output=True,
                timeout=60,
                env=environment(),
                stdin=subprocess.DEVNULL,
            )
            ok = done.returncode == 0
        except (OSError, subprocess.SubprocessError):
            ok = False
    _python_cache[interpreter] = ok
    return ok


def _engine_interpreters() -> list[str]:
    """The engine's own dependency environments, newest first.

    `installs/` keeps one environment per engine build and an update leaves the old one behind, so
    a single guessed path is how a plugin ends up importing from yesterday's venv.
    """
    homes = [os.environ.get("HERMES_HOME", "").strip(), str(Path.home() / ".hermes")]
    found: list[Path] = []
    for home in homes:
        if not home:
            continue
        root = Path(os.path.expanduser(home))
        for pattern in ("installs/*/environments/*/venv", "venv"):
            found.extend(path for path in root.glob(pattern) if path.is_dir())
    executables = []
    for venv in sorted(found, key=lambda path: path.stat().st_mtime, reverse=True):
        for name in ("bin/python3", "bin/python", "Scripts/python.exe"):
            candidate = venv / name
            if candidate.is_file():
                executables.append(str(candidate))
                break
    return executables


def find_python() -> str:
    """The interpreter the vendored scripts run under, or a refusal that says what to install."""
    chosen = os.environ.get("PANTLER_OFFICE_PYTHON", "").strip()
    if chosen:
        if _probe(chosen):
            return chosen
        raise OfficeError(f"PANTLER_OFFICE_PYTHON is set to {chosen!r}, but that interpreter has no "
                          f"office libraries: {PROVISION}.")
    candidates = [sys.executable, *_engine_interpreters()]
    for candidate in candidates:
        if candidate and _probe(candidate):
            return candidate
    raise OfficeError(f"{PROVISION}.")


def script(name: str) -> Path:
    """One vendored script by its file name (no paths from callers ever reach here)."""
    path = UPSTREAM / name
    if not path.is_file():
        raise OfficeError(f"the office format layer has no {name!r}; this build is incomplete")
    return path


def run(name: str, args: list[str], *, spec: dict | None = None,
        timeout: float = DEFAULT_TIMEOUT, cwd: Path | None = None) -> dict:
    """Run one script and return the JSON object it printed.

    `spec`, when given, is written to a private temporary file and its path is put where the
    script expects it (`args[0]`), so the caller never has to own a file to say what it wants.
    """
    interpreter = find_python()
    path = script(name)
    arguments = list(args)
    scratch: str | None = None
    if spec is not None:
        handle, scratch = tempfile.mkstemp(prefix="pantler-office-", suffix=".json")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as fh:
                json.dump(spec, fh, ensure_ascii=False)
        except BaseException:
            os.unlink(scratch)
            raise
        arguments = [scratch, *arguments]
    started = time.monotonic()
    try:
        done = subprocess.run(
            [interpreter, str(path), *arguments],
            capture_output=True,
            timeout=timeout,
            cwd=str(cwd) if cwd else None,
            env=environment(),
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired as exc:
        raise OfficeError(
            f"{name} did not finish within {timeout:.0f}s. Nothing was written; try a smaller "
            f"spec or a smaller sheet."
        ) from exc
    except OSError as exc:
        raise OfficeError(f"{name} could not start: {exc}") from exc
    finally:
        if scratch:
            try:
                os.unlink(scratch)
            except OSError:
                pass
    if len(done.stdout) > MAX_OUTPUT:
        raise OfficeError(f"{name} printed more than {MAX_OUTPUT // 1024} KB; that is a bug, not a "
                          f"document")
    if done.returncode != 0:
        raise OfficeError(_failure(name, done))
    payload = _json(done.stdout)
    if payload.get("ok") is False:
        raise OfficeError(f"{name} refused: {payload.get('error') or 'no reason given'}")
    payload.setdefault("seconds", round(time.monotonic() - started, 2))
    return payload


def _failure(name: str, done: subprocess.CompletedProcess) -> str:
    """The most useful sentence the child left behind: its JSON error, or the last stderr lines."""
    stderr = (done.stderr or b"").decode("utf-8", "replace").strip()
    for line in reversed(stderr.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                payload = json.loads(line)
            except ValueError:
                continue
            if payload.get("error"):
                return f"{name} failed: {payload['error']}"
    tail = " / ".join(line for line in stderr.splitlines()[-3:] if line.strip()) or "no output"
    return f"{name} failed (exit {done.returncode}): {tail}"


def _json(raw: bytes) -> dict:
    text = (raw or b"").decode("utf-8", "replace").strip()
    if not text:
        raise OfficeError("the office script printed nothing; there is no result to report")
    try:
        payload = json.loads(text)
    except ValueError as exc:
        raise OfficeError(f"the office script printed something that is not JSON: {text[:200]!r}") from exc
    if not isinstance(payload, dict):
        raise OfficeError("the office script printed a JSON value that is not an object")
    return payload
