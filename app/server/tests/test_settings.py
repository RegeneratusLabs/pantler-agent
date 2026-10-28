"""Tests for engine settings — the installed tier's local-file settings surface.

Two things are being protected here, and only one of them is functionality.

1. **Refusal.** `config.yaml` is an operator's configuration. The writer replaces one block and
   must preserve every other byte, and it must *refuse* any `model:` block it does not fully
   understand rather than flatten it. A silently flattened block is a rewritten config.
2. **Secrecy.** No route, on any path, returns a secret value. The tests assert on the whole
   serialised payload rather than on the field, so a future field cannot leak one quietly.

Run from the repo root:

    PYTHONPATH=core/src:app/server python -m unittest discover -s app/server/tests -t app/server/tests
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "core" / "src"))
sys.path.insert(0, str(REPO_ROOT / "app" / "server"))

from engine_settings import EngineProfile, SettingsError  # noqa: E402
from pantler_core import PackRegistry, Store, pack_from_dict  # noqa: E402
from pantler_server import ApiError, Bff  # noqa: E402

CONFIG = """\
# a comment that must survive
model:
  provider: opencode-go
  default: deepseek-v4.1-flash
  base_url: https://opencode.ai/zen/go/v1
  api_mode: chat_completions
  key_env: OPENCODE_GO_API_KEY
approvals:
  mode: manual
plugins:
  enabled:
    - pantler
