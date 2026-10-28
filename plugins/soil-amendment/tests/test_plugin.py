"""Smoke-test the plugin exactly as Hermes loads it: import the plugin package,
call register(ctx) against a stub context, then call the tool handlers.

Run with the standard library:

    python3 -m unittest discover -s tests -t tests -v
"""
import importlib.util
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
FIXTURES = os.path.join(HERE, "fixtures")

MULTI = os.path.join(FIXTURES, "example-soil-multi-sample.csv")
SINGLE = os.path.join(FIXTURES, "example-soil-single-sample.csv")
BARE = os.path.join(FIXTURES, "example-soil-no-texture-no-depth.csv")
PLANT = os.path.join(FIXTURES, "example-plant-tissue.csv")


class StubCtx:
    """Records what register(ctx) asks for, without a live Hermes."""

    def __init__(self):
        self.tools: list = []
        self.skills: list = []

    def register_tool(self, **kw):
        self.tools.append(kw)

    def register_skill(self, name, path):
        self.skills.append((name, str(path)))

    def get_config(self):
        return dict(getattr(self, "settings", {}))


def load_plugin():
    """Load the plugin package from its __init__.py, as Hermes does.

    Cached submodules are purged first: `from . import tools` resolves through `sys.modules`, so
    without this a second load would share the first one's `tools` module — and the module-level
    `_CTX` those tests set would leak into every later test.
    """
    for name in [
        n for n in sys.modules
        if n == "soil_amendment_plugin" or n.startswith("soil_amendment_plugin.")
    ]:
        del sys.modules[name]
    init = os.path.join(PLUGIN, "__init__.py")
    if not os.path.isfile(init):
        raise RuntimeError(f"plugin not found at {PLUGIN}")
    spec = importlib.util.spec_from_file_location(
        "soil_amendment_plugin", init,
        submodule_search_locations=[PLUGIN])
    mod = importlib.util.module_from_spec(spec)
    sys.modules["soil_amendment_plugin"] = mod
    spec.loader.exec_module(mod)
    return mod


MOD = None
CTX = None


def setUpModule():
    global MOD, CTX
    MOD = load_plugin()
    CTX = StubCtx()
    MOD.register(CTX)


