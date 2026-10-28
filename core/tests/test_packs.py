"""Tests for the pack contract.

The contract is the load-bearing part of the architecture in the front-end design §3: if
it cannot express a domain without naming it, the shell stops being a host. Most of these
tests are about *refusing* a bad manifest clearly, because a pack that loads wrongly fails
later as a mystery on a screen.

Run:  PYTHONPATH=core/src python -m unittest discover -s core/tests
"""

from __future__ import annotations

import tempfile
import tomllib
import unittest
from pathlib import Path

from pantler_core import (
    FIELD_KINDS,
    Field,
    PackError,
    PackRegistry,
    RecordType,
    load_pack,
    load_packs,
    pack_from_dict,
    render_pack_toml,
    validate_record,
)

MONEY_PACK = {
    "id": "money",
    "name": "Money",
    "version": "0.1.0",
    "records": [
        {
            "type": "invoice",
            "label": "Invoice",
            "plural": "Invoices",
            "id_prefix": "INV",
            "id_sequence": True,
            "fields": [
                {"name": "number", "label": "Number", "required": True},
                {"name": "customer", "label": "Customer", "required": True},
                {"name": "total", "label": "Total", "kind": "money"},
                {"name": "status", "label": "Status", "kind": "enum", "options": ["draft", "sent"]},
            ],
        }
    ],
    "screens": [
        {
            "id": "invoices",
            "title": "Invoices",
            "kind": "list",
            "record_type": "invoice",
            "columns": ["number", "customer", "total", "status"],
        }
    ],
}


class TestLoading(unittest.TestCase):
    def test_a_complete_pack_loads(self) -> None:
        pack = pack_from_dict(MONEY_PACK)
        self.assertEqual(pack.id, "money")
        self.assertEqual(pack.name, "Money")
        self.assertEqual([r.type for r in pack.records], ["invoice"])
        self.assertEqual([s.id for s in pack.screens], ["invoices"])
        self.assertTrue(pack.records[0].id_sequence)
        self.assertEqual(pack.records[0].id_prefix, "INV")

    def test_to_dict_is_what_the_shell_renders_from(self) -> None:
        payload = pack_from_dict(MONEY_PACK).to_dict()
        self.assertEqual(payload["records"][0]["fields"][0]["name"], "number")
        # The shell needs a title to show in a list without being told which field to use.
        self.assertEqual(payload["records"][0]["title_field"], ["number"])

    def test_title_field_can_be_chosen(self) -> None:
        spec = dict(MONEY_PACK)
        spec["records"] = [dict(MONEY_PACK["records"][0], title_field="customer")]
        self.assertEqual(pack_from_dict(spec).records[0].title_field, ("customer",))

    def test_a_title_can_be_more_than_one_field(self) -> None:
        """Two applications in different blocks on the same day must not read identically.

        A single `title_field` cannot express that, so the contract takes a list and the shell
        joins it (the internal audit PACK-2).
        """
        spec = dict(MONEY_PACK)
        # The fixture's own fields, so the screens still resolve; only the title changes.
        spec["records"] = [
            dict(MONEY_PACK["records"][0], title_field=["customer", "number"])
        ]
        self.assertEqual(pack_from_dict(spec).records[0].title_field, ("customer", "number"))

    def test_every_declared_field_kind_is_accepted(self) -> None:
        for kind in FIELD_KINDS:
            extra = {}
            if kind == "enum":
                extra["options"] = ["a"]
            if kind == "reference":
                extra["reference"] = "customer"
            spec = {
                "id": "demo",
                "records": [{"type": "thing", "fields": [dict({"name": "f", "kind": kind}, **extra)]}],
            }
            with self.subTest(kind=kind):
                self.assertEqual(pack_from_dict(spec).records[0].fields[0].kind, kind)


