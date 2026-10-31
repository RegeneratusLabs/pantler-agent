"""The claims tool: report what is in the copy, and never rewrite it.

A thin adapter over `claimsengine`. No catalogue, no store: this one is a pure lookup over words, so
it works on any install and returns the same answer twice.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from . import schemas
from .claimsengine import report

TOOLSET = "claims"
CAPABILITY_KEY = "capability_enabled"

_CTX = None


def _fail(message: str, **extra) -> str:
    payload: dict[str, Any] = {"success": False, "error": message}
    payload.update(extra)
    return json.dumps(payload, default=str)


def _setting(key: str, default: Any = None) -> Any:
    """One key of this plugin's own config, read the way the engine exposes it."""
    getter = getattr(_CTX, "get_config", None)
    if callable(getter):
        try:
            return getter(key, default)
        except TypeError:
            pass
        except Exception:
            return default
        try:
            block = getter()
        except Exception:
            block = None
        if isinstance(block, dict):
            return block.get(key, default)
    block = getattr(_CTX, "config", None)
    if isinstance(block, dict):
        return block.get(key, default)
    return default


def _switched_off() -> str | None:
    value = _setting(CAPABILITY_KEY, True)
    if value is False or (
        isinstance(value, str) and value.strip().lower() in ("false", "off", "no")
    ):
        return _fail(
            "Claim checking is switched off in Capabilities, so nothing here has been checked "
            "against the claim list. Switch it back on before this copy goes anywhere."
        )
    return None


def claim_check(params: dict, **kwargs) -> str:
    if (refusal := _switched_off()) is not None:
        return refusal
    text = params.get("text")
    if not isinstance(text, str) or not text.strip():
        return _fail("give me the copy to check, as `text`")
    return json.dumps(report(text), default=str)


_TOOLS: tuple[tuple[str, dict, Callable[..., str]], ...] = (
    ("claim_check", schemas.CLAIM_CHECK, claim_check),
)
