"""What the assistant has learned — its memory, and the skills it wrote for itself.

pantler's assistant is not a stateless chat: the engine gives it a **memory** it curates
across conversations and the ability to **write its own skills**. Both are on in this
profile and both have been used — `memories/MEMORY.md` holds facts the operator asked it to
keep, and the ledger shows a skill the agent created for itself. None of that was visible
anywhere in this app, which is what this module exists to fix.

**Why the BFF reads files rather than calling the engine.** The engine has all of this —
a learning graph, a curator, an entry-level memory API — but not on the surface pantler
talks to. The gateway's HTTP seam (`gateway/platforms/api_server*.py`) carries **no memory,
skill or self-improvement event at all**; the learning graph and the curator live on the
dashboard's routers and on the `tui_gateway` JSON-RPC socket, two other surfaces with two
other contracts (the front-end design §2 — *never use the dashboard routers*). The one
typed event, `review.summary`, is wired only into the TUI gateway, so a background review
that patches a skill mid-conversation is invisible over HTTP.

What *is* reliably on disk, in the profile we already read for settings and the skills
index, is the whole truth of it::

    profiles/<name>/memories/MEMORY.md     the agent's own notes
    profiles/<name>/memories/USER.md       what it knows about the operator
    profiles/<name>/skills/.usage.json     per-skill provenance and use counts
    profiles/<name>/skills/.curator_ledger.jsonl   every skill write, with its session
    profiles/<name>/skills/.curator_state  the background skill maintainer
    profiles/<name>/skills/.bundled_manifest       which skills shipped with the engine

So this module mirrors those files exactly, the same way `skills_index.py` mirrors the
skill loader and `engine_settings.py` mirrors `config.yaml`. **It is a read model**: it
writes nothing, and every place it cannot answer honestly it says so rather than guessing.

Three narrow readings, stated because each could otherwise be mistaken for more than it is:

* **The ledger is skills only.** A memory write leaves no session provenance on disk — the
  memory tool's own result carries none (`tools/memory_tool_store.py`) — so the per-entry
  *"which conversation taught it this"* answer comes from the conversation itself, not from
  here. The page shows memory entries with the file's own timestamp and claims nothing more.
* **`origin` is read, not inferred.** A skill is `learned` only when the ledger or
  `.usage.json` says the agent wrote it (`created_by: "learn"`), `bundled` only when the
  engine's manifest lists it. Everything else is `installed` — a skill that came with the
  profile, which is a different and weaker claim than "the assistant taught itself".
* **Time is the file's own.** Timestamps are epoch **seconds as floats**, the engine's wire
  convention (the front-end design §2); the front end converts, as it does for sessions.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

# `tools/memory_tool_store.py:25` — the engine's own entry delimiter. A bare "§" inside an
# entry survives; only the full "\n§\n" splits.
ENTRY_DELIMITER = "\n§\n"

# The engine's defaults (`hermes_cli/config_defaults.py`, the `memory:` block). Used only when
# the profile's config.yaml carries no `memory:` block of its own, and reported as the limit we
# actually used so the usage figure is never a percentage of a number nobody chose.
DEFAULT_LIMITS = {"memory": 2200, "user": 1375}

# source -> (file name, label, budget key). The engine reads exactly these two, in this order
# (`agent/learning_graph.py:_memory_cards`). The source is the engine's node-id prefix, which is
# `profile` for USER.md while its config key is `memory.user_char_limit` — hence the fourth
# column rather than a guess from the name.
MEMORY_FILES: tuple[tuple[str, str, str, str], ...] = (
    ("memory", "MEMORY.md", "Memory", "memory"),
    ("profile", "USER.md", "Your profile", "user"),
)

# How many ledger entries the page carries. The file is append-only and grows with use; the
# page shows the recent story, not the archive.
LEDGER_LIMIT = 200

# How much of a skill body a caller gets. Enough to see what it says, not a file dump.
MAX_TEXT = 2000


# --------------------------------------------------------------------------- small helpers


def _read_text(path: Path) -> str | None:
    """The file's text, or None when it exists but cannot be read.

    Strict decoding, exactly as the memory store reads it: `errors="replace"` would show a
    caller a lossy view that a later write could persist over the real bytes
    (`tools/memory_tool_store.py:_read_raw_checked`). A file that does not exist is an empty
    string, which is a normal answer — nothing has been learned yet.
    """
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return None


def _read_json(path: Path) -> Any:
    text = _read_text(path)
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def parse_entries(raw: str) -> list[str]:
    """Stripped, non-empty entries — the engine's own parse (`_parse_entries`)."""
    return [entry for entry in (part.strip() for part in raw.split(ENTRY_DELIMITER)) if entry]


