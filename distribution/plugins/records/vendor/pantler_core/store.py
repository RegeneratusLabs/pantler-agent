"""The record store — the kernel's one piece of durable state.

Generic on purpose. It holds records of any *type* for any *pack* and knows nothing about
what they mean: a record is an id, a type, a pack and a JSON blob. If this file learns what
an invoice is, the architecture in the front-end design §3 has failed.

Why it exists at all: the internal backend audit §1.1. Records used
to live in a dict on a `Ledger` instance, so every invoice died with the process and invoice
numbering restarted at `INV-0001` on every restart — a compliance problem, not a cosmetic one.
Sequential ids are allocated here for the same reason (§1.2, §2.4): from the store, atomically,
so they survive a restart and cannot collide between concurrent runs.

Concurrency. A pack's tools run inside the engine process and the BFF runs in the app, so two
processes reach the same file. WAL plus a busy timeout is what makes that safe; the lock here
only serialises this process's own threads, since `sqlite3` connections are not thread-safe.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS records (
    id         TEXT NOT NULL,
    type       TEXT NOT NULL,
    pack       TEXT NOT NULL,
    data       TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (type, id)
);

CREATE INDEX IF NOT EXISTS records_by_type_updated
    ON records (type, updated_at DESC);

-- Sequential ids, allocated durably. Any pack that wants INV-0001, JOB-0001, SPRAY-0001
-- gets them from here rather than from a counter it keeps in memory.
CREATE TABLE IF NOT EXISTS sequences (
    type TEXT PRIMARY KEY,
    next INTEGER NOT NULL
);
"""


class StoreError(Exception):
    """Raised for a store-level failure the caller can act on."""


