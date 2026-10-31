"""Keep the assistant inside the business it was opened for.

The engine's file and terminal tools have no notion of a profile boundary. They run as the
operator's OS user, so a path such as ``workspace/output`` beside this profile's own
``workspace/<name>`` is readable unless something refuses it. During session
``web-1a90145424a3`` the model listed that shared directory and used another business's
social cards as its reference. This module is the product's boundary: a ``pre_tool_call``
hook that refuses the known data-bearing paths before the tool runs.

It is deliberately a *tool-call* boundary, not an OS sandbox. The file, vision and browser
tools are checked exactly; the terminal is checked heuristically (tokens, quoted strings and
path-like substrings in heredocs). A command that never names a path, or one that relies on
a shell expansion the guard cannot see, can still escape. The BFF's preview jail is the
second, exact door. The limits are recorded in `the status page`.
"""

from __future__ import annotations

import logging
import os
import re
import shlex
from pathlib import Path
from typing import Iterable, Iterator, Sequence
from urllib.parse import unquote, urlparse

logger = logging.getLogger(__name__)

#: A path that belongs to another business, or to the assistant's own state outside this
#: profile. The message never names the path: a refusal is not an existence oracle.
OTHER_BUSINESS = (
    "That file belongs to another business, so I won't open it. I can work from this "
    "business's records and workspace; attach a file if you want me to use it."
)

#: A path outside this workspace that is not another business's data.
OUTSIDE = (
    "That file is outside this business's workspace, so I won't open it. Attach it and I'll "
    "use it, or tell me what you need and I'll work from your records."
)

#: A credential or engine-state file inside this profile.
SECRET = (
    "That is the assistant's own credential or state file, so I won't open it. Ask me for the "
    "record or setting you need instead."
)

#: Names that are never read through a tool, whatever directory they are in. Mirrors the
#: BFF's preview denylist (``app/server/previews.py``) so the two doors agree.
_DENIED_NAMES = frozenset({".env", ".envrc", ".git-credentials", "install_id"})
_DENIED_STEMS = frozenset(
    {
        "auth",
        "credential",
        "credentials",
        "install_id",
        "id_rsa",
        "id_ed25519",
        "id_ecdsa",
        "id_dsa",
        "records",
    }
)
_DENIED_PREFIXES = (
    "state.db",
    "response_store.db",
    "runs_idempotency.db",
    "records.db",
)
_DENIED_SUFFIXES = (".pem", ".key", ".p12", ".pfx")

#: Read-only system paths the renderer legitimately needs. The boundary is the operator's
#: data, not the operating system; a font or a shared library is not another business.
_SYSTEM_ROOTS = (
    Path("/usr"),
    Path("/etc"),
    Path("/opt"),
    Path("/tmp"),
    Path("/var"),
    Path("/proc"),
    Path("/sys"),
    Path("/dev"),
)

#: Path-like text in a shell command: an absolute or explicit relative path. The lookbehind
#: keeps URLs (``https://``) and ordinary words with a slash (``and/or``) out of the scan.
_PATH_LIKE = re.compile(r"""(?<![\w:/])((?:~|\.{1,2}|/)[^\s'"`;|&<>()]*)""")

#: A quoted string in Python source. Only strings are checked in ``execute_code``: a regex
#: over the whole file would read ``a // b`` as a path.
_QUOTED = re.compile(r"""(['"])(.*?)\1""", re.S)

#: Shell tokens that are grammar, not paths.
_SHELL_META = frozenset(
    {"|", "||", "&&", ";", "&", ">", ">>", "<", "<<", "2>", "2>>", "&>", "&>>"}
)


