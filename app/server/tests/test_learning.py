"""Tests for the learning read model — what the assistant has learned about the business.

This is the newest of the BFF's three engine-facing readers (`engine_settings.py`,
`skills_index.py`, this one) and it carries the most weight, because it is the only place a
operator can check a claim the assistant made about itself. So the tests are about **honesty**
rather than features:

* an unreadable file is reported as unreadable, never as "nothing learned";
* `origin: learned` is only claimed when the engine's own files say the agent wrote the skill —
  a bundled skill that was merely patched is not "taught itself";
* the session attribution is the ledger's own `evidence.session_id`, and an unknown session
  yields nothing rather than the nearest row;
* a malformed ledger line is skipped, because another process appends to that file live.

Run from the repo root:

    PYTHONPATH=core/src:app/server python -m unittest discover -s app/server/tests -t app/server/tests
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "core" / "src"))
sys.path.insert(0, str(REPO_ROOT / "app" / "server"))

from learning import (  # noqa: E402
    ENTRY_DELIMITER,
    attach_provenance,
    curator_interval,
    fingerprint,
    load_curator,
    load_ledger,
    load_learning,
    load_memory,
    memory_limits,
    parse_entries,
    session_changes,
)


def ledger_row(
    row_id: str,
    ts: str,
    actor: str,
    action: str,
    skill: str,
    session: str | None = None,
    file_path: str | None = None,
) -> str:
    evidence: dict[str, str] = {}
    if session:
        evidence["session_id"] = session
    if file_path:
        evidence["file_path"] = file_path
    return json.dumps(
        {
            "id": row_id,
            "ts": ts,
            "actor": actor,
            "action": action,
            "skill": skill,
            "evidence": evidence,
            "before": [],
            "after": [{"path": f"/skills/{skill}/SKILL.md", "sha256": "0" * 64}],
        }
    )


class ProfileFixture(unittest.TestCase):
    """A profile directory with the files the engine actually writes."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.profile = Path(self._tmp.name) / "profiles" / "pantler"
        (self.profile / "skills").mkdir(parents=True)
        (self.profile / "memories").mkdir(parents=True)
        self.profile.joinpath("config.yaml").write_text("model:\n  provider: test\n")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write_memory(self, name: str, entries: list[str]) -> None:
        self.profile.joinpath("memories", name).write_text(
            ENTRY_DELIMITER.join(entries), encoding="utf-8"
        )

    def write_usage(self, usage: dict) -> None:
        self.profile.joinpath("skills", ".usage.json").write_text(json.dumps(usage), encoding="utf-8")

    def write_ledger(self, rows: list[str]) -> None:
        self.profile.joinpath("skills", ".curator_ledger.jsonl").write_text(
            "\n".join(rows) + "\n", encoding="utf-8"
        )

    def write_manifest(self, names: list[str]) -> None:
        self.profile.joinpath("skills", ".bundled_manifest").write_text(
            "".join(f"{name}:{'0' * 32}\n" for name in names), encoding="utf-8"
        )


class ParseEntriesTestCase(unittest.TestCase):
    def test_splits_on_the_full_delimiter_only(self) -> None:
        self.assertEqual(parse_entries(f"one{ENTRY_DELIMITER}two"), ["one", "two"])

    def test_a_bare_section_sign_does_not_split(self) -> None:
        # The engine's own rule: only "\n§\n" delimits, so a § inside an entry survives.
        self.assertEqual(parse_entries("a § b"), ["a § b"])

    def test_strips_and_drops_empty_entries(self) -> None:
        self.assertEqual(parse_entries(f"\n  one  {ENTRY_DELIMITER}{ENTRY_DELIMITER}\n"), ["one"])

    def test_an_empty_file_has_no_entries(self) -> None:
        self.assertEqual(parse_entries(""), [])

    def test_fingerprint_is_a_function_of_the_text(self) -> None:
        # Mirrors agent.learning_graph.memory_fingerprint, so an id names the same card the
        # engine's own journey view names — including across an earlier entry being removed.
        self.assertEqual(fingerprint("  hello  "), fingerprint("hello"))
        self.assertNotEqual(fingerprint("hello"), fingerprint("hello."))
        self.assertEqual(len(fingerprint("hello")), 12)