"""

ENV = """\
API_SERVER_KEY=abc123
OPENCODE_GO_API_KEY=
# a note between keys
"""

SECRET = "sk-live-do-not-print-me"


class ProfileTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.dir = Path(self._dir.name) / "pantler"
        self.dir.mkdir(parents=True)
        (self.dir / "config.yaml").write_text(CONFIG)
        (self.dir / ".env").write_text(ENV)
        self.profile = EngineProfile(self.dir)

    def tearDown(self) -> None:
        self._dir.cleanup()

    def config(self) -> str:
        return (self.dir / "config.yaml").read_text()

    def env(self) -> str:
        return (self.dir / ".env").read_text()

    # -- reading ----------------------------------------------------------

    def test_reads_the_model_block(self) -> None:
        self.assertEqual(
            self.profile.model(),
            {
                "provider": "opencode-go",
                "default": "deepseek-v4.1-flash",
                "base_url": "https://opencode.ai/zen/go/v1",
                "api_mode": "chat_completions",
                "key_env": "OPENCODE_GO_API_KEY",
            },
        )

    def test_reports_key_presence_never_values(self) -> None:
        names = self.profile.key_names()
        self.assertTrue(names["API_SERVER_KEY"])
        # An empty value is not a configured key.
        self.assertFalse(names["OPENCODE_GO_API_KEY"])

    def test_a_missing_profile_is_unavailable(self) -> None:
        self.assertFalse(EngineProfile(self.dir / "nope").available)

    # -- writing config.yaml ----------------------------------------------

    def test_set_model_changes_only_that_line(self) -> None:
        self.profile.set_model({"default": "glm-5.3"})
        self.assertEqual(
            self.config(),
            CONFIG.replace("default: deepseek-v4.1-flash", "default: glm-5.3"),
        )

    def test_set_model_leaves_a_comment_and_other_blocks_alone(self) -> None:
        self.profile.set_model({"provider": "openrouter"})
        text = self.config()
        self.assertIn("# a comment that must survive", text)
        self.assertIn("approvals:\n  mode: manual", text)
        self.assertIn("plugins:\n  enabled:\n    - pantler", text)

    def test_set_model_keeps_unknown_keys_in_the_block(self) -> None:
        (self.dir / "config.yaml").write_text("model:\n  provider: a\n  custom: keep-me\n")
        self.profile.set_model({"default": "b"})
        self.assertEqual(
            self.config(), "model:\n  provider: a\n  custom: keep-me\n  default: b\n"
        )

    def test_set_model_creates_the_block_when_absent(self) -> None:
        (self.dir / "config.yaml").write_text("approvals:\n  mode: manual\n")
        self.profile.set_model({"provider": "openrouter", "default": "x"})
        self.assertEqual(
            self.config(),
            "approvals:\n  mode: manual\n\nmodel:\n  provider: openrouter\n  default: x\n",
        )

    def test_set_model_refuses_a_field_it_does_not_own(self) -> None:
        with self.assertRaises(SettingsError) as caught:
            self.profile.set_model({"temperature": "0.2"})
        self.assertEqual(caught.exception.code, "unsupported_field")
        self.assertEqual(self.config(), CONFIG)

    def test_a_backup_is_kept(self) -> None:
        self.profile.set_model({"default": "glm-5.3"})
        self.assertEqual((self.dir / "config.yaml.bak").read_text(), CONFIG)

    def test_a_refused_write_leaves_no_backup(self) -> None:
        with self.assertRaises(SettingsError):
            self.profile.set_model({"nope": "x"})
        self.assertFalse((self.dir / "config.yaml.bak").exists())

    # -- refusing shapes we do not understand -----------------------------

    def test_refuses_every_shape_that_is_not_a_flat_mapping(self) -> None:
        bad = {
            "nested": "model:\n  provider: x\n  options:\n    nested: 1\n",
            "ragged": "model:\n  provider: x\n    default: y\n",
            "list": "model:\n  provider: x\n  tags:\n    - a\n",
            "block scalar": "model:\n  provider: |\n    multi\n",
            "empty value": "model:\n  provider:\n",
            "structural": "model:\n  provider: [a, b]\n",
        }
        for name, text in bad.items():
            with self.subTest(shape=name):
                (self.dir / "config.yaml").write_text(text)
                self.assertFalse(EngineProfile(self.dir).model_shape_ok())
                with self.assertRaises(SettingsError) as caught:
                    EngineProfile(self.dir).set_model({"default": "z"})
                self.assertEqual(caught.exception.code, "unexpected_shape")
                # The refusal must be total: the file is exactly as it was.
                self.assertEqual((self.dir / "config.yaml").read_text(), text)

    def test_accepts_a_flat_block_with_comments_and_quotes(self) -> None:
        (self.dir / "config.yaml").write_text(
            'model:\n  # why not\n  default: "a b: c"\n  provider: "x"\n'
        )
        profile = EngineProfile(self.dir)
        self.assertTrue(profile.model_shape_ok())
        self.assertEqual(profile.model(), {"default": "a b: c", "provider": "x"})

    # -- agent.disabled_toolsets ------------------------------------------

    def test_disabled_toolsets_reads_absent_as_empty(self) -> None:
        self.assertEqual(self.profile.disabled_toolsets(), [])
        self.assertTrue(self.profile.agent_shape_ok())

    def test_set_disabled_toolsets_creates_the_block_when_absent(self) -> None:
        self.profile.set_disabled_toolsets(["browser"])
        self.assertEqual(self.config(), CONFIG + "\nagent:\n  disabled_toolsets: [browser]\n")

    def test_set_disabled_toolsets_inserts_into_an_existing_block(self) -> None:
        (self.dir / "config.yaml").write_text("agent:\n  verbose: true\n")
        self.profile.set_disabled_toolsets(["browser", "terminal"])
        self.assertEqual(
            self.config(),
            "agent:\n  disabled_toolsets: [browser, terminal]\n  verbose: true\n",
        )

    def test_set_disabled_toolsets_preserves_other_agent_keys(self) -> None:
        (self.dir / "config.yaml").write_text(
            "model:\n  provider: x\nagent:\n  verbose: true\n  disabled_toolsets: [browser]\n"
        )
        self.profile.set_disabled_toolsets(["web"])
        self.assertEqual(
            self.config(),
            "model:\n  provider: x\nagent:\n  verbose: true\n  disabled_toolsets: [web]\n",
        )

    def test_set_disabled_toolsets_replaces_a_block_sequence(self) -> None:
        (self.dir / "config.yaml").write_text(
            "agent:\n  disabled_toolsets:\n    - browser\n    - terminal\n  other: keep\n"
        )
        self.assertEqual(EngineProfile(self.dir).disabled_toolsets(), ["browser", "terminal"])
        self.profile.set_disabled_toolsets(["web"])
        self.assertEqual(
            self.config(), "agent:\n  disabled_toolsets: [web]\n  other: keep\n"
        )

    def test_set_disabled_toolsets_sorts_and_dedupes(self) -> None:
        self.assertEqual(
            self.profile.set_disabled_toolsets(["web", "browser", "web"]), ["browser", "web"]
        )
        self.assertEqual(self.profile.disabled_toolsets(), ["browser", "web"])

    def test_reads_the_json_array_string_form(self) -> None:
        (self.dir / "config.yaml").write_text(
            'agent:\n  disabled_toolsets: \'["web", "browser"]\'\n'
        )
        self.assertEqual(EngineProfile(self.dir).disabled_toolsets(), ["web", "browser"])

    def test_an_empty_list_is_written_rather_than_removed(self) -> None:
        (self.dir / "config.yaml").write_text("agent:\n  verbose: true\n")
        self.profile.set_disabled_toolsets([])
        self.assertEqual(self.config(), "agent:\n  disabled_toolsets: []\n  verbose: true\n")
        self.assertEqual(self.profile.disabled_toolsets(), [])

    def test_set_disabled_toolsets_refuses_a_name_the_engine_would_ignore(self) -> None:
        for name in ("", "1LEADING", "has space", "has-dash", "semi;colon", "with\nnewline"):
            with self.subTest(name=name):
                with self.assertRaises(SettingsError) as caught:
                    self.profile.set_disabled_toolsets([name])
                self.assertEqual(caught.exception.code, "bad_name")
        self.assertEqual(self.config(), CONFIG)

    def test_set_disabled_toolsets_refuses_a_shape_it_does_not_understand(self) -> None:
        bad = {
            "nested mapping": "agent:\n  disabled_toolsets:\n    nested: 1\n",
            "flow mapping": "agent:\n  disabled_toolsets: {a: b}\n",
            "ragged": "agent:\n  disabled_toolsets:\n  - browser\n",
            "bad item": "agent:\n  disabled_toolsets: [browser, [x]]\n",
            "value plus list": "agent:\n  disabled_toolsets: [web]\n    - browser\n",
            # Two of the same key: this module would rewrite the first and leave the second,
            # while the engine's loader takes the last — so the screen would show one list and
            # the agent would honour the other (the internal audit BFF-3).
            "duplicated": "agent:\n  disabled_toolsets: [web]\n  disabled_toolsets: [code]\n",
        }
        for name, text in bad.items():
            with self.subTest(shape=name):
                (self.dir / "config.yaml").write_text(text)
                profile = EngineProfile(self.dir)
                self.assertFalse(profile.agent_shape_ok())
                with self.assertRaises(SettingsError) as caught:
                    profile.set_disabled_toolsets(["web"])
                self.assertEqual(caught.exception.code, "unexpected_shape")
                # The refusal is total: the file is exactly as it was.
                self.assertEqual((self.dir / "config.yaml").read_text(), text)

    def test_a_refused_toolset_write_leaves_no_backup(self) -> None:
        (self.dir / "config.yaml").write_text("agent:\n  disabled_toolsets: {a: b}\n")
        with self.assertRaises(SettingsError):
            EngineProfile(self.dir).set_disabled_toolsets(["web"])
        self.assertFalse((self.dir / "config.yaml.bak").exists())

    def test_a_toolset_write_keeps_a_backup(self) -> None:
        self.profile.set_disabled_toolsets(["browser"])
        self.assertEqual((self.dir / "config.yaml.bak").read_text(), CONFIG)

    # -- agent.reasoning_effort -------------------------------------------
    #
    # The engine silently ignores a level it does not know, so the interesting cases are the
    # refusals, the one canonical spelling of "off", and the promise that everything else in
    # config.yaml is left exactly as it was.

    RICH = (
        "# top comment\n"
        "model:\n"
        "  provider: opencode-go\n"
        "approvals:\n"
        "  mode: manual\n"
        "agent:\n"
        "  verbose: true\n"
        "  reasoning_effort: high\n"
        "  disabled_toolsets: [web]\n"
        "plugins:\n"
        "  enabled:\n"
        "    - pantler\n"
    )

    def test_reasoning_effort_reads_absent_as_unset(self) -> None:
        self.assertIsNone(self.profile.reasoning_effort())
        self.assertTrue(self.profile.reasoning_shape_ok())

    def test_reasoning_effort_reads_a_level_and_every_disabled_spelling(self) -> None:
        cases = {
            "low": "low",
            '"max"': "max",
            "false": "false",
            # The engine's other two spellings for "off" mean what `false` means; the page gets
            # one state to select rather than three.
            "none": "false",
            "disabled": "false",
            "False": "false",
        }
        for written, expected in cases.items():
            with self.subTest(written=written):
                (self.dir / "config.yaml").write_text(f"agent:\n  reasoning_effort: {written}\n")
                self.assertEqual(EngineProfile(self.dir).reasoning_effort(), expected)

    def test_reasoning_effort_ignores_a_trailing_yaml_comment(self) -> None:
        # A hand-edited `low  # everyday` is the level `low`. Reading the comment as the value
        # would have the page warn about a level the engine is reading happily.
        (self.dir / "config.yaml").write_text("agent:\n  reasoning_effort: low  # everyday\n")
        profile = EngineProfile(self.dir)
        self.assertEqual(profile.reasoning_effort(), "low")
        self.assertTrue(profile.reasoning_shape_ok())

    def test_reasoning_effort_returns_a_value_the_engine_would_ignore(self) -> None:
        # The read path shows what the file says. Hiding it would leave the operator with a
        # setting they cannot see and the engine is not using.
        (self.dir / "config.yaml").write_text("agent:\n  reasoning_effort: turbo\n")
        profile = EngineProfile(self.dir)
        self.assertEqual(profile.reasoning_effort(), "turbo")
        # Still a shape we will rewrite: the value is wrong, the block is fine.
        self.assertTrue(profile.reasoning_shape_ok())

    def test_reasoning_effort_reads_a_shape_it_cannot_rewrite_as_unset(self) -> None:
        bad = (
            "agent:\n  reasoning_effort:\n    effort: low\n",
            "agent:\n  reasoning_effort: low\n  reasoning_effort: high\n",
        )
        for text in bad:
            with self.subTest(text=text):
                (self.dir / "config.yaml").write_text(text)
                profile = EngineProfile(self.dir)
                # Lenient on the display path, strict on the write path.
                self.assertIsNone(profile.reasoning_effort())
                self.assertFalse(profile.reasoning_shape_ok())

    def test_set_reasoning_effort_creates_the_block_when_absent(self) -> None:
        self.assertEqual(self.profile.set_reasoning_effort("low"), "low")
        self.assertEqual(self.config(), CONFIG + "\nagent:\n  reasoning_effort: low\n")

    def test_set_reasoning_effort_inserts_into_an_existing_block(self) -> None:
        (self.dir / "config.yaml").write_text("agent:\n  verbose: true\n")
        self.profile.set_reasoning_effort("medium")
        self.assertEqual(
            self.config(), "agent:\n  reasoning_effort: medium\n  verbose: true\n"
        )

    def test_set_reasoning_effort_changes_one_line_and_nothing_else(self) -> None:
        (self.dir / "config.yaml").write_text(self.RICH)
        self.profile.set_reasoning_effort("low")
        self.assertEqual(
            self.config(), self.RICH.replace("reasoning_effort: high", "reasoning_effort: low")
        )

    def test_the_disabled_choice_is_written_as_yaml_false(self) -> None:
        (self.dir / "config.yaml").write_text("agent:\n  reasoning_effort: high\n")
        self.assertEqual(self.profile.set_reasoning_effort("false"), "false")
        # Unquoted, because `false` is the value the engine reads as "do not think" — a quoted
        # string is a different YAML node.
        self.assertEqual(self.config(), "agent:\n  reasoning_effort: false\n")
        self.assertNotIn('"false"', self.config())

    def test_every_disabled_spelling_is_written_as_the_canonical_one(self) -> None:
        for written in ("none", "disabled", "false", False):
            with self.subTest(written=written):
                (self.dir / "config.yaml").write_text("agent:\n  reasoning_effort: high\n")
                self.assertEqual(EngineProfile(self.dir).set_reasoning_effort(written), "false")
                self.assertEqual(
                    (self.dir / "config.yaml").read_text(),
                    "agent:\n  reasoning_effort: false\n",
                )

    def test_set_reasoning_effort_refuses_a_level_the_engine_would_ignore(self) -> None:
        for value in ("", "turbo", "Low", "off", "true", True, 7, None):
            with self.subTest(value=value):
                with self.assertRaises(SettingsError) as caught:
                    self.profile.set_reasoning_effort(value)
                self.assertEqual(caught.exception.code, "bad_value")
        self.assertEqual(self.config(), CONFIG)

    def test_set_reasoning_effort_refuses_a_shape_it_does_not_understand(self) -> None:
        bad = {
            "nested mapping": "agent:\n  reasoning_effort:\n    effort: low\n",
            "bare key": "agent:\n  reasoning_effort:\n",
            "flow mapping": "agent:\n  reasoning_effort: {level: low}\n",
            "value plus list": "agent:\n  reasoning_effort: low\n    - x\n",
            "duplicate key": "agent:\n  reasoning_effort: low\n  reasoning_effort: high\n",
            # A flow-mapped block cannot take a child line: YAML forbids it, so a write would
            # emit a broken config.yaml.
            "flow block header": "agent: {verbose: true}\n",
        }
        for name, text in bad.items():
            with self.subTest(shape=name):
                (self.dir / "config.yaml").write_text(text)
                profile = EngineProfile(self.dir)
                self.assertFalse(profile.reasoning_shape_ok())
                with self.assertRaises(SettingsError) as caught:
                    profile.set_reasoning_effort("low")
                self.assertEqual(caught.exception.code, "unexpected_shape")
                # The refusal is total: the file is exactly as it was, and nothing was backed up.
                self.assertEqual((self.dir / "config.yaml").read_text(), text)
                self.assertFalse((self.dir / "config.yaml.bak").exists())

    def test_a_flow_block_header_also_refuses_a_toolset_write(self) -> None:
        # The same shape, for the key this module already owned: inserting a child under a
        # flow-mapped `agent:` would have produced a file the engine cannot parse.
        text = "agent: {verbose: true}\n"
        (self.dir / "config.yaml").write_text(text)
        profile = EngineProfile(self.dir)
        self.assertFalse(profile.agent_shape_ok())
        with self.assertRaises(SettingsError) as caught:
            profile.set_disabled_toolsets(["web"])
        self.assertEqual(caught.exception.code, "unexpected_shape")
        self.assertEqual((self.dir / "config.yaml").read_text(), text)

    def test_a_reasoning_write_keeps_a_backup_and_leaves_a_reread_clean(self) -> None:
        self.profile.set_reasoning_effort("high")
        self.assertEqual((self.dir / "config.yaml.bak").read_text(), CONFIG)
        self.assertEqual(EngineProfile(self.dir).reasoning_effort(), "high")
        # And a second write replaces the line rather than adding another one.
        EngineProfile(self.dir).set_reasoning_effort("low")
        self.assertEqual(self.config().count("reasoning_effort"), 1)

    # -- skills.disabled ---------------------------------------------------

    def test_disabled_skills_reads_absent_as_empty(self) -> None:
        self.assertEqual(self.profile.disabled_skills(), [])
        self.assertTrue(self.profile.skills_shape_ok())

    def test_set_disabled_skills_creates_the_block_when_absent(self) -> None:
        self.profile.set_disabled_skills(["youtube-content"])
        self.assertEqual(
            self.config(), CONFIG + "\nskills:\n  disabled: [youtube-content]\n"
        )

    def test_set_disabled_skills_preserves_other_skills_keys(self) -> None:
        (self.dir / "config.yaml").write_text(
            "skills:\n  trusted_project_dirs: [x]\n  disabled: [a]\n"
        )
        self.profile.set_disabled_skills(["b"])
        self.assertEqual(
            self.config(), "skills:\n  trusted_project_dirs: [x]\n  disabled: [b]\n"
        )

    def test_skill_names_may_carry_hyphens_and_paths(self) -> None:
        # The engine matches a declared name or a `load_name` (`a/one`, `category:skill`).
        (self.dir / "config.yaml").write_text("skills:\n  disabled: []\n")
        self.assertEqual(
            self.profile.set_disabled_skills(["sdlc-review", "a/one", "plug:skill"]),
            ["a/one", "plug:skill", "sdlc-review"],
        )

    def test_an_essential_skill_is_refused_rather_than_written_and_ignored(self) -> None:
        with self.assertRaises(SettingsError) as caught:
            self.profile.set_disabled_skills(["hermes-agent"])
        self.assertEqual(caught.exception.code, "essential")
        self.assertEqual(self.config(), CONFIG)

    def test_set_disabled_skills_refuses_a_name_the_engine_would_ignore(self) -> None:
        for name in ("", "has space", "semi;colon", "with\nnewline"):
            with self.subTest(name=name):
                with self.assertRaises(SettingsError) as caught:
                    self.profile.set_disabled_skills([name])
                self.assertEqual(caught.exception.code, "bad_name")
        self.assertEqual(self.config(), CONFIG)

    def test_set_disabled_skills_refuses_a_shape_it_does_not_understand(self) -> None:
        text = "skills:\n  disabled:\n    nested: 1\n"
        (self.dir / "config.yaml").write_text(text)
        self.assertFalse(EngineProfile(self.dir).skills_shape_ok())
        with self.assertRaises(SettingsError) as caught:
            EngineProfile(self.dir).set_disabled_skills(["a"])
        self.assertEqual(caught.exception.code, "unexpected_shape")
        self.assertEqual((self.dir / "config.yaml").read_text(), text)

    def test_a_disabled_skills_shape_we_cannot_read_still_reports_the_list(self) -> None:
        # The read path is lenient (it only informs the UI); the write path is what refuses.
        (self.dir / "config.yaml").write_text("skills:\n  disabled: [a, b]\n")
        self.assertEqual(EngineProfile(self.dir).disabled_skills(), ["a", "b"])

    # -- toolset opt-ins ---------------------------------------------------

    def test_opted_in_toolsets_is_empty_when_the_file_names_none(self) -> None:
        self.assertEqual(self.profile.opted_in_toolsets(), set())

    def test_opted_in_toolsets_reads_toolsets_and_every_platform_list(self) -> None:
        (self.dir / "config.yaml").write_text(
            "toolsets: [kanban]\n"
            "platform_toolsets:\n"
            "  api_server: [hermes-api-server, web]\n"
            "  cli:\n"
            "    - kanban\n"
        )
        self.assertEqual(
            EngineProfile(self.dir).opted_in_toolsets(),
            {"kanban", "hermes-api-server", "web"},
        )

    # -- writing .env ------------------------------------------------------

    def test_set_key_writes_a_value_and_tightens_permissions(self) -> None:
        self.profile.set_key("OPENCODE_GO_API_KEY", SECRET)
        text = self.env()
        self.assertIn(f"OPENCODE_GO_API_KEY={SECRET}", text)
        self.assertEqual((self.dir / ".env").stat().st_mode & 0o777, 0o600)

    def test_set_key_collapses_a_duplicate_rather_than_leaving_a_stale_copy(self) -> None:
        (self.dir / ".env").write_text("FOO=stale\nBAR=keep\nFOO=stale-again\n")
        EngineProfile(self.dir).set_key("FOO", SECRET)
        text = self.env()
        self.assertEqual(text.count("FOO="), 1)
        self.assertIn(f"FOO={SECRET}", text)
        self.assertIn("BAR=keep", text)

    def test_set_key_appends_a_new_name(self) -> None:
        self.profile.set_key("ANTHROPIC_API_KEY", SECRET)
        self.assertTrue(self.profile.key_names()["ANTHROPIC_API_KEY"])
        self.assertTrue(self.profile.key_names()["API_SERVER_KEY"])
        self.assertIn("# a note between keys", self.env())

    def test_clear_key_removes_the_line_and_keeps_the_rest(self) -> None:
        self.profile.clear_key("OPENCODE_GO_API_KEY")
        text = self.env()
        self.assertNotIn("OPENCODE_GO_API_KEY", text)
        self.assertIn("API_SERVER_KEY=abc123", text)
        self.assertIn("# a note between keys", text)

    def test_clear_key_on_an_unset_name_is_a_refusal(self) -> None:
        with self.assertRaises(SettingsError) as caught:
            self.profile.clear_key("NOT_THERE")
        self.assertEqual(caught.exception.code, "not_set")

    def test_a_value_that_would_not_round_trip_is_refused(self) -> None:
        # `NAME= value` reads back as `value`, so a leading or trailing space would make the
        # key silently a different string (the internal audit BFF-12).
        for value in (" leading", "trailing ", " both "):
            with self.subTest(value=value):
                with self.assertRaises(SettingsError) as caught:
                    self.profile.set_key("FOO", value)
                self.assertEqual(caught.exception.code, "bad_value")
        self.assertNotIn("FOO", self.profile.key_names())

    def test_concurrent_writes_do_not_lose_one(self) -> None:
        # Every setter is read-modify-write over config.yaml. `ThreadingHTTPServer` can run two
        # at once, and without a lock the second rewrites from the state it read before the
        # first wrote, losing a change that was answered 200
        # (the internal audit BFF-11).
        import threading

        names = [f"KEY_{index}" for index in range(24)]
        start = threading.Barrier(len(names))
        profile = self.profile  # one profile, as the server has: the lock lives on it

        def write(name: str) -> None:
            start.wait()
            profile.set_key(name, "v")

        threads = [threading.Thread(target=write, args=(name,)) for name in names]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        present = set(self.profile.key_names())
        for name in names:
            with self.subTest(name=name):
                self.assertIn(name, present, "a concurrent write was lost")

    def test_refuses_a_name_the_engine_would_ignore(self) -> None:
        for name in ("", "1LEADING", "has space", "has-dash", "semi;colon"):
            with self.subTest(name=name):
                with self.assertRaises(SettingsError) as caught:
                    self.profile.set_key(name, SECRET)
                self.assertEqual(caught.exception.code, "bad_name")

    def test_refuses_a_value_that_would_break_the_file(self) -> None:
        for value in ("", "two\nlines", "carriage\rreturn"):
            with self.subTest(value=value):
                with self.assertRaises(SettingsError) as caught:
                    self.profile.set_key("SAFE_NAME", value)
                self.assertEqual(caught.exception.code, "bad_value")

    def test_reads_an_export_prefixed_line(self) -> None:
        (self.dir / ".env").write_text("export FOO=bar\n")
        self.assertTrue(EngineProfile(self.dir).key_names()["FOO"])

    def test_secret_reads_a_value_but_snapshot_never_carries_it(self) -> None:
        value = "ak_live_test_value"
        (self.dir / ".env").write_text(f"COMPOSIO_API_KEY={value}\n")
        profile = EngineProfile(self.dir)
        self.assertEqual(profile.secret("COMPOSIO_API_KEY"), value)
        self.assertEqual(profile.secret("NOT_SET"), "")
        self.assertNotIn(value, json.dumps(profile.snapshot()))


class BffSettingsTestCase(unittest.TestCase):
    """The routes the shell actually calls."""

    PACK = {
        "id": "example",
        "name": "Example",
        "records": [
            {
                "type": "note",
                "label": "Note",
                "plural": "Notes",
                "fields": [{"name": "title", "label": "Title"}],
            }
        ],
        "screens": [],
    }

    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        root = Path(self._dir.name)
        self.dir = root / "pantler"
        self.dir.mkdir()
        (self.dir / "config.yaml").write_text(CONFIG)
        (self.dir / ".env").write_text(ENV)
        self.store = Store(root / "records.db")
        self.registry = PackRegistry([pack_from_dict(self.PACK)])

    def tearDown(self) -> None:
        self.store.close()
        self._dir.cleanup()

    def bff(self, with_profile: bool = True) -> Bff:
        profile = EngineProfile(self.dir) if with_profile else None
        return Bff(self.store, self.registry, profile)

    def test_without_a_profile_settings_are_reported_unavailable(self) -> None:
        status, payload = self.bff(with_profile=False).settings({})
        self.assertEqual(status, 200)
        self.assertFalse(payload["available"])
        self.assertIn("--profile-dir", payload["reason"])

    def test_without_a_profile_a_write_is_refused(self) -> None:
        with self.assertRaises(ApiError) as caught:
            self.bff(with_profile=False).set_model({"body": {"default": "x"}})
        self.assertEqual(caught.exception.code, "settings_unavailable")

    def test_snapshot_carries_no_secret_value(self) -> None:
        bff = self.bff()
        bff.set_key({"name": "OPENCODE_GO_API_KEY", "body": {"value": SECRET}})
        _, payload = bff.settings({})
        # Assert on the whole payload, not a field: a new field cannot leak one quietly.
        self.assertNotIn(SECRET, json.dumps(payload))
        self.assertIn("OPENCODE_GO_API_KEY", json.dumps(payload))

    def test_a_write_marks_the_engine_as_needing_a_restart(self) -> None:
        bff = self.bff()
        _, before = bff.settings({})
        self.assertFalse(before["restart_required"])

        status, payload = bff.set_model({"body": {"default": "glm-5.3"}})
        self.assertEqual(status, 200)
        self.assertTrue(payload["restart_required"])

        _, after = bff.settings({})
        self.assertTrue(after["restart_required"])
        self.assertEqual(after["model"]["default"], "glm-5.3")

    def test_set_model_with_nothing_to_write_is_a_400(self) -> None:
        with self.assertRaises(ApiError) as caught:
            self.bff().set_model({"body": {}})
        self.assertEqual(caught.exception.code, "nothing_to_write")

    def test_set_model_ignores_a_null_rather_than_writing_it(self) -> None:
        _, payload = self.bff().set_model({"body": {"default": "glm-5.3", "provider": None}})
        self.assertEqual(payload["model"]["provider"], "opencode-go")

    def test_set_key_requires_a_string_value(self) -> None:
        with self.assertRaises(ApiError) as caught:
            self.bff().set_key({"name": "FOO", "body": {"value": 7}})
        self.assertEqual(caught.exception.code, "bad_body")

    def test_clear_key_maps_not_set_to_a_404(self) -> None:
        with self.assertRaises(ApiError) as caught:
            self.bff().clear_key({"name": "NOT_THERE"})
        self.assertEqual(caught.exception.code, "not_set")
        self.assertEqual(caught.exception.status, 404)


    def test_set_disabled_toolsets_round_trips(self) -> None:
        bff = self.bff()
        status, payload = bff.set_disabled_toolsets({"body": {"disabled_toolsets": ["browser"]}})
        self.assertEqual(status, 200)
        self.assertEqual(payload["disabled_toolsets"], ["browser"])
        self.assertEqual(payload["applies_to"], "new_conversations")

        _, snapshot = bff.settings({})
        self.assertEqual(snapshot["disabled_toolsets"], ["browser"])
        self.assertTrue(snapshot["profile"]["agent_editable"])

    def test_a_toolset_write_does_not_claim_a_restart_is_needed(self) -> None:
        # The engine re-reads config.yaml when it builds an agent, so this one is live on the
        # next conversation. Saying "restart required" here would be the wrong half of honest.
        bff = self.bff()
        _, payload = bff.set_disabled_toolsets({"body": {"disabled_toolsets": ["browser"]}})
        self.assertNotIn("restart_required", payload)
        _, snapshot = bff.settings({})
        self.assertFalse(snapshot["restart_required"])

    def test_set_disabled_toolsets_requires_a_list(self) -> None:
        for body in ({}, {"disabled_toolsets": "browser"}, {"disabled_toolsets": None}):
            with self.subTest(body=body):
                with self.assertRaises(ApiError) as caught:
                    self.bff().set_disabled_toolsets({"body": body})
                self.assertEqual(caught.exception.code, "bad_body")

    def test_set_disabled_toolsets_refuses_a_bad_name_as_a_422(self) -> None:
        with self.assertRaises(ApiError) as caught:
            self.bff().set_disabled_toolsets({"body": {"disabled_toolsets": ["has space"]}})
        self.assertEqual(caught.exception.status, 422)
        self.assertEqual(caught.exception.code, "bad_name")

    def test_without_a_profile_a_toolset_write_is_refused(self) -> None:
        with self.assertRaises(ApiError) as caught:
            self.bff(with_profile=False).set_disabled_toolsets(
                {"body": {"disabled_toolsets": ["browser"]}}
            )
        self.assertEqual(caught.exception.code, "settings_unavailable")

    # -- agent.reasoning_effort -------------------------------------------

    def test_set_reasoning_effort_round_trips(self) -> None:
        bff = self.bff()
        status, payload = bff.set_reasoning_effort({"body": {"reasoning_effort": "low"}})
        self.assertEqual(status, 200)
        self.assertEqual(payload["reasoning_effort"], "low")
        self.assertEqual(payload["applies_to"], "new_conversations")

        _, snapshot = bff.settings({})
        self.assertEqual(snapshot["reasoning_effort"], "low")
        self.assertTrue(snapshot["profile"]["reasoning_editable"])

    def test_a_reasoning_write_does_not_claim_a_restart_is_needed(self) -> None:
        # The level lives in the `agent:` block, which the engine re-reads when it builds an
        # agent. Saying "restart required" here would be the wrong half of honest — and the
        # model write, which really does wait for a restart, still says so.
        bff = self.bff()
        _, payload = bff.set_reasoning_effort({"body": {"reasoning_effort": "high"}})
        self.assertNotIn("restart_required", payload)
        _, snapshot = bff.settings({})
        self.assertFalse(snapshot["restart_required"])

    def test_set_reasoning_effort_accepts_json_false_as_the_disabled_choice(self) -> None:
        bff = self.bff()
        status, payload = bff.set_reasoning_effort({"body": {"reasoning_effort": False}})
        self.assertEqual(status, 200)
        self.assertEqual(payload["reasoning_effort"], "false")
        self.assertEqual(bff.settings({})[1]["reasoning_effort"], "false")

    def test_set_reasoning_effort_requires_a_string_or_false(self) -> None:
        for body in ({}, {"reasoning_effort": None}, {"reasoning_effort": True},
                     {"reasoning_effort": 7}, {"reasoning_effort": ["low"]}):
            with self.subTest(body=body):
                with self.assertRaises(ApiError) as caught:
                    self.bff().set_reasoning_effort({"body": body})
                self.assertEqual(caught.exception.code, "bad_body")
                self.assertEqual(caught.exception.status, 400)

    def test_set_reasoning_effort_refuses_an_unknown_level_as_a_422(self) -> None:
        with self.assertRaises(ApiError) as caught:
            self.bff().set_reasoning_effort({"body": {"reasoning_effort": "turbo"}})
        self.assertEqual(caught.exception.status, 422)
        self.assertEqual(caught.exception.code, "bad_value")
        # And the refusal told the operator the vocabulary rather than just saying no.
        self.assertIn("minimal", caught.exception.message)

    def test_without_a_profile_a_reasoning_write_is_refused(self) -> None:
        with self.assertRaises(ApiError) as caught:
            self.bff(with_profile=False).set_reasoning_effort(
                {"body": {"reasoning_effort": "low"}}
            )
        self.assertEqual(caught.exception.code, "settings_unavailable")

    def test_the_reasoning_route_is_wired_to_its_handler(self) -> None:
        # The route table is the one part of a settings write no other test touches: a typo in
        # the path or the handler name would only show up as a 404 in a browser.
        from pantler_server import ROUTES

        matches = [
            route
            for route in ROUTES
            if route.method == "PUT" and route.regex.match("/api/settings/reasoning")
        ]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].handler, "set_reasoning_effort")
        self.assertTrue(matches[0].writes, "a settings write must be loopback-only")
        self.assertTrue(hasattr(self.bff(), matches[0].handler))

    def test_a_reasoning_payload_carries_no_secret(self) -> None:
        bff = self.bff()
        bff.set_key({"name": "OPENCODE_GO_API_KEY", "body": {"value": SECRET}})
        _, written = bff.set_reasoning_effort({"body": {"reasoning_effort": "max"}})
        _, snapshot = bff.settings({})
        # The whole serialised payloads, not a field: a new field cannot leak one quietly.
        self.assertNotIn(SECRET, json.dumps(written))
        self.assertNotIn(SECRET, json.dumps(snapshot))
        self.assertEqual(snapshot["reasoning_effort"], "max")

    def test_set_disabled_skills_round_trips(self) -> None:
        bff = self.bff()
        status, payload = bff.set_disabled_skills(
            {"body": {"disabled_skills": ["youtube-content"]}}
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["disabled_skills"], ["youtube-content"])
        self.assertEqual(payload["applies_to"], "new_conversations")

        _, snapshot = bff.settings({})
        self.assertEqual(snapshot["disabled_skills"], ["youtube-content"])
        self.assertTrue(snapshot["profile"]["skills_editable"])

    def test_set_disabled_skills_requires_a_list(self) -> None:
        for body in ({}, {"disabled_skills": "youtube-content"}, {"disabled_skills": None}):
            with self.subTest(body=body):
                with self.assertRaises(ApiError) as caught:
                    self.bff().set_disabled_skills({"body": body})
                self.assertEqual(caught.exception.code, "bad_body")

    def test_set_disabled_skills_maps_an_essential_skill_to_a_422(self) -> None:
        with self.assertRaises(ApiError) as caught:
            self.bff().set_disabled_skills({"body": {"disabled_skills": ["hermes-agent"]}})
        self.assertEqual(caught.exception.status, 422)
        self.assertEqual(caught.exception.code, "essential")


if __name__ == "__main__":
    unittest.main()


# ------------------------------------ A19-CFG-1 · names that steer the engine's own execution


class EnvNameGuardTest(ProfileTestCase):
    """The `.env` writer refuses what the engine's own writer refuses.

    Hermes keeps a denylist of names whose effect is execution rather than configuration; this
    module writes the same file, so it needs the same half of the guard
    (the internal security audit A19-CFG-1).
    """

    def test_a_name_that_steers_execution_is_refused(self) -> None:
        for name in (
            "PYTHONPATH",
            "LD_PRELOAD",
            "LD_LIBRARY_PATH",
            "NODE_OPTIONS",
            "PATH",
            "EDITOR",
            "HERMES_HOME",
            "HERMES_YOLO_MODE",
            "DYLD_INSERT_LIBRARIES",
            "GIT_CONFIG_VALUE_1",
            "BASH_ENV",
        ):
            with self.subTest(name=name):
                with self.assertRaises(SettingsError) as caught:
                    self.profile.set_key(name, "1")
                self.assertEqual(caught.exception.code, "bad_name")
                self.assertNotIn(name, self.env())

    def test_an_ordinary_key_still_writes(self) -> None:
        self.profile.set_key("PANTRY_API_KEY", "value")
        self.assertIn("PANTRY_API_KEY=value", self.env())
        self.assertTrue(self.profile.key_names()["PANTRY_API_KEY"])

    def test_clearing_a_denied_name_is_refused_too(self) -> None:
        with self.assertRaises(SettingsError):
            self.profile.clear_key("PYTHONPATH")

    def test_the_mirrored_denylist_matches_the_engines_own_when_it_is_present(self) -> None:
        # The list is copied from the engine at the pin, and a re-pin may grow it. When the
        # engine source is on this machine, compare the two sets so a new name cannot slip
        # through unnoticed.
        engine = Path("/home/you/.hermes/hermes-agent/hermes_cli/config.py")
        if not engine.is_file():
            self.skipTest("the engine source is not present on this machine")
        import re
        from engine_settings import ENV_NAME_DENYLIST, ENV_NAME_DENY_PREFIXES

        text = engine.read_text(encoding="utf-8")
        block = re.search(r"_ENV_VAR_NAME_DENYLIST[^=]*=\s*frozenset\(\{(.*?)\}\)", text, re.S)
        if block is None:
            self.skipTest("the engine's denylist is not where this test expects it")
        theirs = {name.upper() for name in re.findall(r'"([^"]+)"', block.group(1))}
        self.assertEqual(theirs - ENV_NAME_DENYLIST, set())
        prefixes = re.search(r"_ENV_VAR_NAME_DENY_PREFIXES[^=]*=\s*\((.*?)\)", text, re.S)
        if prefixes is not None:
            self.assertEqual(
                {name for name in re.findall(r'"([^"]+)"', prefixes.group(1))}
                - set(ENV_NAME_DENY_PREFIXES),
                set(),
            )


class EnvValueGuardTest(ProfileTestCase):
    """A value that would not survive the engine's reader is refused, not stored."""

    def test_a_value_that_would_split_into_two_assignments_is_refused(self) -> None:
        # `str.splitlines()` — which the engine's secret scope tokenises with — also splits on a
        # vertical tab, a form feed, NEL, and U+2028/2029 (A19-CFG-3).
        for separator in ("\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"):
            with self.subTest(separator=repr(separator)):
                with self.assertRaises(SettingsError) as caught:
                    self.profile.set_key("OPENCODE_GO_API_KEY", f"benign{separator}PATH=evil")
                self.assertEqual(caught.exception.code, "bad_value")
        self.assertNotIn("PATH=evil", self.env())

    def test_a_comment_or_a_quote_the_engine_would_strip_is_refused(self) -> None:
        for value in ("abc #not-a-comment", '"quoted-secret"', "'single-quoted'"):
            with self.subTest(value=value):
                with self.assertRaises(SettingsError) as caught:
                    self.profile.set_key("PANTRY_API_KEY", value)
                self.assertEqual(caught.exception.code, "bad_value")

    def test_an_ordinary_secret_still_writes(self) -> None:
        self.profile.set_key("PANTRY_API_KEY", "sk-abc-123")
        self.assertIn("PANTRY_API_KEY=sk-abc-123", self.env())