def _under(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _candidate(raw: str) -> str:
    """The path-shaped part of a token, or "" when the token is not a path at all."""
    text = raw.strip()
    if not text:
        return ""
    for marker in ("2>>", "2>", "&>>", "&>", ">>", ">"):
        if text.startswith(marker):
            text = text[len(marker) :]
            break
    if not text or text in _SHELL_META:
        return ""
    if "=" in text:
        head, _, tail = text.partition("=")
        if head and not head.startswith("/") and " " not in head:
            text = tail
    text = text.strip("'\"")
    text = text.rstrip("),;:")
    if not text:
        return ""
    if text.startswith(("http://", "https://")):
        return ""
    if text.startswith("file://"):
        return text
    if text in {".", ".."}:
        return text
    if text.startswith(("/", "~", "./", "../", "$")):
        return text
    if "/" in text:
        return text
    return ""


def _command_candidates(command: str) -> Iterator[str]:
    """Every path-shaped candidate in a shell command, tokens first, then raw substrings.

    The raw scan is what catches a path inside a heredoc or ``python -c``: those are not
    separate shell tokens to us, but they are still text the shell will hand to a program.
    """
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        tokens = command.split()
    seen: set[str] = set()
    for token in tokens:
        candidate = _candidate(token)
        if candidate and candidate not in seen:
            seen.add(candidate)
            yield candidate
    for match in _PATH_LIKE.finditer(command):
        candidate = _candidate(match.group(1))
        if candidate and candidate not in seen:
            seen.add(candidate)
            yield candidate


class Scope:
    """The paths one profile may use, and the refusal for anything else.

    ``for_profile`` is the constructor tests use; ``current`` is the engine-facing one.
    """

    def __init__(
        self,
        profile: Path,
        workspace: Path,
        *,
        hermes_root: Path | None = None,
        home: Path | None = None,
    ):
        self.profile = Path(profile).expanduser().resolve()
        self.workspace = Path(workspace).expanduser().resolve()
        if hermes_root is None:
            parent = self.profile.parent
            hermes_root = parent.parent if parent.name == "profiles" else parent
        self.hermes_root = Path(hermes_root).expanduser().resolve()
        self.home = (Path(home) if home is not None else _subprocess_home(self.profile)).resolve()
        self.workspace_parent = self.workspace.parent
        # Uploaded files are the operator's route for anything outside the workspace. A created
        # profile keeps them under its own directory; the installed profile still uses the BFF's
        # default store beside the checkout. The `.pantler-profile.json` marker is what the app
        # writes for a created profile — the installed one predates it — so a created profile
        # never inherits the install's uploads.
        self.attachments = [self.profile / "attachments"]
        if not (self.profile / ".pantler-profile.json").is_file():
            legacy = self.workspace_parent.parent / ".data" / "attachments"
            if legacy.is_dir():
                self.attachments.append(legacy)
        # The checkout's `examples/` is product sample data, not a business. The dev suite and
        # the soil test use it; a provisioned install has no such directory and gets no root.
        self.samples: list[Path] = []
        samples = self.workspace_parent.parent / "examples"
        if samples.is_dir():
            self.samples.append(samples)

    # -- construction ----------------------------------------------------

    @classmethod
    def for_profile(
        cls,
        profile: str | Path,
        workspace: str | Path | None = None,
        *,
        hermes_root: str | Path | None = None,
        home: str | Path | None = None,
    ) -> "Scope":
        profile_path = Path(profile).expanduser().resolve()
        if workspace is None:
            workspace_path = profile_path / "workspace"
        else:
            workspace_path = Path(workspace).expanduser().resolve()
        # A profile whose config still points at the shared root is a misconfiguration. The
        # dev migration fixes it; until then, prefer the profile's own child when it exists
        # so the shared siblings are not treated as part of this workspace.
        if workspace_path.name != profile_path.name:
            own = (workspace_path / profile_path.name).resolve()
            if own.is_dir():
                workspace_path = own
        return cls(profile_path, workspace_path, hermes_root=hermes_root, home=home)

    @classmethod
    def current(cls) -> "Scope | None":
        """The scope of the profile this turn is being served for, or None outside one."""
        profile = _active_profile()
        if profile is None:
            return None
        workspace = _configured_cwd(profile)
        return cls.for_profile(profile, workspace or profile / "workspace")

    # -- path decisions --------------------------------------------------

    def resolves(self, raw: str | Path, *, cwd: Path | None = None) -> Path | None:
        """Resolve *raw* the way the tool will, or None when it is not a path."""
        text = str(raw).strip()
        if not text:
            return None
        if text.startswith("file://"):
            text = unquote(urlparse(text).path)
        if text.startswith(("http://", "https://")):
            return None
        text = _candidate(text) or text
        text = text.strip("'\"")
        text = text.replace("${HERMES_HOME}", str(self.hermes_root)).replace(
            "$HERMES_HOME", str(self.hermes_root)
        )
        text = text.replace("${PWD}", str(cwd or self.workspace)).replace(
            "$PWD", str(cwd or self.workspace)
        )
        text = text.replace("${HOME}", str(self.home)).replace("$HOME", str(self.home))
        if text == "~" or text.startswith("~/"):
            text = str(self.home) + text[1:]
        text = os.path.expandvars(text)
        if not os.path.isabs(text):
            text = os.path.join(str(cwd or self.workspace), text)
        try:
            return Path(text).resolve(strict=False)
        except (OSError, RuntimeError):
            return None

    def refusal_for_path(self, raw: str | Path, *, cwd: Path | None = None) -> str | None:
        resolved = self.resolves(raw, cwd=cwd)
        if resolved is None:
            return None
        if self._secret(resolved):
            return SECRET
        if _under(resolved, self.workspace):
            return None
        if _under(resolved, self.profile):
            return None
        if any(_under(resolved, root) for root in self.attachments):
            return None
        if any(_under(resolved, root) for root in self.samples):
            return None
        if _under(resolved, self.hermes_root):
            return OTHER_BUSINESS
        if resolved == self.workspace_parent or resolved in self.workspace_parent.parents:
            return OUTSIDE
        if _under(resolved, self.workspace_parent):
            return OTHER_BUSINESS
        if any(_under(resolved, root) for root in _SYSTEM_ROOTS):
            return None
        return OUTSIDE

    def _secret(self, path: Path) -> bool:
        name = path.name.lower()
        if name.startswith(".env") or name in _DENIED_NAMES:
            return True
        if name.startswith(_DENIED_PREFIXES):
            return True
        if name.endswith(_DENIED_SUFFIXES):
            return True
        stem = name.split(".", 1)[0]
        return stem in _DENIED_STEMS

    # -- tool decisions --------------------------------------------------

    def refusal_for_tool(self, tool_name: str, args: dict | None = None) -> str | None:
        args = args or {}
        if tool_name in {"read_file", "write_file", "patch", "search_files"}:
            raw = args.get("path") or args.get("file_path")
            return self.refusal_for_path(raw, cwd=self.workspace) if raw else None
        if tool_name == "terminal":
            return self.refusal_for_command(
                str(args.get("command") or ""), workdir=args.get("workdir")
            )
        if tool_name == "execute_code":
            return self.refusal_for_code(str(args.get("code") or args.get("source") or ""))
        if tool_name in {"soil_test_read", "soil_amendment"}:
            raw = args.get("coa_path")
            # This tool resolves a relative path against the gateway process, not the
            # terminal's workspace; use the same base here so the two agree.
            return self.refusal_for_path(raw, cwd=Path.cwd()) if raw else None
        if tool_name == "vision_analyze":
            raw = args.get("image_url")
            if not raw:
                return None
            text = str(raw).strip()
            if text.startswith(("http://", "https://", "data:")):
                return None
            return self.refusal_for_path(text, cwd=self.workspace)
        if tool_name.startswith("browser_"):
            url = args.get("url")
            if not url:
                return None
            parsed = urlparse(str(url))
            if parsed.scheme != "file":
                return None
            return self.refusal_for_path(unquote(parsed.path), cwd=self.workspace)
        return None

    def refusal_for_command(self, command: str, *, workdir: str | Path | None = None) -> str | None:
        cwd = self.workspace
        if workdir:
            raw_workdir = str(workdir)
            if os.path.isabs(os.path.expanduser(raw_workdir)):
                cwd = Path(os.path.expanduser(raw_workdir)).resolve()
            else:
                cwd = (self.workspace / raw_workdir).resolve()
            refusal = self.refusal_for_path(raw_workdir, cwd=self.workspace)
            if refusal:
                return refusal
        if not command:
            return None
        for candidate in _command_candidates(command):
            refusal = self.refusal_for_path(candidate, cwd=cwd)
            if refusal:
                return refusal
        return None

    def refusal_for_code(self, code: str) -> str | None:
        if not code:
            return None
        for _quote, value in _QUOTED.findall(code):
            if not value or value.startswith(("http://", "https://", "data:")):
                continue
            if value.startswith("file://") or _candidate(value) == value:
                refusal = self.refusal_for_path(value, cwd=self.workspace)
                if refusal:
                    return refusal
        return None


# -- engine-facing resolution ------------------------------------------------


def _active_profile() -> Path | None:
    """The active profile, from the engine's per-turn scope, then a cautious fallback."""
    try:
        from hermes_constants import get_hermes_home

        home = Path(get_hermes_home()).expanduser().resolve()
        if (home / "config.yaml").is_file() or home.parent.name == "profiles":
            return home
    except Exception:
        pass

    env = os.environ.get("HERMES_HOME", "").strip()
    if not env:
        return None
    home = Path(env).expanduser().resolve()
    if (home / "config.yaml").is_file():
        return home
    try:
        active = (home / "active_profile").read_text(encoding="utf-8").strip()
    except OSError:
        active = ""
    if active:
        candidate = (home / "profiles" / active).resolve()
        if (candidate / "config.yaml").is_file():
            return candidate
    return None


def _configured_cwd(profile: Path) -> Path | None:
    """``terminal.cwd`` for the active profile.

    The config is read first because it is the stable anchor; the engine's per-turn value is a
    fallback for a profile whose cwd is configured somewhere this reader does not parse. A
    session's own ``cd`` must never move the boundary.
    """
    candidates: list[str] = []
    config = profile / "config.yaml"
    try:
        section = ""
        for line in config.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if not line[:1].isspace():
                section = line.partition(":")[0].strip()
                continue
            if section != "terminal":
                continue
            key, _, value = line.strip().partition(":")
            if key.strip() == "cwd":
                candidates.append(value.strip().strip("'\""))
    except OSError:
        pass
    try:
        from agent.runtime_cwd import scope_terminal_cwd

        candidates.append(scope_terminal_cwd())
    except Exception:
        pass
    for raw in candidates:
        text = str(raw or "").strip()
        if text and os.path.isabs(os.path.expanduser(os.path.expandvars(text))):
            return Path(os.path.expanduser(os.path.expandvars(text))).resolve()
    return None


def _subprocess_home(profile: Path) -> Path:
    try:
        from hermes_constants import get_subprocess_home

        home = get_subprocess_home()
        if home:
            return Path(home).expanduser().resolve()
    except Exception:
        pass
    candidate = profile / "home"
    return candidate.resolve() if candidate.is_dir() else Path.home().resolve()


# -- hook --------------------------------------------------------------------


def pre_tool_call(tool_name: str, args: dict | None = None, **kwargs) -> dict | None:
    """Refuse a tool call that would leave this business's profile.

    A hook exception is allowed to reach the engine, which fails closed and names the
    callback. Silently allowing on an unexpected error would turn the boundary off.
    """
    scope = Scope.current()
    if scope is None:
        return None
    message = scope.refusal_for_tool(tool_name, args)
    if not message:
        return None
    logger.warning("Profile scope refused %s (outside this business's profile)", tool_name)
    return {"action": "block", "message": message}


__all__ = [
    "OTHER_BUSINESS",
    "OUTSIDE",
    "SECRET",
    "Scope",
    "pre_tool_call",
]
