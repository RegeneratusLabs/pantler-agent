"""A screenshot of a page, with a browser that is already on the machine.

The `website` skill used to need Playwright in a Python environment the operator had to know about,
and the renderer said so in its own docstring. This module removes that: it finds Chrome, Edge or
Chromium, runs it headless once, and writes a PNG. No package, no driver, no second interpreter.

It is a preview, not a document. Chrome's `--screenshot` captures the viewport, so the caller gets
the first screen at a given width and is told that is what it is — the full-page claim is not made.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path


class ScreenshotError(RuntimeError):
    """No browser, or a browser that refused to draw. The caller reports it, never hides it."""


_NAMES = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome",
          "msedge", "microsoft-edge")


def find_chromium(env: dict[str, str] | None = None, home: Path | None = None) -> Path | None:
    """The best executable for a screenshot: explicit choice, headless shell, then a browser."""
    environment = env if env is not None else os.environ
    explicit = (environment.get("PANTLER_CHROMIUM") or "").strip()
    if explicit and Path(explicit).is_file():
        return Path(explicit)

    root = Path(home or Path.home())
    # The headless shell is purpose-built for this: it draws a page and exits, with no windowing
    # and no full-browser startup. It is also the binary that behaves under a restricted userns.
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


def capture(html_path: Path, out_path: Path, width: int, height: int, timeout: float = 45.0,
            browser: Path | None = None) -> dict:
    """Photograph the first screen of a local page. Returns `{path, width, height, browser}`."""
    executable = browser or find_chromium()
    if executable is None:
        raise ScreenshotError(
            "no Chrome, Edge or Chromium was found, so no preview was drawn. The HTML is the "
            "deliverable; say the preview was not made."
        )
    html_path = Path(html_path).resolve()
    if not html_path.is_file():
        raise ScreenshotError(f"{html_path} does not exist")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="pantler-shot-") as scratch:
        scratch_path = Path(scratch)
        profile = scratch_path / "profile"
        environment = dict(os.environ)
        # Chrome writes crash reports and its profile relative to HOME; a scratch HOME keeps it out
        # of the operator's real one, which is also what made the first headless run fail here.
        environment["HOME"] = str(scratch_path)
        environment["TMPDIR"] = str(scratch_path)
        # `--no-sandbox` is deliberate. The page is a local file this plugin generated: no
        # script, no network. Chrome's own sandbox needs unprivileged user namespaces, which
        # Ubuntu 23.10+ and most container images restrict — without this flag the browser aborts
        # with "No usable sandbox" and the operator gets no preview at all.
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
            "--force-device-scale-factor=1",
            f"--user-data-dir={profile}",
            f"--window-size={width},{height}",
            "--virtual-time-budget=4000",
            f"--screenshot={out_path}",
            html_path.as_uri(),
        ]
        try:
            done = subprocess.run(command, capture_output=True, timeout=timeout,
                                  env=environment, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired as exc:
            raise ScreenshotError(
                f"the browser did not finish within {timeout:.0f}s; no preview was drawn"
            ) from exc
        except OSError as exc:
            raise ScreenshotError(f"the browser could not start: {exc}") from exc
    if not out_path.is_file() or out_path.stat().st_size == 0:
        detail = [line for line in (done.stderr or b"").decode("utf-8", "replace").splitlines()
                  if line.strip()]
        tail = " / ".join(detail[-3:]) or "no output"
        raise ScreenshotError(f"the browser ran but wrote no image: {tail}")
    return {"path": str(out_path), "width": width, "height": height,
            "browser": executable.name, "viewport_only": True}
