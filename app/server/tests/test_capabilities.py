"""Tests for the capability registry and its one write path.

Two things are being protected, and only one of them is functionality.

1. **The read model cannot lie.** A row says whether a switch exists, when it takes effect, and
   what a capability needs; every one of those is derived from a file the engine itself reads.
   A row that guessed would be worse than no screen, because the operator would trust it.
2. **A write touches one decision and nothing else.** `config.yaml` is the operator's, and the
   plugin lists are a *pair*: an entry left in both would make a plugin's state depend on which
   reader asked.

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

from capabilities import load_capabilities, parse_manifest  # noqa: E402
from engine_settings import EngineProfile, SettingsError  # noqa: E402
from pantler_core import PackRegistry, Store  # noqa: E402
from pantler_server import ApiError, Bff  # noqa: E402

CONFIG = """\
# the operator's file
model:
  provider: opencode-go
approvals:
  mode: manual
plugins:
  enabled: [pantler]
  entries:
    pantler:
      pricebook_path: /tmp/pricebook.json
mcp_servers:
  notion:
    url: https://mcp.notion.com/mcp
  airtable:
    enabled: false
tools:
  connectors:
    enabled: false
skills:
  disabled: [xurl]
"""

PLUGIN_YAML = """\
name: pantler
version: 0.0.1
description: pantler's own tools
author: pantler
license: MIT
requires_env: [PANTRY_API_KEY]
config_schema:
  profile:
    type: str
    default: default
provides_tools:
  - invoice_create
  - invoice_show
"""

SKILL = """\
---
name: invoicing
description: Draft an invoice from the price book.
metadata:
  category: pantler
---

