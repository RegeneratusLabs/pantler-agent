"""The BFF — the front end's own backend.

Why it exists (the front-end design §3): the shell must not route a record read through
the agent. Listing what a pack holds has to be instant, deterministic and free, and the
engine's seam can be none of those things for a list.

It is **domain-neutral by construction**. It knows record *types*, never meanings: every
route below is generic over whatever the installed packs declare. If this file learns what an
invoice is, the architecture has failed in the same way the kernel would.

Three routes are engine-facing rather than domain-facing, because the engine offers no seam
for what they answer: `/api/settings` (no settings API over HTTP — `admin_config_rw: false`),
`/api/skills` (the engine's `GET /v1/skills` is broken at the pinned commit) and
`/api/learning` (memory, self-written skills and the curator are not on the seam at all). Each
reads the profile's own files instead; that work lives in `engine_settings.py`,
`skills_index.py` and `learning.py`, and this file only routes to it. All three are opt-in —
without `--profile-dir` they answer `available: false`.

Standard library only — ``http.server``, ``sqlite3``, ``json``. That keeps the BFF shippable
without a dependency story, and it is easy to swap for something else once the contract is
proven, because nothing here is clever.

Run:

    PYTHONPATH=core/src python app/server/pantler_server.py --port 8650

Settings additionally need the engine profile, which is opt-in because it grants file writes:

    … --profile-dir .hermes-dev/profiles/pantler
"""

from __future__ import annotations

import argparse
import base64
import functools
import hashlib
import hmac
import ipaddress
import json
import mimetypes
import os
import re
import socket
import sys
import threading
import traceback
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import parse_qs, unquote, urlparse

from capabilities import installed_plugins, load_capabilities
from connectors import ConnectorError, Connectors
from engine_settings import (
    APPLIES_LIVE,
    APPLIES_RESTART,
    REASONING_DISABLED,
    REASONING_EFFORT_KEY,
    REASONING_EFFORTS,
    WRITABLE_MODEL_KEYS,
    EngineProfile,
    SettingsError,
)
import job_runs
from learning import load_learning, load_ledger, session_changes, unavailable
from profiles import ProfileError, ProfileManager
from skills_index import load_skills
from previews import (
    HEAD_BYTES,
    FileRoots,
    PreviewError,
    byte_headers,
    describe_file,
    disposition_of,
    parse_range,
    read_bytes,
    snapshot_text,
)
from attachments import (
    MAX_FILE_BYTES,
    Attachment,
    AttachmentError,
    AttachmentStore,
    compose_input,
    fetch_url,
    select_for_turn,
)
from pantler_core import (
    PackError,
    PackRegistry,
    RecordBook,
    RecordBookError,
    Store,
    StoreError,
    load_packs,
)

MAX_BODY_BYTES = 1_000_000
DEFAULT_LIMIT = 50
MAX_LIMIT = 500
DEFAULT_ATTACHMENTS_KEEP_DAYS = 90

REPO_ROOT = Path(__file__).resolve().parents[2]

#: The toolsets that can run arbitrary code, reach any page or drive the machine itself. Turning
#: one **on** is a deliberate act rather than an accidental screen toggle, so a deployment with a
#: write token must present it (the internal security audit A19-CFG-8). The list is about the
#: nature of the capability, not about a shipped default: since 2026-10-19
#: `distribution/config.yaml` suppresses nothing, so these ship enabled and the guard only bites
#: when one is switched back on after the operator turned it off.
ESCAPE_HATCH_TOOLSETS = frozenset(
    {"browser", "terminal", "code_execution", "computer_use", "image_gen", "delegation"}
)


@functools.lru_cache(maxsize=1)
def _baseline_toolsets() -> frozenset[str]:
    """The toolset names the pinned engine reports, from the captured baseline.

    Empty when the file is absent or unreadable: a missing baseline must not become a reason the
    app cannot be configured.
    """
    path = REPO_ROOT / "baseline" / "pantler-toolsets.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return frozenset()
    data = payload.get("data")
    if not isinstance(data, list):
        return frozenset()
    return frozenset(
        str(entry.get("name"))
        for entry in data
        if isinstance(entry, dict) and entry.get("name")
    )


# ------------------------------------------------------------------- errors


class ApiError(Exception):
    """An error with a status the client can act on."""

    def __init__(self, status: int, message: str, code: str = "error"):
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code


class RawResponse:
    """A non-JSON reply. Only the attachment bytes need this, and they need it badly."""

    def __init__(self, status: int, body: bytes, content_type: str, headers: dict[str, str]):
        self.status = status
        self.body = body
        self.content_type = content_type
        self.headers = headers


# ------------------------------------------------------------------ routing


class Route:
    def __init__(
        self,
        method: str,
        pattern: str,
        handler: str,
        writes: bool = False,
        raw: bool = False,
        headers: tuple[str, ...] = (),
    ):
        self.method = method
        self.handler = handler
        self.writes = writes
        # ``raw``: the body is bytes, read by the handler's own cap rather than parsed as
        # JSON. That is what an upload is, and the engine's own artifact route does the same.
        self.raw = raw
        # Header names the handler needs. HTTP headers are latin-1, so anything with a
        # filename in it travels percent-encoded and is decoded in the handler.
        self.headers = headers
        self.regex = re.compile(f"^{pattern}$")

    def match(self, method: str, path: str) -> re.Match[str] | None:
        if method != self.method:
            return None
        return self.regex.match(path)


ROUTES: tuple[Route, ...] = (
    Route("GET", r"/api/health", "health"),
    # Profiles: the businesses this installation can run. They are engine profiles, and the
    # routes are the shell's own — the engine's profile CRUD lives on the dashboard server,
    # which is not on the surface this app uses (the design notes §2, the front-end design §2).
    # `/active` is declared before the generic name route: this table is matched in order.
    Route("GET", r"/api/profiles", "profiles_list"),
    Route("POST", r"/api/profiles", "create_profile", writes=True),
    Route("GET", r"/api/profiles/active", "active_profile"),
    Route("POST", r"/api/profiles/active", "set_active_profile", writes=True),
    Route(
        "PATCH",
        r"/api/profiles/(?P<name>[a-z0-9][a-z0-9_-]{0,63})",
        "update_profile",
        writes=True,
    ),
    Route(
        "DELETE",
        r"/api/profiles/(?P<name>[a-z0-9][a-z0-9_-]{0,63})",
        "delete_profile",
        writes=True,
    ),
    Route("GET", r"/api/packs", "list_packs"),
    Route("GET", r"/api/skills", "list_skills"),
    # The capability registry: every switchable thing in this profile, in one shape, plus the
    # one write path that flips any of them (the internal capability plan §2).
    Route("GET", r"/api/capabilities", "list_capabilities"),
    Route("PUT", r"/api/capabilities/(?P<id>[^/]+)", "set_capability", writes=True),
    # Composio connectors (the Composio notes, rail C). The grid is read from Composio, so these
    # routes are the only place the screen's connected state comes from — there is no model call
    # and no agent in the loop. The execute route is called by the first-party connectors plugin,
    # not by the browser; the write guard still applies, and the plugin sends its own origin.
    Route("GET", r"/api/connectors", "list_connectors"),
    Route("GET", r"/api/connectors/(?P<id>[a-z0-9][a-z0-9_-]{0,63})/tools", "list_connector_tools"),
    Route("POST", r"/api/connectors/(?P<id>[a-z0-9][a-z0-9_-]{0,63})/connect", "connect_connector", writes=True),
    Route("POST", r"/api/connectors/(?P<id>[a-z0-9][a-z0-9_-]{0,63})/execute", "execute_connector", writes=True),
    Route("DELETE", r"/api/connectors/(?P<id>[a-z0-9][a-z0-9_-]{0,63})", "disconnect_connector", writes=True),
    # What the assistant has learned: its memory, the skills it wrote for itself, and the
    # ledger that attributes a skill write to the conversation that caused it. Read-only by
    # construction — see learning.py.
    Route("GET", r"/api/learning", "learning"),
    Route("GET", r"/api/learning/session/(?P<session>[^/]+)", "session_learning"),
    # A scheduled job's saved output. The gateway offers `/api/jobs` but no per-run read, and
    # the dashboard's `/api/cron/jobs/{id}/runs` is not the seam (the front-end design §3).
    # These two read the active profile's own `cron/output/<job_id>/` directory, read-only and
    # scoped by the same `X-Pantler-Profile` rule as every other route here (job_runs.py).
    Route("GET", r"/api/jobs/(?P<job_id>[a-f0-9]{12})/runs", "list_job_runs"),
    Route(
        "GET",
        r"/api/jobs/(?P<job_id>[a-f0-9]{12})/runs/(?P<run_id>\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})",
        "get_job_run",
    ),
    Route("GET", r"/api/records/(?P<type>[A-Za-z0-9_]+)", "list_records"),
    Route("POST", r"/api/records/(?P<type>[A-Za-z0-9_]+)", "create_record", writes=True),
    Route("GET", r"/api/records/(?P<type>[A-Za-z0-9_]+)/(?P<id>[^/]+)", "get_record"),
    # PATCH merges the fields it is given; PUT replaces the record's data. Two verbs, two
    # meanings, and neither of them surprising (the internal audit BFF-1). All four
    # mutations are in the write-guarded set: a record *is* the operator's data, and the tailnet
    # tier reaches it through the dev proxy, which arrives looking local — the guard's
    # same-origin half is what keeps a page the operator is merely visiting out
    # (the internal security audit A19-EX-3).
    Route("PATCH", r"/api/records/(?P<type>[A-Za-z0-9_]+)/(?P<id>[^/]+)", "patch_record", writes=True),
    Route("PUT", r"/api/records/(?P<type>[A-Za-z0-9_]+)/(?P<id>[^/]+)", "replace_record", writes=True),
    Route("DELETE", r"/api/records/(?P<type>[A-Za-z0-9_]+)/(?P<id>[^/]+)", "delete_record", writes=True),
    # Attachments. Loopback-and-this-origin, like the other writes: the phone tier is the point
    # of the tailnet bind, and a photo taken on a phone is the most likely attachment of all —
    # but the phone reaches this server *through the app*, so it arrives with the app's own
    # origin and this guard costs it nothing (the internal security audit A19-EX-3).
    Route("GET", r"/api/attachments", "list_attachments"),
    Route("POST", r"/api/attachments", "upload_attachment", writes=True, raw=True,
          headers=("X-Attachment-Session", "X-Attachment-Name", "X-Attachment-Relpath",
                   "X-Attachment-Folder", "Content-Type")),
    Route("POST", r"/api/attachments/url", "attach_url", writes=True),
    Route("POST", r"/api/attachments/context", "compose_turn"),
    Route("GET", r"/api/attachments/(?P<id>[^/]+)", "get_attachment"),
    Route("DELETE", r"/api/attachments/(?P<id>[^/]+)", "delete_attachment", writes=True),
    Route("GET", r"/api/attachments/(?P<id>[^/]+)/raw", "get_attachment_raw", headers=("Range",)),
    # Previews (the file-preview design). `meta` is what lets the shell choose a renderer before
    # it moves a byte; `raw` is the one path-addressed door, and `previews.py` owns its jail.
    # Neither is loopback-only, so the reads stay available to the phone tier; the network
    # remains the access control for them, and `A19-EX-5`/`A19-EX-7` are what narrowed the jail.
    Route("GET", r"/api/files/meta", "file_meta"),
    Route("GET", r"/api/attachments/(?P<id>[^/]+)/meta", "attachment_meta"),
    Route("GET", r"/api/files/raw", "file_raw", headers=("Range",)),
    # One fetch, text only, for the page that refuses to be framed. It is a snapshot, not a
    # proxy: nothing of the site is ever served from our origin.
    Route("POST", r"/api/urls/snapshot", "url_snapshot"),
    # Engine settings. Reads are free; writes touch the engine's own files and are the only
    # routes in this server that are refused to non-local callers.
    Route("GET", r"/api/settings", "settings"),
    Route("PUT", r"/api/settings/model", "set_model", writes=True),
    Route("PUT", r"/api/settings/reasoning", "set_reasoning_effort", writes=True),
    Route("PUT", r"/api/settings/toolsets", "set_disabled_toolsets", writes=True),
    Route("PUT", r"/api/settings/skills", "set_disabled_skills", writes=True),
    Route("PUT", r"/api/settings/keys/(?P<name>[A-Za-z_][A-Za-z0-9_]*)", "set_key", writes=True),
    Route("DELETE", r"/api/settings/keys/(?P<name>[A-Za-z_][A-Za-z0-9_]*)", "clear_key", writes=True),
)