class TestPlugin(unittest.TestCase):

    def test_two_tools_and_a_skill_are_registered(self):
        self.assertTrue(os.path.isfile(os.path.join(PLUGIN, "__init__.py")))
        self.assertEqual({t["name"] for t in CTX.tools},
                         {"soil_amendment", "soil_test_read"},
                         "expected two tools registered")
        self.assertTrue(CTX.skills, "no skill registered by the plugin")

    def test_every_tool_schema_has_a_description(self):
        for t in CTX.tools:
            with self.subTest(tool=t["name"]):
                self.assertTrue(t.get("schema", {}).get("description"),
                                f"{t['name']} has no model-facing description")

    def test_full_recommendation(self):
        r = json.loads(MOD.tools.soil_amendment({"coa_path": MULTI, "crop": "Example"}))
        self.assertTrue(r["success"], r)
        s = r["samples"][0]
        self.assertEqual(s["analysis"]["ppm_to_kgha_factor"], 2.175,
                         "expected a derived factor of 2.175 for clay loam at 15 cm")
        self.assertIn("instructions", r,
                      "response must instruct the model not to recalculate")
        # every rule code that fired must carry wording for the narrative layer
        for code in s["rule_codes"]:
            with self.subTest(code=code):
                self.assertIn(code, s["rule_text"], f"rule code '{code}' has no wording")
                self.assertTrue(s["rule_text"][code],
                                f"rule code '{code}' has no wording")

    def test_single_sample_layout(self):
        r2 = json.loads(MOD.tools.soil_amendment({"coa_path": SINGLE}))
        self.assertTrue(r2["success"], r2)
        self.assertEqual(len(r2["samples"]), 1,
                         "method-first fixture should describe one sample")

    def test_no_texture_no_depth_defaults(self):
        r3 = json.loads(MOD.tools.soil_amendment({"coa_path": BARE}))
        self.assertTrue(r3["success"], r3)
        a3 = r3["samples"][0]["analysis"]
        self.assertTrue(a3["bulk_density_is_default"],
                        "bulk density should be flagged as defaulted")
        self.assertFalse(a3["sampling_depth_is_explicit"],
                         "missing depth should be flagged as not explicit")

    def test_read_only_tool_returns_no_program(self):
        r4 = json.loads(MOD.tools.soil_test_read({"coa_path": MULTI, "sample": 2}))
        self.assertTrue(r4["success"], r4)
        self.assertNotIn("recommendation", r4["samples"][0],
                         "soil_test_read must not produce a program")

    def test_a_hostile_argument_is_refused_rather_than_raised(self):
        """Every one of these used to escape the handler as an exception.

        The model supplies these values, so "the model would not do that" is not a defence: a
        readable non-JSON profile was a `JSONDecodeError`, a zero factor a `ZeroDivisionError`, a
        NaN a bare `NaN` in the JSON, and a negative sample index silently read a *different*
        sample from the end of the list (the internal audit PLUG-8).
        """
        hostile = (
            ("profile", "/etc/hostname"),
            ("factor", 0),
            ("factor", -2.5),
            ("factor", float("nan")),
            ("factor", float("inf")),
            ("bulk_density", 0),
            ("bulk_density", -1.5),
            ("depth_cm", -100),
            ("sample", 0),
            ("sample", -2),
            ("sample", 99),
            ("sample", "not a number"),
            ("area_ha", 0),
        )
        for key, value in hostile:
            with self.subTest(argument=f"{key}={value!r}"):
                answer = json.loads(MOD.tools.soil_amendment({"coa_path": SINGLE, key: value}))
                self.assertFalse(answer["success"], answer)
                self.assertTrue(answer.get("error"), answer)
                self.assertNotIn("Traceback", json.dumps(answer))

    def test_a_sane_override_is_still_honoured(self):
        # This fixture carries no texture, so the factor is depth × the default bulk density
        # (1.55) ÷ 10: 30 cm × 1.55 ÷ 10 = 4.65. The point of the test is that a *valid*
        # override still reaches the engine after the validation above.
        answer = json.loads(
            MOD.tools.soil_amendment({"coa_path": SINGLE, "sample": 1, "depth_cm": 30})
        )
        self.assertTrue(answer["success"], answer)
        self.assertAlmostEqual(
            answer["samples"][0]["analysis"]["ppm_to_kgha_factor"], 4.65, places=6
        )

    def test_plant_tissue_is_refused(self):
        r5 = json.loads(MOD.tools.soil_amendment({"coa_path": PLANT}))
        self.assertFalse(r5["success"], "plant tissue test must be refused")

    def test_missing_file_returns_an_error(self):
        r6 = json.loads(MOD.tools.soil_amendment({"coa_path": "does-not-exist.csv"}))
        self.assertFalse(r6["success"], "missing file must return an error")

    def test_out_of_range_sample_returns_an_error(self):
        r7 = json.loads(MOD.tools.soil_amendment({"coa_path": MULTI, "sample": 99}))
        self.assertFalse(r7["success"], "out-of-range sample index must return an error")

    def test_soil_test_read_refuses_a_zero_or_negative_sample_index(self):
        """`sample: 0` returned the *last* sample and `-1` the second-to-last, silently.

        The sibling tool validated the same argument; this is that validation, shared
        (the internal security audit A19-PLUG-10).
        """
        for value in (0, -1, -2, 99, "not a number"):
            with self.subTest(sample=value):
                answer = json.loads(
                    MOD.tools.soil_test_read({"coa_path": MULTI, "sample": value})
                )
                self.assertFalse(answer["success"], answer)
                self.assertIn("sample", answer["error"])

    def test_soil_test_read_still_reads_the_sample_that_was_named(self):
        answer = json.loads(MOD.tools.soil_test_read({"coa_path": MULTI, "sample": 2}))
        self.assertTrue(answer["success"], answer)
        self.assertEqual(len(answer["samples"]), 1)
        self.assertEqual(answer["samples"][0]["sample_id"], "South Block")

    def test_a_model_supplied_profile_path_is_refused(self):
        """`profile: "../../../etc/hostname"` used to open, then report a JSON error.

        A model-supplied profile is a *name* inside the plugin's own `profiles/`; a path is the
        whole ceiling check gone (the internal security audit A19-PLUG-3).
        """
        for name in ("/etc/hostname", "../../../etc/hostname", "profiles/default"):
            with self.subTest(profile=name):
                answer = json.loads(MOD.tools.soil_amendment({"coa_path": SINGLE, "profile": name}))
                self.assertFalse(answer["success"], answer)
                self.assertIn("not a name", answer["error"])
        # The shipped name still loads through the same argument.
        ok = json.loads(MOD.tools.soil_amendment({"coa_path": SINGLE, "profile": "default"}))
        self.assertTrue(ok["success"], ok)

    @staticmethod
    def _write_coa(path, columns, rows=1, name_len=30):
        """A synthetic EAL Layout-A file with `1 + columns` sample columns."""
        header = ["Parameter", "Unit", "Method Reference", "LOR"] + [
            f"S{i}" for i in range(columns)
        ]
        lines = ["Report ID,E26-00-0000_TEST_1,", "Client Sample ID:,", ",".join(header)]
        for i in range(rows):
            lines.append(
                ",".join(
                    [f"Parameter {i:05d}".ljust(name_len, "x"), "mg/kg", "Inhouse S1", "<1"]
                    + ["1.5"] * columns
                )
            )
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")

    def test_a_wide_certificate_is_refused_with_the_count(self):
        """A crafted CoA is bounded at the reader, with a sentence that names the count.

        The audit's file had 40,000 value columns and produced a 226 MB tool result
        (the internal security audit A19-PLUG-7).
        """
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "wide.csv")
            self._write_coa(path, columns=120)
            answer = json.loads(MOD.tools.soil_test_read({"coa_path": path}))
        self.assertFalse(answer["success"], answer)
        self.assertIn("120", answer["error"])
        self.assertIn("50", answer["error"])

    def test_an_answer_too_large_for_a_transcript_is_refused_with_its_size(self):
        """Inside the reader's caps a file can still be wide enough to flood the context.

        The reader's caps bound the input; this is what bounds the output
        (the internal security audit A19-PLUG-7).
        """
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "many.csv")
            self._write_coa(path, columns=50, rows=1990, name_len=40)
            answer = json.loads(MOD.tools.soil_test_read({"coa_path": path}))
        self.assertFalse(answer["success"], answer)
        self.assertIn("characters", answer["error"])
        self.assertIn("2,000,000", answer["error"])

    def test_context_flags_reach_the_engine(self):
        r8 = json.loads(MOD.tools.soil_amendment({
            "coa_path": MULTI, "sample": 1, "is_legume": True,
            "copper_fungicide_history": True, "certification": "organic"}))
        codes = r8["samples"][0]["rule_codes"]
        for expected in ("legume_omit_n", "copper_history", "certification_check"):
            with self.subTest(code=expected):
                self.assertIn(expected, codes,
                              f"context flag '{expected}' did not fire")


