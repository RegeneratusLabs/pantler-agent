"""Tests for the record store.

The kernel had no tests at all until now — the internal backend audit
§1.4 — which is how an in-memory ledger with restart-resetting invoice numbers survived
into a product plan. These are the assertions that would have caught it.

Run:  PYTHONPATH=core/src python -m unittest discover -s core/tests
"""

from __future__ import annotations

import stat
import tempfile
import threading
import unittest
from pathlib import Path

from pantler_core import Store, StoreError, iter_records


class StoreTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.path = Path(self._dir.name) / "records.db"
        self.store = Store(self.path)

    def tearDown(self) -> None:
        self.store.close()
        self._dir.cleanup()


class TestRecords(StoreTestCase):
    def test_create_and_read_back(self) -> None:
        created = self.store.create("note", "demo", {"title": "first"})
        self.assertEqual(created.type, "note")
        self.assertEqual(created.pack, "demo")
        self.assertEqual(created.data, {"title": "first"})
        self.assertTrue(created.id)
        self.assertEqual(created.created_at, created.updated_at)

        fetched = self.store.get("note", created.id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.data, {"title": "first"})

    def test_ids_are_unique_by_default(self) -> None:
        ids = {self.store.create("note", "demo", {"n": i}).id for i in range(25)}
        self.assertEqual(len(ids), 25)

    def test_a_duplicate_id_is_refused_rather_than_overwriting(self) -> None:
        # The old in-memory ledger did `invoices[number] = invoice`, so a repeated number
        # silently replaced an earlier invoice. Losing a record quietly is worse than an error.
        first = self.store.create("note", "demo", {"title": "keep me"}, record_id="NOTE-1")
        with self.assertRaises(StoreError):
            self.store.create("note", "demo", {"title": "replace you"}, record_id="NOTE-1")
        self.assertEqual(self.store.get("note", first.id).data, {"title": "keep me"})

    def test_update_replaces_data_and_moves_updated_at(self) -> None:
        created = self.store.create("note", "demo", {"title": "before"})
        updated = self.store.update("note", created.id, {"title": "after"})
        self.assertEqual(updated.data, {"title": "after"})
        self.assertEqual(updated.created_at, created.created_at)

    def test_update_of_a_missing_record_raises(self) -> None:
        with self.assertRaises(StoreError):
            self.store.update("note", "nope", {"title": "x"})

    def test_delete_reports_whether_anything_went(self) -> None:
        created = self.store.create("note", "demo", {"title": "x"})
        self.assertTrue(self.store.delete("note", created.id))
        self.assertFalse(self.store.delete("note", created.id))
        self.assertIsNone(self.store.get("note", created.id))

    def test_types_do_not_leak_into_each_other(self) -> None:
        self.store.create("note", "demo", {"n": 1})
        self.store.create("task", "demo", {"n": 2})
        self.assertEqual(self.store.count("note"), 1)
        self.assertEqual(self.store.count("task"), 1)
        self.assertEqual([r.data for r in self.store.list("note")], [{"n": 1}])

    def test_list_pages(self) -> None:
        for i in range(5):
            self.store.create("note", "demo", {"n": i}, record_id=f"N{i}")
        page = self.store.list("note", limit=2, offset=1, order="id ASC")
        self.assertEqual([r.id for r in page], ["N1", "N2"])

    def test_order_is_whitelisted(self) -> None:
        # `order` reaches SQL, so caller text must never be interpolated into it.
        with self.assertRaises(StoreError):
            self.store.list("note", order="updated_at DESC; DROP TABLE records")
        self.assertEqual(self.store.count("note"), 0)

    def test_data_survives_reopening_the_file(self) -> None:
        # The whole point: a restart must not lose the business's records.
        self.store.create("note", "demo", {"title": "durable"})
        self.store.close()

        reopened = Store(self.path)
        try:
            self.assertEqual([r.data for r in reopened.list("note")], [{"title": "durable"}])
        finally:
            reopened.close()


class TestSequences(StoreTestCase):
    def test_numbers_are_monotonic(self) -> None:
        self.assertEqual([self.store.next_sequence("invoice") for _ in range(3)], [1, 2, 3])

    def test_numbering_survives_a_restart(self) -> None:
        # Audit §1.2: invoice numbering used to restart at INV-0001 on every gateway restart,
        # so numbers repeated. A number allocated from the store does not.
        self.store.next_sequence("invoice")
        self.store.next_sequence("invoice")
        self.store.close()

        reopened = Store(self.path)
        try:
            self.assertEqual(reopened.next_sequence("invoice"), 3)
        finally:
            reopened.close()

    def test_sequences_are_independent_per_type(self) -> None:
        self.assertEqual(self.store.next_sequence("invoice"), 1)
        self.assertEqual(self.store.next_sequence("job"), 1)
        self.assertEqual(self.store.next_sequence("invoice"), 2)

    def test_start_can_be_chosen(self) -> None:
        self.assertEqual(self.store.next_sequence("invoice", start=1000), 1000)
        self.assertEqual(self.store.next_sequence("invoice"), 1001)

    def test_concurrent_allocation_never_repeats(self) -> None:
        # Audit §2.4: the plugin held one ledger in a module global behind up to ten
        # concurrent runs, and `_number()` was a read-modify-write. Allocation happens in
        # the store now, under a lock and inside a transaction.
        allocated: list[int] = []
        lock = threading.Lock()

        def worker() -> None:
            for _ in range(20):
                value = self.store.next_sequence("invoice")
                with lock:
                    allocated.append(value)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(allocated), 160)
        self.assertEqual(len(set(allocated)), 160, "a number was handed out twice")