def is_loopback(host: str) -> bool:
    """True for a loopback peer, including an IPv4-mapped IPv6 one."""
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return address.is_loopback


def host_name(value: str) -> str:
    """The host part of a `host:port`, a `scheme://host:port` or a bare host.

    The port is dropped and the name is lower-cased, because that is the unit the trust checks
    compare on. An IPv6 literal keeps its brackets off: `urlparse` does that for us.
    """
    text = (value or "").strip()
    if not text:
        return ""
    try:
        parsed = urlparse(text if "//" in text else f"//{text}")
    except ValueError:
        return ""
    return (parsed.hostname or "").lower().rstrip(".")


@functools.lru_cache(maxsize=1)
def local_addresses() -> frozenset[str]:
    """Every name this machine answers on that can be discovered without asking the network.

    This is the first half of what makes a Host header trustworthy: not that it equals whatever
    the caller sent (which is what DNS rebinding defeats — the internal security audit
    A19-EX-1), but that it names this machine. `is_local_address` is the authoritative half for an
    IP literal, because `getaddrinfo(gethostname())` misses addresses that are not in the host's
    own name resolution — on this machine, both the LAN and the tailnet address.
    """
    names: set[str] = {"127.0.0.1", "localhost", "::1", "0.0.0.0", "::"}
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None):
            names.add(str(info[4][0]).lower())
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo("localhost", None):
            names.add(str(info[4][0]).lower())
    except OSError:
        pass
    return frozenset(names)


def is_local_address(name: str) -> bool:
    """Whether `name` is an address this machine actually holds.

    Asked by *binding* to it: a socket can bind to an address only if the machine owns it, which
    is the definition, and it needs no interface enumeration, no subprocess and no platform
    branch. A UDP socket sends nothing by binding, so this is a local question with a local
    answer — a Host naming `192.168.1.100` is this machine; one naming `100.64.0.9` on a machine
    without that interface is not.
    """
    try:
        address = ipaddress.ip_address(name)
    except ValueError:
        return False
    family = socket.AF_INET6 if address.version == 6 else socket.AF_INET
    target: tuple[Any, ...] = (name, 0, 0, 0) if family == socket.AF_INET6 else (name, 0)
    try:
        with socket.socket(family, socket.SOCK_DGRAM) as probe:
            probe.bind(target)
    except OSError:
        return False
    return True


def host_of(url: str) -> str:
    """The `host:port` of a URL, lower-cased, or "" when it is not one."""
    try:
        return urlparse(url).netloc.lower()
    except ValueError:
        return ""