Body.
"""


class RegistryTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.dir = Path(self._dir.name) / "pantler"
        self.dir.mkdir(parents=True)
        (self.dir / "config.yaml").write_text(CONFIG)
        (self.dir / "plugins" / "pantler").mkdir(parents=True)
        (self.dir / "plugins" / "pantler" / "plugin.yaml").write_text(PLUGIN_YAML)
        self.write("skills/invoicing/SKILL.md", SKILL)
        self.profile = EngineProfile(self.dir)

    def tearDown(self) -> None:
        self._dir.cleanup()

    def write(self, relative: str, text: str) -> None:
        path = self.dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def config(self) -> str:
        return (self.dir / "config.yaml").read_text()

    def by_id(self, identifier: str) -> dict:
        rows = {row["id"]: row for row in load_capabilities(self.profile)["data"]}
        self.assertIn(identifier, rows)
        return rows[identifier]

    # -- plugin config ------------------------------------------------------------------

    def test_plugin_states_read_both_lists_and_disabled_wins(self) -> None:
        self.write(
            "config.yaml",
            "plugins:\n  enabled: [pantler, soil-amendment]\n  disabled: [soil-amendment]\n",
        )
        self.assertEqual(
            self.profile.plugin_states(), {"pantler": True, "soil-amendment": False}
        )

    def test_disable_moves_a_plugin_between_the_lists_and_preserves_the_file(self) -> None:
        self.profile.set_plugin_enabled("pantler", False)
        text = self.config()
        self.assertIn("# the operator's file", text)
        self.assertIn("entries:\n    pantler:\n      pricebook_path", text)
        self.assertIn("disabled: [pantler]", text)
        self.assertIn("enabled: []", text)
        self.assertEqual(self.profile.plugin_states(), {"pantler": False})

    def test_enable_moves_it_back(self) -> None:
        self.profile.set_plugin_enabled("pantler", False)
        self.profile.set_plugin_enabled("pantler", True)
        self.assertIn("enabled: [pantler]", self.config())
        self.assertIn("disabled: []", self.config())
        self.assertEqual(self.profile.plugin_states(), {"pantler": True})

    def test_plugin_names_are_validated(self) -> None:
        for bad in ("", "has space", "../escape", 7):
            with self.assertRaises(SettingsError):
                self.profile.set_plugin_enabled(bad, True)  # type: ignore[arg-type]

    def test_a_scalar_requires_env_is_one_credential_not_seven(self) -> None:
        # `parse_manifest` returns a scalar as a string, so `requires_env: PANTRY_API_KEY`
        # used to be iterated character by character
        # (the internal audit BFF-9).
        self.write(
            "plugins/scalar/plugin.yaml",
            "name: scalar\nprovides_tools: [a]\nrequires_env: PANTRY_API_KEY\n",
        )
        row = self.by_id("plugin:scalar")
        self.assertEqual(row["needs"], ["credential:PANTRY_API_KEY"])

    def test_a_kanban_skill_is_listed_where_the_skills_index_lists_it(self) -> None:
        # `/api/capabilities` used to load skills without the kanban environment, so a skill
        # the skills index offered was missing from the registry — a switch the operator could
        # see and not flip (the internal audit BFF-8).
        from skills_index import load_skills

        self.write(
            "skills/board/SKILL.md",
            "---\nname: board\ndescription: The kanban board.\nenvironments:\n  - kanban\n---\n",
        )
        without = {row["name"] for row in load_capabilities(self.profile)["data"] if row["kind"] == "skill"}
        with_kanban = {
            row["name"]
            for row in load_capabilities(self.profile, {"kanban"})["data"]
            if row["kind"] == "skill"
        }
        self.assertNotIn("board", without)
        self.assertIn("board", with_kanban)
        # And the two readers agree, which is the point: one loader, one answer.
        index = {
            skill["name"]
            for skill in load_skills(self.dir, [], active_environments={"kanban"})
        }
        self.assertEqual(with_kanban, index - {"hermes-agent"})

    # -- mcp servers --------------------------------------------------------------------

    def test_mcp_servers_read_nested_enabled_and_treat_absence_as_on(self) -> None:
        self.assertEqual(self.profile.mcp_servers(), {"notion": True, "airtable": False})

    def test_mcp_write_flips_only_that_line(self) -> None:
        self.profile.set_mcp_server_enabled("notion", False)
        text = self.config()
        self.assertIn("  notion:\n    url: https://mcp.notion.com/mcp\n    enabled: false", text)
        self.assertEqual(self.profile.mcp_servers(), {"notion": False, "airtable": False})

    def test_mcp_write_refuses_a_server_that_is_not_configured(self) -> None:
        with self.assertRaises(SettingsError) as caught:
            self.profile.set_mcp_server_enabled("stripe", True)
        self.assertEqual(caught.exception.code, "not_found")
        self.assertNotIn("stripe", self.config())

    def test_mcp_write_refuses_when_there_is_no_mcp_block(self) -> None:
        self.write("config.yaml", "model:\n  provider: a\n")
        profile = EngineProfile(self.dir)
        with self.assertRaises(SettingsError):
            profile.set_mcp_server_enabled("notion", True)

    def test_connectors_flag_reads_and_absent_is_none(self) -> None:
        self.assertFalse(self.profile.connectors_enabled())
        self.write("config.yaml", "model:\n  provider: a\n")
        self.assertIsNone(EngineProfile(self.dir).connectors_enabled())

    # -- the registry -------------------------------------------------------------------

    def test_a_skill_row_carries_the_switch_and_the_honesty(self) -> None:
        row = self.by_id("skill:invoicing")
        self.assertEqual(row["kind"], "skill")
        self.assertEqual(row["name"], "invoicing")
        self.assertEqual(row["group"], "pantler")
        self.assertTrue(row["enabled"])
        self.assertEqual(row["applied_at"], "new_conversations")
        self.assertTrue(row["toggleable"])

    def test_a_disabled_skill_is_listed_as_off_not_dropped(self) -> None:
        self.write("skills/other/SKILL.md", SKILL.replace("invoicing", "other"))
        self.profile.set_disabled_skills(["other"])
        self.assertFalse(self.by_id("skill:other")["enabled"])

    def test_skill_provenance_distinguishes_shipped_bundled_and_local(self) -> None:
        self.write("distribution.yaml", "name: pantler\ndistribution_owned:\n  - skills/invoicing\n")
        self.write("skills/.bundled_manifest", "xurl:abc\n")
        self.write("skills/xurl/SKILL.md", SKILL.replace("invoicing", "xurl"))
        self.write("skills/mine/SKILL.md", SKILL.replace("invoicing", "mine"))
        self.assertEqual(self.by_id("skill:invoicing")["provenance"], "shipped")
        self.assertEqual(self.by_id("skill:xurl")["provenance"], "bundled")
        self.assertEqual(self.by_id("skill:mine")["provenance"], "local")

    def test_the_engine_skill_is_never_listed(self) -> None:
        self.write("skills/hermes-agent/SKILL.md", SKILL.replace("invoicing", "hermes-agent"))
        identifiers = {row["id"] for row in load_capabilities(self.profile)["data"]}
        self.assertNotIn("skill:hermes-agent", identifiers)

    def test_a_plugin_row_reads_label_needs_and_restart_honesty(self) -> None:
        row = self.by_id("plugin:pantler")
        self.assertEqual(row["label"], "pantler")
        self.assertEqual(row["needs"], ["credential:PANTRY_API_KEY"])
        self.assertTrue(row["enabled"])
        self.assertEqual(row["applied_at"], "next_restart")

    def test_an_unlisted_plugin_is_reported_off(self) -> None:
        self.write("config.yaml", "model:\n  provider: a\n")
        self.assertFalse(self.by_id("plugin:pantler")["enabled"])

    def test_mcp_rows_and_a_connector_row_that_refuses_to_pretend(self) -> None:
        self.assertEqual(self.by_id("mcp_server:airtable")["enabled"], False)
        self.assertEqual(self.by_id("mcp_server:airtable")["applied_at"], "next_restart")
        connector = self.by_id("connector:composio")
        self.assertFalse(connector["toggleable"])
        self.assertTrue(connector["reason"])


    def test_a_plugin_switched_off_live_reads_as_off(self) -> None:
        """The engine's list still names it, but the plugin itself would refuse."""
        self.profile.set_plugin_enabled("pantler", False)
        self.profile.set_plugin_enabled("pantler", True)
        self.write(
            "config.yaml",
            self.config().replace("capability_enabled: true", "capability_enabled: false"),
        )
        profile = EngineProfile(self.dir)
        states = {row["name"]: row["enabled"] for row in load_capabilities(profile)["data"]}
        self.assertFalse(states["pantler"])

    # -- manifest reading ---------------------------------------------------------------

    def test_parse_manifest_handles_the_shapes_the_engine_writes(self) -> None:
        parsed = parse_manifest(PLUGIN_YAML)
        self.assertEqual(parsed["name"], "pantler")
        self.assertEqual(parsed["license"], "MIT")
        self.assertEqual(parsed["requires_env"], ["PANTRY_API_KEY"])
        self.assertEqual(parsed["provides_tools"], ["invoice_create", "invoice_show"])
        # A nested mapping is not ours to read, and reading it must not corrupt the scalars.
        self.assertNotIn("profile", parsed)

    def test_parse_manifest_survives_a_folded_description_and_quotes(self) -> None:
        parsed = parse_manifest(
            'name: "quoted"\ndescription: >-\n  a folded line\nrequires_auth: true\n'
        )
        self.assertEqual(parsed["name"], "quoted")
        self.assertEqual(parsed["description"], "")
        self.assertEqual(parsed["requires_auth"], "true")