class MemoryTestCase(ProfileFixture):
    def test_reads_entries_with_the_engines_own_node_ids(self) -> None:
        self.write_memory("MEMORY.md", ["first", "second"])
        memory = load_memory(self.profile)

        self.assertEqual(memory["total"], 2)
        self.assertEqual([entry["text"] for entry in memory["entries"]], ["first", "second"])
        self.assertEqual(memory["entries"][0]["id"], f"memory:memory:0:{fingerprint('first')}")
        self.assertEqual(memory["entries"][1]["id"], f"memory:memory:1:{fingerprint('second')}")
        self.assertEqual(memory["entries"][1]["label"], "Memory")

    def test_a_missing_file_is_empty_not_an_error(self) -> None:
        self.write_memory("MEMORY.md", ["kept"])
        memory = load_memory(self.profile)

        files = {record["name"]: record for record in memory["files"]}
        self.assertTrue(files["MEMORY.md"]["present"])
        self.assertFalse(files["USER.md"]["present"])
        self.assertEqual(files["USER.md"]["entries"], 0)
        self.assertTrue(memory["readable"])

    def test_user_md_uses_the_user_budget_not_the_memory_one(self) -> None:
        # The source prefix is `profile` (the engine's node id) while the config key is
        # `user_char_limit`; conflating them would report USER.md against the wrong ceiling.
        memory = load_memory(self.profile)
        limits = {record["source"]: record["limit"] for record in memory["files"]}
        self.assertEqual(limits["memory"], 2200)
        self.assertEqual(limits["profile"], 1375)

    def test_an_unreadable_file_says_so_rather_than_reading_as_empty(self) -> None:
        path = self.profile / "memories" / "MEMORY.md"
        path.write_bytes(b"\xff\xfe\x00 not utf-8")
        memory = load_memory(self.profile)

        record = next(item for item in memory["files"] if item["name"] == "MEMORY.md")
        self.assertTrue(record["present"])
        self.assertFalse(record["readable"])
        self.assertIsNone(record["entries"])
        self.assertFalse(memory["readable"])

    def test_percent_is_against_the_profiles_own_limit(self) -> None:
        self.write_memory("MEMORY.md", ["x" * 110])
        memory = load_memory(self.profile, {"memory": 2200, "user": 1375})
        record = next(item for item in memory["files"] if item["name"] == "MEMORY.md")
        self.assertEqual(record["percent"], 5)


class LimitsTestCase(unittest.TestCase):
    def test_reads_the_profiles_own_budgets(self) -> None:
        config = "memory:\n  memory_char_limit: 500\n  user_char_limit: 250\n"
        self.assertEqual(memory_limits(config), {"memory": 500, "user": 250})

    def test_an_absent_block_leaves_the_engine_defaults(self) -> None:
        self.assertEqual(memory_limits("model:\n  provider: x\n"), {})

    def test_a_nested_key_does_not_leak_into_the_read(self) -> None:
        config = "other:\n  memory_char_limit: 9\n"
        self.assertEqual(memory_limits(config), {})

    def test_a_non_numeric_value_is_ignored_rather_than_guessed(self) -> None:
        config = "memory:\n  memory_char_limit: auto\n"
        self.assertEqual(memory_limits(config), {})

    def test_curator_interval_is_read_when_set(self) -> None:
        self.assertEqual(curator_interval("curator:\n  interval_hours: 24\n"), 24.0)
        self.assertIsNone(curator_interval("memory:\n  memory_char_limit: 5\n"))


