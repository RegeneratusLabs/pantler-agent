"""The consent gate, tested on the decisions that decide whether it is worth having.

Two of these tests are the whole point. **A person with no consent record is refused**, not warned
about — the plan calls this pack's worst failure mode a statutory breach rather than a bad post, and a
gate that hedges is a gate that gets overridden. And **a withdrawal is final**: the record stays, and
the permission does not.

The rest pin the ways a gate goes wrong quietly: matching one person's consent to another's name,
treating a past purchase as consent, and a switched-off gate that forgets to say it checked nothing.

    python3 -m unittest discover -s plugins/consent/tests -t plugins/consent/tests
"""

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
sys.path.insert(0, str(PLUGIN))

from pantler_core import RecordBook  # noqa: E402
from consentengine import ALLOWED, AMBIGUOUS, NO_RECORD, WITHDRAWN, check_draft  # noqa: E402


class GateTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.book = RecordBook(Path(self._dir.name) / "records.db", REPO / "packs")

    def tearDown(self) -> None:
        self.book.close()
        self._dir.cleanup()

    def consent(self, **fields) -> None:
        payload = {"who": "Maria Chen", "what": "the newsletter", "where_used": "the newsletter"}
        payload.update(fields)
        self.book.save("consent", payload)

    def test_no_record_is_a_refusal_with_a_sentence(self) -> None:
        from consentengine import check_send

        result = check_send(self.book, ["Someone New"], purpose="the newsletter")
        self.assertFalse(result.allowed)
        self.assertEqual(result.decisions[0].status, NO_RECORD)
        self.assertIn("refusal, not a caution", result.decisions[0].detail)

    def test_a_live_consent_allows_and_names_its_record(self) -> None:
        from consentengine import check_send

        self.consent()
        result = check_send(self.book, ["Maria Chen"], purpose="the newsletter")
        self.assertTrue(result.allowed)
        decision = result.decisions[0]
        self.assertEqual(decision.status, ALLOWED)
        self.assertEqual(decision.record_id, "CON-0001")
        self.assertIn("CON-0001", decision.detail)

    def test_a_withdrawal_ends_the_permission_and_the_record_stays(self) -> None:
        from consentengine import check_send

        self.consent(withdrawn_on="2026-10-01")
        result = check_send(self.book, ["Maria Chen"], purpose="the newsletter")
        self.assertFalse(result.allowed)
        self.assertEqual(result.decisions[0].status, WITHDRAWN)
        self.assertIn("withdrawn on 2026-10-01", result.decisions[0].detail)
        # The record is still there — the history is the point.
        self.assertEqual(len(self.book.find("consent")), 1)

    def test_a_consent_for_one_place_does_not_cover_another(self) -> None:
        from consentengine import check_send

        self.consent(where_used="the website")
        result = check_send(self.book, ["Maria Chen"], purpose="the newsletter")
        self.assertFalse(result.allowed)
        self.assertIn("not a consent for all of them", result.decisions[0].detail)

    def test_a_send_with_no_stated_place_is_refused(self) -> None:
        """An omitted `purpose` skipped the place check entirely, so saying nothing was allowed.

        The model chooses the arguments, so the safe default has to be the refusal
        (the internal security audit A19-PLUG-9).
        """
        from consentengine import check_send

        self.consent()
        for purpose in ("", "   "):
            with self.subTest(purpose=purpose):
                result = check_send(self.book, ["Maria Chen"], purpose=purpose)
                self.assertFalse(result.allowed, result)
                self.assertTrue(result.refusals, result)
                self.assertIn("does not say where it is going", result.decisions[0].detail)

    def test_the_place_is_an_identity_not_a_substring(self) -> None:
        """"letter" used to be allowed because it sits inside "the newsletter".

        A consent for one place is not a consent for every substring of its name
        (the internal security audit A19-PLUG-9).
        """
        from consentengine import check_send

        self.consent(where_used="the newsletter")
        self.assertTrue(check_send(self.book, ["Maria Chen"], purpose="the newsletter").allowed)
        for purpose in ("letter", "the news", "newsletters", "newsletter"):
            with self.subTest(purpose=purpose):
                result = check_send(self.book, ["Maria Chen"], purpose=purpose)
                self.assertFalse(result.allowed, purpose)
                self.assertIn("not a consent for all of them", result.decisions[0].detail)

    def test_a_record_naming_two_places_does_not_cover_either_alone(self) -> None:
        """The other direction of the substring test: the record was the longer string."""
        from consentengine import check_send

        self.consent(where_used="the newsletter and the website")
        result = check_send(self.book, ["Maria Chen"], purpose="the newsletter")
        self.assertFalse(result.allowed)
        self.assertIn("not a consent for all of them", result.decisions[0].detail)

    def test_one_persons_consent_does_not_cover_another(self) -> None:
        """The matching rule that matters: a name is a name, not a fuzzy search."""
        from consentengine import check_send

        self.consent(who="Maria Chen")
        for other in ("Chris Chen", "Maria", "M. Chen-Smith", "Mariah Chen"):
            with self.subTest(other=other):
                result = check_send(self.book, [other], purpose="the newsletter")
                # "Maria" alone is refused, and that is the point: a first name is not the person
                # the record names, and a gate that emails on a shared word is a gate that emails
                # the wrong person. The operator answers by giving the full name
                # (the internal audit PLUG-5).
                self.assertFalse(result.allowed, other)

    def test_a_one_word_record_covers_one_name_and_nothing_else(self) -> None:
        """A record whose `who` is one token is that one name.

        "Chen" used to match "Alice Chen", "Bob Chen" and "Chen Family Trust" — one person's
        permission covering three, which is the failure the matcher's own docstring says the rule
        exists to prevent.
        """
        from consentengine import check_send

        self.consent(who="Chen")
        self.assertTrue(check_send(self.book, ["Chen"], purpose="the newsletter").allowed)
        for other in ("Alice Chen", "Bob Chen", "Chen Family Trust"):
            with self.subTest(other=other):
                self.assertFalse(
                    check_send(self.book, [other], purpose="the newsletter").allowed, other
                )

    def test_an_abbreviation_covers_the_name_it_abbreviates(self) -> None:
        from consentengine import check_send

        self.consent(who="M. Chen")
        self.assertTrue(check_send(self.book, ["Maria Chen"], purpose="the newsletter").allowed)

    def test_a_near_miss_name_does_not_inherit_a_consent(self) -> None:
        from consentengine import check_send

        # "Maria" is a prefix of "Mariah", not an abbreviation of it, and they are two people.
        self.consent(who="Maria Chen")
        self.assertFalse(check_send(self.book, ["Mariah Chen"], purpose="the newsletter").allowed)

    def test_a_draft_that_is_not_ready_to_send_is_not_allowed(self) -> None:
        """`send_allowed` has to mean "this may be sent as it stands".

        It reported true while the check beside it said the unsubscribe line was missing — the
        tool's own note says every recipient must be allowed before anything is sent, and a
        message with no way out is not sendable (the internal audit PLUG-16).
        """
        from consentengine import check_send

        self.consent()
        bare = check_send(self.book, ["Maria Chen"], purpose="the newsletter", draft="Hello.")
        self.assertFalse(bare.allowed)
        self.assertTrue(any("unsubscribe" in r.lower() or "sender" in r.lower()
                            for r in bare.refusals), bare.refusals)

        complete = check_send(
            self.book,
            ["Maria Chen"],
            purpose="the newsletter",
            draft=(
                "Hello.\n\nRegards,\nExample Farm, 1 Road, Town\n\n"
                "Unsubscribe: use the link in the footer of this email."
            ),
        )
        self.assertTrue(complete.allowed, complete)

    def test_two_live_records_ask_rather_than_choosing(self) -> None:
        from consentengine import check_send

        self.consent(where_used="the newsletter")
        self.consent(what="the market texts", where_used="the market texts")
        result = check_send(self.book, ["Maria Chen"], purpose="the newsletter")
        self.assertFalse(result.allowed)
        self.assertEqual(result.decisions[0].status, AMBIGUOUS)
        self.assertTrue(result.questions)

    def test_a_mixed_list_is_refused_as_a_whole(self) -> None:
        """One person without a record refuses the send, not just their own line."""
        from consentengine import check_send

        self.consent()
        result = check_send(self.book, ["Maria Chen", "Someone New"], purpose="the newsletter")
        self.assertFalse(result.allowed)
        self.assertEqual(len(result.refusals), 1)
        self.assertEqual(
            [d.status for d in result.decisions], [ALLOWED, NO_RECORD]
        )

    def test_the_draft_checks_report_a_missing_unsubscribe_and_sender(self) -> None:
        findings = check_draft("Beans are ready! Come to the market.")
        checks = {finding["check"] for finding in findings}
        self.assertEqual(checks, {"unsubscribe", "sender"})
        clean = check_draft("Beans are ready — Regards, Josh at Bellview. Unsubscribe any time.")
        self.assertEqual(clean, [])

    def test_an_empty_draft_is_not_linted(self) -> None:
        self.assertEqual(check_draft(""), [])


