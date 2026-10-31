"""The installed skills index — the profile's skills, read from its own files.

**Why this is not the engine's `GET /v1/skills`.** That route is broken at the pinned commit,
and not by anything a caller can change. Its handler calls::

    _find_all_skills(skip_disabled=False, include_editorial=True)

but this build's ``tools.skills_tool._find_all_skills`` accepts only ``skip_disabled`` —
``include_editorial`` appears nowhere else in the tree, so the call raises ``TypeError``, the
handler's bare ``except`` answers 500, and the listing has never worked. We do not fork the
engine (the design notes §1), and restarting the operator's gateway is not the front end's business, so
the installed tier reads the skill files it already owns — the same division of labour as
``engine_settings.py`` reading ``config.yaml`` for settings.

**What it mirrors from the engine**, so the page does not list a skill the agent would not load:

* the profile's ``skills/`` directory as the local tier, plus ``HERMES_HOME/skills`` when it
  differs (higher-precedence roots are empty in this install);
* the ``platforms:`` OS gate — a macOS-only skill is not listed on Linux;
* the ``environments:`` gate — `kanban` comes from the caller (the profile's toolset opt-ins),
  `docker` and `s6` from the filesystem, and an unknown tag fails open as the engine's does;
* ``skills.disabled`` in ``config.yaml``, reported per skill as ``enabled`` so the screen can
  switch one back on;
* ``ESSENTIAL_SKILLS`` (``hermes-agent``) is **not listed at all**: the engine always loads it,
  so a switch could not change anything and the screen does not pretend otherwise;
* first-tier-wins de-duplication by declared name, before the visibility filters.

**What it does not mirror, and does not pretend to:** the ``requires_apps:`` gate,
``skills.external_dirs``, and same-tier shadowing. None is configured in this install, and each
would need the engine's own resolver to answer honestly.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, Iterable

from engine_settings import ESSENTIAL_SKILLS

# Mirrors agent.skill_utils.PLATFORM_MAP — the OS names a `platforms:` list may use, mapped to
# the prefix of `sys.platform` they stand for.
PLATFORM_MAP = {"macos": "darwin", "linux": "linux", "windows": "win32"}

# The `environments:` tags the engine knows how to detect. Anything else fails open (the skill
# stays relevant), and a known tag that is not active hides the skill.
KNOWN_ENVIRONMENTS = frozenset({"kanban", "docker", "s6"})

# Mirrors the directories agent.skill_utils.EXCLUDED_SKILL_DIRS refuses to scan.
EXCLUDED_DIRS = frozenset(
    (
        ".git",
        ".github",
        ".hub",
        ".archive",
        ".curator_backups",
        ".locks",
        ".venv",
        "venv",
        "node_modules",
        "site-packages",
        "__pycache__",
        ".tox",
        ".nox",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
    )
)

# Progressive-disclosure folders inside a skill package: a SKILL.md in one of these is a
# document, not a skill of its own.
SUPPORT_DIRS = frozenset(("references", "templates", "assets", "scripts"))

# The engine reads only the head of a skill to parse its frontmatter; so do we.
FRONTMATTER_BYTES = 4000

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---", re.S)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:FRONTMATTER_BYTES]
    except OSError:
        return ""


def _unquote(value: str) -> str:
    text = value.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    return text


def _parse_value(value: str) -> str | list[str]:
    """A scalar, or an inline `[a, b]` list, with the quotes the engine's YAML load would strip."""
    text = value.strip()
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        return [] if inner == "" else [_unquote(part) for part in inner.split(",") if part.strip()]
    return _unquote(text)


def parse_frontmatter(text: str) -> dict[str, Any]:
    """The first frontmatter block as `key -> scalar | list`.

    The engine prefers a real YAML load and falls back to a line splitter. This is that fallback,
    plus block sequences (`environments:` / `  - kanban`), because one bundled skill gates itself
    on a block-list environment and reading it as an empty scalar would list a skill the engine
    does not offer.
    """
    match = _FRONTMATTER_RE.match(text.removeprefix("\ufeff"))
    if match is None:
        return {}

    lines = match.group(1).splitlines()
    found: dict[str, Any] = {}
    cursor = 0
    while cursor < len(lines):
        line = lines[cursor]
        if not line.strip() or line[:1] in (" ", "\t", "#") or ":" not in line:
            cursor += 1
            continue
        key, value = line.split(":", 1)
        value = value.strip()
        if value:
            found[key.strip()] = _parse_value(value)
            cursor += 1
            continue

        # A bare `key:` may open a block sequence (`- item`) or a nested mapping
        # (`child: value`). Both shapes are real here: the spec has no `category`, so our own
        # skills declare it under `metadata:` while an engine skill may declare a block list in
        # the same position. Reading both keeps a spec-clean skill grouped by what it declares.
        items: list[str] = []
        nested: dict[str, Any] = {}
        cursor += 1
        while cursor < len(lines):
            child = lines[cursor]
            if not child.strip():
                cursor += 1
                continue
            if child[:1] not in (" ", "\t"):
                break
            stripped = child.strip()
            if stripped.startswith("-"):
                items.append(_unquote(stripped[1:]))
            elif ":" in stripped:
                child_key, child_value = stripped.split(":", 1)
                nested[child_key.strip()] = (
                    _parse_value(child_value.strip()) if child_value.strip() else []
                )
            cursor += 1
        found[key.strip()] = nested if nested else items
    return found