def origin_of(url: str) -> str:
    """The scheme://host:port of a URL, or "" — the shape a browser's `Origin` has."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return ""
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def hosts_from_env(name: str = "PANTLER_ALLOWED_HOSTS") -> list[str] | None:
    """The names a deployment says the app is reached by, from one comma-separated variable.

    The dev server already names the tailnet front door with ``PANTLER_ALLOWED_HOSTS``; the
    BFF reads the same variable so one declaration covers both processes. Only exact names
    are used. A leading-dot pattern is Vite's spelling for a whole-domain wildcard, which is
    never trusted here (the internal security audit A19-EX-1), so such an entry is
    dropped rather than quietly honoured.
    """
    raw = os.environ.get(name, "")
    names = [part.strip() for part in raw.split(",")]
    kept = [value for value in names if value and not value.startswith(".")]
    return kept or None


class Bff:
    """The application, independent of HTTP so it can be tested without a socket."""

    def __init__(
        self,
        store: Store,
        registry: PackRegistry,
        profile: EngineProfile | None = None,
        attachments: AttachmentStore | None = None,
        files: FileRoots | None = None,
        connectors: Connectors | None = None,
    ):
        self.store = store
        self.registry = registry
        # The one implementation of "make a record", over the store and the packs this server
        # already holds. The engine-side tools use the same class, which is what makes a spray
        # recorded in a conversation and one typed into a screen the same record rather than
        # two implementations that agree today (the internal audit K15).
        self.book = RecordBook.over(store, registry)
        # Where the packs were read from, and what the directory looked like then. `None` means
        # "loaded once, never checked again" — what `build_bff` callers that pass a registry
        # directly get, and what the tests use.
        self.packs_dir: Path | None = None
        self.custom_packs_dir: Path | None = None
        self._packs_stamp: tuple[tuple[str, int, int], ...] = ()
        self._packs_lock = threading.Lock()
        self.packs_error: str | None = None
        self.profile = profile
        self.attachments = attachments
        # The connector service is built from the profile on first use; tests inject a fake so a
        # route test never opens a socket to Composio.
        self.connectors = connectors
        self._connectors_service: Connectors | None = None
        # The directories a preview may read a path from. Empty is a real answer: the route then
        # refuses with a sentence rather than guessing at $HOME (the file-preview design §4 D6).
        self.files = files or FileRoots()
        # Set by any settings write. The engine reads config.yaml and .env at startup, so a
        # saved change is inert until it restarts — and saying so is the honest half of the UI.
        self.restart_required = False

    # -------------------------------------------------------------- routes

    def watch_packs(self, packs_dir: str | Path, custom_packs_dir: str | Path | None = None) -> None:
        """Re-read the pack directories when their manifests change.

        The registry was built once at boot, so a pack added while the server ran was invisible:
        `/api/health` reported `packs: ["example"]` on a server started before `farm` and `trade`
        existed, with nothing saying the list was stale
        (the internal audit BFF-15). The manifests are a handful of small files, so the
        check is a stat per pack per request to the two routes that read the registry.

        `custom_packs_dir` is the operator's own tree, loaded alongside the shipped one and marked
        `custom` so the shell can label it. A missing directory is an empty custom tree.
        """
        self.packs_dir = Path(packs_dir)
        self.custom_packs_dir = Path(custom_packs_dir) if custom_packs_dir else None
        # An empty stamp is never equal to a real one, so the first read re-loads: the registry
        # this call replaces is whatever the constructor loaded, and that is the point — after
        # `watch_packs`, the registry always matches the directory.
        self._packs_stamp = ()
        self._reload_packs_if_changed()

    def _pack_stamp(self) -> tuple[tuple[str, int, int], ...]:
        """Every manifest's path, mtime and size: the identity of the loaded packs.

        Size as well as mtime: a rewrite inside the filesystem's timestamp tick is otherwise
        invisible, and the suite caught exactly that — two writes in one tick, the second one
        broken, and the registry kept serving as though nothing had changed.
        """
        roots = [root for root in (self.packs_dir, self.custom_packs_dir) if root is not None]
        if not roots:
            return ()
        try:
            return tuple(
                sorted(
                    (str(path), path.stat().st_mtime_ns, path.stat().st_size)
                    for root in roots
                    for path in root.glob("*/pack.toml")
                )
            )
        except OSError:
            return ()

    def _reload_packs_if_changed(self) -> None:
        if self.packs_dir is None:
            return
        stamp = self._pack_stamp()
        if stamp == self._packs_stamp:
            return
        with self._packs_lock:
            # Re-checked under the lock: two threads noticing the same change should load once.
            if stamp == self._packs_stamp:
                return
            try:
                registry = load_packs(self.packs_dir, custom_dir=self.custom_packs_dir)
            except Exception as exc:
                # A pack being edited in place can be invalid for a moment, and the previous
                # registry keeps serving while the reason is reported rather than swallowed.
                # `Exception`, not `PackError`: the parser now refuses a wrong-shaped manifest
                # with a `PackError` of its own, so anything reaching here is a bug — and a bug
                # in a pack file must not take every route down with it
                # (the internal security audit A19-KERN-3).
                self.packs_error = f"{self.packs_dir}: {exc}"
                self._packs_stamp = stamp
                return
            self.registry = registry
            self.book = RecordBook.over(self.store, registry)
            self.packs_error = None
            self._packs_stamp = stamp

    def health(self, _params: dict[str, Any]) -> tuple[int, Any]:
        self._reload_packs_if_changed()
        payload = {
            "status": "ok",
            "store": {"schema_version": self.store.schema_version},
            "packs": [p.id for p in self.registry.packs],
            "record_types": [r.type for r in self.registry.record_types],
        }
        if self.packs_error:
            payload["packs_error"] = self.packs_error
        return HTTPStatus.OK, payload

    def list_packs(self, _params: dict[str, Any]) -> tuple[int, Any]:
        # Exactly what the shell renders from. No pack-specific code on either side.
        self._reload_packs_if_changed()
        return HTTPStatus.OK, {"data": self.registry.to_dict()}

    def list_skills(self, _params: dict[str, Any]) -> tuple[int, Any]:
        """The profile's skills, read from its files.

        Not a route we would choose: the engine's own `GET /v1/skills` answers 500 at the pinned
        commit (`skills_index.py` records exactly why). Without a profile there is no skills
        directory to read, and that is a normal answer rather than a failure.
        """
        if self.profile is None or not self.profile.available:
            return HTTPStatus.OK, {
                "available": False,
                "reason": (
                    "No engine profile is configured for this server, so its skills cannot be "
                    "read. Start the BFF with --profile-dir <profiles/NAME>."
                ),
                "data": [],
            }
        return HTTPStatus.OK, {
            "available": True,
            "profile": self.profile.name,
            "data": self._skills(),
        }

    def list_job_runs(self, params: dict[str, Any]) -> tuple[int, Any]:
        """The runs the engine kept for one scheduled job (`job_runs.py`).

        A missing profile is a normal answer, not a failure — the same contract as `/api/skills`.
        A job that has never run has no directory, and that is an empty list rather than a 404.
        """
        job_id = str(params.get("job_id", ""))
        if self.profile is None or not self.profile.available:
            return HTTPStatus.OK, {
                "available": False,
                "reason": (
                    "No engine profile is configured for this server, so a job's output cannot "
                    "be read. Start the BFF with --profile-dir <profiles/NAME>."
                ),
                "runs": [],
            }
        try:
            runs = job_runs.list_runs(self.profile.dir, job_id)
        except ValueError as exc:
            raise ApiError(HTTPStatus.BAD_REQUEST, str(exc), "bad_job_id") from exc
        return HTTPStatus.OK, {"available": True, "job_id": job_id, "runs": runs}

    def get_job_run(self, params: dict[str, Any]) -> tuple[int, Any]:
        """One run's saved markdown, capped. The engine prunes these, so a 404 is normal."""
        job_id = str(params.get("job_id", ""))
        run_id = str(params.get("run_id", ""))
        if self.profile is None or not self.profile.available:
            raise ApiError(
                HTTPStatus.NOT_FOUND,
                "this machine has no engine profile to read run output from",
                "not_found",
            )
        try:
            run = job_runs.read_run(self.profile.dir, job_id, run_id)
        except ValueError as exc:
            raise ApiError(HTTPStatus.BAD_REQUEST, str(exc), "bad_job_id") from exc
        except FileNotFoundError as exc:
            raise ApiError(HTTPStatus.NOT_FOUND, "that run is not kept any more", "not_found") from exc
        return HTTPStatus.OK, {"job_id": job_id, "run": run}

    def _active_environments(self) -> set[str]:
        """The `environments:` tags this profile is actually running in.

        One detection, three readers (`/api/skills`, `/api/capabilities` and `/api/learning`
        through the first): `environments: [kanban]` skills are offered only when the profile
        opted into the kanban toolset — the engine's own `_profile_has_kanban_toolset` check.
        """
        assert self.profile is not None
        return {"kanban"} if "kanban" in self.profile.opted_in_toolsets() else set()

    def _skills(self) -> list[dict[str, Any]]:
        """The profile's skills, exactly as `skills_index.load_skills` resolves them.

        One loader, two readers (`/api/skills` and `/api/learning`): a page that claimed a
        skill's provenance from a second, separately-resolved list could disagree with the
        screen that switches it on, and there would be no way to tell which was right.
        """
        assert self.profile is not None
        return load_skills(
            self.profile.dir,
            self.profile.disabled_skills(),
            active_environments=self._active_environments(),
        )

    # ----------------------------------------------------------- what it has learned

    def learning(self, _params: dict[str, Any]) -> tuple[int, Any]:
        """Everything this app can honestly say about the assistant's memory and its skills.

        Read from the profile's own files, for the reason `learning.py` argues at length: the
        engine's memory, curator and learning-graph surfaces are not on the seam pantler talks
        to. Without a profile this is `available: false` — a normal answer, never an empty one,
        because "it has learned nothing" is a different sentence from "we cannot see".
        """
        if self.profile is None or not self.profile.available:
            return HTTPStatus.OK, unavailable(
                "No engine profile is configured for this server, so what the assistant has "
                "learned cannot be read. Start the BFF with --profile-dir <profiles/NAME>."
            )
        return HTTPStatus.OK, load_learning(
            self.profile.dir,
            skills=self._skills(),
            config_text=self._config_text(),
        )

    def session_learning(self, params: dict[str, Any]) -> tuple[int, Any]:
        """What one conversation taught it — the engine's own attribution, or nothing.

        The attribution is `evidence.session_id` in the curator's ledger, written by the engine
        when the agent or the curator changes a skill. An empty list is the common and honest
        answer: most conversations change nothing.
        """
        if self.profile is None or not self.profile.available:
            return HTTPStatus.OK, unavailable(
                "No engine profile is configured for this server, so what a conversation "
                "taught the assistant cannot be read."
            )
        session = str(params.get("session") or "")
        return HTTPStatus.OK, {
            "available": True,
            "session": session,
            "data": session_changes(load_ledger(self.profile.dir), session),
        }

    def _config_text(self) -> str:
        assert self.profile is not None
        try:
            return self.profile.config_path.read_text(encoding="utf-8")
        except OSError:
            return ""


    def list_records(self, params: dict[str, Any]) -> tuple[int, Any]:
        record_type = self._record_type(params)
        limit = _bounded_int(params.get("limit"), DEFAULT_LIMIT, 1, MAX_LIMIT)
        offset = _bounded_int(params.get("offset"), 0, 0, sys.maxsize)
        order = params.get("order") or "updated_at DESC"
        try:
            records = self.store.list(record_type.type, limit=limit, offset=offset, order=order)
        except StoreError as exc:
            raise ApiError(HTTPStatus.BAD_REQUEST, str(exc), "bad_order") from exc
        return HTTPStatus.OK, {
            "data": [r.to_dict() for r in records],
            "total": self.store.count(record_type.type),
            "limit": limit,
            "offset": offset,
        }

    def get_record(self, params: dict[str, Any]) -> tuple[int, Any]:
        record_type = self._record_type(params)
        record = self.store.get(record_type.type, params["id"])
        if record is None:
            raise ApiError(HTTPStatus.NOT_FOUND, f"no {record_type.label} with id {params['id']}", "not_found")
        return HTTPStatus.OK, record.to_dict()

    def create_record(self, params: dict[str, Any]) -> tuple[int, Any]:
        """Write one record through the book, so a screen and a tool agree on what that means.

        The id is envelope, not data — it belongs to the store, not to the pack's declared
        fields, so the book takes it separately. A client that sends `id` in the body is
        understood rather than refused, because that is the natural thing to do.
        """
        record_type = self._record_type(params)
        body = dict(self._body(params))
        explicit_id = body.pop("id", None) or params.get("id")
        try:
            record = self.book.save(
                record_type.type,
                body,
                record_id=str(explicit_id) if explicit_id else None,
            )
        except RecordBookError as exc:
            raise self._book_error(exc) from exc
        return HTTPStatus.CREATED, record.to_dict()

    def patch_record(self, params: dict[str, Any]) -> tuple[int, Any]:
        """Change the fields named in the body and leave the rest alone.

        `PATCH` merges — that is what the verb means, and a client that sends one field means
        one field. It used to *replace* the record's data, so patching a title dropped every
        other field, and because a required field is validated, a one-field patch of a record
        with any required field was refused outright
        (the internal audit BFF-1). `PUT` is the replacing verb, below.
        """
        record_type = self._record_type(params)
        changes = dict(self._body(params))
        changes.pop("id", None)

        existing = self.store.get(record_type.type, params["id"])
        if existing is None:
            raise ApiError(
                HTTPStatus.NOT_FOUND,
                f"no {record_type.label} with id {params['id']}",
                "not_found",
            )
        return self._write_through_the_book(record_type.type, params["id"], {**existing.data, **changes})

    def replace_record(self, params: dict[str, Any]) -> tuple[int, Any]:
        """Replace a record's data outright, keeping its id and its created_at."""
        record_type = self._record_type(params)
        data = dict(self._body(params))
        data.pop("id", None)
        return self._write_through_the_book(record_type.type, params["id"], data)

    def _write_through_the_book(
        self, type_name: str, record_id: str, data: dict[str, Any]
    ) -> tuple[int, Any]:
        try:
            record = self.book.update(type_name, record_id, data)
        except RecordBookError as exc:
            raise self._book_error(exc) from exc
        return HTTPStatus.OK, record.to_dict()

    @staticmethod
    def _book_error(exc: RecordBookError) -> ApiError:
        """The book's refusal, as a status the client can act on.

        The book carries a `code` for exactly this: before, the BFF decided by re-running the
        validation itself, which is the duplication this removes
        (the internal audit K15).
        """
        status = {
            "unknown_type": HTTPStatus.NOT_FOUND,
            "not_found": HTTPStatus.NOT_FOUND,
            "invalid": HTTPStatus.UNPROCESSABLE_ENTITY,
            "conflict": HTTPStatus.CONFLICT,
        }.get(exc.code, HTTPStatus.INTERNAL_SERVER_ERROR)
        code = {
            "unknown_type": "unknown_record_type",
            "invalid": "invalid_record",
            "conflict": "already_exists",
        }.get(exc.code, exc.code)
        return ApiError(status, exc.message, code)

    def delete_record(self, params: dict[str, Any]) -> tuple[int, Any]:
        record_type = self._record_type(params)
        if not self.book.delete(record_type.type, params["id"]):
            raise ApiError(HTTPStatus.NOT_FOUND, f"no {record_type.label} with id {params['id']}", "not_found")
        return HTTPStatus.NO_CONTENT, None

    # ---------------------------------------------------------- attachments
    #
    # The engine will not carry a file for us (the attachment design §2), so the BFF writes the
    # bytes to disk beside the engine and composes a turn that names the paths. Upload happens
    # when the file is chosen, not when Send is pressed: that is what lets a chip say
    # "uploading" or "too large" before the operator has committed to anything.

    def upload_attachment(self, params: dict[str, Any]) -> tuple[int, Any]:
        """One raw body, one file. Headers carry the metadata; names are percent-encoded
        because HTTP headers are latin-1 and an operator's file names are not."""
        store = self._attachments()
        headers = params.get("headers") or {}
        session = unquote(headers.get("X-Attachment-Session", ""))
        name = unquote(headers.get("X-Attachment-Name", ""))
        rel_path = unquote(headers.get("X-Attachment-Relpath", "")) or None
        folder_token = headers.get("X-Attachment-Folder") or None
        if not name:
            raise ApiError(HTTPStatus.BAD_REQUEST, "an X-Attachment-Name header is required", "bad_body")

        try:
            record = store.save_bytes(
                session,
                name,
                params.get("body_bytes") or b"",
                mime_hint=headers.get("Content-Type", ""),
                rel_path=rel_path,
                folder_token=folder_token,
            )
        except AttachmentError as exc:
            raise self._attachment_error(exc) from exc
        return HTTPStatus.CREATED, record.to_dict()

    def attach_url(self, params: dict[str, Any]) -> tuple[int, Any]:
        store = self._attachments()
        body = self._body(params)
        url = body.get("url")
        if not isinstance(url, str) or not url.strip():
            raise ApiError(HTTPStatus.BAD_REQUEST, "a string `url` is required", "bad_body")
        try:
            record = store.save_url(str(body.get("session") or ""), url)
        except AttachmentError as exc:
            raise self._attachment_error(exc) from exc
        return HTTPStatus.CREATED, record.to_dict()

    def list_attachments(self, params: dict[str, Any]) -> tuple[int, Any]:
        store = self._attachments()
        session = str(params.get("session") or "")
        try:
            records = store.list(session)
        except AttachmentError as exc:
            raise self._attachment_error(exc) from exc
        return HTTPStatus.OK, {"data": [record.to_dict() for record in records]}

    def get_attachment(self, params: dict[str, Any]) -> tuple[int, Any]:
        return HTTPStatus.OK, self._attachment(params["id"]).to_dict()

    def delete_attachment(self, params: dict[str, Any]) -> tuple[int, Any]:
        store = self._attachments()
        try:
            store.delete(params["id"])
        except AttachmentError as exc:
            raise self._attachment_error(exc) from exc
        # Idempotent on purpose: a chip removed twice is not an error worth a dialog.
        return HTTPStatus.NO_CONTENT, None

    def get_attachment_raw(self, params: dict[str, Any]) -> tuple[int, Any]:
        """The stored bytes, served as data rather than as a page.

        The content type is the security decision here, not a detail. Only two families are
        served with their own type — a raster image, and a PDF whose signature agrees with what
        its name and mime claim — and everything else, an uploaded SVG or HTML above all, goes
        out as an octet-stream with a download disposition, because a file that a browser renders
        inline would be script running on this origin (the attachment design §6,
        the file-preview design §4 D5).

        A `Range` is the one thing a preview adds to the response: a PDF viewer asks for byte
        ranges, and a 25 MB file should not have to cross the wire to show its first page.
        """
        store = self._attachments()
        record = self._attachment(params["id"])
        try:
            data = store.read(record)
        except AttachmentError as exc:
            raise self._attachment_error(exc) from exc

        content_type, disposition = disposition_of(record.mime, record.name, data[:HEAD_BYTES])
        # The tuple's status is the route's; the bytes' own status lives on the response, which
        # is what lets a range answer 206 through the same return path as a 200.
        return HTTPStatus.OK, _byte_response(
            name=record.name,
            data=data,
            content_type=content_type,
            disposition=disposition,
            range_header=_range_header(params),
        )

    def compose_turn(self, params: dict[str, Any]) -> tuple[int, Any]:
        """The engine input for a turn: the operator's words plus what they attached.

        Composing here rather than in the browser keeps the paths, the inlining rules and the
        caps in one testable place — and the format is frozen, because the shell parses it
        back out to redraw the chips after a reload (the attachment design §4).
        """
        store = self._attachments()
        body = self._body(params)
        session = str(body.get("session") or "")
        text = body.get("text")
        if text is not None and not isinstance(text, str):
            raise ApiError(HTTPStatus.BAD_REQUEST, "`text` must be a string", "bad_body")

        ids = body.get("ids") or []
        if not isinstance(ids, list):
            raise ApiError(HTTPStatus.BAD_REQUEST, "`ids` must be a list", "bad_body")

        records: list[Attachment] = []
        for attachment_id in ids:
            record = self._attachment(str(attachment_id))
            # A session's attachments are its own. This is not a security boundary so much as
            # a correctness one: a stale browser tab must not attach another conversation's
            # files to this turn.
            if record.session != session:
                raise ApiError(
                    HTTPStatus.NOT_FOUND,
                    f"{attachment_id} does not belong to this conversation",
                    "not_found",
                )
            records.append(record)

        try:
            chosen = select_for_turn(records)
            composed = compose_input(text or "", chosen)
        except AttachmentError as exc:
            raise self._attachment_error(exc) from exc
        return HTTPStatus.OK, {"input": composed, "attachments": [r.to_dict() for r in chosen]}

    # --------------------------------------------------------------- previews
    #
    # The second door onto bytes: a path the agent read or wrote, rather than a file the
    # operator attached. Everything about it is in `previews.py` — the roots, the jail, the
    # denylist, the range — because that module is the whole of the new attack surface, and
    # keeping it in one file is what makes it reviewable.

    def file_meta(self, params: dict[str, Any]) -> tuple[int, Any]:
        """What a path is, without moving its bytes.

        The shell asks this first so that a 25 MB scan is a card with a Download button rather
        than a download. A file that cannot be previewed still answers, with `render:
        "download"`, so the card can promise the truth.
        """
        path = self.files.resolve(str(params.get("path") or ""))
        return HTTPStatus.OK, describe_file(path).to_dict()

    def attachment_meta(self, params: dict[str, Any]) -> tuple[int, Any]:
        """What an attachment is, in the same shape as `file_meta`.

        An attachment is reached by id rather than by path, so this is the one door that needs no
        jail: the store only knows the files it wrote, and the id is the whole of the
        authorisation. The answer is the same `PreviewMeta` the path route gives, because one
        function decides what may be rendered and the two doors must not be able to disagree.
        """
        record = self._attachment(params["id"])
        store = self._attachments()
        if record.kind == "folder":
            # A folder is a tree, not a document: there is nothing to put in a frame.
            raise ApiError(
                HTTPStatus.BAD_REQUEST,
                "a folder has no preview of its own",
                "not_a_file",
            )
        # Through the store, so a record whose `root` was edited is refused by the same rule
        # every other door uses (the internal security audit A19-EX-11).
        try:
            path = store.path_of(record)
        except AttachmentError as exc:
            raise self._attachment_error(exc) from exc
        return HTTPStatus.OK, describe_file(path).to_dict()

    def file_raw(self, params: dict[str, Any]) -> tuple[int, Any]:
        """The bytes of one file inside a declared root.

        The same disposition function as an attachment decides what may be inline, so the two
        doors cannot disagree about it.
        """
        path = self.files.resolve(str(params.get("path") or ""))
        file = describe_file(path)
        return HTTPStatus.OK, _byte_response(
            name=file.name,
            data=read_bytes(file),
            content_type=file.content_type,
            disposition=file.disposition,
            range_header=_range_header(params),
        )

    def url_snapshot(self, params: dict[str, Any]) -> tuple[int, Any]:
        """The readable text of one http/https page, fetched once.

        This is the fallback for a site that refuses to be framed, and it is deliberately a
        snapshot rather than a proxy: the page is reduced to text, nothing of the site is ever
        served from our origin, and no header of ours is forwarded to the target. `fetch_url`
        already carries the guards — http/https only, private and loopback addresses refused, a
        byte cap, a timeout.
        """
        body = self._body(params)
        url = body.get("url")
        if not isinstance(url, str) or not url.strip():
            raise ApiError(HTTPStatus.BAD_REQUEST, "a string `url` is required", "bad_body")
        try:
            fetched = fetch_url(url)
        except AttachmentError as exc:
            raise self._attachment_error(exc) from exc

        text, truncated = snapshot_text(fetched.body)
        return HTTPStatus.OK, {
            "url": fetched.url,
            "title": fetched.title,
            "mime": fetched.mime,
            "text": text,
            "truncated": truncated,
        }

    def _attachment(self, attachment_id: str) -> Attachment:
        store = self._attachments()
        try:
            return store.get(attachment_id)
        except AttachmentError as exc:
            raise self._attachment_error(exc) from exc

    def _attachments(self) -> AttachmentStore:
        if self.attachments is None:
            raise ApiError(
                HTTPStatus.SERVICE_UNAVAILABLE,
                "This server was started without an attachment store.",
                "attachments_unavailable",
            )
        return self.attachments

    @staticmethod
    def _attachment_error(exc: AttachmentError) -> ApiError:
        return ApiError(exc.status, exc.message, exc.code)

    # ------------------------------------------------------------- settings
    #
    # The engine has no settings API on this seam (verified: /api/config, /api/config/schema,
    # /api/env and /api/model/set are all 404 on the gateway), so the installed tier edits the
    # engine's own files. That is what the front-end design §2 prescribes. Everything below
    # is a thin shell over `engine_settings.py`.

    def settings(self, _params: dict[str, Any]) -> tuple[int, Any]:
        if self.profile is None or not self.profile.available:
            return HTTPStatus.OK, {
                "available": False,
                "reason": (
                    "No engine profile is configured for this server, so settings are "
                    "read-only here. Start the BFF with --profile-dir <profiles/NAME>."
                ),
            }
        return HTTPStatus.OK, self.profile.snapshot() | {"restart_required": self.restart_required}

    def set_model(self, params: dict[str, Any]) -> tuple[int, Any]:
        profile = self._profile()
        body = self._body(params)
        # Only the keys we mean to own; an explicit null means "leave this one alone".
        wanted = {k: v for k, v in body.items() if k in WRITABLE_MODEL_KEYS and v is not None}
        if not wanted:
            raise ApiError(
                HTTPStatus.BAD_REQUEST,
                f"name at least one of {', '.join(WRITABLE_MODEL_KEYS)}",
                "nothing_to_write",
            )
        try:
            model = profile.set_model(wanted)
        except SettingsError as exc:
            raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, exc.message, exc.code) from exc
        self.restart_required = True
        return HTTPStatus.OK, {"model": model, "restart_required": True}

    def set_reasoning_effort(self, params: dict[str, Any]) -> tuple[int, Any]:
        """Write `agent.reasoning_effort` — how hard the engine thinks before it answers.

        Not a restart-required write: the level lives in the `agent:` block, which the engine
        re-reads whenever it builds an agent, so this lands on the next conversation. The `model:`
        and `.env` writes above are the ones that wait for a restart. The engine clamps the level
        down to the nearest one the chosen model accepts (`agent/reasoning_effort.py`), so what is
        stored is a preference about effort rather than a promise about the wire — and a level
        outside the engine's vocabulary is refused rather than written and silently ignored.
        """
        profile = self._profile()
        value = self._body(params).get(REASONING_EFFORT_KEY)
        if value is False:
            # A JSON `false` is the disabled choice spelled the way the engine spells it.
            value = REASONING_DISABLED
        if not isinstance(value, str):
            raise ApiError(
                HTTPStatus.BAD_REQUEST,
                f"a string `{REASONING_EFFORT_KEY}` is required — one of "
                f"{', '.join(REASONING_EFFORTS)}, or false to switch thinking off",
                "bad_body",
            )
        try:
            written = profile.set_reasoning_effort(value)
        except SettingsError as exc:
            raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, exc.message, exc.code) from exc
        return HTTPStatus.OK, {
            REASONING_EFFORT_KEY: written,
            "applies_to": "new_conversations",
        }

    def set_disabled_toolsets(self, params: dict[str, Any]) -> tuple[int, Any]:
        """Replace `agent.disabled_toolsets` — the engine's own suppression list.

        This is the honest half of the Capabilities screen's switches: the tools really are
        subtracted from the agent, not hidden in our UI. It is deliberately *not* marked
        `restart_required`: the engine re-reads config.yaml when it builds an agent, so the
        change lands on the next conversation (an already-open one keeps its agent).
        """
        profile = self._profile()
        names = self._body(params).get("disabled_toolsets")
        if not isinstance(names, list):
            raise ApiError(
                HTTPStatus.BAD_REQUEST, "a list `disabled_toolsets` is required", "bad_body"
            )
        try:
            disabled = profile.set_disabled_toolsets(names)
        except SettingsError as exc:
            raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, exc.message, exc.code) from exc
        return HTTPStatus.OK, {
            "disabled_toolsets": disabled,
            "applies_to": "new_conversations",
        }

    def list_capabilities(self, _params: dict[str, Any]) -> tuple[int, Any]:
        """Every switchable thing in this profile, in one shape (`capabilities.py`).

        The shell composes this with the engine's `GET /v1/toolsets` into one list: this server
        reads the profile's files, and the toolsets live on the engine's side of the seam.
        Without a profile there is nothing to read, which is a normal answer rather than a
        failure — the same contract as `/api/skills`.
        """
        if self.profile is None or not self.profile.available:
            return HTTPStatus.OK, {
                "available": False,
                "reason": (
                    "No engine profile is configured for this server, so its capabilities "
                    "cannot be read. Start the BFF with --profile-dir <profiles/NAME>."
                ),
                "data": [],
            }
        return HTTPStatus.OK, load_capabilities(self.profile, self._active_environments())

    def set_capability(self, params: dict[str, Any]) -> tuple[int, Any]:
        """One write path for every switch, dispatching on the id's kind.

        Why one route rather than four (the internal capability plan §2.1): the storage differs —
        a skill lives in `skills.disabled`, a toolset in `agent.disabled_toolsets`, a plugin in
        two lists under `plugins:`, an MCP server in a nested block — but the *decision* is the
        same one, and four writers would eventually disagree about it.

        Names are validated against what the profile actually holds, because a name the engine
        does not know is a write that silently does nothing. Toolsets are the exception: the
        engine's own list is the authority and it sits on the far side of the seam, so this
        passes the name to the same writer `/api/settings/toolsets` uses.
        """
        profile = self._profile()
        body = self._body(params)
        enabled = body.get("enabled")
        if not isinstance(enabled, bool):
            raise ApiError(HTTPStatus.BAD_REQUEST, "a boolean `enabled` is required", "bad_body")

        identifier = unquote(str(params.get("id", "")))
        kind, _, name = identifier.partition(":")
        if not kind or not name:
            raise ApiError(
                HTTPStatus.BAD_REQUEST,
                "a capability id is `<kind>:<name>` — for example `skill:invoicing`",
                "bad_id",
            )

        try:
            if kind == "skill":
                self._require_known_skill(name)
                profile.update_disabled_skills(name, enabled)
            elif kind == "plugin":
                self._require_known_plugin(name)
                profile.set_plugin_enabled(name, enabled)
            elif kind == "mcp_server":
                profile.set_mcp_server_enabled(name, enabled)
            elif kind == "toolset":
                self._require_known_toolset(name)
                if enabled and name in ESCAPE_HATCH_TOOLSETS and not params.get("deliberate", True):
                    # These are the capabilities that run code, reach any page or drive the
                    # machine, so switching one back on is a deliberate act: a deployment that has
                    # a write token must present it (the internal security audit A19-CFG-8).
                    raise ApiError(
                        HTTPStatus.FORBIDDEN,
                        f"{name} can run code, reach any page or drive the machine. Turning it "
                        "on needs the write token: start the server with --token and send it as "
                        "X-Pantler-Token.",
                        "escape_hatch",
                    )
                profile.update_disabled_toolsets(name, enabled)
            elif kind == "connector":
                raise ApiError(
                    HTTPStatus.CONFLICT,
                    f"{name} has no client wired yet, so it cannot be switched",
                    "not_toggleable",
                )
            else:
                raise ApiError(
                    HTTPStatus.BAD_REQUEST, f"{kind!r} is not a capability kind", "bad_id"
                )
        except SettingsError as exc:
            # `not_found` is the settings layer saying the profile does not hold this name —
            # a missing MCP server, for instance — and that is the 404 the README promises for
            # every kind. Mapping every SettingsError to 422 made the sentence false for
            # `mcp_server:` (the internal audit DOC-1).
            status = (
                HTTPStatus.NOT_FOUND
                if exc.code == "not_found"
                else HTTPStatus.UNPROCESSABLE_ENTITY
            )
            raise ApiError(status, exc.message, exc.code) from exc

        return HTTPStatus.OK, {
            "id": identifier,
            "enabled": enabled,
            "applies_to": APPLIES_LIVE if kind in ("skill", "toolset") else APPLIES_RESTART,
        }

    def _require_known_skill(self, name: str) -> None:
        """Refuse a skill name this profile does not hold.

        The rule the shell already follows when it writes a disable list: never write a name
        the engine does not report. A typo would otherwise edit the operator's config to no
        effect, and the screen would keep showing the skill as on.
        """
        if name not in {skill["name"] for skill in self._skills()}:
            raise ApiError(
                HTTPStatus.NOT_FOUND, f"this profile holds no skill named {name!r}", "not_found"
            )

    def _require_known_toolset(self, name: str) -> None:
        """Refuse a toolset name the pinned engine does not have, when the baseline says so.

        The engine's own list is on the far side of the seam, and the capability screen reads it
        from there — but `baseline/pantler-toolsets.json` is the captured surface at the pin, the
        same file `scripts/toolset-check.py` asserts against, so it is a real allow-list for a
        name arriving over HTTP. Without it (a checkout that has no baseline) the write is
        allowed, because the engine warns about an unknown name rather than acting on it
        (the internal security audit A19-CFG-8).
        """
        known = _baseline_toolsets()
        if known and name not in known:
            raise ApiError(
                HTTPStatus.NOT_FOUND,
                f"{name!r} is not a toolset of the pinned engine (known: "
                f"{', '.join(sorted(known))})",
                "not_found",
            )

    def _require_known_plugin(self, name: str) -> None:
        """Refuse a plugin name this profile does not hold.

        The same rule as `_require_known_skill`, and for the same reason — but this one was
        missing, so `PUT /api/capabilities/plugin:anything` wrote the name into
        `plugins.enabled` and answered 200 for a plugin that does not exist
        (the internal audit BFF-2). A *known* name is one the registry lists, which is
        the set the screen offers.
        """
        assert self.profile is not None
        if name not in installed_plugins(self.profile):
            raise ApiError(
                HTTPStatus.NOT_FOUND, f"this profile holds no plugin named {name!r}", "not_found"
            )

    def set_disabled_skills(self, params: dict[str, Any]) -> tuple[int, Any]:
        """Replace `skills.disabled` — the engine's own skill switch.

        Like the toolset write, this is live on the next conversation: the engine re-reads
        `config.yaml` when it assembles an agent. A skill the engine always loads is refused
        rather than written and silently ignored.
        """
        profile = self._profile()
        names = self._body(params).get("disabled_skills")
        if not isinstance(names, list):
            raise ApiError(
                HTTPStatus.BAD_REQUEST, "a list `disabled_skills` is required", "bad_body"
            )
        try:
            disabled = profile.set_disabled_skills(names)
        except SettingsError as exc:
            raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, exc.message, exc.code) from exc
        return HTTPStatus.OK, {
            "disabled_skills": disabled,
            "applies_to": "new_conversations",
        }

    def set_key(self, params: dict[str, Any]) -> tuple[int, Any]:
        profile = self._profile()
        body = self._body(params)
        value = body.get("value")
        if not isinstance(value, str):
            raise ApiError(HTTPStatus.BAD_REQUEST, "a string `value` is required", "bad_body")
        try:
            profile.set_key(params["name"], value)
        except SettingsError as exc:
            raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, exc.message, exc.code) from exc
        self.restart_required = True
        # The value itself never comes back, not even echoed.
        return HTTPStatus.OK, {"name": params["name"], "is_set": True, "restart_required": True}

    def clear_key(self, params: dict[str, Any]) -> tuple[int, Any]:
        profile = self._profile()
        try:
            profile.clear_key(params["name"])
        except SettingsError as exc:
            status = (
                HTTPStatus.NOT_FOUND if exc.code == "not_set" else HTTPStatus.UNPROCESSABLE_ENTITY
            )
            raise ApiError(status, exc.message, exc.code) from exc
        self.restart_required = True
        return HTTPStatus.OK, {"name": params["name"], "is_set": False, "restart_required": True}

    # ------------------------------------------------------------ connectors
    #
    # Rail C of the Composio notes: the BFF holds the operator's own project key and talks to
    # Composio, so the screen reads a connection instead of drawing a map. `connectors.py` owns
    # the calls and the identity; these are the thin routes over it.

    def _connector_service(self) -> Connectors:
        if self.connectors is not None:
            return self.connectors
        if self.profile is None or not self.profile.available:
            raise ApiError(
                HTTPStatus.SERVICE_UNAVAILABLE,
                "No engine profile is configured for this server, so its connectors cannot be "
                "read. Start the BFF with --profile-dir <profiles/NAME>.",
                "connectors_unavailable",
            )
        if self._connectors_service is None:
            self._connectors_service = Connectors(self.profile)
        return self._connectors_service

    @staticmethod
    def _connector_error(exc: ConnectorError) -> ApiError:
        status = {
            "bad_request": HTTPStatus.BAD_REQUEST,
            "not_in_catalogue": HTTPStatus.NOT_FOUND,
            "insufficient_permissions": HTTPStatus.FORBIDDEN,
            "not_configured": HTTPStatus.CONFLICT,
            "managed_auth_unavailable": HTTPStatus.CONFLICT,
            "not_connected": HTTPStatus.CONFLICT,
            "write_tool": HTTPStatus.CONFLICT,
            "bad_state": HTTPStatus.INTERNAL_SERVER_ERROR,
        }.get(exc.code, HTTPStatus.BAD_GATEWAY)
        return ApiError(status, exc.message, exc.code)

    def list_connectors(self, _params: dict[str, Any]) -> tuple[int, Any]:
        """The screen's whole state, read from Composio. A Composio failure is an error field."""
        return HTTPStatus.OK, self._connector_service().status()

    def list_connector_tools(self, params: dict[str, Any]) -> tuple[int, Any]:
        try:
            return HTTPStatus.OK, self._connector_service().tools(
                params["id"], params.get("tool")
            )
        except ConnectorError as exc:
            raise self._connector_error(exc) from exc

    def connect_connector(self, params: dict[str, Any]) -> tuple[int, Any]:
        try:
            return HTTPStatus.OK, self._connector_service().connect(params["id"])
        except ConnectorError as exc:
            raise self._connector_error(exc) from exc

    def execute_connector(self, params: dict[str, Any]) -> tuple[int, Any]:
        """Called by the first-party connectors plugin after the engine's approval gate.

        It is a write route like any other, so the browser guard still applies. The plugin sends
        the BFF's own origin and `Sec-Fetch-Site: same-origin`; the human decision happened one
        layer up, in the engine's `pre_tool_call` approval.
        """
        body = self._body(params)
        try:
            return HTTPStatus.OK, self._connector_service().execute(
                params["id"],
                body.get("tool"),
                body.get("arguments", {}),
                read_only_requested=body.get("read_only", False) is True,
            )
        except ConnectorError as exc:
            raise self._connector_error(exc) from exc

    def disconnect_connector(self, params: dict[str, Any]) -> tuple[int, Any]:
        try:
            return HTTPStatus.OK, self._connector_service().disconnect(params["id"])
        except ConnectorError as exc:
            raise self._connector_error(exc) from exc

    def _profile(self) -> EngineProfile:
        if self.profile is None or not self.profile.available:
            raise ApiError(
                HTTPStatus.SERVICE_UNAVAILABLE,
                "No engine profile is configured for this server. Start the BFF with "
                "--profile-dir <profiles/NAME> to enable settings.",
                "settings_unavailable",
            )
        return self.profile

    # ------------------------------------------------------------- helpers

    def _record_type(self, params: dict[str, Any]):
        name = params["type"]
        record_type = self.registry.record_type(name)
        if record_type is None:
            known = ", ".join(sorted(r.type for r in self.registry.record_types)) or "none installed"
            raise ApiError(
                HTTPStatus.NOT_FOUND,
                f"no pack declares a record type {name!r} (known: {known})",
                "unknown_record_type",
            )
        return record_type

    def _body(self, params: dict[str, Any]) -> dict[str, Any]:
        body = params.get("body")
        if body is None:
            raise ApiError(HTTPStatus.BAD_REQUEST, "a JSON body is required", "missing_body")
        if not isinstance(body, dict):
            raise ApiError(HTTPStatus.BAD_REQUEST, "the JSON body must be an object", "bad_body")
        return body


