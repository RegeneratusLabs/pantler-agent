"""The profile registry, its file operations, and per-profile BFF dispatch.

These drive the manager and the router directly, like the rest of the BFF suite: the contract
is what matters — which directory is copied, which paths are rewritten, which profile answers a
request — and a socket adds nothing to any of it.
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

from profiles import ProfileError, ProfileManager, _remove_standalone  # noqa: E402
from pantler_server import (  # noqa: E402
    ApiError,
    BffRouter,
    build_bff,
    profile_file_roots,
    profile_workspace_for_preview,
)
from previews import FileRoots, PreviewError  # noqa: E402

PACK = """
id = "example"
label = "Example"
[[records]]
type = "note"
label = "Note"
plural = "Notes"
title_field = "title"
id_prefix = "NOTE"
id_sequence = true
[[records.fields]]
name = "title"
kind = "text"
"""

CONFIG = """\
model:
  provider: opencode-go
  default: deepseek-v4.1-flash
  base_url: https://example.invalid/v1
  key_env: TEST_KEY
plugins:
  enabled: [records, pantler]
  entries:
    records:
      settings:
        capability_enabled: true
        store_path: {store}
        packs_dir: {packs}
    pantler:
      pricebook_path: {profile}/pricebook.json
gateway:
  standalone: true
terminal:
  cwd: {workspace}