def _as_list(value: Any) -> list[str]:
    """A parsed list, an inline `[a, b]`, `a, b` or a bare `a`, as a list of unquoted names."""
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
        return [part.strip().strip("\"'") for part in text.split(",") if part.strip()]
    return [text] if text else []


def matches_platform(frontmatter: dict[str, Any], platform: str | None = None) -> bool:
    """True when the skill's `platforms:` list matches the OS (absent = every OS).

    *platform* is `sys.platform` unless given, so a test can pin the answer instead of
    inheriting whatever host it runs on.
    """
    platforms = _as_list(frontmatter.get("platforms"))
    if not platforms:
        return True
    current = platform if platform is not None else sys.platform
    for name in platforms:
        mapped = PLATFORM_MAP.get(name.lower(), name.lower())
        if current.startswith(mapped):
            return True
    return False


def matches_environment(frontmatter: dict[str, Any], active: Iterable[str] = ()) -> bool:
    """True when ANY declared `environments:` tag is active.

    The engine's rule, including its fail-open: an unknown tag is relevant. *active* carries the
    tags a caller determined for itself (the BFF passes `kanban` when the profile opts into the
    kanban toolset); `docker` and `s6` are read from the filesystem here.
    """
    tags = [tag.lower() for tag in _as_list(frontmatter.get("environments"))]
    if not tags:
        return True
    running = {tag.lower() for tag in active}
    for tag in tags:
        if tag in running:
            return True
        if tag == "docker":
            if Path("/.dockerenv").exists() or Path("/run/.containerenv").exists():
                return True
        elif tag == "s6":
            if Path("/run/s6").is_dir() or Path("/package/admin/s6-overlay").is_dir():
                return True
        elif tag not in KNOWN_ENVIRONMENTS:
            return True  # unknown tags fail open, exactly as the engine's detector does
    return False


def _category(frontmatter: dict[str, Any], relative: Path) -> str | None:
    """The skill's group: what it declares, else its first directory under the root.

    Three places, in order, because three authors write frontmatter here. The Agent Skills spec
    has no `category`, so our own skills declare it under `metadata:` — the spec's map for exactly
    this kind of extra. Two of them (`invoicing`, `soil-amendment-engine`) were written before
    that rule and carried a top-level `category:`; both were rewritten, so no shipped skill has
    one now. The engine's bundled skills declare neither and are grouped by their directory.
    Reading all three keeps a skill an operator wrote, or one the engine ships, from silently
    landing in "General".

    This is presentation only — it changes no skill's loadability.
    """
    declared = str(frontmatter.get("category") or "").strip()
    if declared:
        return declared
    metadata = frontmatter.get("metadata")
    if isinstance(metadata, dict):
        nested = str(metadata.get("category") or "").strip()
        if nested:
            return nested
    parts = relative.parts
    return parts[0] if len(parts) >= 3 else None


def _skill_files(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    found: list[Path] = []
    for path in sorted(root.rglob("SKILL.md")):
        parts = path.parts
        if any(part in EXCLUDED_DIRS for part in parts):
            continue
        if any(part in SUPPORT_DIRS for part in parts[:-1]):
            continue
        found.append(path)
    return found


def skill_roots(profile_dir: Path) -> list[Path]:
    """The roots to read, in precedence order: the profile, then the engine home if it differs."""
    local = profile_dir / "skills"
    home = profile_dir.parent.parent / "skills"
    roots = [local]
    if home.is_dir() and home.resolve() != local.resolve():
        roots.append(home)
    return roots


def load_skills(
    profile_dir: Path,
    disabled: Iterable[str] = (),
    platform: str | None = None,
    active_environments: Iterable[str] = (),
) -> list[dict[str, Any]]:
    """The profile's skills, as `{name, description, category, enabled, essential}`.

    A disabled skill is **listed with `enabled: false`**, not dropped: this feeds a screen that
    can switch it back on, which is exactly what the engine's own config surface does
    (`_find_all_skills(skip_disabled=True)`). A skill the current OS or environment cannot load
    is dropped — there is no switch that would change that.
    """
    # The engine subtracts ESSENTIAL_SKILLS from the list before it filters, so a name written
    # for one of those is inert — reporting it as off would be the lie, not the switch.
    hidden = {name for name in disabled if name} - ESSENTIAL_SKILLS
    seen: set[str] = set()
    skills: list[dict[str, Any]] = []

    for root in skill_roots(profile_dir):
        for skill_md in _skill_files(root):
            frontmatter = parse_frontmatter(_read(skill_md))
            name = str(frontmatter.get("name") or skill_md.parent.name).strip()
            if not name or name in seen:
                continue
            # Shadowing is resolved over everything scanned, *before* visibility — a hidden
            # copy still owns its name, exactly as the engine's catalog resolves it.
            seen.add(name)
            if not matches_platform(frontmatter, platform):
                continue
            if not matches_environment(frontmatter, active_environments):
                continue
            # The engine always loads ESSENTIAL_SKILLS, so there is nothing an operator could do
            # with one: it is not listed, and `set_disabled_skills` refuses to write it.
            if name in ESSENTIAL_SKILLS:
                continue
            skills.append(
                {
                    "name": name,
                    "description": str(frontmatter.get("description", "")).strip(),
                    "category": _category(frontmatter, skill_md.relative_to(root)),
                    "enabled": name not in hidden,
                }
            )

    skills.sort(key=lambda skill: (skill["category"] or "", skill["name"]))
    return skills
