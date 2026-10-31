"""The plugin as the engine loads it: registration, the capability switch, and the JSON shape.

Three things are protected here. The registration contract (two tools, one toolset) is what the
manifest declares. The capability switch is the difference between a tool that is hidden and a tool
that refuses — the engine keeps a registered handler until a restart, so the handler is what makes
"off" true. And the handler's *shape* is what the model reads: JSON with a `record` and, when
something needs settling, a `question` rather than an exception.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parent
REPO = PLUGIN.parent.parent
sys.path.insert(0, str(REPO / "core" / "src"))
BOOK = str(HERE / "fixtures" / "spraybook.json")


class HostileArgumentsTestCase(unittest.TestCase):
    """What the model may pass, and what the tool does with it.

    These are the audit's PLUG-11, PLUG-12 and PLUG-13: a compliance record that says a negative
    amount was applied, a ceiling compared across units, and a record written while a question
    about it was still open.
    """

    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.dir = Path(self._dir.name)
        self.mod = load_plugin()
        self.ctx = PerKeyCtx(
            store_path=str(self.dir / "records.db"),
            packs_dir=str(REPO / "packs"),
            catalogue_path=str(BOOK),
        )
        self.mod.register(self.ctx)

    def tearDown(self) -> None:
        # The spray book is not a handle; the record store is. Both caches are cleared so the
        # next test (and the next plugin load) starts from its own configuration.
        records = self.mod.tools._STATE.get("records")
        if records is not None:
            records.close()
        for key in ("book", "records", "source"):
            self.mod.tools._STATE[key] = None
        self._dir.cleanup()

    def call(self, **overrides) -> dict:
        args = {
            "applied": "2026-10-01",
            "block": "North block",
            "product": "Copper oxychloride 500",
            "rate": 2,
            "rate_unit": "kg/ha",
            "area_ha": 2,
        }
        args.update(overrides)
        handler = next(t["handler"] for t in self.ctx.tools if t["name"] == "spray_record")
        return json.loads(handler(args))

    def test_a_rate_of_nothing_is_a_question_not_a_record(self) -> None:
        for rate in (-5, 0):
            with self.subTest(rate=rate):
                answer = self.call(rate=rate)
                self.assertFalse(answer["success"], answer)
                self.assertTrue(any("more than nothing" in q for q in answer["questions"]))

    def test_an_area_of_nothing_is_a_question_and_no_amount_is_invented(self) -> None:
        answer = self.call(area_ha=0)
        self.assertTrue(any("more than nothing" in q for q in answer["questions"]))
        # One question about the missing number, not two, and no `used` worked out from nothing.
        self.assertEqual(len([q for q in answer["questions"] if "hectares" in q]), 1, answer)
        self.assertIsNone(answer.get("used"))

    def test_a_maximum_with_no_unit_is_not_compared(self) -> None:
        with open(BOOK, encoding="utf-8") as handle:
            book = copy.deepcopy(json.load(handle))
        for entry in book["inputs"]:
            if entry["name"] == "Copper oxychloride 500":
                entry.pop("max_rate_unit", None)
        path = self.dir / "nounit.json"
        path.write_text(json.dumps(book))
        self.ctx.settings["catalogue_path"] = str(path)
        self.mod.tools._STATE["book"] = None

        answer = self.call(rate=99)
        self.assertTrue(answer["success"], answer)
        self.assertTrue(any("no unit beside it" in w for w in answer["warnings"]), answer)
        self.assertEqual(answer["questions"], [], "an incomparable maximum produced a question")

    def test_a_dry_run_computes_and_writes_nothing(self) -> None:
        answer = self.call(dry_run=True)
        self.assertTrue(answer["success"], answer)
        self.assertTrue(answer["dry_run"])
        self.assertFalse(answer["saved"])
        self.assertIn("Nothing was written", answer["note"])
        self.assertNotIn("id", answer, "a dry run allocated an id")

    def test_a_hostile_rate_is_refused_rather_than_raised(self) -> None:
        """`1e400` is not a rate it should convert — it is a number built to overflow one.

        `Fraction("1e400")` reached `_number`, which converted it to a float and left as an
        `OverflowError`; `"1/0"` left as a `ZeroDivisionError`
        (the internal security audit A19-PLUG-5).
        """
        for rate in ("1e400", "1/0", float("inf"), "9" * 400):
            with self.subTest(rate=rate):
                answer = self.call(rate=rate)
                self.assertFalse(answer["success"], answer)
                self.assertTrue(answer.get("question") or answer.get("error"), answer)
                self.assertNotIn("Traceback", json.dumps(answer))

    def test_the_same_call_without_dry_run_writes_once(self) -> None:
        answer = self.call()
        self.assertTrue(answer["success"], answer)
        self.assertTrue(answer["saved"], answer)
        self.assertIn("id", answer)


class PerKeyCtx:
    """The engine's reader: `ctx.get_config(key, default)`, live on every call."""

    def __init__(self, **settings):
        self.settings = settings
        self.tools: list = []

    def register_tool(self, **kw):
        self.tools.append(kw)

    def get_config(self, key=None, default=None):
        if key is None:
            return dict(self.settings)
        return self.settings.get(key, default)


