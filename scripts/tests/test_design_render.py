"""The design skill's renderer: exact sizes, a readable card, and a refusing palette.

The renderer needs Pillow and a system font. The engine's own interpreter has Pillow; the
stdlib test runner may not, so the suite skips rather than failing for a missing optional
dependency. The checks that do run are the ones that matter: the PNG is the requested size,
the layout assertions pass, and a low-contrast palette is refused instead of shipped.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RENDERER = ROOT / "distribution" / "skills" / "design" / "scripts" / "render_card.py"

try:
    from PIL import Image
except ImportError:  # pragma: no cover - depends on the interpreter
    Image = None


def load_renderer():
    spec = importlib.util.spec_from_file_location("pantler_design_render", RENDERER)
    module = importlib.util.module_from_spec(spec)
    sys.modules["pantler_design_render"] = module
    spec.loader.exec_module(module)
    return module


@unittest.skipIf(Image is None, "Pillow is not available in this interpreter")
class RendererTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.render = load_renderer()

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def render_to(self, name: str, **kwargs) -> tuple[Path, str]:
        out = self.tmp / f"{name}.png"
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            ok = self.render.render(out=str(out), **kwargs)
        self.assertTrue(ok, buffer.getvalue())
        self.assertNotIn("FAIL", buffer.getvalue())
        return out, buffer.getvalue()

    def test_a_square_day_card_is_the_requested_size(self) -> None:
        out, output = self.render_to(
            "day", headline="Local veggie boxes", day="Every Thursday", size=(1080, 1080)
        )
        self.assertTrue(out.is_file())
        with Image.open(out) as image:
            self.assertEqual(image.size, (1080, 1080))
        self.assertIn("wrote", output)

    def test_a_portrait_list_card_is_the_requested_size(self) -> None:
        out, _ = self.render_to(
            "list",
            headline="This week",
            items=["Lettuce", "Broccoli", "Cauliflower"],
            eyebrow="AVAILABILITY",
            footer="WEEK OF 19 OCTOBER",
            size=(1080, 1350),
        )
        with Image.open(out) as image:
            self.assertEqual(image.size, (1080, 1350))

    def test_a_low_contrast_palette_is_refused(self) -> None:
        with self.assertRaises(self.render.RenderError):
            self.render.render(
                out=str(self.tmp / "bad.png"),
                headline="Low contrast",
                day="Never",
                ground="#F7F3EA",
                ink="#F0EADF",
            )

    def test_a_card_with_no_band_is_refused(self) -> None:
        with self.assertRaises(self.render.RenderError):
            self.render.render(out=str(self.tmp / "empty.png"), headline="Nothing to say")

    def test_size_parsing_accepts_the_three_usual_shapes(self) -> None:
        self.assertEqual(self.render._parse_size("1080x1080"), (1080, 1080))
        self.assertEqual(self.render._parse_size("1080x1350"), (1080, 1350))
        self.assertEqual(self.render._parse_size("1200x627"), (1200, 627))
        with self.assertRaises(Exception):
            self.render._parse_size("1080")


if __name__ == "__main__":
    unittest.main()