class CapabilityRouteTestCase(RegistryTestCase):
    """The same fixture, driven through the BFF's handlers rather than the modules."""

    def setUp(self) -> None:
        super().setUp()
        self.store = Store(":memory:")
        self.bff = Bff(self.store, PackRegistry([]), profile=self.profile)

    def test_without_a_profile_the_route_answers_available_false(self) -> None:
        bff = Bff(self.store, PackRegistry([]))
        status, payload = bff.list_capabilities({})
        self.assertEqual(status, 200)
        self.assertFalse(payload["available"])
        self.assertEqual(payload["data"], [])

    def test_the_route_serves_the_registry(self) -> None:
        status, payload = self.bff.list_capabilities({})
        self.assertEqual(status, 200)
        self.assertTrue(payload["available"])
        kinds = {row["kind"] for row in payload["data"]}
        self.assertEqual(kinds, {"skill", "plugin", "mcp_server", "connector"})

    def test_switching_a_skill_off_writes_the_engine_list(self) -> None:
        status, payload = self.bff.set_capability(
            {"id": "skill:invoicing", "body": {"enabled": False}}
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["applies_to"], "new_conversations")
        self.assertEqual(self.profile.disabled_skills(), ["invoicing", "xurl"])
        # …and back on again, without duplicating the entry.
        self.bff.set_capability({"id": "skill:invoicing", "body": {"enabled": True}})
        self.assertEqual(self.profile.disabled_skills(), ["xurl"])

    def test_a_skill_this_profile_does_not_hold_is_refused(self) -> None:
        with self.assertRaises(ApiError) as caught:
            self.bff.set_capability({"id": "skill:nope", "body": {"enabled": False}})
        self.assertEqual(caught.exception.status, 404)
        self.assertNotIn("nope", self.config())

    def test_a_plugin_this_profile_does_not_hold_is_refused(self) -> None:
        # The skill path had this guard and the plugin path did not, so
        # `PUT /api/capabilities/plugin:anything` wrote the name into `plugins.enabled` and
        # answered 200 for a plugin that does not exist
        # (the internal audit BFF-2).
        with self.assertRaises(ApiError) as caught:
            self.bff.set_capability({"id": "plugin:nope", "body": {"enabled": True}})
        self.assertEqual(caught.exception.status, 404)
        self.assertNotIn("nope", self.config())

    def test_an_mcp_server_this_profile_does_not_hold_is_refused_with_404(self) -> None:
        """The third kind, and the one whose refusal came back as 422.

        `set_mcp_server_enabled` raises `SettingsError("not_found")`, and the capability route
        mapped every `SettingsError` to 422 — so the README's "a name the profile does not hold
        is a 404 before anything is written" was false for exactly this kind
        (the internal audit DOC-1).
        """
        with self.assertRaises(ApiError) as caught:
            self.bff.set_capability({"id": "mcp_server:stripe", "body": {"enabled": True}})
        self.assertEqual(caught.exception.status, 404)
        self.assertNotIn("stripe", self.config())

    def test_a_plugin_switch_says_restart(self) -> None:
        status, payload = self.bff.set_capability(
            {"id": "plugin:pantler", "body": {"enabled": False}}
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["applies_to"], "next_restart")

    def test_every_id_the_registry_serves_is_one_the_write_path_accepts(self) -> None:
        """The two halves of the registry must agree on how a row is named.

        This is the test that would have caught an id prefix disagreeing with its kind: the
        row could be listed and never switched, and each side's own tests would still pass.
        """
        _, payload = self.bff.list_capabilities({})
        for row in payload["data"]:
            kind, _, name = row["id"].partition(":")
            self.assertEqual(kind, row["kind"], row["id"])
            self.assertTrue(name, row["id"])
            # Every toggleable row must survive a round trip through the writer.
            if not row["toggleable"]:
                continue
            status, answer = self.bff.set_capability(
                {"id": row["id"], "body": {"enabled": row["enabled"]}}
            )
            self.assertEqual(status, 200, row["id"])
            self.assertEqual(answer["id"], row["id"])

    def test_an_mcp_server_switch_round_trips(self) -> None:
        status, payload = self.bff.set_capability(
            {"id": "mcp_server:notion", "body": {"enabled": False}}
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["applies_to"], "next_restart")
        self.assertFalse(self.profile.mcp_servers()["notion"])

    def test_a_connector_switch_is_refused_rather_than_faked(self) -> None:
        with self.assertRaises(ApiError) as caught:
            self.bff.set_capability({"id": "connector:composio", "body": {"enabled": False}})
        self.assertEqual(caught.exception.status, 409)

    def test_the_body_and_the_id_are_validated(self) -> None:
        with self.assertRaises(ApiError):
            self.bff.set_capability({"id": "skill:invoicing", "body": {"enabled": "yes"}})
        with self.assertRaises(ApiError):
            self.bff.set_capability({"id": "invoicing", "body": {"enabled": True}})
        with self.assertRaises(ApiError):
            self.bff.set_capability({"id": "nonsense:thing", "body": {"enabled": True}})


