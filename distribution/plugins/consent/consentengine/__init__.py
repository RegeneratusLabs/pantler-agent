"""The consent gate: may this message go to this person, and if not, why not.

Domain content, and deterministic on purpose. Every jurisdiction examined makes consent a statutory
gate with the same shape — the Spam Act 2003 (Cth) ss 16–18, CAN-SPAM, ePrivacy Art 13 — and
`capability-plan.md` §6 calls the pre-send gate the practical pack's worst failure mode: not a bad
post, a **statutory breach**. A model deciding whether consent exists is the wrong tool for that; a
lookup over consent records is the right one.
"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

_VENDOR = _Path(__file__).resolve().parents[1] / "vendor"
if _VENDOR.is_dir() and str(_VENDOR) not in _sys.path:
    _sys.path.append(str(_VENDOR))

from .gate import (  # noqa: E402
    ALLOWED,
    AMBIGUOUS,
    NO_RECORD,
    WITHDRAWN,
    Decision,
    SendCheck,
    check_draft,
    check_recipients,
    check_send,
)

__all__ = [
    "ALLOWED",
    "AMBIGUOUS",
    "NO_RECORD",
    "WITHDRAWN",
    "Decision",
    "SendCheck",
    "check_draft",
    "check_recipients",
    "check_send",
]
