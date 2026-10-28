#!/usr/bin/env python3
"""Assert that the distribution we ship is coherent, before it reaches anyone's machine.

This is the first slice of `skillcheck` (the skills and plugins notes
§2.2, the internal capability plan §3 item A5): the distribution payload is
the one artefact the *engine* never inspects, because it validates hub installs and agent-written
skills rather than a `distribution_owned` tree. Everything here is a rule this repository has
already argued in prose — the point is that a rule in prose fails nothing.

What it checks, and why each one has bitten or could:

1. **Every `distribution_owned` path exists in the payload.** A declared path that is absent is
   skipped silently (`_owned_entries` yields only `if src.exists()`), so a typo would quietly stop
   the distribution owning something it believes it owns.
2. **`.no-bundled-skills` is present *and* declared.** Present-but-undeclared means it never
   installs; declared-but-absent means the engine seeds its whole bundled skill set into a food
   business's profile.
3. **Every shipped skill obeys the house rules**, and every relative link in one resolves: frontmatter parses, `name` matches its directory,
   `description` fits the engine's 60-character prompt budget (`SKILL_PROMPT_DESC_LIMIT`) or the
   routing signal is truncated, only the Agent Skills spec's fields are top-level, and a licence is
   declared.
4. **A skill the plugin also bundles is byte-identical to the distribution's copy.** Two copies of
   one skill drift; a plugin test asserts it for `soil-amendment`, and this asserts it for any
   plugin, from the distribution's side.
5. **Every plugin that imports the kernel carries a copy of it** — byte-identical to
   `core/src/pantler_core`, because nothing installs the kernel into the engine's Python on a
   machine that has no dev script (the plugin kernel).
6. **Every plugin ships, file for file — and is enabled.** A plugin is how a pack reaches the engine, and the
   payload is the only thing the installer copies — so a plugin that lives only in the repository
   is a capability an operator does not get. The copies under `distribution/plugins/` must be
   byte-identical to `plugins/`, and must not carry `tests/`, `scripts/` or `__pycache__`.
   `scripts/check-distribution.py --sync-plugins` writes them; a plain run checks them.
7. **The packs ship, and they are the repository's packs.** `records`, `consent` and `spray`
   resolve their record types from `packs_dir`, so a payload without `packs/` installs eight
   skills whose tools all refuse. The copies under `distribution/packs/` must be byte-identical,
   and `distribution_owned` must name the directory (the internal audit DIST-1).
8. **The shipped `config.yaml` names only real toolsets**, and its `approvals.mode` is a string in
   the engine's vocabulary. The file suppresses no toolset at install — the surface is the
   operator's to switch — but when it does name one (their own edit, carried forward by an
   update), a name the engine does not know is warned about and ignored, so a typo would leave the
   capability enabled on their machine while the file says otherwise. A bare `off` parses as YAML
   `false`, which the engine maps to "approvals off" with no error at all
   (the internal backend audit §2.1).

Standard library only, like everything else in this repository's shipped path.

Usage:
    scripts/check-distribution.py          exit 1 on any violation
"""

from __future__ import annotations

import argparse
import json
import shutil
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DISTRIBUTION = ROOT / "distribution"
MANIFEST = DISTRIBUTION / "distribution.yaml"
BASELINE = ROOT / "baseline" / "pantler-toolsets.json"

PROMPT_DESC_LIMIT = 60  # agent/skill_utils.SKILL_PROMPT_DESC_LIMIT at the pin
SPEC_FIELDS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
APPROVAL_MODES = {"manual", "smart", "off"}

#: Problems found by this run. `main` clears it, so a second `main()` in one process — a test,
#: or a future `--watch` — does not re-report the first run's findings
#: (the internal audit SCR-2).
problems: list[str] = []

#: Things a fresh install will ask the operator for, and which we deliberately do not ship. They
#: are reported on every run and they never fail it: the alternative — seeding a price book — would
#: have the assistant quote prices nobody set (the internal audit DIST-2, DIST-7).
warnings: list[str] = []


def fail(message: str) -> None:
    problems.append(message)


def warn(message: str) -> None:
    warnings.append(message)


