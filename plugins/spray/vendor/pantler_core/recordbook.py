"""Writing a record from either side of the seam.

There are two authors of a record: the BFF, when the operator types one into a screen, and an
engine-side tool, when the assistant records one out of a conversation. Both have to validate
against the same pack, allocate from the same sequence and render the same id — a spray recorded by
the assistant and one typed into the app are the same record, and two implementations of "make a
record" is how they stop being. `format_record_id`'s own docstring says as much; this is the object
that makes it true rather than aspirational.

What it is not: a cache, a service, or a second store. It opens the store and the packs it was
pointed at, does the three steps the BFF's `create_record` does — validate, allocate, insert — and
the caller closes it. Domain-neutral by construction: it knows record *types* and never what a
certificate or a spray is (the front-end design §3).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from .packs import PackError, PackRegistry, RecordType, format_record_id, load_packs, validate_record
from .store import Record, Store, StoreError, open_store


class RecordBookError(Exception):
    """A record could not be written or read, with a sentence saying why.

    ``code`` is what a caller routes on, so the BFF can answer 404, 409 and 422 without
    re-deriving the reason from the sentence (the internal audit K15).
    """

    def __init__(self, message: str, code: str = "record_error"):
        super().__init__(message)
        self.message = message
        self.code = code


class RecordBook:
    """The store and the packs, together, for whoever holds the profile's paths."""

    def __init__(self, store_path: str | Path, packs_dir: str | Path,
                 custom_packs_dir: str | Path | None = None):
        self.store = open_store(store_path)
        try:
            self.registry: PackRegistry = load_packs(packs_dir, custom_dir=custom_packs_dir)
        except PackError as exc:
            self.store.close()
            raise RecordBookError(f"the packs at {packs_dir} do not load: {exc}") from exc

    @classmethod
    def over(cls, store: Store, registry: PackRegistry) -> "RecordBook":
        """A book over a store and a registry somebody else already opened.

        The BFF holds both — it serves `/api/health` and `/api/packs` from them — and it used
        to reimplement validate-allocate-insert beside this class instead of using it, which is
        two implementations of "make a record" that agree until one of them is edited
        (the internal audit K15). This is the door for that caller: the same book, on a
        store it does not own and must not close.
        """
        book = cls.__new__(cls)
        book.store = store
        book.registry = registry
        return book

    # ------------------------------------------------------------------ types

    def record_type(self, name: str) -> RecordType:
        """The declared type called ``name``, or an error listing the ones that exist."""
        for pack in self.registry.packs:
            found = pack.record_type(name)
            if found is not None:
                return found
        known = sorted({record.type for pack in self.registry.packs for record in pack.records})
        listed = ", ".join(known) if known else "none"
        raise RecordBookError(
            f"no record type called {name!r} is installed. Known types: {listed}",
            "unknown_type",
        )

    def pack_of(self, name: str) -> str:
        for pack in self.registry.packs:
            if pack.record_type(name) is not None:
                return pack.id
        return ""

    def is_custom_type(self, name: str) -> bool:
        """True when ``name`` is declared by an operator-authored custom pack."""
        owner = self.registry.owner(name)
        pack = self.registry.pack(owner) if owner else None
        return bool(pack and pack.custom)

    # ------------------------------------------------------------------ writing

    def save(
        self,
        type_name: str,
        data: dict[str, Any],
        *,
        record_id: str | None = None,
    ) -> Record:
        """Validate ``data`` against the pack's type, allocate its id, and insert it.

        Refusals carry every problem the pack found rather than the first, for the same reason the
        kernel's validator does: one error at a time is a form nobody finishes. A caller that
        wants the operator to hear it plainly should pass the sentence through, not summarise it.
        """
        record_type = self.record_type(type_name)
        payload = dict(data)
        payload.pop("id", None)  # the id is envelope, not a declared field
        problems = validate_record(record_type, payload)
        if problems:
            raise RecordBookError("; ".join(problems), "invalid")

        identifier = record_id
        if record_type.id_sequence:
            # Both branches touch the store, so both belong inside the translation below: a busy
            # store raised `database is locked` straight out of `save` because the sequence
            # allocation sat outside the `try` (the internal security audit A19-KERN-6).
            try:
                if identifier is not None:
                    # A caller that numbers a record itself has to move the counter past it, or
                    # the store will hand the same number out again later
                    # (the internal audit K14).
                    self.store.adopt_sequence(
                        record_type.type,
                        identifier,
                        prefix=record_type.id_prefix or record_type.type.upper(),
                    )
                else:
                    identifier = format_record_id(
                        record_type, self.store.next_sequence(record_type.type)
                    )
            except StoreError as exc:
                raise RecordBookError(str(exc), "conflict") from exc
            except Exception as exc:  # anything else sqlite raises
                raise RecordBookError(
                    f"could not number the {type_name}: {exc}", "store_error"
                ) from exc
        try:
            return self.store.create(
                record_type.type, self.pack_of(type_name), payload, record_id=identifier
            )
        except StoreError as exc:
            raise RecordBookError(str(exc), "conflict") from exc
        except Exception as exc:  # anything else sqlite raises
            raise RecordBookError(f"could not write the {type_name}: {exc}", "store_error") from exc

    def update(self, type_name: str, record_id: str, data: dict[str, Any]) -> Record:
        """Replace a record's data, validating the result against its pack.

        Here rather than in the caller so that a screen edit and a conversation edit are
        validated the same way — the whole point of one book (K15).
        """
        record_type = self.record_type(type_name)
        payload = dict(data)
        payload.pop("id", None)
        problems = validate_record(record_type, payload)
        if problems:
            raise RecordBookError("; ".join(problems), "invalid")
        if self.store.get(record_type.type, record_id) is None:
            raise RecordBookError(f"no {record_type.label} with id {record_id}", "not_found")
        try:
            return self.store.update(record_type.type, record_id, payload)
        except StoreError as exc:
            raise RecordBookError(str(exc), "not_found") from exc

    def delete(self, type_name: str, record_id: str) -> bool:
        self.record_type(type_name)
        return self.store.delete(type_name, record_id)

    # ------------------------------------------------------------------ reading

    def get(self, type_name: str, record_id: str) -> Record | None:
        self.record_type(type_name)
        return self.store.get(type_name, record_id)

    def find(
        self,
        type_name: str,
        *,
        limit: int = 20,
        order: str = "updated_at DESC",
        where: dict[str, Any] | None = None,
        contains: str = "",
    ) -> list[Record]:
        """Recent records of one type, optionally filtered by field equality or a substring.

        Filtering happens here rather than in SQL on purpose: the fields live inside a JSON column,
        so a SQL filter would have to know each pack's shape — which is the one thing this module
        must not learn. A compliance record set is small; the scan is honest.

        The scan walks the whole type, in pages. It used to look at `limit × 5` rows and stop,
        which meant a filter that excluded most of them silently returned fewer matches than
        existed — with nothing in the answer to say the window had run out
        (the internal audit K13).
        """
        self.record_type(type_name)
        wanted = {key: str(value).casefold() for key, value in (where or {}).items()}
        needle = contains.casefold().strip()
        wanted_limit = max(1, int(limit))
        found: list[Record] = []

        page_size = 500
        offset = 0
        while True:
            page = self.store.list(type_name, limit=page_size, offset=offset, order=order)
            if not page:
                break
            for record in page:
                data = record.data or {}
                if any(str(data.get(key, "")).casefold() != value for key, value in wanted.items()):
                    continue
                if needle and needle not in str(data).casefold():
                    continue
                found.append(record)
                if len(found) >= wanted_limit:
                    return found
            if len(page) < page_size:
                break
            offset += len(page)
        return found

    def types(self) -> Iterable[str]:
        return sorted({record.type for pack in self.registry.packs for record in pack.records})

    def close(self) -> None:
        self.store.close()