class LedgerTestCase(ProfileFixture):
    def test_reads_the_engines_attribution(self) -> None:
        self.write_ledger(
            [
                ledger_row("a", "2026-10-13T06:14:33.393453+00:00", "curator", "patch", "soil", "web-1"),
                ledger_row("b", "2026-10-13T06:14:34.000000+00:00", "agent", "create", "carousel"),
            ]
        )
        rows = load_ledger(self.profile)

        self.assertEqual([row["skill"] for row in rows], ["soil", "carousel"])
        self.assertEqual(rows[0]["session"], "web-1")
        self.assertIsNone(rows[1]["session"])
        self.assertAlmostEqual(rows[0]["at"], 1791872073.39, places=2)

    def test_a_malformed_line_is_skipped_not_fatal(self) -> None:
        # The file is appended to by another process; a half-written tail is normal.
        self.profile.joinpath("skills", ".curator_ledger.jsonl").write_text(
            '{"id": "a", "ts": "2026-10-13T00:00:00+00:00", "actor": "agent", "action": "create", "skill": "x"}\n'
            '{"id": "b", "ts": "2026-10-13T00:00:0\n',
            encoding="utf-8",
        )
        self.assertEqual([row["id"] for row in load_ledger(self.profile)], ["a"])

    def test_an_absent_ledger_is_an_empty_list(self) -> None:
        self.assertEqual(load_ledger(self.profile), [])

    def test_session_attribution_is_exact(self) -> None:
        self.write_ledger(
            [
                ledger_row("a", "2026-10-13T06:00:00+00:00", "agent", "patch", "one", "web-1"),
                ledger_row("b", "2026-10-13T06:00:01+00:00", "agent", "patch", "two", "web-2"),
            ]
        )
        rows = load_ledger(self.profile)

        self.assertEqual([row["skill"] for row in session_changes(rows, "web-2")], ["two"])
        self.assertEqual(session_changes(rows, "web-9"), [])
        self.assertEqual(session_changes(rows, ""), [])


class ProvenanceTestCase(ProfileFixture):
    def test_a_learned_skill_is_learned_only_when_the_engine_says_so(self) -> None:
        # The distinction that matters most on the page: a skill the app shipped is not a skill
        # the assistant taught itself, however useful it turns out to be.
        self.write_usage(
            {
                "carousel": {"created_by": "learn", "patch_count": 2, "use_count": 0},
                "invoicing": {"created_by": None, "patch_count": 0, "use_count": 34},
            }
        )
        self.write_manifest(["pdf"])
        rows = {
            row["name"]: row
            for row in attach_provenance(
                [{"name": "carousel"}, {"name": "invoicing"}, {"name": "pdf"}],
                {"carousel": {"created_by": "learn"}, "invoicing": {"created_by": None}, "pdf": {"created_by": None}},
                {"pdf"},
                [],
            )
        }

        self.assertEqual(rows["carousel"]["origin"], "learned")
        self.assertEqual(rows["invoicing"]["origin"], "installed")
        self.assertEqual(rows["pdf"]["origin"], "bundled")

    def test_the_ledger_can_make_a_skill_learned_without_usage_metadata(self) -> None:
        ledger = [
            {"id": "a", "at": 10.0, "actor": "agent", "action": "create", "skill": "carousel", "session": "web-1", "file": None, "files": []}
        ]
        row = attach_provenance([{"name": "carousel"}], {}, set(), ledger)[0]
        self.assertEqual(row["origin"], "learned")
        self.assertEqual(row["learnedAt"], 10.0)

    def test_a_bundled_skill_that_was_patched_is_bundled_not_learned(self) -> None:
        usage = {"pdf": {"created_by": None, "patch_count": 3, "use_count": 1}}
        ledger = [
            {"id": "a", "at": 5.0, "actor": "curator", "action": "patch", "skill": "pdf", "session": None, "file": None, "files": []}
        ]
        row = attach_provenance([{"name": "pdf"}], usage, {"pdf"}, ledger)[0]
        self.assertEqual(row["origin"], "bundled")
        self.assertIsNone(row["learnedAt"])
        self.assertEqual(row["patches"], 3)
        self.assertEqual(row["lastPatchedAt"], 5.0)

    def test_an_external_mount_is_neither_learned_nor_bundled(self) -> None:
        usage = {"mounted": {"created_by": "external"}}
        row = attach_provenance([{"name": "mounted"}], usage, {"mounted"}, [])[0]
        self.assertEqual(row["origin"], "external")

    def test_the_earliest_create_wins_when_the_ledger_has_several(self) -> None:
        ledger = [
            {"id": "b", "at": 20.0, "actor": "agent", "action": "create", "skill": "x", "session": None, "file": None, "files": []},
            {"id": "a", "at": 10.0, "actor": "agent", "action": "create", "skill": "x", "session": None, "file": None, "files": []},
        ]
        row = attach_provenance([{"name": "x"}], {}, set(), ledger)[0]
        self.assertEqual(row["learnedAt"], 10.0)

    def test_a_skill_the_engine_knows_nothing_about_keeps_its_own_fields(self) -> None:
        row = attach_provenance(
            [{"name": "fresh", "description": "d", "category": "c", "enabled": False}], {}, set(), []
        )[0]
        self.assertEqual(row["description"], "d")
        self.assertEqual(row["category"], "c")
        self.assertFalse(row["enabled"])
        self.assertEqual(row["patches"], 0)
        self.assertEqual(row["uses"], 0)


