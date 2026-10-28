#!/usr/bin/env python3
"""Drive a conversation against a pantler gateway and report every event.

This is the seed of the golden-conversation suite (the design notes §4): a fixed scenario, the
events the engine actually emitted, and a pass/fail on what the invoice tools did.

Usage:
    scripts/golden.py --turns "invoice Bellview CSA for 12 kilos of beans"
    scripts/golden.py --turns "invoice Bellview for 12 kilos of beans"

The gateway token is read from `PANTLER_API_KEY`, then `--key-file` (the dev profile's `.env`).
It is never a command-line argument: `ps` and the shell's history can see one
(the internal security audit A19-SC-8).

Wire contract (re-verified against Hermes 297552a9d646119871391d202509822cd86330df,
  v0.22.1; first verified at 13dc3a73895aff1f823c1566bc1dd9b52fe35b65, v0.21.4):
  POST /v1/runs                     -> 202 {"run_id","status","replayed"}
  GET  /v1/runs/{id}/events         -> SSE; frames are `id: <seq>` + `data: <json>`;
                                       the type is the JSON "event" key, NOT an SSE
                                       `event:` line.

There is no approval step: the plugin registers no `pre_tool_call` hook and nothing it
exposes is outbound. If a run ever does park on an approval, that is a change worth
noticing rather than something this script quietly answers.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TERMINAL = {"run.completed", "run.failed", "run.cancelled", "run.interrupted"}


# ------------------------------------------------------------------ transport


def api_key(key_file: Path) -> str:
    """The gateway bearer token: `PANTLER_API_KEY`, then the profile's `.env`.

    Never argv. `--key` put the token where `ps` and the shell's history could see it, and the
    environment and the profile file already cover every caller — `test.sh` and the docs never
    passed the flag (the internal security audit A19-SC-8).
    """
    if env := os.environ.get("PANTLER_API_KEY"):
        return env
    try:
        for line in key_file.read_text().splitlines():
            if line.startswith("API_SERVER_KEY="):
                return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return ""


def profile_for(key_file: Path) -> str:
    """The profile a key file belongs to (``…/profiles/<name>/.env``), or PANTLER_PROFILE.

    A host gateway serves the profiles under ``/p/<name>/``; the bare route is the default
    profile, which has no pantler plugins and no model. Deriving the prefix from the same key file
    the token comes from keeps the documented command working on both topologies.
    """
    try:
        if key_file.parent.parent.name == "profiles":
            return key_file.parent.name
    except (AttributeError, OSError):
        pass
    return os.environ.get("PANTLER_PROFILE", "").strip()


def api_base(base: str, profile: str) -> str:
    root = base.rstrip("/")
    return f"{root}/p/{profile}" if profile else root


class Gateway:
    def __init__(self, base: str, key: str, timeout: float = 180.0):
        self.base = base.rstrip("/")
        self.key = key
        self.timeout = timeout

    def _open(self, req: urllib.request.Request):
        req.add_header("Authorization", f"Bearer {self.key}")
        return urllib.request.urlopen(req, timeout=self.timeout)

    def post(self, path: str, body: dict) -> dict:
        data = json.dumps(body).encode()
        req = urllib.request.Request(
            self.base + path, data=data, headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with self._open(req) as resp:
                return json.loads(resp.read().decode() or "{}")
        except urllib.error.HTTPError as exc:
            raise SystemExit(f"POST {path} -> HTTP {exc.code}: {exc.read().decode()[:400]}") from None

    def events(self, run_id: str):
        """Yield decoded event payloads until the run reaches a terminal state."""
        req = urllib.request.Request(self.base + f"/v1/runs/{run_id}/events")
        req.add_header("Accept", "text/event-stream")
        with self._open(req) as resp:
            for raw in resp:
                line = raw.decode("utf-8", "replace").rstrip("\n")
                if not line.startswith("data:"):
                    continue  # `: open`, `: keepalive`, `id:` lines carry no payload
                payload = line[len("data:"):].strip()
                if not payload:
                    continue
                try:
                    event = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                yield event
                if event.get("event") in TERMINAL:
                    return


# --------------------------------------------------------------------- report


class Report:
    """What happened, and what is wrong with it.

    The docstring promised "a pass/fail on what the invoice tools did" and the script printed a
    summary and returned 0 whatever happened — `failed` was printed and ignored. The judgement is
    here now, and `main` exits 1 when there is anything in `failures`
    (the internal audit SCR-6).
    """

    def __init__(self) -> None:
        self.events: list[dict] = []
        self.tools: list[str] = []
        self.output = ""
        self.status = "unknown"
        self.error = ""
        self.failures: list[str] = []

    def feed(self, event: dict) -> None:
        self.events.append(event)
        kind = event.get("event")
        if kind == "tool.started":
            self.tools.append(str(event.get("tool", "")))
        elif kind == "approval.request":
            self.failures.append(
                f"a run parked on an approval ({event.get('description')!r}); nothing this plugin "
                "registers is outbound, so the tool surface has changed"
            )
        elif kind in TERMINAL:
            self.status = str(kind).split(".", 1)[1]
            if kind == "run.completed":
                self.output = str(event.get("output", ""))
            elif event.get("error"):
                # The engine puts the reason on the terminal frame (an expired upstream key, a
                # model that refused, a tool that crashed). Without it the report said only
                # "the run ended 'failed'" and left the reader to go hunting.
                self.error = str(event["error"])

    def judge(self) -> None:
        """The assertions, run once the last turn has landed."""
        if self.status != "completed":
            reason = f": {self.error}" if self.error else ""
            self.failures.append(f"the run ended {self.status!r} rather than completing{reason}")
        if any(tool.startswith("invoice_") for tool in self.tools):
            if not self.output.strip():
                self.failures.append("an invoice tool ran and the assistant said nothing")
            elif "draft" not in self.output.casefold():
                self.failures.append(
                    "an invoice tool ran and the reply does not call it a draft — a draft that "
                    f"reads as sent is the failure this suite exists to catch: {self.output!r}"
                )

    def summary(self) -> str:
        lines = [f"status:  {self.status}", f"tools:   {', '.join(self.tools) or '(none)'}"]
        if self.error:
            lines.append(f"error:   {self.error}")
        lines.append(f"output:\n{self.output}")
        if self.failures:
            lines.append("FAILED:")
            lines.extend(f"  - {failure}" for failure in self.failures)
        else:
            lines.append("PASS: the run completed and the invoice reply read as a draft")
        return "\n".join(lines)


# ------------------------------------------------------------------- scenario


def run_turn(gw: Gateway, text: str, session: str, report: Report) -> None:
    body: dict = {"input": text}
    if session:
        body["session_id"] = session
    started = gw.post("/v1/runs", body)
    run_id = started["run_id"]
    print(f"\n=== turn: {text!r}\n    run_id={run_id}", flush=True)

    for event in gw.events(run_id):
        report.feed(event)
        kind = event.get("event")
        if kind == "message.delta":
            sys.stdout.write(event.get("delta", ""))
            sys.stdout.flush()
        elif kind == "tool.started":
            print(f"\n  [tool.started] {event.get('tool')} {event.get('preview', '')}", flush=True)
        elif kind == "tool.completed":
            print(f"  [tool.completed] {event.get('tool')} error={event.get('error')}", flush=True)
        elif kind == "approval.request":
            # Nothing in this plugin is outbound, so this should not happen. Report it
            # loudly rather than answering it: a run parking here means the tool surface
            # changed, and that is exactly what the golden suite exists to catch.
            print(
                f"\n  [approval.request] UNEXPECTED — nothing registered here is outbound: "
                f"{event.get('description')!r}",
                flush=True,
            )
        elif kind in TERMINAL:
            print(f"\n  [{kind}]", flush=True)


def main(argv: list[str] | None = None) -> int:
    # `allow_abbrev=False`: without it `--key` is an unambiguous abbreviation of `--key-file`, so
    # the flag this script removed would still parse — as a path, not a token
    # (the internal security audit A19-SC-8).
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter, allow_abbrev=False
    )
    ap.add_argument("--base", default=os.environ.get("PANTLER_API", "http://127.0.0.1:8644"))
    ap.add_argument("--key-file", default=str(ROOT / ".hermes-dev/profiles/pantler/.env"))
    ap.add_argument(
        "--profile",
        default="",
        help="profile to address under /p/<name>/ (default: derived from the key file, or PANTLER_PROFILE)",
    )
    ap.add_argument("--turns", nargs="+", help="One or more turns, sent in one session.")
    ap.add_argument("--session", default="", help="Reuse a session id; default is a fresh one.")
    args = ap.parse_args(argv)

    key_file = Path(args.key_file)
    key = api_key(key_file)
    if not key:
        raise SystemExit("no API key: set PANTLER_API_KEY, or provide --key-file")
    profile = args.profile.strip() or profile_for(key_file)

    turns = args.turns or ["Reply with exactly: seam-ok"]
    session = args.session or f"golden-{uuid.uuid4().hex[:12]}"
    gw = Gateway(api_base(args.base, profile), key)
    report = Report()

    for turn in turns:
        run_turn(gw, turn, session, report)
        time.sleep(0.5)

    report.judge()
    print("\n" + "=" * 70)
    print(report.summary())
    return 1 if report.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
