"""Previews — serving bytes the operator can look at, without becoming a file browser.

Why this exists (the file-preview design): a conversation is full of files, and until now none of
them could be looked at. The chip showed a thumbnail for a raster image and was inert otherwise;
a path the agent named was plain text. This module is the serving half of the answer — the
disposition, the roots and their jail, the byte range — and it is deliberately the whole of the
new attack surface, so it is deliberately one file.

Standard library only, like the rest of the BFF. Four responsibilities:

    the disposition   which types may ever be served inline, and as what
    the roots         which directories this server will read from, and nothing else
    the range         one byte range, the platform's own rule
    the meta          what a path is, so the shell can choose a renderer before moving bytes

Two rules from the attachment design §6 survive contact with a preview, and both are load-bearing:

  * **An uploaded file must never become a page on our own origin.** Exactly three families are
    served inline — raster images, PDF, and text *as* ``text/plain`` — and ``text/html``,
    ``application/xhtml+xml`` and ``image/svg+xml`` are never among them. A text file is served
    as ``text/plain`` rather than as its own type, which is what makes that rule hold for a
    ``.md`` that is full of HTML as much as for a ``.txt``.

  * **Names are not paths.** A caller supplies a path and this module resolves it against an
    explicit root list, rejects ``..``, rejects a non-absolute path, and serves the *resolved*
    path — so a symlink out of a root is caught by the containment check rather than by hope.
    The install's own credentials (the engine key in the profile's ``.env``, ``auth.json``) are
    named and refused, because a root is the operator's checkout.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import quote

from attachments import INLINE_IMAGE_MIMES, classify, human_size, sniff_mime

# --------------------------------------------------------------------- limits
#
# One number to explain, not two: the per-file cap is the engine's own attachment cap, so
# "why 25 MB?" has the same answer on the upload path and on the preview path
# (the attachment design §3).

MAX_PREVIEW_BYTES = 25 * 1024 * 1024

# How much of a file is read to decide what it is. Enough for every signature we know, and for a
# `%PDF-` header that sits behind a little junk, which some producers emit.
HEAD_BYTES = 1024

# How much of a fetched page is handed back as a snapshot. The sheet shows a page's text when a
# site refuses to be framed; past this, the honest answer is the link itself.
MAX_SNAPSHOT_CHARS = 200_000

# ------------------------------------------------------------------ disposition

PDF_MIME = "application/pdf"

# Types that are a *page* if a browser is ever handed them with their own content type. They are
# classified `other` — download and nothing else — so that nothing downstream can be tempted to
# frame one. `image/svg+xml` is here rather than with the images on purpose: an SVG is script.
PAGE_MIMES = frozenset({"text/html", "application/xhtml+xml", "image/svg+xml"})

# Sound and moving pictures. Inert in the way a raster image is — a browser hands these to a
# decoder, never to its HTML parser — which is why they join the inline set rather than the
# download one. They need `Range` to seek, which the byte route already answers.
MEDIA_PREFIXES = ("audio/", "video/")


def kind_of(mime: str, name: str) -> str:
    """The one word the shell routes on: ``image`` · ``pdf`` · ``media`` · ``text`` · ``other``.

    ``other`` means download-and-nothing-else, and it is where the page types land.
    """
    if mime in PAGE_MIMES:
        return "other"
    if mime == PDF_MIME:
        return "pdf"
    if mime.startswith(MEDIA_PREFIXES):
        return "media"
    display = classify(mime, name)
    if display == "image":
        # A raster the browser can paint. TIFF and HEIC reach here and are still served as a
        # download by `disposition_of`, because they are not in the inline raster set.
        return "image"
    if display == "text":
        return "text"
    return "other"


def looks_like_pdf(head: bytes) -> bool:
    """A PDF's own signature, checked rather than trusted.

    The store sniffs on the way in, so this is the second pair of eyes: a file whose name and
    stored mime say PDF but whose bytes say something else is served as a download.
    """
    return b"%PDF-" in head[:HEAD_BYTES]


def disposition_of(mime: str, name: str, head: bytes = b"") -> tuple[str, str]:
    """``(content_type, disposition)`` — the security decision, in one function.

    Three families are served inline, each with its own type: a raster image, a PDF whose
    signature agrees, and sound or moving pictures. **Everything else — text, HTML, SVG, office
    documents, archives, unknown binaries — goes out as an octet-stream with a download
    disposition.** That is what stops a served file from ever becoming a page on this origin, and
    keeping the inline set to three families is what makes the rule auditable by reading one
    function.

    The line the three share is that a browser hands them to a decoder or a viewer rather than to
    its HTML parser. A page type is never on this list, whatever its extension says.

    Text is not an exception, and that is deliberate: the sheet shows a text file by fetching
    the bytes and rendering them as text nodes, which needs no disposition at all and gives a
    renderer we control (wrapping, theme, a size cap) rather than the browser's plain-text view.
    """
    kind = kind_of(mime, name)
    if kind == "image" and mime in INLINE_IMAGE_MIMES:
        return mime, "inline"
    if kind == "pdf" and looks_like_pdf(head):
        return PDF_MIME, "inline"
    if kind == "media":
        return mime, "inline"
    return "application/octet-stream", "attachment"


# ----------------------------------------------------------------------- errors


class PreviewError(Exception):
    """A refusal with a sentence, because the operator reads it.

    ``status`` is the HTTP status the route answers with; ``code`` is a stable machine word.
    """

    def __init__(self, status: int, message: str, code: str = "preview_error"):
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code


# ------------------------------------------------------------------------ roots

# Credential-shaped names, refused by basename. A root is the operator's own checkout, and the
# engine's API key lives in `.hermes-dev/profiles/<name>/.env` inside it — so this is not
# hypothetical. Case-insensitive, because a filesystem may not be.
#
# Names are matched by **family**, not by exact spelling: the audit found `auth.json` refused
# while `auth.json.bak-anon-probe` beside it was served, and the same for a `.env` that had been
# rotated (the internal security audit A19-EX-5). A backup of a credential is a credential.
DENIED_NAMES = frozenset(
    {
        ".env",
        ".envrc",
        ".git-credentials",
        "install_id",
        # Not a credential: the record store is not a document, and a browser's copy of the
        # whole ledger is the one thing this route should never be asked for.
        "records.db",
    }
)

#: Stems that are never served, whatever follows them: the stem itself, or the stem and a
#: separator. `auth.json`, `auth.json.bak-2026`, `auth.lock`, `id_rsa`, `id_rsa_old` and
#: `credentials.bak` are all the same file to a reader — while `author.md` and
#: `authentication.md` are not, which is why the separator matters.
DENIED_STEMS = (
    "auth",
    "credential",
    "credentials",
    "install_id",
    "id_rsa",
    "id_ed25519",
    "id_ecdsa",
    "id_dsa",
    "records",
)

#: Engine state files, matched by prefix so `-wal`, `-shm` and `.bak` go with them. These are
#: the operator's sessions, messages and memories, and a route that refuses `records.db` for
#: exactly that reason must refuse these too.
DENIED_PREFIXES = (
    "state.db",
    "response_store.db",
    "runs_idempotency.db",
    "records.db",
)

# Directory names that are never walked into, at any depth. `.hermes` and `.hermes-dev` are the
# engine's home: transcripts, request dumps, logs, memories and credentials live under them, and
# the default read root is the checkout that contains them.
DENIED_DIRS = frozenset(
    {".git", ".ssh", ".hermes", ".hermes-dev", ".data", "mcp-tokens", "pairing"}
)

_DENIED_SUFFIXES = (".pem", ".key", ".p12", ".pfx")


def _is_denied_stem(lowered: str) -> bool:
    for stem in DENIED_STEMS:
        if lowered == stem or lowered.startswith((stem + ".", stem + "-", stem + "_")):
            return True
    return False


def denied_name(path: Path) -> str | None:
    """Why this path is never served, or None when it is allowed."""
    lowered = path.name.lower()
    if lowered.startswith(".env"):
        # `.env`, `.envrc`, `.env.local`, `.env.bak-cors` — every spelling of the same file.
        return path.name
    if lowered in DENIED_NAMES:
        return path.name
    if _is_denied_stem(lowered):
        return path.name
    if lowered.startswith(DENIED_PREFIXES):
        return path.name
    if lowered.endswith(_DENIED_SUFFIXES):
        return path.name
    for part in path.parts:
        if part.lower() in DENIED_DIRS:
            return part
    return None


@dataclass(frozen=True)
class FileRoots:
    """The directories this server will read a path from, and the only ones.

    Empty is a real answer, not a fallback: with no root configured the route refuses rather than
    guessing at ``$HOME``. A caller who wants the operator's home directory can say so with
    ``--files-root ~``; that is a decision someone makes, not a default they discover.
    """

    paths: tuple[Path, ...] = ()

    @classmethod
    def build(cls, roots: Iterable[str | Path] | None) -> "FileRoots":
        resolved: list[Path] = []
        for raw in roots or ():
            if raw is None:
                continue
            text = str(raw).strip()
            if not text:
                continue
            try:
                path = Path(text).expanduser().resolve()
            except (OSError, RuntimeError):
                continue
            if path not in resolved:
                resolved.append(path)
        return cls(tuple(resolved))

    @property
    def enabled(self) -> bool:
        return bool(self.paths)

    def describe(self) -> list[str]:
        return [str(path) for path in self.paths]

    def resolve(self, raw: str) -> Path:
        """The one door from a caller's string to a path on disk. Raises `PreviewError`."""
        if not self.paths:
            raise PreviewError(
                403,
                "this server was started without --files-root, so it cannot read a file by "
                "path. Attachments still preview; add --files-root DIR to preview a workspace.",
                "no_roots",
            )
        text = (raw or "").strip()
        if not text:
            raise PreviewError(400, "a `path` is required", "bad_path")
        if "\x00" in text:
            raise PreviewError(400, "that path is not a path", "bad_path")

        candidate = Path(text)
        if not candidate.is_absolute():
            raise PreviewError(
                400,
                "a preview path must be absolute: the transcript carries no working directory, "
                "so a relative path cannot be resolved honestly",
                "relative_path",
            )
        if ".." in candidate.parts:
            raise PreviewError(400, "a path cannot contain '..'", "bad_path")

        try:
            # Not `strict=True`: resolving first and *then* checking the roots made this an
            # existence oracle for any path on the machine — "no such file" and "that file is
            # outside the directories this server may read" are different answers, and the
            # second one also carried the operating system's errno
            # (the internal security audit A19-EX-7). The roots decide first; only a path
            # inside them is ever told whether it exists.
            resolved = candidate.resolve(strict=False)
        except (OSError, RuntimeError) as exc:
            raise PreviewError(400, "that path cannot be read", "bad_path") from exc

        if not any(resolved == root or root in resolved.parents for root in self.paths):
            raise PreviewError(
                403,
                "that file is outside the directories this server may read",
                "outside_roots",
            )

        reason = denied_name(resolved)
        if reason:
            raise PreviewError(403, f"{reason} is never served", "denied")

        if not resolved.exists():
            raise PreviewError(404, "no such file", "not_found")
        if not resolved.is_file():
            raise PreviewError(400, "that path is not a regular file", "not_a_file")

        return resolved


