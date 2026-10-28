"""The profile-scope boundary.

These are the paths from session ``web-1a90145424a3`` and the neighbour cases around them:
the shared ``workspace/`` root, the sibling profile, the profile's own secrets, and the
ordinary system paths a renderer still needs. The tests drive ``Scope`` directly; the
engine-facing resolution is deliberately a thin wrapper so the decisions are testable
without a gateway.

Run through ``scripts/test.sh python``, or directly:

    python3 -m unittest discover -s plugins/pantler/tests -t plugins/pantler/tests
"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parent


def load_scope():
    path = PLUGIN / "scope.py"
    spec = importlib.util.spec_from_file_location("pantler_scope", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["pantler_scope"] = module
    spec.loader.exec_module(module)
    return module


class ScopeFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.scope_module = load_scope()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.home = self.root / ".hermes-dev"
        self.profiles = self.home / "profiles"
        self.alpha = self.profiles / "alpha"
        self.beta = self.profiles / "beta"
        self.workspace_root = self.root / "workspace"
        self.alpha_ws = self.workspace_root / "alpha"
        self.beta_ws = self.workspace_root / "beta"
        self.shared = self.workspace_root / "output"
        self.alpha_home = self.alpha / "home"
        for directory in (
            self.alpha,
            self.beta,
            self.alpha_ws,
            self.beta_ws,
            self.shared,
            self.alpha_home,
            self.alpha / "skills" / "design",
            self.beta / "skills",
        ):
            directory.mkdir(parents=True, exist_ok=True)
        (self.alpha / "config.yaml").write_text(
            f"terminal:\n  cwd: {self.alpha_ws}\n", encoding="utf-8"
        )
        (self.alpha / ".env").write_text("SECRET=1\n", encoding="utf-8")
        (self.alpha / "records.db").write_bytes(b"")
        (self.alpha / "state.db").write_bytes(b"")
        (self.alpha / "skills" / "design" / "scripts").mkdir(parents=True, exist_ok=True)
        (self.alpha / "skills" / "design" / "scripts" / "render_card.py").write_text(
            "# renderer\n", encoding="utf-8"
        )
        (self.alpha_ws / "output" / "design").mkdir(parents=True, exist_ok=True)
        (self.alpha_ws / "output" / "design" / "card.png").write_bytes(b"png")
        (self.beta_ws / "card.png").write_bytes(b"png")
        (self.shared / "card.png").write_bytes(b"png")
        (self.alpha_home / ".cache").mkdir(parents=True, exist_ok=True)
        self.legacy_attachments = self.root / ".data" / "attachments"
        self.legacy_attachments.mkdir(parents=True, exist_ok=True)
        (self.legacy_attachments / "upload.pdf").write_bytes(b"%PDF-")
        (self.alpha / "attachments").mkdir(exist_ok=True)
        (self.alpha / "attachments" / "scan.csv").write_text("sample\n", encoding="utf-8")
        (self.root / "examples" / "soil").mkdir(parents=True, exist_ok=True)
        (self.root / "examples" / "soil" / "coa.csv").write_text("sample\n", encoding="utf-8")
        self.scope = self.scope_module.Scope.for_profile(
            self.alpha, self.alpha_ws, hermes_root=self.home, home=self.alpha_home
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def path_refusal(self, path, **kwargs):
        return self.scope.refusal_for_path(str(path), **kwargs)

    # -- allowed ---------------------------------------------------------

    def test_the_profiles_own_workspace_is_allowed(self) -> None:
        self.assertIsNone(self.path_refusal(self.alpha_ws / "card.png"))
        self.assertIsNone(self.path_refusal(self.alpha_ws / "output" / "design" / "card.png"))

    def test_the_profiles_own_skill_scripts_are_allowed(self) -> None:
        self.assertIsNone(
            self.path_refusal(self.alpha / "skills" / "design" / "scripts" / "render_card.py")
        )

    def test_the_profiles_own_memory_and_cache_are_allowed(self) -> None:
        self.assertIsNone(self.path_refusal(self.alpha / "memories" / "MEMORY.md"))
        self.assertIsNone(self.path_refusal(self.alpha_home / ".cache" / "ms-playwright"))

    def test_uploaded_files_are_allowed(self) -> None:
        self.assertIn((self.alpha / "attachments").resolve(), self.scope.attachments)
        self.assertIn(self.legacy_attachments.resolve(), self.scope.attachments)
        self.assertIsNone(self.path_refusal(self.alpha / "attachments" / "scan.csv"))
        # This fixture has no `.pantler-profile.json`, so it stands in for the install profile:
        # the BFF's default store beside the checkout is its uploads, not another business's.
        self.assertIsNone(self.path_refusal(self.legacy_attachments / "upload.pdf"))

    def test_a_created_profile_does_not_inherit_the_installs_uploads(self) -> None:
        (self.alpha / ".pantler-profile.json").write_text("{}", encoding="utf-8")
        scope = self.scope_module.Scope.for_profile(
            self.alpha, self.alpha_ws, hermes_root=self.home, home=self.alpha_home
        )
        self.assertIn((self.alpha / "attachments").resolve(), scope.attachments)
        self.assertNotIn(self.legacy_attachments.resolve(), scope.attachments)
        self.assertIsNone(scope.refusal_for_path(self.alpha / "attachments" / "scan.csv"))

    def test_system_paths_needed_by_a_renderer_are_allowed(self) -> None:
        for path in ("/usr/share/fonts/truetype/lato/Lato-Black.ttf", "/tmp/render", "/etc/os-release"):
            with self.subTest(path=path):
                self.assertIsNone(self.path_refusal(path))

    def test_the_checkouts_examples_are_sample_data(self) -> None:
        self.assertIn((self.root / "examples").resolve(), self.scope.samples)
        self.assertIsNone(self.path_refusal(self.root / "examples" / "soil" / "coa.csv"))

    def test_a_relative_path_inside_the_workspace_is_allowed(self) -> None:
        self.assertIsNone(self.path_refusal("output/design/card.png", cwd=self.alpha_ws))
        self.assertIsNone(self.path_refusal("./output/design/card.png", cwd=self.alpha_ws))

    # -- another business ------------------------------------------------

    def test_another_profiles_state_is_another_business(self) -> None:
        refusal = self.path_refusal(self.beta / "config.yaml")
        self.assertEqual(refusal, self.scope_module.OTHER_BUSINESS)
        self.assertNotIn(str(self.beta), refusal)

    def test_another_profiles_workspace_is_another_business(self) -> None:
        self.assertEqual(self.path_refusal(self.beta_ws / "card.png"), self.scope_module.OTHER_BUSINESS)

    def test_the_shared_output_root_is_another_business(self) -> None:
        self.assertEqual(
            self.path_refusal(self.shared / "card.png"), self.scope_module.OTHER_BUSINESS
        )

    def test_the_workspace_parent_and_its_ancestors_are_outside(self) -> None:
        for path in (self.workspace_root, self.workspace_root.parent, Path("/home"), Path("/")):
            with self.subTest(path=path):
                self.assertEqual(self.path_refusal(path), self.scope_module.OUTSIDE)

    def test_dotdot_from_the_workspace_cannot_reach_a_sibling(self) -> None:
        self.assertEqual(
            self.path_refusal("../output/card.png", cwd=self.alpha_ws),
            self.scope_module.OTHER_BUSINESS,
        )
        self.assertEqual(self.path_refusal("..", cwd=self.alpha_ws), self.scope_module.OUTSIDE)

    def test_a_symlink_inside_the_workspace_cannot_point_at_another_business(self) -> None:
        link = self.alpha_ws / "borrowed.png"
        try:
            os.symlink(self.beta_ws / "card.png", link)
        except OSError as exc:  # pragma: no cover - filesystem dependent
            self.skipTest(f"symlinks unavailable: {exc}")
        self.assertEqual(self.path_refusal(link), self.scope_module.OTHER_BUSINESS)

    # -- secrets ---------------------------------------------------------

    def test_the_profiles_own_credentials_and_state_are_refused(self) -> None:
        for path in (
            self.alpha / ".env",
            self.alpha / ".env.local",
            self.alpha / "records.db",
            self.alpha / "records.db-wal",
            self.alpha / "state.db",
            self.alpha / "response_store.db",
            self.alpha / "auth.json",
            self.alpha / "install_id",
            self.alpha / "id_rsa",
            self.alpha / "cert.pem",
        ):
            with self.subTest(path=path):
                self.assertEqual(self.path_refusal(path), self.scope_module.SECRET)

    # -- terminal --------------------------------------------------------

    def test_terminal_refuses_a_named_other_business_path(self) -> None:
        message = self.scope.refusal_for_command(f"cat {self.beta_ws / 'card.png'}")
        self.assertEqual(message, self.scope_module.OTHER_BUSINESS)
        self.assertNotIn(str(self.beta_ws), message)

    def test_terminal_refuses_dotdot_and_find_of_an_ancestor(self) -> None:
        self.assertEqual(self.scope.refusal_for_command("cd .. && ls"), self.scope_module.OUTSIDE)
        self.assertEqual(self.scope.refusal_for_command("find /home"), self.scope_module.OUTSIDE)
        self.assertEqual(self.scope.refusal_for_command("find /"), self.scope_module.OUTSIDE)

    def test_terminal_allows_ordinary_workspace_work(self) -> None:
        for command in (
            "find . -maxdepth 2",
            "ls output/design",
            "fc-list | grep -i lato",
            "python3 -c \"import PIL; print(PIL.__version__)\"",
            "python3 -c \"print('a/b')\"",
        ):
            with self.subTest(command=command):
                self.assertIsNone(self.scope.refusal_for_command(command))

    def test_terminal_reads_a_path_inside_a_heredoc(self) -> None:
        command = f"python3 - <<'PY'\nopen({str(self.beta_ws / 'card.png')!r}).read()\nPY"
        self.assertEqual(self.scope.refusal_for_command(command), self.scope_module.OTHER_BUSINESS)

    def test_terminal_honours_a_workdir(self) -> None:
        self.assertEqual(
            self.scope.refusal_for_command("ls", workdir=str(self.beta_ws)),
            self.scope_module.OTHER_BUSINESS,
        )
        self.assertIsNone(self.scope.refusal_for_command("ls", workdir=str(self.alpha_ws)))

    # -- other tools -----------------------------------------------------

    def test_file_and_search_tools_refuse_another_business(self) -> None:
        for tool in ("read_file", "write_file", "patch", "search_files"):
            with self.subTest(tool=tool):
                self.assertEqual(
                    self.scope.refusal_for_tool(tool, {"path": str(self.beta_ws / "card.png")}),
                    self.scope_module.OTHER_BUSINESS,
                )

    def test_files_can_read_a_relative_workspace_path(self) -> None:
        self.assertIsNone(
            self.scope.refusal_for_tool("read_file", {"path": "output/design/card.png"})
        )

    def test_execute_code_checks_quoted_paths(self) -> None:
        code = f"open({str(self.beta_ws / 'card.png')!r}).read()"
        self.assertEqual(self.scope.refusal_for_code(code), self.scope_module.OTHER_BUSINESS)
        self.assertIsNone(self.scope.refusal_for_code("print('a/b')"))
        self.assertIsNone(self.scope.refusal_for_code("print('https://example.com/a')"))

    def test_vision_checks_paths_but_not_urls(self) -> None:
        self.assertEqual(
            self.scope.refusal_for_tool("vision_analyze", {"image_url": str(self.beta_ws / "card.png")}),
            self.scope_module.OTHER_BUSINESS,
        )
        self.assertIsNone(
            self.scope.refusal_for_tool("vision_analyze", {"image_url": "https://example.com/a.png"})
        )
        self.assertIsNone(
            self.scope.refusal_for_tool("vision_analyze", {"image_url": "data:image/png;base64,AA"})
        )

    def test_the_soil_tools_check_the_coa_path(self) -> None:
        for tool in ("soil_test_read", "soil_amendment"):
            with self.subTest(tool=tool):
                self.assertEqual(
                    self.scope.refusal_for_tool(
                        tool, {"coa_path": str(self.beta_ws / "soil.csv")}
                    ),
                    self.scope_module.OTHER_BUSINESS,
                )
                self.assertIsNone(
                    self.scope.refusal_for_tool(
                        tool, {"coa_path": str(self.alpha / "attachments" / "scan.csv")}
                    )
                )

    def test_browser_checks_file_urls(self) -> None:
        self.assertEqual(
            self.scope.refusal_for_tool(
                "browser_navigate", {"url": (self.beta_ws / "card.png").as_uri()}
            ),
            self.scope_module.OTHER_BUSINESS,
        )
        self.assertIsNone(
            self.scope.refusal_for_tool("browser_navigate", {"url": "https://example.com"})
        )

    # -- configuration shapes -------------------------------------------

    def test_a_shared_workspace_root_uses_the_profiles_own_child(self) -> None:
        (self.workspace_root / "alpha").mkdir(exist_ok=True)
        scope = self.scope_module.Scope.for_profile(
            self.alpha, self.workspace_root, hermes_root=self.home, home=self.alpha_home
        )
        self.assertEqual(scope.workspace, (self.workspace_root / "alpha").resolve())
        self.assertEqual(
            scope.refusal_for_path(self.shared / "card.png"), self.scope_module.OTHER_BUSINESS
        )

    def test_an_unrelated_workspace_name_is_left_alone(self) -> None:
        custom = self.root / "business"
        custom.mkdir()
        scope = self.scope_module.Scope.for_profile(
            self.alpha, custom, hermes_root=self.home, home=self.alpha_home
        )
        self.assertEqual(scope.workspace, custom.resolve())

    # -- the engine-facing hook -----------------------------------------

    def test_the_hook_blocks_and_allows_through_the_active_profile(self) -> None:
        with mock.patch.object(
            self.scope_module, "_active_profile", return_value=self.alpha
        ), mock.patch.object(
            self.scope_module, "_configured_cwd", return_value=self.alpha_ws
        ):
            blocked = self.scope_module.pre_tool_call(
                "read_file", {"path": str(self.beta_ws / "card.png")}
            )
            self.assertEqual(blocked["action"], "block")
            self.assertEqual(blocked["message"], self.scope_module.OTHER_BUSINESS)
            self.assertIsNone(
                self.scope_module.pre_tool_call(
                    "read_file", {"path": str(self.alpha_ws / "card.png")}
                )
            )


if __name__ == "__main__":
    unittest.main()
