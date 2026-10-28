"""The spray engine: a catalogue of operator-entered facts, and the arithmetic over them.

Domain content, deliberately not in `pantler-core`: the kernel knows record *types* and units, never
what a withholding period is (the design notes §8, and the correction the skills and plugins notes §4.1
records for the soil engine). This package depends on the kernel's errors and unit table and on
nothing else — no engine import, standard library only.
"""

# The engine's Python may not have the kernel installed, and this package is imported
# directly by its own tests as well as through the plugin, so it cannot rely on the plugin
# package having run first (see plugins/spray/pantler_kernel.py).
import sys as _sys
from pathlib import Path as _Path

_VENDOR = _Path(__file__).resolve().parents[1] / "vendor"
if _VENDOR.is_dir() and str(_VENDOR) not in _sys.path:
    _sys.path.append(str(_VENDOR))

from .application import record_application
from .catalogue import (
    AREA_RATE_UNITS,
    CONCENTRATION_RATE_UNITS,
    RATE_UNITS,
    Block,
    Input,
    SprayBook,
)

__all__ = [
    "AREA_RATE_UNITS",
    "CONCENTRATION_RATE_UNITS",
    "RATE_UNITS",
    "Block",
    "Input",
    "SprayBook",
    "record_application",
]
