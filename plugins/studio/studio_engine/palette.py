"""Colour as arithmetic: parse, mix, and the one check that matters.

The brand package's own rule is that contrast is measured, never eyeballed. This module is that
rule for the operator's palettes: a ground and an ink, a measured ratio, and a refusal below 4.5:1.
A colour picked because it looked right on the designer's monitor is how a market sign ends up
unreadable in the sun.

Tints and shades are mixed in linear-light space so a 10% tint looks like a tint rather than mud.
"""

from __future__ import annotations

import re

HEX = re.compile(r"^#?([0-9a-fA-F]{6})$")

#: WCAG 2.2 AA. Encoded as constants with their source, per the licence ladder.
AA_TEXT = 4.5
AA_LARGE = 3.0


class ColourError(ValueError):
    """A colour that is not a six-digit hex, or a pair that fails the contrast floor."""


def parse(value: str) -> tuple[int, int, int]:
    match = HEX.match(str(value).strip())
    if not match:
        raise ColourError(f"{value!r} is not a six-digit hex colour")
    raw = match.group(1)
    return tuple(int(raw[index : index + 2], 16) for index in (0, 2, 4))  # type: ignore[return-value]


def to_hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02X}{:02X}{:02X}".format(*(max(0, min(255, round(channel))) for channel in rgb))


def _channel(value: int) -> float:
    c = value / 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminance(rgb: tuple[int, int, int]) -> float:
    r, g, b = rgb
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    first, second = sorted((luminance(a), luminance(b)), reverse=True)
    return (first + 0.05) / (second + 0.05)


def mix(a: tuple[int, int, int], b: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
    """`amount` of `b` in `a`, mixed in linear light."""
    amount = max(0.0, min(1.0, amount))

    def blend(x: int, y: int) -> int:
        lin = _channel(x) * (1 - amount) + _channel(y) * amount
        srgb = 12.92 * lin if lin <= 0.0031308 else 1.055 * (lin ** (1 / 2.4)) - 0.055
        return round(max(0.0, min(1.0, srgb)) * 255)

    return (blend(a[0], b[0]), blend(a[1], b[1]), blend(a[2], b[2]))


def tint(rgb: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
    return mix(rgb, (255, 255, 255), amount)


def shade(rgb: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
    return mix(rgb, (0, 0, 0), amount)


def is_dark(rgb: tuple[int, int, int]) -> bool:
    return luminance(rgb) < 0.35


def readable_on(ground: tuple[int, int, int], candidates: list[tuple[int, int, int]]) -> tuple[int, int, int]:
    """The first candidate that clears AA on this ground, or the highest-contrast one."""
    best = max(candidates, key=lambda candidate: contrast(candidate, ground))
    for candidate in candidates:
        if contrast(candidate, ground) >= AA_TEXT:
            return candidate
    return best


def scrim_for(
    ink: tuple[int, int, int], ground: tuple[int, int, int], target: float = AA_TEXT
) -> tuple[tuple[int, int, int], float]:
    """The tint and opacity that get `ink` to `target` over `ground`.

    Used behind type set on a photograph. Returns a colour and the opacity at which it reaches
    the target; the caller draws the scrim before the type. Honest limit: the preview cannot
    sample every pixel of a photo in this module, so the check uses the ground the caller passes,
    which the renderer takes from the image's own average in the text's box.
    """
    direction = (0, 0, 0) if is_dark(ink) else (255, 255, 255)
    # The background a scrim approaches is its own colour; find the least opacity that clears.
    for step in range(0, 101, 5):
        alpha = step / 100
        blended = mix(ground, direction, alpha)
        if contrast(ink, blended) >= target:
            return direction, alpha
        if alpha == 1.0:
            break
    return direction, 1.0


def validate_pair(ink: str, ground: str, label: str = "ink on ground") -> dict:
    ink_rgb, ground_rgb = parse(ink), parse(ground)
    ratio = contrast(ink_rgb, ground_rgb)
    return {
        "id": f"contrast.{label}",
        "ok": ratio >= AA_TEXT,
        "value": round(ratio, 2),
        "detail": f"{label} is {ratio:.2f}:1 (AA needs {AA_TEXT}:1)",
    }