class TestEnvelope(StoreTestCase):
    def test_schema_version_is_recorded(self) -> None:
        self.assertEqual(self.store.schema_version, 1)

    def test_to_dict_is_json_shaped(self) -> None:
        created = self.store.create("note", "demo", {"title": "x"})
        payload = created.to_dict()
        self.assertEqual(
            set(payload), {"id", "type", "pack", "data", "created_at", "updated_at"}
        )


class TestFileDiscipline(StoreTestCase):
    """The store is the operator's business, so the file it lives in is theirs alone."""

    def test_the_store_is_readable_by_its_owner_only(self) -> None:
        # SQLite creates the file with the process umask — 0644 on a default machine, so
        # every other account on it could read the customers, the prices and the compliance
        # records (the internal audit K10).
        self.store.create("note", "demo", {"title": "x"})  # makes the -wal appear
        for suffix in ("", "-wal"):
            companion = Path(f"{self.path}{suffix}")
            with self.subTest(suffix=suffix or "db"):
                self.assertTrue(companion.exists(), f"{companion} was not created")
                self.assertEqual(stat.S_IMODE(companion.stat().st_mode), 0o600)

    def test_an_existing_store_is_tightened_on_open(self) -> None:
        self.store.close()
        self.path.chmod(0o644)
        with Store(self.path) as reopened:
            self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
            self.assertEqual(reopened.count("note"), 0)

    def test_the_store_is_a_context_manager(self) -> None:
        # The suite used to print `ResourceWarning: unclosed database`; a caller that wants to
        # be sure can now say so in one line (the internal audit K9).
        path = Path(self._dir.name) / "context.db"
        with Store(path) as store:
            store.create("note", "demo", {"title": "x"})
        with Store(path) as again:
            self.assertEqual(again.count("note"), 1)

    def test_wal_is_actually_in_force(self) -> None:
        # A store that silently stayed in `delete` mode is the two-process case quietly
        # broken (the internal audit K12).
        with Store(self.path) as store:
            mode = store._db.execute("PRAGMA journal_mode").fetchone()[0]
        self.assertEqual(str(mode).lower(), "wal")


class TestStreaming(StoreTestCase):
    def test_iter_records_walks_everything_once(self) -> None:
        made = [self.store.create("note", "demo", {"title": f"n{i}"}).id for i in range(25)]
        seen = [record.id for record in iter_records(self.store, "note", batch=4)]
        self.assertEqual(seen, sorted(made))

    def test_a_row_written_mid_export_is_not_repeated_or_skipped(self) -> None:
        # The bug an `OFFSET` walk had: a row inserted behind the cursor shifts every later
        # page by one, so the export both repeats and skips (the internal audit K11).
        made = [self.store.create("note", "demo", {"title": f"n{index}"}).id for index in range(10)]

        seen: list[str] = []
        for index, record in enumerate(iter_records(self.store, "note", batch=3)):
            seen.append(record.id)
            if index == 2:
                self.store.create("note", "demo", {"title": "inserted mid-walk"})

        self.assertEqual(len(seen), len(set(seen)), "a record was yielded twice")
        self.assertEqual(seen, sorted(seen), "the walk went backwards")
        # Every record that existed when the walk started is in it exactly once. A record
        # written mid-walk is seen only if it landed ahead of the cursor, which is what a
        # keyset walk promises and all it promises.
        for identifier in made:
            with self.subTest(identifier=identifier):
                self.assertEqual(seen.count(identifier), 1)
        self.assertIn(len(seen), (10, 11))


if __name__ == "__main__":
    unittest.main()


class StoreRobustnessTest(unittest.TestCase):
    """Failures a caller can act on, rather than the ones sqlite happens to raise."""

    def test_a_store_whose_parent_is_a_file_is_a_store_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            blocker = Path(directory) / "not-a-directory"
            blocker.write_text("x")
            with self.assertRaises(StoreError):
                Store(blocker / "records.db")

    def test_a_store_path_that_cannot_be_opened_is_a_store_error(self) -> None:
        with self.assertRaises(StoreError):
            Store("/proc/1/definitely-not-writable.db")

    def test_an_id_the_counter_cannot_read_is_refused_not_crashed(self) -> None:
        # `isdigit()` is true for "²" and `int()` is capped at 4300 digits, so both of these
        # raised `ValueError` out of `adopt_sequence` (the internal security audit
        # A19-KERN-5).
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / "records.db")
            try:
                self.assertFalse(store.adopt_sequence("invoice", "INV-²", prefix="INV"))
                self.assertFalse(store.adopt_sequence("invoice", "INV-" + "9" * 5000, prefix="INV"))
                self.assertTrue(store.adopt_sequence("invoice", "INV-0007", prefix="INV"))
                self.assertEqual(store.next_sequence("invoice"), 8)
            finally:
                store.close()

    def test_a_zero_batch_export_is_refused_rather_than_empty(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / "records.db")
            try:
                store.create("note", "example", {"title": "one"})
                with self.assertRaises(StoreError):
                    list(iter_records(store, "note", batch=0))
                self.assertEqual(len(list(iter_records(store, "note", batch=1))), 1)
            finally:
                store.close()