# ------------------------------------------- A19-CFG-2 · YAML that a parser can read back


class ScalarRenderTest(unittest.TestCase):
    """Values that used to break the file or change its meaning are quoted now."""

    def test_the_values_that_broke_the_file_are_quoted(self) -> None:
        from engine_settings import _scalar

        for value in ("@evil", "`tick", "x:", ":", "-", "?", ",", "#hash", "&anchor", "*alias"):
            with self.subTest(value=value):
                rendered = _scalar(value)
                self.assertTrue(rendered.startswith('"') and rendered.endswith('"'), rendered)

    def test_the_words_yaml_reads_as_something_else_are_quoted(self) -> None:
        from engine_settings import _scalar

        for value in ("off", "ON", "no", "true", "false", "null", "~", "123", "1e5", ".inf"):
            with self.subTest(value=value):
                self.assertTrue(_scalar(value).startswith('"'), value)

    def test_an_ordinary_value_is_still_written_bare(self) -> None:
        from engine_settings import _scalar

        self.assertEqual(_scalar("opencode-go"), "opencode-go")
        self.assertEqual(_scalar("https://opencode.ai/zen/go/v1"), "https://opencode.ai/zen/go/v1")

    def test_a_control_character_is_refused_rather_than_written(self) -> None:
        from engine_settings import _scalar

        with self.assertRaises(SettingsError):
            _scalar("a\x00b")

    def test_the_disabled_reasoning_level_is_still_a_yaml_boolean(self) -> None:
        # `agent.reasoning_effort: false` is the engine's own spelling for "do not think"; it is
        # written literally on purpose, and every other value in the vocabulary is validated.
        from engine_settings import _scalar_literal

        self.assertEqual(_scalar_literal("false"), "false")
        self.assertEqual(_scalar_literal("low"), "low")