class TestRefusingBadManifests(unittest.TestCase):
    def test_a_pack_needs_an_id(self) -> None:
        with self.assertRaises(PackError):
            pack_from_dict({"name": "Nameless"})

    def test_a_record_needs_a_type(self) -> None:
        with self.assertRaises(PackError):
            pack_from_dict({"id": "x", "records": [{"fields": [{"name": "f"}]}]})

    def test_a_record_needs_fields(self) -> None:
        with self.assertRaises(PackError):
            pack_from_dict({"id": "x", "records": [{"type": "thing"}]})

    def test_an_unknown_field_kind_is_refused(self) -> None:
        with self.assertRaises(PackError) as caught:
            pack_from_dict({"id": "x", "records": [{"type": "t", "fields": [{"name": "f", "kind": "colour"}]}]})
        self.assertIn("colour", str(caught.exception))

    def test_an_enum_without_options_is_refused(self) -> None:
        with self.assertRaises(PackError):
            pack_from_dict({"id": "x", "records": [{"type": "t", "fields": [{"name": "f", "kind": "enum"}]}]})

    def test_a_reference_without_a_target_is_refused(self) -> None:
        with self.assertRaises(PackError):
            pack_from_dict({"id": "x", "records": [{"type": "t", "fields": [{"name": "f", "kind": "reference"}]}]})

    def test_a_title_field_that_is_not_a_field_is_refused(self) -> None:
        for title in ("nope", ["f", "nope"], 7):
            with self.subTest(title=title):
                with self.assertRaises(PackError):
                    pack_from_dict(
                        {
                            "id": "x",
                            "records": [{"type": "t", "title_field": title, "fields": [{"name": "f"}]}],
                        }
                    )

    def test_a_screen_may_only_reference_types_its_own_pack_declares(self) -> None:
        # Otherwise a pack could render a screen over another pack's records, and the
        # ownership rule that makes the store unambiguous would be decorative.
        with self.assertRaises(PackError) as caught:
            pack_from_dict(
                {
                    "id": "x",
                    "records": [{"type": "t", "fields": [{"name": "f"}]}],
                    "screens": [{"id": "s", "record_type": "someone_elses"}],
                }
            )
        self.assertIn("someone_elses", str(caught.exception))

    def test_a_screen_column_that_is_not_a_field_is_refused(self) -> None:
        # A typo'd column renders an empty cell for ever; the manifest is the only place that
        # could have caught it (the internal audit K3).
        with self.assertRaises(PackError) as caught:
            pack_from_dict(
                {
                    "id": "x",
                    "records": [{"type": "t", "fields": [{"name": "f"}]}],
                    "screens": [{"id": "s", "record_type": "t", "columns": ["f", "typo"]}],
                }
            )
        self.assertIn("typo", str(caught.exception))

    def test_a_duplicated_record_type_is_refused_with_its_own_name(self) -> None:
        # The registry catches this too, but it reports the pack as claiming a type from
        # itself, which sends the reader looking for a second pack
        # (the internal audit K4).
        with self.assertRaises(PackError) as caught:
            pack_from_dict(
                {
                    "id": "x",
                    "records": [
                        {"type": "t", "fields": [{"name": "f"}]},
                        {"type": "t", "fields": [{"name": "g"}]},
                    ],
                }
            )
        message = str(caught.exception)
        self.assertIn("'t'", message)
        self.assertIn("more than once", message)
        self.assertNotIn("both", message)


class TestRegistry(unittest.TestCase):
    def test_two_packs_may_not_claim_the_same_record_type(self) -> None:
        registry = PackRegistry()
        registry.add(pack_from_dict(MONEY_PACK))
        with self.assertRaises(PackError):
            registry.add(pack_from_dict({"id": "other", "records": [{"type": "invoice", "fields": [{"name": "f"}]}]}))

    def test_registry_reports_ownership(self) -> None:
        registry = PackRegistry([pack_from_dict(MONEY_PACK)])
        self.assertEqual(registry.owner("invoice"), "money")
        self.assertIsNotNone(registry.record_type("invoice"))
        self.assertIsNone(registry.record_type("spray"))

    def test_load_packs_reads_a_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "money").mkdir()
            (root / "money" / "pack.toml").write_text(
                """
id = "money"
name = "Money"

[[records]]
type = "invoice"
label = "Invoice"

  [[records.fields]]
  name = "number"
  required = true
""",
                encoding="utf-8",
            )
            registry = load_packs(root)
            self.assertEqual([p.id for p in registry.packs], ["money"])
            self.assertEqual(registry.record_type("invoice").label, "Invoice")

    def test_a_missing_directory_is_an_empty_registry(self) -> None:
        self.assertEqual(load_packs("/nonexistent/packs").packs, [])

    def test_load_pack_reports_a_missing_manifest(self) -> None:
        with self.assertRaises(PackError):
            load_pack("/nonexistent/pack.toml")



CLEANING_PACK = {
    "id": "custom-cleaning_log",
    "name": "Kitchen cleaning log",
    "version": "1.0.0",
    "records": [
        {
            "type": "cleaning_log",
            "label": "Kitchen cleaning log",
            "plural": "Kitchen cleaning logs",
            "title_field": "date",
            "id_prefix": "CLN",
            "id_sequence": True,
            "fields": [
                {"name": "date", "label": "Date", "kind": "date", "required": True},
                {"name": "task", "label": "Task", "required": True},
                {"name": "notes", "label": "Notes", "kind": "longtext"},
            ],
        }
    ],
    "screens": [
        {
            "id": "cleaning_log",
            "title": "Kitchen cleaning logs",
            "record_type": "cleaning_log",
            "columns": ["date", "task"],
        }
    ],
}