# ------------------------------------------------------------------------ range


@dataclass(frozen=True)
class ByteRange:
    """One inclusive byte range, already clamped to the file."""

    start: int
    end: int

    @property
    def length(self) -> int:
        return self.end - self.start + 1

    def header(self, size: int) -> str:
        return f"bytes {self.start}-{self.end}/{size}"


_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")

# Python refuses to convert a very long string of digits to an int (3.11+ caps it at 4300
# characters by default), and a `Range` header is caller-supplied text. Nine digits is already
# 1 GB; anything past eighteen cannot be a byte offset in a file this server will ever serve, so
# it is treated as unsatisfiable instead of being converted (the internal audit BFF-7).
_MAX_RANGE_DIGITS = 18


def _range_number(text: str) -> int | None:
    """The number in a range field, or None when it is too long to be one."""
    if len(text) > _MAX_RANGE_DIGITS:
        return None
    return int(text)


def parse_range(header: str | None, size: int) -> ByteRange | None:
    """The range a request asks for, or None to send the whole thing.

    A malformed header is *ignored* rather than rejected, and so is a multi-range request: the
    RFC lets a server ignore `Range` entirely, and the things that ask for a range — a PDF
    viewer, a `<video>` — ask for one at a time. Only a well-formed, unsatisfiable range is an
    error: 416, with the size, which is what both of them expect.
    """
    if not header:
        return None
    text = header.strip()
    if "," in text:
        return None
    match = _RANGE_RE.match(text)
    if match is None:
        return None

    raw_start, raw_end = match.group(1), match.group(2)
    if raw_start == "" and raw_end == "":
        return None
    if size == 0:
        raise PreviewError(416, "that file is empty", "range_unsatisfiable")

    if raw_start == "":
        # A suffix range: the last N bytes.
        wanted = _range_number(raw_end)
        if wanted is None:
            raise PreviewError(416, "that byte range is not in the file", "range_unsatisfiable")
        if wanted == 0:
            raise PreviewError(416, "that byte range is empty", "range_unsatisfiable")
        start = max(0, size - wanted)
        end = size - 1
    else:
        first = _range_number(raw_start)
        if first is None:
            raise PreviewError(416, "that byte range is not in the file", "range_unsatisfiable")
        start = first
        if raw_end == "":
            end = size - 1
        else:
            last = _range_number(raw_end)
            if last is None:
                raise PreviewError(416, "that byte range is not in the file", "range_unsatisfiable")
            end = min(last, size - 1)
        if start >= size or start > end:
            raise PreviewError(416, "that byte range is not in the file", "range_unsatisfiable")

    return ByteRange(start, end)


