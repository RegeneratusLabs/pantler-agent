"""The operator's own photographs, made ready without being changed.

A food business's photos are usually a phone shot of a crate under a fluoro light. What helps is a
crop, a straight horizon, a warmer white balance and the right aspect ratio for the feed — not a
generated picture of produce the business does not have. Nothing here invents an image, and nothing
removes a feature: a photo of a person still needs the consent record before it goes on a card.

Pillow is a core engine dependency; if it is missing the tool says so in a sentence rather than
failing mid-write.
"""

from __future__ import annotations

from pathlib import Path

SQUARE = (1080, 1080)
PORTRAIT = (1080, 1350)


class PhotoError(ValueError):
    """A file that is not an image, or an operation the operator did not mean."""


def available() -> bool:
    try:
        import PIL  # noqa: F401
    except Exception:
        return False
    return True


def _open(path: Path):
    from PIL import Image, ImageOps

    try:
        image = Image.open(path)
    except Exception as exc:
        raise PhotoError(f"{path.name} is not an image the studio can read: {exc}") from exc
    image = ImageOps.exif_transpose(image).convert("RGB")
    return image


def _cover(image, size: tuple[int, int], focus: tuple[float, float] = (0.5, 0.5)):
    from PIL import Image

    target_w, target_h = size
    scale = max(target_w / image.width, target_h / image.height)
    resized = image.resize(
        (max(target_w, int(round(image.width * scale))),
         max(target_h, int(round(image.height * scale)))),
        Image.LANCZOS,
    )
    fx, fy = focus
    left = int(max(0, min(resized.width - target_w, resized.width * fx - target_w / 2)))
    top = int(max(0, min(resized.height - target_h, resized.height * fy - target_h / 2)))
    return resized.crop((left, top, left + target_w, top + target_h))


def clean(path: Path, out_dir: Path, max_edge: int = 2400, quality: int = 88) -> dict:
    """Orientation, size and metadata only. The picture is the operator's."""
    from PIL import Image

    image = _open(path)
    scale = min(1.0, max_edge / max(image.width, image.height))
    if scale < 1.0:
        image = image.resize((int(image.width * scale), int(image.height * scale)), Image.LANCZOS)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{path.stem}-clean.jpg"
    image.save(target, "JPEG", quality=quality, optimize=True, progressive=True)
    return {"source": str(path), "output": str(target), "size": [image.width, image.height]}


def social_crops(path: Path, out_dir: Path, focus: tuple[float, float] = (0.5, 0.5)) -> list[dict]:
    image = _open(path)
    out_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []
    for name, size in (("square", SQUARE), ("portrait", PORTRAIT)):
        crop = _cover(image, size, focus)
        target = out_dir / f"{path.stem}-{name}.jpg"
        crop.save(target, "JPEG", quality=90, optimize=True, progressive=True)
        results.append(
            {"source": str(path), "output": str(target), "size": list(size), "crop": name}
        )
    return results


def contact_sheet(paths: list[Path], out: Path, library, columns: int = 3,
                  thumb: int = 520) -> dict:
    """One page of thumbnails, named, so the operator can choose rather than guess."""
    from PIL import Image, ImageDraw, ImageFont

    rows = (len(paths) + columns - 1) // columns
    gap = 24
    label_h = 54
    width = columns * thumb + (columns + 1) * gap
    height = rows * (thumb + label_h) + (rows + 1) * gap
    sheet = Image.new("RGB", (width, height), (24, 26, 26))
    draw = ImageDraw.Draw(sheet)
    face_path = library.face_for("barlow", 500).path
    try:
        font = ImageFont.truetype(str(face_path), 22)
    except Exception:  # pragma: no cover - a broken install
        font = ImageFont.load_default()
    for index, path in enumerate(paths):
        row, column = divmod(index, columns)
        x = gap + column * (thumb + gap)
        y = gap + row * (thumb + label_h + gap)
        image = _cover(_open(path), (thumb, thumb))
        sheet.paste(image, (x, y))
        draw.text((x + 2, y + thumb + 10), path.name[:38], font=font, fill=(236, 231, 222))
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, "PNG", optimize=True)
    return {"output": str(out), "size": [width, height], "count": len(paths)}


def prepare(inputs: list[Path], out_dir: Path, mode: str, focus=(0.5, 0.5)) -> dict:
    """One entry point for the tool: clean, crop, or a contact sheet."""
    if not inputs:
        raise PhotoError("no photographs were named")
    if not available():
        raise PhotoError(
            "this machine has no image library available to the studio, so the photographs were "
            "not touched; nothing was written"
        )
    for path in inputs:
        if not path.is_file():
            raise PhotoError(f"{path} does not exist")

    if mode == "contact-sheet":
        result = contact_sheet(inputs, out_dir / "contact-sheet.png", _library())
        return {"mode": mode, "outputs": [result]}

    outputs: list[dict] = []
    for path in inputs:
        if mode == "social-crops":
            outputs.extend(social_crops(path, out_dir, tuple(focus)))
        elif mode == "clean":
            outputs.append(clean(path, out_dir))
        else:
            raise PhotoError(f"unknown mode {mode!r}; use clean, social-crops or contact-sheet")
    return {"mode": mode, "outputs": outputs}


def _library():
    """The font library, imported lazily so this module stays importable without the plugin."""
    from .library import Library

    return Library(Path(__file__).resolve().parent / "library")