class LiveFlagTestCase(RegistryTestCase):
    """The live half of a plugin switch, written into the plugin's own settings subtree.

    The engine's plugin list needs a restart, so on its own it leaves a registered tool callable
    in a conversation that is already open. `plugins.entries.<id>.settings.capability_enabled` is
    what the handler reads on every call, and it has to be created for a plugin whose `entries`
    block has never existed — a fresh install has no `settings:` anywhere.
    """

    def test_the_flag_lands_in_the_plugins_own_settings(self) -> None:
        self.profile.set_plugin_enabled("pantler", False)
        text = self.config()
        self.assertIn("    pantler:\n", text)
        self.assertIn("      settings:\n        capability_enabled: false", text)
        self.assertIn("pricebook_path", text)

    def test_the_flag_is_created_for_a_plugin_with_no_entry_block(self) -> None:
        self.profile.set_plugin_enabled("soil-amendment", False)
        text = self.config()
        self.assertIn("    soil-amendment:\n      settings:\n        capability_enabled: false", text)

    def test_an_existing_settings_block_keeps_its_own_keys(self) -> None:
        self.write(
            "config.yaml",
            "plugins:\n  enabled: [pantler]\n  entries:\n    pantler:\n"
            "      settings:\n        existing: keep-me\n",
        )
        profile = EngineProfile(self.dir)
        profile.set_plugin_enabled("pantler", False)
        text = (self.dir / "config.yaml").read_text()
        self.assertIn("existing: keep-me", text)
        self.assertIn("capability_enabled: false", text)

    def test_the_flag_round_trips_without_duplicating(self) -> None:
        self.profile.set_plugin_enabled("pantler", False)
        self.profile.set_plugin_enabled("pantler", True)
        text = self.config()
        self.assertEqual(text.count("capability_enabled"), 1)
        self.assertIn("capability_enabled: true", text)

    def test_a_setting_is_read_from_inside_its_own_block_only(self) -> None:
        # `plugin_setting` used to read one line past the settings block, so a *sibling* key
        # of the same name came back as if it were inside — while `plugin_capability_flags`,
        # the other reader of that key, correctly said there was none
        # (the internal audit BFF-10). Two readers of one key must not disagree.
        self.write(
            "config.yaml",
            "plugins:\n  enabled: [pantler]\n  entries:\n    pantler:\n"
            "      settings:\n      capability_enabled: false\n",
        )
        profile = EngineProfile(self.dir)
        self.assertEqual(profile.plugin_setting("pantler", "capability_enabled"), "")
        self.assertEqual(profile.plugin_capability_flags(), {})

    def test_a_setting_inside_the_block_is_still_read(self) -> None:
        self.write(
            "config.yaml",
            "plugins:\n  enabled: [pantler]\n  entries:\n    pantler:\n"
            "      settings:\n        capability_enabled: false\n",
        )
        profile = EngineProfile(self.dir)
        self.assertEqual(profile.plugin_setting("pantler", "capability_enabled"), "false")
        self.assertEqual(profile.plugin_capability_flags(), {"pantler": False})