@dataclass(frozen=True)
class Record:
    id: str
    type: str
    pack: str
    data: dict[str, Any]
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "pack": self.pack,
            "data": self.data,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    """A SQLite-backed record store. Open one per process."""

    def __init__(self, path: str | Path):
        self.path = str(path)
        # `StoreError` is documented as "a failure the caller can act on", and the callers catch
        # exactly that — but a store path whose parent is a file, or one under /proc, used to
        # raise `FileExistsError`/`sqlite3.OperationalError` straight through
        # (the internal security audit A19-KERN-6).
        try:
            if self.path != ":memory:":
                Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise StoreError(f"cannot use {self.path}: {exc}") from exc

        self._lock = threading.RLock()
        try:
            self._db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        except sqlite3.Error as exc:
            raise StoreError(f"cannot open {self.path}: {exc}") from exc
        self._db.row_factory = sqlite3.Row
        self._configure()
        self._migrate()
        self._restrict()

    def _restrict(self) -> None:
        """Keep the store readable by its owner only.

        A ledger holds the operator's customers, their prices and their compliance records,
        and SQLite creates the file with the process umask — 0644 on a default machine, so
        every other account on it could read the lot. The attachments store has always
        written 0600 (attachments.py:_write_private); this is the same rule for the file
        that matters more (the internal audit K10).

        The `-wal` and `-shm` siblings are created lazily by SQLite *after* the first write,
        so the check runs again at close, which is the other moment both exist.
        """
        if self.path == ":memory:":
            return
        for suffix in ("", "-wal", "-shm"):
            companion = Path(f"{self.path}{suffix}")
            try:
                if companion.exists():
                    companion.chmod(0o600)
            except OSError:
                # A store on a filesystem that cannot carry permissions is still a store.
                continue

    def _configure(self) -> None:
        with self._lock:
            # WAL lets the engine-side tools and the BFF read and write the same file.
            mode = self._db.execute("PRAGMA journal_mode=WAL").fetchone()
            # NORMAL is the pairing WAL is designed for: durable across a process crash, and
            # only at risk from a power loss, which is the trade the store's docstring makes.
            self._db.execute("PRAGMA synchronous=NORMAL")
            # Wait rather than fail when the other process holds the write lock.
            self._db.execute("PRAGMA busy_timeout=5000")
            self._db.execute("PRAGMA foreign_keys=ON")
        # A store that silently stayed in `delete` mode is the two-process case quietly
        # broken: a pack's tool in the engine process and the BFF would serialise against
        # each other, and the failure would look like a random "database is locked" much
        # later (the internal audit K12). A memory store has no journal file to have.
        if self.path != ":memory:" and str(mode[0]).lower() != "wal":
            raise StoreError(
                f"{self.path} cannot use write-ahead logging (it reports {mode[0]!r}), so two "
                f"processes cannot safely share it. Put the store on a local filesystem."
            )

    def _migrate(self) -> None:
        with self._lock:
            self._db.executescript(_SCHEMA)
            row = self._db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
            if row is None:
                self._db.execute(
                    "INSERT INTO meta (key, value) VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),)
                )

    @property
    def schema_version(self) -> int:
        with self._lock:
            row = self._db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        return int(row["value"]) if row else 0

    def close(self) -> None:
        with self._lock:
            # The `-wal` file only exists while the connection is open, so this is the last
            # moment the store is entirely on disk.
            self._restrict()
            self._db.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *_exc: object) -> None:
        """Close on the way out, so a caller cannot forget.

        The suite used to print `ResourceWarning: unclosed database` several times, which is
        the shape of the bug in production too: a store opened per request and never closed
        leaks a file handle and a WAL until the process ends (the internal audit K9).
        """
        self.close()

    # ------------------------------------------------------------- records

    def list(
        self,
        type: str,
        *,
        limit: int = 50,
        offset: int = 0,
        order: str = "updated_at DESC",
        after: str | None = None,
    ) -> list[Record]:
        """Records of one type. `order` is never caller-supplied text — see `_safe_order`.

        `after` is the keyset form of paging: "the next page starts above this id". It exists
        for `iter_records`, because an `OFFSET` walk over a table that is being written both
        repeats and skips rows as the cursor shifts underneath it
        (the internal audit K11). Ignored unless `order` is by id, which is what makes
        it meaningful.
        """
        clause = _safe_order(order)
        with self._lock:
            if after is not None and clause.startswith("id "):
                rows = self._db.execute(
                    f"SELECT * FROM records WHERE type = ? AND id > ? ORDER BY {clause} LIMIT ?",
                    (type, after, max(0, int(limit))),
                ).fetchall()
            else:
                rows = self._db.execute(
                    f"SELECT * FROM records WHERE type = ? ORDER BY {clause} LIMIT ? OFFSET ?",
                    (type, max(0, int(limit)), max(0, int(offset))),
                ).fetchall()
        return [_row_to_record(row) for row in rows]

    def count(self, type: str) -> int:
        with self._lock:
            row = self._db.execute("SELECT COUNT(*) AS n FROM records WHERE type = ?", (type,)).fetchone()
        return int(row["n"]) if row else 0

    def get(self, type: str, record_id: str) -> Record | None:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM records WHERE type = ? AND id = ?", (type, record_id)
            ).fetchone()
        return _row_to_record(row) if row else None

    def create(
        self,
        type: str,
        pack: str,
        data: dict[str, Any],
        *,
        record_id: str | None = None,
    ) -> Record:
        """Insert a record. Raises if the id is already taken — never overwrites.

        The overwrite is worth calling out: the old in-memory ledger did
        `self.invoices[number] = invoice`, so a repeated number silently replaced the
        earlier invoice. A duplicate id is a bug worth surfacing, not a value worth losing.
        """
        rid = record_id or uuid.uuid4().hex[:12]
        stamp = _now()
        payload = json.dumps(data, ensure_ascii=False, sort_keys=True)

        with self._lock:
            try:
                self._db.execute(
                    "INSERT INTO records (id, type, pack, data, created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (rid, type, pack, payload, stamp, stamp),
                )
            except sqlite3.IntegrityError as exc:
                raise StoreError(f"{type} {rid} already exists") from exc
            row = self._db.execute(
                "SELECT * FROM records WHERE type = ? AND id = ?", (type, rid)
            ).fetchone()
        return _row_to_record(row)

    def update(self, type: str, record_id: str, data: dict[str, Any]) -> Record:
        """Replace a record's data. Raises if it does not exist."""
        stamp = _now()
        payload = json.dumps(data, ensure_ascii=False, sort_keys=True)
        with self._lock:
            cursor = self._db.execute(
                "UPDATE records SET data = ?, updated_at = ? WHERE type = ? AND id = ?",
                (payload, stamp, type, record_id),
            )
            if cursor.rowcount == 0:
                raise StoreError(f"no {type} with id {record_id}")
            row = self._db.execute(
                "SELECT * FROM records WHERE type = ? AND id = ?", (type, record_id)
            ).fetchone()
        return _row_to_record(row)

    def delete(self, type: str, record_id: str) -> bool:
        with self._lock:
            cursor = self._db.execute(
                "DELETE FROM records WHERE type = ? AND id = ?", (type, record_id)
            )
        return cursor.rowcount > 0

    # ---------------------------------------------------------- sequences

    def next_sequence(self, type: str, *, start: int = 1) -> int:
        """Allocate the next integer for `type`, durably and atomically.

        This is the fix for invoice numbering restarting at 1 after a restart. It is
        deliberately generic: the store hands out numbers, it does not format them.
        """
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                row = self._db.execute("SELECT next FROM sequences WHERE type = ?", (type,)).fetchone()
                if row is None:
                    value = start
                    self._db.execute(
                        "INSERT INTO sequences (type, next) VALUES (?, ?)", (type, value + 1)
                    )
                else:
                    value = int(row["next"])
                    self._db.execute(
                        "UPDATE sequences SET next = ? WHERE type = ?", (value + 1, type)
                    )
                self._db.execute("COMMIT")
            except Exception:
                self._db.execute("ROLLBACK")
                raise
        return value

    def adopt_sequence(self, type: str, identifier: str, *, prefix: str = "") -> bool:
        """Move `type`'s counter past an id somebody else allocated.

        A caller that numbers a record itself — a certificate transcribed from paper, say —
        would otherwise leave the counter behind the ids already in the table, and the next
        allocated number would collide with one of them
        (the internal audit K14). Returns whether the counter moved.

        The id is only read as a number when it has the type's own shape (`CERT-0007` with
        prefix `CERT`); anything else is left alone, because a hand-made id is not a promise
        about the numbering.
        """
        shape = f"{prefix}-" if prefix else ""
        if not shape or not identifier.startswith(shape):
            return False
        digits = identifier[len(shape) :]
        # `isdigit()` is true for "²" and `int()` is capped at 4300 digits (3.11+), so an id the
        # check accepted raised `ValueError` out of a caller that only catches `StoreError`
        # (the internal security audit A19-KERN-5). ASCII digits, bounded length.
        if not (digits.isascii() and digits.isdigit() and len(digits) <= 18):
            return False
        try:
            wanted = int(digits) + 1
        except ValueError:  # pragma: no cover - the guard above makes this unreachable
            return False

        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                row = self._db.execute(
                    "SELECT next FROM sequences WHERE type = ?", (type,)
                ).fetchone()
                current = int(row["next"]) if row else 1
                if wanted <= current:
                    self._db.execute("COMMIT")
                    return False
                if row is None:
                    self._db.execute(
                        "INSERT INTO sequences (type, next) VALUES (?, ?)", (type, wanted)
                    )
                else:
                    self._db.execute(
                        "UPDATE sequences SET next = ? WHERE type = ?", (wanted, type)
                    )
                self._db.execute("COMMIT")
            except Exception:
                self._db.execute("ROLLBACK")
                raise
        return True