class PluginTestCase(unittest.TestCase):
    class Ctx:
        def __init__(self, **settings):
            self.settings, self.tools = settings, []

        def register_tool(self, **kw):
            self.tools.append(kw)

        def get_config(self, key=None, default=None):
            return dict(self.settings) if key is None else self.settings.get(key, default)

    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.store = Path(self._dir.name) / "records.db"

    def tearDown(self) -> None:
        book = getattr(self, "_module", None)
        if book is not None:
            cached = book.tools._STATE.get("book")
            if cached is not None:
                cached.close()
            book.tools._STATE["book"] = None
        self._dir.cleanup()

    def load(self, **settings):
        for name in [n for n in sys.modules if n == "consent_plugin" or n.startswith("consent_plugin.")]:
            del sys.modules[name]
        spec = importlib.util.spec_from_file_location(
            "consent_plugin", PLUGIN / "__init__.py", submodule_search_locations=[str(PLUGIN)]
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules["consent_plugin"] = module
        spec.loader.exec_module(module)
        ctx = self.Ctx(store_path=str(self.store), packs_dir=str(REPO / "packs"), **settings)
        module.register(ctx)
        self._module = module
        return module, ctx

    def call(self, ctx, params):
        return json.loads(next(t["handler"] for t in ctx.tools if t["name"] == "consent_check")(params))

    def test_one_tool_under_its_own_toolset(self) -> None:
        _, ctx = self.load()
        self.assertEqual([t["name"] for t in ctx.tools], ["consent_check"])
        self.assertEqual({t["toolset"] for t in ctx.tools}, {"consent"})

    def test_a_refusal_comes_back_as_a_refusal(self) -> None:
        _, ctx = self.load()
        result = self.call(ctx, {"recipients": ["Someone New"], "purpose": "the newsletter"})
        self.assertTrue(result["success"], result)
        self.assertFalse(result["send_allowed"])
        self.assertTrue(result["refusals"])

    def test_the_gate_reads_records_written_elsewhere(self) -> None:
        """A consent recorded in the app is a consent this gate can see — one store, one answer."""
        writer = RecordBook(self.store, REPO / "packs")
        writer.save(
            "consent",
            {"who": "Maria Chen", "what": "the newsletter", "where_used": "the newsletter"},
        )
        writer.close()
        _, ctx = self.load()
        result = self.call(ctx, {"recipients": ["Maria Chen"], "purpose": "the newsletter"})
        self.assertTrue(result["send_allowed"], result)
        self.assertEqual(result["decisions"][0]["record_id"], "CON-0001")

    def test_a_switched_off_gate_says_it_checked_nothing(self) -> None:
        _, ctx = self.load(capability_enabled=False)
        result = self.call(ctx, {"recipients": ["Maria Chen"]})
        self.assertFalse(result["success"])
        self.assertIn("nobody here has been checked", result["error"])

    def test_recipients_may_arrive_as_one_string(self) -> None:
        _, ctx = self.load()
        # The purpose is required now (A19-PLUG-9); what this test pins is the recipient form.
        result = self.call(
            ctx, {"recipients": "Maria Chen, Someone New", "purpose": "the newsletter"}
        )
        self.assertEqual(len(result["decisions"]), 2)

    def test_an_omitted_purpose_is_refused_by_the_tool(self) -> None:
        """An omitted `purpose` used to skip the place check, so saying nothing was allowed.

        The model chooses the arguments, and the one it gets by omission is the one it will use
        (the internal security audit A19-PLUG-9).
        """
        writer = RecordBook(self.store, REPO / "packs")
        writer.save(
            "consent",
            {"who": "Maria Chen", "what": "the newsletter", "where_used": "the newsletter"},
        )
        writer.close()
        _, ctx = self.load()
        for params in (
            {"recipients": ["Maria Chen"]},
            {"recipients": ["Maria Chen"], "purpose": "   "},
        ):
            with self.subTest(params=params):
                result = self.call(ctx, params)
                self.assertFalse(result["success"], result)
                self.assertIn("Which place", result["error"])
                self.assertNotIn("decisions", result)

    def test_an_abbreviated_place_is_refused_by_the_tool(self) -> None:
        """"letter" sits inside "the newsletter" and used to be allowed: identity, not substring.

        (the internal security audit A19-PLUG-9)
        """
        writer = RecordBook(self.store, REPO / "packs")
        writer.save(
            "consent",
            {"who": "Maria Chen", "what": "the newsletter", "where_used": "the newsletter"},
        )
        writer.close()
        _, ctx = self.load()
        allowed = self.call(
            ctx, {"recipients": ["Maria Chen"], "purpose": "the newsletter"}
        )
        self.assertTrue(allowed["send_allowed"], allowed)
        for purpose in ("letter", "the news", "newsletters"):
            with self.subTest(purpose=purpose):
                result = self.call(ctx, {"recipients": ["Maria Chen"], "purpose": purpose})
                self.assertFalse(result["send_allowed"], result)
                self.assertTrue(result["refusals"], result)


if __name__ == "__main__":
    unittest.main()