def read(path: Path) -> str:
    """The file's text, or "" — and a *failure* when it exists but cannot be read.

    `""` for any `OSError` made an unreadable file look like a missing one, so a permission
    problem was reported as an absent path — or, where the caller treats empty as "nothing to
    check", as no problem at all (the internal audit SCR-2).
    """
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
    except OSError as exc:
        fail(f"{path} exists but could not be read: {exc}")
        return ""


def frontmatter(text: str) -> dict[str, object] | None:
    """The leading `---` block, as `key -> scalar | list | mapping`. None when it is absent."""
    match = re.match(r"---\n(.*?)\n---\n", text.removeprefix("\ufeff"), re.S)
    if match is None:
        return None
    found: dict[str, object] = {}
    lines = match.group(1).splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip() or line[:1] in (" ", "\t", "#") or ":" not in line:
            index += 1
            continue
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if value:
            found[key] = value.strip("'\"")
            index += 1
            continue
        items: list[str] = []
        nested: dict[str, str] = {}
        index += 1
        while index < len(lines):
            child = lines[index]
            if not child.strip():
                index += 1
                continue
            if child[:1] not in (" ", "\t"):
                break
            stripped = child.strip()
            if stripped.startswith("- "):
                items.append(stripped[2:].strip().strip("'\""))
            elif ":" in stripped:
                child_key, _, child_value = stripped.partition(":")
                nested[child_key.strip()] = child_value.strip().strip("'\"")
            index += 1
        found[key] = nested if nested else items
    return found


def nested_scalar(text: str, block: str, key: str) -> str:
    """`block.key` as a scalar, one level down — `approvals.mode`, for instance."""
    inside = False
    for line in text.splitlines():
        if line.strip() and not line[:1].isspace():
            inside = line.partition(":")[0].strip() == block
            continue
        if not inside:
            continue
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or ":" not in stripped:
            continue
        name, _, value = stripped.partition(":")
        if name.strip() == key:
            return value.strip().strip("'\"")
    return ""


def manifest_list(text: str, key: str) -> list[str]:
    """A top-level `key:` block sequence or inline list."""
    names: list[str] = []
    collecting = False
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line[:1].isspace():
            collecting = False
            name, _, value = line.partition(":")
            if name.strip() != key:
                continue
            value = value.strip()
            if value.startswith("[") and value.endswith("]"):
                return [
                    part.strip().strip("'\"") for part in value[1:-1].split(",") if part.strip()
                ]
            collecting = True
            continue
        if collecting:
            stripped = line.strip()
            if stripped.startswith("- "):
                names.append(stripped[2:].strip().strip("'\""))
            else:
                collecting = False
    return names


def manifest_scalar(text: str, key: str) -> str:
    """A top-level `key: value` scalar, quotes stripped."""
    for line in text.splitlines():
        if not line[:1].isspace() and line.partition(":")[0].strip() == key:
            return line.partition(":")[2].strip().strip("'\"")
    return ""


#: A YAML comment: `#` at the start of a line, or after whitespace. The scanners below are not
#: parsers, so this is the one YAML nicety they have to know about to read the payload's files.
COMMENT = re.compile(r"(^|\s)#")


def strip_comment(line: str) -> str:
    """The line up to its YAML comment, if it has one."""
    match = COMMENT.search(line)
    return line[: match.start()] if match else line


def indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" \t"))