"""


class ProfileFixture(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.home = self.root / ".hermes-dev"
        self.profiles = self.home / "profiles"
        self.install = self.profiles / "pantler"
        self.install.mkdir(parents=True)
        self.store = self.root / ".data" / "records.db"
        self.attachments = self.root / ".data" / "attachments"
        self.workspace_root = self.root / "workspace"
        self.source_workspace = self.workspace_root
        self.source_workspace.mkdir(parents=True)
        (self.source_workspace / "AGENTS.md").write_text("# guide\n", encoding="utf-8")

        self.packs = self.root / "packs"
        (self.packs / "example").mkdir(parents=True)
        (self.packs / "example" / "pack.toml").write_text(PACK, encoding="utf-8")

        for directory in ("skills", "skills/invoicing", "plugins", "packs", "packs/example", "sessions", "memories"):
            (self.install / directory).mkdir(parents=True, exist_ok=True)
        (self.install / "skills" / "invoicing" / "SKILL.md").write_text("# invoice\n", encoding="utf-8")
        (self.install / "packs" / "example" / "pack.toml").write_text(PACK, encoding="utf-8")
        (self.install / "plugins" / "records").symlink_to(self.root / "plugins" / "records")
        (self.install / "SOUL.md").write_text("# soul\n", encoding="utf-8")
        (self.install / "distribution.yaml").write_text("name: pantler\n", encoding="utf-8")
        (self.install / "pricebook.json").write_text('{"items": []}\n', encoding="utf-8")
        (self.install / "config.yaml").write_text(
            CONFIG.format(
                store=self.store,
                packs=self.packs,
                profile=self.install,
                workspace=self.source_workspace,
            ),
            encoding="utf-8",
        )
        (self.install / ".env").write_text(
            "API_SERVER_HOST=127.0.0.1\n"
            "API_SERVER_PORT=8644\n"
            "API_SERVER_KEY=test-key-that-is-long-enough\n"
            "TEST_KEY=provider-key\n",
            encoding="utf-8",
        )
        # A source profile's runtime state must never be copied into a new one.
        (self.install / "sessions" / "session.json").write_text("{}", encoding="utf-8")
        (self.install / "memories" / "MEMORY.md").write_text("a fact\n", encoding="utf-8")
        self.store.parent.mkdir(parents=True)
        self.store.write_bytes(b"")

        self.manager = ProfileManager(
            self.install,
            store_path=self.store,
            attachments_dir=self.attachments,
            workspace_root=self.workspace_root,
            repo_root=self.root,
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def create_second(self, **kwargs):
        return self.manager.create("second", **kwargs)


class TestRegistry(ProfileFixture):
    def test_the_installed_profile_is_listed_and_active_by_default(self) -> None:
        self.assertTrue(self.manager.available)
        listed = self.manager.list()
        self.assertEqual([profile.name for profile in listed], ["pantler"])
        self.assertTrue(listed[0].is_install)
        self.assertTrue(listed[0].active)
        self.assertEqual(self.manager.active(), "pantler")
        self.assertEqual(listed[0].model, "deepseek-v4.1-flash")

    def test_an_invalid_name_is_refused_with_the_rule(self) -> None:
        for bad in ("", "two words", "-leading", "_leading", "x" * 65):
            with self.subTest(bad=bad), self.assertRaises(ProfileError) as caught:
                self.manager.validate(bad)
            self.assertIn(caught.exception.status, (400, 422))

    def test_the_engine_host_profile_is_not_managed_here(self) -> None:
        with self.assertRaises(ProfileError) as caught:
            self.manager.validate("default")
        self.assertEqual(caught.exception.code, "reserved_name")

    def test_a_directory_without_identity_is_not_a_profile(self) -> None:
        (self.profiles / "empty").mkdir()
        self.assertEqual([profile.name for profile in self.manager.list()], ["pantler"])


class TestPreviewRoots(ProfileFixture):
    """A business's app may preview its own files, never a sibling's or the checkout."""

    def test_a_shared_workspace_root_is_not_a_preview_root(self) -> None:
        self.assertIsNone(profile_workspace_for_preview(self.manager, "pantler"))
        roots = profile_file_roots(self.manager, "pantler")
        self.assertEqual(roots, [str(self.attachments)])

    def test_the_profiles_own_child_is_used_when_it_exists(self) -> None:
        own = self.workspace_root / "pantler"
        own.mkdir()
        self.assertEqual(profile_workspace_for_preview(self.manager, "pantler"), own)
        self.assertIn(str(own), profile_file_roots(self.manager, "pantler"))

    def test_a_new_profile_previews_only_its_own_workspace(self) -> None:
        self.create_second()
        roots = profile_file_roots(self.manager, "second")
        self.assertIn(str(self.workspace_root / "second"), roots)
        self.assertNotIn(str(self.workspace_root), roots)
        self.assertNotIn(str(REPO_ROOT), roots)

        shared = FileRoots.build(roots)
        self.assertTrue(shared.resolve(str(self.workspace_root / "second" / "AGENTS.md")))
        shared_file = self.workspace_root / "pantler.txt"
        shared_file.write_text("the other business\n", encoding="utf-8")
        with self.assertRaises(PreviewError) as caught:
            shared.resolve(str(shared_file))
        self.assertEqual(caught.exception.code, "outside_roots")

    def test_an_explicit_files_root_is_still_honoured(self) -> None:
        roots = profile_file_roots(self.manager, "pantler", [str(self.workspace_root)])
        self.assertIn(str(self.workspace_root), roots)


class TestConfigText(unittest.TestCase):
    def test_standalone_and_its_empty_parent_are_removed(self) -> None:
        text = (
            "gateway:\n"
            "  standalone: true\n"
            "# a comment after the block belongs to the file\n"
            "terminal:\n"
            "  cwd: /tmp\n"
        )
        cleaned = _remove_standalone(text)
        self.assertNotIn("standalone", cleaned)
        self.assertNotIn("gateway:", cleaned)
        self.assertIn("# a comment after the block belongs to the file", cleaned)
        self.assertIn("terminal:", cleaned)

    def test_a_gateway_block_with_other_keys_keeps_them(self) -> None:
        cleaned = _remove_standalone(
            "gateway:\n  standalone: true\n  multiplex_profiles: true\n"
        )
        self.assertIn("gateway:", cleaned)
        self.assertIn("multiplex_profiles: true", cleaned)
        self.assertNotIn("standalone", cleaned)


class TestCreate(ProfileFixture):
    def test_create_copies_the_product_payload_and_not_the_source_state(self) -> None:
        profile = self.create_second(display_name="Second Farm", description="The other business")
        second = self.install.parent / "second"
        self.assertTrue(second.is_dir())
        self.assertEqual(profile.name, "second")
        self.assertEqual(profile.display_name, "Second Farm")
        self.assertEqual(profile.description, "The other business")
        self.assertFalse(profile.active)

        self.assertTrue((second / "skills" / "invoicing" / "SKILL.md").is_file())
        self.assertTrue((second / "packs" / "example" / "pack.toml").is_file())
        self.assertTrue((second / "pricebook.json").is_file())
        self.assertTrue((second / "SOUL.md").is_file())
        self.assertTrue((second / "plugins" / "records").is_symlink())
        # The new business starts clean.
        self.assertFalse((second / "sessions" / "session.json").exists())
        self.assertFalse((second / "memories" / "MEMORY.md").exists())
        self.assertFalse((second / "records.db").exists())

    def test_create_rewrites_paths_and_drops_standalone(self) -> None:
        self.create_second()
        second = self.install.parent / "second"
        config = (second / "config.yaml").read_text(encoding="utf-8")
        self.assertIn(str(second / "records.db"), config)
        self.assertIn(str(second / "packs"), config)
        self.assertIn(str(second / "pricebook.json"), config)
        self.assertIn(str(self.workspace_root / "second"), config)
        self.assertNotIn(str(self.store), config)
        self.assertNotIn("standalone", config)
        self.assertNotIn("gateway:", config)

    def test_create_strips_the_listener_and_keeps_the_credentials(self) -> None:
        self.create_second()
        env = (self.install.parent / "second" / ".env").read_text(encoding="utf-8")
        self.assertNotIn("API_SERVER_PORT", env)
        self.assertNotIn("API_SERVER_HOST", env)
        self.assertIn("API_SERVER_KEY=test-key-that-is-long-enough", env)
        self.assertIn("TEST_KEY=provider-key", env)
        self.assertEqual((self.install.parent / "second" / ".env").stat().st_mode & 0o777, 0o600)

    def test_create_copies_a_packs_directory_named_only_in_the_config(self) -> None:
        # The dev install keeps its packs in the checkout and names them with `packs_dir`,
        # rather than carrying a `packs/` of its own. The clone must still get a real one,
        # because its config is rewritten to point inside itself.
        import shutil

        shutil.rmtree(self.install / "packs")
        self.create_second()
        self.assertTrue((self.install.parent / "second" / "packs" / "example" / "pack.toml").is_file())

    def test_create_seeds_a_workspace_with_the_operating_guide(self) -> None:
        self.create_second()
        guide = self.workspace_root / "second" / "AGENTS.md"
        self.assertEqual(guide.read_text(encoding="utf-8"), "# guide\n")

    def test_create_refuses_a_duplicate_and_a_reserved_name(self) -> None:
        self.create_second()
        with self.assertRaises(ProfileError) as caught:
            self.create_second()
        self.assertEqual(caught.exception.status, 409)
        with self.assertRaises(ProfileError) as caught:
            self.manager.create("default")
        self.assertEqual(caught.exception.code, "reserved_name")

    def test_create_from_a_named_profile(self) -> None:
        self.create_second(display_name="Second")
        third = self.manager.create("third", source="second")
        self.assertEqual(third.name, "third")
        self.assertEqual(
            (self.install.parent / "third" / "skills" / "invoicing" / "SKILL.md").read_text(
                encoding="utf-8"
            ),
            "# invoice\n",
        )
        self.assertEqual(third.to_dict()["name"], "third")
        self.assertEqual(self.manager.meta("third")["clone_from"], "second")

    def test_a_failed_create_leaves_nothing_behind(self) -> None:
        # A source config whose model block names an unreadable file does not stop a copy; a
        # write failure does. Simulate one by making the target's parent read-only is not
        # portable — instead ask for a name whose workspace cannot be created (a file there).
        (self.workspace_root / "blocked").write_text("not a directory", encoding="utf-8")
        with self.assertRaises(OSError):
            self.manager.create("blocked")
        self.assertFalse((self.install.parent / "blocked").exists())


class TestActiveAndUpdate(ProfileFixture):
    def test_set_active_writes_the_engines_own_pointer(self) -> None:
        self.create_second()
        self.assertEqual(self.manager.set_active("second"), "second")
        self.assertEqual((self.home / "active_profile").read_text(encoding="utf-8"), "second\n")
        self.assertEqual(self.manager.active(), "second")
        self.assertTrue(self.manager.info("second").active)

    def test_setting_the_install_profile_removes_the_pointer(self) -> None:
        self.create_second()
        self.manager.set_active("second")
        self.manager.set_active("pantler")
        self.assertFalse((self.home / "active_profile").exists())
        self.assertEqual(self.manager.active(), "pantler")

    def test_a_dangling_pointer_falls_back_to_the_install(self) -> None:
        (self.home / "active_profile").write_text("gone\n", encoding="utf-8")
        self.assertEqual(self.manager.active(), "pantler")

    def test_update_changes_only_the_fields_it_is_given(self) -> None:
        self.create_second(display_name="Two", description="first")
        updated = self.manager.update("second", display_name="Second Farm")
        self.assertEqual(updated.display_name, "Second Farm")
        self.assertEqual(updated.description, "first")
        updated = self.manager.update("second", description="now this")
        self.assertEqual(updated.display_name, "Second Farm")
        self.assertEqual(updated.description, "now this")

    def test_unknown_profile_is_a_404(self) -> None:
        with self.assertRaises(ProfileError) as caught:
            self.manager.info("nope")
        self.assertEqual(caught.exception.status, 404)


class TestRenameAndDelete(ProfileFixture):
    def test_rename_moves_the_profile_and_rewrites_its_paths(self) -> None:
        self.create_second()
        self.manager.set_active("second")
        renamed = self.manager.rename("second", "garden")
        second = self.install.parent / "second"
        garden = self.install.parent / "garden"
        self.assertEqual(renamed.name, "garden")
        self.assertFalse(second.exists())
        self.assertTrue(garden.is_dir())
        config = (garden / "config.yaml").read_text(encoding="utf-8")
        self.assertIn(str(garden / "records.db"), config)
        self.assertNotIn(str(second), config)
        self.assertEqual((self.home / "active_profile").read_text(encoding="utf-8"), "garden\n")
        self.assertTrue((self.workspace_root / "garden").is_dir())
        self.assertFalse((self.workspace_root / "second").exists())
        self.assertEqual(self.manager.meta("garden")["previous_names"], ["second"])

    def test_rename_tombstones_the_old_name_and_hides_a_ghost(self) -> None:
        self.create_second()
        self.manager.rename("second", "garden")
        self.assertTrue((self.profiles / ".deleted" / "second").is_file())
        ghost = self.install.parent / "second"
        ghost.mkdir()
        (ghost / "state.db").write_bytes(b"")
        self.assertEqual(self.manager.names(), ["pantler", "garden"])
        with self.assertRaises(ProfileError):
            self.manager.info("second")

    def test_rename_refuses_the_installed_profile(self) -> None:
        with self.assertRaises(ProfileError) as caught:
            self.manager.rename("pantler", "other")
        self.assertEqual(caught.exception.code, "install_profile")

    def test_delete_removes_the_profile_and_its_workspace(self) -> None:
        self.create_second()
        self.manager.delete("second")
        self.assertFalse((self.install.parent / "second").exists())
        self.assertFalse((self.workspace_root / "second").exists())
        self.assertEqual(self.manager.names(), ["pantler"])

    def test_delete_tombstones_the_name_and_a_recreate_clears_it(self) -> None:
        self.create_second()
        self.manager.delete("second")
        marker = self.profiles / ".deleted" / "second"
        self.assertTrue(marker.is_file())

        # A multiplexer can drop a cron heartbeat or a state.db into the removed path before
        # its next rescan. That shell is not a profile, even though it carries an identity
        # marker the engine also counts.
        ghost = self.install.parent / "second"
        ghost.mkdir()
        (ghost / "state.db").write_bytes(b"")
        self.assertEqual(self.manager.names(), ["pantler"])
        with self.assertRaises(ProfileError):
            self.manager.info("second")

        recreated = self.manager.create("second")
        self.assertEqual(recreated.name, "second")
        self.assertFalse(marker.exists())
        self.assertTrue((ghost / "config.yaml").is_file())

    def test_a_new_manager_sweeps_a_tombstoned_ghost(self) -> None:
        self.create_second()
        self.manager.delete("second")
        ghost = self.install.parent / "second"
        ghost.mkdir()
        (ghost / "state.db").write_bytes(b"")
        reopened = ProfileManager(
            self.install,
            store_path=self.store,
            attachments_dir=self.attachments,
            workspace_root=self.workspace_root,
            repo_root=self.root,
        )
        self.assertFalse(ghost.exists())
        self.assertEqual(reopened.names(), ["pantler"])
        self.assertTrue((self.profiles / ".deleted" / "second").exists())

    def test_delete_refuses_the_installed_and_active_profiles(self) -> None:
        self.create_second()
        with self.assertRaises(ProfileError) as caught:
            self.manager.delete("pantler")
        self.assertEqual(caught.exception.code, "install_profile")
        self.manager.set_active("second")
        with self.assertRaises(ProfileError) as caught:
            self.manager.delete("second")
        self.assertEqual(caught.exception.code, "active_profile")
        self.assertTrue((self.install.parent / "second").exists())


class TestGatewayState(ProfileFixture):
    def test_single_profile_gateway_reports_the_install_and_not_a_new_profile(self) -> None:
        self.create_second()
        state = {
            "pid": os.getpid(),
            "served_profiles": [],
        }
        (self.install / "gateway_state.json").write_text(json.dumps(state), encoding="utf-8")
        listed = {profile.name: profile for profile in self.manager.list()}
        self.assertTrue(listed["pantler"].served)
        self.assertFalse(listed["second"].served)

    def test_a_multiplexed_gateway_reports_every_served_profile(self) -> None:
        self.create_second()
        (self.home / "config.yaml").write_text(
            "gateway:\n  multiplex_profiles: true\n", encoding="utf-8"
        )
        (self.home / "gateway_state.json").write_text(
            json.dumps({"pid": os.getpid(), "served_profiles": ["pantler", "second"]}),
            encoding="utf-8",
        )
        gateway = self.manager.gateway()
        self.assertTrue(gateway["multiplex"])
        listed = {profile.name: profile for profile in self.manager.list()}
        self.assertTrue(listed["pantler"].served)
        self.assertTrue(listed["second"].served)


class TestRouting(ProfileFixture):
    def setUp(self) -> None:
        super().setUp()
        self.packs_dir = self.packs
        self.base = build_bff(
            self.store,
            self.packs_dir,
            self.install,
            self.attachments,
            [self.root],
        )

        def factory(name: str):
            return build_bff(
                self.manager.store_for(name),
                self.packs_dir,
                self.manager.path_for(name),
                self.manager.attachments_for(name),
                [self.root],
            )

        self.router = BffRouter(self.base, self.manager, factory)

    def tearDown(self) -> None:
        self.router.close()
        super().tearDown()

    def test_a_write_lands_in_the_selected_profiles_store(self) -> None:
        self.manager.create("second")
        status, created = self.router.create_record(
            {"_profile": "second", "type": "note", "body": {"title": "second's note"}}
        )
        self.assertEqual(status, 201)
        self.assertEqual(created["id"], "NOTE-0001")

        status, page = self.router.list_records({"_profile": "second", "type": "note"})
        self.assertEqual(status, 200)
        self.assertEqual(page["total"], 1)

        status, page = self.router.list_records({"_profile": "pantler", "type": "note"})
        self.assertEqual(status, 200)
        self.assertEqual(page["total"], 0, "one profile's records never appear in another's")

    def test_no_header_uses_the_active_profile(self) -> None:
        self.manager.create("second")
        self.manager.set_active("second")
        status, created = self.router.create_record({"type": "note", "body": {"title": "x"}})
        self.assertEqual(status, 201)
        self.assertEqual(
            Store_total(self.manager.store_for("second")), 1
        )
        self.assertEqual(Store_total(self.store), 0)

    def test_an_unknown_profile_is_refused_not_ignored(self) -> None:
        with self.assertRaises(ApiError) as caught:
            self.router.list_records({"_profile": "nope", "type": "note"})
        self.assertEqual(caught.exception.status, 404)

    def test_a_server_without_a_profile_dir_says_so(self) -> None:
        router = BffRouter(self.base, None, lambda name: self.base)
        status, payload = router.profiles_list({})
        self.assertEqual(status, 200)
        self.assertFalse(payload["available"])
        self.assertEqual(payload["profiles"], [])
        with self.assertRaises(ApiError) as caught:
            router.create_profile({"body": {"name": "x"}})
        self.assertEqual(caught.exception.status, 503)

    def test_profile_administration_goes_through_the_router(self) -> None:
        status, listed = self.router.profiles_list({})
        self.assertEqual(status, 200)
        self.assertTrue(listed["available"])
        self.assertEqual(listed["active"], "pantler")

        status, created = self.router.create_profile(
            {"body": {"name": "second", "display_name": "Second"}}
        )
        self.assertEqual(status, 201)
        self.assertEqual(created["profile"]["name"], "second")
        # This fixture's engine is a single-profile gateway, so the screen is told the truth:
        # the new profile is on disk, and a host restart is what makes it conversational.
        self.assertTrue(created["restart_required"])

        status, changed = self.router.update_profile(
            {"name": "second", "body": {"description": "Another business"}}
        )
        self.assertEqual(status, 200)
        self.assertEqual(changed["profile"]["description"], "Another business")

        status, active = self.router.set_active_profile({"body": {"name": "second"}})
        self.assertEqual(status, 200)
        self.assertEqual(active["active"], "second")

        # The active profile is protected: deleting it would leave the app pointing at a
        # directory that no longer exists. Switch home first.
        status, back = self.router.set_active_profile({"body": {"name": "pantler"}})
        self.assertEqual(status, 200)
        self.assertEqual(back["active"], "pantler")

        status, deleted = self.router.delete_profile({"name": "second"})
        self.assertEqual(status, 200)
        self.assertEqual(deleted["deleted"], "second")


def Store_total(path: Path) -> int:
    """Read a record store without creating a second long-lived connection."""
    from pantler_core import Store

    store = Store(path)
    try:
        return store.count("note")
    finally:
        store.close()