class BffRouter:
    """One BFF application per profile, chosen per request.

    The handlers below are the exception: they manage the registry itself, so they run on the
    router rather than on a profile. Everything else is looked up on the selected profile's
    ``Bff`` — the same object the tests drive, built with that profile's store, attachments and
    engine settings. A request with no selection uses the profile the app is currently on, so
    a client that has not learned about profiles yet keeps working.

    The selection is the ``X-Pantler-Profile`` header. It is read from the request rather than
    from a mutable server-wide field: two tabs (or a desktop and a phone) can be on different
    profiles at once without one changing the other's records underneath it.
    """

    def __init__(
        self,
        base: Bff,
        profiles: ProfileManager | None,
        factory: Callable[[str], Bff],
    ):
        self.base = base
        self.profiles = profiles
        self._factory = factory
        self._bffs: dict[str, Bff] = {}
        self._lock = threading.RLock()

    # -- profile administration ------------------------------------------

    def profiles_list(self, _params: dict[str, Any]) -> tuple[int, Any]:
        if self.profiles is None or not self.profiles.available:
            reason = (
                self.profiles.reason
                if self.profiles is not None
                else "This server was started without --profile-dir, so it does not know an "
                "installation to read profiles from."
            )
            return HTTPStatus.OK, {
                "available": False,
                "reason": reason,
                "active": None,
                "profiles": [],
                "gateway": {"multiplex": False, "served": None, "live": False},
                "restart_required": False,
            }
        gateway = self.profiles.gateway()
        active = self.profiles.active()
        profiles = self.profiles.list()
        return HTTPStatus.OK, {
            "available": True,
            "active": active,
            "profiles": [profile.to_dict() for profile in profiles],
            "gateway": gateway,
            # A second profile on a gateway that is not multiplexing is real on disk and
            # unusable in conversation until the engine restarts. Say so before the operator
            # spends a session discovering it.
            "restart_required": len(profiles) > 1 and not gateway.get("multiplex"),
            "install": self.profiles.install_name,
        }

    def active_profile(self, _params: dict[str, Any]) -> tuple[int, Any]:
        if self.profiles is None or not self.profiles.available:
            return HTTPStatus.OK, {"available": False, "active": None, "profile": None}
        active = self.profiles.active()
        return HTTPStatus.OK, {
            "available": self.profiles.available,
            "active": active,
            "profile": self._info(active),
        }

    def _require_profiles(self) -> ProfileManager:
        if self.profiles is None or not self.profiles.available:
            reason = (
                self.profiles.reason
                if self.profiles is not None
                else "This server was started without --profile-dir, so it cannot manage profiles."
            )
            raise ApiError(HTTPStatus.SERVICE_UNAVAILABLE, reason, "profiles_unavailable")
        return self.profiles

    def set_active_profile(self, params: dict[str, Any]) -> tuple[int, Any]:
        profiles = self._require_profiles()
        body = self.base._body(params)
        try:
            active = profiles.set_active(body.get("name"))
        except ProfileError as exc:
            raise ApiError(exc.status, exc.message, exc.code) from exc
        return HTTPStatus.OK, {"active": active, "profile": self._info(active)}

    def create_profile(self, params: dict[str, Any]) -> tuple[int, Any]:
        profiles = self._require_profiles()
        body = self.base._body(params)
        try:
            profile = profiles.create(
                body.get("name"),
                source=body.get("clone_from") or body.get("source") or None,
                display_name=str(body.get("display_name") or ""),
                description=str(body.get("description") or ""),
            )
        except ProfileError as exc:
            raise ApiError(exc.status, exc.message, exc.code) from exc
        except OSError as exc:
            raise ApiError(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                f"the profile directory could not be written: {exc.strerror or exc}",
                "profile_io",
            ) from exc
        gateway = profiles.gateway()
        return HTTPStatus.CREATED, {
            "profile": profile.to_dict(),
            "gateway": gateway,
            "restart_required": not gateway.get("multiplex"),
        }

    def update_profile(self, params: dict[str, Any]) -> tuple[int, Any]:
        profiles = self._require_profiles()
        body = self.base._body(params)
        name = params["name"]
        try:
            new_name = body.get("new_name")
            if isinstance(new_name, str) and new_name.strip() and new_name.strip() != name:
                profile = profiles.rename(name, new_name)
                # The cached application holds a SQLite connection by the old path, which has
                # just moved. Drop it before the next request asks it for a record.
                self.drop(name)
            else:
                if "display_name" not in body and "description" not in body:
                    raise ApiError(
                        HTTPStatus.BAD_REQUEST,
                        "send `new_name`, `display_name` or `description`",
                        "nothing_to_write",
                    )
                profile = profiles.update(
                    name,
                    display_name=body.get("display_name") if "display_name" in body else None,
                    description=body.get("description") if "description" in body else None,
                )
        except ProfileError as exc:
            raise ApiError(exc.status, exc.message, exc.code) from exc
        except OSError as exc:
            raise ApiError(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                f"the profile could not be changed: {exc.strerror or exc}",
                "profile_io",
            ) from exc
        return HTTPStatus.OK, {
            "profile": profile.to_dict(),
            "active": profiles.active(),
            "gateway": profiles.gateway(),
        }

    def delete_profile(self, params: dict[str, Any]) -> tuple[int, Any]:
        profiles = self._require_profiles()
        # Close this profile's store before removing the directory rather than after: the
        # SQLite connection and its WAL are files inside the tree being deleted.
        self.drop(params["name"])
        try:
            profiles.delete(params["name"])
        except ProfileError as exc:
            raise ApiError(exc.status, exc.message, exc.code) from exc
        except OSError as exc:
            raise ApiError(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                f"the profile could not be deleted: {exc.strerror or exc}",
                "profile_io",
            ) from exc
        return HTTPStatus.OK, {"deleted": params["name"], "active": profiles.active()}

    # -- per-profile dispatch --------------------------------------------

    def _info(self, name: str) -> dict[str, Any] | None:
        if self.profiles is None:
            return None
        try:
            return self.profiles.info(name).to_dict()
        except ProfileError:
            return None

    def selected(self, params: dict[str, Any]) -> str:
        """Which profile this request is about.

        The explicit header wins, because the browser knows which one it is showing. With no
        header the registry's active profile answers, so a script or a client from an older
        build still lands somewhere real. The installed profile always uses the BFF object
        ``serve`` built with the operator's original flags, which is what preserves the
        existing store and attachment directory.
        """
        if self.profiles is None:
            return self.base.profile.name if self.base.profile is not None else ""
        hint = str(params.get("_profile") or "").strip()
        if hint:
            try:
                return self.profiles.require(hint)
            except ProfileError as exc:
                raise ApiError(exc.status, exc.message, exc.code) from exc
        return self.profiles.active()

    def bff_for(self, name: str) -> Bff:
        if self.profiles is None or not self.profiles.available or name == self.profiles.install_name:
            return self.base
        with self._lock:
            found = self._bffs.get(name)
            if found is not None:
                return found
            bff = self._factory(name)
            self._bffs[name] = bff
            return bff

    def drop(self, name: str) -> None:
        """Forget a cached application and close its store (rename or delete)."""
        if self.profiles is None:
            return
        try:
            key = self.profiles.normalize(name)
        except ProfileError:
            return
        if key == self.profiles.install_name:
            return
        with self._lock:
            stale = self._bffs.pop(key, None)
        if stale is not None:
            stale.store.close()

    def __getattr__(self, handler: str):
        """Resolve a data route on the selected profile's application, lazily."""
        if handler.startswith("_"):
            raise AttributeError(handler)

        def call(params: dict[str, Any]):
            name = self.selected(params)
            return getattr(self.bff_for(name), handler)(params)

        call.__name__ = handler
        return call

    def close(self) -> None:
        with self._lock:
            applications = list(self._bffs.values())
            self._bffs.clear()
        for application in applications:
            application.store.close()
        self.base.store.close()