# ------------------------------------------------------------------------- meta


@dataclass(frozen=True)
class PreviewFile:
    """What a path is, decided once here so the shell never re-derives it."""

    path: Path
    name: str
    mime: str
    size: int
    kind: str
    render: str
    content_type: str
    disposition: str

    @property
    def inline(self) -> bool:
        """Whether an element may point at the byte route and have it rendered."""
        return self.disposition == "inline"

    def to_dict(self) -> dict[str, object]:
        return {
            "path": str(self.path),
            "name": self.name,
            "mime": self.mime,
            "size": self.size,
            "size_human": human_size(self.size),
            "kind": self.kind,
            # Two different questions, and the shell needs both. `render` is what the sheet
            # should do; `inline` is whether it may point an element at the byte route at all.
            # A text file is `render: "text"` with `inline: false` — the sheet fetches the bytes
            # and draws text nodes — and that is the only place the two disagree.
            "render": self.render,
            "content_type": self.content_type,
            "disposition": self.disposition,
            "inline": self.inline,
        }


def describe_file(path: Path) -> PreviewFile:
    """Read the head of a file and say what it is. Never reads more than `HEAD_BYTES`."""
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise PreviewError(404, f"that file cannot be read ({exc})", "not_found") from exc

    if size > MAX_PREVIEW_BYTES:
        raise PreviewError(
            413,
            f"that file is larger than {human_size(MAX_PREVIEW_BYTES)}, so it is not previewed "
            "here. Ask the assistant to read it, or open it on the machine.",
            "too_large",
        )

    try:
        with path.open("rb") as handle:
            head = handle.read(HEAD_BYTES)
    except OSError as exc:
        raise PreviewError(403, f"that file cannot be read ({exc})", "unreadable") from exc

    mime = sniff_mime(head, path.name)
    kind = kind_of(mime, path.name)
    content_type, disposition = disposition_of(mime, path.name, head)

    # `render` is what the sheet should do; `inline` (in the dict below) is whether it may point
    # an element at the byte route at all. They are different questions:
    #
    #   image  → inline, painted from the route
    #   pdf    → inline, framed from the route
    #   media  → inline, played from the route (a range seek is why the route answers 206)
    #   text   → fetched as bytes and drawn as text nodes, because the route will not inline it
    #   other  → download; a TIFF or a HEIC is image-shaped and not paintable, and lands here
    if disposition == "inline" and kind in ("image", "pdf", "media"):
        render = kind
    elif kind == "text":
        render = "text"
    else:
        render = "download"
    return PreviewFile(
        path=path,
        name=path.name,
        mime=mime,
        size=size,
        kind=kind,
        render=render,
        content_type=content_type,
        disposition=disposition,
    )


