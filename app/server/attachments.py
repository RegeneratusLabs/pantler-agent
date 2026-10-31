"""Attachments — the operator's files, carried to the engine without the engine's help.

Why this exists (the attachment design §2): the pinned engine will not carry a file for us.
``POST /v1/runs`` takes text, ``/v1/artifacts/upload`` is gated behind browser control, and the
TUI gateway's base64 attachment pipeline is not reachable from outside. What *is* reachable is
the agent's own toolbox — ``read_file`` extracts documents, ``search_files`` walks a directory,
``vision_analyze`` loads an image from a path. So we write the bytes to disk on the machine the
engine runs on and compose a turn that names the paths.

Standard library only, like the rest of the BFF. Three responsibilities, in order:

    the store      files under <root>/<session>/<id>/<name>, with a meta.json beside them
    the fetcher    http/https URLs, capped and guarded, reduced to text
    the composer   the frozen text format that both this module and the shell understand

Nothing here knows what an invoice is. An attachment is bytes with a name.
"""

from __future__ import annotations

import functools
import hashlib
import ipaddress
import json
import mimetypes
import os
import re
import secrets
import shutil
import socket
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from html.parser import HTMLParser
from http.client import HTTPConnection, HTTPSConnection
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlparse
from urllib.request import HTTPHandler, HTTPRedirectHandler, HTTPSHandler, Request, build_opener

# --------------------------------------------------------------------- limits
#
# One number to explain, not two: the per-file cap is the engine's own attachment cap
# (tui_gateway/prompt_attachments.py), so "why 25 MB?" has the same answer on both sides.

MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_FILES_PER_TURN = 20
MAX_FOLDER_FILES = 50
MAX_FOLDER_BYTES = 100 * 1024 * 1024

# The whole store, not one file: the per-file cap bounds a request, and nothing bounded the
# directory (the internal security audit A19-EX-12). Generous on purpose — a food
# business's paperwork is small — and the sweep still removes what nobody has touched.
MAX_STORE_BYTES = 2 * 1024 * 1024 * 1024
MAX_STORE_FILES = 20_000
INLINE_PER_FILE_BYTES = 32 * 1024
INLINE_TOTAL_BYTES = 128 * 1024
MAX_URL_BYTES = 5 * 1024 * 1024
URL_TIMEOUT_SECONDS = 15.0
URL_MAX_REDIRECTS = 4
NAME_MAX_CHARS = 120

# The engine rejects a request body over 10 MB (api_server.py:233). The inline budget above
# keeps a composed turn three orders of magnitude clear of it; this is the assertion, not
# the mechanism.
MAX_COMPOSED_BYTES = 9 * 1024 * 1024

# Raster formats a browser renders safely. SVG is deliberately absent: it can carry script,
# and an uploaded file must never become a page on our own origin (the attachment design §6).
INLINE_IMAGE_MIMES = frozenset(
    {"image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp"}
)

_TEXT_EXTENSIONS = frozenset(
    """txt text log md markdown rst csv tsv json jsonl ndjson yaml yml toml ini cfg conf env
    xml html htm css scss less js mjs cjs ts tsx jsx py rb go rs java kt swift c h cpp hpp cc
    sh bash zsh fish ps1 sql graphql gql diff patch srt vtt tex bib""".split()
)

_DOCUMENT_MIMES = frozenset(
    {
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-powerpoint",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.oasis.opendocument.text",
        "application/vnd.oasis.opendocument.spreadsheet",
        "application/vnd.oasis.opendocument.presentation",
        "application/rtf",
        "application/epub+zip",
    }
)

_ARCHIVE_MIMES = frozenset(
    {"application/zip", "application/gzip", "application/x-tar", "application/x-7z-compressed"}
)

# Magic bytes, checked before any caller-supplied Content-Type. A browser guesses from the
# extension; the bytes do not guess.
_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"BM", "image/bmp"),
    (b"II*\x00", "image/tiff"),
    (b"MM\x00*", "image/tiff"),
    (b"%PDF-", "application/pdf"),
    (b"PK\x03\x04", "application/zip"),
    (b"\x1f\x8b", "application/gzip"),
)


class AttachmentError(Exception):
    """An attachment problem with a status the client can act on."""

    def __init__(self, status: int, message: str, code: str = "attachment_error"):
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code


# ------------------------------------------------------------------ the record


