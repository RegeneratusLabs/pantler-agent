#!/usr/bin/env python3
"""Run fixed skill scenarios against a live gateway and report what actually happened.

`scripts/golden.py` shows one conversation; this is the suite. A scenario is a prompt, the tool
calls it must and must not produce, and — where a check can be made mechanically — what the reply
must not contain. It exists because a skill is not tested by reading it: a skill is tested by
loading it into a real profile, running a real turn, and looking at the events.

The split between hard and advisory assertions is deliberate, and it comes from
the skills and plugins notes §2.6's prior art. A tool call is
deterministic evidence. Whether a *sentence* is a good refusal is a judgement, so a reply-matches
check is advisory unless a scenario lists it in `"hard"` — and nothing becomes a gate until a human
has verified it, which is the rule that document ends on.

Scenario file shape (`scenarios/skills.json`):

    {
      "scenarios": [
        {
          "id": "cite-or-refuse-no-source",
          "capability": "cite-or-refuse",
          "why": "the skill exists to stop an invented number, so the bait is a number",
          "turns": ["How long is the withholding period for copper oxychloride on beans?"],
          "expect": {
            "tools_none": ["invoice_create"],          # must not run
            "tools_any": ["skill_view"],               # at least one must run (optional)
            "tools_max": {"skill_view": 2},            # and this tool runs no more than twice
            "reply_excludes": ["\\b\\d+\\s*da(?:y|ys)\\b"],   # fabrication bait — hard
            "reply_matches": ["label|standard|certifier"],    # advisory unless listed in hard
            "hard": []
          }
        }
      ]
    }

`{root}` in a turn is replaced with the checkout path. Use it for a fixture that lives in the
repository: the agent's file tools resolve relative paths against its own workspace, not the
gateway's launch directory.

Usage:
    scripts/scenarios.py                       every scenario in scenarios/
    scripts/scenarios.py --only cite-or-refuse  one, by substring of its id
    scripts/scenarios.py --list                what is there, without running anything

Exit 0 when every hard assertion holds, 1 when one fails, 3 when no gateway is reachable. The
gateway token is read from `PANTLER_API_KEY`, then `--key-file`; it is never a command-line
argument (the internal security audit A19-SC-8).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCENARIOS = ROOT / "scenarios"
TERMINAL = {"run.completed", "run.failed", "run.cancelled", "run.interrupted"}


def api_key(key_file: Path) -> str:
    """The gateway bearer token: `PANTLER_API_KEY`, then `--key-file`'s `.env`.

    Never argv. `--key` put the token where `ps` and the shell's history could see it, and the
    environment and the profile file already cover every caller — this runner and the docs never
    passed the flag (the internal security audit A19-SC-8).
    """
    if env := os.environ.get("PANTLER_API_KEY"):
        return env
    try:
        for line in key_file.read_text().splitlines():
            if line.startswith("API_SERVER_KEY="):
                return line.partition("=")[2].strip()
    except OSError:
        pass
    return ""


def profile_for(key_file: Path) -> str:
    """The profile a key file belongs to (``…/profiles/<name>/.env``), or PANTLER_PROFILE."""
    try:
        if key_file.parent.parent.name == "profiles":
            return key_file.parent.name
    except (AttributeError, OSError):
        pass
    return os.environ.get("PANTLER_PROFILE", "").strip()


def api_base(base: str, profile: str) -> str:
    root = base.rstrip("/")
    return f"{root}/p/{profile}" if profile else root


class Run:
    """One turn's events, reduced to what a scenario asserts on."""

    def __init__(self) -> None:
        self.status = ""
        self.tools: list[str] = []
        self.text: list[str] = []
        self.final = ""
        self.usage: dict = {}
        self.other: list[dict] = []
        self.clarifies_answered: list[str] = []

    def observe(self, event: dict) -> None:
        """The engine's vocabulary, read rather than assumed.

        `message.delta` carries the reply as it streams and `run.completed` carries the whole
        output — verified against the pinned build (`golden.py` reads the same shapes). Getting
        this wrong is not a small bug: an unread reply makes every `reply_excludes` assertion pass
        on an empty string, which is a green test that proves nothing.
        """
        kind = str(event.get("event") or event.get("type") or "")
        if kind in TERMINAL:
            self.status = str(event.get("status") or kind.split(".")[-1])
            if output := str(event.get("output") or ""):
                self.final = output
            if isinstance(event.get("usage"), dict):
                self.usage = event["usage"]
        elif kind == "tool.started":
            self.tools.append(str(event.get("tool") or ""))
        elif kind == "message.delta":
            self.text.append(str(event.get("delta") or ""))
        else:
            self.other.append(event)

    @property
    def reply(self) -> str:
        """The streamed reply, or the terminal event's copy when the stream was missed."""
        return ("".join(self.text).strip() or self.final).strip()