def load_plugin():
    for name in [n for n in sys.modules if n == "spray_plugin" or n.startswith("spray_plugin.")]:
        del sys.modules[name]
    init = PLUGIN / "__init__.py"
    spec = importlib.util.spec_from_file_location(
        "spray_plugin", init, submodule_search_locations=[str(PLUGIN)]
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["spray_plugin"] = module
    spec.loader.exec_module(module)
    return module


class SprayPluginTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = load_plugin()
        self.ctx = PerKeyCtx(catalogue_path=BOOK)
        self.mod.register(self.ctx)

    def tearDown(self) -> None:
        # The plugin caches the record store it was pointed at; closing it here keeps the suite free
        # of unclosed-database warnings (and is what a long-running host would do on shutdown).
        for key in ("records", "book"):
            book = self.mod.tools._STATE.get(key)
            if book is not None and hasattr(book, "close"):
                book.close()
            self.mod.tools._STATE[key] = None

    def call(self, name: str, params: dict) -> dict:
        handler = next(tool["handler"] for tool in self.ctx.tools if tool["name"] == name)
        return json.loads(handler(params))

    def test_register_asks_for_the_declared_tools_under_our_toolset(self) -> None:
        self.assertEqual(
            sorted(tool["name"] for tool in self.ctx.tools), ["spray_inputs", "spray_record"]
        )
        self.assertEqual({tool["toolset"] for tool in self.ctx.tools}, {"spray"})

    def test_every_schema_tells_the_model_not_to_compute(self) -> None:
        for tool in self.ctx.tools:
            description = tool["schema"]["description"].lower()
            with self.subTest(tool=tool["name"]):
                self.assertTrue(description)
                if tool["name"] == "spray_record":
                    self.assertIn("arithmetic is done here", description)

    def test_a_record_comes_back_with_the_computed_numbers(self) -> None:
        result = self.call(
            "spray_record",
            {
                "applied": "2026-10-14",
                "block": "north",
                "product": "copper",
                "rate": 2.5,
                "rate_unit": "kg/ha",
            },
        )
        self.assertTrue(result["success"], result)
        self.assertEqual(result["product_used"], {"amount": 8.75, "unit": "kg"})
        self.assertEqual(result["record"]["earliest_safe_date"], "2026-10-15")

    def test_a_question_comes_back_as_a_question_not_an_exception(self) -> None:
        result = self.call(
            "spray_record",
            {
                "applied": "2026-10-14",
                "block": "south forty",
                "product": "copper",
                "rate": 1,
                "rate_unit": "kg/ha",
            },
        )
        self.assertFalse(result["success"])
        self.assertIn("south forty", result["question"])

    def test_the_input_list_reports_which_label_facts_are_missing(self) -> None:
        result = self.call("spray_inputs", {})
        self.assertTrue(result["success"], result)
        by_name = {row["name"]: row for row in result["inputs"]}
        self.assertEqual(by_name["Copper oxychloride 500"]["withholding_days"], 1)
        self.assertIn("withholding period", by_name["Wettable sulphur"]["missing"])
        self.assertIn("maximum rate", by_name["Fish emulsion"]["missing"])

    def test_the_record_is_actually_written_when_a_store_is_configured(self) -> None:
        """The property the first version of this tool got wrong: it computed and claimed.

        `RecordBook` is the kernel's, so the record this writes is the same one the app would
        write — and a second book opened on the same file can see it.
        """
        import tempfile
        from pathlib import Path

        from pantler_core import RecordBook

        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "records.db"
            ctx = PerKeyCtx(catalogue_path=BOOK, store_path=str(store), packs_dir=str(REPO / "packs"))
            self.mod.register(ctx)
            handler = next(t["handler"] for t in ctx.tools if t["name"] == "spray_record")
            result = json.loads(
                handler(
                    {
                        "applied": "2026-10-14",
                        "block": "north",
                        "product": "copper",
                        "rate": 2.5,
                        "rate_unit": "kg/ha",
                    }
                )
            )
            self.assertTrue(result["saved"], result)
            self.assertEqual(result["id"], "APP-0001")
            self.assertIn("APP-0001", result["summary"])
            reader = RecordBook(store, REPO / "packs")
            try:
                stored = reader.get("application", "APP-0001")
                self.assertIsNotNone(stored)
                assert stored is not None
                self.assertEqual(stored.data["earliest_safe_date"], "2026-10-15")
                self.assertEqual(stored.data["withholding_days"], 1)
            finally:
                reader.close()

    def test_without_a_store_the_answer_says_nothing_was_written(self) -> None:
        """A computed record that was not saved must not be reported as saved."""
        handler = next(t["handler"] for t in self.ctx.tools if t["name"] == "spray_record")
        result = json.loads(
            handler(
                {
                    "applied": "2026-10-14",
                    "block": "north",
                    "product": "copper",
                    "rate": 1,
                    "rate_unit": "kg/ha",
                }
            )
        )
        self.assertFalse(result["saved"])
        self.assertTrue(any("Nothing was written" in w for w in result["warnings"]), result)

    def test_the_records_are_the_spray_book_when_they_hold_anything(self) -> None:
        """The fix for the fault a live conversation found: one set of facts, entered once.

        A block and an input are written through the record store — the way the app writes them —
        and the tool must resolve against those, not against a JSON file beside them.
        """
        import tempfile
        from pathlib import Path

        from pantler_core import RecordBook

        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "records.db"
            writer = RecordBook(store, REPO / "packs")
            writer.save(
                "block",
                {"name": "North block", "area_ha": 3.5, "certified": "organic"},
            )
            writer.save(
                "input",
                {
                    "name": "Copper oxychloride 500",
                    "unit": "kg",
                    "withholding_days": 1,
                    "re_entry_hours": 24,
                    "registration": "APVMA 12345",
                    "max_rate": 3,
                    "max_rate_unit": "kg/ha",
                },
            )
            writer.close()

            # No catalogue_path at all: the records are the only source.
            ctx = PerKeyCtx(store_path=str(store), packs_dir=str(REPO / "packs"))
            self.mod.register(ctx)
            handler = next(t["handler"] for t in ctx.tools if t["name"] == "spray_record")
            result = json.loads(
                handler(
                    {
                        "applied": "2026-10-14",
                        "block": "north",
                        "product": "copper",
                        "rate": 2.5,
                        "rate_unit": "kg/ha",
                    }
                )
            )
            self.assertTrue(result["success"], result)
            self.assertIn("records", result["spray_book_source"])
            self.assertEqual(result["record"]["area_ha"], 3.5)
            self.assertEqual(result["record"]["earliest_safe_date"], "2026-10-15")
            self.assertEqual(result["registration"], "APVMA 12345")

    def test_a_rate_above_the_recorded_maximum_is_a_question(self) -> None:
        """The label maximum lives on the input record now, so the ceiling check works from records."""
        import tempfile
        from pathlib import Path

        from pantler_core import RecordBook

        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "records.db"
            writer = RecordBook(store, REPO / "packs")
            writer.save("block", {"name": "North block", "area_ha": 2})
            writer.save(
                "input",
                {"name": "Copper", "unit": "kg", "max_rate": 3, "max_rate_unit": "kg/ha"},
            )
            writer.close()
            ctx = PerKeyCtx(store_path=str(store), packs_dir=str(REPO / "packs"))
            self.mod.register(ctx)
            handler = next(t["handler"] for t in ctx.tools if t["name"] == "spray_record")
            result = json.loads(
                handler(
                    {
                        "applied": "2026-10-14",
                        "block": "north",
                        "product": "copper",
                        "rate": 4,
                        "rate_unit": "kg/ha",
                    }
                )
            )
            self.assertEqual(result["record"]["rate"], 4)  # recorded as given
            self.assertTrue(result["questions"], result)

    def test_the_file_is_used_only_when_the_records_hold_nothing(self) -> None:
        """And the result says so, because a name that resolves in one place and not the other is
        exactly the confusion this replaced."""
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            ctx = PerKeyCtx(
                catalogue_path=BOOK,
                store_path=str(Path(tmp) / "empty.db"),
                packs_dir=str(REPO / "packs"),
            )
            self.mod.register(ctx)
            handler = next(t["handler"] for t in ctx.tools if t["name"] == "spray_record")
            result = json.loads(
                handler(
                    {
                        "applied": "2026-10-14",
                        "block": "north",
                        "product": "copper",
                        "rate": 1,
                        "rate_unit": "kg/ha",
                    }
                )
            )
            self.assertTrue(result["success"], result)
            self.assertIn("the file", result["spray_book_source"])
            self.assertTrue(
                any("not your records" in w for w in result["warnings"]), result["warnings"]
            )

    def test_a_corrected_spray_book_file_is_seen_without_a_restart(self) -> None:
        """The book was cached for the life of the process, with nothing to invalidate it.

        A withholding period corrected in the file was invisible until the gateway restarted, and
        the stale figure is what the record printed as an earliest safe harvest date
        (the internal security audit A19-PLUG-11).
        """
        with open(BOOK, encoding="utf-8") as handle:
            payload = json.load(handle)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "spraybook.json"
            path.write_text(json.dumps(payload))
            self.ctx.settings["catalogue_path"] = str(path)

            before = self.call("spray_inputs", {})
            by_name = {row["name"]: row for row in before["inputs"]}
            self.assertEqual(by_name["Copper oxychloride 500"]["withholding_days"], 1)

            for entry in payload["inputs"]:
                if entry["name"] == "Copper oxychloride 500":
                    entry["withholding_days"] = 21
            path.write_text(json.dumps(payload))
            os.utime(path, (0, 0))  # a different mtime, as a real edit would have

            after = self.call("spray_inputs", {})
            by_name = {row["name"]: row for row in after["inputs"]}
            self.assertEqual(by_name["Copper oxychloride 500"]["withholding_days"], 21)

    def test_a_corrected_input_record_is_seen_without_a_restart(self) -> None:
        """The book built from the records is invalidated too — the store's mtime is the stamp.

        The records are the source the app writes, so this is the correction the operator actually
        makes: a withholding period read off the label after the application was recorded
        (the internal security audit A19-PLUG-11).
        """
        from pantler_core import RecordBook

        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "records.db"
            writer = RecordBook(store, REPO / "packs")
            writer.save("block", {"name": "North block", "area_ha": 2})
            writer.save("input", {"name": "Copper", "unit": "kg", "withholding_days": 7})
            writer.close()

            ctx = PerKeyCtx(store_path=str(store), packs_dir=str(REPO / "packs"))
            self.mod.register(ctx)
            handler = next(t["handler"] for t in ctx.tools if t["name"] == "spray_record")
            args = {
                "applied": "2026-10-14",
                "block": "north",
                "product": "copper",
                "rate": 1,
                "rate_unit": "kg/ha",
            }
            first = json.loads(handler(args))
            self.assertEqual(first["record"]["withholding_days"], 7)

            editor = RecordBook(store, REPO / "packs")
            editor.update(
                "input", "INP-0001", {"name": "Copper", "unit": "kg", "withholding_days": 21}
            )
            editor.close()
            os.utime(store, (0, 0))

            second = json.loads(handler(args))
            self.assertEqual(second["record"]["withholding_days"], 21)
            self.assertEqual(second["record"]["earliest_safe_date"], "2026-11-04")

    def test_a_switched_off_capability_refuses_in_one_sentence(self) -> None:
        ctx = PerKeyCtx(catalogue_path=BOOK, capability_enabled=False)
        self.mod.register(ctx)
        for name in ("spray_record", "spray_inputs"):
            with self.subTest(tool=name):
                answer = json.loads(
                    next(t["handler"] for t in ctx.tools if t["name"] == name)({})
                )
                self.assertFalse(answer["success"])
                self.assertIn("switched off in Capabilities", answer["error"])

    def test_the_switch_is_read_per_call(self) -> None:
        self.ctx.settings["capability_enabled"] = False
        result = self.call("spray_inputs", {})
        self.assertIn("switched off", result["error"])
        self.ctx.settings["capability_enabled"] = True
        self.assertTrue(self.call("spray_inputs", {})["success"])

    def test_a_missing_spray_book_says_where_one_goes(self) -> None:
        ctx = PerKeyCtx(catalogue_path=str(HERE / "fixtures" / "no-such-book.json"))
        self.mod.register(ctx)
        result = json.loads(ctx.tools[0]["handler"]({}))
        self.assertFalse(result["success"])
        self.assertIn("spray book", result["error"])

    def test_no_configured_path_falls_back_to_the_engine_home(self) -> None:
        # Saved and restored: the dev instructions export HERMES_HOME, and a test that popped it
        # left every later test running against a different home
        # (the internal audit PLUG-16).
        previous = os.environ.get("HERMES_HOME")
        os.environ["HERMES_HOME"] = str(HERE / "fixtures")
        try:
            ctx = PerKeyCtx()
            self.mod.register(ctx)
            result = json.loads(next(t["handler"] for t in ctx.tools if t["name"] == "spray_inputs")({}))
            # fixtures/spraybook.json exists, so the fallback finds it.
            self.assertTrue(result["success"], result)
        finally:
            if previous is None:
                os.environ.pop("HERMES_HOME", None)
            else:
                os.environ["HERMES_HOME"] = previous


if __name__ == "__main__":
    unittest.main()