def _row_to_record(row: sqlite3.Row) -> Record:
    return Record(
        id=row["id"],
        type=row["type"],
        pack=row["pack"],
        data=json.loads(row["data"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


_ORDERS = {
    "updated_at DESC": "updated_at DESC, id ASC",
    "updated_at ASC": "updated_at ASC, id ASC",
    "created_at DESC": "created_at DESC, id ASC",
    "created_at ASC": "created_at ASC, id ASC",
    "id ASC": "id ASC",
    "id DESC": "id DESC",
}


def _safe_order(order: str) -> str:
    """Whitelist ORDER BY. Never interpolate caller text into SQL."""
    if order not in _ORDERS:
        raise StoreError(f"unsupported order {order!r}; expected one of {sorted(_ORDERS)}")
    return _ORDERS[order]


def open_store(path: str | Path) -> Store:
    return Store(path)


def iter_records(store: Store, type: str, *, batch: int = 100) -> Iterable[Record]:
    """Stream every record of a type. For exports and the audit pack.

    A keyset walk (`id > the last one seen`), not `OFFSET`: an export runs while the app is
    writing, and a row inserted behind an `OFFSET` cursor makes every later page one short,
    so the walk both repeats and skips. An id cursor cannot
    (the internal audit K11).
    """
    if batch < 1:
        # `max(0, int(limit))` turned this into `LIMIT 0`: the first page came back empty and the
        # generator returned, so a compliance export was silently empty rather than refused
        # (the internal security audit A19-KERN-7).
        raise StoreError(f"batch has to be at least 1, got {batch!r}")
    last: str | None = None
    while True:
        page = store.list(type, limit=batch, order="id ASC", after=last)
        if not page:
            return
        yield from page
        last = page[-1].id
