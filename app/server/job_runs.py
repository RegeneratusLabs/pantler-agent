"""A scheduled job's saved output, read from the profile that owns it.

The gateway exposes `/api/jobs` (create, list, pause, run) but **no per-run read**. With no
delivery platform configured, a job's output is written by the engine's scheduler to
``<profile>/cron/output/<job_id>/<timestamp>.md`` (`cron/jobs.py` `save_job_output` at the pin)
and that file is the only record of what the job produced. The dashboard server has a richer
route for it (`/api/cron/jobs/{id}/runs`), and the front-end contract is explicit that the
dashboard API is not the seam (the front-end design §3), so the BFF reads the profile's own
directory instead.

This module is the whole of that read:

    the ids          the engine's own shapes — twelve lowercase hex, and its timestamp stem
    the jail         the job's directory under the profile's `cron/output`, resolved
    the cap          a run is text and is shown, not transferred; 256 KB is already long
    the preview      one line for the picker, read from the head rather than the whole file

It is deliberately read-only and deliberately narrow: no path is accepted from the caller, the
filename is built from a validated stem, and nothing outside `cron/output/<job_id>/` is ever
opened. A missing directory is an empty answer, not an error: a job that has never run has no
output and that is normal.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

#: The engine's job ids: `uuid.uuid4().hex[:12]` (`cron/jobs.py` `create_job`).
JOB_ID_RE = re.compile(r"[a-f0-9]{12}")

#: `save_job_output`'s stem: `%Y-%m-%d_%H-%M-%S` (`cron/jobs.py`).
RUN_ID_RE = re.compile(r"\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}")

#: `save_job_output`'s suffix.
RUN_SUFFIX = ".md"

#: What the dialog will render in one go. A briefing is pages, not megabytes.
MAX_RUN_BYTES = 256 * 1024

#: How many runs the picker is handed. The engine prunes its own directory; this is the view's
#: bound, so a profile with a long history does not build a thousand-row dialog.
MAX_RUNS = 50

#: One line for the picker.
PREVIEW_CHARS = 240

#: Enough of a file to build a preview without reading a long run.
PREVIEW_BYTES = 4096


def list_runs(profile_dir: Path, job_id: str) -> list[dict[str, Any]]:
    """The runs kept for one job, newest first. Missing directory → no runs."""
    directory = _output_dir(profile_dir, job_id)
    if not directory.is_dir():
        return []

    rows: list[tuple[float, dict[str, Any]]] = []
    try:
        entries = list(directory.iterdir())
    except OSError:
        # The directory can be pruned between the check and the scan; a job with no runs is a
        # normal answer, not a 500.
        return []
    for path in entries:
        match = RUN_ID_RE.fullmatch(path.stem) if path.suffix == RUN_SUFFIX else None
        if match is None:
            continue
        try:
            # A run is read, so the path is resolved before it is touched: a symlink planted
            # in the profile's own directory must not turn this into a reader for another file.
            resolved = path.resolve()
            if not resolved.is_relative_to(directory) or not resolved.is_file():
                continue
            stat = resolved.stat()
        except OSError:
            continue
        rows.append(
            (
                stat.st_mtime,
                {
                    "id": match.group(0),
                    "at": _iso(stat.st_mtime),
                    "size": stat.st_size,
                    "preview": _preview(resolved),
                },
            )
        )

    rows.sort(key=lambda row: row[0], reverse=True)
    return [row for _, row in rows[:MAX_RUNS]]


def read_run(profile_dir: Path, job_id: str, run_id: str) -> dict[str, Any]:
    """One run's text. Raises `FileNotFoundError` when the engine no longer keeps it."""
    directory = _output_dir(profile_dir, job_id)
    path = _run_path(directory, run_id)
    if not path.is_file():
        raise FileNotFoundError(run_id)

    try:
        stat = path.stat()
        # One byte over the cap is enough to know it was cut, and never loads the rest.
        with path.open("rb") as handle:
            data = handle.read(MAX_RUN_BYTES + 1)
    except OSError as exc:  # unreadable is the same answer as gone, for a preview
        raise FileNotFoundError(run_id) from exc

    truncated = len(data) > MAX_RUN_BYTES
    content = data[:MAX_RUN_BYTES].decode("utf-8", errors="replace")
    return {
        "id": run_id,
        "at": _iso(stat.st_mtime),
        "size": stat.st_size,
        "content": content,
        "truncated": truncated,
    }


def _output_dir(profile_dir: Path, job_id: str) -> Path:
    """`<profile>/cron/output/<job_id>`, resolved and contained."""
    if not JOB_ID_RE.fullmatch(str(job_id or "")):
        raise ValueError(f"invalid cron job id: {job_id!r}")
    root = (Path(profile_dir) / "cron" / "output").resolve()
    directory = (root / job_id).resolve()
    if directory != root and not directory.is_relative_to(root):
        raise ValueError(f"cron job id escapes the output directory: {job_id!r}")
    return directory


def _run_path(directory: Path, run_id: str) -> Path:
    """`<directory>/<run_id>.md`, resolved and contained."""
    if not RUN_ID_RE.fullmatch(str(run_id or "")):
        raise ValueError(f"invalid cron run id: {run_id!r}")
    path = (directory / f"{run_id}{RUN_SUFFIX}").resolve()
    if path != directory and not path.is_relative_to(directory):
        raise ValueError(f"cron run id escapes the output directory: {run_id!r}")
    return path


def _iso(timestamp: float) -> str:
    """The file's mtime as an ISO instant — the one fact about a run that is zone-free."""
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def _preview(path: Path) -> str:
    """The first line or two of a run, whitespace collapsed, from the head of the file."""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            head = handle.read(PREVIEW_BYTES)
    except OSError:
        return ""
    text = " ".join(head.split())
    if len(text) > PREVIEW_CHARS:
        return text[: PREVIEW_CHARS - 1].rstrip() + "…"
    return text