def fingerprint(entry: str) -> str:
    """The entry's identity, by its text.

    Mirrors `agent.learning_graph.memory_fingerprint` byte for byte, so a node id minted here
    names the same entry the engine's own journey view names. That matters because the id is
    position *and* text: an earlier entry can be removed between two reads, and a bare index
    would then point at somebody else's memory.
    """
    return hashlib.sha256(entry.strip().encode("utf-8")).hexdigest()[:12]


def _seconds(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _parse_iso(value: Any) -> float | None:
    """An ISO-8601 stamp from the ledger as epoch seconds, or None."""
    if not isinstance(value, str) or not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        from datetime import datetime

        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None


# ------------------------------------------------------------------------------- memory


def _memory_refusal(path: Path, profile_dir: Path) -> str | None:
    """Why this memory file is not read, or None when it is.

    A symlink is refused, and so is anything that resolves outside the profile: this route takes
    no path from a caller, so the only way a file here is not the file it says it is, is somebody
    putting a link there (the internal security audit A19-CFG-9).
    """
    try:
        if path.is_symlink():
            return "this file is a symlink, so it is not read"
        resolved = path.resolve()
        if resolved != path and profile_dir.resolve() not in resolved.parents:
            return "this file points outside the profile, so it is not read"
    except OSError:
        return "this file cannot be resolved, so it is not read"
    return None


def load_memory(profile_dir: Path, limits: dict[str, int] | None = None) -> dict[str, Any]:
    """`MEMORY.md` and `USER.md` as entries, with the engine's own budgets.

    An unreadable file is reported as `readable: false` against that file rather than as an
    empty memory — "it has learned nothing" and "we cannot see what it learned" are different
    sentences and the screen must not confuse them.
    """
    resolved = {**DEFAULT_LIMITS, **(limits or {})}
    base = profile_dir / "memories"
    files: list[dict[str, Any]] = []
    entries: list[dict[str, Any]] = []

    for source, name, label, budget in MEMORY_FILES:
        path = base / name
        refusal = _memory_refusal(path, profile_dir)
        raw = None if refusal else _read_text(path)
        limit = resolved.get(budget, DEFAULT_LIMITS.get(budget, 2200))
        record: dict[str, Any] = {
            "source": source,
            "name": name,
            "label": label,
            "present": path.is_file(),
            "readable": raw is not None,
            "limit": limit,
            "modified": _seconds(path),
        }
        if refusal:
            # A memory file that is a symlink to `.env` would put a credential in the transcript
            # through a read route with no denylist (the internal security audit A19-CFG-9).
            record["reason"] = refusal

        if raw is None:
            record.update({"chars": None, "entries": None, "percent": None})
            files.append(record)
            continue

        parsed = parse_entries(raw)
        chars = len(ENTRY_DELIMITER.join(parsed))
        record.update(
            {
                "chars": chars,
                "entries": len(parsed),
                # Char budget, which is what the engine gates on. Rounded up: a memory that is
                # one character over is over.
                "percent": min(100, -(-chars * 100 // limit)) if limit > 0 else None,
            }
        )
        files.append(record)

        for index, text in enumerate(parsed):
            entries.append(
                {
                    # The engine's node id shape (`agent.learning_graph.memory_node_id`).
                    "id": f"memory:{source}:{index}:{fingerprint(text)}",
                    "source": source,
                    "label": label,
                    "index": index,
                    "text": text[:MAX_TEXT],
                    "chars": len(text),
                    "truncated": len(text) > MAX_TEXT,
                }
            )

    return {
        "files": files,
        "entries": entries,
        "total": len(entries),
        "readable": all(record["readable"] for record in files),
    }


def memory_limits(config_text: str) -> dict[str, int]:
    """The profile's `memory.memory_char_limit` / `memory.user_char_limit`, when it sets them.

    A deliberately shallow read of one flat `memory:` block: anything nested or non-numeric is
    ignored and the engine's default stands. `engine_settings.parse_scalar_block` is the strict
    parser and belongs to the write path; guessing there would risk a write, guessing here
    risks a percentage.
    """
    limits: dict[str, int] = {}
    lines = config_text.splitlines()
    inside = False
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line[:1].isspace():
            inside = line.split(":", 1)[0].strip() == "memory"
            continue
        if not inside or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        target = {"memory_char_limit": "memory", "user_char_limit": "user"}.get(key)
        if target is None:
            continue
        try:
            limits[target] = int(value.strip())
        except ValueError:
            continue
    return limits


# ------------------------------------------------------------------------------- skills


def load_usage(profile_dir: Path) -> dict[str, Any]:
    """`skills/.usage.json` — the engine's per-skill provenance and counters."""
    data = _read_json(profile_dir / "skills" / ".usage.json")
    return data if isinstance(data, dict) else {}


def load_bundled(profile_dir: Path) -> set[str]:
    """The names the engine's own manifest lists — `name:hash` lines, one per shipped skill.

    `.bundled_manifest` is the tombstone file (`app/server/README.md`, "Curating the bundled
    set"); its *entries* are the skills that shipped, which is what `origin: bundled` means.
    """
    text = _read_text(profile_dir / "skills" / ".bundled_manifest") or ""
    names: set[str] = set()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        names.add(line.split(":", 1)[0].strip())
    return names


def load_ledger(profile_dir: Path, limit: int = LEDGER_LIMIT) -> list[dict[str, Any]]:
    """`skills/.curator_ledger.jsonl`, newest last, clipped to *limit*.

    One line per write the agent or the curator made to a skill: what it did, to which skill,
    and — the reason this file is worth reading at all — **which conversation caused it**
    (`evidence.session_id`). That is the only session-level provenance the engine leaves
    anywhere, and it is what lets a screen say "this conversation is what taught it that".

    A malformed line is dropped rather than raising: the file is appended to by another
    process, and a half-written tail is a normal thing to find.
    """
    text = _read_text(profile_dir / "skills" / ".curator_ledger.jsonl")
    if not text:
        return []

    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        evidence = record.get("evidence") if isinstance(record.get("evidence"), dict) else {}
        after = record.get("after") if isinstance(record.get("after"), list) else []
        files = [item.get("path") for item in after if isinstance(item, dict) and item.get("path")]
        rows.append(
            {
                "id": str(record.get("id") or ""),
                "at": _parse_iso(record.get("ts")),
                "atIso": record.get("ts"),
                # "agent" (the assistant, mid-conversation) or "curator" (the background
                # skill maintainer). The engine's own vocabulary, kept verbatim.
                "actor": str(record.get("actor") or ""),
                "action": str(record.get("action") or ""),
                "skill": str(record.get("skill") or ""),
                "session": str(evidence.get("session_id") or "") or None,
                "file": str(evidence.get("file_path") or "") or None,
                "files": [str(path) for path in files],
            }
        )

    return rows[-limit:]


def _flag(value: Any) -> bool:
    """A boolean as a hand-edited file may spell it.

    `bool("false")` is `True`, so a state file carrying `paused: "false"` — a string, which is
    what a JSON string is — reported the curator as paused when it was not
    (the internal audit BFF-13).
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in ("false", "off", "no", "0", "")
    return bool(value)


def _count(value: Any) -> int:
    """An integer from a file, or 0 — never a crash on somebody else's shape."""
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def load_curator(profile_dir: Path) -> dict[str, Any]:
    """`skills/.curator_state` plus the interval the profile configured, when it did.

    There is **no switch here**. The engine's curator controls are on the dashboard's
    routers, not on the seam, and a switch that cannot change anything is a claim this app
    cannot back up (`app/server/README.md`, "Capabilities"). So this is a status line.
    """
    state = _read_json(profile_dir / "skills" / ".curator_state")
    if not isinstance(state, dict):
        return {"available": False}

    return {
        "available": True,
        "paused": _flag(state.get("paused")),
        "runCount": _count(state.get("run_count")),
        "lastRunAt": _parse_iso(state.get("last_run_at")),
        "lastRunIso": state.get("last_run_at"),
        "summary": state.get("last_run_summary") or None,
    }


def curator_interval(config_text: str) -> float | None:
    """`curator.interval_hours` from `config.yaml`, when the profile sets it (engine default 168)."""
    inside = False
    for line in config_text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line[:1].isspace():
            inside = line.split(":", 1)[0].strip() == "curator"
            continue
        if not inside or ":" not in line:
            continue
        key, value = line.split(":", 1)
        if key.strip() != "interval_hours":
            continue
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _learned_at(ledger: Iterable[dict[str, Any]]) -> dict[str, float | None]:
    """Skill name -> the earliest moment the ledger shows the agent writing it."""
    created: dict[str, float | None] = {}
    for row in ledger:
        if row["action"] != "create" or not row["skill"]:
            continue
        stamp = row["at"]
        if row["skill"] not in created or (stamp and (created[row["skill"]] or 0) > stamp):
            created[row["skill"]] = stamp
    return created


def attach_provenance(
    skills: Iterable[dict[str, Any]],
    usage: dict[str, Any],
    bundled: set[str],
    ledger: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Add `origin`, the counters and the ledger's own timestamps to the skills index.

    Four origins, and the strength of the claim differs between them — which is exactly why
    they are not collapsed into one "installed" bucket:

    ``learned``    the assistant wrote it (`.usage.json` `created_by == "learn"`, or the ledger
                   records an `agent`/`curator` create). The only origin that means "it taught
                   itself this".
    ``bundled``    the engine shipped it and the profile has not removed it.
    ``installed``  it came with the profile — a pack's or the distribution's own skill.
    ``external``   `.usage.json` marks it `external`, i.e. mounted from `skills.external_dirs`
                   rather than living in the profile. Configured, not learned.
    """
    ledger_rows = list(ledger)
    created_by_ledger = _learned_at(ledger_rows)
    patched: dict[str, float] = {}
    for row in ledger_rows:
        if not row["skill"] or row["at"] is None:
            continue
        patched[row["skill"]] = max(patched.get(row["skill"], 0.0), row["at"])

    out: list[dict[str, Any]] = []
    for skill in skills:
        name = str(skill.get("name") or "")
        record = usage.get(name) if isinstance(usage.get(name), dict) else {}
        created_by = str(record.get("created_by") or "")

        if created_by == "external" or record.get("source") == "external":
            origin = "external"
        elif created_by == "learn" or record.get("learned") is True or name in created_by_ledger:
            origin = "learned"
        elif name in bundled:
            origin = "bundled"
        else:
            origin = "installed"

        out.append(
            {
                **skill,
                "origin": origin,
                "learnedAt": created_by_ledger.get(name),
                "createdAt": record.get("created_at") if isinstance(record.get("created_at"), str) else None,
                "lastPatchedAt": patched.get(name),
                "lastUsedAt": record.get("last_used_at") if isinstance(record.get("last_used_at"), str) else None,
                "patches": _count(record.get("patch_count")),
                "uses": _count(record.get("use_count")),
                "state": str(record.get("state") or "active"),
                "pinned": bool(record.get("pinned")),
            }
        )
    return out


def summarise(skills: Iterable[dict[str, Any]]) -> dict[str, int]:
    rows = list(skills)
    return {
        "listed": len(rows),
        "learned": sum(1 for skill in rows if skill.get("origin") == "learned"),
        "changed": sum(1 for skill in rows if (skill.get("patches") or 0) > 0),
    }


# ------------------------------------------------------------------------- the read model


def load_learning(
    profile_dir: Path,
    skills: Iterable[dict[str, Any]] = (),
    config_text: str = "",
    ledger_limit: int = LEDGER_LIMIT,
) -> dict[str, Any]:
    """Everything the app can honestly say about what the assistant has learned.

    *skills* is the caller's own index — `skills_index.load_skills()` — so provenance is
    attached to the list the Capabilities page already shows, rather than to a second list
    that could disagree with it.
    """
    ledger = load_ledger(profile_dir, ledger_limit)
    enriched = attach_provenance(skills, load_usage(profile_dir), load_bundled(profile_dir), ledger)

    return {
        "available": True,
        "profile": profile_dir.name,
        "memory": load_memory(profile_dir, memory_limits(config_text)),
        "skills": enriched,
        "counts": summarise(enriched),
        "ledger": ledger,
        "curator": {**load_curator(profile_dir), "intervalHours": curator_interval(config_text)},
    }


def session_changes(ledger: Iterable[dict[str, Any]], session: str) -> list[dict[str, Any]]:
    """The ledger rows the engine attributes to one conversation, oldest first.

    This is the answer to "what did *this* conversation teach it", and it is the engine's own
    attribution (`evidence.session_id`), not a guess from timestamps.
    """
    wanted = session.strip()
    if not wanted:
        return []
    return [row for row in ledger if row["session"] == wanted]


def unavailable(reason: str) -> dict[str, Any]:
    """The honest answer when there is no profile to read — never an empty one.

    `available: false` is a normal reply, exactly as it is for `/api/settings` and
    `/api/skills`: the server was started without `--profile-dir`, so there is nothing to
    look at, and "it has learned nothing" would be a different and false statement.
    """
    return {"available": False, "reason": reason, "memory": None, "skills": [], "ledger": [], "curator": None}