@dataclass
class Attachment:
    """One uploaded thing: a file, a folder of files, or a fetched URL."""

    id: str
    session: str
    name: str
    mime: str
    size: int
    kind: str
    created_at: float
    root: str  # absolute path to the file, or to the folder's directory
    rel_path: str | None = None
    source_url: str | None = None
    files: list[dict[str, Any]] = field(default_factory=list)
    folder_token: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """What the shell sees. ``kind`` is decided here so the shell never re-derives it."""
        return {
            "id": self.id,
            "session": self.session,
            "name": self.name,
            "mime": self.mime,
            "size": self.size,
            "size_human": human_size(self.size),
            "kind": self.kind,
            "created_at": self.created_at,
            "path": self.root,
            "rel_path": self.rel_path,
            "source_url": self.source_url,
            "file_count": len(self.files) if self.kind == "folder" else 1,
            "files": self.files if self.kind == "folder" else [],
        }

    def to_meta(self) -> dict[str, Any]:
        """What meta.json holds. Same shape, plus the two fields the store needs and the
        shell does not (the folder token is bookkeeping, not something to render)."""
        return self.to_dict() | {"root": self.root, "folder_token": self.folder_token}

    @classmethod
    def from_meta(cls, data: dict[str, Any]) -> "Attachment":
        return cls(
            id=str(data["id"]),
            session=str(data.get("session") or ""),
            name=str(data.get("name") or "file"),
            mime=str(data.get("mime") or "application/octet-stream"),
            size=int(data.get("size") or 0),
            kind=str(data.get("kind") or "other"),
            created_at=float(data.get("created_at") or 0.0),
            root=str(data.get("root") or ""),
            rel_path=data.get("rel_path"),
            source_url=data.get("source_url"),
            files=list(data.get("files") or []),
            folder_token=data.get("folder_token"),
        )


# ------------------------------------------------------------------- the store


