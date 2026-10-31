"""A plugin must work on a machine where the kernel was never installed.

This is the test for round 2's structural finding. The engine's Python does not have `pantler_core`
in it — on a dev machine `scripts/dev-sync.sh` puts it there by hand, and an engine update builds a
*fresh* dependency environment without it. On a customer's machine nothing does it at all, and the
plugin does not import: no error anybody sees until a tool is called.

So the proof has to run under an interpreter that genuinely cannot import the kernel, which means a
subprocess with `-I` (isolated: no site, no PYTHONPATH, no current directory) and the repository's
`core/src` deliberately absent. Anything less would test the dev machine, not the product.

    python3 -m unittest discover -s scripts/tests -t scripts/tests
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

PROOF = r'''
import importlib.util, json, sys, tempfile
from pathlib import Path

REPO = Path(sys.argv[1])
try:
    import pantler_core
    print(json.dumps({"error": "the kernel is importable in this interpreter"}))
    raise SystemExit(0)
except ImportError:
    pass

tmp = tempfile.TemporaryDirectory()


class Ctx:
    def __init__(self, **settings):
        self.settings, self.tools = settings, []

    def register_tool(self, **kw):
        self.tools.append(kw)

    def get_config(self, key=None, default=None):
        return dict(self.settings) if key is None else self.settings.get(key, default)


out = {"kernel_absent": True, "plugins": {}}
# Every plugin that vendors the kernel, not four of the six: `claims` and `consent` import it too,
# and the proof that the vendored copy is the one that runs did not cover them
# (the internal audit SCR-7). Discovered from the tree so a seventh plugin is covered
# without editing this list.
VENDORING = sorted(
    plugin.name for plugin in (REPO / "plugins").iterdir()
    if (plugin / "vendor" / "pantler_core").is_dir()
)
assert VENDORING, "no plugin vendors the kernel"
for name in VENDORING:
    plugin = REPO / "plugins" / name
    spec = importlib.util.spec_from_file_location(
        f"{name}_plugin", plugin / "__init__.py", submodule_search_locations=[str(plugin)]
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[f"{name}_plugin"] = module
    spec.loader.exec_module(module)
    ctx = Ctx(
        catalogue_path=str(REPO / "plugins" / "spray" / "tests" / "fixtures" / "spraybook.json"),
        store_path=str(Path(tmp.name) / "records.db"),
        packs_dir=str(REPO / "packs"),
    )
    module.register(ctx)
    out["plugins"][name] = len(ctx.tools)

spray = sys.modules["spray_plugin"]
result = json.loads(next(t[2] for t in spray.tools._TOOLS if t[0] == "spray_record")({
    "applied": "2026-10-14", "block": "north", "product": "copper",
    "rate": 2.5, "rate_unit": "kg/ha",
}))
out["spray_record"] = {"saved": result.get("saved"), "id": result.get("id")}

records = sys.modules["records_plugin"]
saved = json.loads(next(t[2] for t in records.tools._TOOLS if t[0] == "record_save")(
    {"type": "certificate", "fields": {"holder": "our business", "scheme": "ACO"}}
))
out["record_save"] = {"id": saved.get("id"), "empty": bool(saved.get("empty_fields"))}
out["kernel_from"] = sys.modules["pantler_core"].__file__.split("pantler/")[-1]
out["sources"] = {name: sys.modules[f"{name}_plugin"].pantler_kernel.SOURCE for name in VENDORING}
print(json.dumps(out))
'''


# With a kernel importable — the case the old shim lost. A decoy `pantler_core` on PYTHONPATH
# stands in for the stale installed copy the audit found: the shim used to prefer it, so the
# plugins ran a two-day-old kernel while every gate stayed green
# (the internal security audit A19-KERN-1). The decoy is deliberately broken so a test that
# silently used it would fail loudly rather than pass.
DECOY_PROOF = r'''
import importlib.util, json, sys
from pathlib import Path

REPO = Path(sys.argv[1])
import pantler_core
out = {"chose_installed": pantler_core.__file__}
sys.modules.pop("pantler_core")
for module in [name for name in list(sys.modules) if name.startswith("pantler_core.")]:
    sys.modules.pop(module)

plugin = REPO / "plugins" / "records"
spec = importlib.util.spec_from_file_location(
    "records_plugin", plugin / "__init__.py", submodule_search_locations=[str(plugin)]
)
module = importlib.util.module_from_spec(spec)
sys.modules["records_plugin"] = module
spec.loader.exec_module(module)
out["source"] = module.pantler_kernel.SOURCE
out["kernel_used"] = sys.modules["pantler_core"].__file__
print(json.dumps(out))
'''


class InstalledKernelDoesNotWinTest(unittest.TestCase):
    """The vendored copy is authoritative, not a fallback."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._decoy = tempfile.TemporaryDirectory()
        decoy = Path(cls._decoy.name)
        package = decoy / "pantler_core"
        package.mkdir()
        # Importable, and nothing like the kernel: a plugin that used it would fail on the first
        # `pantler_core.recordbook` import, which is the loud failure this test wants.
        (package / "__init__.py").write_text("STALE = True\n")
        cls.result = subprocess.run(
            [sys.executable, "-B", "-c", DECOY_PROOF, str(ROOT)],
            capture_output=True,
            text=True,
            timeout=120,
            cwd="/",
            env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(decoy)},
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._decoy.cleanup()

    def test_the_decoy_was_importable_and_lost(self) -> None:
        self.assertEqual(self.result.returncode, 0, self.result.stderr[-800:])
        payload = json.loads(self.result.stdout.strip().splitlines()[-1])
        self.assertIn("pantler_core/__init__.py", payload["chose_installed"])
        self.assertEqual(payload["source"], "vendored")
        self.assertIn("vendor/pantler_core", payload["kernel_used"])


class VendoredKernelTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = subprocess.run(
            # `-B` as well as `-I`: isolation implies `-E`, which *ignores* PYTHONDONTWRITEBYTECODE,
            # so the flag is the only way to keep the working tree free of caches.
            [sys.executable, "-B", "-I", "-c", PROOF, str(ROOT)],
            capture_output=True,
            text=True,
            timeout=120,
            cwd="/",  # nothing of the repository on the path by accident
            # No PYTHONPATH, no HERMES_HOME, and no bytecode written into the working tree: the
            # vendored copy is imported from the repository, and a cache there would be an artefact
            # of running the tests rather than something to ship.
            env={"PATH": "/usr/bin:/bin"},
        )

    def payload(self) -> dict:
        self.assertEqual(self.result.returncode, 0, self.result.stderr[-800:])
        line = self.result.stdout.strip().splitlines()[-1] if self.result.stdout.strip() else "{}"
        return json.loads(line)

    def test_the_kernel_really_is_absent_from_the_interpreter(self) -> None:
        """Otherwise every assertion below would pass for the wrong reason."""
        self.assertTrue(self.payload()["kernel_absent"])

    def test_every_plugin_that_needs_the_kernel_still_registers_its_tools(self) -> None:
        # All six that vendor the kernel, with the tool count each registers through its
        # entry point: the proof covers `claims` and `consent` too, and a plugin that stops
        # registering fails here rather than at session start. The expected counts are derived
        # from the tree — the list used to be hard-coded while the comment above it claimed to
        # discover plugins, so a seventh plugin was discovered and then failed the comparison
        # for the wrong reason (the internal security audit A19-KERN-2).
        vendoring = sorted(
            plugin.name for plugin in (ROOT / "plugins").iterdir()
            if (plugin / "vendor" / "pantler_core").is_dir()
        )
        expected = {}
        for name in vendoring:
            manifest = ROOT / "plugins" / name / "plugin.yaml"
            tools = [
                line.strip()[2:].strip()
                for line in manifest.read_text(encoding="utf-8").splitlines()
                if line.strip().startswith("- ")
            ]
            expected[name] = sum(1 for tool in tools if not tool.startswith(" "))
        self.assertEqual(sorted(self.payload()["plugins"]), vendoring)
        self.assertEqual(set(self.payload()["plugins"]), set(expected))

    def test_the_shim_says_it_chose_the_vendored_copy(self) -> None:
        sources = set(self.payload()["sources"].values())
        self.assertEqual(sources, {"vendored"})

    def test_the_kernel_comes_from_the_vendored_copy(self) -> None:
        self.assertIn("vendor/pantler_core", self.payload()["kernel_from"])

    def test_the_tools_still_compute_and_still_save(self) -> None:
        payload = self.payload()
        self.assertEqual(payload["spray_record"], {"saved": True, "id": "APP-0001"})
        self.assertEqual(payload["record_save"]["id"], "CERT-0001")
        self.assertTrue(payload["record_save"]["empty"])


if __name__ == "__main__":
    unittest.main()
