"""The capability registry — every switchable thing in this profile, in one shape.

Why it exists (the internal capability plan §2): a capability is declared in four places today — a
pack, a plugin manifest, a skill file and the distribution — and none of them knows about the
others. The operator's question is simpler than that: *what is this, and how do I turn it off?*
This module answers it from the files the profile already owns, so the answer cannot drift from
the thing it describes.

Sources, all of them local:

* **skills** — `skills_index.load_skills`, the same loader `/api/skills` and `/api/learning` use
* **plugins** — `<profile>/plugins/*/plugin.yaml`, plus `plugins.enabled` / `plugins.disabled`
* **MCP servers** — `mcp_servers.<name>.enabled` in `config.yaml`
* **connectors** — `tools.connectors.enabled`, listed but **not switchable**, because pantler
  wires no connector of its own yet and a switch that does nothing would be a lie

**Toolsets are deliberately not here.** Their names, labels, tool lists and enabled state live
on the engine's `GET /v1/toolsets`, and this server has no gateway client by design (it reads the
profile's files instead — `app/server/README.md`). The shell composes both lists into one screen
rather than this module inventing a second source for toolset names, which is exactly how the
hand-written card list went stale.

Every row carries `toggleable` and, when false, a `reason`. A row the engine always loads, a
switch that needs a restart, a capability with no client behind it: each says so, and the shell
draws no switch it cannot honour.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from engine_settings import (
    APPLIES_LIVE,
    APPLIES_RESTART,
    EngineProfile,
)

# The distribution's own manifest, copied into the profile root by the installer. It names the
# paths the distribution owns; everything else in the profile is the operator's, the assistant's
# or the engine's. Reading it is how a row can say where a skill came from.
DISTRIBUTION_MANIFEST = "distribution.yaml"
BUNDLED_MANIFEST = Path("skills") / ".bundled_manifest"


def load_capabilities(
    profile: EngineProfile, active_environments: Iterable[str] = ()
) -> dict[str, Any]:
    """Every capability in this profile, in one list.

    *active_environments* is the caller's own environment detection — `kanban` from the
    profile's toolset opt-ins — and is threaded in rather than re-derived here, because this
    registry and `GET /api/skills` have to agree about which skills exist. A skill listed by
    one and missing from the other is a switch the operator can see and not flip
    (the internal audit BFF-8).
    """
    skills = _skills(profile, active_environments)
    return {
        "available": True,
        "profile": profile.name,
        "data": [
            *skills,
            *_plugins(profile),
            *_mcp_servers(profile),
            *_connectors(profile),
        ],
    }


# --------------------------------------------------------------------------- skills


def _skills(profile: EngineProfile, active_environments: Iterable[str] = ()) -> list[dict[str, Any]]:
    from skills_index import load_skills

    owned = _distribution_owned(profile.dir)
    bundled = _bundled_names(profile.dir)
    rows: list[dict[str, Any]] = []
    for skill in load_skills(
        profile.dir,
        profile.disabled_skills(),
        active_environments=active_environments,
    ):
        name = skill["name"]
        rows.append(
            {
                "id": f"skill:{name}",
                "kind": "skill",
                "name": name,
                "label": name,
                "description": skill.get("description", ""),
                "group": skill.get("category") or "General",
                "enabled": bool(skill.get("enabled")),
                "toggleable": True,
                "reason": None,
                "applied_at": APPLIES_LIVE,
                "needs": [],
                "provenance": _provenance(name, owned, bundled),
            }
        )
    return rows


def _provenance(name: str, owned: list[str], bundled: set[str]) -> str:
    """Who put this file here: the distribution, the engine, or this machine.

    The distinction matters because the three behave differently on update — the distribution
    replaces what it owns, the engine re-seeds what it bundles, and neither should touch what
    the operator or the assistant wrote. Until `distribution_owned` names individual skills,
    everything under an owned directory reads as `shipped`, which is the honest reading of the
    manifest as written.
    """
    if name in bundled:
        return "bundled"
    if any(entry == "skills" or entry == f"skills/{name}" for entry in owned):
        return "shipped"
    return "local"


def _distribution_owned(profile_dir: Path) -> list[str]:
    text = _read(profile_dir / DISTRIBUTION_MANIFEST)
    if not text:
        return []
    return _manifest_block_list(text, "distribution_owned")


def _bundled_names(profile_dir: Path) -> set[str]:
    text = _read(profile_dir / BUNDLED_MANIFEST)
    names = set()
    for line in text.splitlines():
        name = line.split(":", 1)[0].strip()
        if name:
            names.add(name)
    return names


# --------------------------------------------------------------------------- plugins


def _plugins(profile: EngineProfile) -> list[dict[str, Any]]:
    # The effective state, not just the config list: a plugin whose live flag is off refuses at
    # call time, so reporting it as on because the engine's list still names it would be the
    # registry telling the operator something the plugin itself would contradict.
    states = profile.plugin_effective_states()
    rows: list[dict[str, Any]] = []
    for name, entry in sorted(installed_plugins(profile).items()):
        manifest = parse_manifest(_read(entry / "plugin.yaml"))
        # `plugins.enabled` is an opt-in allow-list: the engine loads a user plugin only when
        # the list names it (`plugins_discovery._get_enabled_plugins`), so a plugin sitting in
        # the profile with no config entry is off, and saying so is not a guess. The live flag
        # is ANDed in by `plugin_effective_states`.
        enabled = states.get(name, False)
        rows.append(
            {
                "id": f"plugin:{name}",
                "kind": "plugin",
                "name": name,
                "label": str(manifest.get("label") or name),
                "description": str(manifest.get("description") or ""),
                "group": "Plugins",
                "enabled": enabled,
                "toggleable": True,
                "reason": None,
                "applied_at": APPLIES_RESTART,
                "needs": _needs(manifest),
                "provenance": "shipped",
            }
        )
    return rows


def _plugin_dirs(directory: Path) -> Iterable[Path]:
    """Every plugin this profile holds: a directory with a manifest or an entry point."""
    if not directory.is_dir():
        return []
    return [
        entry
        for entry in directory.iterdir()
        if entry.is_dir() and (entry / "plugin.yaml").is_file()
    ]


def installed_plugins(profile: EngineProfile) -> dict[str, Path]:
    """The plugins this profile holds, as `engine name -> directory`.

    The set this module lists and the set a capability write may name have to be one set, or a
    switch can write a name that nothing loads — which the write path then reports as success
    (the internal audit BFF-2). One reader, two callers.
    """
    found: dict[str, Path] = {}
    for entry in _plugin_dirs(profile.dir / "plugins"):
        manifest = parse_manifest(_read(entry / "plugin.yaml"))
        name = str(manifest.get("name") or entry.name).strip()
        if name:
            found[name] = entry
    return found


def _name_list(value: Any) -> list[str]:
    """A manifest value that should be a list of names, read as one.

    `parse_manifest` returns a scalar as a string, so `requires_env: FOO` would otherwise be
    iterated character by character and the screen would claim seven credentials called F,
    O, O… (the internal audit BFF-9).
    """
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _needs(manifest: dict[str, Any]) -> list[str]:
    """What a capability needs before it can work, from the engine's own manifest fields.

    No new manifest keys: the engine warns on unknown ones, and it already has the vocabulary —
    `requires_env` for credentials, `optional_env` for the ones that only unlock extras,
    `requires_auth` for an account, and the dependency lists for code the plugin needs. Reading
    those keeps one source of truth and keeps the warning log quiet.
    """
    needs: list[str] = []
    for key in _name_list(manifest.get("requires_env")):
        needs.append(f"credential:{key}")
    for key in _name_list(manifest.get("optional_env")):
        needs.append(f"credential:{key}?")
    if str(manifest.get("requires_auth", "")).strip().lower() in ("true", "yes"):
        needs.append("auth")
    for key in ("pip_dependencies", "python_dependencies", "external_dependencies"):
        if _name_list(manifest.get(key)):
            needs.append("dependencies")
            break
    return needs


# --------------------------------------------------------------------------- MCP servers


def _mcp_servers(profile: EngineProfile) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name, enabled in sorted(profile.mcp_servers().items()):
        rows.append(
            {
                # The id prefix is the kind — the write path dispatches on it, so a row whose
                # id said `mcp:` while its kind said `mcp_server` could be read but never
                # switched (found by the web agent, not by the route tests).
                "id": f"mcp_server:{name}",
                "kind": "mcp_server",
                "name": name,
                "label": name,
                "description": "",
                "group": "MCP servers",
                "enabled": enabled,
                "toggleable": True,
                "reason": None,
                # The engine reads the server list at discovery, so a change lands on the next
                # session rather than mid-conversation.
                "applied_at": APPLIES_RESTART,
                "needs": [],
                "provenance": "user",
            }
        )
    return rows


# --------------------------------------------------------------------------- connectors


def _connectors(profile: EngineProfile) -> list[dict[str, Any]]:
    """The connector surface, named but not switchable from this registry.

    A connection is not a capability toggle: it is an account the operator authorised in the
    Connectors section, and the section reads its state from Composio. This row exists so the
    registry still names the surface, and its reason points at where the control actually is.
    """
    enabled = profile.connectors_enabled()
    return [
        {
            "id": "connector:composio",
            "kind": "connector",
            "name": "composio",
            "label": "Connected apps",
            "description": (
                "The apps outside this machine. Their sign-in and their state are managed in "
                "the Connectors section below."
            ),
            "group": "Connectors",
            "enabled": True if enabled is None else enabled,
            "toggleable": False,
            "reason": "connections are managed in the Connectors section, not here",
            "applied_at": APPLIES_LIVE,
            "needs": [],
            "provenance": "user",
        }
    ]


# --------------------------------------------------------------------------- manifests


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def parse_manifest(text: str) -> dict[str, Any]:
    """The handful of `plugin.yaml` fields this module needs, without a YAML dependency.

    The engine is the authority on what a manifest means; this reads the fields the registry
    reports and ignores everything else, so a manifest shape it does not understand costs a
    missing label rather than a broken screen. Scalars, inline lists and block sequences only —
    enough for every manifest in this repository and for the engine's own.
    """
    out: dict[str, Any] = {}
    pending: str | None = None
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if pending is not None:
            stripped = raw.strip()
            if stripped.startswith("- ") or stripped == "-":
                item = stripped[1:].strip().strip("'\"")
                if item:
                    out[pending].append(item)
                continue
            pending = None
        if raw[:1].isspace():
            continue  # a nested mapping (config_schema, tags…) is not ours to read
        key, _, value = raw.partition(":")
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if value in (">-", ">", "|", "|-"):
            out[key] = ""
            continue
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            out[key] = [part.strip().strip("'\"") for part in inner.split(",") if part.strip()]
            continue
        if value == "":
            out[key] = []
            pending = key
            continue
        out[key] = value.strip("'\"")
    return out


def _manifest_block_list(text: str, key: str) -> list[str]:
    """A top-level `key:` block sequence or inline list from a small YAML file."""
    names: list[str] = []
    collecting = False
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if not raw[:1].isspace():
            collecting = False
            name, _, value = raw.partition(":")
            if name.strip() != key:
                continue
            value = value.strip()
            if value.startswith("[") and value.endswith("]"):
                inner = value[1:-1].strip()
                return [part.strip().strip("'\"") for part in inner.split(",") if part.strip()]
            collecting = True
            continue
        if collecting:
            stripped = raw.strip()
            if stripped.startswith("- "):
                names.append(stripped[2:].strip().strip("'\""))
            else:
                collecting = False
    return [name for name in names if name]