class ScalarWriteTest(ProfileTestCase):
    def test_a_model_value_that_used_to_break_the_file_round_trips(self) -> None:
        self.profile.set_model({"provider": "@evil"})
        self.assertEqual(self.profile.model()["provider"], "@evil")
        self.assertIn('provider: "@evil"', self.config())

    def test_a_value_that_used_to_be_a_boolean_round_trips_as_a_string(self) -> None:
        self.profile.set_model({"default": "off"})
        self.assertEqual(self.profile.model()["default"], "off")
        self.assertIn('default: "off"', self.config())


# ------------------------------------------------ A19-CFG-6 · the backup is a credential too


class BackupTest(ProfileTestCase):
    def test_the_backup_of_the_env_file_is_private(self) -> None:
        import os

        os.chmod(self.dir / ".env", 0o644)
        self.profile.set_key("PANTRY_API_KEY", "value")
        mode = (self.dir / ".env.bak").stat().st_mode & 0o777
        self.assertEqual(mode, 0o600)
        self.assertIn("API_SERVER_KEY=abc123", (self.dir / ".env.bak").read_text())

    def test_a_planted_symlink_is_not_written_through(self) -> None:
        outside = Path(self._dir.name) / "outside.txt"
        outside.write_text("ORIGINAL")
        (self.dir / ".env.bak").symlink_to(outside)
        with self.assertRaises(SettingsError) as caught:
            self.profile.set_key("PANTRY_API_KEY", "value")
        self.assertEqual(caught.exception.code, "bad_backup")
        self.assertEqual(outside.read_text(), "ORIGINAL")