def nested_list(text: str, block: str, key: str) -> list[str] | None:
    """`block.key` as a list, or None when that exact key is absent.

    Both YAML shapes the payload uses are read: a block sequence below the key, and the inline
    `key: [a, b]` form. Blank lines and comments are ignored, and the sequence ends at the next
    line indented no further than the key itself.

    The scanner used to return *any* block sequence under the parent — it reset its span only
    when it saw the wanted key, so renaming `agent.disabled_toolsets`, or emptying it and adding
    a decoy list under the same parent, still returned the six toolset names and the gate stayed
    green while the distribution disabled nothing (the internal security audit A19-SC-1).
    `None` is deliberate and load-bearing: this script is standard library only, so the callers
    must treat "no such key" as a failure rather than as an empty list to shrug at.
    """
    lines = text.splitlines()
    start = None
    for index, raw in enumerate(lines):
        line = strip_comment(raw)
        if not line.strip() or line[:1].isspace():
            continue
        name, sep, _ = line.partition(":")
        if sep and name.strip() == block:
            start = index
            break
    if start is None:
        return None
    child_indent = None
    for index in range(start + 1, len(lines)):
        line = strip_comment(lines[index])
        if not line.strip():
            continue
        if indent_of(line) == 0:
            break  # the block is empty: no child key at all
        child_indent = indent_of(line)
        break
    if child_indent is None:
        return None
    for index in range(start + 1, len(lines)):
        line = strip_comment(lines[index])
        if not line.strip():
            continue
        if indent_of(line) < child_indent:
            break  # the parent block has ended
        if indent_of(line) > child_indent:
            continue  # a child of a sibling key, not a key of this block
        name, sep, value = line.partition(":")
        if not sep or name.strip() != key:
            continue
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            return [part.strip().strip("'\"") for part in value[1:-1].split(",") if part.strip()]
        if value:
            return None  # a scalar, not a list: the caller has to fail on the shape too
        items: list[str] = []
        for child in lines[index + 1 :]:
            child_line = strip_comment(child)
            if not child_line.strip():
                continue
            if indent_of(child_line) <= child_indent:
                break
            stripped = child_line.strip()
            if not stripped.startswith("- "):
                break
            items.append(stripped[2:].strip().strip("'\""))
        return items
    return None


def check_manifest() -> list[str]:
    text = read(MANIFEST)
    if not text:
        fail("distribution/distribution.yaml is missing or unreadable")
        return []
    owned = manifest_list(text, "distribution_owned")
    if not owned:
        fail(
            "distribution_owned is empty: an omitted key makes the engine claim the whole "
            "payload instead (profile_distribution.py:343-353)"
        )
    for entry in owned:
        if not (DISTRIBUTION / entry).exists():
            fail(f"distribution_owned names {entry!r}, which the payload does not carry")
    if ".no-bundled-skills" not in owned:
        fail(
            "the bundled-skills marker is not declared in distribution_owned, so it would never "
            "install and the engine's own skills would be seeded into the profile"
        )
    return owned


def check_skills(owned: list[str]) -> None:
    skills_root = DISTRIBUTION / "skills"
    # A SKILL.md inside another skill's directory is a second skill with the parent's name
    # when loaded, and the engine refuses the bare name as ambiguous. The dev profile had
    # exactly that (`social-post-batch/social-post-batch/SKILL.md`), which is why the same
    # skill could not be loaded by name in session web-1a90145424a3.
    for nested in sorted(skills_root.glob("*/*/SKILL.md")):
        fail(
            f"{nested.relative_to(ROOT)}: a SKILL.md inside another skill's directory. "
            f"Move it out or archive it; two skills sharing a name make the bare name "
            f"unloadable."
        )
    for skill_md in sorted(skills_root.glob("*/SKILL.md")):
        name = skill_md.parent.name
        text = read(skill_md)
        block = frontmatter(text)
        if block is None:
            fail(f"skills/{name}/SKILL.md has no frontmatter block")
            continue
        declared = str(block.get("name", ""))
        if declared != name:
            fail(f"skills/{name}: frontmatter name is {declared!r}, not the directory name")
        description = str(block.get("description", ""))
        if not description:
            fail(f"skills/{name}: no description, so the engine has no routing signal")
        elif len(description) > PROMPT_DESC_LIMIT:
            fail(
                f"skills/{name}: description is {len(description)} characters; the engine's "
                f"prompt index truncates at {PROMPT_DESC_LIMIT} to 57 + '…', losing the signal"
            )
        extra = sorted(set(block) - SPEC_FIELDS)
        if extra:
            fail(
                f"skills/{name}: top-level field(s) {', '.join(extra)} are not in the Agent "
                f"Skills spec; extras belong under `metadata:`"
            )
        if not str(block.get("license", "")):
            fail(f"skills/{name}: no `license`, which the shipped path requires to be MIT")
        if f"skills/{name}" not in owned and "skills" not in owned:
            fail(f"skills/{name} exists but no distribution_owned path covers it")


LINK = re.compile(r"\]\(([^)\s]+)\)")


