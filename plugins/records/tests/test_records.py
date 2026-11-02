"""The record tools, loaded the way the engine loads them, against a real store and packs."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parent
REPO = PLUGIN.parent.parent
sys.path.insert(0, str(REPO / "core" / "src"))


class PerKeyCtx:
    def __init__(self, **settings):
        self.settings = settings
        self.tools: list = []
        self.hooks: dict[str, list] = {}

    def register_tool(self, **kw):
        self.tools.append(kw)

    def register_hook(self, name, callback):
        self.hooks.setdefault(name, []).append(callback)

    def get_config(self, key=None, default=None):
        if key is None:
            return dict(self.settings)
        return self.settings.get(key, default)


def load_plugin():
    for name in [n for n in sys.modules if n == "records_plugin" or n.startswith("records_plugin.")]:
        del sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        "records_plugin", PLUGIN / "__init__.py", submodule_search_locations=[str(PLUGIN)]
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["records_plugin"] = module
    spec.loader.exec_module(module)
    return module


class RecordsPluginTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.dir = Path(self._dir.name)
        self.mod = load_plugin()
        self.ctx = PerKeyCtx(
            store_path=str(self.dir / "records.db"),
            packs_dir=str(REPO / "packs"),
            custom_packs_dir=str(self.dir / "custom-packs"),
        )
        self.mod.register(self.ctx)

    def tearDown(self) -> None:
        book = self.mod.tools._STATE.get("book")
        if book is not None:
            book.close()
        self.mod.tools._STATE["book"] = None
        self._dir.cleanup()

    def call(self, name: str, params: dict) -> dict:
        handler = next(tool["handler"] for tool in self.ctx.tools if tool["name"] == name)
        return json.loads(handler(params))

    def test_registers_the_record_tools_under_the_records_toolset(self) -> None:
        self.assertEqual(
            sorted(t["name"] for t in self.ctx.tools),
            [
                "capture_dismiss",
                "capture_link",
                "capture_save",
                "record_find",
                "record_save",
                "record_type_create",
                "record_type_propose",
                "record_types",
            ],
        )
        self.assertEqual({t["toolset"] for t in self.ctx.tools}, {"records"})
        self.assertEqual(len(self.ctx.hooks["pre_tool_call"]), 1)

    def test_a_certificate_is_saved_and_read_back(self) -> None:
        saved = self.call(
            "record_save",
            {
                "type": "certificate",
                "fields": {
                    "holder": "our business",
                    "scheme": "ACO",
                    "certifier": "Australian Certified Organic",
                    "number": "12345",
                    "expires": "2027-03-31",
                },
            },
        )
        self.assertTrue(saved["success"], saved)
        self.assertEqual(saved["id"], "CERT-0001")
        found = self.call("record_find", {"type": "certificate", "where": {"holder": "our business"}})
        self.assertEqual(found["count"], 1)
        self.assertEqual(found["records"][0]["scheme"], "ACO")

    def test_a_missing_required_field_is_refused_with_the_field_named(self) -> None:
        refused = self.call("record_save", {"type": "certificate", "fields": {"scheme": "ACO"}})
        self.assertFalse(refused["success"])
        # The sentence reads well for the operator; the machine name is what the model must pass.
        self.assertIn("certificate", refused["error"])
        self.assertIn(
            "holder",
            {field["name"] for field in refused["required"]},
            "the refusal must name the field the model has to collect",
        )

    def test_an_unknown_type_lists_what_is_installed(self) -> None:
        refused = self.call("record_save", {"type": "unicorn", "fields": {}})
        self.assertFalse(refused["success"])
        self.assertIn("certificate", refused["error"])

    def test_finding_nothing_says_so_rather_than_failing(self) -> None:
        found = self.call("record_find", {"type": "certificate"})
        self.assertTrue(found["success"])
        self.assertEqual(found["count"], 0)
        self.assertIn("no such record", found["note"])

    def test_a_hostile_limit_is_refused_rather_than_raised(self) -> None:
        """`limit` came straight from the model into `int()`.

        A list was a TypeError, an infinity an OverflowError, a negative number silently read one
        record and 0 meant ten — all of them escapes rather than refusals
        (the internal audit PLUG-8, PLUG-16).
        """
        for value in ([1], float("inf"), -3, 0, "abc", True, 99_999):
            with self.subTest(limit=value):
                answer = self.call("record_find", {"type": "certificate", "limit": value})
                self.assertFalse(answer["success"], answer)
                self.assertIn("limit", answer["error"])

    def test_a_sane_limit_still_reaches_the_store(self) -> None:
        answer = self.call("record_find", {"type": "certificate", "limit": 5})
        self.assertTrue(answer["success"], answer)

    def test_the_type_list_carries_the_required_fields(self) -> None:
        listed = self.call("record_types", {})
        self.assertTrue(listed["success"], listed)
        certificate = next(t for t in listed["types"] if t["type"] == "certificate")
        required = {f["name"] for f in certificate["fields"] if f["required"]}
        self.assertEqual(required, {"holder", "scheme"})

    def test_the_types_this_tool_does_not_write_are_refused_with_a_sentence(self) -> None:
        """The store saves any installed type, so this one call could forge what a gate reads.

        An invoice number, a consent record and a spray application were all writable from a
        conversation — past the spray engine, past the consent gate, and into the records both of
        them trust (the internal security audit A19-PLUG-1, A19-PLUG-2, A19-DIST-8).
        """
        for type_name, fields in (
            ("invoice", {"number": "INV-0001", "customer": "Mallory Holdings (forged)"}),
            (
                "invoice_line",
                {
                    "invoice": "INV-0001",
                    "description": "forged",
                    "quantity": 1,
                    "unit_price_cents": 1,
                    "amount_cents": 1,
                },
            ),
            (
                "consent",
                {"who": "Alice Chen", "what": "newsletter", "where_used": "the newsletter"},
            ),
            ("campaign", {"name": "Launch"}),
            (
                "application",
                {
                    "date": "2026-10-19",
                    "block": "BLK-9999",
                    "input": "INP-9999",
                    "rate": 250,
                    "rate_unit": "L/ha",
                    "withholding_days": 0,
                },
            ),
        ):
            with self.subTest(type=type_name):
                refused = self.call("record_save", {"type": type_name, "fields": fields})
                self.assertFalse(refused["success"], refused)
                self.assertIn(type_name, refused["error"])
                self.assertIn("not a record this tool writes", refused["error"])
                self.assertNotIn("Traceback", json.dumps(refused))

    def test_no_forged_record_landed_in_the_store(self) -> None:
        self.call(
            "record_save",
            {
                "type": "invoice",
                "fields": {"number": "INV-0001", "customer": "Mallory Holdings (forged)"},
            },
        )
        self.call(
            "record_save",
            {
                "type": "consent",
                "fields": {"who": "Alice Chen", "what": "newsletter", "where_used": "the newsletter"},
            },
        )
        self.assertEqual(self.call("record_find", {"type": "invoice"})["count"], 0)
        self.assertEqual(self.call("record_find", {"type": "consent"})["count"], 0)

    def test_the_four_types_this_tool_writes_still_work(self) -> None:
        for type_name, fields in (
            ("certificate", {"holder": "our business", "scheme": "ACO"}),
            ("block", {"name": "North block", "area_ha": 2}),
            ("harvest", {"lot": "LOT-1", "date": "2026-10-01"}),
            ("input", {"name": "Copper oxychloride 500", "unit": "kg"}),
        ):
            with self.subTest(type=type_name):
                saved = self.call("record_save", {"type": type_name, "fields": fields})
                self.assertTrue(saved["success"], saved)
                self.assertEqual(saved["type"], type_name)
                self.assertTrue(saved["id"])

    def test_the_schema_names_only_the_types_this_tool_writes(self) -> None:
        description = next(
            tool["schema"]["description"]
            for tool in self.ctx.tools
            if tool["name"] == "record_save"
        )
        for type_name in ("certificate", "block", "harvest", "input"):
            self.assertIn(type_name, description)
        type_property = next(
            tool["schema"]["parameters"]["properties"]["type"]["description"]
            for tool in self.ctx.tools
            if tool["name"] == "record_save"
        )
        self.assertNotIn("application", type_property)

    def test_a_saved_record_reports_the_fields_it_left_empty(self) -> None:
        """The gap that caused a 407,000-token file hunt becomes a question in the result."""
        saved = self.call(
            "record_save",
            {
                "type": "certificate",
                "fields": {"holder": "our business", "scheme": "ACO"},
            },
        )
        self.assertTrue(saved["success"], saved)
        named = {field["name"] for field in saved["empty_fields"]}
        self.assertIn("evidence", named)
        self.assertIn("expires", named)
        # A field that was filled is not reported as a gap, and neither is a required one.
        self.assertNotIn("scheme", named)
        self.assertNotIn("holder", named)

    def test_a_switched_off_capability_refuses(self) -> None:
        ctx = PerKeyCtx(
            store_path=str(self.dir / "records.db"),
            packs_dir=str(REPO / "packs"),
            capability_enabled=False,
        )
        self.mod.register(ctx)
        for tool in ctx.tools:
            with self.subTest(tool=tool["name"]):
                answer = json.loads(tool["handler"]({"type": "certificate"}))
                self.assertFalse(answer["success"])
                self.assertIn("switched off in Capabilities", answer["error"])

    def test_two_records_get_sequential_ids(self) -> None:
        for scheme in ("ACO", "NASAA"):
            saved = self.call(
                "record_save",
                {
                    "type": "certificate",
                    "fields": {"holder": "our business", "scheme": scheme},
                },
            )
            self.assertTrue(saved["success"], saved)
        self.assertEqual(self.call("record_find", {"type": "certificate"})["count"], 2)

    # ----------------------------------------------------- custom record types

    def _custom_spec(self) -> dict:
        return {
            "type": "cleaning_log",
            "label": "Kitchen cleaning log",
            "plural": "Kitchen cleaning logs",
            "id_prefix": "CLN",
            "fields": [
                {"name": "date", "label": "Date", "kind": "date", "required": True},
                {"name": "task", "label": "Task", "kind": "text", "required": True},
                {"name": "cleaner", "label": "Cleaner", "kind": "text"},
                {"name": "sign_off", "label": "Signed off by", "kind": "text"},
                {"name": "notes", "label": "Notes", "kind": "longtext"},
            ],
            "columns": ["date", "task", "cleaner"],
        }

    # -- captures -------------------------------------------------------

    def test_a_capture_is_saved_immediately_without_a_typed_record(self) -> None:
        saved = self.call(
            "capture_save",
            {"text": "I sprayed the tomatoes in block B today", "occurred_on": "2026-10-30", "tags": "block B, tomatoes"},
        )
        self.assertTrue(saved["success"], saved)
        self.assertEqual(saved["id"], "CAP-0001")
        self.assertEqual(saved["record"]["status"], "captured")
        self.assertEqual(saved["record"]["source"], "chat")
        self.assertEqual(saved["record"]["occurred_on"], "2026-10-30")
        found = self.call("record_find", {"type": "capture"})
        self.assertEqual(found["count"], 1)
        self.assertEqual(found["records"][0]["id"], "CAP-0001")

    def test_a_capture_does_not_need_a_date_and_keeps_the_words(self) -> None:
        saved = self.call("capture_save", {"text": "The north fence is damaged; fix it before the next crop."})
        self.assertTrue(saved["success"], saved)
        self.assertNotIn("occurred_on", saved["record"])
        self.assertEqual(saved["record"]["text"], "The north fence is damaged; fix it before the next crop.")

    def test_a_bad_capture_date_or_source_is_saved_with_a_warning(self) -> None:
        saved = self.call(
            "capture_save",
            {"text": "The ACO auditor is coming on 5 November.", "occurred_on": "next Tuesday", "source": "letter"},
        )
        self.assertTrue(saved["success"], saved)
        self.assertEqual(saved["record"]["status"], "captured")
        self.assertEqual(saved["record"]["source"], "chat")
        self.assertNotIn("occurred_on", saved["record"])
        self.assertEqual(len(saved.get("warnings", [])), 2)

    def test_an_empty_capture_is_refused(self) -> None:
        refused = self.call("capture_save", {"text": "   "})
        self.assertFalse(refused["success"], refused)
        self.assertIn("what should I capture", refused["error"])

    def test_record_save_cannot_write_a_capture(self) -> None:
        refused = self.call("record_save", {"type": "capture", "fields": {"text": "bypass", "status": "captured"}})
        self.assertFalse(refused["success"], refused)
        self.assertIn("capture_save", refused["error"])

    def test_capture_link_requires_a_real_record_and_marks_the_capture(self) -> None:
        capture = self.call("capture_save", {"text": "Harvested 420 kg of carrots, lot CAR-1001."})
        self.assertTrue(capture["success"], capture)
        missing = self.call(
            "capture_link",
            {"capture_id": capture["id"], "record_type": "harvest", "record_id": "HAR-9999"},
        )
        self.assertFalse(missing["success"], missing)
        self.assertIn("create the typed record first", missing["error"])

        block = self.call("record_save", {"type": "block", "fields": {"name": "Block A", "area_ha": 0.8}})
        self.assertTrue(block["success"], block)
        linked = self.call(
            "capture_link",
            {"capture_id": capture["id"], "record_type": "block", "record_id": block["id"]},
        )
        self.assertTrue(linked["success"], linked)
        self.assertEqual(linked["record"]["status"], "promoted")
        self.assertEqual(linked["record"]["record_type"], "block")
        self.assertEqual(linked["record"]["record_id"], block["id"])

    def test_a_promoted_capture_cannot_be_relinked(self) -> None:
        capture = self.call("capture_save", {"text": "A note to link once."})
        first = self.call("record_save", {"type": "block", "fields": {"name": "Block A"}})
        second = self.call("record_save", {"type": "block", "fields": {"name": "Block B"}})
        self.assertTrue(self.call(
            "capture_link",
            {"capture_id": capture["id"], "record_type": "block", "record_id": first["id"]},
        )["success"])
        refused = self.call(
            "capture_link",
            {"capture_id": capture["id"], "record_type": "block", "record_id": second["id"]},
        )
        self.assertFalse(refused["success"], refused)
        self.assertIn("already linked", refused["error"])

    def test_a_capture_can_be_dismissed_but_a_promoted_one_cannot(self) -> None:
        capture = self.call("capture_save", {"text": "A note the operator does not want."})
        dismissed = self.call("capture_dismiss", {"capture_id": capture["id"]})
        self.assertTrue(dismissed["success"], dismissed)
        self.assertEqual(dismissed["record"]["status"], "dismissed")

        promoted = self.call("capture_save", {"text": "A note that becomes a block."})
        block = self.call("record_save", {"type": "block", "fields": {"name": "Block C"}})
        self.assertTrue(self.call(
            "capture_link",
            {"capture_id": promoted["id"], "record_type": "block", "record_id": block["id"]},
        )["success"])
        refused = self.call("capture_dismiss", {"capture_id": promoted["id"]})
        self.assertFalse(refused["success"], refused)
        self.assertIn("already promoted", refused["error"])

    def test_capture_ids_are_sequential_and_not_record_ids(self) -> None:
        first = self.call("capture_save", {"text": "First capture."})
        second = self.call("capture_save", {"text": "Second capture."})
        self.assertEqual(first["id"], "CAP-0001")
        self.assertEqual(second["id"], "CAP-0002")
        block = self.call("record_save", {"type": "block", "fields": {"name": "Block D"}})
        self.assertEqual(block["id"], "BLK-0001")

    def test_propose_returns_a_schema_and_writes_nothing(self) -> None:
        proposed = self.call("record_type_propose", self._custom_spec())
        self.assertTrue(proposed["success"], proposed)
        self.assertEqual(proposed["type"], "cleaning_log")
        self.assertEqual([field["name"] for field in proposed["fields"]][:2], ["date", "task"])
        self.assertFalse((self.dir / "custom-packs").exists())

    def test_create_a_custom_type_and_save_a_record_in_it(self) -> None:
        created = self.call("record_type_create", self._custom_spec())
        self.assertTrue(created["success"], created)
        self.assertEqual(created["type"], "cleaning_log")
        pack = self.dir / "custom-packs" / "cleaning_log" / "pack.toml"
        self.assertTrue(pack.is_file())

        saved = self.call(
            "record_save",
            {
                "type": "cleaning_log",
                "fields": {"date": "2026-10-22", "task": "Floors, benches, sinks", "cleaner": "Sam"},
            },
        )
        self.assertTrue(saved["success"], saved)
        self.assertEqual(saved["id"], "CLN-0001")
        found = self.call("record_find", {"type": "cleaning_log"})
        self.assertEqual(found["count"], 1)
        listed = self.call("record_types", {})
        custom = next(t for t in listed["types"] if t["type"] == "cleaning_log")
        self.assertTrue(custom["custom"])

    def test_a_shipped_type_cannot_be_redeclared_as_custom(self) -> None:
        refused = self.call("record_type_create", {**self._custom_spec(), "type": "invoice"})
        self.assertFalse(refused["success"], refused)
        self.assertIn("already exists", refused["error"])

    def test_the_same_custom_type_cannot_be_created_twice(self) -> None:
        self.assertTrue(self.call("record_type_create", self._custom_spec())["success"])
        refused = self.call("record_type_create", self._custom_spec())
        self.assertFalse(refused["success"], refused)
        self.assertIn("already", refused["error"])

    def test_the_create_hook_asks_for_approval(self) -> None:
        hook = self.ctx.hooks["pre_tool_call"][0]
        decision = hook("record_type_create", self._custom_spec())
        self.assertEqual(decision["action"], "approve")
        self.assertIn("Kitchen cleaning log", decision["message"])
        self.assertIn("same records database", decision["message"])

    def test_the_guard_blocks_a_direct_pack_write(self) -> None:
        hook = self.ctx.hooks["pre_tool_call"][0]
        target = self.dir / "custom-packs" / "cleaning_log" / "pack.toml"
        decision = hook("write_file", {"path": str(target)})
        self.assertEqual(decision["action"], "block")
        self.assertIn("record_type_propose", decision["message"])

    def test_the_guard_blocks_a_terminal_write_to_the_store(self) -> None:
        hook = self.ctx.hooks["pre_tool_call"][0]
        decision = hook("terminal", {"command": "cat > records.db <<'EOF'\\nx\\nEOF"})
        self.assertEqual(decision["action"], "block")

    def test_the_guard_blocks_an_execute_code_write_to_the_store(self) -> None:
        hook = self.ctx.hooks["pre_tool_call"][0]
        decision = hook(
            "execute_code",
            {"code": "open('custom-packs/x/pack.toml', 'w').write('id = 1')"},
        )
        self.assertEqual(decision["action"], "block")



if __name__ == "__main__":
    unittest.main()