# ------------------------------------------------- A19-CFG-4/CFG-5 · shapes and lost updates


class WriteShapeTest(ProfileTestCase):
    def test_a_flow_mapping_parent_is_refused_rather_than_broken(self) -> None:
        (self.dir / "config.yaml").write_text(
            "plugins:\n  entries: {pantler: {settings: {capability_enabled: true}}}\n"
        )
        with self.assertRaises(SettingsError) as caught:
            EngineProfile(self.dir).set_plugin_enabled("pantler", False)
        self.assertEqual(caught.exception.code, "bad_shape")
        # And the file is untouched.
        self.assertIn("entries: {pantler:", (self.dir / "config.yaml").read_text())

    def test_concurrent_switches_do_not_lose_each_other(self) -> None:
        import threading

        names = [f"skill-{index}" for index in range(12)]
        errors: list[BaseException] = []

        def flip(name: str) -> None:
            try:
                self.profile.update_disabled_skills(name, False)
            except BaseException as exc:  # noqa: BLE001 - reported below
                errors.append(exc)

        threads = [threading.Thread(target=flip, args=(name,)) for name in names]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(sorted(self.profile.disabled_skills()), sorted(names))

    def test_a_toolset_toggle_reads_and_writes_under_one_lock(self) -> None:
        self.profile.set_disabled_toolsets(["browser", "terminal"])
        self.profile.update_disabled_toolsets("browser", True)
        self.assertEqual(self.profile.disabled_toolsets(), ["terminal"])