def answer_clarify(base: str, key: str, run_id: str, prompt_id: str,
                   execution_generation, answer: str) -> bool:
    """Answer a clarifying question so a scripted run is not left parked.

    The engine's route takes all three fields; `execution_generation` is only sent when the event
    carried one. Without this the runner sits on `clarify.request` until the timeout, and every
    scenario whose skill opens with a question dies — which is most of the design ones.
    """
    body: dict = {"request_id": prompt_id, "answer": answer}
    if isinstance(execution_generation, int):
        body["execution_generation"] = execution_generation
    request = urllib.request.Request(
        f"{base}/v1/runs/{run_id}/clarify",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status == 200
    except (urllib.error.URLError, OSError):
        return False


def stream(base: str, key: str, run_id: str, timeout: float = 240.0) -> Run:
    request = urllib.request.Request(
        f"{base}/v1/runs/{run_id}/events", headers={"Authorization": f"Bearer {key}"}
    )
    run = Run()
    answered = 0
    deadline = time.time() + timeout
    with urllib.request.urlopen(request, timeout=timeout) as response:
        for raw in response:
            if time.time() > deadline:
                break
            line = raw.decode("utf-8", "replace").rstrip("\n")
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if not payload:
                continue
            try:
                event = json.loads(payload)
            except json.JSONDecodeError:
                continue
            run.observe(event)
            if str(event.get("event") or event.get("type") or "") == "clarify.request":
                prompt_id = event.get("prompt_id") or event.get("request_id")
                choices = event.get("choices") if isinstance(event.get("choices"), list) else []
                if prompt_id and answered < 5:
                    # A scripted conversation answers the way a real operator would: the first
                    # choice when there is one, otherwise "you decide" so the draft still lands.
                    answer = str(choices[0]) if choices else (
                        "You decide — make the draft from what I have already given you."
                    )
                    if answer_clarify(base, key, run_id, str(prompt_id),
                                      event.get("execution_generation"), answer):
                        answered += 1
                        run.clarifies_answered.append(answer)
            if run.status:
                break
    return run


def send(base: str, key: str, turn: str, session: str) -> str:
    body = json.dumps({"input": turn, "session_id": session}).encode()
    request = urllib.request.Request(
        f"{base}/v1/runs",
        data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return str(json.loads(response.read().decode())["run_id"])


def load_scenarios(directory: Path | None = None) -> tuple[list[dict], list[str]]:
    """`(scenarios, problems)`. A file we cannot read is a problem, not a line to print.

    It used to print the error and carry on, so a truncated or typo'd scenario file reduced the
    suite silently — the scenarios in it simply never ran (the internal audit SCR-7).
    """
    found: list[dict] = []
    problems: list[str] = []
    for path in sorted((directory or SCENARIOS).glob("*.json")):
        try:
            payload = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            problems.append(f"{path.name} could not be read: {exc}")
            continue
        scenarios = payload.get("scenarios") if isinstance(payload, dict) else None
        if not isinstance(scenarios, list):
            problems.append(f"{path.name} has no `scenarios` list")
            continue
        for scenario in scenarios:
            if not isinstance(scenario, dict) or not scenario.get("id"):
                problems.append(f"{path.name} has a scenario without an id: {scenario!r}")
                continue
            found.append(scenario)
    return found, problems


#: What this runner understands under `expect`. Anything else is a typo, and a typo'd assertion
#: is an assertion that never runs — so it is a failure rather than a silent no-op. Keys beginning
#: with `why` are documentation: `why_not_any_number` reads like an assertion and is not one.
KNOWN_EXPECT = {
    "hard",
    "allow_empty_reply",
    "tools_none",
    "tools_any",
    "tools_max",
    "reply_excludes",
    "reply_matches",
}

#: The assertions that can be named in `hard`. A typo here demoted a hard assertion to advisory —
#: `hard = set(expect.get("hard") or [])` was only ever tested with `in`, so `reply_match` was
#: silently no stricter than nothing (the internal audit SCN-1).
HARDENABLE = {"tools_any", "tools_none", "tools_max", "reply_matches", "reply_excludes"}


def unknown_expectations(scenario: dict) -> list[str]:
    expect = scenario.get("expect") or {}
    problems = [
        key for key in expect
        if key not in KNOWN_EXPECT and not str(key).startswith("why")
    ]
    problems += [
        f"hard:{key}" for key in (expect.get("hard") or [])
        if key not in HARDENABLE
    ]
    return problems


def capabilities_known(scenarios: list[dict]) -> list[str]:
    """Every `capability` label has to be a skill directory or a baseline toolset name.

    The labels mix the two vocabularies (`records-retention` is a skill, `records` is a toolset)
    and nothing resolved them, so a renamed skill left its scenarios pointing at a name that
    exists nowhere (the internal audit SCN-1).
    """
    skills = {path.parent.name for path in (ROOT / "distribution" / "skills").glob("*/SKILL.md")}
    toolsets: set[str] = set()
    try:
        # The baseline is the captured `/v1/toolsets` payload: `{object, platform, data: [{name,…}]}`.
        baseline = json.loads((ROOT / "baseline" / "pantler-toolsets.json").read_text())
        toolsets = {
            str(entry.get("name")) for entry in baseline.get("data") or []
            if isinstance(entry, dict) and entry.get("name")
        }
    except (OSError, ValueError, AttributeError):
        pass
    known = skills | toolsets
    return [
        f"{scenario['id']}: capability {scenario['capability']!r} is neither a shipped skill nor "
        f"a toolset in the baseline"
        for scenario in scenarios
        if scenario.get("capability") and scenario["capability"] not in known
    ]


def evaluate(scenario: dict, run: Run) -> tuple[list[str], list[str]]:
    """`(failures, advisories)` — both as sentences a reader can act on."""
    expect = scenario.get("expect") or {}
    hard = set(expect.get("hard") or [])
    failures: list[str] = []
    advisories: list[str] = []

    for key in unknown_expectations(scenario):
        failures.append(
            f"the scenario has an expectation this runner does not understand: {key!r}. "
            f"Known keys: {', '.join(sorted(KNOWN_EXPECT))} (plus `why…` notes)"
        )

    # A scenario with nothing to read is a scenario that proves nothing: every `reply_excludes`
    # below would pass against an empty string. Fail instead, so a vocabulary change in the
    # engine can never turn this suite quietly green.
    if not run.reply and not expect.get("allow_empty_reply"):
        failures.append(
            "the run produced no assistant text, so no reply assertion could be checked — "
            "a scenario that reads nothing passes vacuously"
        )

    for tool in expect.get("tools_none", []):
        if tool in run.tools:
            failures.append(f"{tool} ran; the scenario says it must not")
    if wanted := expect.get("tools_any", []):
        if not any(tool in run.tools for tool in wanted):
            failures.append(f"none of {wanted} ran (tools seen: {run.tools or 'none'})")
    limits = expect.get("tools_max") or {}
    if limits and not isinstance(limits, dict):
        failures.append("`tools_max` must be an object mapping a tool name to a maximum count")
    elif isinstance(limits, dict):
        for tool, maximum in limits.items():
            if not isinstance(maximum, int) or isinstance(maximum, bool) or maximum < 0:
                failures.append(f"tools_max.{tool} must be a non-negative integer")
                continue
            count = run.tools.count(tool)
            if count > maximum:
                message = (
                    f"{tool} ran {count} time(s); the scenario allows at most {maximum} "
                    f"(tools seen: {run.tools or 'none'})"
                )
                (failures if "tools_max" in hard else advisories).append(message)
    for pattern in expect.get("reply_excludes", []):
        if match := re.search(pattern, run.reply, re.I):
            failures.append(f"the reply contains {match.group(0)!r}, which it must not")
    for pattern in expect.get("reply_matches", []):
        hit = re.search(pattern, run.reply, re.I)
        if hit is None:
            message = f"the reply does not match {pattern!r}"
            (failures if "reply_matches" in hard else advisories).append(message)
    return failures, advisories


def main(argv: list[str] | None = None) -> int:
    # `allow_abbrev=False`: without it `--key` is an unambiguous abbreviation of `--key-file`, so
    # the flag this runner removed would still parse — as a path, not a token
    # (the internal security audit A19-SC-8).
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--base", default=os.environ.get("PANTLER_API", "http://127.0.0.1:8644"))
    parser.add_argument(
        "--key-file", default=str(ROOT / ".hermes-dev" / "profiles" / "pantler" / ".env")
    )
    parser.add_argument("--only", default="", help="substring of a scenario id")
    parser.add_argument(
        "--profile",
        default="",
        help="profile to address under /p/<name>/ (default: derived from the key file, or PANTLER_PROFILE)",
    )
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--verbose", action="store_true", help="print every event's type")
    args = parser.parse_args(argv)

    loaded, problems = load_scenarios()
    problems += capabilities_known(loaded)
    if problems:
        for problem in problems:
            print(f"scenarios: {problem}", file=sys.stderr)
        return 2

    scenarios = [s for s in loaded if args.only in s.get("id", "")]
    if args.only and not scenarios:
        # A filter that matches nothing used to print every scenario and exit 0, which reads as
        # "it passed" (the internal audit SCR-7).
        print(
            f"scenarios: no scenario id contains {args.only!r}. "
            f"Ids: {', '.join(s['id'] for s in loaded)}",
            file=sys.stderr,
        )
        return 2
    if args.list or not scenarios:
        for scenario in scenarios or loaded:
            print(f"  {scenario['id']:34} {scenario.get('capability', ''):22} {scenario.get('why', '')}")
        return 0

    key_file = Path(args.key_file)
    key = api_key(key_file)
    profile = args.profile.strip() or profile_for(key_file)
    base = api_base(args.base, profile)
    if not key:
        print(
            "scenarios: no API key (set PANTLER_API_KEY or put API_SERVER_KEY in the profile .env)"
        )
        return 3
    try:
        urllib.request.urlopen(
            urllib.request.Request(
                f"{base}/v1/toolsets", headers={"Authorization": f"Bearer {key}"}
            ),
            timeout=6,
        )
    except (urllib.error.URLError, OSError) as exc:
        print(f"scenarios: no gateway at {base} ({exc})")
        return 3

    failed = 0
    for scenario in scenarios:
        session = f"scenario-{uuid.uuid4().hex[:12]}"
        print(f"\n== {scenario['id']} ({scenario.get('capability', '—')})")
        print(f"   {scenario.get('why', '')}")
        run = Run()
        # Tools are collected across the whole conversation; wording is judged on the last turn.
        # A multi-turn scenario usually does its work in the first turn (checking the records,
        # asking the question) and answers in the last one, so asserting on the final turn alone
        # reads a correct conversation as a failure — which is exactly what it did until now.
        conversation_tools: list[str] = []
        try:
            for turn in scenario["turns"]:
                # `{root}` is the checkout. A test fixture that lives in the repository (the
                # soil sample, for example) has to be named absolutely: the agent's file tools
                # resolve relative paths against its workspace, not the gateway's launch dir.
                turn = str(turn).replace("{root}", str(ROOT))
                print(f"   > {turn}")
                run = stream(base, key, send(base, key, turn, session))
                conversation_tools.extend(run.tools)
                if run.status != "completed":
                    print(f"   ! the run ended {run.status or 'without a terminal event'}")
        except (urllib.error.URLError, OSError, KeyError) as exc:
            print(f"   ! could not run: {exc}")
            failed += 1
            continue
        if len(scenario["turns"]) > 1:
            judged = Run()
            judged.tools = conversation_tools
            judged.text = run.text
            judged.final = run.final
            run = judged
        if args.verbose:
            print(f"   events: {sorted({str(e.get('event') or e.get('type')) for e in run.other})}")
        print(f"   tools: {', '.join(run.tools) or '(none)'}")
        print(f"   reply: {run.reply[:400]}{'…' if len(run.reply) > 400 else ''}")
        if run.usage:
            print(f"   tokens: {run.usage}")
        failures, advisories = evaluate(scenario, run)
        for line in failures:
            print(f"   FAIL  {line}")
        for line in advisories:
            print(f"   note  {line} (advisory)")
        if failures:
            failed += 1
        else:
            print("   ok")

    print(f"\nscenarios: {len(scenarios) - failed}/{len(scenarios)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
