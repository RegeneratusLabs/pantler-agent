"""The pantler plugin, loaded the way Hermes loads it, plus its capability switch.

Two things are being protected here.

1. **The plugin's own contract**: `register(ctx)` asks for exactly the tools the manifest
   declares, under the toolset the pack owns, with handlers that answer a string.
2. **The switch is real.** The engine's plugin list is restart-grade — a tool registered before
   the switch stays callable until the process restarts — so the handler reads
   `capability_enabled` on every call and refuses in a sentence instead of doing the work. A
   switch that only hides a tool is a lie the first time a conversation outlives it.

Run with the standard library, from this directory or through `scripts/test.sh`:

    python3 -m unittest discover -s tests -t tests
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
PRICEBOOK = os.path.join(HERE, "fixtures-pricebook.json")
REPO = os.path.dirname(os.path.dirname(PLUGIN))
sys.path.insert(0, os.path.join(REPO, "core", "src"))


class PerKeyCtx:
    """The engine's own reader: `ctx.get_config(key, default)`, live on every call."""

    def __init__(self, **settings):
        self.settings = settings
        self.tools: list = []
        self.skills: list = []

    def register_tool(self, **kw):
        self.tools.append(kw)

    def register_skill(self, name, path):
        self.skills.append((name, str(path)))

    def get_config(self, key=None, default=None):
        if key is None:
            return dict(self.settings)  # an older whole-block reader
        return self.settings.get(key, default)


class BlockCtx(PerKeyCtx):
    """An older surface that hands over the whole block and takes no key."""

    def get_config(self):  # type: ignore[override]
        return dict(self.settings)


class HookCtx(PerKeyCtx):
    """The current engine surface: a plugin can register a pre_tool_call hook."""

    def __init__(self, **settings):
        super().__init__(**settings)
        self.hooks: dict[str, list] = {}

    def register_hook(self, name, callback):
        self.hooks.setdefault(name, []).append(callback)