def _range_header(params: dict[str, Any]) -> str | None:
    """The `Range` a route was given, when it asked for the header at all."""
    headers = params.get("headers") or {}
    value = headers.get("Range")
    return value if isinstance(value, str) and value.strip() else None


def _byte_response(
    *,
    name: str,
    data: bytes,
    content_type: str,
    disposition: str,
    range_header: str | None,
) -> RawResponse:
    """One byte response, for both doors onto bytes.

    `data` is the whole file — both callers have it in hand, and both are capped at the same 25
    MB — and the slice is taken here. That is deliberate: a range can then never be served from
    a different read than the one the metadata described.

    An unsatisfiable range answers 416 with `Content-Range: bytes */<size>`, which is what a
    PDF viewer and a `<video>` both check before they ask again. Anything malformed is ignored
    and the whole file is sent, which the RFC allows and which is the kinder failure.
    """
    headers = byte_headers(disposition, name)
    try:
        chosen = parse_range(range_header, len(data))
    except PreviewError as exc:
        if exc.status != HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE:
            raise
        headers["Content-Range"] = f"bytes */{len(data)}"
        return RawResponse(
            HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE,
            b"",
            "text/plain; charset=utf-8",
            headers,
        )

    if chosen is None:
        return RawResponse(HTTPStatus.OK, data, content_type, headers)
    headers["Content-Range"] = chosen.header(len(data))
    return RawResponse(
        HTTPStatus.PARTIAL_CONTENT,
        data[chosen.start : chosen.end + 1],
        content_type,
        headers,
    )


