"""The availability engine: spoken lines in, an unpriced list out.

Domain content, not kernel: the kernel knows items, units and how to resolve a name; it does not
know what a market list is. Standard library and the kernel only.
"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

# The engine's Python may not have the kernel installed, and this package is imported directly by
# its own tests as well as through the plugin (see plugins/availability/pantler_kernel.py).
_VENDOR = _Path(__file__).resolve().parents[1] / "vendor"
if _VENDOR.is_dir() and str(_VENDOR) not in _sys.path:
    _sys.path.append(str(_VENDOR))

from .build import ListLine, build_list
from .lines import SpokenLine, parse_line

__all__ = ["ListLine", "SpokenLine", "build_list", "parse_line"]
