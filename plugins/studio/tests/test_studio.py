"""The studio's own suite: library, fonts, type, layout, audit, brand and the tools' boundary.

Stdlib only, the way every plugin suite here runs: the engine's test interpreter may have no image
library, and the renderer has to be testable without one. The SVG path is asserted always; the PNG
path is asserted when Pillow is present and skipped when it is not, so a missing optional dependency
never hides a broken layout.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parent
REPO = PLUGIN.parent.parent
sys.path.insert(0, str(PLUGIN))
sys.path.insert(0, str(PLUGIN.parent))
sys.path.insert(0, str(REPO / "core" / "src"))

from studio_engine import audit, brand as brand_kit, fonts, layout, pages, palette, photos  # noqa: E402
from studio_engine import raster, render, screenshot, svg, templates, text  # noqa: E402
from studio_engine.library import Library, LibraryError  # noqa: E402

LIBRARY_ROOT = PLUGIN / "studio_engine" / "library"


def library() -> Library:
    return Library(LIBRARY_ROOT)


class LibraryTestCase(unittest.TestCase):
    def test_the_library_ships_sixteen_directions_twelve_templates_and_a_palette_for_each(self):
        lib = library()
        self.assertEqual(len(lib.directions), 16)
        self.assertEqual(len(lib.templates), 12)
        self.assertGreaterEqual(len(lib.palettes), 24)
        self.assertGreaterEqual(len(lib.pairings), 10)

    def test_every_direction_points_at_a_palette_and_a_pairing_that_exist(self):
        lib = library()
        for direction in lib.directions.values():
            self.assertIn(direction.palette, lib.palettes, direction.id)
            self.assertIn(direction.type, lib.pairings, direction.id)

    def test_every_palette_clears_the_contrast_floor(self):
        for entry in library().palettes.values():
            ratio = palette.contrast(palette.parse(entry.ink), palette.parse(entry.ground))
            self.assertGreaterEqual(ratio, 4.5, entry.id)

    def test_every_pairing_uses_a_licensed_face(self):
        lib = library()
        for pairing in lib.pairings.values():
            for family in (pairing.display.family, pairing.text.family, pairing.label.family):
                self.assertTrue((PLUGIN / "fonts" / "LICENSES").joinpath(
                    lib.fonts.licence_of(family)).is_file(), family)

    def test_an_unlicensed_family_is_refused(self):
        with self.assertRaises(fonts.FontError):
            library().fonts.face_for("comic-sans", 400)


class FontTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lib = library()
        cls.face = cls.lib.fonts.face("young-serif-400")

    def test_a_space_is_narrower_than_a_cap_and_width_scales_with_size(self):
        space = self.face.width(" ", 100)
        cap = self.face.width("M", 100)
        self.assertGreater(cap, space)
        self.assertAlmostEqual(self.face.width("M", 200), cap * 2, places=3)

    def test_size_for_width_inverts_width(self):
        target = 400.0
        size = self.face.size_for_width("Saturday", target)
        self.assertAlmostEqual(self.face.width("Saturday", size), target, places=2)

    def test_a_script_the_face_lacks_is_reported_not_drawn_as_tofu(self):
        self.assertFalse(self.face.covers("\u4e2d"))
        self.assertTrue(self.face.covers("Saturday"))

    def test_tracking_widens_a_tracked_label(self):
        plain = self.face.width("MARKET", 24)
        tracked = self.face.width("MARKET", 24, 0.2)
        self.assertGreater(tracked, plain)


class TextTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.face = library().fonts.face("young-serif-400")

    def test_a_wrapped_line_never_exceeds_the_column(self):
        lines = text.wrap("Lettuce, broccoli, cauliflower and silverbeet from the north block",
                          self.face, 60, 600)
        for line in lines:
            self.assertLessEqual(self.face.width(line, 60), 600)

    def test_a_two_line_headline_beats_an_orphaned_three_line_one(self):
        fitted = text.balanced("Local veggie boxes", self.face, 874, 153, 60, max_lines=3)
        self.assertTrue(fitted.fits)
        self.assertLessEqual(len(fitted.lines), 2)
        self.assertFalse(fitted.widows)

    def test_impossible_copy_is_reported_rather_than_silently_shrunk(self):
        fitted = text.balanced("a" * 40, self.face, 200, 100, 80, max_lines=2)
        self.assertFalse(fitted.fits)
        self.assertGreater(fitted.overflow, 0)


class LayoutTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lib = library()

    def spec(self, **overrides) -> dict:
        base = {
            "template": "feed-square-day",
            "direction": "01-quiet-ledger",
            "content": {"headline": "Local veggie boxes", "day": "Every Thursday"},
            "out": "output/design/test",
        }
        base.update(overrides)
        return base

    def test_a_valid_brief_resolves(self):
        spec = layout.resolve(self.spec(), self.lib, {})
        self.assertEqual((spec.width, spec.height), (1080, 1080))

    def test_an_unknown_key_is_refused_not_ignored(self):
        with self.assertRaises(layout.LayoutError):
            layout.resolve(self.spec(coordinate="10,10"), self.lib, {})

    def test_missing_required_content_is_refused(self):
        with self.assertRaises(layout.LayoutError):
            layout.resolve(self.spec(content={"headline": "Only a headline"}), self.lib, {})

    def test_low_contrast_operator_palette_is_refused(self):
        with self.assertRaises(layout.LayoutError):
            layout.resolve(
                self.spec(palette={"ground": "#EEEEEE", "ink": "#CCCCCC", "accent": "#CCCCCC"}),
                self.lib,
                {},
            )

    def test_an_unknown_template_names_the_library(self):
        with self.assertRaises(LibraryError):
            layout.resolve(self.spec(template="no-such-card"), self.lib, {})


class RenderTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lib = library()

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.tmp = Path(self._tmp.name)
        self.workspace = self.tmp / "workspace"
        self.workspace.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def render(self, **overrides) -> dict:
        spec = {
            "template": "feed-square-day",
            "direction": "01-quiet-ledger",
            "content": {
                "eyebrow": "Availability",
                "headline": "Local veggie boxes",
                "day": "Every Thursday",
                "footer": "BELLVIEW FARM",
            },
            "out": "output/design/test",
        }
        spec.update(overrides)
        if spec.get("direction") is None:
            spec.pop("direction", None)
        return render.job(spec, self.workspace, self.lib)

    def test_the_job_writes_a_self_contained_svg_and_a_report(self):
        report = self.render()
        out = self.workspace / "output" / "design" / "test"
        self.assertTrue(report["ok"], [c for c in report["failures"]])
        self.assertTrue((out / "card.svg").is_file())
        self.assertTrue((out / "report.json").is_file())
        self.assertTrue((out / "brief.json").is_file())
        svg_text = (out / "card.svg").read_text()
        self.assertNotIn('href="http', svg_text)
        self.assertIn("data:font/ttf;base64,", svg_text)
        root = ET.fromstring(svg_text)
        self.assertEqual(root.attrib["width"], "1080")
        self.assertEqual(len(root.findall(".//{http://www.w3.org/2000/svg}text")) > 0, True)

    def test_the_png_is_exactly_the_requested_size_when_pillow_is_present(self):
        if not raster.available():
            self.skipTest("Pillow is not available in this interpreter")
        report = self.render()
        from PIL import Image

        with Image.open(report["files"]["png"]) as image:
            self.assertEqual(image.size, (1080, 1080))
        self.assertLess((self.workspace / "output/design/test/card.png").stat().st_size, 5 * 1024 * 1024)

    def test_every_template_draws_and_passes_its_hard_checks(self):
        cases = {
            "feed-square-day": {"headline": "Local veggie boxes", "day": "Every Thursday"},
            "feed-square-list": {"headline": "What's ready", "items": ["Lettuce | 12", "Broccoli | 8"]},
            "portrait-availability": {"headline": "This week", "items": ["Lettuce", "Kale", "Radish",
                                                                        "Silverbeet", "Fennel"]},
            "story-announcement": {"headline": "The first of the season", "day": "At the market Saturday"},
            "market-day": {"day": "Saturday", "venue": "Pomona markets", "time": "7am"},
            "quote-card": {"quote": "The best garlic I have cooked with.", "attribution": "M. Nguyen"},
            "price-board": {"headline": "Prices", "items": ["Garlic | $18/kg", "Honey | $14"]},
            "carousel-cover": {"headline": "Start with the hardneck", "number": "01"},
        }
        directions = ["01-quiet-ledger", "03-pantry-shelf", "08-produce-catalogue",
                      "09-seasonal-almanac", "06-bread-and-ledger", "04-long-table",
                      "11-apothecary", "16-paper-bag"]
        for (template_id, content), direction in zip(cases.items(), directions):
            with self.subTest(template=template_id):
                report = self.render(template=template_id, direction=direction, content=content,
                                     out=f"output/design/{template_id}")
                self.assertTrue(report["ok"], [c for c in report["failures"]])

    def test_the_print_templates_are_the_physical_size_they_claim(self):
        cases = {
            "poster-a3": ({"headline": "Hardneck, picked this week", "day": "At the market Saturday"},
                          (297.0, 420.0)),
            "sign-a3": ({"day": "Saturday", "venue": "Pomona markets"}, (420.0, 297.0)),
            "menu-a4": ({"headline": "This week", "items": ["Garlic | $18/kg"]}, (210.0, 297.0)),
            "label-proof": ({"headline": "Bellview garlic"}, (100.0, 150.0)),
        }
        for template_id, (content, mm) in cases.items():
            with self.subTest(template=template_id):
                report = self.render(template=template_id, direction="11-apothecary",
                                     content=content, out=f"output/print/{template_id}")
                self.assertTrue(report["ok"], [c for c in report["failures"]])
                self.assertEqual(tuple(report["physical_mm"]), mm)
                svg_text = (self.workspace / f"output/print/{template_id}/card.svg").read_text()
                self.assertIn(f'width="{mm[0]:.1f}mm"', svg_text)

    def test_a_label_proof_reports_the_particulars_it_cannot_supply(self):
        report = self.render(template="label-proof", direction="11-apothecary",
                             content={"headline": "Bellview garlic"}, out="output/print/label")
        self.assertIn("[NET WEIGHT]", report["placeholders"])
        self.assertIn("[INGREDIENTS]", report["placeholders"])

    def test_a_branded_card_signs_itself_with_the_brand_name(self):
        report = render.job(
            {
                "template": "feed-square-day",
                "direction": "01-quiet-ledger",
                "content": {"headline": "Local veggie boxes", "day": "Every Thursday"},
                "out": "output/design/branded",
            },
            self.workspace,
            self.lib,
            {"name": "Bellview Garlic"},
        )
        self.assertTrue(report["ok"], [c["id"] for c in report["failures"]])
        self.assertEqual(report["content"]["footer"], "Bellview Garlic")

    def test_a_placeholder_is_reported_not_hidden(self):
        report = self.render(content={"headline": "Boxes from [TOWN]", "day": "Every Thursday"})
        self.assertIn("[TOWN]", report["placeholders"])


class AuditTestCase(unittest.TestCase):
    def test_low_contrast_is_a_hard_failure(self):
        result = palette.validate_pair("#DDDDDD", "#FFFFFF")
        self.assertFalse(result["ok"])

    def test_placeholders_are_found_in_the_copy(self):
        matches = audit.PLACEHOLDER.findall("Pickup at [TOWN] on [DAY]")
        self.assertEqual(matches, ["[TOWN]", "[DAY]"])

    def test_a_composition_with_four_type_sizes_is_soft_flagged(self):
        lib = library()
        spec = layout.resolve(
            {
                "template": "price-board",
                "direction": "11-apothecary",
                "content": {"headline": "Prices", "items": ["Garlic | $18/kg", "Honey | $14"],
                            "price_note": "GST included"},
                "out": "output/design/audit",
            },
            lib,
            {},
        )
        checks = {item["id"]: item for item in audit.check(templates.compose(spec, lib), spec)}
        self.assertFalse(checks["type.scale"]["hard"])


class BrandTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lib = library()

    def test_the_interview_offers_three_different_directions(self):
        candidates = brand_kit.derive({"posture": "warm", "kind": "preserves"}, self.lib)
        self.assertEqual(len(candidates), 3)
        self.assertEqual(len({candidate.direction.id for candidate in candidates}), 3)

    def test_a_kit_without_a_name_is_refused(self):
        with self.assertRaises(brand_kit.BrandError):
            brand_kit.Brand.from_dict({"tagline": "no name"})

    def test_a_kit_with_low_contrast_is_reported(self):
        kit = brand_kit.Brand(
            name="Bellview", palette="pantry-sand", type="young-serif-mono",
            colours={"ground": "#FFFFFF", "ink": "#EEEEEE", "accent": "#CCCCCC"},
        )
        problems = brand_kit.validate(kit, self.lib)
        self.assertTrue(any("4.5:1" in problem for problem in problems), problems)

    def test_a_kit_round_trips_and_its_sheet_and_lockups_compose(self):
        kit = brand_kit.Brand(
            name="Bellview Garlic", tagline="Hardneck, from the hills", palette="pantry-sand",
            type="young-serif-mono", direction="03-pantry-shelf",
            colours={"ground": "#EDE3D0", "ink": "#1B2420", "accent": "#6E3B52",
                     "accent2": "#C9922E"},
            status="starter",
        )
        self.assertEqual(brand_kit.validate(kit, self.lib), [])
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = brand_kit.save(kit, Path(tmp) / "brand.json")
            again = brand_kit.load(path)
        self.assertEqual(again.name, kit.name)
        self.assertTrue(brand_kit.sheet(again, self.lib).ops)
        for layout_name in ("horizontal", "stacked", "monogram"):
            self.assertTrue(brand_kit.lockup(again, self.lib, layout_name).ops)


class PageTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lib = library()

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def brief(self, **overrides) -> dict:
        spec = {
            "blueprint": "producer",
            "out": "output/site",
            "content": {
                "name": "Bellview Garlic",
                "tagline": "Hardneck, from the hills",
                "opening": "Garlic grown on the hills at Bellview.",
                "sections": [
                    {"kind": "list", "title": "What's ready", "items": ["Garlic | $18/kg"]},
                    {"kind": "contact", "title": "Find us", "lines": ["Pomona markets"]},
                ],
                "footer": "Bellview Garlic",
            },
        }
        spec.update(overrides)
        return spec

    def test_a_producer_page_passes_its_checks_and_copies_its_fonts(self):
        report = render.page_job(self.brief(), self.tmp, self.lib, None, previews=False)
        self.assertTrue(report["ok"], [c["id"] for c in report["failures"]])
        html = (self.tmp / "output/site/index.html").read_text()
        self.assertEqual(html.count("<h1"), 1)
        self.assertNotIn("<script", html)
        self.assertNotIn("http://", html)
        self.assertNotIn("https://", html)
        self.assertTrue((self.tmp / "output/site/assets/fonts").is_dir())
        self.assertTrue(list((self.tmp / "output/site/assets/fonts").glob("*.ttf")))

    def test_a_page_with_no_way_to_contact_is_refused(self):
        spec = self.brief()
        spec["content"]["sections"] = [{"kind": "list", "items": ["Garlic"]}]
        with self.assertRaises(pages.PageError):
            pages.build(spec, self.lib, None, self.tmp / "site")

    def test_an_order_page_needs_an_action(self):
        spec = self.brief(blueprint="order")
        with self.assertRaises(pages.PageError):
            pages.build(spec, self.lib, None, self.tmp / "site")

    def test_an_image_without_alt_is_refused(self):
        spec = self.brief()
        image = self.tmp / "photo.jpg"
        image.write_bytes(b"\xff\xd8\xff\xd9")
        spec["content"]["image"] = {"path": str(image)}
        with self.assertRaises(pages.PageError):
            pages.build(spec, self.lib, None, self.tmp / "site")

    def test_an_unknown_section_kind_is_refused(self):
        spec = self.brief()
        spec["content"]["sections"].append({"kind": "carousel"})
        with self.assertRaises(pages.PageError):
            pages.build(spec, self.lib, None, self.tmp / "site")

    def test_a_placeholder_is_reported_not_published_quietly(self):
        spec = self.brief()
        spec["content"]["opening"] = "Boxes from [TOWN], every Thursday."
        report = render.page_job(spec, self.tmp, self.lib, None, previews=False)
        self.assertIn("[TOWN]", report["placeholders"])

    def test_no_browser_is_a_sentence_not_a_crash(self):
        with self.assertRaises(screenshot.ScreenshotError):
            screenshot.capture(self.tmp / "missing.html", self.tmp / "shot.png", 800, 600,
                               browser=Path("/nonexistent-chrome"))


class ToolTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.tmp = Path(self._tmp.name)
        os.environ["PANTLER_WORKSPACE"] = str(self.tmp)
        import studio as plugin_package

        self.tools = plugin_package.tools
        plugin_package.tools._LIBRARY = None

    def tearDown(self):
        os.environ.pop("PANTLER_WORKSPACE", None)
        self._tmp.cleanup()

    def test_the_library_lists_in_one_call(self):
        payload = json.loads(self.tools.design_templates({"section": "templates"}))
        self.assertTrue(payload["success"])
        self.assertEqual(len(payload["templates"]), 12)

    def test_a_bad_brief_comes_back_as_a_sentence(self):
        payload = json.loads(self.tools.design_render({"spec": {"template": "nope"}}))
        self.assertFalse(payload["success"])
        self.assertIn("template", payload["error"])

    def test_a_design_outside_the_workspace_is_refused(self):
        payload = json.loads(
            self.tools.design_render(
                {
                    "spec": {
                        "template": "feed-square-day",
                        "direction": "01-quiet-ledger",
                        "content": {"headline": "Local veggie boxes", "day": "Every Thursday"},
                        "out": "../../elsewhere",
                    }
                }
            )
        )
        self.assertFalse(payload["success"])
        self.assertIn("outside this business's workspace", payload["error"])

    def test_a_render_inside_the_workspace_succeeds(self):
        payload = json.loads(
            self.tools.design_render(
                {
                    "spec": {
                        "template": "feed-square-day",
                        "direction": "01-quiet-ledger",
                        "content": {"headline": "Local veggie boxes", "day": "Every Thursday"},
                        "out": "output/design/ok",
                    }
                }
            )
        )
        self.assertTrue(payload["success"], payload.get("error"))
        self.assertTrue(Path(payload["files"]["svg"]).is_file())

    def test_photos_without_an_image_library_say_so(self):
        if photos.available():
            self.skipTest("Pillow is present, so the refusal path does not apply")
        payload = json.loads(self.tools.photo_prepare({"inputs": ["missing.jpg"]}))
        self.assertFalse(payload["success"])
        self.assertIn("does not exist", payload["error"])

    def test_the_workspace_is_the_active_profiles_terminal_cwd_not_the_host_home(self):
        host = self.tmp / "host"
        profile = host / "profiles" / "pantler"
        workspace = self.tmp / "workspace" / "pantler"
        workspace.mkdir(parents=True)
        profile.mkdir(parents=True)
        (host / "profiles").mkdir(parents=True, exist_ok=True)
        (host / "active_profile").write_text("pantler\n", encoding="utf-8")
        (profile / "config.yaml").write_text(
            f"terminal:\n  cwd: {workspace}\n", encoding="utf-8"
        )
        previous_home = os.environ.get("HERMES_HOME")
        os.environ["HERMES_HOME"] = str(host)
        os.environ.pop("PANTLER_WORKSPACE", None)
        try:
            self.assertEqual(self.tools._workspace(), workspace.resolve())
        finally:
            if previous_home is None:
                os.environ.pop("HERMES_HOME", None)
            else:
                os.environ["HERMES_HOME"] = previous_home
            os.environ["PANTLER_WORKSPACE"] = str(self.tmp)

    def test_a_page_outside_the_workspace_is_refused(self):
        payload = json.loads(
            self.tools.design_page(
                {
                    "spec": {
                        "blueprint": "producer",
                        "content": {"name": "Bellview", "opening": "Garlic.",
                                    "sections": [{"kind": "contact", "lines": ["Pomona"]}]},
                        "out": "../site",
                    }
                }
            )
        )
        self.assertFalse(payload["success"])
        self.assertIn("outside this business's workspace", payload["error"])

    def test_a_page_inside_the_workspace_builds(self):
        payload = json.loads(
            self.tools.design_page(
                {
                    "spec": {
                        "blueprint": "producer",
                        "content": {"name": "Bellview", "opening": "Garlic.",
                                    "sections": [{"kind": "contact", "lines": ["Pomona"]}]},
                        "out": "output/site",
                    },
                    "previews": False,
                }
            )
        )
        self.assertTrue(payload["success"], payload.get("error"))
        self.assertTrue(Path(payload["files"]["html"]).is_file())

    def test_the_brand_interview_needs_a_name(self):
        payload = json.loads(self.tools.design_brand({"stage": "directions", "answers": {}}))
        self.assertFalse(payload["success"])
        self.assertIn("name", payload["error"])


if __name__ == "__main__":
    unittest.main()