def check_skill_links() -> None:
    """Every relative link in a shipped skill must resolve from where it shipped, inside the payload.

    Drafts live under the skill drafts and link to repository documents; the shipped copies live
    under `distribution/skills/`, where the same relative path means somewhere else entirely. That
    is exactly how the first promotion broke a link, which is why `scripts/promote-skill.py`
    rewrites them and this asserts it — a skill that points at a document nobody can open is worse
    than one that does not cite it.

    Resolving *and* existing is not enough: the design notes resolves from the payload only
    because the payload still sits inside the repository, and points at nothing at all once the
    skills are installed in a profile. Five shipped skills had links like that
    (the internal audit DIST-4), so containment is the second half of the rule.
    """
    payload = DISTRIBUTION.resolve()
    for skill_md in sorted((DISTRIBUTION / "skills").glob("*/**/*.md")):
        for line_number, line in enumerate(skill_md.read_text(encoding="utf-8").splitlines(), 1):
            for match in LINK.finditer(line):
                link = match.group(1)
                if link.startswith(("http://", "https://", "#", "mailto:")):
                    continue
                target = (skill_md.parent / link.split("#", 1)[0]).resolve()
                if not target.exists():
                    fail(
                        f"{skill_md.relative_to(ROOT)}:{line_number} links to {link!r}, which does "
                        f"not resolve from there"
                    )
                elif target != payload and not target.is_relative_to(payload):
                    fail(
                        f"{skill_md.relative_to(ROOT)}:{line_number} links to {link!r}, which "
                        f"resolves outside the payload — it would be dead on an operator's machine"
                    )


#: The two shapes a plugin registers tools in. `_TOOLS` is read as a block from its assignment
#: to the closing `)` at the start of a line; the first element of each row is the tool name.
TOOLS_BLOCK = re.compile(r"^_TOOLS[^=\n]*=\s*\((.*?)^\)", re.S | re.M)
TOOLS_ROW = re.compile(r'^\s*\(\s*"([A-Za-z0-9_.-]+)"\s*,', re.M)
#: `ctx.register_tool(name="…", …)`, on one line or several. A variable (`name=tool_name`) is
#: deliberately not matched: that is what `REGISTER_TOOL_CALL` is for.
REGISTER_TOOL_LITERAL = re.compile(r'\bregister_tool\(\s*name\s*=\s*"([A-Za-z0-9_.-]+)"')
REGISTER_TOOL_CALL = re.compile(r"\bregister_tool\s*\(")


def check_declared_tools() -> None:
    """Every tool a plugin registers must be in its manifest's `provides_tools`.

    The engine's own validator treats an undeclared tool as a hard failure
    (`hermes_cli/plugin_validate.py:417-431`), so a plugin that registers one it does not
    declare fails the check `plugins/README.md` calls "the check that matters" — and
    `records` did exactly that with `record_types`, while the README's own table listed all
    three (the internal audit PLUG-2).

    The names come from the source rather than from running the plugin: this checker has no
    engine, and the shapes are stable — a `_TOOLS` table whose first element is the name, or a
    literal `register_tool(name=…)`. Every `.py` the plugin ships is read, not only `tools.py`:
    `soil-amendment` registers its two tools by name in `__init__.py` and has no `_TOOLS` table
    at all, so the old check opened `tools.py`, found no table and *continued* — a plugin whose
    registration lives in another module was never compared with `provides_tools`. A plugin
    that registers something but yields nothing parsable now fails with a sentence instead of
    skipping, because an unread registration is an unchecked one
    (the internal security audit A19-SC-9). `tests/` and `vendor/` are skipped: a
    fixture's fake tool list and the vendored kernel are not what the engine loads.
    """
    for plugin in sorted((ROOT / "plugins").iterdir()):
        manifest = plugin / "plugin.yaml"
        if not manifest.is_file():
            continue
        declared = set(manifest_list(read(manifest), "provides_tools"))
        registered: set[str] = set()
        registers = False
        for source_file in sorted(plugin.rglob("*.py")):
            relative = source_file.relative_to(plugin)
            if {"__pycache__", "tests", "vendor"} & set(relative.parts):
                continue
            source = read(source_file)
            if REGISTER_TOOL_CALL.search(source):
                registers = True
            for block in TOOLS_BLOCK.finditer(source):
                registered |= set(TOOLS_ROW.findall(block.group(1)))
            registered |= set(REGISTER_TOOL_LITERAL.findall(source))
        if not (declared or registers or registered):
            continue  # nothing in this plugin claims to register a tool
        if not registered:
            fail(
                f"plugins/{plugin.name}: registers tools but no `_TOOLS` table or literal "
                f"`register_tool(name=…)` call could be parsed from its sources, so nothing "
                f"checks them against provides_tools; declare them where this gate can read them"
            )
            continue
        for name in sorted(registered - declared):
            fail(
                f"plugins/{plugin.name}: registers {name!r}, which its plugin.yaml does not "
                f"declare in provides_tools; the engine's validator refuses a plugin like that"
            )


