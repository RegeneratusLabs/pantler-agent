"""Engine settings — the installed tier's local-file settings surface.

the front-end design §2 records that the engine advertises `admin_config_rw: false`,
and §7 punts the consequence to us: *"No settings UI over the seam. Installed tier must use
local files; hosted defers."* Verified live against engine 0.21.6 and re-verified in source at
0.22.1 (no route matching `config` in the api server's route table), that is exactly right —
every dashboard settings route is absent from the gateway:

    /api/config          404      /api/config/schema   404
    /api/env             404      /api/model/set       404
    /api/model/options   200  ← the only settings-shaped route we get

So there is no settings API to call. What the engine actually reads at startup is two files
in the profile, and this module edits those:

    profiles/<name>/config.yaml     the `model:` block, plus the keys we own under `agent:`
    profiles/<name>/.env            secrets, as KEY=VALUE

Three rules it will not break:

1. **A secret value is never returned.** Callers see ``is_set``, never the value. The only
   way a key leaves the machine is by the engine using it.
2. **`config.yaml` is edited surgically, never regenerated.** The `model:` block is replaced
   from its own parsed keys and the `agent:` keys are replaced line by line; every other byte is
   preserved. A block that is not a shape we understand is *refused* rather than guessed at —
   the file is an operator's configuration, and a bad guess breaks their agent.
3. **Every write is atomic and backed up.** Write to a sibling temp file, `os.replace`, and
   keep a `.bak` of what was there. A half-written `.env` is an engine that will not start.

This is deliberately *not* in `pantler_core`. The kernel is domain logic and engine-agnostic;
this module knows the engine's on-disk layout, which is a front-end concern.
"""

from __future__ import annotations

import functools
import os
import re
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Any, Callable, Iterable

# An env name the engine will actually read. Mirrors the guard Hermes uses for the same job
# (`hermes_cli/config.py::_ENV_VAR_NAME_RE`), because accepting a name it silently ignores is
# worse than refusing it.
ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# ...and the other half of that guard, which this module used to be missing
# (the internal security audit A19-CFG-1): the engine's own denylist of names whose
# *effect* is execution rather than configuration. Copied name-for-name from
# `hermes_cli/config.py::_ENV_VAR_NAME_DENYLIST` and `_ENV_VAR_NAME_DENY_PREFIXES` at the pin;
# `app/server/tests/test_settings.py` compares the two sets when the engine source is present,
# so a re-pin that grows the engine's list fails here rather than silently reopening the hole.
ENV_NAME_DENY_PREFIXES = ("LD_", "DYLD_", "GIT_CONFIG_")
ENV_NAME_DENYLIST = frozenset(
    {
        "BASH_ENV", "BROWSER", "CLASSPATH", "DYLD_FALLBACK_FRAMEWORK_PATH",
        "DYLD_FALLBACK_LIBRARY_PATH", "DYLD_FRAMEWORK_PATH", "DYLD_INSERT_LIBRARIES",
        "DYLD_LIBRARY_PATH", "EDITOR", "ENV", "EXINIT", "GIT_ASKPASS", "GIT_DIR", "GIT_EDITOR",
        "GIT_EXEC_PATH", "GIT_EXTERNAL_DIFF", "GIT_PAGER", "GIT_PROXY_COMMAND",
        "GIT_SEQUENCE_EDITOR", "GIT_SHELL", "GIT_SSH", "GIT_SSH_COMMAND", "GIT_TEMPLATE_DIR",
        "GOFLAGS", "HERMES_ACCEPT_HOOKS", "HERMES_CONFIG", "HERMES_CONFIG_PATH",
        "HERMES_COPILOT_ACP_ARGS", "HERMES_COPILOT_ACP_COMMAND", "HERMES_CRON_SESSION",
        "HERMES_ENV", "HERMES_ENV_PATH", "HERMES_EXEC_ASK", "HERMES_GATEWAY_SESSION",
        "HERMES_HOME", "HERMES_INTERACTIVE", "HERMES_OPTIONAL_MCPS", "HERMES_PROFILE",
        "HERMES_REDACT_SECRETS", "HERMES_SESSION_KEY", "HERMES_SESSION_PLATFORM",
        "HERMES_SINGLE_QUERY_SESSION", "HERMES_YOLO_MODE", "JAVA_TOOL_OPTIONS",
        "JDK_JAVA_OPTIONS", "LD_AUDIT", "LD_DEBUG", "LD_LIBRARY_PATH", "LD_PRELOAD", "MANPAGER",
        "NODE_OPTIONS", "NODE_PATH", "PAGER", "PATH", "PERL5LIB", "PERL5OPT", "PERLLIB",
        "PROMPT_COMMAND", "PYTHONBREAKPOINT", "PYTHONCASEOK", "PYTHONEXECUTABLE", "PYTHONHOME",
        "PYTHONNOUSERSITE", "PYTHONPATH", "PYTHONSTARTUP", "PYTHONUSERBASE", "RUBYLIB",
        "RUBYOPT", "RUSTFLAGS", "SHELL", "SSH_ASKPASS", "SUDO_ASKPASS", "VIMINIT", "VISUAL",
        "ZDOTDIR", "_JAVA_OPTIONS",
    }
)

# A `key: value` line inside a block, and a top-level `key:` opener.
_SCALAR_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)$")

# Values that begin with any of these are YAML structure, not a scalar. We refuse to touch a
# block containing them rather than emit something that changes its meaning.
_STRUCTURAL_PREFIXES = ("|", ">", "&", "*", "!", "{", "[", "#")

#: A plain scalar this module is willing to emit unquoted. Deliberately strict: YAML reads a
#: leading `@` or backtick as a reserved indicator, a trailing `:` as a mapping value, and the
#: bare words `null`/`true`/`off`/`~`/`123` as something other than a string
#: (the internal security audit A19-CFG-2). Quoting those is cheaper than reasoning about
#: them, so only an unambiguous token is ever emitted bare.
_PLAIN_SAFE_RE = re.compile(r"^[A-Za-z0-9_./+][A-Za-z0-9_./+~-]*$")

#: Whatever these spell, a reader may see a boolean, a null or a number. Quote them. `.inf` and
#: `.nan` are YAML's own float spellings, which Python's `float()` does not recognise and YAML
#: does, so they cannot be caught by the `float()` check below.
_YAML_WORDS = frozenset(
    {
        "y", "n", "yes", "no", "true", "false", "on", "off", "null", "none", "~", "nan", "inf",
        ".inf", ".nan",
    }
)


#: Characters YAML will not start a plain scalar with, plus the first character of each
#: indicator pair. A value that begins with one of these is quoted.
_UNSAFE_FIRST = frozenset("-?:,[]{}#&*!|>'\"%@`")


def _plain_ok(value: str) -> bool:
    """Whether `value` can be written as a plain scalar and still read back as this string."""
    if not value or value != value.strip():
        return False
    if value[0] in _UNSAFE_FIRST:
        return False
    if value.endswith(":") or ": " in value or " #" in value or "\t#" in value:
        return False
    if any(ord(ch) < 0x20 for ch in value):
        return False
    if value.lower() in _YAML_WORDS:
        return False
    try:
        float(value)  # `123`, `1e5`, `.inf`: a number, not the string we were handed
    except ValueError:
        return True
    return False


