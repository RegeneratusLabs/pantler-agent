"""Profiles — more than one business on one installation.

A pantler profile is a Hermes profile: its own ``config.yaml``, ``.env``, skills, plugins,
memories, sessions and record store under ``$HERMES_HOME/profiles/<name>``. The engine already
isolates all of that; this module is the part the shell needs on top of it:

* **discovery** — which profile directories are live, and which one this installation is;
* **creation** — copy the installed product payload (config, skills, plugins, packs, pricebook)
  into a new profile, rewriting the paths that would otherwise point back at the source;
* **rename and delete** — filesystem operations with the guards that make them safe;
* **the selected profile** — the engine's own ``active_profile`` file, read with a fallback to
  the installed profile so a fresh install has an answer before anything is written;
* **where that profile's data lives** — the record store, the attachment store and the
  workspace. The installed profile keeps the paths it was started with (``--store``,
  ``--attachments-dir``); every other profile keeps its data inside its own profile directory,
  which is what makes delete and rename move the business with the profile.

Standard library only, like the rest of the BFF. It parses exactly the few scalar keys it
needs out of the engine's YAML and never rewrites a block it does not understand: creation
edits the copied file line by line, and a path it cannot recognise is left alone rather than
guessed at.

Why the profile directory is the data home for new profiles
------------------------------------------------------------
The plugins already default to ``<profile>/records.db``, ``<profile>/packs`` and
``<profile>/pricebook.json`` when the config does not name another path. Putting a new
profile's store there means the BFF and the agent's tools read one file without either side
having to be told where it is, and a rename moves it in one ``os.rename``.

The installed profile is the exception: it was started with explicit ``--store`` and
``--attachments-dir`` flags, and those are the operator's existing data. They are preserved
exactly, so upgrading the app does not move a record store.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from engine_settings import EngineProfile

#: The engine's own profile-id grammar (``hermes_constants.PROFILE_ID_RE``). Kept as a copy
#: rather than imported because the BFF never imports the engine; the rule is small and the
#: engine's own CLI would refuse the same names.
PROFILE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

#: ``default`` is the host profile (``$HERMES_HOME`` itself), not a profile under ``profiles/``.
#: It is the engine's, and pantler does not create, rename or delete it.
RESERVED_NAMES = frozenset({"default"})

#: The engine's deleted-profile markers live under ``profiles/.deleted/<name>``. A running
#: multiplexer may still have a profile in memory when its directory is removed and can
#: recreate a skeleton (cron/state.db) before the next rescan; the marker is what keeps that
#: ghost out of the served set, and out of this registry.
TOMBSTONE_DIR = ".deleted"

#: Our per-profile metadata. Deliberately not ``profile.yaml``: that file is the engine's
#: (kanban descriptions, display names, rename history) and the BFF should not have to write
#: YAML to keep our own fields. A missing file is an empty answer, never an error.
META_NAME = ".pantler-profile.json"

#: The engine identity markers. A directory without one is not a profile and is never listed
#: or served (``hermes_constants.named_profile_has_identity``).
IDENTITY_MARKERS = ("config.yaml", ".env", "SOUL.md", "profile.yaml", "auth.json", "state.db")

#: Directories the engine expects in a profile. Empty ones are enough; creating them keeps a
#: fresh profile from looking like a half-built one to the engine's own layout checks.
PROFILE_DIRS = ("memories", "sessions", "skills", "skins", "logs", "plans", "workspace", "cron", "home")

#: Files copied when a profile is created from another. Only the product's payload: no
#: sessions, no memories, no cron, no gateway state, no record store. A new profile is a new
#: business, not a snapshot of the one it was modelled on.
CLONED_FILES = (
    "config.yaml",
    ".env",
    "SOUL.md",
    "distribution.yaml",
    "pricebook.json",
    "spraybook.json",
    ".no-bundled-skills",
)

#: Directories copied when a profile is created from another.
CLONED_DIRS = ("skills", "plugins", "packs", "skins")

#: State inside a cloned ``skills/`` directory that belongs to the source profile, not to the
#: skills: usage counts, the curator's ledger and its state. Copying these would attribute
#: another business's history to the new profile.
SKILL_STATE_NAMES = frozenset(
    {".usage.json", ".curator_ledger.jsonl", ".curator_state", ".skills_prompt_snapshot.json"}
)

#: The scalar keys a clone rewrites when they point at the source. They are the plugin settings
#: the shipped payload uses to find the record store, the packs, the price book and the
#: workspace (``plugins/*/tools.py`` documents each default).
PATH_KEYS = ("store_path", "packs_dir", "pricebook_path", "catalogue_path", "cwd")

#: Environment keys a secondary profile must not inherit: a shared listener owns the port, and
#: a profile that still names one would fight it if someone launched this profile standalone.
STRIPPED_ENV_KEYS = ("API_SERVER_HOST", "API_SERVER_PORT", "GATEWAY_MULTIPLEX_PROFILES")

_SCALAR_LINE = re.compile(r"^(?P<indent>\s*)(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*:\s*(?P<value>.*?)\s*$")
_TOP_LEVEL = re.compile(r"^(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*:\s*(?P<value>.*?)\s*$")


class ProfileError(Exception):
    """A profile operation refused with a status the shell can act on."""

    def __init__(self, status: int, message: str, code: str = "profile_error"):
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code


@dataclass(frozen=True)
class ProfileInfo:
    """One profile as the Profiles page sees it."""

    name: str
    path: Path
    is_install: bool
    active: bool
    display_name: str
    description: str
    provider: str
    model: str
    has_env: bool
    served: bool | None

    @property
    def label(self) -> str:
        return self.display_name or self.name

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "is_install": self.is_install,
            "active": self.active,
            "provider": self.provider or None,
            "model": self.model or None,
            "has_env": self.has_env,
            "served": self.served,
        }


# --------------------------------------------------------------------- small readers


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _atomic_write(path: Path, text: str, mode: int = 0o600) -> None:
    """Write through a sibling temp file, then replace — the engine's own files are read by
    another process and a half-written ``active_profile`` or ``.env`` is a bad morning."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _rmtree(path: Path) -> None:
    """Remove a tree even when SQLite left read-only files behind.

    A file where a directory was expected is removed too: a failed create can leave the
    workspace path as a file, and the cleanup must not turn that into a second exception.
    """
    if not path.exists() and not path.is_symlink():
        return
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
        return

    def _on_error(func, target, _info):  # pragma: no cover - filesystem-specific
        try:
            os.chmod(target, 0o700)
            func(target)
        except OSError:
            pass

    shutil.rmtree(path, onerror=_on_error)