def packs_files() -> list[Path]:
    """Every file of every pack that belongs in the payload."""
    return sorted(path for path in (ROOT / "packs").rglob("*") if path.is_file() and path.suffix != ".pyc")


def sync_pack_copies() -> None:
    """Write `distribution/packs/` from `packs/`, removing anything that no longer ships."""
    source_root = ROOT / "packs"
    target_root = DISTRIBUTION / "packs"
    wanted = {path.relative_to(source_root) for path in packs_files()}
    for stale in sorted(target_root.rglob("*"), reverse=True) if target_root.is_dir() else []:
        if stale.is_file() and stale.relative_to(target_root) not in wanted:
            stale.unlink()
    # …and the directories the unlinked files were the last of, or the payload keeps a pack
    # directory with no pack in it (it did: `distribution/packs/example/` survived the move of
    # the fixture out of the shipped root — the internal audit PACK-1).
    for stale in sorted(target_root.rglob("*"), reverse=True) if target_root.is_dir() else []:
        if stale.is_dir() and not any(stale.iterdir()):
            stale.rmdir()
    for relative in sorted(wanted):
        destination = target_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((source_root / relative).read_bytes())
    print("check-distribution: distribution/packs/ rewritten from packs/")


def check_pack_payload(owned: list[str]) -> None:
    """The packs have to ship, and they have to be the ones in the repository.

    Three shipped plugins read `packs_dir` — `records`, `consent` and `spray` resolve the
    record types they validate against from it — so a payload without `packs/` is eight
    shipped skills instructing tools that cannot run
    (the internal audit DIST-1).
    """
    if "packs" not in owned:
        fail(
            "distribution_owned does not include `packs`, so a fresh install has no record "
            "types: record_save, record_find, consent_check and spray_record all refuse"
        )
    payload = DISTRIBUTION / "packs"
    source_root = ROOT / "packs"
    wanted = {path.relative_to(source_root) for path in packs_files()}
    for relative in sorted(wanted):
        shipped = payload / relative
        if not shipped.is_file():
            fail(f"distribution/packs/{relative} is missing; run --sync-plugins")
        elif shipped.read_bytes() != (source_root / relative).read_bytes():
            fail(
                f"distribution/packs/{relative} differs from packs/{relative}; run "
                f"scripts/check-distribution.py --sync-plugins"
            )
    for extra in sorted(payload.rglob("*")) if payload.is_dir() else []:
        if extra.is_file() and extra.relative_to(payload) not in wanted:
            fail(
                f"distribution/packs/{extra.relative_to(payload)} should not ship; run "
                f"scripts/check-distribution.py --sync-plugins"
            )


def check_plugin_floors(owned: list[str]) -> None:
    """Every plugin's `requires_hermes` must be the distribution's own `hermes_requires`.

    Seven plugins declared `>=0.21.0` while the distribution declared `>=0.22.1` — two floors,
    drifted, and nothing noticed because no check compared them
    (the internal audit DOC-10). The pin is what the plugins are verified against, so the
    pin is the floor; a plugin that genuinely works on an older engine can say so, but it has to
    say it in a place this check reads.
    """
    distribution = read(MANIFEST)
    required = manifest_scalar(distribution, "hermes_requires")
    if not required:
        fail("distribution.yaml has no `hermes_requires`, so no plugin floor can be compared")
        return
    for plugin in sorted(path for path in (ROOT / "plugins").iterdir() if path.is_dir()):
        manifest = plugin / "plugin.yaml"
        if not manifest.is_file():
            continue
        declared = manifest_scalar(read(manifest), "requires_hermes")
        if declared != required:
            fail(
                f"plugins/{plugin.name}/plugin.yaml requires {declared or 'nothing'!r} while the "
                f"distribution requires {required!r}; make them agree"
            )