if __name__ == "__main__":
    unittest.main()


class EscapeHatchTestCase(CapabilityRouteTestCase):
    """Turning a powerful capability back on is not the same act as turning one off.

    `browser`, `terminal`, `code_execution`, `computer_use`, `image_gen` and `delegation` run code,
    reach any page or drive the machine. They ship enabled — since 2026-10-19
    `distribution/config.yaml` suppresses nothing — and the guard is about the *switch*: re-enabling
    one after the operator turned it off is a deliberate act rather than an accidental toggle, so it
    needs the write token when the deployment configured one
    (the internal security audit A19-CFG-8).
    """

    def test_disabling_an_escape_hatch_needs_no_token(self) -> None:
        status, payload = self.bff.set_capability(
            {"id": "toolset:terminal", "body": {"enabled": False}}
        )
        self.assertEqual(status, 200)
        self.assertIn("terminal", self.profile.disabled_toolsets())

    def test_enabling_one_with_no_token_configured_is_allowed_but_deliberate(self) -> None:
        self.profile.set_disabled_toolsets(["terminal"])
        status, _ = self.bff.set_capability(
            {"id": "toolset:terminal", "body": {"enabled": True}}
        )
        self.assertEqual(status, 200)
        self.assertNotIn("terminal", self.profile.disabled_toolsets())

    def test_enabling_one_with_a_token_configured_needs_the_token(self) -> None:
        # The dispatcher injects `deliberate`: true when the deployment configured no token, or
        # when the request presented the right one.
        self.profile.set_disabled_toolsets(["terminal"])
        with self.assertRaises(ApiError) as caught:
            self.bff.set_capability(
                {"id": "toolset:terminal", "body": {"enabled": True}, "deliberate": False}
            )
        self.assertEqual(caught.exception.status, 403)
        self.assertEqual(caught.exception.code, "escape_hatch")
        self.assertIn("terminal", self.profile.disabled_toolsets())

    def test_with_the_token_the_same_switch_goes_through(self) -> None:
        self.profile.set_disabled_toolsets(["terminal"])
        status, _ = self.bff.set_capability(
            {"id": "toolset:terminal", "body": {"enabled": True}, "deliberate": True}
        )
        self.assertEqual(status, 200)
        self.assertNotIn("terminal", self.profile.disabled_toolsets())

    def test_an_unknown_toolset_name_is_refused_against_the_baseline(self) -> None:
        with self.assertRaises(ApiError) as caught:
            self.bff.set_capability(
                {"id": "toolset:not_a_real_toolset", "body": {"enabled": False}}
            )
        self.assertEqual(caught.exception.status, 404)
        self.assertNotIn("not_a_real_toolset", self.config())
