"""Write the artboard as one self-contained SVG.

Self-contained is the requirement, not a nicety: the file has to open on the operator's laptop, in
the app's preview, in a printer's RIP, and on a machine that has none of the fonts. So the faces the
card actually uses are embedded as data URIs, images are inlined, and nothing is linked.

Every `<text>` carries the width the layout measured. That is what keeps the SVG and the PNG in the
same places: a browser that resolves a slightly different advance still draws inside the box the
layout reserved, instead of pushing a line into the margin.
"""

from __future__ import annotations

import base64
from html import escape
from pathlib import Path

from .layout import Composition, ImageOp, RectOp, TextOp


def _font_family(face_id: str) -> str:
    return f"studio-{face_id}"


def _mime(path: Path) -> str:
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(path.suffix.lower(), "application/octet-stream")


def _embed(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def _number(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def render(
    composition: Composition,
    faces: dict[str, Path],
    title: str = "",
    physical: tuple[float, float] | None = None,
) -> str:
    """`faces` maps a face id to its file; only the ones used are embedded.

    `physical` is the finished size in millimetres. A print file that says `width="297mm"` opens at
    A3 in a print application; one that says `width="3508"` opens at "some pixels" and somebody has
    to work out the size. The viewBox stays in pixels, so every measured coordinate is unchanged.
    """
    used = {op.face_id for op in composition.texts()}
    missing = sorted(used - set(faces))
    if missing:
        raise ValueError(f"no font file for face(s): {', '.join(missing)}")

    parts: list[str] = []
    size = (
        f'width="{physical[0]:.1f}mm" height="{physical[1]:.1f}mm"'
        if physical
        else f'width="{composition.width}" height="{composition.height}"'
    )
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'{size} '
        f'viewBox="0 0 {composition.width} {composition.height}" '
        f'shape-rendering="geometricPrecision" text-rendering="geometricPrecision">'
    )
    if title:
        parts.append(f"<title>{escape(title)}</title>")
    parts.append("<defs><style type=\"text/css\"><![CDATA[")
    for face_id in sorted(used):
        parts.append(
            f"@font-face{{font-family:'{_font_family(face_id)}';"
            f"src:url(data:font/ttf;base64,{_embed(faces[face_id])}) format('truetype');"
            "font-weight:normal;font-style:normal;}"
        )
    parts.append("]]></style></defs>")
    parts.append(
        f'<rect x="0" y="0" width="{composition.width}" height="{composition.height}" '
        f'fill="{composition.ground}"/>'
    )

    for op in composition.ops:
        if isinstance(op, ImageOp):
            path = Path(op.path)
            if not path.is_file():
                raise ValueError(f"image not found: {path}")
            xlink = f' xlink:href="data:{_mime(path)};base64,{_embed(path)}"'
            parts.append(
                f'<image x="{_number(op.x)}" y="{_number(op.y)}" '
                f'width="{_number(op.w)}" height="{_number(op.h)}" '
                f'preserveAspectRatio="xMidYMid slice" opacity="{_number(op.opacity)}"'
                f"{xlink}/>"
            )
        elif isinstance(op, RectOp):
            parts.append(
                f'<rect x="{_number(op.x)}" y="{_number(op.y)}" width="{_number(op.w)}" '
                f'height="{_number(op.h)}" fill="{op.fill}" opacity="{_number(op.opacity)}"/>'
            )
        elif isinstance(op, TextOp):
            family = _font_family(op.face_id)
            common = (
                f'font-family="{family}" font-size="{_number(op.size)}" fill="{op.fill}"'
            )
            if op.chars:
                for char, offset in op.chars:
                    if char.isspace():
                        continue
                    parts.append(
                        f'<text x="{_number(op.x + offset)}" y="{_number(op.baseline)}" '
                        f'{common} xml:space="preserve">{escape(char)}</text>'
                    )
            else:
                parts.append(
                    f'<text x="{_number(op.x)}" y="{_number(op.baseline)}" {common} '
                    f'textLength="{_number(op.width)}" lengthAdjust="spacingAndGlyphs" '
                    f'xml:space="preserve">{escape(op.text)}</text>'
                )
    parts.append("</svg>")
    return "\n".join(parts)


def write(
    composition: Composition,
    faces: dict[str, Path],
    path: Path,
    title: str = "",
    physical: tuple[float, float] | None = None,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(composition, faces, title=title, physical=physical), encoding="utf-8")
    return path