def check_operator_owes() -> None:
    """What a fresh install has to be given, named once per run.

    Two files and a name are owed by the operator, and neither the audit nor this file should be
    the only place that says so: an install with no price book makes the `invoicing` skill's first
    instruction a refusal, and a payload that declares MIT with no `LICENSE` beside it is a
    licence nobody can read. Both are *warnings* rather than failures on purpose — shipping a
    seeded price book would have the assistant quote fiction, and the copyright holder's name is
    the operator's to write (the internal audit DIST-2, DIST-7).
    """
    books = {
        "pricebook.json": "the invoicing and availability tools resolve customers, items and prices from it",
        "spraybook.json": "the spray tool resolves blocks, products and withholding periods from it",
    }
    for name, why in books.items():
        if not (DISTRIBUTION / name).is_file():
            warn(
                f"no {name} in the payload: {why}. The operator supplies it — a "
                f"{name} beside their profile's config.yaml, or `plugins.entries.<plugin>` in "
                f"config.yaml, or the plugin's PANTLER_* variable. The skills name this step."
            )
    if not (DISTRIBUTION / "LICENSE").is_file():
        declared = {
            str(path.parent.name)
            for path in (DISTRIBUTION / "skills").glob("*/SKILL.md")
            if "license:" in read(path)
        }
        warn(
            f"no LICENSE in the payload while {len(declared)} shipped skill(s) declare one and "
            f"distribution.yaml declares MIT: add it with the copyright holder's name "
            f"(the internal audit DIST-7)."
        )


def check_duplicate_ownership(owned: list[str]) -> None:
    """A path declared twice installs twice and means nothing.

    `distribution_owned` had six duplicated skill entries, because `promote-skill.py` could
    not see them (`promoted_names` matched only a run of `- ` lines) and nothing here looked
    (the internal audit DIST-8, SCR-3).
    """
    seen: dict[str, int] = {}
    for entry in owned:
        seen[entry] = seen.get(entry, 0) + 1
    for entry, count in sorted(seen.items()):
        if count > 1:
            fail(f"distribution_owned names {entry!r} {count} times")


def check_plugin_copies() -> None:
    """A skill the plugin bundles must be the same file the distribution ships."""
    for plugin_skill in sorted((ROOT / "plugins").glob("*/skills/*/SKILL.md")):
        shipped = DISTRIBUTION / "skills" / plugin_skill.parent.name / "SKILL.md"
        if not shipped.is_file():
            fail(f"{plugin_skill.relative_to(ROOT)} has no distribution copy")
            continue
        if read(plugin_skill) != read(shipped):
            fail(
                f"{plugin_skill.parent.name}: the plugin's copy and the distribution's copy "
                f"differ; whichever is stale will be the one an operator loads"
            )


PLUGIN_SKIP_DIRS = {"tests", "scripts", "__pycache__", ".pytest_cache"}
KERNEL = ROOT / "core" / "src" / "pantler_core"


def plugins_needing_kernel() -> list[Path]:
    """Plugins whose source imports `pantler_core`, and so need a vendored copy of it.

    Detected rather than declared: a plugin that starts importing the kernel and is not vendored
    would fail on a machine where the kernel is not installed, and nothing in the repository would
    say so. The scan is the declaration.
    """
    found = []
    for plugin in sorted((ROOT / "plugins").iterdir()):
        if not plugin.is_dir() or not (plugin / "plugin.yaml").is_file():
            continue
        for source in plugin.rglob("*.py"):
            if "vendor" in source.parts or PLUGIN_SKIP_DIRS & set(source.parts):
                continue
            if "pantler_core" in source.read_text(encoding="utf-8"):
                found.append(plugin)
                break
    return found