class CuratorTestCase(ProfileFixture):
    def test_reads_the_state_file(self) -> None:
        self.profile.joinpath("skills", ".curator_state").write_text(
            json.dumps(
                {
                    "paused": True,
                    "run_count": 24,
                    "last_run_at": "2026-10-10T04:24:27.762791+00:00",
                    "last_run_summary": "auto: 2 marked stale, 6 archived",
                }
            ),
            encoding="utf-8",
        )
        curator = load_curator(self.profile)

        self.assertTrue(curator["available"])
        self.assertTrue(curator["paused"])
        self.assertEqual(curator["runCount"], 24)
        self.assertEqual(curator["summary"], "auto: 2 marked stale, 6 archived")

    def test_an_absent_state_file_is_unavailable_not_idle(self) -> None:
        self.assertFalse(load_curator(self.profile)["available"])


class LoadLearningTestCase(ProfileFixture):
    def test_assembles_the_whole_read_model(self) -> None:
        self.write_memory("MEMORY.md", ["Bellview delivers Tuesdays."])
        self.write_usage({"carousel": {"created_by": "learn", "use_count": 2}})
        self.write_ledger(
            [ledger_row("a", "2026-10-13T06:00:00+00:00", "agent", "create", "carousel", "web-1")]
        )
        model = load_learning(
            self.profile,
            skills=[{"name": "carousel"}, {"name": "invoicing"}],
            config_text="memory:\n  memory_char_limit: 100\n",
        )

        self.assertTrue(model["available"])
        self.assertEqual(model["profile"], "pantler")
        self.assertEqual(model["counts"], {"listed": 2, "learned": 1, "changed": 0})
        self.assertEqual(model["memory"]["total"], 1)
        self.assertEqual(model["ledger"][0]["session"], "web-1")
        self.assertEqual(model["skills"][0]["origin"], "learned")

    def test_an_empty_profile_is_available_and_empty(self) -> None:
        # The distinction the whole module turns on: available with nothing learned is a
        # different answer from unavailable.
        model = load_learning(self.profile)
        self.assertTrue(model["available"])
        self.assertEqual(model["memory"]["entries"], [])
        self.assertEqual(model["counts"]["listed"], 0)
        self.assertEqual(model["ledger"], [])


class BffRouteTestCase(ProfileFixture):
    """The route, through the object the HTTP layer calls — no socket."""

    def bff(self):
        from pantler_core import PackRegistry, Store
        from pantler_server import Bff
        from engine_settings import EngineProfile

        store = Store(Path(self._tmp.name) / "records.db")
        return Bff(store, PackRegistry([]), EngineProfile(self.profile))

    def test_learning_answers_the_read_model(self) -> None:
        self.write_memory("MEMORY.md", ["kept"])
        status, payload = self.bff().learning({})

        self.assertEqual(status, 200)
        self.assertTrue(payload["available"])
        self.assertEqual(payload["memory"]["total"], 1)

    def test_session_learning_is_scoped_to_the_session(self) -> None:
        self.write_ledger(
            [
                ledger_row("a", "2026-10-13T06:00:00+00:00", "agent", "patch", "one", "web-1"),
                ledger_row("b", "2026-10-13T06:00:01+00:00", "agent", "patch", "two", "web-2"),
            ]
        )
        status, payload = self.bff().session_learning({"session": "web-1"})

        self.assertEqual(status, 200)
        self.assertEqual([row["skill"] for row in payload["data"]], ["one"])

    def test_without_a_profile_every_answer_is_unavailable_not_empty(self) -> None:
        from pantler_core import PackRegistry, Store
        from pantler_server import Bff

        store = Store(Path(self._tmp.name) / "records.db")
        bff = Bff(store, PackRegistry([]), None)

        for payload in (bff.learning({})[1], bff.session_learning({"session": "web-1"})[1]):
            self.assertFalse(payload["available"])
            self.assertTrue(payload["reason"])


