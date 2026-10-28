"""Tests for the BFF.

These drive the :class:`Bff` application object directly rather than over a socket, so they
test the contract — routing, validation, id allocation, status codes — without a port, a
thread or a race. The HTTP layer above it is thin and deliberately boring.

Run from the repo root:

    PYTHONPATH=core/src:app/server python -m unittest discover -s app/server/tests -t app/server/tests
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "core" / "src"))
sys.path.insert(0, str(REPO_ROOT / "app" / "server"))

from pantler_core import PackRegistry, Store, pack_from_dict  # noqa: E402

from pantler_server import ApiError, Bff  # noqa: E402

PACK = {
    "id": "example",
    "name": "Example",
    "records": [
        {
            "type": "note",
            "label": "Note",
            "plural": "Notes",
            "id_prefix": "NOTE",
            "id_sequence": True,
            "fields": [
                {"name": "title", "label": "Title", "required": True},
                {"name": "kind", "label": "Kind", "kind": "enum", "options": ["observation", "task"]},
                {"name": "cost", "label": "Cost", "kind": "money"},
            ],
        }
    ],
    "screens": [{"id": "notes", "title": "Notes", "record_type": "note", "columns": ["title", "kind"]}],
}


FIRST_PACK = """
id = "first"
label = "First"
[[records]]
type = "note"
label = "Note"
plural = "Notes"
title_field = "title"
[[records.fields]]
name = "title"
kind = "text"
"""

SECOND_PACK = """
id = "second"
label = "Second"
[[records]]
type = "task"
label = "Task"
plural = "Tasks"
title_field = "title"
[[records.fields]]
name = "title"
kind = "text"
"""

CUSTOM_PACK = """
id = "custom-cleaning"
name = "Kitchen cleaning log"
[[records]]
type = "cleaning_log"
label = "Kitchen cleaning log"
plural = "Kitchen cleaning logs"
title_field = "date"
id_prefix = "CLN"
id_sequence = true

  [[records.fields]]
  name = "date"
  kind = "date"
  required = true

  [[records.fields]]
  name = "task"
  required = true