def _quote(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    if any(ord(ch) < 0x20 for ch in escaped):
        raise SettingsError(
            "that value contains a control character, which cannot be written to config.yaml",
            "bad_value",
        )
    return f'"{escaped}"'


def _scalar(value: str) -> str:
    """Render one YAML scalar, quoting unless the value is unambiguous as a plain string.

    The old rule emitted anything matching ``^[A-Za-z0-9_./:@+~-]+$`` bare, which produced
    `provider: @evil` (a scanner error), `provider: x:` (a mapping value) and `provider: off`
    (the boolean false) — a settings write that either broke the file or silently changed its
    meaning (the internal security audit A19-CFG-2).
    """
    value = "" if value is None else str(value)
    return value if _plain_ok(value) else _quote(value)


def _scalar_literal(value: str) -> str:
    """A scalar the *caller* has validated as a YAML literal on purpose.

    One key needs this: `agent.reasoning_effort: false` is written as the boolean, because that
    is the spelling the engine documents for "do not think". Every caller has already checked the
    value against a closed vocabulary (REASONING_EFFORTS / REASONING_DISABLED_SPELLINGS), so
    nothing else can reach here.
    """
    return value if value == REASONING_DISABLED else _scalar(value)

# The keys of the `model:` block we are willing to write. Anything else in that block is
# preserved untouched.
WRITABLE_MODEL_KEYS = ("provider", "default", "base_url", "api_mode", "key_env")

# The one key under `agent:` this module owns: the engine's global suppression list, which
# is subtracted *last* from whatever a platform enables. It is the honest way to switch a
# capability off — the tools really disappear, rather than being hidden in a UI. Every other
# line of the `agent:` block is preserved untouched.
AGENT_BLOCK = "agent"
DISABLED_TOOLSETS_KEY = "disabled_toolsets"

# The second key we own under `agent:`: how hard the engine thinks before it answers.
#
# The vocabulary is the engine's own, not ours. `agent/reasoning_effort.py` accepts these seven
# levels and `clamp_effort` knocks a request *down* to the nearest level the route actually
# supports, so a level written here is a preference about effort, never a promise about what
# reaches the wire. `hermes_constants.py` additionally reads `none`, `false` and `disabled` as
# "do not think"; we write the canonical `false` and accept the other two on input, because an
# operator who hand-wrote `none` means exactly that.
#
# An unrecognised value is silently ignored by the engine — it falls back to its own default —
# so the writer refuses anything outside this vocabulary rather than writing a line that does
# nothing at all. Same rule as `ENV_NAME_RE` and `TOOLSET_NAME_RE`: accepting a name the engine
# ignores is worse than refusing it.
REASONING_EFFORT_KEY = "reasoning_effort"
REASONING_EFFORTS = ("minimal", "low", "medium", "high", "xhigh", "max", "ultra")
REASONING_DISABLED = "false"
REASONING_DISABLED_SPELLINGS = frozenset({"none", "false", "disabled"})

# A toolset name the engine will recognise — the names `GET /v1/toolsets` returns (`records`,
# `web`, `code_execution`, …). Accepting a name the engine silently ignores is worse than
# refusing it, the same rule `ENV_NAME_RE` enforces for `.env`.
TOOLSET_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")

# The `skills:` block's suppression list. Skill names carry hyphens (`sdlc-review`), and the
# engine also matches a `load_name` — the relative path a same-tier duplicate is listed under
# (`a/one`) or a plugin namespace (`category:skill`). So this is wider than a toolset name.
SKILLS_BLOCK = "skills"
DISABLED_SKILLS_KEY = "disabled"
SKILL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")

# `skills.disabled` cannot switch these off: `agent.skill_utils.get_disabled_skill_names`
# subtracts ESSENTIAL_SKILLS after reading the list. Kept here so the API can say so rather
# than accept a write the engine would ignore.
ESSENTIAL_SKILLS = frozenset({"hermes-agent"})

# --- plugins, MCP servers and connectors -----------------------------------------------
#
# The capability registry (`capabilities.py`) needs to read every switch in this file, and its
# write path needs to flip three of them. Two of those are nested, which is why they are read
# leniently and written narrowly: the file belongs to the operator, and a switch that rewrote
# more than the line it owns would be a worse bug than a switch that refuses.

PLUGINS_BLOCK = "plugins"
ENABLED_PLUGINS_KEY = "enabled"
DISABLED_PLUGINS_KEY = "disabled"
# A plugin id, as the profile's own directories and the engine's config write it
# (`pantler`, `soil-amendment`). Narrower than a path, wider than a toolset name.
PLUGIN_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
# Plugin setting keys are the engine's own: lower snake case, as `plugin.yaml` declares them.
SETTING_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")

MCP_BLOCK = "mcp_servers"
MCP_ENABLED_KEY = "enabled"
NESTED_BLOCK = "tools"
CONNECTORS_KEY = "connectors"

# The live half of a plugin switch. The engine's own plugin lists are restart-grade — its CLI
# says so in as many words, "there is no un-wire primitive, so a running gateway keeps the
# plugin's handlers until restart" — which leaves a tool that is already registered callable
# until the process restarts. `plugins.entries.<id>.settings.capability_enabled` is read by the
# plugin itself on every call (`ctx.get_config`, a mtime-keyed config read), so the handler can
# refuse in a sentence while its schema is still visible. One switch, two keys, two latencies:
# this one is immediate; the engine's list is what makes the tool disappear entirely.
ENTRIES_KEY = "entries"
SETTINGS_KEY = "settings"
CAPABILITY_KEY = "capability_enabled"

# The two states a capability can be in, and what the engine does with a write. Not a promise
# about *when* an already-open conversation changes: see `app/server/README.md`.
APPLIES_LIVE = "new_conversations"
APPLIES_RESTART = "next_restart"


def _key_re(key: str) -> re.Pattern[str]:
    """`key: value` at any indent inside a block, capturing the value."""
    return re.compile(rf"^[ \t]+{re.escape(key)}[ \t]*:[ \t]*(.*)$")


class SettingsError(Exception):
    """A refusal the caller can show. Never a partial write."""

    def __init__(self, message: str, code: str = "settings_error"):
        super().__init__(message)
        self.message = message
        self.code = code


def _serialised(method: Callable[..., Any]) -> Callable[..., Any]:
    """Run one settings write at a time on this profile.

    Every writer below is read-modify-write: it parses `config.yaml`, changes one line and
    rewrites the file. `ThreadingHTTPServer` means two of those can overlap, and the second
    would rewrite the file from the state it read before the first wrote — losing a change
    that was already answered 200 (the internal audit BFF-11). The lock lives on the
    profile, so it also covers a settings write racing a capability switch.
    """

    @functools.wraps(method)
    def wrapper(self: "EngineProfile", *args: Any, **kwargs: Any) -> Any:
        with self._write_lock:
            return method(self, *args, **kwargs)

    return wrapper


# ------------------------------------------------------------------ YAML bits


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _find_block(lines: list[str], key: str) -> tuple[int, int] | None:
    """Line span of a top-level `key:` block, exclusive of trailing blanks."""
    start = None
    for index, line in enumerate(lines):
        if line.startswith(f"{key}:"):
            start = index
            break
    if start is None:
        return None

    end = start + 1
    while end < len(lines):
        line = lines[end]
        if line.strip() == "" or line[0] in " \t":
            end += 1
            continue
        break

    # Do not swallow the blank line that separates this block from the next one.
    while end - 1 > start and lines[end - 1].strip() == "":
        end -= 1
    return start, end


def parse_scalar_block(block: list[str]) -> dict[str, str]:
    """Parse a flat mapping of scalars, or raise if it is anything else.

    Everything here exists to refuse rather than guess. Two shapes that must not be read as
    flat are a nested mapping and a ragged indent: both would otherwise flatten silently, and
    a flattened `model:` block is a rewritten config.yaml.

        model:
          provider: x
          options:          ← its children are at a deeper indent, so this is nested
            nested: 1
    """
    parsed: dict[str, str] = {}
    indent: int | None = None

    for offset, raw in enumerate(block[1:], start=1):
        line = raw.strip()
        if line == "" or line.startswith("#"):
            continue
        if raw[:1] not in (" ", "\t"):
            # A second top-level key inside the span: the block is not what we think it is.
            raise SettingsError("the model block is not a simple mapping", "unexpected_shape")

        width = len(raw) - len(raw.lstrip())
        if indent is None:
            indent = width
        elif width != indent:
            raise SettingsError(
                "the model block nests deeper than one level", "unexpected_shape"
            )

        if line.startswith("- ") or line == "-":
            raise SettingsError("the model block contains a list", "unexpected_shape")
        match = _SCALAR_RE.match(line)
        if match is None:
            raise SettingsError(
                f"line {offset + 1} of the model block is not `key: value`", "unexpected_shape"
            )
        value = match.group(2).strip()
        if value.startswith(_STRUCTURAL_PREFIXES):
            raise SettingsError(f"`{match.group(1)}` is not a plain value", "unexpected_shape")
        # A key with no value at all opens a nested block; refuse it wherever it appears.
        if value == "":
            raise SettingsError(
                f"`{match.group(1)}` has no value, so it opens a nested block", "unexpected_shape"
            )
        parsed[match.group(1)] = _unquote(value)
    return parsed


def render_scalar_block(key: str, values: dict[str, str]) -> list[str]:
    return [f"{key}:", *(f"  {name}: {_scalar(value)}" for name, value in values.items())]


def _parse_name_list(value: str, key: str, name_re: re.Pattern[str], kind: str) -> list[str]:
    """A name list as YAML, or as the engine's own scalar-or-JSON-array string.

    Mirrors `agent.skill_utils.parse_config_string_list`, so `[a, b]`, `'["a"]'` and a bare
    `a` all mean a list. Anything else raises: guessing here rewrites config.yaml.
    """
    text = _unquote(value.strip())
    if text.startswith("["):
        if not text.endswith("]"):
            raise SettingsError(f"`{key}` is not a closed list", "unexpected_shape")
        inner = text[1:-1].strip()
        items = [] if inner == "" else [_unquote(part.strip()) for part in inner.split(",")]
    else:
        items = [text] if text else []

    names: list[str] = []
    for item in items:
        if not name_re.match(item):
            raise SettingsError(
                f"`{key}` contains {item!r}, which is not a {kind} name", "unexpected_shape"
            )
        if item not in names:
            names.append(item)
    return names


def _read_block_list(
    lines: list[str], block: str, key: str, name_re: re.Pattern[str], kind: str
) -> tuple[list[str], tuple[int, int]] | None:
    """Locate `block.key` and the line span it occupies.

    Returns None when the key is absent. Raises `SettingsError` when it is present in a shape
    this module will not rewrite — a nested mapping, a ragged sequence, a value that is not a
    valid name. Refusing is the whole point: the file is an operator's config.
    """
    found_block = _find_block(lines, block)
    if found_block is None:
        return None
    start, end = found_block

    key_re = _key_re(key)
    matches = [index for index in range(start + 1, end) if key_re.match(lines[index])]
    if not matches:
        return None
    if len(matches) > 1:
        # Two `disabled_toolsets:` lines: this module would rewrite the first and leave the
        # second, while the engine's YAML loader takes the last — so the screen would show one
        # list and the agent would honour the other. The pair is refused for the same reason a
        # duplicated scalar is (the internal audit BFF-3).
        raise SettingsError(f"`{key}` appears more than once", "unexpected_shape")
    key_index = matches[0]

    raw = lines[key_index]
    indent = len(raw) - len(raw.lstrip())
    value = key_re.match(raw).group(1).strip()

    def refuse(reason: str) -> SettingsError:
        return SettingsError(f"`{key}` {reason}", "unexpected_shape")

    if value:
        names = _parse_name_list(value, key, name_re, kind)
        # A value on the key line followed by deeper `- item` lines is malformed YAML. Rewriting
        # around it would emit a broken file, so refuse.
        for item in lines[key_index + 1 : end]:
            if item.strip() == "":
                continue
            if len(item) - len(item.lstrip()) > indent and item.strip().startswith("-"):
                raise refuse("has both a value and a nested list")
            break
        return names, (key_index, key_index + 1)

    # A bare `key:` opens a block sequence. Items must sit deeper than the key and start with
    # `-`; anything else is a shape we refuse rather than flatten.
    names = []
    cursor = key_index + 1
    while cursor < end:
        item = lines[cursor]
        if item.strip() == "":
            cursor += 1
            continue
        if len(item) - len(item.lstrip()) <= indent:
            if item.strip().startswith("-"):
                raise refuse("is not indented as a sequence")
            break
        stripped = item.strip()
        if not stripped.startswith("-"):
            raise refuse("is not a plain list of names")
        entry = _unquote(stripped[1:].strip())
        if not name_re.match(entry):
            raise refuse(f"contains {entry!r}, which is not a {kind} name")
        if entry not in names:
            names.append(entry)
        cursor += 1
    return names, (key_index, cursor)


def _scalar_without_comment(value: str) -> str:
    """A plain scalar with any YAML end-of-line comment removed.

    `reasoning_effort: low  # everyday` holds the level `low`: YAML ends a plain scalar at
    whitespace-then-`#`. Reading the comment as part of the value would make the page claim the
    engine is ignoring a level it reads perfectly well. A quoted value keeps its `#`, because
    there it is part of the string.
    """
    if value.startswith(("\"", "'")):
        return value
    match = re.search(r"[ \t]#", value)
    return value if match is None else value[: match.start()].rstrip()


def _read_block_scalar(
    lines: list[str], block: str, key: str
) -> tuple[str, tuple[int, int]] | None:
    """Locate `block.key` as one scalar line, and the line span it occupies.

    Returns None when the key is absent. Raises `SettingsError` for every shape this module will
    not rewrite: a bare `key:` that opens a nested block, a value with still-deeper lines under
    it (which is not valid YAML), a value that is really a list or a `|` block, and the key
    appearing twice — which spelling the engine's own loader would take is not something to
    guess at.
    """
    found_block = _find_block(lines, block)
    if found_block is None:
        return None
    start, end = found_block

    key_re = _key_re(key)
    matches = [index for index in range(start + 1, end) if key_re.match(lines[index])]
    if not matches:
        return None
    if len(matches) > 1:
        raise SettingsError(f"`{key}` appears more than once", "unexpected_shape")

    index = matches[0]
    raw = lines[index]
    value = key_re.match(raw).group(1).strip()
    if value == "":
        raise SettingsError(
            f"`{key}` has no value, so it opens a nested block", "unexpected_shape"
        )
    if value.startswith(_STRUCTURAL_PREFIXES):
        raise SettingsError(f"`{key}` is not a plain value", "unexpected_shape")

    indent = len(raw) - len(raw.lstrip())
    for item in lines[index + 1 : end]:
        if item.strip() == "":
            continue
        if len(item) - len(item.lstrip()) > indent:
            raise SettingsError(f"`{key}` has both a value and a nested block", "unexpected_shape")
        break

    return _unquote(_scalar_without_comment(value)), (index, index + 1)


def _block_header_is_bare(line: str, block: str) -> bool:
    """Whether `block:` carries no value — the only header a child line can be added under.

    `agent: {disabled_toolsets: [web]}` is a valid file and an impossible parent: YAML forbids
    block children under a flow mapping, so inserting a line there would emit a broken config.
    """
    rest = line[len(block) + 1 :]
    comment = rest.find("#")
    if comment != -1:
        rest = rest[:comment]
    return rest.strip() == ""


def _block_can_take_a_child(lines: list[str], block: str) -> bool:
    """Whether `block` is absent (so we would create it) or bare enough to insert under."""
    span = _find_block(lines, block)
    return span is None or _block_header_is_bare(lines[span[0]], block)


def _normalize_reasoning_effort(value: Any) -> str:
    """The spelling to write for one requested level, or a refusal.

    Everything is written as one of `REASONING_EFFORTS` or the canonical `false`, so the file
    says one thing rather than three: `none` and `disabled` are the engine's other spellings for
    "off", and a JSON `false` is the same choice typed the way the engine types it. Levels are
    matched exactly, because the engine compares strings and would silently ignore `Low`; the
    refusal names the vocabulary instead of leaving the operator with a setting that does nothing.
    """
    if isinstance(value, bool):
        if value is False:
            return REASONING_DISABLED
        raise SettingsError(
            f"`{REASONING_EFFORT_KEY}` cannot be true — write one of "
            f"{', '.join(REASONING_EFFORTS)}, or false to switch thinking off",
            "bad_value",
        )
    if not isinstance(value, str):
        raise SettingsError(f"`{REASONING_EFFORT_KEY}` must be a string", "bad_value")

    text = value.strip()
    # Case-insensitively, because YAML's own booleans arrive as `False`/`TRUE` and all of them
    # mean the same thing to the engine's reader. A *level* in the wrong case stays a refusal:
    # it is the spelling, not the intent, that the engine matches on.
    if text.lower() in REASONING_DISABLED_SPELLINGS:
        return REASONING_DISABLED
    if text not in REASONING_EFFORTS:
        raise SettingsError(
            f"{value!r} is not a reasoning level the engine reads — write one of "
            f"{', '.join(REASONING_EFFORTS)}, or false to switch thinking off",
            "bad_value",
        )
    return text


def _write_block_list(
    lines: list[str],
    block: str,
    key: str,
    names: list[str],
    found: tuple[list[str], tuple[int, int]] | None,
) -> list[str]:
    """Replace one `block.key` line with an inline list, preserving every other line."""
    rendered = f"{key}: [{', '.join(names)}]"
    return _write_block_entry(lines, block, rendered, None if found is None else found[1])


def _write_block_entry(
    lines: list[str], block: str, rendered: str, found: tuple[int, int] | None
) -> list[str]:
    """Replace one line of `block` with `rendered`, or insert it, preserving every other line."""
    if found is None:
        span = _find_block(lines, block)
        if span is None:
            head = lines if not lines or lines[-1].strip() == "" else [*lines, ""]
            return [*head, f"{block}:", f"  {rendered}", ""]
        start, end = span
        if not _block_header_is_bare(lines[start], block):
            raise SettingsError(
                f"the `{block}:` line carries its mapping on one line, so a child cannot be "
                f"added under it",
                "unexpected_shape",
            )
        indent = _block_indent(lines, start, end)
        return [*lines[: start + 1], f"{indent}{rendered}", *lines[start + 1 :]]

    key_start, key_end = found
    indent = lines[key_start][: len(lines[key_start]) - len(lines[key_start].lstrip())]
    return [*lines[:key_start], f"{indent}{rendered}", *lines[key_end:]]


def _read_disabled_toolsets(lines: list[str]) -> tuple[list[str], tuple[int, int]] | None:
    return _read_block_list(lines, AGENT_BLOCK, DISABLED_TOOLSETS_KEY, TOOLSET_NAME_RE, "toolset")


def _block_indent(lines: list[str], start: int, end: int) -> str:
    """The indentation an existing block already uses, so an inserted key matches it."""
    for line in lines[start + 1 : end]:
        if line.strip():
            return line[: len(line) - len(line.lstrip())]
    return "  "


def _lenient_name_list(value: str) -> list[str]:
    """A name list read for information, not rewritten. No validation, no refusal."""
    text = _unquote(value.strip())
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        items = [] if inner == "" else [_unquote(part.strip()) for part in inner.split(",")]
    else:
        items = [text] if text else []
    return [item for item in items if item]


def _read_disabled_skills(lines: list[str]) -> list[str]:
    """`skills.disabled` as written, or [] when absent.

    A read-only path: this only needs to know which names the engine would filter, so a shape
    it does not understand reads as "nothing disabled" rather than refusing. The write path
    (there is none today) would be the place to be strict.
    """
    block = _find_block(lines, SKILLS_BLOCK)
    if block is None:
        return []
    start, end = block

    key_re = _key_re(DISABLED_SKILLS_KEY)
    key_index = next((i for i in range(start + 1, end) if key_re.match(lines[i])), None)
    if key_index is None:
        return []

    raw = lines[key_index]
    indent = len(raw) - len(raw.lstrip())
    value = key_re.match(raw).group(1).strip()
    if value:
        return _lenient_name_list(value)

    names: list[str] = []
    cursor = key_index + 1
    while cursor < end:
        item = lines[cursor]
        if item.strip() == "":
            cursor += 1
            continue
        if len(item) - len(item.lstrip()) <= indent:
            break
        stripped = item.strip()
        if stripped.startswith("-"):
            entry = _unquote(stripped[1:].strip())
            if entry:
                names.append(entry)
        cursor += 1
    return names


def _lenient_block_list(lines: list[str], block: str, key: str) -> list[str]:
    """`block.key` as a name list, read for information.

    The counterpart to `_read_block_list`: no validation and no refusal, because a reader that
    refuses to describe a file is worse than one that describes it approximately. A shape this
    does not understand reads as "nothing here", which is what a screen should show.
    """
    span = _find_block(lines, block)
    if span is None:
        return []
    start, end = span
    key_re = _key_re(key)
    for index in range(start + 1, end):
        match = key_re.match(lines[index])
        if match is None:
            continue
        value = match.group(1).strip()
        if value:
            return _lenient_name_list(value)
        indent = len(lines[index]) - len(lines[index].lstrip())
        names: list[str] = []
        for item in lines[index + 1 : end]:
            if not item.strip():
                continue
            if len(item) - len(item.lstrip()) <= indent:
                break
            if item.strip().startswith("-"):
                names.append(_unquote(item.strip()[1:].strip()))
        return [name for name in names if name]
    return []


def _child_key(line: str) -> tuple[str, int] | None:
    """`(key, indent)` for a mapping line, or None for anything else. A reader's parser."""
    if not line.strip() or line.lstrip().startswith("#"):
        return None
    match = re.match(r"^(\s*)([^:#]+):", line)
    if match is None:
        return None
    return _unquote(match.group(2).strip()), len(match.group(1))


def _mcp_servers_from(lines: list[str]) -> dict[str, bool]:
    """`mcp_servers.<name>.enabled`, read for information.

    A server with no `enabled` line is on — the engine's own default — so absence reads as
    enabled rather than as unknown. Nested blocks are walked by indentation, never by a YAML
    parser, because this module has no dependency and the file belongs to the operator.
    """
    span = _find_block(lines, MCP_BLOCK)
    if span is None:
        return {}
    start, end = span
    parent_indent = len(lines[start]) - len(lines[start].lstrip())
    servers: dict[str, bool] = {}
    index = start + 1
    while index < end:
        child = _child_key(lines[index])
        if child is None:
            index += 1
            continue
        name, indent = child
        if indent <= parent_indent:
            break
        enabled = True
        cursor = index + 1
        while cursor < end:
            line = lines[cursor]
            if line.strip() and (len(line) - len(line.lstrip())) <= indent:
                break
            match = _key_re(MCP_ENABLED_KEY).match(line)
            if match is not None:
                enabled = match.group(1).strip().lower() not in ("false", "off", "no")
                cursor += 1
                break
            cursor += 1
        if name:
            servers[name] = enabled
        index = cursor if cursor > index else index + 1
    return servers


def _child_block_span(lines: list[str], start: int, end: int, name: str) -> tuple[int, int] | None:
    """The line span of one `mcp_servers.<name>:` block, or None when it is not there."""
    parent_indent = len(lines[start]) - len(lines[start].lstrip())
    for index in range(start + 1, end):
        child = _child_key(lines[index])
        if child is None:
            continue
        child_name, indent = child
        if indent <= parent_indent:
            break
        if child_name != name:
            continue
        cursor = index + 1
        while cursor < end:
            line = lines[cursor]
            if line.strip() and (len(line) - len(line.lstrip())) <= indent:
                break
            cursor += 1
        return index, cursor
    return None


def _ensure_block(lines: list[str], path: tuple[str, ...]) -> tuple[list[str], tuple[int, int]]:
    """`lines` with `path` present as nested mappings, and the span of the deepest one.

    Creating structure is the one thing the other writers refuse to do — they edit a key that
    exists and refuse a shape they do not understand, because the file belongs to the operator.
    This is the deliberate exception: a capability switch must be able to reach a plugin's own
    settings subtree on a profile whose `plugins:` block has never had an `entries:` key, or a
    fresh install could not switch anything off. It adds only the keys it was asked for.
    """
    current = list(lines)
    span = _find_block(current, path[0])
    if span is None:
        if current and current[-1].strip():
            current.append("")
        current.append(f"{path[0]}:")
        span = (len(current) - 1, len(current))
    for key in path[1:]:
        start, end = span
        # Every parent on the way down must be a bare `key:` header. `_write_block_entry` refuses
        # a flow mapping; this one used to insert a block child under one anyway, which produced
        # a config.yaml no parser accepts (the internal security audit A19-CFG-4).
        parent = current[start].strip()
        if not _block_header_is_bare(parent, parent.partition(":")[0].strip()):
            raise SettingsError(
                f"{parent.strip()!r} carries its value inline, so a setting cannot be written "
                "under it without rewriting the operator's file",
                "bad_shape",
            )
        child = _child_block_span(current, start, end, key)
        if child is None:
            # Two spaces deeper than the block's own key line. Not `_block_indent`: a block with
            # no children yet would give the default, which is shallower than a nested parent's
            # own indent, and the new key would land outside the block it belongs to.
            parent_indent = len(current[start]) - len(current[start].lstrip())
            current.insert(end, f"{' ' * (parent_indent + 2)}{key}:")
            child = (end, end + 1)
        span = child
    return current, span


def _write_in_span(lines: list[str], span: tuple[int, int], key: str, rendered: str) -> list[str]:
    """Set one `key: value` line inside a known block span, replacing it or adding it.

    The indent is the span's own key plus two, not the indent of whatever line happens to
    follow: a block that has no children yet — a freshly created `settings:` — must still get
    a child deeper than itself, or the line lands as a sibling and the next write cannot find
    it again.
    """
    start, end = span
    key_re = _key_re(key)
    for index in range(start + 1, end):
        if key_re.match(lines[index]):
            indent = lines[index][: len(lines[index]) - len(lines[index].lstrip())]
            return [*lines[:index], f"{indent}{rendered}", *lines[index + 1 :]]
    parent_indent = len(lines[start]) - len(lines[start].lstrip())
    return [*lines[:end], f"{' ' * (parent_indent + 2)}{rendered}", *lines[end:]]


def _flag_value(lines: list[str], span: tuple[int, int], key: str) -> bool | None:
    """`key` as a boolean inside a block span, or None when the block does not say.

    The engine's booleans are YAML's, and a hand-edited file may carry any of them; reading
    `false`, `off` and `no` as off costs nothing and stops a switch from looking stuck on.
    """
    start, end = span
    for index in range(start + 1, end):
        match = _key_re(key).match(lines[index])
        if match is not None:
            return match.group(1).strip().lower() not in ("false", "off", "no")
    return None


def _nested_block(lines: list[str], span: tuple[int, int], key: str) -> tuple[int, int] | None:
    """The span of a named child block inside a block, walked by indentation."""
    return _child_block_span(lines, span[0], span[1], key)


def _read_list_items(lines: list[str], key: str) -> set[str]:
    """A top-level `key:` list — inline or block sequence — as a set of names."""
    block = _find_block(lines, key)
    if block is None:
        return set()
    start, end = block

    inline = lines[start].partition(":")[2].strip()
    if inline:
        return set(_lenient_name_list(inline))

    return {
        _unquote(line.strip()[1:].strip())
        for line in lines[start + 1 : end]
        if line.strip().startswith("-") and _unquote(line.strip()[1:].strip())
    }


def _read_nested_list_items(lines: list[str], key: str) -> set[str]:
    """Every name in a top-level `key:` mapping whose children are lists (`platform_toolsets`)."""
    block = _find_block(lines, key)
    if block is None:
        return set()
    start, end = block

    names: set[str] = set()
    cursor = start + 1
    while cursor < end:
        line = lines[cursor]
        if line.strip() == "" or line[:1] not in (" ", "\t"):
            cursor += 1
            continue
        stripped = line.strip()
        if stripped.startswith("-"):
            names.add(_unquote(stripped[1:].strip()))
            cursor += 1
            continue

        _, _, value = stripped.partition(":")
        value = value.strip()
        child_indent = len(line) - len(line.lstrip())
        cursor += 1
        if value:
            names.update(_lenient_name_list(value))
            continue
        # A child header (`api_server:`) followed by a deeper block sequence.
        while cursor < end:
            deeper = lines[cursor]
            if deeper.strip() == "":
                cursor += 1
                continue
            if len(deeper) - len(deeper.lstrip()) <= child_indent:
                break
            if deeper.strip().startswith("-"):
                names.add(_unquote(deeper.strip()[1:].strip()))
            cursor += 1

    return {name for name in names if name}


def _atomic_write(path: Path, text: str, *, mode: int | None = None) -> None:
    """Replace a file wholesale, or leave the original exactly as it was."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    temp = Path(temp_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        if mode is not None:
            os.chmod(temp, mode)
        elif path.exists():
            os.chmod(temp, path.stat().st_mode & 0o777)
        os.replace(temp, path)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise


def _backup(path: Path) -> None:
    """Keep the previous file beside it — 0600, and never through a planted link.

    `shutil.copy2` preserves the *source* mode, so a `.env` that started 0644 stayed 0644 in the
    backup while the new file was 0600 — a credential copy left world-readable — and a `.env.bak`
    that is a symlink made the write follow it out of the profile
    (the internal security audit A19-CFG-6). The engine's own `config_backups` refuses
    exactly that link; so does this.
    """
    if not path.exists():
        return
    destination = path.with_name(path.name + ".bak")
    if destination.is_symlink():
        raise SettingsError(
            f"{destination.name} is a symlink, so it will not be written",
            "bad_backup",
        )
    shutil.copy2(path, destination)
    try:
        os.chmod(destination, 0o600)
    except OSError:
        pass


# ------------------------------------------------------------------- the profile


class EngineProfile:
    """Read and write one engine profile's local settings files."""

    def __init__(self, directory: Path):
        self.dir = directory
        self.config_path = directory / "config.yaml"
        self.env_path = directory / ".env"
        # One writer at a time: every setter below is read-modify-write over a file that a
        # second request could be editing at the same moment (`_serialised`).
        self._write_lock = threading.RLock()

    # -- availability -----------------------------------------------------

    @property
    def name(self) -> str:
        return self.dir.name

    @property
    def available(self) -> bool:
        return self.dir.is_dir() and (self.config_path.is_file() or self.env_path.is_file())

    # -- config.yaml ------------------------------------------------------

    def _config_lines(self) -> list[str]:
        if not self.config_path.is_file():
            return []
        return self.config_path.read_text(encoding="utf-8").splitlines()

    def model(self) -> dict[str, str]:
        """The `model:` block as written, or an empty mapping when there is none.

        A block we cannot parse reads as empty rather than raising: this is the *display*
        path, and the write path is where the refusal belongs.
        """
        block = _find_block(self._config_lines(), "model")
        if block is None:
            return {}
        try:
            return parse_scalar_block(self._config_lines()[block[0] : block[1]])
        except SettingsError:
            return {}

    def model_shape_ok(self) -> bool:
        """Whether the current `model:` block is safe to edit in place."""
        lines = self._config_lines()
        block = _find_block(lines, "model")
        if block is None:
            return True
        try:
            parse_scalar_block(lines[block[0] : block[1]])
            return True
        except SettingsError:
            return False

    @_serialised
    def set_model(self, values: dict[str, str]) -> dict[str, str]:
        """Replace only the keys named in `WRITABLE_MODEL_KEYS`, preserving the rest."""
        unknown = sorted(set(values) - set(WRITABLE_MODEL_KEYS))
        if unknown:
            raise SettingsError(
                f"cannot write {', '.join(unknown)} — the model block accepts "
                f"{', '.join(WRITABLE_MODEL_KEYS)}",
                "unsupported_field",
            )
        for name, value in values.items():
            if not isinstance(value, str):
                raise SettingsError(f"`{name}` must be a string", "bad_value")

        lines = self._config_lines()
        block = _find_block(lines, "model")

        if block is None:
            current: dict[str, str] = {}
            span = (len(lines), len(lines))
        else:
            current = parse_scalar_block(lines[block[0] : block[1]])  # refuses a bad shape
            span = block

        merged = {**current, **values}
        rendered = render_scalar_block("model", merged)

        if block is None:
            head = lines if not lines or lines[-1].strip() == "" else [*lines, ""]
            updated = [*head, *rendered, ""]
        else:
            updated = [*lines[: span[0]], *rendered, *lines[span[1] :]]

        text = "\n".join(updated)
        if not text.endswith("\n"):
            text += "\n"

        _backup(self.config_path)
        _atomic_write(self.config_path, text)
        return merged

    # -- agent.disabled_toolsets ------------------------------------------
    #
    # Switching a capability off is a write to the engine's own suppression list, not a
    # hidden UI state: `model_tools._select_tool_names` subtracts this list last, so the
    # tools are genuinely absent from the agent. The engine re-reads config.yaml whenever it
    # builds an agent, so a save lands on the next conversation without a gateway restart.

    def disabled_toolsets(self) -> list[str]:
        """`agent.disabled_toolsets` as a list. A shape we cannot read displays as empty."""
        try:
            found = _read_disabled_toolsets(self._config_lines())
        except SettingsError:
            return []
        return [] if found is None else found[0]

    def disabled_skills(self) -> list[str]:
        """`skills.disabled` as written — what the engine hides from the skills index."""
        return _read_disabled_skills(self._config_lines())

    def opted_in_toolsets(self) -> set[str]:
        """Toolset names this profile opts into *by name*: `toolsets:` and `platform_toolsets.<p>`.

        Exactly the first two checks of the engine's `_profile_has_kanban_toolset`, which the
        skill `environments: [kanban]` gate calls. It reads what the file says and does not
        resolve composites or platform defaults — enough to answer whether kanban is on, which
        is the only environment this install gates a skill on.
        """
        lines = self._config_lines()
        return _read_list_items(lines, "toolsets") | _read_nested_list_items(
            lines, "platform_toolsets"
        )

    def agent_shape_ok(self) -> bool:
        """Whether the disabled list is a shape we are willing to rewrite in place."""
        lines = self._config_lines()
        try:
            found = _read_disabled_toolsets(lines)
        except SettingsError:
            return False
        return found is not None or _block_can_take_a_child(lines, AGENT_BLOCK)

    def skills_shape_ok(self) -> bool:
        """Whether `skills.disabled` is a shape we are willing to rewrite in place."""
        lines = self._config_lines()
        try:
            found = _read_block_list(
                lines, SKILLS_BLOCK, DISABLED_SKILLS_KEY, SKILL_NAME_RE, "skill"
            )
        except SettingsError:
            return False
        return found is not None or _block_can_take_a_child(lines, SKILLS_BLOCK)

    # -- agent.reasoning_effort -------------------------------------------
    #
    # The engine clamps a level to the nearest one the chosen model accepts
    # (`agent/reasoning_effort.py::clamp_effort`), so what is stored is the operator's
    # preference about effort. It lives in the `agent:` block, which the engine re-reads when it
    # builds an agent: a save lands on the next conversation, not at the next gateway start —
    # unlike the `model:` block above, which is read once at startup.

    def reasoning_effort(self) -> str | None:
        """`agent.reasoning_effort` as the file holds it: a level, `false`, or None when unset.

        The read path is lenient where the write path refuses: a shape we cannot parse reads as
        unset, and a *value* outside the engine's vocabulary comes back verbatim. Showing what
        the file says is the honest answer — the page can then say the engine is ignoring it,
        rather than displaying a level that is not in force.
        """
        try:
            found = _read_block_scalar(self._config_lines(), AGENT_BLOCK, REASONING_EFFORT_KEY)
        except SettingsError:
            return None
        if found is None:
            return None
        value = found[0]
        # The engine's other two spellings for "off" mean what `false` means; report the one we
        # would write so the page has a single state to select.
        return REASONING_DISABLED if value.lower() in REASONING_DISABLED_SPELLINGS else value

    def reasoning_shape_ok(self) -> bool:
        """Whether `agent.reasoning_effort` is a shape we are willing to rewrite in place."""
        lines = self._config_lines()
        try:
            found = _read_block_scalar(lines, AGENT_BLOCK, REASONING_EFFORT_KEY)
        except SettingsError:
            return False
        return found is not None or _block_can_take_a_child(lines, AGENT_BLOCK)

    @_serialised
    def set_reasoning_effort(self, value: Any) -> str:
        """Replace `agent.reasoning_effort`, preserving every other line of the file.

        Refuses any value the engine would silently ignore, and writes the canonical `false` for
        a disabled level so the file carries one spelling of "off" rather than three.
        """
        wanted = _normalize_reasoning_effort(value)

        lines = self._config_lines()
        # Refuses a shape we do not understand *before* anything is written.
        found = _read_block_scalar(lines, AGENT_BLOCK, REASONING_EFFORT_KEY)
        updated = _write_block_entry(
            lines,
            AGENT_BLOCK,
            f"{REASONING_EFFORT_KEY}: {_scalar_literal(wanted)}",
            None if found is None else found[1],
        )
        self._commit(updated)
        return wanted

    @_serialised
    def set_disabled_toolsets(self, names: Iterable[str]) -> list[str]:
        """Replace `agent.disabled_toolsets`, preserving every other line of the file."""
        return self._set_block_list(AGENT_BLOCK, DISABLED_TOOLSETS_KEY, names, TOOLSET_NAME_RE, "toolset")

    @_serialised
    def update_disabled_toolsets(self, name: str, enabled: bool) -> list[str]:
        """Flip one toolset: the whole read-modify-write, under the same lock as the write.

        The route used to read the list and *then* call the setter, so two switches pressed at
        the same moment each wrote a list computed before the other landed and eleven of twelve
        concurrent writes vanished (the internal security audit A19-CFG-5).
        """
        disabled = [entry for entry in self.disabled_toolsets() if entry != name]
        if not enabled:
            disabled.append(name)
        return self.set_disabled_toolsets(disabled)

    @_serialised
    def update_disabled_skills(self, name: str, enabled: bool) -> list[str]:
        """Flip one skill, for the same reason as `update_disabled_toolsets`."""
        disabled = [entry for entry in self.disabled_skills() if entry != name]
        if not enabled:
            disabled.append(name)
        return self.set_disabled_skills(disabled)

    @_serialised
    def set_disabled_skills(self, names: Iterable[str]) -> list[str]:
        """Replace `skills.disabled`, preserving every other line of the file.

        This is the engine's own skill switch: `agent.skill_utils.get_disabled_skill_names`
        reads this list (minus `ESSENTIAL_SKILLS`) when it assembles the skills index. A name
        the engine always loads is refused rather than written and ignored.
        """
        return self._set_block_list(
            SKILLS_BLOCK, DISABLED_SKILLS_KEY, names, SKILL_NAME_RE, "skill", ESSENTIAL_SKILLS
        )

    def enabled_plugins(self) -> list[str]:
        """`plugins.enabled`, read for information. Absent reads as empty, not as an error."""
        return _lenient_block_list(self._config_lines(), PLUGINS_BLOCK, ENABLED_PLUGINS_KEY)

    def disabled_plugins(self) -> list[str]:
        """`plugins.disabled`. The engine lets this list win over `plugins.enabled`."""
        return _lenient_block_list(self._config_lines(), PLUGINS_BLOCK, DISABLED_PLUGINS_KEY)

    def plugin_states(self) -> dict[str, bool]:
        """Every plugin this file names, as `name -> enabled`.

        Only names the config mentions: a plugin the engine resolves from its own tree is not
        this file's business, and reporting it as "off" because it is absent here would be the
        lie. The registry lists what the profile actually holds and uses this for the state.
        """
        enabled = set(self.enabled_plugins())
        disabled = set(self.disabled_plugins())
        return {name: (name in enabled and name not in disabled) for name in enabled | disabled}

    @_serialised
    def set_plugin_enabled(self, name: str, enabled: bool) -> dict[str, bool]:
        """Move one plugin between `plugins.enabled` and `plugins.disabled`, in one commit.

        Two lists because the engine has two, and `disabled` wins. Leaving an entry in both
        would make a plugin's state depend on which reader asked, so the pair is rewritten
        together rather than one list edited and the other hoped for.

        This is a *restart* switch, not a live one: the engine discovers plugins once per
        process, and its own CLI says so — "there is no un-wire primitive, so a running gateway
        keeps the plugin's handlers until restart". `applies_to` says `next_restart`.
        """
        if not isinstance(name, str) or not PLUGIN_NAME_RE.match(name):
            raise SettingsError(f"{name!r} is not a plugin name", "bad_name")
        if not isinstance(enabled, bool):
            raise SettingsError("`enabled` must be true or false", "bad_body")

        lines = self._config_lines()
        # Both shapes are validated before either is written.
        found_enabled = _read_block_list(
            lines, PLUGINS_BLOCK, ENABLED_PLUGINS_KEY, PLUGIN_NAME_RE, "plugin"
        )
        found_disabled = _read_block_list(
            lines, PLUGINS_BLOCK, DISABLED_PLUGINS_KEY, PLUGIN_NAME_RE, "plugin"
        )
        on = [n for n in (found_enabled[0] if found_enabled else []) if n != name]
        off = [n for n in (found_disabled[0] if found_disabled else []) if n != name]
        (on if enabled else off).append(name)
        on.sort()
        off.sort()

        updated = _write_block_list(lines, PLUGINS_BLOCK, ENABLED_PLUGINS_KEY, on, found_enabled)
        # `found_disabled` spans the *old* line numbers, so locate it again in the new text.
        found_disabled = _read_block_list(
            updated, PLUGINS_BLOCK, DISABLED_PLUGINS_KEY, PLUGIN_NAME_RE, "plugin"
        )
        updated = _write_block_list(
            updated, PLUGINS_BLOCK, DISABLED_PLUGINS_KEY, off, found_disabled
        )
        # The live half: the plugin reads this on every call, so the handler can refuse before
        # the engine's list (which needs a restart) has taken the tool away.
        updated, span = _ensure_block(
            updated, (PLUGINS_BLOCK, ENTRIES_KEY, name, SETTINGS_KEY)
        )
        updated = _write_in_span(
            updated, span, CAPABILITY_KEY, f"{CAPABILITY_KEY}: {'true' if enabled else 'false'}"
        )
        self._commit(updated)
        return {name: enabled}

    @_serialised
    def set_plugin_setting(self, name: str, key: str, value: str) -> dict[str, str]:
        """Write one key under `plugins.entries.<name>.settings`, preserving the rest of the file.

        This is where a plugin's own configuration lives — the engine hands the block to the
        plugin untouched, and the plugin reads it on every call. It is what points a tool at the
        operator's data: their spray book, the record store the app writes. Without it, an install
        has to hand-edit `config.yaml` to make a shipped tool work, which is not an install.

        A *restart* switch, like everything else in this block: the plugin host builds its config
        once per process.
        """
        if not isinstance(name, str) or not PLUGIN_NAME_RE.match(name):
            raise SettingsError(f"{name!r} is not a plugin name", "bad_name")
        if not isinstance(key, str) or not SETTING_KEY_RE.match(key):
            raise SettingsError(f"{key!r} is not a plugin setting key", "bad_key")
        if not isinstance(value, str):
            raise SettingsError("a plugin setting is written as text", "bad_body")

        lines = self._config_lines()
        updated, span = _ensure_block(
            lines, (PLUGINS_BLOCK, ENTRIES_KEY, name, SETTINGS_KEY)
        )
        updated = _write_in_span(updated, span, key, f"{key}: {_scalar(value)}")
        self._commit(updated)
        return {key: value}

    def plugin_setting(self, name: str, key: str) -> str:
        """Read one `plugins.entries.<name>.settings.<key>`, or "" when it is not set.

        The span is half-open like every other one in this module, so the line *after* the
        settings block — a sibling key, which is a different setting — is not read as if it
        were inside it (the internal audit BFF-10).
        """
        lines = self._config_lines()
        plugins = _find_block(lines, PLUGINS_BLOCK)
        if plugins is None:
            return ""
        entries = _nested_block(lines, plugins, ENTRIES_KEY)
        if entries is None:
            return ""
        mine = _nested_block(lines, entries, name)
        if mine is None:
            return ""
        settings = _nested_block(lines, mine, SETTINGS_KEY)
        if settings is None:
            return ""
        for line in lines[settings[0] : settings[1]]:
            stripped = line.strip()
            if stripped.startswith(f"{key}:"):
                return _scalar_without_comment(stripped.partition(":")[2].strip())
        return ""

    def plugin_capability_flags(self) -> dict[str, bool]:
        """`plugins.entries.<name>.settings.capability_enabled`, read for information.

        The live half of a plugin switch: what the handler itself reads on every call. A plugin
        with no flag is on — absence means nobody has switched it off.
        """
        lines = self._config_lines()
        plugins = _find_block(lines, PLUGINS_BLOCK)
        if plugins is None:
            return {}
        entries = _nested_block(lines, plugins, ENTRIES_KEY)
        if entries is None:
            return {}
        start, end = entries
        entry_indent = len(lines[start]) - len(lines[start].lstrip())
        flags: dict[str, bool] = {}
        index = start + 1
        while index < end:
            child = _child_key(lines[index])
            if child is None:
                index += 1
                continue
            name, indent = child
            if indent <= entry_indent:
                break
            settings = _nested_block(lines, (index, end), SETTINGS_KEY)
            if name and settings is not None:
                value = _flag_value(lines, settings, CAPABILITY_KEY)
                if value is not None:
                    flags[name] = value
            index += 1
        return flags

    def plugin_effective_states(self) -> dict[str, bool]:
        """Whether each named plugin would actually work: enabled *and* not switched off live."""
        states = self.plugin_states()
        flags = self.plugin_capability_flags()
        for name, value in flags.items():
            states[name] = states.get(name, True) and value
        return states

    def mcp_servers(self) -> dict[str, bool]:
        """`mcp_servers.<name>.enabled`, read for information.

        A server with no `enabled` line is on — the engine's own default — so absence is
        reported as enabled rather than as unknown.
        """
        return _mcp_servers_from(self._config_lines())

    @_serialised
    def set_mcp_server_enabled(self, name: str, enabled: bool) -> dict[str, bool]:
        """Flip `enabled` on an MCP server the profile already configures.

        It refuses to *create* a server entry. Pantler ships no MCP server (invariant 2), so a
        name that is not already in this file is either a typo or an integration nobody asked
        for, and writing it would look like a feature.
        """
        if not isinstance(name, str) or not name.strip():
            raise SettingsError("a server name is required", "bad_name")
        if not isinstance(enabled, bool):
            raise SettingsError("`enabled` must be true or false", "bad_body")

        lines = self._config_lines()
        span = _find_block(lines, MCP_BLOCK)
        if span is None:
            raise SettingsError(
                "this profile configures no MCP servers, so there is nothing to switch",
                "not_found",
            )
        server = _child_block_span(lines, *span, name)
        if server is None:
            raise SettingsError(
                f"{name} is not an MCP server in this profile; add it with the engine's own "
                f"CLI first",
                "not_found",
            )
        child_start, child_end = server
        rendered = f"{MCP_ENABLED_KEY}: {'true' if enabled else 'false'}"
        key_re = _key_re(MCP_ENABLED_KEY)
        existing = next(
            (i for i in range(child_start + 1, child_end) if key_re.match(lines[i])), None
        )
        if existing is not None:
            indent = lines[existing][: len(lines[existing]) - len(lines[existing].lstrip())]
            updated = [*lines[:existing], f"{indent}{rendered}", *lines[existing + 1 :]]
        else:
            indent = _block_indent(lines, child_start, child_end)
            updated = [*lines[:child_end], f"{indent}{rendered}", *lines[child_end:]]
        self._commit(updated)
        return {name: enabled}

    def connectors_enabled(self) -> bool | None:
        """`tools.connectors.enabled`, or None when the file does not say.

        Read-only on purpose: pantler wires no connector of its own yet, and the sheet that
        draws the ten tiles deliberately offers no switch until one is real.
        """
        lines = self._config_lines()
        tools = _find_block(lines, NESTED_BLOCK)
        if tools is None:
            return None
        connectors = _nested_block(lines, tools, CONNECTORS_KEY)
        if connectors is None:
            return None
        return _flag_value(lines, connectors, MCP_ENABLED_KEY)

    def _set_block_list(
        self,
        block: str,
        key: str,
        names: Iterable[str],
        name_re: re.Pattern[str],
        kind: str,
        forbidden: frozenset[str] = frozenset(),
    ) -> list[str]:
        wanted: list[str] = []
        for name in names:
            if not isinstance(name, str) or not name_re.match(name):
                raise SettingsError(f"{name!r} is not a {kind} name", "bad_name")
            if name in forbidden:
                raise SettingsError(
                    f"{name} is always loaded, so it cannot be switched off", "essential"
                )
            if name not in wanted:
                wanted.append(name)
        wanted.sort()

        lines = self._config_lines()
        # Refuses a shape we do not understand *before* anything is written.
        found = _read_block_list(lines, block, key, name_re, kind)
        updated = _write_block_list(lines, block, key, wanted, found)
        self._commit(updated)
        return wanted

    def _commit(self, lines: list[str]) -> None:
        text = "\n".join(lines)
        if not text.endswith("\n"):
            text += "\n"
        _backup(self.config_path)
        _atomic_write(self.config_path, text)

    # -- .env -------------------------------------------------------------

    def _env_lines(self) -> list[str]:
        if not self.env_path.is_file():
            return []
        return self.env_path.read_text(encoding="utf-8").splitlines()

    def key_names(self) -> dict[str, bool]:
        """Every name in `.env` and whether it holds a value. Never the value itself."""
        found: dict[str, bool] = {}
        for line in self._env_lines():
            entry = _parse_env_line(line)
            if entry is None:
                continue
            name, value = entry
            found[name] = bool(value)
        return found

    def secret(self, name: str) -> str:
        """One `.env` value, for a server-side caller that must use it.

        This is deliberately *not* part of `snapshot()`: the settings route proves a key is set
        and never returns it (the internal security audit A19-CFG-3). The connector
        service needs the value to call Composio, and it is the only caller.
        """
        for line in self._env_lines():
            entry = _parse_env_line(line)
            if entry is not None and entry[0] == name:
                return entry[1]
        return ""

    @_serialised
    def set_key(self, name: str, value: str) -> None:
        """Write one `NAME=value` line into `.env`, replacing any existing one.

        The value is written bare, which is what the engine reads, so a value that cannot
        survive that round trip is refused rather than quietly changed: a leading or trailing
        space is stripped by every reader of a `.env` file, and a key that silently becomes a
        different string is the worst kind of accepted (`the internal audit BFF-12`).

        A `.env.bak` of the previous file is kept beside it (`_backup`), and the preview
        denylist refuses to serve either name.
        """
        _check_env_name(name)
        if not isinstance(value, str) or value == "":
            raise SettingsError("a key needs a value", "bad_value")
        _check_env_value(value)

        lines = self._env_lines()
        replacement = f"{name}={value}"
        updated: list[str] = []
        replaced = False
        for line in lines:
            entry = _parse_env_line(line)
            if entry is not None and entry[0] == name:
                if not replaced:
                    updated.append(replacement)
                    replaced = True
                continue  # collapse duplicates rather than leave a stale second copy
            updated.append(line)

        if not replaced:
            if updated and updated[-1].strip() != "":
                updated.append("")
            updated.append(replacement)

        # 0600: the file holds provider credentials. Match what the dev environment does.
        _backup(self.env_path)
        _atomic_write(self.env_path, "\n".join(updated) + "\n", mode=0o600)

    @_serialised
    def clear_key(self, name: str) -> None:
        _check_env_name(name)
        lines = self._env_lines()
        updated = [line for line in lines if not _is_env_name(line, name)]
        if updated == lines:
            raise SettingsError(f"{name} is not set", "not_set")
        _backup(self.env_path)
        _atomic_write(self.env_path, "\n".join(updated) + "\n", mode=0o600)

    # -- the whole picture ------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        model = self.model()
        return {
            "available": True,
            "profile": {
                # The name, not the path: this is a readable GET, and the operator's home
                # directory is not something a page needs to lay out a settings form
                # (the internal security audit A19-CFG-11).
                "name": self.name,
                "config_exists": self.config_path.is_file(),
                "env_exists": self.env_path.is_file(),
                "model_editable": self.model_shape_ok(),
                "agent_editable": self.agent_shape_ok(),
                "reasoning_editable": self.reasoning_shape_ok(),
                "skills_editable": self.skills_shape_ok(),
            },
            "model": model,
            "reasoning_effort": self.reasoning_effort(),
            "disabled_toolsets": self.disabled_toolsets(),
            "disabled_skills": self.disabled_skills(),
            "keys": [
                {"name": name, "is_set": is_set}
                for name, is_set in sorted(self.key_names().items())
            ],
        }


def _check_env_name(name: str) -> None:
    """Refuse a name the engine will not honour, or one that would steer its own execution.

    The shape check is only half of the engine's rule. Hermes refuses to persist a set of names
    through its own env writer — "names that influence subprocess execution (LD_PRELOAD,
    PYTHONPATH, PATH, EDITOR, …) or Hermes runtime location and security policy (HERMES_HOME,
    HERMES_YOLO_MODE, …)" (`hermes_cli/config.py::_ENV_VAR_NAME_DENYLIST`) — and this module
    writes the same file, so it has to refuse them too. Without that half, any local caller could
    put `LD_PRELOAD` or `PYTHONPATH` into the profile's `.env`, which the engine exports into the
    environment of every child process it starts (the internal security audit A19-CFG-1).
    """
    if not ENV_NAME_RE.match(name or ""):
        raise SettingsError(f"{name!r} is not a valid environment variable name", "bad_name")
    upper = name.upper()
    if upper.startswith(ENV_NAME_DENY_PREFIXES) or upper in ENV_NAME_DENYLIST:
        raise SettingsError(
            f"{name} is a name the engine refuses to persist: it would steer how the engine "
            "itself runs, so it cannot be set from here",
            "bad_name",
        )


def _check_env_value(value: str) -> None:
    """Refuse a value that would not survive the engine's own reader unchanged.

    `str.splitlines()` is what the engine's secret scope tokenises with, and it splits on more
    than `\\n`: a vertical tab or a U+2028 in a value made the rest of it a second assignment
    (the internal security audit A19-CFG-3). The engine also strips a ` #` comment and
    unquotes a fully quoted value (A19-CFG-7), so both are refused here rather than stored as
    something the operator did not type.
    """
    if len(value.splitlines()) != 1:
        raise SettingsError("a key value cannot span lines", "bad_value")
    if value != value.strip():
        raise SettingsError(
            "a key value cannot begin or end with a space: the engine strips it when it "
            "reads .env, so the key would not be the one you typed",
            "bad_value",
        )
    if value.startswith(("'", '"')) and value.endswith(value[0]) and len(value) >= 2:
        raise SettingsError(
            "a key value cannot be wrapped in quotes: the engine removes them when it reads "
            ".env, so the key would not be the one you typed",
            "bad_value",
        )
    if " #" in value or "\t#" in value:
        raise SettingsError(
            "a key value cannot contain ' #': the engine reads the rest of the line as a "
            "comment, so the key would be truncated",
            "bad_value",
        )


def _parse_env_line(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if stripped.startswith("export "):
        stripped = stripped[len("export ") :].lstrip()
    name, separator, value = stripped.partition("=")
    name = name.strip()
    if not separator or not ENV_NAME_RE.match(name):
        return None
    return name, _unquote(value.strip())


def _is_env_name(line: str, name: str) -> bool:
    entry = _parse_env_line(line)
    return entry is not None and entry[0] == name