class CuratorStateTestCase(ProfileFixture):
    """`.curator_state` is the engine's file, written by the engine's own code.

    The reader has to survive whatever a hand edit or an older engine leaves in it: a state
    file is not a contract this app can refuse (the internal audit BFF-13).
    """

    def write_state(self, payload) -> None:
        text = payload if isinstance(payload, str) else json.dumps(payload)
        self.profile.joinpath("skills", ".curator_state").write_text(text, encoding="utf-8")

    def test_a_normal_state_reads_back(self) -> None:
        self.write_state({"paused": True, "run_count": 3, "last_run_at": "2026-10-13T06:00:00+00:00"})
        state = load_curator(self.profile)
        self.assertTrue(state["available"])
        self.assertTrue(state["paused"])
        self.assertEqual(state["runCount"], 3)
        self.assertIsNotNone(state["lastRunAt"])

    def test_a_string_false_is_not_paused(self) -> None:
        # `bool("false")` is `True`, so the status line used to report a paused curator for a
        # file that said the opposite.
        self.write_state({"paused": "false", "run_count": "0"})
        state = load_curator(self.profile)
        self.assertFalse(state["paused"])
        self.assertEqual(state["runCount"], 0)

    def test_a_nonsense_run_count_does_not_raise(self) -> None:
        # This used to be an unhandled `ValueError` — a 500 on `/api/learning` because one
        # field of one file was not a number.
        self.write_state({"paused": False, "run_count": "not a number"})
        self.assertEqual(load_curator(self.profile)["runCount"], 0)

    def test_a_missing_or_unreadable_state_is_unavailable(self) -> None:
        self.assertEqual(load_curator(self.profile), {"available": False})
        self.write_state("[1, 2, 3]")
        self.assertEqual(load_curator(self.profile), {"available": False})


if __name__ == "__main__":
    unittest.main()


# ------------------------------------------- A19-CFG-9 · a memory file that is not a memory


class MemorySymlinkTest(unittest.TestCase):
    """A planted symlink must not turn the memory reader into a credential reader."""

    def test_a_symlinked_memory_file_is_refused_and_its_target_is_not_read(self) -> None:
        from learning import load_memory

        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory)
            (profile / "memories").mkdir()
            (profile / ".env").write_text("ANTHROPIC_API_KEY=sk-live-real-secret\n")
            (profile / "memories" / "MEMORY.md").symlink_to(profile / ".env")
            payload = load_memory(profile)
            rendered = json.dumps(payload)
            self.assertNotIn("sk-live-real-secret", rendered)
            entry = next(f for f in payload["files"] if f["name"] == "MEMORY.md")
            self.assertFalse(entry["readable"])
            self.assertIn("symlink", entry["reason"])

    def test_an_ordinary_memory_file_still_reads(self) -> None:
        from learning import load_memory

        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory)
            (profile / "memories").mkdir()
            (profile / "memories" / "MEMORY.md").write_text("Bellview CSA pays on Fridays\n")
            payload = load_memory(profile)
            entry = next(f for f in payload["files"] if f["name"] == "MEMORY.md")
            self.assertTrue(entry["readable"])

    def test_a_broken_usage_counter_does_not_take_the_route_down(self) -> None:
        from learning import load_ledger, session_changes

        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory)
            (profile / "skills").mkdir()
            (profile / "skills" / ".usage.json").write_text(
                json.dumps({"invoicing": {"patch_count": "many", "use_count": None}})
            )
            # Whatever the ledger says, this must answer rather than raise.
            self.assertIsInstance(session_changes(load_ledger(profile), "web-1"), list)