def read_bytes(file: PreviewFile, byte_range: ByteRange | None = None) -> bytes:
    """The bytes, or the asked-for slice of them."""
    try:
        with file.path.open("rb") as handle:
            if byte_range is not None:
                handle.seek(byte_range.start)
                return handle.read(byte_range.length)
            return handle.read()
    except OSError as exc:
        raise PreviewError(403, f"that file cannot be read ({exc})", "unreadable") from exc


def byte_headers(disposition: str, name: str) -> dict[str, str]:
    """The headers every byte response carries, whichever door the bytes came through.

    Takes the two values rather than a `PreviewFile`, because the attachment route has the same
    two and no path: one header set, two readers, so the doors cannot drift apart.
    """
    return {
        "Accept-Ranges": "bytes",
        "X-Content-Type-Options": "nosniff",
        # Private, and short. A preview is the operator's own file, and a cached copy of a
        # workspace file that has since changed is worse than a second read.
        "Cache-Control": "private, max-age=300",
        "Content-Disposition": _disposition_header(disposition, name),
    }


def _disposition_header(disposition: str, name: str) -> str:
    """Both forms, because an operator's file names are not ASCII and RFC 6266 says so."""
    ascii_name = "".join(ch if 32 <= ord(ch) < 127 and ch not in '"\\' else "_" for ch in name)
    return f"{disposition}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"


def snapshot_text(text: bytes, limit: int = MAX_SNAPSHOT_CHARS) -> tuple[str, bool]:
    """The readable text of a fetched page, capped — and whether it was capped."""
    decoded = text.decode("utf-8", "replace")
    if len(decoded) <= limit:
        return decoded, False
    return decoded[:limit], True