class AttachmentStore:
    """Files on disk, with the filesystem as the index.

    There is no index file to fall out of sync: an attachment is found by globbing for its
    id, which is unique across the store. That is a deliberate choice at this scale — the
    alternative is a database whose only job would be to agree with the directory listing.
    """

    def __init__(
        self,
        root: str | Path,
        *,
        max_file_bytes: int = MAX_FILE_BYTES,
        url_fetcher: Callable[[str], "FetchedUrl"] | None = None,
    ):
        self.root = Path(root)
        self.max_file_bytes = max_file_bytes
        self._url_fetcher = url_fetcher or fetch_url
        # meta.json is read-modify-written when a folder grows, and ThreadingHTTPServer means
        # two uploads from one Folder… gesture can be in flight at once.
        self._lock = threading.Lock()

    def _private_dir(self, directory: Path) -> Path:
        """Create a directory under the root, closing every level it had to create.

        `mkdir(parents=True)` makes each intermediate with the process umask, so
        `<root>/<session>/` was listable even though `<root>/<session>/<id>/` and the files
        inside it were not — and a directory listing is a list of what the operator has
        (the internal audit BFF-14). The walk stops at the root and never leaves it.
        """
        directory.mkdir(parents=True, exist_ok=True)
        root = self.root.resolve()
        for path in (directory, *directory.parents):
            try:
                resolved = path.resolve()
            except OSError:
                break
            if resolved != root and not resolved.is_relative_to(root):
                break
            try:
                path.chmod(0o700)
            except OSError:
                pass
            if resolved == root:
                break
        return directory

    # -- writing ----------------------------------------------------------

    def save_bytes(
        self,
        session: str,
        name: str,
        data: bytes,
        *,
        mime_hint: str = "",
        rel_path: str | None = None,
        folder_token: str | None = None,
    ) -> Attachment:
        """Store one file, or add one to a folder upload.

        ``folder_token`` is minted by the client for one Folder… gesture. The first file
        creates the folder record; every later file appends to it, so the operator gets one
        chip for a directory rather than fifty.
        """
        if not data:
            raise AttachmentError(400, "the file is empty", "empty_file")
        if len(data) > self.max_file_bytes:
            raise AttachmentError(
                413,
                f"{name} is {human_size(len(data))}; the limit is "
                f"{human_size(self.max_file_bytes)}",
                "too_large",
            )
        # A per-file cap bounded each request and nothing bounded the store: a loop of uploads
        # filled the disk (the internal security audit A19-EX-12).
        used_bytes, used_files = self.usage()
        if used_bytes + len(data) > MAX_STORE_BYTES:
            raise AttachmentError(
                507,
                f"the attachment store is full ({human_size(MAX_STORE_BYTES)}); remove old "
                "attachments or raise the limit",
                "store_full",
            )
        if used_files >= MAX_STORE_FILES:
            raise AttachmentError(
                507,
                f"the attachment store already holds {MAX_STORE_FILES} files; remove some "
                "before attaching more",
                "store_full",
            )

        session = _safe_session(session)
        if folder_token:
            return self._save_into_folder(session, folder_token, name, data, rel_path)
        return self._save_single(session, name, data, mime_hint)

    def _save_single(self, session: str, name: str, data: bytes, mime_hint: str) -> Attachment:
        attachment_id = _new_id()
        clean = sanitize_name(name)
        mime = sniff_mime(data, clean, mime_hint)
        directory = self._private_dir(self.root / session / attachment_id)

        target = _contained(directory, clean)
        _write_private(target, data)

        record = Attachment(
            id=attachment_id,
            session=session,
            name=clean,
            mime=mime,
            size=len(data),
            kind=classify(mime, clean),
            created_at=time.time(),
            root=str(target),
            files=[{"rel_path": clean, "size": len(data), "sha256": _sha256(data), "mime": mime}],
        )
        self._write_meta(record)
        return record

    def _save_into_folder(
        self, session: str, folder_token: str, name: str, data: bytes, rel_path: str | None
    ) -> Attachment:
        rel = sanitize_relpath(rel_path or name)
        with self._lock:
            record = self._find_by_folder_token(session, folder_token)
            if record is None:
                label = folder_token_name(rel)
                record = Attachment(
                    id=_new_id(),
                    session=session,
                    name=label,
                    mime="inode/directory",
                    size=0,
                    kind="folder",
                    created_at=time.time(),
                    root="",
                    folder_token=folder_token,
                )
                record.root = str(self.root / session / record.id / label)

            if len(record.files) >= MAX_FOLDER_FILES:
                raise AttachmentError(
                    413,
                    f"{record.name} has more than {MAX_FOLDER_FILES} files; "
                    "attach a smaller selection",
                    "too_many_files",
                )
            if record.size + len(data) > MAX_FOLDER_BYTES:
                raise AttachmentError(
                    413,
                    f"{record.name} is over {human_size(MAX_FOLDER_BYTES)}; "
                    "attach a smaller selection",
                    "folder_too_large",
                )

            # The picker reports the chosen folder as the first segment of every relative
            # path, and that name is already the record's own directory. Strip it, so the
            # tree does not nest inside a copy of itself.
            parts = rel.split("/")
            inner = "/".join(parts[1:]) if len(parts) > 1 else parts[0]

            directory = self._record_path(record)
            self._private_dir(directory)
            target = _contained(directory, inner)
            _write_private(target, data)

            mime = sniff_mime(data, inner, "")
            record.files.append(
                {
                    "rel_path": inner,
                    "size": len(data),
                    "sha256": _sha256(data),
                    "mime": mime,
                }
            )
            record.size += len(data)
            self._write_meta(record)
            return record

    def save_url(self, session: str, url: str) -> Attachment:
        """Fetch a URL once, now, and keep what it answered.

        Fetching at attach time rather than at send time is the honest choice: what the
        operator attached is what the assistant will read, and a page that has changed since
        is not silently substituted.
        """
        session = _safe_session(session)
        fetched = self._url_fetcher(url)

        attachment_id = _new_id()
        directory = self._private_dir(self.root / session / attachment_id)

        stored_name = sanitize_name(_url_filename(fetched.url, fetched.mime))
        target = _contained(directory, stored_name)
        _write_private(target, fetched.body)

        record = Attachment(
            id=attachment_id,
            session=session,
            name=sanitize_name(fetched.title or fetched.url),
            mime=fetched.mime,
            size=len(fetched.body),
            kind="url",
            created_at=time.time(),
            root=str(target),
            source_url=fetched.url,
            files=[
                {
                    "rel_path": stored_name,
                    "size": len(fetched.body),
                    "sha256": _sha256(fetched.body),
                    "mime": fetched.mime,
                }
            ],
        )
        self._write_meta(record)
        return record

    # -- reading ----------------------------------------------------------

    def get(self, attachment_id: str) -> Attachment:
        if not _ID_RE.fullmatch(attachment_id or ""):
            raise AttachmentError(400, "that is not an attachment id", "invalid_id")
        for meta in self.root.glob(f"*/{attachment_id}/meta.json"):
            try:
                record = Attachment.from_meta(json.loads(meta.read_text("utf-8")))
            except (OSError, ValueError, KeyError) as exc:
                raise AttachmentError(410, "that attachment's record is unreadable", "gone") from exc
            if self._checked(record) is None:
                raise AttachmentError(
                    410, "that attachment's record does not point inside the store", "unusable_record"
                )
            return record
        raise AttachmentError(404, "no such attachment", "not_found")

    def list(self, session: str) -> list[Attachment]:
        session = _safe_session(session)
        found: list[Attachment] = []
        for meta in (self.root / session).glob("*/meta.json"):
            try:
                record = Attachment.from_meta(json.loads(meta.read_text("utf-8")))
            except (OSError, ValueError, KeyError):
                continue  # a half-written record is skipped, not fatal
            checked = self._checked(record)
            if checked is not None:
                found.append(checked)
        return sorted(found, key=lambda attachment: attachment.created_at)

    def usage(self) -> tuple[int, int]:
        """What the store holds: (bytes, files). One walk, and only on the write path."""
        total = 0
        count = 0
        if not self.root.is_dir():
            return (0, 0)
        for path in self.root.rglob("*"):
            try:
                if path.is_file():
                    total += path.stat().st_size
                    count += 1
            except OSError:
                continue
        return (total, count)

    def _record_path(self, record: Attachment) -> Path:
        """The one place a stored `root` is turned back into a path, and the one rule.

        A `root` comes from `meta.json`, which this store writes — but a truncated or edited
        record is not impossible, and `delete` already refused exactly that case
        (the internal audit BFF-14). The other doors read the same field, so they share
        the check (the internal security audit A19-EX-11): a `root` of `""` resolves to
        the working directory, and a `root` of someone else's directory is not ours to read.
        """
        root = self.root.resolve()
        resolved = Path(record.root).resolve()
        if resolved == root or root not in resolved.parents:
            raise AttachmentError(
                410,
                "that attachment's record does not point inside the store",
                "unusable_record",
            )
        return resolved

    def _checked(self, record: Attachment) -> Attachment | None:
        """The record, if the store is willing to own the path it carries; else None."""
        try:
            self._record_path(record)
        except AttachmentError:
            return None
        return record

    def path_of(self, record: Attachment) -> Path:
        """Where this record's bytes are, checked against the store (A19-EX-11)."""
        return self._record_path(record)

    def delete(self, attachment_id: str) -> bool:
        """Remove an attachment and everything under it. Idempotent."""
        try:
            record = self.get(attachment_id)
        except AttachmentError as exc:
            if exc.code == "not_found":
                return False
            raise
        directory = self._record_path(record).parent
        shutil.rmtree(directory, ignore_errors=True)
        return True

    def read(self, record: Attachment) -> bytes:
        """The stored bytes. A folder has no single blob, so it answers with its listing."""
        if record.kind == "folder":
            raise AttachmentError(400, "a folder has no single body", "is_folder")
        try:
            return self._record_path(record).read_bytes()
        except OSError as exc:
            raise AttachmentError(410, "the stored file is gone", "gone") from exc

    def repair_modes(self) -> int:
        """Bring an existing store back to 0700 directories and 0600 files.

        The 0700/0600 rule landed on 2026-10-18 and only applied to what it wrote, so every
        directory created before it was still listable — on this machine, all of them
        (the internal security audit A19-DATA-5). A check that only runs on write never
        repairs the past; this runs once at startup.
        """
        if not self.root.is_dir():
            return 0
        repaired = 0
        for path in sorted(self.root.rglob("*")):
            try:
                wanted = 0o700 if path.is_dir() else 0o600
                if (path.stat().st_mode & 0o777) != wanted:
                    path.chmod(wanted)
                    repaired += 1
            except OSError:
                continue  # a filesystem that cannot carry permissions is still a store
        try:
            if (self.root.stat().st_mode & 0o777) != 0o700:
                self.root.chmod(0o700)
                repaired += 1
        except OSError:
            pass
        return repaired

    def sweep(self, keep_days: int) -> int:
        """Drop attachments nobody has attached for a while.

        Age is the directory's mtime, not the recorded ``created_at``: nothing here updates
        either when an attachment is read, so this is really "attached a while ago", which
        is the honest description of what it does.
        """
        if keep_days <= 0 or not self.root.exists():
            return 0
        cutoff = time.time() - keep_days * 86400
        removed = 0
        for session_dir in self.root.iterdir():
            if not session_dir.is_dir():
                continue
            for directory in session_dir.iterdir():
                try:
                    if directory.is_dir() and directory.stat().st_mtime < cutoff:
                        shutil.rmtree(directory, ignore_errors=True)
                        removed += 1
                except OSError:
                    continue
            if not any(session_dir.iterdir()):
                shutil.rmtree(session_dir, ignore_errors=True)
        return removed

    # -- internals --------------------------------------------------------

    def _write_meta(self, record: Attachment) -> None:
        directory = self.root / record.session / record.id
        self._private_dir(directory)
        target = directory / "meta.json"
        temporary = directory / "meta.json.part"
        temporary.write_text(
            json.dumps(record.to_meta(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)

    def _find_by_folder_token(self, session: str, token: str) -> Attachment | None:
        cleaned = _clean_token(token)
        if not cleaned:
            raise AttachmentError(400, "that folder token is not usable", "bad_folder")
        for meta in (self.root / session).glob("*/meta.json"):
            try:
                data = json.loads(meta.read_text("utf-8"))
            except (OSError, ValueError):
                continue
            if data.get("folder_token") == cleaned:
                return Attachment.from_meta(data)
        return None


def _clean_token(token: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "", str(token or ""))[:40]


def _safe_session(session: str) -> str:
    """A session id becomes a directory name. It arrives from the browser, so it is never trusted."""
    cleaned = re.sub(r"[^A-Za-z0-9_.-]", "", str(session or ""))[:80].strip(".-")
    if not cleaned:
        raise AttachmentError(400, "a session id is required", "bad_session")
    return cleaned


_ID_RE = re.compile(r"[0-9a-f]{12}")


def _new_id() -> str:
    return secrets.token_hex(6)


def _contained(directory: Path, relative: str) -> Path:
    """Join ``relative`` under ``directory`` and refuse anything that escapes it."""
    root = directory.resolve()
    candidate = (root / relative).resolve()
    if candidate != root and root not in candidate.parents:
        raise AttachmentError(400, "that file name is not usable", "bad_name")
    return candidate


def sanitize_name(name: str) -> str:
    """A display name that is safe as one path segment.

    Unicode is kept — an operator's file names are not ASCII — but separators, control
    characters, leading dots and anything that could climb out are not.
    """
    cleaned = unicodedata.normalize("NFKC", str(name or ""))
    cleaned = cleaned.replace("\\", "/").split("/")[-1]
    cleaned = "".join(ch for ch in cleaned if ch.isprintable())
    cleaned = re.sub(r'[<>:"|?*]', "-", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().strip(".")
    if not cleaned:
        cleaned = "file"
    if len(cleaned) > NAME_MAX_CHARS:
        suffix = Path(cleaned).suffix
        if suffix and len(suffix) <= 12:
            cleaned = cleaned[: NAME_MAX_CHARS - len(suffix)] + suffix
        else:
            cleaned = cleaned[:NAME_MAX_CHARS]
    return cleaned


def sanitize_relpath(rel_path: str) -> str:
    """A folder-relative path, segment by segment, so ``../..`` cannot survive it."""
    raw = str(rel_path or "").replace("\\", "/").split("/")
    # Drop the climbing segments before sanitising: afterwards ``..`` has already become a
    # harmless-looking "file", and a name is much harder to reason about than an absence.
    kept = [part for part in raw if part.strip() and part.strip() not in (".", "..")]
    return "/".join(sanitize_name(part) for part in kept) or "file"


def folder_token_name(rel_path: str) -> str:
    first = str(rel_path or "").replace("\\", "/").split("/")[0]
    return sanitize_name(unquote(first)) or "folder"


def _mkdir_private(directory: Path) -> None:
    """Create a directory only its owner may look inside.

    The files themselves have always been 0600 (`_write_private`), but the directories were
    made with the process umask, so `attachments/<session>/` was listable and every file name
    on it was readable even when the bytes were not (the internal audit BFF-14).
    """
    directory.mkdir(parents=True, exist_ok=True)
    try:
        directory.chmod(0o700)
    except OSError:
        # A filesystem that cannot carry permissions is still a place to put a file.
        pass


def _write_private(target: Path, data: bytes) -> None:
    _mkdir_private(target.parent)
    temporary = target.with_name(target.name + ".part")
    temporary.write_bytes(data)
    os.chmod(temporary, 0o600)
    os.replace(temporary, target)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _url_filename(url: str, mime: str) -> str:
    path = urlparse(url).path
    candidate = sanitize_name(unquote(path.rsplit("/", 1)[-1])) if path else ""
    if candidate and candidate != "file":
        return candidate
    return "page" + (mimetypes.guess_extension(mime or "") or ".txt")


# --------------------------------------------------------------- classification


#: A media type, as `type/subtype` with the RFC 6838 token characters. A hint that does not
#: match this is not a media type and is discarded rather than stored (A19-EX-10).
_MEDIA_TYPE_RE = re.compile(r"^[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*$")


def sniff_mime(data: bytes, name: str, hint: str = "") -> str:
    """Magic bytes first, then the caller's hint, then the name. The order is the argument.

    A browser's ``Content-Type`` for a ``.csv`` is often ``application/vnd.ms-excel`` and for
    an unknown extension is ``application/octet-stream``; the sniff is what makes the file
    render as a table and inline as text rather than as an opaque blob.
    """
    head = data[:16]
    if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return "image/webp"
    for signature, mime in _MAGIC:
        if head.startswith(signature):
            if mime == "application/zip":
                # Every OOXML/ODF document is a zip; only the name tells them apart.
                return mimetypes.guess_type(name)[0] or mime
            return mime

    # The hint is a header value the client chose, and a *folded* one arrives with CRLF still in
    # it — which was then stored as the MIME and echoed as a response header
    # (the internal security audit A19-EX-10). Printable ASCII only, and it has to look
    # like a media type at all: a hint that does not is not a hint.
    hint = "".join(ch for ch in (hint or "") if 0x20 <= ord(ch) < 0x7F)
    hint = hint.split(";")[0].strip().lower()
    if hint and not _MEDIA_TYPE_RE.match(hint):
        hint = ""
    guessed = mimetypes.guess_type(name)[0]
    # A browser calls a .csv `application/vnd.ms-excel` and a .md `text/markdown` it may not
    # know at all. When the name says "this is text", the name wins: being wrong here costs an
    # inlined table, and being wrong the other way costs a needless tool round trip.
    if guessed and guessed.startswith("text/") and not hint.startswith("text/"):
        return guessed
    if hint and hint != "application/octet-stream":
        return hint
    return guessed or "application/octet-stream"


def describe(record: Attachment) -> str:
    """The one-line description in the composed listing — and therefore in the transcript."""
    if record.kind == "folder":
        count = len(record.files)
        return f"folder, {count} file{'' if count == 1 else 's'}, {human_size(record.size)}"
    return f"{record.mime}, {human_size(record.size)}"


def classify(mime: str, name: str) -> str:
    """The display kind, decided once here so the shell never re-derives it."""
    extension = Path(name).suffix.lower().lstrip(".")
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("text/"):
        return "text"
    if mime in _DOCUMENT_MIMES:
        return "document"
    if mime in _ARCHIVE_MIMES:
        return "archive"
    if mime in ("application/json", "application/xml", "application/yaml", "application/x-yaml"):
        return "text"
    if extension in _TEXT_EXTENSIONS:
        return "text"
    return "other"


def human_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    value = float(size)
    for unit in ("KB", "MB", "GB"):
        value /= 1024
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if value >= 100 else f"{value:.1f} {unit}"
    return f"{size} B"


def decode_text(data: bytes) -> str | None:
    """Text, or None when the bytes are not text.

    UTF-8 first, with a Windows-1252 fallback for the spreadsheets this market actually
    exports — but only when the result looks like text, because cp1252 will happily decode
    a JPEG into plausible-looking mojibake.
    """
    for encoding in ("utf-8-sig", "utf-8"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    try:
        candidate = data.decode("cp1252")
    except UnicodeDecodeError:
        return None
    controls = sum(1 for ch in candidate if ord(ch) < 32 and ch not in "\t\n\r")
    return candidate if controls <= max(1, len(candidate) // 50) else None


# --------------------------------------------------------------- the URL fetch


@dataclass
class FetchedUrl:
    url: str
    body: bytes
    mime: str
    title: str | None = None


class _TextExtractor(HTMLParser):
    """HTML in, readable text out. Not a renderer: nothing here lays anything out."""

    _SKIP = frozenset({"script", "style", "noscript", "template", "svg", "head"})
    _BREAKS = frozenset(
        {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article"}
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title: str | None = None
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag: str, _attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True
        elif tag in self._BREAKS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title and self.title is None and data.strip():
            self.title = data.strip()
        if self._skip_depth:
            return
        text = data.strip()
        if text:
            self.parts.append(text + " ")

    def text(self) -> str:
        joined = "".join(self.parts)
        joined = re.sub(r"[ \t]+", " ", joined)
        joined = re.sub(r"\n\s*\n\s*\n+", "\n\n", joined)
        return joined.strip()


def html_to_text(raw: bytes) -> tuple[str, str | None]:
    parser = _TextExtractor()
    try:
        parser.feed(raw.decode("utf-8", "replace"))
    except Exception:  # a malformed page is still a page
        pass
    return parser.text(), parser.title


class _Pin:
    """The address the next connection goes to, filled once per hop.

    `fetch_url` validates a name once and then connects to *that* address. Re-resolving at
    connect time is what made the guard advisory: a name whose answers alternate gets a public
    answer for the check and a loopback one for the connection
    (the internal security audit A19-EX-6).
    """

    __slots__ = ("address",)

    def __init__(self, address: tuple[str, int] | None = None) -> None:
        self.address = address


class _PinnedHTTPConnection(HTTPConnection):
    """HTTP to a pinned address. `self.host` stays the name, so `Host:` is still right."""

    def __init__(self, host: str, port: int | None = None, *, pin: _Pin, **kwargs: Any) -> None:
        super().__init__(host, port, **kwargs)
        self._pin = pin

    def connect(self) -> None:
        address = self._pin.address or (self.host, self.port)
        self.sock = socket.create_connection(address, self.timeout, self.source_address)
        if self._tunnel_host:
            self._tunnel()


class _PinnedHTTPSConnection(HTTPSConnection):
    """HTTPS to a pinned address, with the certificate still checked against the real name.

    Pinning must not quietly turn verification off, so the socket is wrapped with
    `server_hostname` set to the name in the URL.
    """

    def __init__(self, host: str, port: int | None = None, *, pin: _Pin, **kwargs: Any) -> None:
        super().__init__(host, port, **kwargs)
        self._pin = pin

    def connect(self) -> None:
        address = self._pin.address or (self.host, self.port)
        sock = socket.create_connection(address, self.timeout, self.source_address)
        if self._tunnel_host:
            self.sock = sock
            self._tunnel()
            sock = self.sock
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class _PinnedHTTPHandler(HTTPHandler):
    def __init__(self, pin: _Pin) -> None:
        super().__init__()
        self._pin = pin

    def http_open(self, req):  # type: ignore[no-untyped-def]
        return self.do_open(functools.partial(_PinnedHTTPConnection, pin=self._pin), req)


class _PinnedHTTPSHandler(HTTPSHandler):
    def __init__(self, pin: _Pin) -> None:
        super().__init__()
        self._pin = pin

    def https_open(self, req):  # type: ignore[no-untyped-def]
        return self.do_open(
            functools.partial(_PinnedHTTPSConnection, pin=self._pin), req, context=self._context
        )


class _CheckedRedirects(HTTPRedirectHandler):
    """Every hop is checked against the same host rules as the first request — and re-pinned.

    Checking without re-pinning would leave the hop free to resolve somewhere else.
    """

    max_redirections = URL_MAX_REDIRECTS

    def __init__(self, pin: _Pin) -> None:
        self._pin = pin

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        parsed = urlparse(newurl)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise AttachmentError(400, "that page redirected somewhere not allowed", "bad_redirect")
        address = _refuse_private_host(parsed.hostname, parsed.port)
        if address is not None:
            self._pin.address = address
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _tune_socket(response: Any, remaining: float) -> None:
    """Make the *next read* obey the whole-fetch deadline, not just the gaps between reads.

    `read(65536)` blocks until the buffer fills and resets the socket timeout on every byte, so
    a page dripping one byte at a time held the thread past the deadline — for as long as it
    liked (the internal security audit A19-EX-9).
    """
    try:
        response.fp.raw._sock.settimeout(max(0.05, remaining))
    except (AttributeError, OSError, ValueError):
        pass


def fetch_url(url: str) -> FetchedUrl:
    """Fetch one http/https URL, once, with the guards the attachment design §6 lists.

    Private, loopback and link-local addresses are refused. The BFF can be bound to a tailnet
    address so a phone can reach it, and "fetch this URL and hand me the text" is a sharp
    thing to expose to a network: it would otherwise read localhost services and the
    operator's LAN. The escape hatch for an intranet page is the assistant's own web tools,
    which run under the engine's policy rather than ours.
    """
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise AttachmentError(400, "only http and https addresses can be attached", "bad_url")
    pin = _Pin(_refuse_private_host(parsed.hostname, parsed.port))

    request = Request(
        parsed.geturl(),
        headers={
            # Identify honestly. A page that refuses an unknown client is a page we do not
            # scrape behind its back.
            "User-Agent": "pantler/0.0 (+local attachment fetch)",
            "Accept": "text/html,application/xhtml+xml,text/plain,application/json;q=0.9,*/*;q=0.5",
        },
    )
    opener = build_opener(
        _PinnedHTTPHandler(pin), _PinnedHTTPSHandler(pin), _CheckedRedirects(pin)
    )
    # A deadline for the whole fetch, not per socket operation: `timeout=` bounds each read,
    # so a server that drips a byte at a time would hold the request open indefinitely
    # (the internal audit BFF-14). The cap is the same one, spent once.
    deadline = time.monotonic() + URL_TIMEOUT_SECONDS
    chunks: list[bytes] = []
    received = 0
    try:
        with opener.open(request, timeout=URL_TIMEOUT_SECONDS) as response:
            while received <= MAX_URL_BYTES:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise AttachmentError(
                        504,
                        f"that page took longer than {URL_TIMEOUT_SECONDS:.0f} seconds to "
                        f"answer; save it and attach the file instead",
                        "fetch_timeout",
                    )
                _tune_socket(response, remaining)
                # `read1` returns what has arrived instead of waiting for the whole buffer, so
                # the deadline above is actually consulted while a slow page is still talking.
                reader = getattr(response, "read1", None) or response.read
                chunk = reader(min(65536, MAX_URL_BYTES + 1 - received))
                if not chunk:
                    break
                chunks.append(chunk)
                received += len(chunk)
            body = b"".join(chunks)
            mime = (response.headers.get_content_type() or "").lower()
            final_url = response.geturl()
    except HTTPError as exc:
        raise AttachmentError(502, f"that page answered HTTP {exc.code}", "fetch_failed") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise AttachmentError(502, f"could not fetch that address ({exc})", "fetch_failed") from exc

    if len(body) > MAX_URL_BYTES:
        raise AttachmentError(
            413,
            f"that page is larger than {human_size(MAX_URL_BYTES)}; attach the document instead",
            "url_too_large",
        )

    title: str | None = None
    if mime in ("text/html", "application/xhtml+xml"):
        text, title = html_to_text(body)
        body = text.encode("utf-8")
        mime = "text/plain"
    elif not (mime.startswith("text/") or mime in ("application/json", "application/xml")):
        raise AttachmentError(
            415,
            f"that address answered {mime}, which cannot be attached as a page",
            "unsupported_type",
        )
    if not body.strip():
        raise AttachmentError(502, "that page had no readable text", "empty_page")
    return FetchedUrl(url=final_url, body=body, mime=mime, title=title)


def _refuse_private_host(hostname: str, port: int | None = None) -> tuple[str, int] | None:
    """Resolve `hostname` once, refuse a private answer, and return the address to connect to.

    The returned address is what the caller must dial. Resolving here for the *check* and
    letting the connection resolve again is the whole of A19-EX-6, so the answer is not
    advisory: `fetch_url` pins it.
    """
    try:
        infos = socket.getaddrinfo(hostname, port or 0, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise AttachmentError(400, f"could not resolve {hostname}", "bad_host") from exc
    answers: list[tuple[str, int]] = []
    for info in infos:
        address = str(info[4][0])
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError:
            continue
        if isinstance(parsed, ipaddress.IPv6Address) and parsed.ipv4_mapped:
            parsed = parsed.ipv4_mapped
        if (
            parsed.is_loopback
            or parsed.is_private
            or parsed.is_link_local
            or parsed.is_reserved
            or parsed.is_multicast
            or parsed.is_unspecified
        ):
            raise AttachmentError(
                400,
                f"{hostname} is on a private or local address; save the page and attach the "
                "file instead",
                "private_host",
            )
        answers.append((address, int(info[4][1])))
    if not answers:
        raise AttachmentError(400, f"could not resolve {hostname}", "bad_host")
    # Every answer was public (one private answer refuses the whole name above), so any of them
    # is safe to dial — and it is *this* one, not a second resolution.
    return answers[0]


# ---------------------------------------------------------------- the composer
#
# The format below is frozen. The BFF writes it and the shell parses it back out to redraw
# the chips after a reload, so a change here is a change in two languages at once.
# the attachment design §4 is the contract; app/shared/src/attachments.ts is its other half.

BLOCK_HEADER = "Attached files ({count}):"
BLOCK_HINT = "Read a document with read_file; look at an image with vision_analyze."


def compose_input(text: str, attachments: Sequence[Attachment]) -> str:
    """The engine input for a turn: the operator's words, then what they attached."""
    if not attachments:
        return text.strip()

    lines: list[str] = []
    if text.strip():
        lines.append(text.strip())
        lines.append("")

    lines.append(BLOCK_HEADER.format(count=len(attachments)))
    for index, record in enumerate(attachments, start=1):
        lines.append(f"{index}. {record.name} — {describe(record)}")
        lines.append(f"   Path: {record.root}")
    lines.append(BLOCK_HINT)

    inlined = _inline_sections(attachments)
    if inlined:
        lines.append("")
        lines.extend(inlined)

    composed = "\n".join(lines).strip()
    if len(composed.encode("utf-8")) > MAX_COMPOSED_BYTES:
        # Belt and braces: the inline budget already guarantees this cannot happen, and a
        # silent truncation would be worse than an error the operator can see.
        raise AttachmentError(
            413,
            "the attachments and the message together are too large for one turn; "
            "attach fewer files",
            "turn_too_large",
        )
    return composed


def _inline_sections(attachments: Sequence[Attachment]) -> list[str]:
    """Text attachments, inlined in order, under one shared budget.

    A CSV of orders that is already text should not need a tool round trip to become
    visible. Past the budget, the path and ``read_file`` are the right shape — and the
    listing above always has the path.
    """
    sections: list[str] = []
    budget = INLINE_TOTAL_BYTES
    for record in attachments:
        if budget <= 0:
            break
        if record.kind not in ("text", "url"):
            continue
        try:
            data = Path(record.root).read_bytes()
        except OSError:
            continue
        if len(data) > INLINE_PER_FILE_BYTES:
            sections.append(
                f"--- {record.name} — not inlined: {human_size(len(data))}, larger than "
                f"{human_size(INLINE_PER_FILE_BYTES)}; read it with read_file ---"
            )
            continue
        decoded = decode_text(data)
        if decoded is None:
            sections.append(f"--- {record.name} — not inlined: not text ---")
            continue
        if len(data) > budget:
            sections.append(
                f"--- {record.name} — not inlined: this turn's text budget is spent; "
                "read it with read_file ---"
            )
            continue
        budget -= len(data)
        sections.append(f"--- {record.name} ---")
        sections.append(decoded.rstrip())
        sections.append(f"--- end {record.name} ---")
    return sections


def select_for_turn(
    records: Iterable[Attachment], limit: int = MAX_FILES_PER_TURN
) -> list[Attachment]:
    """The attachments a single turn will carry, in the order the operator chose them."""
    chosen = list(records)
    if len(chosen) > limit:
        raise AttachmentError(
            413,
            f"a turn can carry {limit} attachments; this one has {len(chosen)}. "
            "Send some now, or put them in a folder",
            "too_many_attachments",
        )
    return chosen