def _bounded_int(raw: Any, default: int, low: int, high: int) -> int:
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ApiError(HTTPStatus.BAD_REQUEST, f"expected a number, got {raw!r}", "bad_query") from exc
    return max(low, min(high, value))


# -------------------------------------------------------------------- HTTP


class Handler(BaseHTTPRequestHandler):
    server_version = "pantler-bff/0.0.1"
    protocol_version = "HTTP/1.1"

    # Injected by `serve`.
    bff: Bff
    static_root: Path | None = None
    #: Origins *other than this one* that may read a response and make a write. Empty by
    #: default, because the shell never needs one: through the dev proxy and through
    #: `--static` it is same-origin, so nothing has to be granted.
    cors_origins: tuple[str, ...] = ()
    #: Host names this machine answers to, beyond the addresses it can discover for itself.
    #: `--allow-host` (or `$PANTLER_ALLOWED_HOSTS`, the name the dev server is also told)
    #: adds one; a name that only resolves here (a MagicDNS name, say) needs it.
    trusted_hosts: tuple[str, ...] = ()
    #: The shared secret a non-browser client presents to write (`X-Pantler-Token`). Generated
    #: per start when `--token`/`PANTLER_BFF_TOKEN` is not given, and printed to the log so a
    #: script can pick it up; see `serve`.
    token: str = ""
    #: Set once this request's body has been read, so a refusal can tell whether the socket
    #: still holds bytes the next request would be parsed inside. Reset per request by
    #: `handle_one_request` calling `parse_request`, which is why it is a class default.
    _body_read: bool = False

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write(f"{self.address_string()} {fmt % args}\n")

    # -- origins ----------------------------------------------------------
    #
    # Why this is not just the peer check it used to be (the internal audit SEC-1):
    # `is_loopback(self.client_address[0])` answers "did this arrive over the loopback
    # interface", and a page on any other origin that the operator visits answers yes,
    # because the browser is the one connecting. The old `_cors` reflected whatever
    # `Origin` it was given, so that page could read every record, read any file the
    # preview roots allow, and — with a two-header preflight — write `config.yaml`.
    #
    # The rule now, twice tightened (the internal security audit A19-EX-1, A19-EX-2):
    #
    #   * a host is trusted only when it names an address *this machine holds* (loopback,
    #     one of its interface addresses, or a name passed with `--allow-host`). Comparing
    #     the Origin against the request's own `Host` was not enough: under DNS rebinding
    #     the attacker's page sends both, and they agree with each other;
    #   * a write must carry a positive signal — the token, or an Origin/Referer/fetch
    #     metadata from a trusted host. The absence of every signal is a script, not a
    #     browser, and is refused rather than waved through.

    def _request_host(self) -> str:
        return (self.headers.get("Host") or "").strip().lower()

    def _host_trusted(self, value: str) -> bool:
        """Whether `value` names this machine, rather than merely naming the request."""
        name = host_name(value)
        if not name:
            return False
        if name in {granted.lower() for granted in type(self).trusted_hosts}:
            return True
        if name in local_addresses():
            return True
        # An IP literal is answered by the machine itself (see `is_local_address`); a *name* is
        # not, because resolving it is the very thing a rebinding attacker controls.
        return is_local_address(name)

    def _origin_allowed(self, origin: str) -> bool:
        wanted = (origin or "").strip().rstrip("/")
        if not wanted:
            return False
        if wanted.lower() in {granted.lower().rstrip("/") for granted in type(self).cors_origins}:
            return True
        host = self._request_host()
        # Same *and* trusted: the origin must name the same host the request did, and that
        # host must be one of ours.
        return bool(host) and host_name(wanted) == host_name(host) and self._host_trusted(host)

    def _token_ok(self) -> bool:
        """Whether the request carries the configured write token, if there is one."""
        expected = type(self).token
        if not expected:
            return False
        offered = (self.headers.get("X-Pantler-Token") or "").strip()
        return bool(offered) and hmac.compare_digest(offered, expected)

    def _deliberate(self) -> bool:
        """Whether this request proves it meant the change.

        True when the deployment configured no token (nothing to present), or when it did and
        the request presented it. The capability route reads this through `params["deliberate"]`
        for the switches that are escape hatches rather than ordinary toggles.
        """
        return self._token_ok() or not type(self).token

    def _foreign_write(self) -> bool:
        """Whether a write arrived from somewhere other than this app.

        The peer address cannot tell: a cross-site request from the operator's own
        browser is a loopback connection. So a write has to *look* like ours as well —
        and a caller that carries none of these headers at all is a script, which must
        present the token rather than being assumed friendly
        (the internal security audit A19-EX-2).
        """
        if self._token_ok():
            return False
        site = (self.headers.get("Sec-Fetch-Site") or "").strip().lower()
        if site and site not in ("same-origin", "none"):
            return True
        origin = (self.headers.get("Origin") or "").strip()
        if origin:
            return not self._origin_allowed(origin)
        host = self._request_host()
        referer = (self.headers.get("Referer") or "").strip()
        if referer:
            return not (self._host_trusted(host) and host_name(referer) == host_name(host))
        if site:
            # A browser that sent fetch metadata but no Origin/Referer: same-origin and a
            # trusted host is as much as we can ask for.
            return not self._host_trusted(host)
        return True

    def _untrusted_front_door(self) -> bool:
        """Whether a refusal is the app being reached by a name this server does not know.

        The browser sent an Origin naming the same host it addressed, so this is not a page
        from somewhere else — it is the app itself, at a name the server was never told to
        answer to (a tailnet/MagicDNS name reached through the dev proxy, typically). The
        guard's decision is unchanged; only the sentence changes, because "come from the
        app" is misleading when the operator is already in the app.
        """
        origin = (self.headers.get("Origin") or "").strip()
        host = self._request_host()
        return (
            bool(origin)
            and bool(host)
            and host_name(origin) == host_name(host)
            and not self._host_trusted(host)
        )

    def _write_refusal(self) -> str:
        """The sentence for a refused write: the fix, when there is one to name."""
        if self._untrusted_front_door():
            return (
                "this app is being reached by a name the server has not been told about; "
                "start it with --allow-host <name> or set PANTLER_ALLOWED_HOSTS"
            )
        return "this change has to come from the app itself, not from another page"

    # -- verbs ------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch("POST")

    def do_PATCH(self) -> None:  # noqa: N802
        self._dispatch("PATCH")

    def do_PUT(self) -> None:  # noqa: N802
        self._dispatch("PUT")

    def do_DELETE(self) -> None:  # noqa: N802
        self._dispatch("DELETE")

    def do_OPTIONS(self) -> None:  # noqa: N802
        # A preflight is answered only for an origin we would serve; for any other, the
        # refusal carries no CORS headers, so the browser stops before the real request.
        origin = (self.headers.get("Origin") or "").strip()
        if origin and not self._origin_allowed(origin):
            self._send_json(
                HTTPStatus.FORBIDDEN,
                {
                    "error": {
                        "message": "this server answers only its own origin",
                        "code": "cross_origin",
                    }
                },
            )
            return
        self.send_response(HTTPStatus.NO_CONTENT)
        self._cors()
        self.send_header("Allow", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
        self.send_header("Content-Length", "0")
        self.end_headers()

    # -- dispatch ---------------------------------------------------------

    def _dispatch(self, method: str) -> None:
        # One handler instance serves every request on a kept-alive connection, so the
        # per-request facts start here rather than in `__init__`.
        self._body_read = False

        parsed = urlparse(self.path)
        path = unquote(parsed.path)

        if not path.startswith("/api/"):
            self._serve_static(path)
            return

        for route in ROUTES:
            match = route.match(method, path)
            if match is None:
                continue

            # The settings writes, the capability switches and the record mutations change
            # state, so they are refused to anything that is not this machine *and* this
            # origin. Loopback is the cheap half; `_foreign_write` is the half that can see
            # where the request came from, and it is what stops a page the operator happens
            # to be visiting from writing their configuration (the internal audit SEC-1).
            if route.writes:
                if not is_loopback(self.client_address[0]):
                    self._close_if_body_pending()
                    self._send_json(
                        HTTPStatus.FORBIDDEN,
                        {
                            "error": {
                                "message": "settings can only be changed from this machine",
                                "code": "not_local",
                            }
                        },
                    )
                    return
                if self._foreign_write():
                    self._close_if_body_pending()
                    self._send_json(
                        HTTPStatus.FORBIDDEN,
                        {
                            "error": {
                                "message": self._write_refusal(),
                                "code": "cross_origin",
                            }
                        },
                    )
                    return

            # The path's own captures are merged *last* so a query key can never replace
            # one: `DELETE /api/records/note/NOTE-1?id=NOTE-2` used to delete NOTE-2, and
            # every route with an id in its path had the same hole
            # (the internal audit BFF-6). Query parameters a route genuinely reads
            # (`limit`, `order`, `session`, `path`) still arrive the same way.
            params: dict[str, Any] = {}
            params["query"] = {k: v[0] for k, v in parse_qs(parsed.query).items()}
            params.update(params["query"])
            params.update(match.groupdict())
            if route.headers:
                params["headers"] = {name: self.headers.get(name, "") for name in route.headers}
            # The selected profile is request-scoped, not a server-wide mutable. It is read
            # from the header the shell sends, and the router validates it against the
            # registry — a name that is not a profile is a 404, never a path.
            params["_profile"] = (self.headers.get("X-Pantler-Profile") or "").strip()
            # Injected last, so nothing a caller sent can stand in for it.
            params["deliberate"] = self._deliberate()

            try:
                if route.raw:
                    params["body_bytes"] = self._read_raw_body()
                elif method in ("POST", "PATCH", "PUT"):
                    params["body"] = self._read_json_body()
                status, payload = getattr(self.bff, route.handler)(params)
            except ApiError as exc:
                # A refusal may have happened before the body was read — the body cap above is
                # the common case — and an unread body must not be left for the next request
                # to be parsed inside (the internal audit BFF-4).
                self._close_if_body_pending()
                self._send_json(exc.status, {"error": {"message": exc.message, "code": exc.code}})
                return
            except PreviewError as exc:
                # A preview refusal is already a sentence and a status — "that file is outside
                # the directories this server may read" — so it needs no translation, only a
                # body. It is caught here rather than in each handler so that no future route
                # can serve bytes and forget to answer for a refusal (the file-preview design §4).
                self._send_json(exc.status, {"error": {"message": exc.message, "code": exc.code}})
                return
            except PackError as exc:
                self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": {"message": str(exc), "code": "pack_error"}})
                return
            except Exception as exc:  # a bug, not a request problem
                # The operator sees a sentence and a reference; the detail goes to the log,
                # where it is useful, rather than to the client, where it is an inventory of
                # the machine (the internal audit BFF-7).
                reference = uuid.uuid4().hex[:8]
                self.log_error(
                    "unhandled %s [%s] on %s %s: %s\n%s",
                    type(exc).__name__,
                    reference,
                    method,
                    path,
                    exc,
                    traceback.format_exc(),
                )
                self._close_if_body_pending()
                self._send_json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {
                        "error": {
                            "message": (
                                "the server hit an unexpected problem. The details are in its "
                                f"log under {reference}."
                            ),
                            "code": "internal",
                        }
                    },
                )
                return

            # A success can leave a body unread too: a GET is allowed to carry one, and the
            # keep-alive connection would then parse those bytes as the next request
            # (the internal security audit A19-EX-13). Consume-or-close, as for refusals.
            self._close_if_body_pending()
            if isinstance(payload, RawResponse):
                self._send_bytes(payload)
            elif payload is None:
                self.send_response(status)
                self._cors()
                self._connection_header()
                self._security_headers()
                self.send_header("Content-Length", "0")
                self.end_headers()
            else:
                self._send_json(status, payload)
            return

        self._close_if_body_pending()
        self._send_json(
            HTTPStatus.METHOD_NOT_ALLOWED if self._path_exists(path) else HTTPStatus.NOT_FOUND,
            {"error": {"message": f"no route for {method} {path}", "code": "no_route"}},
        )

    def _path_exists(self, path: str) -> bool:
        return any(route.regex.match(path) for route in ROUTES)

    # -- bodies -----------------------------------------------------------

    def _declared_body(self) -> int:
        """How many bytes the request says it is sending, or 0 when it says nothing."""
        raw = self.headers.get("Content-Length") or "0"
        try:
            return max(0, int(raw))
        except ValueError:
            return 0

    def _close_if_body_pending(self) -> None:
        """Refuse to reuse a connection that still holds an unread body.

        A refusal that happens *before* the body is read — an oversize body, a foreign
        origin, a route that does not exist — leaves those bytes in the socket, and the
        next request line the server parses is a piece of the previous one. The fix is not
        to read a body we have already decided to refuse (that is the denial of service the
        cap exists to avoid); it is to say the connection ends here. The client reconnects,
        which is what it would have done anyway.
        """
        if self._declared_body() > 0 and not self._body_read:
            self.close_connection = True

    def _read_json_body(self) -> Any:
        raw_length = self.headers.get("Content-Length") or "0"
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise ApiError(HTTPStatus.BAD_REQUEST, "invalid Content-Length", "bad_body") from exc

        # A negative length is not a small body. `rfile.read(-1)` reads until the peer closes,
        # which is unbounded memory and a thread parked for as long as the peer likes
        # (the internal security audit A19-EX-4), so the range is checked before anything
        # else looks at it.
        if length < 0:
            raise ApiError(HTTPStatus.BAD_REQUEST, "invalid Content-Length", "bad_body")
        if length > MAX_BODY_BYTES:
            raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "body too large", "too_large")
        if length == 0:
            self._body_read = True
            return None

        # Only a JSON request is read as JSON. This is not pedantry: `Content-Type:
        # text/plain` is one of the three a browser may send **without a preflight**, so a
        # page on any origin could POST a JSON body here — the one write a cross-site request
        # could still reach, since PATCH and DELETE need the preflight the origin guard
        # refuses (the internal audit SEC-1). Requiring the type the API actually
        # speaks costs a real client nothing and closes that path.
        declared = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if declared != "application/json":
            raise ApiError(
                HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                f"this route reads `application/json`, not {declared or 'nothing'}",
                "unsupported_media_type",
            )

        raw = self.rfile.read(length)
        self._body_read = True
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ApiError(HTTPStatus.BAD_REQUEST, f"invalid JSON: {exc}", "bad_json") from exc

    def _read_raw_body(self) -> bytes:
        """One upload. The cap is the store's own, so the two can never disagree."""
        store = self.bff.attachments
        limit = store.max_file_bytes if store is not None else MAX_FILE_BYTES
        raw_length = self.headers.get("Content-Length") or "0"
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise ApiError(HTTPStatus.BAD_REQUEST, "invalid Content-Length", "bad_body") from exc
        if length < 0:
            # See `_read_json_body`: `read(-1)` is "until EOF", not "nothing".
            raise ApiError(HTTPStatus.BAD_REQUEST, "invalid Content-Length", "bad_body")
        if length > limit:
            raise ApiError(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                f"the file is larger than {limit // (1024 * 1024)} MB",
                "too_large",
            )
        body = self.rfile.read(length) if length else b""
        self._body_read = True
        return body

    # -- responses --------------------------------------------------------

    def _send_bytes(self, response: RawResponse) -> None:
        self.send_response(response.status)
        self._cors()
        self._connection_header()
        self.send_header("Content-Type", response.content_type)
        self.send_header("Content-Length", str(len(response.body)))
        for name, value in response.headers.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(response.body)

    def _send_json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self._cors()
        self._connection_header()
        self._security_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _security_headers(self) -> None:
        """The headers that cost nothing and close a class of accidents.

        `nosniff` was only on the byte routes; JSON and the built shell went without. The
        shell is the one that renders model output, so it carries the CSP
        (the internal security audit A19-EX-8).
        """
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")

    #: The shell's Content-Security-Policy, with `{script_src}` filled from the document that is
    #: actually being served. Inline script is not allowed wholesale — `index.html`'s first-paint
    #: theme script is hashed from its own bytes by `_csp_for`, so the hash cannot drift from the
    #: document the way a hard-coded one would.
    CSP_TEMPLATE = (
        "default-src 'self'; script-src {script_src}; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; media-src 'self' blob:; font-src 'self' data:; "
        "connect-src 'self'; frame-src http: https:; object-src 'none'; base-uri 'none'; "
        "form-action 'none'; frame-ancestors 'none'"
    )

    #: `<script>` without a `src`, capturing its body. `type="module" src=…` is not it.
    _INLINE_SCRIPT_RE = re.compile(rb"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", re.S | re.I)

    @classmethod
    def _csp_for(cls, body: bytes) -> str:
        hashes = [
            "'sha256-" + base64.b64encode(hashlib.sha256(match.group(1)).digest()).decode() + "'"
            for match in cls._INLINE_SCRIPT_RE.finditer(body)
        ]
        return cls.CSP_TEMPLATE.format(script_src=" ".join(["'self'", *hashes]))

    def _connection_header(self) -> None:
        """Say the connection is ending when it is.

        `close_connection` is the server's own decision (an unread body, a client that asked
        for it, HTTP/1.0). Saying so lets the client start a new connection deliberately
        instead of writing a request into a socket that is about to close.
        """
        if self.close_connection:
            self.send_header("Connection", "close")

    def _cors(self) -> None:
        """CORS headers, for our own origin only.

        The shell normally reaches the BFF through the same origin (the dev server proxies
        /api, and `--static` serves both), so the ordinary answer is one header naming that
        origin. An origin that is not ours gets **nothing** — no
        `Access-Control-Allow-Origin`, no method list — which is what stops any other page
        the operator visits from reading a response. `--cors-origin` is the deliberate
        exception for a separately-served build.
        """
        origin = (self.headers.get("Origin") or "").strip()
        if not origin or not self._origin_allowed(origin):
            return
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
        # The answer depends on the request's Origin, so a cache must not reuse it.
        self.send_header("Vary", "Origin")

    def _serve_static(self, path: str) -> None:
        """Serve a built shell, so the whole app can be one origin."""
        root = type(self).static_root
        if root is None:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": {"message": "not found", "code": "not_found"}})
            return

        relative = path.lstrip("/") or "index.html"
        shell = root.resolve()
        candidate = (shell / relative).resolve()
        # Never serve outside the root, however the path was spelled. A prefix test is not
        # containment: with `static_root=/srv/shell`, `/srv/shell-evil/secret` starts with
        # `/srv/shell` and used to be served (the internal audit BFF-5). `is_relative_to`
        # compares path components, not characters.
        if candidate != shell and not candidate.is_relative_to(shell):
            self._send_json(HTTPStatus.FORBIDDEN, {"error": {"message": "forbidden", "code": "forbidden"}})
            return
        if candidate.is_dir():
            candidate = candidate / "index.html"
        if not candidate.is_file():
            # Single-page app: unknown paths fall back to the shell.
            candidate = shell / "index.html"
        if not candidate.is_file():
            self._send_json(HTTPStatus.NOT_FOUND, {"error": {"message": "not found", "code": "not_found"}})
            return

        body = candidate.read_bytes()
        content_type = mimetypes.guess_type(str(candidate))[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self._security_headers()
        if content_type == "text/html":
            # The shell is the only document this server ever serves, and it renders model
            # output. Everything it loads is its own bundle or a framed preview.
            self.send_header("Content-Security-Policy", self._csp_for(body))
            self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


# ------------------------------------------------------------------- serve


def build_bff(
    store_path: str | Path,
    packs_dir: str | Path,
    profile_dir: str | Path | None = None,
    attachments_dir: str | Path | None = None,
    files_roots: Iterable[str | Path] | None = None,
    custom_packs_dir: str | Path | None = None,
) -> Bff:
    profile = EngineProfile(Path(profile_dir).resolve()) if profile_dir else None
    attachments = AttachmentStore(Path(attachments_dir).resolve()) if attachments_dir else None
    if custom_packs_dir is None and profile_dir is not None:
        custom_packs_dir = Path(profile_dir).resolve() / "custom-packs"
    bff = Bff(
        Store(store_path),
        load_packs(packs_dir, custom_dir=custom_packs_dir),
        profile,
        attachments,
        FileRoots.build(files_roots),
    )
    bff.watch_packs(packs_dir, custom_packs_dir)
    return bff


def profile_workspace_for_preview(profiles: ProfileManager, name: str) -> Path | None:
    """The profile's own workspace, never the shared root it may still be configured with.

    A legacy dev install points ``terminal.cwd`` at the shared ``workspace/`` root. Opening
    that root as a preview root would expose every sibling business's output, which is the
    leak this change closes. The profile's own child is safe when it exists; when it does
    not, the app gets no workspace root and the startup banner says how to fix the config.
    """
    workspace = profiles.workspace_for(name)
    if workspace != profiles.workspace_root:
        return workspace
    own = profiles.workspace_root / profiles.validate(name)
    return own if own.is_dir() else None


def profile_file_roots(
    profiles: ProfileManager,
    name: str,
    extra_roots: Iterable[str | Path] = (),
) -> list[str]:
    """The directories one business's app may preview from — its own, and only its own.

    ``REPO_ROOT`` is deliberately absent. It used to be a default root, which made every
    profile's app able to read every other profile's workspace and the checkout itself. The
    attachments store and the workspace are the two places a produced file can be; anything
    else is an explicit ``--files-root`` grant from the operator.
    """
    roots: list[str] = []
    attachments = profiles.attachments_for(name)
    if attachments is not None:
        roots.append(str(attachments))
    workspace = profile_workspace_for_preview(profiles, name)
    if workspace is not None:
        roots.append(str(workspace))
    for root in extra_roots:
        text = str(root).strip()
        if text and text not in roots:
            roots.append(text)
    return roots


def serve(
    *,
    store_path: str | Path,
    packs_dir: str | Path,
    host: str = "127.0.0.1",
    port: int = 8650,
    static_root: str | Path | None = None,
    profile_dir: str | Path | None = None,
    attachments_dir: str | Path | None = None,
    attachments_keep_days: int = DEFAULT_ATTACHMENTS_KEEP_DAYS,
    files_roots: Iterable[str | Path] | None = None,
    custom_packs_dir: str | Path | None = None,
    cors_origins: Iterable[str] | None = None,
    allow_hosts: Iterable[str] | None = None,
    token: str | None = None,
) -> None:
    # Profiles are opt-in in the same way settings are: the registry needs an explicit
    # ``--profile-dir`` to know which installation it belongs to. Without one, every request
    # gets the single application above and the Profiles screen reports why it is empty.
    profiles = (
        ProfileManager(
            profile_dir,
            store_path=store_path,
            attachments_dir=attachments_dir,
            repo_root=REPO_ROOT,
        )
        if profile_dir
        else None
    )
    explicit_roots = list(files_roots or [])
    if profiles is not None and profiles.available:
        base_roots = profile_file_roots(profiles, profiles.active(), explicit_roots)
    else:
        # The pre-profiles shape: one store, one workspace (the checkout), one app. It keeps
        # the old repository root because there is no other business to leak to.
        base_roots = ([str(attachments_dir)] if attachments_dir else [])
        base_roots.append(str(REPO_ROOT))
        base_roots.extend(str(root) for root in explicit_roots)

    bff = build_bff(
        store_path, packs_dir, profile_dir, attachments_dir, base_roots, custom_packs_dir
    )

    workspace_warnings: list[str] = []
    if profiles is not None and profiles.available:
        active = profiles.active()
        if profile_workspace_for_preview(profiles, active) is None:
            workspace_warnings.append(
                f"profile “{active}” works in the shared workspace root. Point its "
                f"terminal.cwd at {profiles.workspace_root / active} so its previews stay "
                f"inside its own business."
            )

    def make_profile_bff(name: str) -> Bff:
        """A profile's own application: its store, its attachments, its workspace."""
        attachments = profiles.attachments_for(name)
        roots = profile_file_roots(profiles, name, explicit_roots)
        built = build_bff(
            profiles.store_for(name),
            packs_dir,
            profiles.path_for(name),
            attachments,
            roots,
            profiles.path_for(name) / "custom-packs",
        )
        if built.attachments is not None and attachments_keep_days > 0:
            # The base profile is swept below at startup; a profile that is opened later gets
            # the same treatment the first time it is opened.
            built.attachments.sweep(attachments_keep_days)
        return built

    application: BffRouter = BffRouter(bff, profiles, make_profile_bff)

    granted = tuple(
        origin.rstrip("/") for origin in (cors_origins or ()) if str(origin).strip()
    )
    # A name passed with `--allow-host` is trusted, and so is the host of any origin that was
    # explicitly granted: the operator has said those names are this app.
    trusted = tuple(
        dict.fromkeys(
            [name for name in (host_name(host),) if name]
            + [name for name in (host_name(value) for value in (allow_hosts or ())) if name]
            + [name for name in (host_name(value) for value in granted) if name]
        )
    )
    secret = (token or "").strip()

    handler = type(
        "BoundHandler",
        (Handler,),
        {
            "bff": application,
            "static_root": Path(static_root).resolve() if static_root else None,
            "cors_origins": granted,
            "trusted_hosts": trusted,
            "token": secret,
        },
    )

    httpd = ThreadingHTTPServer((host, port), handler)
    httpd.daemon_threads = True

    # Line-buffered even when stdout is a file: this is a server people leave running under
    # nohup, and a startup banner that only appears when it exits is worse than none.
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except (AttributeError, ValueError):  # a replaced stdout, or a Python that cannot
        pass

    packs = ", ".join(p.id for p in bff.registry.packs) or "none"
    print(f"pantler BFF on http://{host}:{port}")
    print(f"  store   {store_path}")
    print(f"  packs   {packs}")
    if bff.attachments is not None:
        print(f"  files   {bff.attachments.root}")
        repaired = bff.attachments.repair_modes()
        if repaired:
            print(f"          repaired permissions on {repaired} item(s) older than the fix")
        if attachments_keep_days > 0:
            removed = bff.attachments.sweep(attachments_keep_days)
            print(
                f"          swept {removed} attachment(s) older than {attachments_keep_days} days"
                if removed
                else f"          keeping attachments for {attachments_keep_days} days"
            )
    else:
        print("  files   none  (attachments are off)")
    roots = bff.files.describe()
    if roots:
        print(f"  read    {roots[0]}")
        for extra in roots[1:]:
            print(f"          {extra}")
    else:
        print("  read    none  (pass --files-root DIR to preview a workspace by path)")
    if static_root:
        print(f"  shell   {static_root}")
    if granted:
        print(f"  origin  also answering {', '.join(granted)}")
    else:
        print("  origin  this server's own only  (--cors-origin grants another)")
    if bff.profile is not None and bff.profile.available:
        print(f"  profile {bff.profile.dir}  (settings editable)")
        if not is_loopback(host) and host not in ("localhost", ""):
            print(
                "\n  ⚠  this server is not bound to loopback and settings edits are enabled.\n"
                "     A request still has to arrive looking local and from this origin, but the\n"
                "     dev proxy makes a tailnet browser look exactly like that — keep the bind\n"
                "     to your tailnet and the port behind a Tailscale ACL.\n"
            )
    else:
        print("  profile none  (settings read-only; pass --profile-dir to enable)")
    if profiles is not None:
        if profiles.available:
            names = profiles.names()
            print(
                f"  profiles {profiles.profiles_root}  "
                f"({len(names)} profile{'s' if len(names) != 1 else ''}; active {profiles.active()})"
            )
            gateway = profiles.gateway()
            if len(names) > 1 and not gateway.get("multiplex"):
                print(
                    "           the running engine serves one profile. To use the others, "
                    "start the host\n"
                    "           gateway with gateway.multiplex_profiles: true and serve them "
                    "under /p/<name>/."
                )
            for warning in workspace_warnings:
                print(f"  ⚠  {warning}")
        else:
            print(f"  profiles off  ({profiles.reason})")
    if secret:
        print("  writes  token required (X-Pantler-Token)")
    else:
        print("  writes  this origin only (a script must send an Origin or --token)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping")
    finally:
        httpd.server_close()
        application.close()


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="pantler's front-end backend")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8650)
    parser.add_argument("--store", default=str(REPO_ROOT / ".data" / "records.db"))
    parser.add_argument("--packs", default=str(REPO_ROOT / "packs"))
    parser.add_argument(
        "--custom-packs",
        default=None,
        help=(
            "the operator's own record types, outside the distribution-owned packs/. Defaults "
            "to custom-packs/ beside --profile-dir"
        ),
    )
    parser.add_argument("--static", default=None, help="serve a built shell from this directory")
    parser.add_argument(
        "--profile-dir",
        default=None,
        help=(
            "the installed engine profile (…/profiles/NAME). Enables the settings write API "
            "and the profile registry (the directory's parent is the profiles root)."
        ),
    )
    parser.add_argument(
        "--attachments-dir",
        default=str(REPO_ROOT / ".data" / "attachments"),
        help="where uploaded files are kept. Beside the engine, which reads them by path.",
    )
    parser.add_argument(
        "--attachments-keep-days",
        type=int,
        default=DEFAULT_ATTACHMENTS_KEEP_DAYS,
        help="sweep attachments older than this at startup; 0 keeps them forever",
    )
    parser.add_argument(
        "--files-root",
        action="append",
        default=None,
        metavar="DIR",
        help=(
            "an extra directory a preview may read a file from, beyond this profile's own "
            "workspace and attachments. Repeatable. Without --profile-dir the repository is "
            "also read (the legacy single-profile shape); without any root the by-path route "
            "refuses rather than guessing at $HOME (the file-preview design §4 D6)"
        ),
    )
    parser.add_argument(
        "--cors-origin",
        action="append",
        default=None,
        metavar="ORIGIN",
        help=(
            "an origin other than this server's own that may read a response and make a write, "
            "e.g. http://127.0.0.1:5175. Repeatable, and empty by default: the shell is "
            "same-origin through the dev proxy and through --static, so nothing needs granting"
        ),
    )
    parser.add_argument(
        "--allow-host",
        action="append",
        default=hosts_from_env(),
        metavar="NAME",
        help=(
            "a host name this app answers to, beyond the addresses the machine can discover "
            "for itself — a MagicDNS name, say. Repeatable; defaults to the comma-separated "
            "$PANTLER_ALLOWED_HOSTS, the variable the dev server uses, so one declaration "
            "covers both. A request whose Host is not one of these is not treated as this "
            "app, which is what closes DNS rebinding "
            "(the internal security audit A19-EX-1)"
        ),
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("PANTLER_BFF_TOKEN") or None,
        help=(
            "the shared secret a non-browser client sends as X-Pantler-Token to write "
            "(default: $PANTLER_BFF_TOKEN, or none — a browser's own Origin is then the only "
            "signal a write may carry)"
        ),
    )
    args = parser.parse_args(argv)

    # Where a preview may read from: the profile's own workspace and attachments are added by
    # `serve`; `--files-root` is the operator's explicit addition. This used to seed the whole
    # repository, which made every profile's app able to open every other profile's output.
    roots = [str(root) for root in (args.files_root or [])]

    serve(
        store_path=args.store,
        packs_dir=args.packs,
        host=args.host,
        port=args.port,
        static_root=args.static,
        profile_dir=args.profile_dir,
        attachments_dir=args.attachments_dir,
        attachments_keep_days=args.attachments_keep_days,
        files_roots=roots,
        custom_packs_dir=args.custom_packs,
        cors_origins=args.cors_origin,
        allow_hosts=args.allow_host,
        token=args.token,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