[[screens]]
id = "cleaning_log"
title = "Kitchen cleaning logs"
record_type = "cleaning_log"
columns = ["date", "task"]
"""


class BffTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.store_path = Path(self._dir.name) / "records.db"
        self.store = Store(self.store_path)
        self.bff = Bff(self.store, PackRegistry([pack_from_dict(PACK)]))

    def tearDown(self) -> None:
        self.store.close()
        self._dir.cleanup()

    def call(self, handler: str, **params):
        return getattr(self.bff, handler)(params)

    def create(self, **data):
        status, payload = self.call("create_record", type="note", body=data)
        self.assertEqual(status, 201)
        return payload


class TestMeta(BffTestCase):
    def test_health_reports_the_store_and_packs(self) -> None:
        status, payload = self.call("health")
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["packs"], ["example"])
        self.assertEqual(payload["record_types"], ["note"])

    def test_a_pack_added_while_the_server_runs_is_picked_up(self) -> None:
        """The registry was built once at boot and never re-read.

        The running dev BFF still reported `packs: ["example"]` after `farm` and `trade` existed,
        so the live app was missing two packs' screens and record types with no signal
        (the internal audit BFF-15).
        """
        packs = Path(self._dir.name) / "packs"
        (packs / "first").mkdir(parents=True)
        (packs / "first" / "pack.toml").write_text(FIRST_PACK, encoding="utf-8")
        self.bff.watch_packs(packs)
        self.assertEqual(self.call("health")[1]["packs"], ["first"])

        (packs / "second").mkdir()
        (packs / "second" / "pack.toml").write_text(SECOND_PACK, encoding="utf-8")
        self.assertEqual(self.call("health")[1]["packs"], ["first", "second"])
        self.assertEqual(self.call("list_packs")[1]["data"][-1]["id"], "second")

    def test_a_broken_pack_keeps_the_previous_registry_and_says_so(self) -> None:
        packs = Path(self._dir.name) / "packs"
        (packs / "first").mkdir(parents=True)
        (packs / "first" / "pack.toml").write_text(FIRST_PACK, encoding="utf-8")
        self.bff.watch_packs(packs)
        self.assertEqual(self.call("health")[1]["packs"], ["first"])

        # A record with no fields: `PackError`, not a pack that quietly declares nothing.
        (packs / "first" / "pack.toml").write_text(
            'id = "first"\nlabel = "First"\n[[records]]\ntype = "note"\n', encoding="utf-8"
        )
        payload = self.call("health")[1]
        self.assertEqual(payload["packs"], ["first"], "the old registry keeps serving")
        self.assertIn("packs_error", payload)

    def test_packs_returns_what_the_shell_renders_from(self) -> None:
        status, payload = self.call("list_packs")
        self.assertEqual(status, 200)
        pack = payload["data"][0]
        self.assertEqual(pack["id"], "example")
        self.assertEqual(pack["screens"][0]["record_type"], "note")
        # A list, always: one field is the common case, and a type whose rows would otherwise
        # read identically names more than one (the internal audit PACK-2).
        self.assertEqual(pack["records"][0]["title_field"], ["title"])

    def test_a_custom_pack_is_loaded_and_its_type_can_be_written(self) -> None:
        packs = Path(self._dir.name) / "packs"
        custom = Path(self._dir.name) / "custom-packs"
        (packs / "first").mkdir(parents=True)
        (packs / "first" / "pack.toml").write_text(FIRST_PACK, encoding="utf-8")
        (custom / "cleaning").mkdir(parents=True)
        (custom / "cleaning" / "pack.toml").write_text(CUSTOM_PACK, encoding="utf-8")
        self.bff.watch_packs(packs, custom)

        self.assertEqual(self.call("health")[1]["packs"], ["first", "custom-cleaning"])
        listed = self.call("list_packs")[1]["data"]
        self.assertTrue(next(pack for pack in listed if pack["id"] == "custom-cleaning")["custom"])

        status, payload = self.call(
            "create_record",
            type="cleaning_log",
            body={"date": "2026-10-22", "task": "Floors and benches"},
        )
        self.assertEqual(status, 201)
        self.assertEqual(payload["id"], "CLN-0001")
        self.assertEqual(payload["data"]["task"], "Floors and benches")


class TestCreate(BffTestCase):
    def test_create_allocates_a_sequential_id(self) -> None:
        self.assertEqual(self.create(title="first")["id"], "NOTE-0001")
        self.assertEqual(self.create(title="second")["id"], "NOTE-0002")

    def test_ids_do_not_restart_when_the_process_does(self) -> None:
        self.create(title="first")
        self.store.close()

        reopened = Store(self.store_path)
        try:
            bff = Bff(reopened, PackRegistry([pack_from_dict(PACK)]))
            status, payload = bff.create_record({"type": "note", "body": {"title": "after restart"}})
            self.assertEqual(status, 201)
            self.assertEqual(payload["id"], "NOTE-0002")
        finally:
            reopened.close()

    def test_an_explicit_id_is_honoured(self) -> None:
        status, payload = self.call("create_record", type="note", body={"title": "x", "id": "NOTE-9999"})
        self.assertEqual(status, 201)
        self.assertEqual(payload["id"], "NOTE-9999")

    def test_a_duplicate_explicit_id_is_a_conflict(self) -> None:
        self.call("create_record", type="note", body={"title": "x", "id": "NOTE-1"})
        with self.assertRaises(ApiError) as caught:
            self.call("create_record", type="note", body={"title": "y", "id": "NOTE-1"})
        self.assertEqual(caught.exception.status, 409)


class TestValidation(BffTestCase):
    def test_a_missing_required_field_is_unprocessable(self) -> None:
        with self.assertRaises(ApiError) as caught:
            self.call("create_record", type="note", body={"kind": "task"})
        self.assertEqual(caught.exception.status, 422)
        self.assertIn("Title is required", caught.exception.message)

    def test_a_bad_enum_is_unprocessable(self) -> None:
        with self.assertRaises(ApiError) as caught:
            self.call("create_record", type="note", body={"title": "x", "kind": "nonsense"})
        self.assertIn("observation, task", caught.exception.message)

    def test_a_missing_body_is_a_bad_request(self) -> None:
        with self.assertRaises(ApiError) as caught:
            self.call("create_record", type="note")
        self.assertEqual(caught.exception.status, 400)


class TestRead(BffTestCase):
    def test_get_returns_the_record(self) -> None:
        created = self.create(title="first", kind="task")
        status, payload = self.call("get_record", type="note", id=created["id"])
        self.assertEqual(status, 200)
        self.assertEqual(payload["data"]["title"], "first")

    def test_get_missing_is_404(self) -> None:
        with self.assertRaises(ApiError) as caught:
            self.call("get_record", type="note", id="NOTE-9999")
        self.assertEqual(caught.exception.status, 404)

    def test_list_reports_a_total_for_paging(self) -> None:
        for i in range(5):
            self.create(title=f"n{i}")
        status, payload = self.call("list_records", type="note", limit="2", offset="1", order="id ASC")
        self.assertEqual(status, 200)
        self.assertEqual(payload["total"], 5)
        self.assertEqual([r["id"] for r in payload["data"]], ["NOTE-0002", "NOTE-0003"])

    def test_limit_is_clamped(self) -> None:
        status, payload = self.call("list_records", type="note", limit="100000")
        self.assertEqual(payload["limit"], 500)

    def test_a_bad_order_is_a_bad_request_not_an_injection(self) -> None:
        with self.assertRaises(ApiError) as caught:
            self.call("list_records", type="note", order="updated_at DESC; DROP TABLE records")
        self.assertEqual(caught.exception.status, 400)
        self.assertEqual(self.store.count("note"), 0)


class TestUpdateAndDelete(BffTestCase):
    def test_patch_merges_and_leaves_the_other_fields_alone(self) -> None:
        # PATCH means patch. Replacing meant a one-field edit dropped everything else — and
        # because a required field is validated, it was refused outright unless the whole
        # record was resent (the internal audit BFF-1).
        created = self.create(title="before", kind="task")
        status, payload = self.call(
            "patch_record", type="note", id=created["id"], body={"title": "after"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["data"], {"title": "after", "kind": "task"})

    def test_patch_of_an_empty_body_changes_nothing(self) -> None:
        created = self.create(title="before", kind="task")
        status, payload = self.call("patch_record", type="note", id=created["id"], body={})
        self.assertEqual(status, 200)
        self.assertEqual(payload["data"], {"title": "before", "kind": "task"})

    def test_patch_validates_the_merged_record(self) -> None:
        created = self.create(title="before", kind="task")
        with self.assertRaises(ApiError) as caught:
            self.call("patch_record", type="note", id=created["id"], body={"kind": "nonsense"})
        self.assertEqual(caught.exception.status, 422)
        # And a refused patch did not half-write: the record is exactly as it was.
        _, unchanged = self.call("get_record", type="note", id=created["id"])
        self.assertEqual(unchanged["data"]["kind"], "task")
        self.assertEqual(unchanged["data"]["title"], "before")

    def test_put_replaces_the_whole_record(self) -> None:
        created = self.create(title="before", kind="task")
        status, payload = self.call(
            "replace_record", type="note", id=created["id"], body={"title": "after"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["data"], {"title": "after"})

    def test_put_demands_a_complete_record(self) -> None:
        created = self.create(title="before", kind="task")
        with self.assertRaises(ApiError) as caught:
            self.call("replace_record", type="note", id=created["id"], body={})
        self.assertEqual(caught.exception.status, 422)

    def test_patch_missing_is_404(self) -> None:
        with self.assertRaises(ApiError) as caught:
            self.call("patch_record", type="note", id="NOTE-9999", body={"title": "x"})
        self.assertEqual(caught.exception.status, 404)

    def test_delete_then_get_is_404(self) -> None:
        created = self.create(title="gone")
        status, payload = self.call("delete_record", type="note", id=created["id"])
        self.assertEqual(status, 204)
        self.assertIsNone(payload)
        with self.assertRaises(ApiError):
            self.call("get_record", type="note", id=created["id"])

    def test_delete_missing_is_404(self) -> None:
        with self.assertRaises(ApiError) as caught:
            self.call("delete_record", type="note", id="NOTE-9999")
        self.assertEqual(caught.exception.status, 404)


class TestUnknownTypes(BffTestCase):
    def test_an_undeclared_type_is_404_and_says_what_is_known(self) -> None:
        # The most likely mistake is a pack that failed to load, so the message names what
        # the registry actually holds rather than just refusing.
        with self.assertRaises(ApiError) as caught:
            self.call("list_records", type="invoice")
        self.assertEqual(caught.exception.status, 404)
        self.assertIn("note", caught.exception.message)

    def test_an_empty_registry_still_answers_health(self) -> None:
        bff = Bff(self.store, PackRegistry())
        status, payload = bff.health({})
        self.assertEqual(status, 200)
        self.assertEqual(payload["packs"], [])


if __name__ == "__main__":
    unittest.main()
