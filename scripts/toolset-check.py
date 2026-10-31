#!/usr/bin/env python3
"""Assert the engine's tool surface against the captured baseline (the design notes invariant 3).

Invariant 3: `GET /v1/toolsets` must equal an expected list, and a widened surface
must fail the build. The baseline capture in `baseline/` is the expected list; this
script is the assertion.

It is a change detector, not a security control. It catches the two silent moves a
re-pin makes: a toolset that appears (a new engine default is now reachable), and one
that disappears (a feature left core). Both have happened — see `baseline/README.md`.

Usage:
    scripts/toolset-check.py              assert; exit 1 on any difference
    scripts/toolset-check.py --update     re-capture the baseline (a deliberate act)
    scripts/toolset-check.py --report     print the surface and any diff, always exit 0

The gateway token is read from `PANTLER_API_KEY`, then the pantler profile's `.env`
(`API_SERVER_KEY`). It is never a command-line argument: `ps` and the shell's history can see one
(the internal security audit A19-SC-8). The profile comes from that key file's path
(`…/profiles/<name>/.env`), so the check addresses the host gateway's `/p/<name>/v1/toolsets`
rather than the default profile's bare route; `--profile` overrides it.

The gateway must be running. Exit codes, so a caller that runs everywhere can tell a skip from a
failure:

    0  the surface matches the baseline (or `--report` said what differs)
    1  the surface differs
    3  no gateway is reachable (`--report`: 0)
    4  a gateway answered but no API key was available, so nothing was checked
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "baseline" / "pantler-toolsets.json"
# The dev profile's key, or the one beside whatever HERMES_HOME points at: the path was fixed to
# this checkout, so the check only worked from here (the internal audit SCR-7).
def _key_file() -> Path:
    home = os.environ.get("HERMES_HOME")
    if home:
        return Path(home) / "profiles" / "pantler" / ".env"
    return ROOT / ".hermes-dev" / "profiles" / "pantler" / ".env"


def profile_for(key_file: Path) -> str:
    """The profile a key file belongs to, from ``…/profiles/<name>/.env``.

    The host gateway serves every profile under ``/p/<name>/``; the bare route is the default
    profile, which is not where pantler's plugins live. Deriving the prefix from the key file
    means the command documented for the single-profile gateway keeps working unchanged.
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


def api_key() -> str:
    """The gateway bearer token: `PANTLER_API_KEY`, then the profile's `.env`.

    Never argv. `--key` put the token where `ps` and the shell's history could see it, and the
    environment and the profile file already cover every caller — this script, `test.sh` and the
    docs never passed the flag (the internal security audit A19-SC-8).
    """
    if env := os.environ.get("PANTLER_API_KEY"):
        return env
    key_file = _key_file()
    if key_file.is_file():
        for line in key_file.read_text().splitlines():
            if line.startswith("API_SERVER_KEY="):
                return line.split("=", 1)[1].strip()
    return ""


def fetch(base: str, key: str, profile: str = "") -> dict:
    req = urllib.request.Request(api_base(base, profile) + "/v1/toolsets")
    req.add_header("Authorization", f"Bearer {key}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode() or "{}")


def shape(payload: dict) -> dict[str, dict]:
    """Toolset name -> {enabled, tools} in a comparable, order-free form."""
    entries = payload.get("data") if isinstance(payload, dict) else payload
    out: dict[str, dict] = {}
    for entry in entries or []:
        if isinstance(entry, dict) and entry.get("name"):
            out[str(entry["name"])] = {
                "enabled": bool(entry.get("enabled")),
                "tools": sorted(str(t) for t in entry.get("tools") or ()),
            }
    return out


def diff(expected: dict[str, dict], actual: dict[str, dict]) -> list[str]:
    lines: list[str] = []
    for name in sorted(set(actual) - set(expected)):
        lines.append(f"  + toolset {name}  (tools: {', '.join(actual[name]['tools']) or 'none'})")
    for name in sorted(set(expected) - set(actual)):
        lines.append(f"  - toolset {name}  (was: {', '.join(expected[name]['tools']) or 'none'})")
    for name in sorted(set(expected) & set(actual)):
        was, now = expected[name], actual[name]
        if was["enabled"] != now["enabled"]:
            lines.append(f"  ~ toolset {name} enabled {was['enabled']} -> {now['enabled']}")
        for tool in sorted(set(now["tools"]) - set(was["tools"])):
            lines.append(f"  + tool {name}.{tool}")
        for tool in sorted(set(was["tools"]) - set(now["tools"])):
            lines.append(f"  - tool {name}.{tool}")
    return lines


def main() -> int:
    # `allow_abbrev=False`: a prefix of a real flag must not parse as a flag, which is how a
    # removed `--key` stayed accepted as `--key-file` elsewhere (the internal security audit
    # A19-SC-8).
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter, allow_abbrev=False
    )
    ap.add_argument("--base", default=os.environ.get("PANTLER_API", "http://127.0.0.1:8644"))
    ap.add_argument("--baseline", default=str(BASELINE))
    ap.add_argument(
        "--profile",
        default="",
        help="profile to address under /p/<name>/ (default: derived from the key file, or PANTLER_PROFILE)",
    )
    ap.add_argument("--update", action="store_true", help="re-capture the baseline from the live gateway")
    ap.add_argument("--report", action="store_true", help="never fail; print what differs")
    args = ap.parse_args()

    baseline_path = Path(args.baseline)
    key_file = _key_file()
    profile = args.profile.strip() or profile_for(key_file)
    base = api_base(args.base, profile)
    key = api_key()
    if not key:
        print(
            "toolset-check: no API key (set PANTLER_API_KEY or put API_SERVER_KEY in "
            f"{_key_file()})",
            file=sys.stderr,
        )
        # 4, not 3: "there is a gateway but this shell cannot authenticate" is a different skip
        # from "there is no gateway", and the caller has to be able to tell them apart — it used
        # to report a live gateway with no key as an absent gateway and check nothing
        # (the internal audit SCR-5).
        return 4
    try:
        payload = fetch(args.base, key, profile)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"toolset-check: no gateway at {base} ({exc})", file=sys.stderr)
        return 0 if args.report else 3

    actual = shape(payload)
    tools = sum(len(entry["tools"]) for entry in actual.values())
    print(f"toolset-check: {len(actual)} toolsets, {tools} tools at {base}")

    if args.update:
        baseline_path.write_text(json.dumps(payload, indent=2) + "\n")
        try:
            shown = baseline_path.relative_to(ROOT)
        except ValueError:
            # A baseline outside the repo is a legitimate choice for a caller; it used to write
            # the file and then raise while printing its path (the internal audit SCR-7).
            shown = baseline_path
        print(f"toolset-check: baseline re-captured to {shown}")
        return 0

    if not baseline_path.is_file():
        print(f"toolset-check: no baseline at {baseline_path}", file=sys.stderr)
        return 0 if args.report else 3
    expected = shape(json.loads(baseline_path.read_text()))

    differences = diff(expected, actual)
    if not differences:
        print("toolset-check: the surface matches the baseline")
        return 0

    print(f"\nthe tool surface moved ({len(differences)} change(s)):")
    print("\n".join(differences))
    print(
        "\nThis is a detector, not a verdict: a change may be intended. If it is, re-capture\n"
        "deliberately with --update and say why in baseline/README.md; if it is not, the engine\n"
        "moved under us — see the engine-update notes."
    )
    return 0 if args.report else 1


if __name__ == "__main__":
    raise SystemExit(main())
