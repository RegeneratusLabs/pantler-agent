"""Tests for the skills index — the profile's skills, read from its files.

Two things matter here. **Fidelity**: the page must not list a skill the agent would not load,
so the `platforms:` gate, `skills.disabled`, and profile-over-home precedence are pinned. And
**honesty about the gap**: this reader stands in for the engine's own `GET /v1/skills`, which
answers 500 at the pinned commit, so the test says what it mirrors and what it does not.

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

from engine_settings import EngineProfile  # noqa: E402
from pantler_core import PackRegistry, Store, pack_from_dict  # noqa: E402
from pantler_server import Bff  # noqa: E402
from skills_index import (  # noqa: E402
    load_skills,
    matches_environment,
    matches_platform,
    parse_frontmatter,
    skill_roots,
)


def write_skill(root: Path, relative: str, name: str, description: str = "", extra: str = "") -> Path:
    path = root / relative / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f'---\nname: {name}\ndescription: "{description}"\n{extra}---\n\n# {name}\n',
        encoding="utf-8",
    )
    return path


class FrontmatterTestCase(unittest.TestCase):
    def test_reads_flat_keys_and_strips_quotes(self) -> None:
        text = '---\nname: invoicing\ndescription: "A: quoted value"\n---\nbody\n'
        self.assertEqual(
            parse_frontmatter(text),
            {"name": "invoicing", "description": "A: quoted value"},
        )

    def test_no_frontmatter_is_empty(self) -> None:
        self.assertEqual(parse_frontmatter("# just a heading\n"), {})

    def test_nested_keys_are_read_under_their_parent(self) -> None:
        """A nested mapping belongs to the key above it, not to the top level.

        This changed when the capability registry was built. Our own skills declare `category`
        under `metadata:` — the Agent Skills spec has no top-level `category` — and the parser
        used to drop that mapping on the floor, which would have put every spec-clean skill in
        "General". Comment lines are still ignored, and an indented key still never becomes a
        top-level one.
        """
        text = "---\nname: x\nmetadata:\n  nested: 1\n# note: ignored\n---\n"
        self.assertEqual(parse_frontmatter(text), {"name": "x", "metadata": {"nested": "1"}})

    def test_reads_an_inline_list(self) -> None:
        text = "---\nplatforms: [linux, macos, windows]\n---\n"
        self.assertEqual(parse_frontmatter(text)["platforms"], ["linux", "macos", "windows"])

    def test_reads_a_block_sequence(self) -> None:
        # `environments:` is written as a block list in the bundled set; reading it as an empty
        # scalar would list a kanban-only skill the engine does not offer.
        text = "---\nname: sdlc-review\nenvironments:\n  - kanban\n---\n"
        self.assertEqual(parse_frontmatter(text)["environments"], ["kanban"])

    def test_strips_a_leading_bom(self) -> None:
        self.assertEqual(parse_frontmatter("\ufeff---\nname: x\n---\n"), {"name": "x"})


class EnvironmentTestCase(unittest.TestCase):
    def test_absent_environments_match_everything(self) -> None:
        self.assertTrue(matches_environment({}))

    def test_a_kanban_only_skill_is_hidden_unless_kanban_is_active(self) -> None:
        frontmatter = {"environments": ["kanban"]}
        self.assertFalse(matches_environment(frontmatter))
        self.assertTrue(matches_environment(frontmatter, {"kanban"}))

    def test_an_unknown_tag_fails_open_like_the_engine(self) -> None:
        self.assertTrue(matches_environment({"environments": ["some-future-thing"]}))

    def test_any_active_tag_is_enough(self) -> None:
        frontmatter = {"environments": ["kanban", "docker"]}
        self.assertTrue(matches_environment(frontmatter, {"kanban"}))


class PlatformTestCase(unittest.TestCase):
    def test_absent_platforms_match_everything(self) -> None:
        self.assertTrue(matches_platform({}, "linux"))

    def test_a_matching_list_matches(self) -> None:
        frontmatter = {"platforms": "[linux, macos, windows]"}
        self.assertTrue(matches_platform(frontmatter, "linux"))
        self.assertTrue(matches_platform(frontmatter, "darwin"))

    def test_a_macos_only_skill_is_hidden_on_linux(self) -> None:
        # The four apple skills in the bundled set are `[macos]`; listing them on Linux would
        # show the operator something the agent cannot load.
        self.assertFalse(matches_platform({"platforms": "[macos]"}, "linux"))
        self.assertTrue(matches_platform({"platforms": "[macos]"}, "darwin"))

    def test_a_bare_scalar_platform_works(self) -> None:
        self.assertTrue(matches_platform({"platforms": "linux"}, "linux"))
        self.assertFalse(matches_platform({"platforms": "windows"}, "linux"))


class LoadSkillsTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.root = Path(self._dir.name)
        self.profile_dir = self.root / "profiles" / "pantler"
        self.skills = self.profile_dir / "skills"
        self.home_skills = self.root / "skills"
        self.skills.mkdir(parents=True)
        self.home_skills.mkdir(parents=True)

    def tearDown(self) -> None:
        self._dir.cleanup()

    def load(self, disabled: list[str] | None = None):
        return load_skills(self.profile_dir, disabled or [], platform="linux")

    def test_reads_name_description_and_path_category(self) -> None:
        write_skill(self.skills, "media/youtube-content", "youtube-content", "Fetch a video.")
        self.assertEqual(
            self.load(),
            [
                {
                    "name": "youtube-content",
                    "description": "Fetch a video.",
                    "category": "media",
                    "enabled": True,
                }
            ],
        )

    def test_a_declared_category_wins_over_the_path(self) -> None:
        # The distribution's own skill sits at the top level but declares `category: pantler`.
        write_skill(self.skills, "invoicing", "invoicing", "Drafting.", extra="category: pantler\n")
        self.assertEqual(self.load()[0]["category"], "pantler")

    def test_a_top_level_skill_without_a_category_is_general(self) -> None:
        write_skill(self.skills, "loose", "loose", "No category.")
        self.assertIsNone(self.load()[0]["category"])

    def test_a_platform_gated_skill_is_not_listed(self) -> None:
        write_skill(self.skills, "apple/imessage", "imessage", extra="platforms: [macos]\n")
        write_skill(self.skills, "media/ok", "ok", extra="platforms: [linux, macos, windows]\n")
        self.assertEqual([skill["name"] for skill in self.load()], ["ok"])

    def test_a_disabled_skill_is_listed_as_off_rather_than_dropped(self) -> None:
        # The screen this feeds can switch a skill back on, so a disabled one must stay in the
        # list — exactly what the engine's own config surface does (skip_disabled=True).
        write_skill(self.skills, "media/a", "a")
        write_skill(self.skills, "media/b", "b")
        listed = {skill["name"]: skill["enabled"] for skill in self.load(["a"])}
        self.assertEqual(listed, {"a": False, "b": True})

    def test_an_essential_skill_is_not_listed_at_all(self) -> None:
        # The engine always loads `hermes-agent`, so a switch could not change anything and the
        # screen does not offer one — it is not in the index even when `skills.disabled` names it.
        write_skill(self.skills, "autonomous-ai-agents/hermes-agent", "hermes-agent")
        write_skill(self.skills, "media/ok", "ok")
        self.assertEqual([skill["name"] for skill in self.load(["hermes-agent"])], ["ok"])

    def test_the_profile_root_wins_over_the_engine_home(self) -> None:
        write_skill(self.skills, "media/dup", "dup", "Profile copy.")
        write_skill(self.home_skills, "media/dup", "dup", "Home copy.")
        self.assertEqual([skill["description"] for skill in self.load()], ["Profile copy."])

    def test_a_hidden_copy_still_shadows_a_lower_tier(self) -> None:
        # The engine resolves shadowing before visibility, so a disabled profile skill keeps
        # the name and the home copy does not surface in its place.
        write_skill(self.skills, "media/dup", "dup", "Profile copy.")
        write_skill(self.home_skills, "media/dup", "dup", "Home copy.")
        self.assertEqual(
            [(skill["description"], skill["enabled"]) for skill in self.load(["dup"])],
            [("Profile copy.", False)],
        )

    def test_support_and_excluded_directories_are_not_scanned(self) -> None:
        write_skill(self.skills, "media/real", "real")
        write_skill(self.skills, "media/real/references", "not-a-skill")
        write_skill(self.skills, "node_modules/pkg", "dependency-skill")
        self.assertEqual([skill["name"] for skill in self.load()], ["real"])

    def test_a_skill_without_a_name_falls_back_to_its_directory(self) -> None:
        path = self.skills / "media" / "unnamed" / "SKILL.md"
        path.parent.mkdir(parents=True)
        path.write_text("---\ndescription: no name\n---\n", encoding="utf-8")
        self.assertEqual(self.load()[0]["name"], "unnamed")

    def test_sorted_by_category_then_name(self) -> None:
        write_skill(self.skills, "media/zeta", "zeta")
        write_skill(self.skills, "alpha/beta", "beta")
        write_skill(self.skills, "alpha/alpha", "alpha")
        self.assertEqual(
            [(skill["category"], skill["name"]) for skill in self.load()],
            [("alpha", "alpha"), ("alpha", "beta"), ("media", "zeta")],
        )

    def test_an_environment_gated_skill_follows_the_active_environments(self) -> None:
        write_skill(
            self.skills, "devops/sdlc-review", "sdlc-review", extra="environments:\n  - kanban\n"
        )
        write_skill(self.skills, "media/ok", "ok")
        self.assertEqual([skill["name"] for skill in self.load()], ["ok"])
        self.assertEqual(
            [
                skill["name"]
                for skill in load_skills(
                    self.profile_dir, [], platform="linux", active_environments={"kanban"}
                )
            ],
            ["sdlc-review", "ok"],
        )

    def test_skill_roots_include_the_engine_home_when_it_exists(self) -> None:
        self.assertEqual(skill_roots(self.profile_dir), [self.skills, self.home_skills])

    def test_skill_roots_omit_a_missing_engine_home(self) -> None:
        self.home_skills.rmdir()
        self.assertEqual(skill_roots(self.profile_dir), [self.skills])


class BffSkillsRouteTestCase(unittest.TestCase):
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
        self.profile_dir = root / "profiles" / "pantler"
        self.skills = self.profile_dir / "skills"
        self.skills.mkdir(parents=True)
        (self.profile_dir / "config.yaml").write_text("model:\n  provider: x\n", encoding="utf-8")
        write_skill(self.skills, "media/youtube-content", "youtube-content", "Fetch a video.")
        self.store = Store(root / "records.db")
        self.registry = PackRegistry([pack_from_dict(self.PACK)])

    def tearDown(self) -> None:
        self.store.close()
        self._dir.cleanup()

    def test_without_a_profile_skills_are_reported_unavailable(self) -> None:
        status, payload = Bff(self.store, self.registry, None).list_skills({})
        self.assertEqual(status, 200)
        self.assertFalse(payload["available"])
        self.assertEqual(payload["data"], [])
        self.assertIn("--profile-dir", payload["reason"])

    def test_with_a_profile_it_lists_what_the_engine_would_load(self) -> None:
        bff = Bff(self.store, self.registry, EngineProfile(self.profile_dir))
        status, payload = bff.list_skills({})
        self.assertEqual(status, 200)
        self.assertTrue(payload["available"])
        self.assertEqual(payload["profile"], "pantler")
        self.assertEqual([skill["name"] for skill in payload["data"]], ["youtube-content"])


if __name__ == "__main__":
    unittest.main()