class TestCustomPacks(unittest.TestCase):
    def _write(self, root: Path, name: str, pack: dict) -> None:
        (root / name).mkdir(parents=True)
        (root / name / "pack.toml").write_text(
            render_pack_toml(pack_from_dict(pack)), encoding="utf-8"
        )

    def test_a_custom_directory_loads_after_the_shipped_packs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shipped, custom = root / "packs", root / "custom-packs"
            self._write(shipped, "money", MONEY_PACK)
            self._write(custom, "cleaning_log", CLEANING_PACK)
            registry = load_packs(shipped, custom_dir=custom)
            self.assertEqual([pack.id for pack in registry.packs],
                             ["money", "custom-cleaning_log"])
            self.assertFalse(registry.pack("money").custom)
            self.assertTrue(registry.pack("custom-cleaning_log").custom)
            self.assertEqual(registry.owner("cleaning_log"), "custom-cleaning_log")

    def test_a_custom_pack_may_not_shadow_a_shipped_type(self) -> None:
        shadow = {
            **CLEANING_PACK,
            "records": [{**CLEANING_PACK["records"][0], "type": "invoice"}],
            "screens": [
                {
                    **CLEANING_PACK["screens"][0],
                    "record_type": "invoice",
                    "columns": ["date"],
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write(root / "packs", "money", MONEY_PACK)
            self._write(root / "custom-packs", "shadow", shadow)
            with self.assertRaises(PackError):
                load_packs(root / "packs", custom_dir=root / "custom-packs")

    def test_render_pack_toml_round_trips_the_declaration(self) -> None:
        pack = pack_from_dict(CLEANING_PACK)
        text = render_pack_toml(pack)
        again = pack_from_dict(tomllib.loads(text))
        self.assertEqual(again.records[0].type, "cleaning_log")
        self.assertEqual([field.name for field in again.records[0].fields],
                         ["date", "task", "notes"])
        self.assertEqual(again.screens[0].columns, ("date", "task"))
        self.assertEqual(again.records[0].id_prefix, "CLN")
        self.assertTrue(again.records[0].id_sequence)


class TestValidation(unittest.TestCase):
    def setUp(self) -> None:
        self.invoice = pack_from_dict(MONEY_PACK).records[0]

    def test_a_good_record_passes(self) -> None:
        self.assertEqual(
            validate_record(self.invoice, {"number": "INV-0001", "customer": "Bellview CSA", "status": "draft"}),
            [],
        )

    def test_every_problem_is_reported_at_once(self) -> None:
        # A form that reveals one error per submission is a form nobody finishes.
        problems = validate_record(self.invoice, {"status": "nonsense", "surprise": 1})
        self.assertEqual(len(problems), 4)
        self.assertTrue(any("Number is required" in p for p in problems))
        self.assertTrue(any("Customer is required" in p for p in problems))
        self.assertTrue(any("surprise" in p for p in problems))
        self.assertTrue(any("draft, sent" in p for p in problems))

    def test_blank_strings_count_as_missing(self) -> None:
        problems = validate_record(self.invoice, {"number": "   ", "customer": "x"})
        self.assertTrue(any("Number is required" in p for p in problems))

    def test_money_must_be_a_whole_number_of_cents(self) -> None:
        # Not "a number": money is integer cents everywhere else in this package, and a float
        # that got in would be stored as one and then divide to nothing in `format_money`
        # (the internal audit K1).
        problems = validate_record(self.invoice, {"number": "n", "customer": "c", "total": "lots"})
        self.assertTrue(any("Total must be a whole number of cents" in p for p in problems))

    def test_a_float_is_not_money(self) -> None:
        for wrong in (12.5, 12.0):
            with self.subTest(wrong=wrong):
                problems = validate_record(
                    self.invoice, {"number": "n", "customer": "c", "total": wrong}
                )
                self.assertTrue(any("whole number of cents" in p for p in problems), problems)

    def test_an_integer_is_money(self) -> None:
        self.assertEqual(
            validate_record(self.invoice, {"number": "n", "customer": "c", "total": 1250}), []
        )

    def test_a_boolean_is_not_a_number(self) -> None:
        # `True` is an int in Python, and would sail through a naive isinstance check.
        problems = validate_record(self.invoice, {"number": "n", "customer": "c", "total": True})
        self.assertTrue(any("whole number of cents" in p for p in problems))

    def test_a_date_is_the_one_spelling_a_form_writes(self) -> None:
        dated = RecordType(
            type="certificate",
            label="Certificate",
            plural="Certificates",
            fields=(Field(name="expires", label="Expires", kind="date"),),
        )
        self.assertEqual(validate_record(dated, {"expires": "2026-10-16"}), [])
        for wrong in ("16/10/2026", "2026-1-1", "next tuesday", "20261016"):
            with self.subTest(wrong=wrong):
                problems = validate_record(dated, {"expires": wrong})
                self.assertTrue(any("YYYY-MM-DD" in p for p in problems), problems)
        self.assertTrue(
            any("not a real date" in p for p in validate_record(dated, {"expires": "2026-02-30"}))
        )

    def test_non_object_data_is_refused(self) -> None:
        self.assertEqual(validate_record(self.invoice, ["not", "a", "dict"]), ["record data must be an object"])


if __name__ == "__main__":
    unittest.main()


class PackShapeTest(unittest.TestCase):
    """A manifest that is valid TOML of the wrong shape is a refusal, not a crash.

    Every reader below calls `.get` on the entries, so `records = "spray"` or a mistyped
    `screens` used to raise `AttributeError` from inside the parser — which the BFF does not
    catch, so a pack being edited took every request down instead of leaving the previous
    registry serving (the internal security audit A19-KERN-3).
    """

    def test_a_records_value_that_is_not_a_list_is_refused(self) -> None:
        for value in ("spray", 42, {"a": 1}):
            with self.subTest(value=value):
                with self.assertRaises(PackError) as caught:
                    pack_from_dict({"id": "x", "records": value})
                self.assertIn("records", str(caught.exception))

    def test_an_entry_that_is_not_a_table_is_refused(self) -> None:
        for records in ([42], ["application"], [[1]]):
            with self.subTest(records=records):
                with self.assertRaises(PackError) as caught:
                    pack_from_dict({"id": "x", "records": records})
                self.assertIn("records[0]", str(caught.exception))

    def test_fields_screens_and_columns_of_the_wrong_shape_are_refused(self) -> None:
        cases = (
            {"records": [{"type": "t", "fields": "ab"}]},
            {"records": [{"type": "t", "fields": [42]}]},
            {"records": [{"type": "t", "fields": [{"name": "a"}], "id_sequence": "maybe"}]},
            {"records": [{"type": "t", "fields": [{"name": "a", "kind": "enum", "options": 5}]}]},
            {
                "records": [{"type": "t", "fields": [{"name": "a"}]}],
                "screens": [{"id": "s", "record_type": "t", "columns": "a"}],
            },
        )
        for payload in cases:
            with self.subTest(payload=payload):
                with self.assertRaises(PackError):
                    pack_from_dict(payload)

    def test_an_options_string_is_refused_rather_than_read_per_character(self) -> None:
        # `options = "dry,wet"` used to become ('d','r','y',',','w','e','t'), so the enum
        # accepted "d" and rejected "dry" (the internal security audit A19-KERN-4).
        with self.assertRaises(PackError) as caught:
            pack_from_dict(
                {"id": "x", "records": [{"type": "t", "fields": [
                    {"name": "a", "kind": "enum", "options": "dry,wet"}]}]}
            )
        self.assertIn("list of strings", str(caught.exception))
        pack = pack_from_dict(
            {"id": "x", "records": [{"type": "t", "fields": [
                {"name": "a", "kind": "enum", "options": ["dry", "wet"]}]}]}
        )
        field = pack.records[0].fields[0]
        self.assertEqual(field.options, ("dry", "wet"))

    def test_a_string_false_does_not_switch_on_sequence_ids(self) -> None:
        pack = pack_from_dict(
            {"id": "x", "records": [{"type": "t", "fields": [{"name": "a"}], "id_sequence": "false"}]}
        )
        self.assertFalse(pack.records[0].id_sequence)
        pack = pack_from_dict(
            {"id": "x", "records": [{"type": "t", "fields": [{"name": "a"}], "id_sequence": "yes"}]}
        )
        self.assertTrue(pack.records[0].id_sequence)

    def test_a_manifest_nested_too_deeply_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "pack.toml"
            manifest.write_text("id = 'x'\ndeep = " + "[" * 2000 + "]" * 2000 + "\n")
            with self.assertRaises(PackError):
                load_pack(manifest)
