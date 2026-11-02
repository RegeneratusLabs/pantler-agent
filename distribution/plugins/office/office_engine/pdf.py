"""The workbook as a PDF, with the browser the machine already has.

Same route as the `documents` skill and the studio's preview: find Chrome, Edge or Chromium, run
it headless once, and print the page we already rendered. No LibreOffice, no converter, no second
rendering engine — the page that is the preview is the page that becomes the PDF, so the two cannot
disagree.

The finder is a deliberate copy of `plugins/studio/studio_engine/screenshot.py`'s. A plugin is
loaded on its own and a shared support package is one more thing that has to be installed and
found; ten duplicated lines are cheaper, and `plugins/README.md` says so.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

_NAMES = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome",
          "msedge", "microsoft-edge")


class PdfError(RuntimeError):
    """No browser, or a browser that refused to print. The caller reports it; never hides it."""


def find_chromium(env: dict[str, str] | None = None, home: Path | None = None) -> Path | None:
    """The best executable for printing a local page: explicit choice, then what is installed."""
    environment = env if env is not None else os.environ
    explicit = (environment.get("PANTLER_CHROMIUM") or "").strip()
    if explicit and Path(explicit).is_file():
        return Path(explicit)

    root = Path(home or Path.home())
    cache = root / ".cache" / "ms-playwright"
    for pattern in ("chromium_headless_shell-*/chrome-headless-shell-*/chrome-headless-shell",
                    "chromium_headless_shell-*/chrome-linux*/chrome-headless-shell"):
        for match in sorted(cache.glob(pattern), reverse=True):
            if match.is_file():
                return match

    for name in _NAMES:
        found = shutil.which(name, path=environment.get("PATH"))
        if found:
            return Path(found)

    candidates = [
        root / ".local" / "bin" / "chromium",
        Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
        Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    ]
    for pattern in ("chromium-*/chrome-linux64/chrome", "chromium-*/chrome-linux*/chrome",
                    "chromium-*/chrome-mac*/Chromium.app/Contents/MacOS/Chromium"):
        for match in sorted(cache.glob(pattern), reverse=True) if cache.is_dir() else []:
            if match.is_file():
                return match
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def print_pdf(html_path: Path, out_path: Path, *, timeout: float = 60.0) -> dict:
    """Print a local page to `out_path`. Returns `{path, browser}`; raises `PdfError` otherwise."""
    executable = find_chromium()
    if executable is None:
        raise PdfError("no Chrome, Edge or Chromium was found, so no PDF was printed. The workbook "
                       "and its preview page are the deliverables; say the PDF was not made.")
    html_path = Path(html_path).resolve()
    if not html_path.is_file():
        raise PdfError("the preview page this PDF would print does not exist")

    with tempfile.TemporaryDirectory(prefix="pantler-office-pdf-") as scratch:
        scratch_path = Path(scratch)
        environment = dict(os.environ)
        # Chrome writes crash reports and its profile relative to HOME; a scratch HOME keeps the
        # operator's own directory out of it, and a short one keeps the socket path legal.
        environment["HOME"] = str(scratch_path)
        environment["TMPDIR"] = str(scratch_path)
        command = [
            str(executable),
            "--headless",
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--disable-crash-reporter",
            "--disable-breakpad",
            "--hide-scrollbars",
            f"--user-data-dir={scratch_path / 'profile'}",
            "--no-pdf-header-footer",
            "--virtual-time-budget=4000",
            f"--print-to-pdf={Path(out_path)}",
            html_path.as_uri(),
        ]
        try:
            done = subprocess.run(command, capture_output=True, timeout=timeout,
                                  env=environment, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired as exc:
            raise PdfError(f"the browser did not finish printing within {timeout:.0f}s") from exc
        except OSError as exc:
            raise PdfError(f"the browser could not start: {exc}") from exc
    target = Path(out_path)
    if not target.is_file() or target.stat().st_size == 0:
        detail = [line for line in (done.stderr or b"").decode("utf-8", "replace").splitlines()
                  if line.strip()]
        tail = " / ".join(detail[-3:]) or "no output"
        raise PdfError(f"the browser ran but wrote no PDF: {tail}")
    if not target.read_bytes()[:5] == b"%PDF-":
        raise PdfError("the browser wrote a file that is not a PDF")
    return {"path": str(target), "bytes": target.stat().st_size, "browser": executable.name}