def load_plugin():
    """A genuinely fresh plugin, as a process that has just started would have.

    Purging `pantler_plugin.*` matters: `from . import tools` resolves through `sys.modules`,
    so without this every "fresh" load would share one `tools` module and its cached ledger —
    and a test that switched the price book would silently keep reading the previous one.
    """
    for name in [n for n in sys.modules if n == "pantler_plugin" or n.startswith("pantler_plugin.")]:
        del sys.modules[name]
    init = os.path.join(PLUGIN, "__init__.py")
    spec = importlib.util.spec_from_file_location(
        "pantler_plugin", init, submodule_search_locations=[PLUGIN]
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["pantler_plugin"] = mod
    spec.loader.exec_module(mod)
    return mod


class PantlerPluginTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = load_plugin()
        self.ctx = PerKeyCtx(pricebook_path=PRICEBOOK)
        self.mod.register(self.ctx)
        self.tools = self.mod.tools

    def call(self, name: str, args: dict) -> str:
        handler = next(tool["handler"] for tool in self.ctx.tools if tool["name"] == name)
        return handler(args)

    # -- registration -------------------------------------------------------------------

    def test_register_asks_for_the_declared_tools_under_our_toolset(self) -> None:
        self.assertEqual(
            sorted(tool["name"] for tool in self.ctx.tools), ["invoice_create", "invoice_show"]
        )
        # `invoicing`, not `records`: the toolset name is the capability the operator toggles, and
        # the generic record tools (plugins/records/) hold that name themselves.
        self.assertEqual({tool["toolset"] for tool in self.ctx.tools}, {"invoicing"})

    def test_register_installs_the_profile_scope_hook(self) -> None:
        ctx = HookCtx(pricebook_path=PRICEBOOK)
        self.mod.register(ctx)
        self.assertEqual(list(ctx.hooks), ["pre_tool_call"])
        self.assertEqual(ctx.hooks["pre_tool_call"], [self.mod.scope.pre_tool_call])

    def test_handlers_answer_with_prose_the_model_can_read(self) -> None:
        answer = self.call("invoice_show", {"number": "INV-0001"})
        self.assertIsInstance(answer, str)
        self.assertIn("INV-0001", answer)

    # -- the capability switch ----------------------------------------------------------

    def test_a_switched_off_capability_refuses_in_one_sentence(self) -> None:
        ctx = PerKeyCtx(pricebook_path=PRICEBOOK, capability_enabled=False)
        self.mod.register(ctx)
        for name in ("invoice_create", "invoice_show"):
            answer = self.call(name, {"customer": "Bellview", "lines": [], "number": "INV-1"})
            self.assertIn("switched off in Capabilities", answer)
            # The refusal replaces the work, not the error message the work would have given.
            self.assertNotIn("price book", answer)

    def test_the_switch_is_read_per_call_not_at_registration(self) -> None:
        ctx = PerKeyCtx(pricebook_path=PRICEBOOK, capability_enabled=True)
        self.mod.register(ctx)
        self.assertNotIn("switched off", self.call("invoice_show", {"number": "X"}))
        ctx.settings["capability_enabled"] = False
        self.assertIn("switched off", self.call("invoice_show", {"number": "X"}))
        ctx.settings["capability_enabled"] = True
        self.assertNotIn("switched off", self.call("invoice_show", {"number": "X"}))

    def test_the_flag_accepts_the_spellings_a_hand_edited_file_may_carry(self) -> None:
        for value in (False, "false", "off", "no"):
            ctx = PerKeyCtx(pricebook_path=PRICEBOOK, capability_enabled=value)
            self.mod.register(ctx)
            self.assertIn("switched off", self.call("invoice_show", {"number": "X"}), value)
        for value in (True, "true", None):
            ctx = PerKeyCtx(pricebook_path=PRICEBOOK, capability_enabled=value)
            self.mod.register(ctx)
            self.assertNotIn("switched off", self.call("invoice_show", {"number": "X"}), value)

    def test_an_absent_flag_is_on(self) -> None:
        self.assertNotIn("switched off", self.call("invoice_show", {"number": "X"}))

    def test_an_older_block_reader_still_works(self) -> None:
        ctx = BlockCtx(pricebook_path=PRICEBOOK, capability_enabled=False)
        self.mod.register(ctx)
        self.assertIn("switched off", self.call("invoice_show", {"number": "X"}))

    # -- configuration ------------------------------------------------------------------

    def test_the_price_book_path_is_read_the_way_the_engine_exposes_it(self) -> None:
        """`ctx.get_config(key, default)` — one key, not the whole block.

        This was silently dead: the reader called `get_config()` with no key, the engine raised,
        and the plugin fell back to `HERMES_HOME/pricebook.json`. It worked by accident. The
        configured path is now the one that is used, and the error says so.
        """
        configured = os.path.join(HERE, "configured-but-missing.json")
        ctx = PerKeyCtx(pricebook_path=configured)
        self.mod.register(ctx)
        answer = self.call(
            "invoice_create",
            {"customer": "Bellview", "lines": [{"item": "kale", "quantity": "2"}]},
        )
        self.assertIn("configured-but-missing.json", answer)

    # -- numbering, and the cache --------------------------------------------------------

    def test_the_invoice_number_comes_from_the_store_when_there_is_one(self) -> None:
        """A counter in memory hands the same number to a different invoice after a restart.

        The number is reserved in the record store the app already keeps, and the draft is saved
        in the money pack beside it (the internal audit PLUG-1, PLUG-14, K5).
        """
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp) / "profiles" / "pantler"
            profile.mkdir(parents=True)
            (profile / "config.yaml").write_text("model:\n  provider: test\n")
            (profile / "pricebook.json").write_text(Path(PRICEBOOK).read_text())
            store_path = profile / "records.db"

            ctx = PerKeyCtx(store_path=str(store_path), packs_dir=str(Path(REPO) / "packs"))
            mod = load_plugin()
            mod.register(ctx)
            # The plugin resolves the profile from its own location, so point the price book at
            # the copy above rather than the repository's.
            ctx.settings["pricebook_path"] = str(profile / "pricebook.json")
            first = mod.tools._handle_invoice_create(
                {"customer": "Bellview", "lines": [{"item": "Green Beans", "quantity": "2"}]}
            )
            second = mod.tools._handle_invoice_create(
                {"customer": "Bellview", "lines": [{"item": "Green Beans", "quantity": "3"}]}
            )
            self.assertIn("INV-0001", first)
            self.assertIn("INV-0002", second)
            self.assertIn("Saved as INV-0001 in the money pack", first)

            # A restart: a fresh plugin, the same store — the next number continues.
            mod2 = load_plugin()
            ctx2 = PerKeyCtx(
                store_path=str(store_path),
                pricebook_path=str(profile / "pricebook.json"),
                packs_dir=str(Path(REPO) / "packs"),
            )
            mod2.register(ctx2)
            third = mod2.tools._handle_invoice_create(
                {"customer": "Bellview", "lines": [{"item": "Green Beans", "quantity": "1"}]}
            )
            self.assertIn("INV-0003", third)

    def test_a_draft_is_saved_and_read_back_with_its_lines(self) -> None:
        """The draft used to live in the conversation's memory and nowhere else.

        The number was reserved, so it could not be reissued — but the invoice the number
        belonged to was gone when the process was, which meant an operator could not see or
        correct what they had asked for (the internal audit PLUG-1, PLUG-14).
        """
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp) / "profiles" / "pantler"
            profile.mkdir(parents=True)
            (profile / "config.yaml").write_text("model:\n  provider: test\n")
            (profile / "pricebook.json").write_text(Path(PRICEBOOK).read_text())
            (profile / "packs").symlink_to(Path(REPO) / "packs")

            mod = load_plugin()
            ctx = PerKeyCtx(
                store_path=str(profile / "records.db"),
                pricebook_path=str(profile / "pricebook.json"),
                packs_dir=str(profile / "packs"),
            )
            mod.register(ctx)

            created = json.loads(
                mod.tools._handle_invoice_create(
                    {
                        "customer": "Bellview",
                        "lines": [
                            {"item": "Green Beans", "quantity": "2", "unit": "kilos"},
                            {"item": "Eggs", "quantity": "4", "unit": "dozen"},
                        ],
                    }
                )
            )
            self.assertTrue(created["saved"], created)
            self.assertIn("Saved as INV-0001 in the money pack", created["message"])

            # A *fresh* plugin, the same store: the read path is the store, not the memory that
            # wrote it.
            mod2 = load_plugin()
            ctx2 = PerKeyCtx(
                store_path=str(profile / "records.db"),
                pricebook_path=str(profile / "pricebook.json"),
                packs_dir=str(profile / "packs"),
            )
            mod2.register(ctx2)
            shown = json.loads(mod2.tools._handle_invoice_show({"number": "INV-0001"}))

            self.assertTrue(shown["success"], shown)
            self.assertTrue(shown["saved"])
            # The price book's own name for the customer, not the word that was typed.
            self.assertEqual(shown["invoice"]["customer"], "Bellview CSA")
            self.assertEqual(len(shown["invoice"]["lines"]), 2)
            self.assertEqual(shown["invoice"]["lines"][0]["description"], "Green Beans")
            self.assertEqual(shown["invoice"]["lines"][0]["amount"], "$24.00")
            # 2 x $12 + 4 x $9 = $60, plus 10% GST = $66.00.
            self.assertEqual(shown["invoice"]["total_cents"], 6600)
            self.assertIn("INV-0001 for Bellview CSA", shown["message"])

    def test_without_the_money_pack_the_draft_is_shown_and_not_claimed_saved(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp) / "profiles" / "pantler"
            profile.mkdir(parents=True)
            (profile / "config.yaml").write_text("model:\n  provider: test\n")
            (profile / "pricebook.json").write_text(Path(PRICEBOOK).read_text())

            mod = load_plugin()
            ctx = PerKeyCtx(
                store_path=str(profile / "records.db"),
                pricebook_path=str(profile / "pricebook.json"),
                packs_dir=str(Path(tmp) / "no-such-packs"),
            )
            mod.register(ctx)

            answer = json.loads(
                mod.tools._handle_invoice_create(
                    {"customer": "Bellview", "lines": [{"item": "Green Beans", "quantity": "1"}]}
                )
            )
            self.assertTrue(answer["success"], answer)
            self.assertFalse(answer["saved"])
            self.assertIn("the money pack is not loaded", answer["message"])

    def test_a_changed_price_book_is_read_without_a_restart(self) -> None:
        # The ledger used to be cached on nothing at all, so an edited price or a corrected tax
        # rate was invisible until the gateway restarted (the internal audit PLUG-14).
        import json
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            book = Path(tmp) / "pricebook.json"
            book.write_text(Path(PRICEBOOK).read_text())
            self.ctx.settings["pricebook_path"] = str(book)
            before = self.call(
                "invoice_create",
                {"customer": "Bellview", "lines": [{"item": "Green Beans", "quantity": "1"}]},
            )

            payload = json.loads(book.read_text())
            payload["items"][0]["unit_price_cents"] = 9999
            book.write_text(json.dumps(payload))
            os.utime(book, (0, 0))  # a different mtime, as a real edit would have

            after = self.call(
                "invoice_create",
                {"customer": "Bellview", "lines": [{"item": "Green Beans", "quantity": "1"}]},
            )
            self.assertNotEqual(before, after)
            self.assertIn("99.99", after)

    def test_a_forged_invoice_number_cannot_be_shown_as_the_genuine_invoice(self) -> None:
        """The invoice is resolved by envelope id, and its `number` has to agree with that id.

        A record written by anything that can save one could claim INV-0001's number while sitting
        at INV-0002, and `invoice_show("INV-0001")` used to search that caller-writable field and
        show the forgery in the genuine invoice's place
        (the internal security audit A19-PLUG-1).
        """
        import tempfile
        from pathlib import Path

        from pantler_core import RecordBook

        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp) / "profiles" / "pantler"
            profile.mkdir(parents=True)
            (profile / "config.yaml").write_text("model:\n  provider: test\n")
            (profile / "pricebook.json").write_text(Path(PRICEBOOK).read_text())
            store = profile / "records.db"

            mod = load_plugin()
            ctx = PerKeyCtx(
                store_path=str(store),
                pricebook_path=str(profile / "pricebook.json"),
                packs_dir=os.path.join(REPO, "packs"),
            )
            mod.register(ctx)
            created = json.loads(
                mod.tools._handle_invoice_create(
                    {"customer": "Bellview", "lines": [{"item": "Green Beans", "quantity": "2"}]}
                )
            )
            self.assertEqual(created["invoice"]["number"], "INV-0001")

            # The forgery: a second invoice record claiming the first one's number, written the
            # way any other record writer would write one.
            forger = RecordBook(store, os.path.join(REPO, "packs"))
            forger.save(
                "invoice",
                {
                    "number": "INV-0001",
                    "customer": "Mallory Holdings (forged)",
                    "status": "paid",
                    "total_cents": 999999,
                },
            )
            forger.close()

            shown = json.loads(mod.tools._handle_invoice_show({"number": "INV-0001"}))
            self.assertTrue(shown["success"], shown)
            self.assertEqual(shown["invoice"]["customer"], "Bellview CSA")
            self.assertNotIn("Mallory", json.dumps(shown))

            # The forged record cannot be shown under its own id either: the number it carries
            # disagrees with the id it is stored at.
            other = json.loads(mod.tools._handle_invoice_show({"number": "INV-0002"}))
            self.assertFalse(other["success"], other)
            self.assertNotIn("Mallory", json.dumps(other))

    def test_a_hostile_quantity_is_refused_before_anything_is_written(self) -> None:
        """`1e400` was converted *after* the header was stored, and the invoice number was burnt.

        `"1e400"`, a JSON `1e400` and `"1/0"` are quantities the ledger must never see: the bound
        is in front of it, so no number is reserved and no orphan record is left
        (the internal security audit A19-PLUG-5).
        """
        import tempfile
        from pathlib import Path

        from pantler_core import RecordBook

        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp) / "profiles" / "pantler"
            profile.mkdir(parents=True)
            (profile / "config.yaml").write_text("model:\n  provider: test\n")
            (profile / "pricebook.json").write_text(Path(PRICEBOOK).read_text())
            store = profile / "records.db"

            mod = load_plugin()
            ctx = PerKeyCtx(
                store_path=str(store),
                pricebook_path=str(profile / "pricebook.json"),
                packs_dir=os.path.join(REPO, "packs"),
            )
            mod.register(ctx)

            for quantity in ("1e400", "1/0", json.loads("1e400")):
                with self.subTest(quantity=quantity):
                    answer = mod.tools._handle_invoice_create(
                        {
                            "customer": "Bellview",
                            "lines": [{"item": "Green Beans", "quantity": quantity}],
                        }
                    )
                    self.assertNotIn("Traceback", answer)
                    self.assertNotIn("INV-", answer, "a refused line reserved a number")
                    self.assertIn("How many", answer)

            reader = RecordBook(store, os.path.join(REPO, "packs"))
            try:
                self.assertEqual(reader.find("invoice"), [], "a refused line left a record")
            finally:
                reader.close()

            # Nothing was consumed: the next good call is still INV-0001 and it is saved.
            ok = json.loads(
                mod.tools._handle_invoice_create(
                    {"customer": "Bellview", "lines": [{"item": "Green Beans", "quantity": "2"}]}
                )
            )
            self.assertTrue(ok["saved"], ok)
            self.assertEqual(ok["invoice"]["number"], "INV-0001")

    def test_a_line_with_no_quantity_is_a_question_not_a_one(self) -> None:
        # The schema marks quantity required, so this only fires when the model has already
        # dropped it — and defaulting to 1 put a price on a line nobody asked for
        # (the internal audit PLUG-9).
        self.mod.register(PerKeyCtx(pricebook_path=PRICEBOOK))
        answer = self.call("invoice_create", {"customer": "Bellview", "lines": [{"item": "kale"}]})
        self.assertIn("How many", answer)
        self.assertNotIn("INV-", answer)
        # And a quantity of zero or less is the same question, from the ledger's own refusal.
        for bad in ("0", "-2"):
            with self.subTest(quantity=bad):
                answer = self.call(
                    "invoice_create",
                    {"customer": "Bellview", "lines": [{"item": "Green Beans", "quantity": bad}]},
                )
                self.assertIn("How many", answer)
                self.assertNotIn("INV-", answer)


if __name__ == "__main__":
    unittest.main()
