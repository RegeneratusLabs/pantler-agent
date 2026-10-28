"""The claims engine: what in this copy is a claim, and what would have to stand behind it.

Domain content, not kernel: the kernel knows records and units, not advertising law. Standard
library and the kernel only.
"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

_VENDOR = _Path(__file__).resolve().parents[1] / "vendor"
if _VENDOR.is_dir() and str(_VENDOR) not in _sys.path:
    _sys.path.append(str(_VENDOR))

from .lint import Finding, check, report
from .vocabulary import RULES, Rule

__all__ = ["RULES", "Finding", "Rule", "check", "report"]
