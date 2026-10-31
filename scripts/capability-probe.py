#!/usr/bin/env python3
"""Install the distribution into a throwaway profile and verify the capability path end to end.

This is the harness for the skill build-out. Authoring a skill is the cheap part; what has to be
true is that it *installs*, that the registry serves it, that its switch works, and that a fresh
profile gets it — and none of that is visible from a unit test that reads files.

It installs into the *existing* engine home (`.hermes-dev` by default, `PANTLER_HERMES_HOME` to
override) under a throwaway profile name, because a brand-new engine home has no dependency
environment and the installer stops with `run hermes pm repair` — preparing one is minutes of work
that has nothing to do with the capability being tested. The profile is created and removed by this
script; nothing else in the home is touched.

What it does, in order:

1. creates a temporary profile root and runs the real installer over `distribution/`
2. starts the BFF against that profile on a free port
3. asserts the registry answers for it: every shipped skill is a row, with a description inside the
   engine's 60-character budget, `provenance: shipped`, and `toggleable: true`
4. flips the first skill off through `PUT /api/capabilities/{id}` and asserts the registry and
   `config.yaml` both say so, then flips it back
5. tears the profile down unless `--keep` was passed

Exit 3 means the harness could not run (no `hermes` on PATH): the caller decides whether to skip.
A failure exits 1 with the sentence that says what was wrong.

Usage:
    scripts/capability-probe.py            run, tear down, exit 0 or 1
    scripts/capability-probe.py --keep     leave the profile and the BFF running to poke at
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DISTRIBUTION = ROOT / "distribution"
PROMPT_DESC_LIMIT = 60


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def python_for_bff() -> str:
    """The interpreter the gateway uses, found wherever this machine keeps its engine home."""
    override = os.environ.get("PANTLER_PYTHON", "")
    if override and Path(override).exists():
        return override
    for home in (
        Path(os.environ.get("PANTLER_HERMES_HOME") or ""),
        Path(os.environ.get("HERMES_HOME") or ""),
        Path.home() / ".hermes",
    ):
        if not home or not home.is_dir():
            continue
        bundled = sorted((home / "tools").glob("python-*/bin/python3"))
        if bundled:
            return str(bundled[0])
    return "python3"


def hermes_cli() -> str | None:
    override = os.environ.get("PANTLER_HERMES", "")
    if override:
        return override if Path(override).exists() else None
    return shutil.which("hermes")


def wait_for(url: str, seconds: float = 20.0) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            time.sleep(0.3)
    return False


def get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=10) as response:
        return json.loads(response.read().decode())


def put(url: str, payload: dict) -> tuple[int, dict]:
    # The BFF refuses a write that carries no provenance at all, because "no headers" is what a
    # script sends and also what an attacker's script sends; a caller that is not a browser says
    # so with the origin it is speaking as
    # (the internal security audit A19-EX-2).
    origin = f"http://{urllib.parse.urlparse(url).netloc}"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Origin": origin},
        method="PUT",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode() or "{}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", action="store_true", help="leave the profile and BFF running")
    parser.add_argument("--hermes-home", default="", help="engine home to install a probe profile into")
    args = parser.parse_args()

    if args.hermes_home:
        os.environ["PANTLER_HERMES_HOME"] = args.hermes_home
    hermes = hermes_cli()
    if hermes is None:
        print("capability-probe: no `hermes` on PATH, so a profile cannot be installed here")
        return 3

    home = Path(os.environ.get("PANTLER_HERMES_HOME") or (ROOT / ".hermes-dev")).resolve()
    if not (home / "profiles").is_dir():
        print(f"capability-probe: {home} is not an engine home with profiles/, so nothing to install into")
        return 3
    name = f"capability-probe-{os.getpid()}"
    profile = home / "profiles" / name
    problems: list[str] = []
    bff: subprocess.Popen | None = None
    code = 3
    # The directory this run created, held as a path: the guard used to compare against a `name`
    # that later code rebound, which is how eleven throwaway profiles came to be left behind.
    created: Path | None = None
    try:
        install = subprocess.run(
            [hermes, "profile", "install", str(DISTRIBUTION), "--name", name, "-y"],
            env={**os.environ, "HERMES_HOME": str(home)},
            capture_output=True,
            text=True,
            timeout=300,
        )
        created = profile if profile.is_dir() else None
        if install.returncode != 0 or not profile.is_dir():
            print("capability-probe: the installer failed")
            print((install.stderr or install.stdout or "").strip()[-600:])
            return 1

        port = free_port()
        bff = subprocess.Popen(
            [python_for_bff(), str(ROOT / "app" / "server" / "pantler_server.py"),
             "--port", str(port), "--profile-dir", str(profile)],
            env={**os.environ, "PYTHONPATH": str(ROOT / "core" / "src")},
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        base = f"http://127.0.0.1:{port}"
        if not wait_for(f"{base}/api/health"):
            print("capability-probe: the BFF did not come up")
            return 1

        registry = get(f"{base}/api/capabilities")
        if not registry.get("available"):
            print(f"capability-probe: the registry is unavailable — {registry.get('reason')}")
            return 1

        rows = {row["id"]: row for row in registry["data"]}
        installed = sorted(p.name for p in (profile / "skills").iterdir() if p.is_dir())
        for skill in installed:
            row = rows.get(f"skill:{skill}")
            if row is None:
                problems.append(f"{skill} is installed but the registry serves no row for it")
                continue
            if row["provenance"] != "shipped":
                problems.append(f"{skill}: provenance is {row['provenance']!r}, expected 'shipped'")
            if not row["toggleable"]:
                problems.append(f"{skill}: is not toggleable ({row['reason']})")
            if row["applied_at"] != "new_conversations":
                problems.append(f"{skill}: applies at {row['applied_at']!r}")
            if not row["description"]:
                problems.append(f"{skill}: no description, so the engine has no routing signal")
            elif len(row["description"]) > PROMPT_DESC_LIMIT:
                problems.append(
                    f"{skill}: description is {len(row['description'])} characters, over the "
                    f"{PROMPT_DESC_LIMIT}-character prompt budget"
                )

        # A plugin's files being present is not the same as the plugin running: the engine's
        # `plugins.enabled` list is opt-in, so an install can ship a plugin and never load it.
        # That is exactly the gap this harness exists to catch, so assert the state, not just
        # the row.
        plugin_rows = [row for row in rows.values() if row["kind"] == "plugin"]
        if not plugin_rows:
            problems.append("the registry serves no plugin row at all")
        for row in plugin_rows:
            if not row["enabled"]:
                problems.append(
                    f"{row['name']} ships but is not enabled in this profile, so its tools are "
                    f"declared and never loaded"
                )
        if not any(row["kind"] == "connector" for row in rows.values()):
            problems.append("the registry serves no connector row at all")

        # The packs, from a *fresh* install: three shipped plugins resolve their record types
        # from `packs_dir`, and the payload used to carry no packs at all, so a record tool
        # refused on a machine that had just installed everything correctly. A read is enough
        # to prove the wiring and writes nothing (the internal audit WIRE-1).
        packs = get(f"{base}/api/packs")
        pack_ids = [pack.get("id") for pack in packs.get("data") or []]
        if not any(pack_id != "example" for pack_id in pack_ids):
            problems.append(
                f"the install serves no real pack (packs: {pack_ids or 'none'}) — the record "
                f"tools resolve their types from packs_dir and will refuse"
            )
        else:
            first = next(pack for pack in packs["data"] if pack.get("id") != "example")
            types = [record.get("type") for record in first.get("records") or []]
            if not types:
                problems.append(f"pack {first.get('id')} declares no record types")
            else:
                listing = get(f"{base}/api/records/{types[0]}?limit=1")
                if "data" not in listing:
                    problems.append(
                        f"reading a record of type {types[0]} from {first.get('id')} answered "
                        f"{listing}"
                    )

        # The switch, on a real row, through the real write path.
        if installed:
            target = f"skill:{installed[0]}"
            status, answer = put(f"{base}/api/capabilities/{target}", {"enabled": False})
            if status != 200:
                problems.append(f"switching {target} off answered {status}: {answer}")
            else:
                after = {row["id"]: row for row in get(f"{base}/api/capabilities")["data"]}
                if after[target]["enabled"]:
                    problems.append(f"{target} still reads as enabled after being switched off")
                config = (profile / "config.yaml").read_text()
                if installed[0] not in config:
                    problems.append(f"{target} was switched off but config.yaml does not name it")
                put(f"{base}/api/capabilities/{target}", {"enabled": True})

        if problems:
            code = 1
        else:
            print(
                f"capability-probe: {len(installed)} installed skill(s), "
                f"{len(plugin_rows)} plugin(s) enabled, {len(rows)} registry row(s) — "
                f"install → registry → switch verified"
            )
            if args.keep:
                print(f"capability-probe: kept — profile {profile}, BFF {base}")
                bff = None
            code = 0
    finally:
        if bff is not None:
            bff.terminate()
            try:
                bff.wait(timeout=5)
            except subprocess.TimeoutExpired:
                bff.kill()
        # Only ever the profile this run created, and only inside the recorded home.
        if created is not None and not args.keep and created.parent == home / "profiles":
            shutil.rmtree(created, ignore_errors=True)
            if created.exists():
                # A leak is loud now: the run fails rather than leaving 30 MB behind quietly.
                print(f"capability-probe: could not remove {created}", file=sys.stderr)
                problems.append(f"the throwaway profile {created.name} could not be removed")
                code = 1

    if problems:
        for problem in problems:
            print(f"capability-probe: {problem}")
        print(f"capability-probe: {len(problems)} problem(s)")
    return code


if __name__ == "__main__":
    sys.exit(main())
