#!/usr/bin/env python3
"""Copy the installation's provisioned credentials into every profile that lacks them.

A profile created from the app is a copy of the product payload, including `.env`. That is how a
new business gets working credentials, but it also means a key added or rotated **after** a
profile was created never reaches it. This script is the repair and rotation path: it reads the
installation's value and writes it, 0600 and atomically, into each profile's `.env`.

The value is never printed. The default is to fill a missing key only; `--force` replaces an
existing value, which is what a rotation needs.

Usage:
    scripts/sync-profile-keys.py                         # fill missing COMPOSIO_API_KEY
    scripts/sync-profile-keys.py --force                 # rotate every profile
    scripts/sync-profile-keys.py --dry-run               # say what would change

Source order: `PANTLER_COMPOSIO_API_KEY` in this process's environment, then `COMPOSIO_API_KEY`
in the source profile's `.env` (default: the `pantler` profile beside `--profiles-root`).
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from pathlib import Path

KEY_NAME = "COMPOSIO_API_KEY"
DEPLOYMENT_KEY_NAME = "PANTLER_COMPOSIO_API_KEY"
ROOT = Path(__file__).resolve().parent.parent


def default_profiles_root() -> Path:
    home = os.environ.get("HERMES_HOME", "").strip()
    if home:
        return Path(home) / "profiles"
    return ROOT / ".hermes-dev" / "profiles"


def env_value(path: Path, name: str) -> str:
    """One `NAME=value` from an `.env`, or "". Quotes and `export` are tolerated."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        if key.startswith("export "):
            key = key[7:].strip()
        if key == name:
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1].strip()
            return value
    return ""


def source_value(profiles_root: Path, source_profile: str) -> str:
    deployment = os.environ.get(DEPLOYMENT_KEY_NAME, "").strip()
    if deployment:
        return deployment
    return env_value(profiles_root / source_profile / ".env", KEY_NAME)


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def set_env_value(path: Path, name: str, value: str) -> None:
    lines: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    kept = [
        line
        for line in lines
        if not (
            line.strip()
            and not line.lstrip().startswith("#")
            and "=" in line
            and line.partition("=")[0].strip().removeprefix("export ").strip() == name
        )
    ]
    kept.append(f"{name}={value}")
    atomic_write(path, "\n".join(kept) + "\n")


def profile_directories(profiles_root: Path) -> list[Path]:
    try:
        entries = sorted(profiles_root.iterdir(), key=lambda path: path.name)
    except OSError:
        return []
    return [
        entry
        for entry in entries
        if entry.is_dir() and not entry.name.startswith(".") and (entry / "config.yaml").is_file()
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profiles-root", type=Path, default=default_profiles_root())
    parser.add_argument("--source-profile", default="pantler")
    parser.add_argument("--force", action="store_true", help="replace an existing value")
    parser.add_argument("--dry-run", action="store_true", help="say what would change")
    args = parser.parse_args(argv)

    root: Path = args.profiles_root
    if not root.is_dir():
        print(f"sync-profile-keys: no profiles directory at {root}", file=sys.stderr)
        return 2

    value = source_value(root, args.source_profile)
    if not value:
        print(
            "sync-profile-keys: no value. Set PANTLER_COMPOSIO_API_KEY, or put "
            f"{KEY_NAME} in {root / args.source_profile / '.env'}.",
            file=sys.stderr,
        )
        return 2

    changed = 0
    for profile in profile_directories(root):
        path = profile / ".env"
        current = env_value(path, KEY_NAME)
        if current and not args.force:
            print(f"{profile.name}: {KEY_NAME} already set")
            continue
        if current == value and not args.force:
            print(f"{profile.name}: {KEY_NAME} already set")
            continue
        if args.dry_run:
            print(f"{profile.name}: would set {KEY_NAME}")
            continue
        set_env_value(path, KEY_NAME, value)
        print(f"{profile.name}: {KEY_NAME} set")
        changed += 1

    if args.dry_run:
        print("dry run: nothing written")
    else:
        print(f"sync-profile-keys: {changed} profile(s) updated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
