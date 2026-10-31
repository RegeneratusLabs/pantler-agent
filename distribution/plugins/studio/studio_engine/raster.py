"""Draw the same operations with Pillow, for the PNG a feed will accept.

Pillow is a core dependency of the engine, so in the product this path always exists. The layout
decided every position; this module only paints. Where a face is drawn, the baseline is the anchor,
for the same reason the canvas positions by top: two faces with different ascents cannot share a
top edge and look right.

The import is lazy and guarded. A machine without Pillow still gets the SVG and an honest sentence;
it never gets a stack trace in the middle of a card.
"""

from __future__ import annotations

from pathlib import Path

from .layout import Composition, ImageOp, RectOp, TextOp


def available() -> bool:
    try:
        import PIL  # noqa: F401
    except Exception:
        return False
    return True


def _hex(value: str) -> tuple[int, int, int]:
    raw = value.lstrip("#")
    return tuple(int(raw[index : index + 2], 16) for index in (0, 2, 4))  # type: ignore[return-value]


def draw(composition: Composition, faces: dict[str, Path], path: Path) -> Path:
    from PIL import Image, ImageDraw, ImageFont  # imported here so the module loads without it

    image = Image.new("RGB", (composition.width, composition.height), _hex(composition.ground))
    draw_ctx = ImageDraw.Draw(image, "RGBA")
    cache: dict[tuple[str, int], object] = {}

    def font_for(face_id: str, size: float):
        key = (face_id, max(1, int(round(size))))
        if key not in cache:
            cache[key] = ImageFont.truetype(str(faces[face_id]), key[1])
        return cache[key]

    for op in composition.ops:
        if isinstance(op, ImageOp):
            source = Image.open(op.path).convert("RGB")
            target_w, target_h = max(1, int(round(op.w))), max(1, int(round(op.h)))
            scale = max(target_w / source.width, target_h / source.height)
            resized = source.resize(
                (max(target_w, int(source.width * scale)), max(target_h, int(source.height * scale))),
                Image.LANCZOS,
            )
            fx, fy = op.focus
            left = int(max(0, min(resized.width - target_w, resized.width * fx - target_w / 2)))
            top = int(max(0, min(resized.height - target_h, resized.height * fy - target_h / 2)))
            crop = resized.crop((left, top, left + target_w, top + target_h))
            if op.opacity < 1.0:
                image.paste(crop, (int(round(op.x)), int(round(op.y))),
                            Image.new("L", crop.size, int(255 * op.opacity)))
            else:
                image.paste(crop, (int(round(op.x)), int(round(op.y))))
        elif isinstance(op, RectOp):
            colour = _hex(op.fill) + (int(255 * op.opacity),)
            draw_ctx.rectangle(
                [op.x, op.y, op.x + op.w, op.y + op.h],
                fill=colour if op.opacity < 1.0 else _hex(op.fill),
            )
        elif isinstance(op, TextOp):
            font = font_for(op.face_id, op.size)
            fill = _hex(op.fill)
            if op.chars:
                for char, offset in op.chars:
                    if char.isspace():
                        continue
                    draw_ctx.text((op.x + offset, op.baseline), char, font=font, fill=fill,
                                  anchor="ls")
            else:
                draw_ctx.text((op.x, op.baseline), op.text, font=font, fill=fill, anchor="ls")

    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, "PNG", optimize=True)
    return path
