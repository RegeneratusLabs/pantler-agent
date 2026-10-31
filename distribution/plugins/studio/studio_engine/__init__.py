"""The deterministic studio: fonts, layout, renderers, audit, brand and photos.

This plugin does not touch the record kernel: it is the studio's own engine and imports only the
standard library plus the optional Pillow the engine already carries.
"""

from __future__ import annotations

__all__ = [
    "audit",
    "brand",
    "fonts",
    "layout",
    "library",
    "palette",
    "photos",
    "raster",
    "render",
    "svg",
    "templates",
    "text",
]