def _pid_alive(pid: Any) -> bool:
    try:
        value = int(pid)
    except (TypeError, ValueError):
        return False
    if value <= 0:
        return False
    try:
        os.kill(value, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (OSError, ValueError):
        return False
    return True


def _multiplex_enabled(config_path: Path) -> bool:
    """Whether the *default* profile's config explicitly asks for multi-profile serving.

    Read by text rather than parsed as YAML: one boolean, and a config we cannot read is an
    honest ``False`` rather than a reason to fail the Profiles screen.
    """
    try:
        text = config_path.read_text(encoding="utf-8")
    except OSError:
        return False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if re.match(r"^multiplex_profiles\s*:\s*(true|yes|on|1)\s*$", stripped, re.I):
            return True
    return False


def _served_profiles(home: Path) -> list[str] | None:
    """The engine's own record of which profiles the live gateway serves, or None.

    The default gateway writes ``served_profiles`` into its ``gateway_state.json`` at startup.
    A single-profile gateway launched from a named profile writes ``[]`` into that profile's
    state file; ``None`` means there is no live record at all.
    """
    candidates = [home / "gateway_state.json"]
    profiles = home / "profiles"
    try:
        candidates.extend(sorted(profiles.glob("*/gateway_state.json")))
    except OSError:
        pass
    best: tuple[float, list[str]] | None = None
    for candidate in candidates:
        state = _read_json(candidate)
        if not isinstance(state, dict) or not _pid_alive(state.get("pid")):
            continue
        served = state.get("served_profiles")
        if not isinstance(served, list):
            continue
        names = [str(name) for name in served if isinstance(name, str) and name]
        # The default's record is authoritative when several live states exist; otherwise the
        # newest write wins. `updated_at` is ISO text on this build, so mtime is the fallback.
        try:
            stamp = candidate.stat().st_mtime
        except OSError:
            stamp = 0.0
        if best is None or stamp >= best[0]:
            best = (stamp, names)
    return best[1] if best is not None else None


# ------------------------------------------------------------------------ the manager


class ProfileManager:
    """The profile registry and the operations the Profiles screen performs."""

    def __init__(
        self,
        install_dir: str | Path,
        *,
        store_path: str | Path,
        attachments_dir: str | Path | None,
        workspace_root: str | Path | None = None,
        repo_root: str | Path | None = None,
    ):
        self.install_dir = Path(install_dir).resolve()
        self.install_name = self.install_dir.name
        self.store_path = Path(store_path).resolve()
        self.attachments_dir = Path(attachments_dir).resolve() if attachments_dir else None
        self.repo_root = Path(repo_root).resolve() if repo_root else Path.cwd().resolve()
        self.workspace_root = (
            Path(workspace_root).resolve()
            if workspace_root
            else self.repo_root / "workspace"
        )

        # A managed profile is a direct child of a directory named ``profiles``. Anything else
        # (the engine's ``~/.hermes`` default, a profile pointed at from elsewhere) is not a
        # registry this installation can create named profiles in.
        if self.install_dir.parent.name == "profiles":
            self.profiles_root = self.install_dir.parent
            self.hermes_home = self.profiles_root.parent
            self.enabled = True
            self.reason = ""
        else:
            self.profiles_root = self.install_dir.parent
            self.hermes_home = self.install_dir.parent
            self.enabled = False
            self.reason = (
                "Profiles need an install under <HERMES_HOME>/profiles/<name>; this server was "
                f"started with {self.install_dir}."
            )
        self._lock = threading.RLock()
        self._active_path = self.hermes_home / "active_profile"
        # A multiplexer can leave a skeleton (state.db, cron heartbeats) in a deleted profile's
        # path before its next rescan. The tombstone makes it unservable; this startup pass is
        # what also removes the bytes, once no process is watching the directory.
        self._sweep_tombstoned()

    def _sweep_tombstoned(self) -> None:
        try:
            markers = list((self.profiles_root / TOMBSTONE_DIR).iterdir())
        except OSError:
            return
        for marker in markers:
            if not marker.is_file():
                continue
            name = marker.name
            if not PROFILE_ID_RE.match(name) or name == self.install_name:
                continue
            with self._lock:
                if self._tombstone(name).exists():
                    _rmtree(self.profiles_root / name)

    # -- availability ----------------------------------------------------

    @property
    def available(self) -> bool:
        return self.enabled and self.install_dir.is_dir()

    @property
    def install(self) -> Path:
        return self.install_dir

    # -- names -----------------------------------------------------------

    @staticmethod
    def normalize(name: Any) -> str:
        if not isinstance(name, str):
            raise ProfileError(400, "a profile name must be a string", "bad_name")
        value = name.strip().lower()
        if not value:
            raise ProfileError(400, "a profile name is required", "bad_name")
        return value

    @classmethod
    def validate(cls, name: Any) -> str:
        value = cls.normalize(name)
        if value in RESERVED_NAMES:
            raise ProfileError(
                422,
                f"“{value}” is the engine's own host profile and is not managed here. "
                "Choose a name for a new profile.",
                "reserved_name",
            )
        if not PROFILE_ID_RE.match(value):
            raise ProfileError(
                422,
                "Use lowercase letters, numbers, '-' or '_', starting with a letter or number, "
                "up to 64 characters.",
                "invalid_name",
            )
        return value

    def path_for(self, name: str) -> Path:
        return self.profiles_root / self.validate(name)

    def _tombstone(self, name: str) -> Path:
        return self.profiles_root / TOMBSTONE_DIR / self.validate(name)

    def _is_deleted(self, name: str) -> bool:
        try:
            return self._tombstone(name).exists()
        except ProfileError:
            return False

    def _mark_deleted(self, name: str) -> None:
        marker = self._tombstone(name)
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("deleted\n", encoding="utf-8")

    def _clear_deleted(self, name: str) -> None:
        self._tombstone(name).unlink(missing_ok=True)

    def _has_identity(self, path: Path) -> bool:
        return path.is_dir() and any((path / marker).exists() for marker in IDENTITY_MARKERS)

    def names(self) -> list[str]:
        if not self.available:
            return []
        found: list[str] = []
        try:
            for entry in self.profiles_root.iterdir():
                if not entry.is_dir() or not PROFILE_ID_RE.match(entry.name):
                    continue
                if self._is_deleted(entry.name):
                    continue
                if self._has_identity(entry):
                    found.append(entry.name)
        except OSError:
            return []
        if self.install_name not in found and self.install_dir.is_dir():
            found.append(self.install_name)
        return sorted(found, key=lambda name: (name != self.install_name, name))

    def exists(self, name: str) -> bool:
        try:
            value = self.validate(name)
            return not self._is_deleted(value) and self._has_identity(self.path_for(value))
        except ProfileError:
            return False

    def require(self, name: Any) -> str:
        value = self.validate(name)
        if not self.available:
            raise ProfileError(503, self.reason or "profiles are not available", "unavailable")
        if self._is_deleted(value) or not self._has_identity(self.profiles_root / value):
            raise ProfileError(404, f"no profile named “{value}”", "not_found")
        return value

    # -- active ----------------------------------------------------------

    def active(self) -> str:
        """The selected profile: the engine's ``active_profile``, or this install's name.

        ``active_profile`` is a sticky *engine* setting that the Hermes CLI also reads. Pantler
        uses it as its own selection so there is one answer rather than two, but falls back to
        the installed profile rather than to ``default``: a fresh pantler install is the
        ``pantler`` profile, and sending the UI to an unmanaged ``default`` would be a lie.
        """
        try:
            raw = self._active_path.read_text(encoding="utf-8-sig").strip()
        except OSError:
            return self.install_name
        if not raw:
            return self.install_name
        try:
            candidate = self.normalize(raw)
        except ProfileError:
            return self.install_name
        if candidate in RESERVED_NAMES:
            return self.install_name
        return candidate if self.exists(candidate) else self.install_name

    def set_active(self, name: Any) -> str:
        value = self.require(name)
        if value == self.install_name:
            self._active_path.unlink(missing_ok=True)
        else:
            _atomic_write(self._active_path, value + "\n", mode=0o600)
        return value

    # -- data locations --------------------------------------------------

    def store_for(self, name: str) -> Path:
        if self.validate(name) == self.install_name:
            return self.store_path
        return self.path_for(name) / "records.db"

    def attachments_for(self, name: str) -> Path:
        if self.validate(name) == self.install_name and self.attachments_dir is not None:
            return self.attachments_dir
        return self.path_for(name) / "attachments"

    def workspace_for(self, name: str) -> Path:
        if self.validate(name) == self.install_name:
            configured = self._terminal_cwd(self.install_dir / "config.yaml")
            if configured is not None:
                return configured
            return self.workspace_root
        return self.workspace_root / self.validate(name)

    @staticmethod
    def _terminal_cwd(config_path: Path) -> Path | None:
        """``terminal.cwd`` from a config, when it is an absolute path we can use."""
        try:
            lines = config_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return None
        section = ""
        for line in lines:
            top = _TOP_LEVEL.match(line)
            if top:
                section = top.group("key")
                continue
            found = _SCALAR_LINE.match(line)
            if found and section == "terminal" and found.group("key") == "cwd":
                raw = _unquote(found.group("value"))
                if raw and os.path.isabs(os.path.expanduser(os.path.expandvars(raw))):
                    return Path(os.path.expanduser(os.path.expandvars(raw))).resolve()
        return None

    # -- metadata --------------------------------------------------------

    def meta(self, name: str) -> dict[str, Any]:
        path = self.path_for(name) / META_NAME
        data = _read_json(path)
        if isinstance(data, dict):
            return {
                "display_name": str(data.get("display_name") or "").strip(),
                "description": str(data.get("description") or "").strip(),
                "created_at": data.get("created_at"),
                "clone_from": data.get("clone_from"),
                "previous_names": [
                    str(value) for value in (data.get("previous_names") or []) if isinstance(value, str)
                ],
            }
        # Fall back to the engine's own ``profile.yaml`` for a profile created by the Hermes
        # CLI or dashboard, so the two front ends do not disagree about a name.
        display, description = self._profile_yaml_meta(path)
        return {
            "display_name": display,
            "description": description,
            "created_at": None,
            "clone_from": None,
            "previous_names": [],
        }

    @staticmethod
    def _profile_yaml_meta(profile_dir: Path) -> tuple[str, str]:
        """Top-level ``display_name`` and ``description`` from ``profile.yaml``, ignoring the
        nested engine blocks this module never writes."""
        try:
            lines = (profile_dir / "profile.yaml").read_text(encoding="utf-8-sig").splitlines()
        except OSError:
            return "", ""
        values: dict[str, str] = {}
        for line in lines:
            match = _TOP_LEVEL.match(line)
            if not match:
                continue
            key = match.group("key")
            if key in ("display_name", "description"):
                values[key] = _unquote(match.group("value"))
        return values.get("display_name", ""), values.get("description", "")

    def update(self, name: str, *, display_name: str | None = None, description: str | None = None) -> ProfileInfo:
        value = self.require(name)
        path = self.path_for(value)
        meta = self.meta(value)
        if display_name is not None:
            meta["display_name"] = str(display_name).strip()[:80]
        if description is not None:
            meta["description"] = str(description).strip()[:400]
        meta.setdefault("created_at", time.time())
        _atomic_write(path / META_NAME, json.dumps(meta, indent=2) + "\n", mode=0o600)
        return self.info(value)

    # -- list / info -----------------------------------------------------

    def gateway(self) -> dict[str, Any]:
        """What the running engine says it serves, and whether it is multiplexing.

        The live served set is the truth when it exists: a gateway that answers for two
        profiles is multiplexing whatever its config said at boot, and a config key alone is
        only a prediction of the next boot. The config fallback matters before the first
        restart, when there is no served set yet.
        """
        configured = _multiplex_enabled(self.hermes_home / "config.yaml")
        served = _served_profiles(self.hermes_home)
        if served is None:
            served = _served_profiles(self.install_dir)
        live_multiplex = served is not None and len(served) > 1
        return {
            "multiplex": configured or live_multiplex,
            "served": served,
            "live": served is not None,
        }

    def _served_for(self, name: str, gateway: dict[str, Any]) -> bool | None:
        served = gateway.get("served")
        if isinstance(served, list) and name in served:
            return True
        if gateway.get("live") is not True:
            return None
        if gateway.get("multiplex") is True:
            return False
        # A single-profile gateway serves the profile it was launched as. We cannot see the
        # launch profile from its ``served_profiles`` (it is ``[]``), but the installed profile
        # is the one this installation runs.
        return name == self.install_name

    def info(self, name: str, *, gateway: dict[str, Any] | None = None, active: str | None = None) -> ProfileInfo:
        value = self.require(name)
        current = active if active is not None else self.active()
        gate = gateway if gateway is not None else self.gateway()
        path = self.path_for(value)
        meta = self.meta(value)
        model = EngineProfile(path).model()
        return ProfileInfo(
            name=value,
            path=path,
            is_install=value == self.install_name,
            active=value == current,
            display_name=meta["display_name"],
            description=meta["description"],
            provider=str(model.get("provider") or ""),
            model=str(model.get("default") or model.get("model") or ""),
            has_env=(path / ".env").is_file(),
            served=self._served_for(value, gate),
        )

    def list(self) -> list[ProfileInfo]:
        if not self.available:
            return []
        gateway = self.gateway()
        active = self.active()
        return [self.info(name, gateway=gateway, active=active) for name in self.names()]

    # -- create ----------------------------------------------------------

    def create(
        self,
        name: Any,
        *,
        source: Any | None = None,
        display_name: str = "",
        description: str = "",
    ) -> ProfileInfo:
        value = self.validate(name)
        if not self.available:
            raise ProfileError(503, self.reason or "profiles are not available", "unavailable")
        source_name = self.require(source if source is not None else self.install_name)
        target = self.path_for(value)
        with self._lock:
            if self._is_deleted(value):
                # The name was deleted before. Recreating it is an explicit act, and the ghost
                # a still-running multiplexer may have left is not a profile.
                self._clear_deleted(value)
                _rmtree(target)
            if target.exists():
                raise ProfileError(409, f"a profile named “{value}” already exists", "exists")
            staging = self.profiles_root / f".{value}.staging-{os.getpid()}-{uuid.uuid4().hex[:8]}"
            created_workspace = self.workspace_root / value
            published = False
            try:
                self._copy_payload(self.path_for(source_name), staging)
                self._prepare_profile(staging, source_dir=self.path_for(source_name), target_dir=target)
                os.replace(staging, target)
                published = True
                self._seed_workspace(source_name, value)
                _atomic_write(
                    target / META_NAME,
                    json.dumps(
                        {
                            "display_name": str(display_name or "").strip()[:80],
                            "description": str(description or "").strip()[:400],
                            "created_at": time.time(),
                            "clone_from": source_name,
                        },
                        indent=2,
                    )
                    + "\n",
                    mode=0o600,
                )
            except BaseException:
                _rmtree(staging)
                if published:
                    _rmtree(target)
                if created_workspace.exists():
                    _rmtree(created_workspace)
                raise
        return self.info(value)

    def _copy_payload(self, source: Path, target: Path) -> None:
        target.mkdir(parents=True, exist_ok=False)
        for directory in PROFILE_DIRS:
            (target / directory).mkdir(parents=True, exist_ok=True)
        for filename in CLONED_FILES:
            origin = source / filename
            if not origin.is_file():
                continue
            destination = target / filename
            shutil.copy2(origin, destination)
            if filename == ".env":
                os.chmod(destination, 0o600)
        for directory in CLONED_DIRS:
            origin = source / directory
            if not origin.is_dir():
                continue
            shutil.copytree(
                origin,
                target / directory,
                symlinks=True,
                ignore=self._clone_ignore(directory),
                dirs_exist_ok=True,
            )
        # A profile installed from the distribution normally carries its own `packs/`, and the
        # older dev install points at the checkout instead. Copy whichever exists, so the
        # rewritten `packs_dir` in the clone names a directory that is really there.
        if not (target / "packs").is_dir():
            external = _scalar_path(source / "config.yaml", "packs_dir")
            if external is not None and external.is_dir():
                shutil.copytree(external, target / "packs", symlinks=True, dirs_exist_ok=True)
        if not (target / "pricebook.json").is_file():
            external = _scalar_path(source / "config.yaml", "pricebook_path")
            if external is not None and external.is_file():
                shutil.copy2(external, target / "pricebook.json")

    @staticmethod
    def _clone_ignore(directory: str):
        """Leave source-profile state behind when copying product files."""
        if directory != "skills":
            return None

        def ignore(_path: str, names: list[str]) -> set[str]:
            return {name for name in names if name in SKILL_STATE_NAMES or name == "__pycache__"}

        return ignore

    def _prepare_profile(self, staging: Path, *, source_dir: Path, target_dir: Path) -> None:
        """Rewrite the copied config for its new home, and give it its own directories."""
        config_path = staging / "config.yaml"
        if config_path.is_file():
            text = config_path.read_text(encoding="utf-8")
            mapping = self._path_mapping(source_dir, target_dir, text)
            text = _rewrite_paths(text, mapping)
            # The keys the plugins resolve are rewritten by *name* as well as by path: a config
            # that used a relative path, or one that pointed at a file the source's own paths
            # did not mention, still ends up inside the new profile.
            text = _rewrite_scalar_keys(
                text,
                {
                    "store_path": str(target_dir / "records.db"),
                    "packs_dir": str(target_dir / "packs"),
                    "pricebook_path": str(target_dir / "pricebook.json"),
                    "catalogue_path": str(target_dir / "pricebook.json"),
                },
                cwd=str(self.workspace_root / target_dir.name),
            )
            text = _remove_standalone(text)
            text = _strip_keys(text, {"gateway.multiplex_profiles"})
            text = _ensure_terminal_cwd(text, self.workspace_root / target_dir.name)
            config_path.write_text(text, encoding="utf-8")
        env_path = staging / ".env"
        if env_path.is_file():
            env_path.write_text(_rewrite_env(env_path.read_text(encoding="utf-8")), encoding="utf-8")
            os.chmod(env_path, 0o600)
        else:
            _atomic_write(env_path, "", mode=0o600)

    def _path_mapping(
        self, source_dir: Path, target_dir: Path, config_text: str
    ) -> list[tuple[str, str]]:
        """Every source path a cloned config may name, and where it belongs in the new profile.

        The profile directory itself is replaced first: it catches the price book, plans and
        any other file the payload keeps inside the profile. The three plugin locations are
        then read out of the copied config, so an operator who moved their store to another
        disk is still copied to the new profile's own store rather than sharing it.
        """
        target_workspace = self.workspace_root / target_dir.name
        target_store = target_dir / "records.db"
        target_packs = target_dir / "packs"
        target_pricebook = target_dir / "pricebook.json"
        source_store = self.store_for(source_dir.name) if source_dir.parent == self.profiles_root else self.store_path
        source_attachments = (
            self.attachments_for(source_dir.name)
            if source_dir.parent == self.profiles_root
            else self.attachments_dir
        )
        mapping: list[tuple[str, str]] = [
            (str(source_dir), str(target_dir)),
            (str(source_store), str(target_store)),
        ]
        if source_attachments is not None:
            mapping.append((str(source_attachments), str(target_dir / "attachments")))
        source_workspace = self._terminal_cwd(source_dir / "config.yaml")
        if source_workspace is not None and str(source_workspace) != str(source_dir):
            mapping.append((str(source_workspace), str(target_workspace)))
        target_by_key = {
            "store_path": str(target_store),
            "packs_dir": str(target_packs),
            "pricebook_path": str(target_pricebook),
            "catalogue_path": str(target_pricebook),
            "cwd": str(target_workspace),
        }
        section = ""
        for line in config_text.splitlines():
            top = _TOP_LEVEL.match(line)
            if top:
                section = top.group("key")
                continue
            found = _SCALAR_LINE.match(line)
            if not found or found.group("key") not in PATH_KEYS:
                continue
            key = found.group("key")
            if key == "cwd" and section != "terminal":
                continue
            raw = _unquote(found.group("value"))
            if raw and raw not in {old for old, _new in mapping}:
                mapping.append((raw, target_by_key[key]))
        return mapping

    def _seed_workspace(self, source_name: str, name: str) -> None:
        """Give a new profile its own working directory with the product's operating guide.

        The container is copied only as far as ``AGENTS.md``: another profile's working files
        are its business, not this one's.
        """
        target = self.workspace_root / name
        target.mkdir(parents=True, exist_ok=True)
        guide = self.workspace_for(source_name) / "AGENTS.md"
        if not guide.is_file():
            fallback = self.repo_root / "distribution" / "workspace" / "AGENTS.md"
            guide = fallback if fallback.is_file() else guide
        if guide.is_file():
            shutil.copy2(guide, target / "AGENTS.md")

    # -- rename / delete -------------------------------------------------

    def rename(self, old: Any, new: Any) -> ProfileInfo:
        source_name = self.require(old)
        target_name = self.validate(new)
        if source_name == self.install_name:
            raise ProfileError(
                409,
                "The installed profile is not renamed here. Change its display name instead.",
                "install_profile",
            )
        if source_name == target_name:
            return self.info(source_name)
        old_dir = self.path_for(source_name)
        new_dir = self.path_for(target_name)
        old_workspace = self.workspace_for(source_name)
        new_workspace = self.workspace_root / target_name
        with self._lock:
            if self._is_deleted(target_name):
                self._clear_deleted(target_name)
                _rmtree(new_dir)
            if new_dir.exists():
                raise ProfileError(409, f"a profile named “{target_name}” already exists", "exists")
            os.rename(old_dir, new_dir)
            try:
                config_path = new_dir / "config.yaml"
                if config_path.is_file():
                    text = config_path.read_text(encoding="utf-8")
                    mapping = [
                        (str(old_dir), str(new_dir)),
                        (self.store_for(source_name).as_posix(), str(self.store_for(target_name))),
                        (str(old_workspace), str(new_workspace)),
                    ]
                    config_path.write_text(_rewrite_paths(text, mapping), encoding="utf-8")
                if old_workspace.is_dir() and old_workspace.parent == self.workspace_root:
                    if not new_workspace.exists():
                        os.rename(old_workspace, new_workspace)
                meta = self.meta(target_name)
                previous = list(meta.get("previous_names") or [])
                if source_name not in previous:
                    previous.append(source_name)
                meta["previous_names"] = previous
                _atomic_write(
                    new_dir / META_NAME,
                    json.dumps(meta, indent=2) + "\n",
                    mode=0o600,
                )
                # A running multiplexer still has the old name in its served set until the next
                # rescan. The tombstone is what keeps a cron/heartbeat shell it writes into the
                # old path from becoming a profile again — and what tells the engine to drop it.
                self._mark_deleted(source_name)
            except BaseException:
                # Put the directory back: a half-renamed profile is worse than a refused one.
                with _suppress_oserror():
                    os.rename(new_dir, old_dir)
                with _suppress_oserror():
                    if new_workspace.is_dir() and not old_workspace.exists():
                        os.rename(new_workspace, old_workspace)
                with _suppress_oserror():
                    self._clear_deleted(source_name)
                raise
            if self._read_active_name() == source_name:
                self.set_active(target_name)
        return self.info(target_name)

    def delete(self, name: Any) -> None:
        value = self.require(name)
        if value == self.install_name:
            raise ProfileError(409, "The installed profile cannot be deleted.", "install_profile")
        if value == self.active():
            raise ProfileError(
                409,
                f"“{value}” is the selected profile. Switch to another profile before deleting it.",
                "active_profile",
            )
        path = self.path_for(value)
        workspace = self.workspace_for(value)
        with self._lock:
            # Mark first. A multiplexer that still has this profile in memory can write a cron
            # heartbeat or a state database between the rmtree and its next rescan; the marker
            # makes that ghost unservable and invisible to this registry.
            self._mark_deleted(value)
            _rmtree(path)
            # A quick second pass covers the writes that landed during the first one. The
            # marker stays: the next rescan reads it and drops the profile from the served set.
            _rmtree(path)
            # Only a workspace this manager created is removed. An operator who pointed the
            # profile somewhere else keeps their directory.
            if workspace.parent == self.workspace_root:
                _rmtree(workspace)

    def _read_active_name(self) -> str | None:
        try:
            raw = self._active_path.read_text(encoding="utf-8-sig").strip()
        except OSError:
            return None
        return raw or None


# ------------------------------------------------------------------- text helpers


def _unquote(value: str) -> str:
    """A YAML scalar as a string: enough for the paths and quoted labels in a profile."""
    text = value.split(" #", 1)[0].strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        quote = text[0]
        body = text[1:-1]
        if quote == "'":
            return body.replace("''", "'")
        try:
            return json.loads(text)
        except ValueError:
            return body
    return text


def _scalar_path(config_path: Path, key: str) -> Path | None:
    """The first absolute path a config names for *key*, resolved; None when absent."""
    try:
        lines = config_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        found = _SCALAR_LINE.match(line)
        if not found or found.group("key") != key:
            continue
        raw = _unquote(found.group("value"))
        if raw and os.path.isabs(os.path.expanduser(os.path.expandvars(raw))):
            return Path(os.path.expanduser(os.path.expandvars(raw))).resolve()
    return None


def _quote(value: str) -> str:
    """A path as a YAML double-quoted scalar when it needs one, bare otherwise."""
    if re.match(r"^[A-Za-z0-9_./~+-]+$", value):
        return value
    return json.dumps(value)


def _rewrite_paths(text: str, mapping: Iterable[tuple[str, str]]) -> str:
    """Replace exact path strings, longest first so one path cannot eat another's prefix."""
    result = text
    for old, new in sorted(mapping, key=lambda pair: len(pair[0]), reverse=True):
        if old and old != new:
            result = result.replace(old, new)
    # A value that was quoted stays quoted; a replaced bare path stays bare. The replacement
    # above cannot produce a malformed YAML scalar because these are path strings, but a path
    # with a space would once it is unquoted. Re-quote only the value of a scalar line whose
    # text changed and is not already quoted.
    return _requote_changed_values(text, result)


def _requote_changed_values(before: str, after: str) -> str:
    """Best-effort fidelity for a bare value that now needs quoting (a space in a path)."""
    if before == after or " " not in after:
        return after
    original = before.splitlines()
    updated = after.splitlines()
    if len(original) != len(updated):
        return after
    fixed: list[str] = []
    for old_line, new_line in zip(original, updated):
        if old_line == new_line:
            fixed.append(new_line)
            continue
        match = _SCALAR_LINE.match(new_line)
        if not match:
            fixed.append(new_line)
            continue
        raw = match.group("value")
        if not raw or raw[0] in "\"'[]{}|>":
            fixed.append(new_line)
            continue
        fixed.append(f"{match.group('indent')}{match.group('key')}: {_quote(raw)}")
    return "\n".join(fixed) + ("\n" if after.endswith("\n") else "")


def _remove_standalone(text: str) -> str:
    """Drop ``gateway.standalone: true`` from a cloned config.

    ``standalone`` is the engine's per-profile opt-out from the one-gateway-per-host topology.
    Carrying it into a new profile would make the multiplexer skip that profile — the exact
    opposite of what creating one is for. When the key was the block's only content the empty
    ``gateway:`` line goes too, rather than leaving a null block for a reader to wonder about.
    """
    lines = text.splitlines()
    out: list[str] = []
    index = 0
    while index < len(lines):
        top = _TOP_LEVEL.match(lines[index])
        if not top or top.group("key") != "gateway":
            out.append(lines[index])
            index += 1
            continue
        end = index + 1
        while end < len(lines):
            candidate = lines[end]
            # A top-level line (including a flush-left comment) ends the block. An indented
            # comment belongs to it.
            if candidate and not candidate[0].isspace():
                break
            end += 1
        block = lines[index + 1 : end]
        kept = [
            line
            for line in block
            if not (
                (found := _SCALAR_LINE.match(line)) and found.group("key") == "standalone"
            )
        ]
        has_content = any(
            line.strip() and not line.lstrip().startswith("#") for line in kept
        )
        if has_content:
            out.append(lines[index])
            out.extend(kept)
        # Otherwise the only content was `standalone`: the parent key goes with it.
        index = end
    return "\n".join(out) + ("\n" if text.endswith("\n") and out else "")


def _strip_keys(text: str, dotted: set[str]) -> str:
    """Remove scalar keys named by dotted path, leaving every other line untouched."""
    if not dotted:
        return text
    out: list[str] = []
    section = ""
    for line in text.splitlines():
        top = _TOP_LEVEL.match(line)
        if top:
            section = top.group("key")
            if top.group("key") in dotted:
                continue
            out.append(line)
            continue
        found = _SCALAR_LINE.match(line)
        if found and f"{section}.{found.group('key')}" in dotted:
            continue
        out.append(line)
    return "\n".join(out) + ("\n" if text.endswith("\n") and out else "")


def _ensure_terminal_cwd(text: str, workspace: Path) -> str:
    """Make sure a cloned config tells the engine where to work.

    The workspace is where the agent writes the files a preview will read, and the preview
    jail refuses ``.hermes-dev`` — so a profile with no ``terminal.cwd`` writes into its
    profile directory and the app cannot open the result. A source config that omits the key
    gets one added here; a block that already has it was rewritten by the path mapping above.
    """
    lines = text.splitlines()
    section = ""
    terminal_line = -1
    has_cwd = False
    for index, line in enumerate(lines):
        top = _TOP_LEVEL.match(line)
        if top:
            section = top.group("key")
            if section == "terminal":
                terminal_line = index
            continue
        found = _SCALAR_LINE.match(line)
        if found and section == "terminal" and found.group("key") == "cwd":
            has_cwd = True
    if has_cwd:
        return text
    rendered = f"  cwd: {_quote(str(workspace))}"
    if terminal_line >= 0:
        lines.insert(terminal_line + 1, rendered)
    else:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend(["terminal:", rendered])
    return "\n".join(lines) + "\n"


def _rewrite_scalar_keys(
    text: str, values: dict[str, str], *, cwd: str | None = None
) -> str:
    """Set the named scalar keys, wherever they appear, preserving indentation and comments.

    These are the plugin-facing paths (``store_path``, ``packs_dir``, the price book and
    ``terminal.cwd``). A clone must own them even when the source wrote a relative path or a
    path into a directory that is not part of the copy.
    """
    out: list[str] = []
    section = ""
    for line in text.splitlines():
        top = _TOP_LEVEL.match(line)
        if top:
            section = top.group("key")
            out.append(line)
            continue
        found = _SCALAR_LINE.match(line)
        if not found:
            out.append(line)
            continue
        key = found.group("key")
        if key in values:
            out.append(f"{found.group('indent')}{key}: {_quote(values[key])}")
            continue
        if key == "cwd" and section == "terminal" and cwd is not None:
            out.append(f"{found.group('indent')}cwd: {_quote(cwd)}")
            continue
        out.append(line)
    return "\n".join(out) + ("\n" if text.endswith("\n") and out else "")


def _rewrite_env(text: str) -> str:
    """A cloned profile keeps its credentials but not the port a shared listener owns."""
    out: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in STRIPPED_ENV_KEYS:
                continue
        out.append(line)
    return "\n".join(out) + ("\n" if text.endswith("\n") and out else "")


class _suppress_oserror:
    """Tiny context manager so a rollback's own failure cannot mask the original one."""

    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type, exc, tb) -> bool:
        return exc_type is not None and issubclass(exc_type, OSError)