def sync_kernel_copies() -> None:
    """Write `plugins/<name>/vendor/pantler_core/` for every plugin that imports the kernel."""
    for plugin in plugins_needing_kernel():
        target = plugin / "vendor" / "pantler_core"
        if target.exists():
            shutil.rmtree(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(
            KERNEL,
            target,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        print(f"check-distribution: vendored the kernel into {plugin.name}/vendor/")


def check_kernel_copies() -> None:
    """The vendored kernel must be byte-identical to `core/src/pantler_core`.

    A stale copy is the worst kind: it imports, it runs, and it behaves like the kernel did on the
    day it was copied. So every file is compared, and a file the source no longer has must not
    linger in the copy.
    """
    wanted = {
        path.relative_to(KERNEL)
        for path in KERNEL.rglob("*")
        if path.is_file() and path.suffix != ".pyc" and "__pycache__" not in path.parts
    }
    for plugin in plugins_needing_kernel():
        target = plugin / "vendor" / "pantler_core"
        if not target.is_dir():
            fail(
                f"plugins/{plugin.name} imports pantler_core but carries no vendored kernel; run "
                f"scripts/check-distribution.py --sync-plugins"
            )
            continue
        for relative in sorted(wanted):
            shipped = target / relative
            if not shipped.is_file():
                fail(f"plugins/{plugin.name}/vendor/pantler_core/{relative} is missing")
            elif shipped.read_bytes() != (KERNEL / relative).read_bytes():
                fail(
                    f"plugins/{plugin.name}/vendor/pantler_core/{relative} differs from "
                    f"core/src/pantler_core/{relative}; run "
                    f"scripts/check-distribution.py --sync-plugins"
                )
        for extra in sorted(target.rglob("*")):
            if not extra.is_file() or extra.relative_to(target) in wanted:
                continue
            # A byte-code cache is not a second copy of the kernel: importing a plugin writes one,
            # and the check ran *before* the plugin suites, so a green `test.sh` could be followed
            # by a red gate with no source change — the way a gate becomes one people ignore
            # (the internal audit SCR-8).
            if extra.suffix == ".pyc" or "__pycache__" in extra.parts:
                continue
            fail(
                f"plugins/{plugin.name}/vendor/pantler_core/{extra.relative_to(target)} is not "
                f"in the kernel; run scripts/check-distribution.py --sync-plugins"
            )


def shippable_files(plugin: Path) -> list[Path]:
    """The files of a plugin that belong in the payload: source, not scaffolding."""
    return sorted(
        path
        for path in plugin.rglob("*")
        if path.is_file()
        and path.suffix != ".pyc"
        and not (set(path.relative_to(plugin).parts[:-1]) & PLUGIN_SKIP_DIRS)
    )


def sync_plugin_copies() -> None:
    """Write `distribution/plugins/` from `plugins/`, removing anything that no longer ships."""
    target_root = DISTRIBUTION / "plugins"
    for plugin in sorted((ROOT / "plugins").iterdir()):
        if not plugin.is_dir() or not (plugin / "plugin.yaml").is_file():
            continue
        target = target_root / plugin.name
        wanted = {path.relative_to(plugin) for path in shippable_files(plugin)}
        for stale in sorted(target.rglob("*"), reverse=True) if target.is_dir() else []:
            if stale.is_file() and stale.relative_to(target) not in wanted:
                stale.unlink()
        for relative in sorted(wanted):
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes((plugin / relative).read_bytes())
    print("check-distribution: distribution/plugins/ rewritten from plugins/")


def check_plugin_payload(owned: list[str]) -> None:
    if "plugins" not in owned:
        fail(
            "distribution_owned does not include `plugins`, so a fresh install gets no "
            "first-party tools at all — the skills would be instructions with nothing behind them"
        )
    payload = DISTRIBUTION / "plugins"
    for plugin in sorted((ROOT / "plugins").iterdir()):
        if not plugin.is_dir() or not (plugin / "plugin.yaml").is_file():
            continue
        target = payload / plugin.name
        if not target.is_dir():
            fail(f"plugins/{plugin.name} has no copy under distribution/plugins/")
            continue
        wanted = {path.relative_to(plugin) for path in shippable_files(plugin)}
        for relative in sorted(wanted):
            shipped = target / relative
            if not shipped.is_file():
                fail(f"distribution/plugins/{plugin.name}/{relative} is missing")
            elif shipped.read_bytes() != (plugin / relative).read_bytes():
                fail(
                    f"distribution/plugins/{plugin.name}/{relative} differs from the source; run "
                    f"scripts/check-distribution.py --sync-plugins"
                )
        for extra in sorted(target.rglob("*")):
            if extra.is_file() and extra.relative_to(target) not in wanted:
                fail(
                    f"distribution/plugins/{plugin.name}/{extra.relative_to(target)} should not "
                    f"ship; run scripts/check-distribution.py --sync-plugins"
                )


def check_plugins_enabled() -> None:
    """A plugin the payload ships must be named in the shipped `plugins.enabled` list.

    `plugins.enabled` is an opt-in allow-list, so a plugin that ships without being named is a
    directory of files the engine never loads — the tools it declares exist only on paper. This
    was true of the first payload that carried plugins, and the capability probe caught it.
    """
    payload = DISTRIBUTION / "plugins"
    if not payload.is_dir():
        return
    enabled = nested_list(read(DISTRIBUTION / "config.yaml"), "plugins", "enabled")
    if enabled is None:
        # `nested_list` returns None for "no such key" rather than "no list" (A19-SC-1). A
        # missing `plugins.enabled` is not an empty allow-list to skip past: it is every shipped
        # plugin never loading.
        fail(
            "distribution/config.yaml has no `plugins.enabled` list, so the engine loads none of "
            "the plugins the payload ships"
        )
        return
    for plugin in sorted(payload.iterdir()):
        if not plugin.is_dir() or not (plugin / "plugin.yaml").is_file():
            continue
        if plugin.name not in enabled:
            fail(
                f"the payload ships plugins/{plugin.name} but distribution/config.yaml does not "
                f"name it in plugins.enabled, so a fresh install never loads it"
            )


def check_config() -> None:
    path = DISTRIBUTION / "config.yaml"
    text = read(path)
    if not text:
        fail("distribution/config.yaml is missing, so a fresh install gets the engine's defaults")
        return
    mode = nested_scalar(text, "approvals", "mode")
    if mode not in APPROVAL_MODES:
        fail(f"distribution/config.yaml: approvals.mode is {mode!r}, not one of {APPROVAL_MODES}")
    if mode == "off":
        fail(
            "distribution/config.yaml turns approvals off; a bare `off` is YAML false and the "
            "engine disables the human gate silently (the internal backend audit §2.1)"
        )
    baseline = json.loads(read(BASELINE) or "{}")
    known = {entry["name"] for entry in baseline.get("data", [])}
    if not known:
        fail("baseline/pantler-toolsets.json carries no toolsets to check the config against")
        return
    # The shipped file suppresses nothing, and that is the default it is supposed to carry: a
    # capability is turned off by the operator on the Capabilities screen, not by a list they never
    # saw. What is still checked is the opposite mistake — a name here that the engine does not
    # know is warned about and ignored, so a typo leaves the capability *enabled* while the file
    # reads as though it were off. `None` is "no such key" (the shipped shape) and `[]` is an
    # explicit "suppress nothing": both are fine, and every name that is present must be real.
    disabled = nested_list(text, "agent", "disabled_toolsets")
    for name in disabled or []:
        if name not in known:
            fail(
                f"distribution/config.yaml disables {name!r}, which is not a toolset at the pin; "
                f"the engine warns and ignores it, leaving the capability enabled"
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--sync-plugins",
        action="store_true",
        help="rewrite distribution/plugins/ from plugins/ instead of checking it",
    )
    args = parser.parse_args()
    problems.clear()
    if args.sync_plugins:
        # Order matters: each payload copy is generated *from* its source, so the vendored
        # kernel has to be in place first or the payload's plugins ship without it.
        sync_kernel_copies()
        sync_plugin_copies()
        sync_pack_copies()
        return 0
    owned = check_manifest()
    check_duplicate_ownership(owned)
    check_plugin_floors(owned)
    check_skills(owned)
    check_skill_links()
    check_plugin_copies()
    check_plugin_payload(owned)
    check_kernel_copies()
    check_pack_payload(owned)
    check_declared_tools()
    check_plugins_enabled()
    check_config()
    check_operator_owes()
    for problem in problems:
        print(f"check-distribution: {problem}")
    if problems:
        print(
            f"check-distribution: {len(problems)} problem(s) — the payload is not shippable as it "
            f"stands (the skills and plugins notes §2.1)"
        )
        return 1
    for warning in warnings:
        print(f"check-distribution: note — {warning}")
    print("check-distribution: manifest, skills, plugin copies and shipped defaults are coherent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