if __name__ == "__main__":
    unittest.main()


class PerKeyCtx(StubCtx):
    """The engine's own reader: `ctx.get_config(key, default)`, live on every call."""

    def __init__(self, **settings):
        super().__init__()
        self.settings = settings

    def get_config(self, key=None, default=None):  # type: ignore[override]
        if key is None:
            return dict(self.settings)  # an older whole-block reader
        return self.settings.get(key, default)


class TestCapabilitySwitch(unittest.TestCase):
    """The live half of the capability switch.

    The engine's plugin list is restart-grade — "there is no un-wire primitive, so a running
    gateway keeps the plugin's handlers until restart" — so a tool registered before the switch
    stays callable until then. The handler reads `capability_enabled` per call and refuses; a
    switch that only hides a tool is a lie the first time a conversation outlives it.
    """

    def load(self, **settings):
        mod = load_plugin()
        ctx = PerKeyCtx(**settings)
        mod.register(ctx)
        return mod

    def test_a_switched_off_capability_refuses_before_reading_anything(self):
        mod = self.load(capability_enabled=False)
        for tool in ("soil_amendment", "soil_test_read"):
            with self.subTest(tool=tool):
                r = json.loads(getattr(mod.tools, tool)({"coa_path": "/no/such/file.csv"}))
                self.assertFalse(r["success"])
                self.assertIn("switched off in Capabilities", r["error"])
                # It refused instead of reporting the missing file the work would have found.
                self.assertNotIn("no such file", r["error"])

    def test_the_switch_is_read_per_call_not_at_registration(self):
        mod = self.load(capability_enabled=True)
        self.assertTrue(json.loads(mod.tools.soil_test_read({"coa_path": SINGLE}))["success"])
        mod.tools._CTX.settings["capability_enabled"] = False
        refused = json.loads(mod.tools.soil_test_read({"coa_path": SINGLE}))
        self.assertIn("switched off in Capabilities", refused["error"])

    def test_the_flag_accepts_the_spellings_a_hand_edited_file_may_carry(self):
        for value in (False, "false", "off", "no"):
            with self.subTest(value=value):
                mod = self.load(capability_enabled=value)
                r = json.loads(mod.tools.soil_test_read({"coa_path": SINGLE}))
                self.assertIn("switched off", r["error"])

    def test_an_absent_flag_is_on(self):
        mod = self.load()
        self.assertTrue(json.loads(mod.tools.soil_test_read({"coa_path": SINGLE}))["success"])

    def test_the_old_block_reader_still_works(self):
        mod = load_plugin()
        ctx = StubCtx()
        ctx.settings = {"capability_enabled": False}
        mod.register(ctx)
        r = json.loads(mod.tools.soil_test_read({"coa_path": SINGLE}))
        self.assertIn("switched off", r["error"])
