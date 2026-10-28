"""The availability tool: resolve the spoken lines, or say what could not be resolved.

Every handler is a thin adapter over `availabilityengine`. The catalogue is the operator's own price
book — the same file the invoicing tool reads — so one list of items serves both, and an item nobody
has named before shows up as a question rather than a guess.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable

from pantler_core import PriceBookError, price_book_from_json

from . import schemas
from .availabilityengine import build_list

TOOLSET = "availability"
CAPABILITY_KEY = "capability_enabled"

_CTX = None
_STATE: dict[str, Any] = {"book": None}


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
            "The availability list is switched off in Capabilities. Switch it back on there and "
            "ask me again."
        )
    return None


def _catalogue_path() -> Path | None:
    configured = _setting("pricebook_path") or _setting("catalogue_path")
    if configured:
        return Path(os.path.expanduser(os.path.expandvars(str(configured))))
    env = os.environ.get("PANTLER_PRICEBOOK", "").strip()
    if env:
        return Path(os.path.expanduser(os.path.expandvars(env)))
    home = os.environ.get("HERMES_HOME", "").strip()
    return Path(home) / "pricebook.json" if home else None


def _book():
    if _STATE["book"] is not None:
        return _STATE["book"]
    path = _catalogue_path()
    if path is None:
        raise PriceBookError(
            "no catalogue configured: set plugins.entries.availability.pricebook_path in "
            "config.yaml, or PANTLER_PRICEBOOK, or place pricebook.json in HERMES_HOME"
        )
    if not path.is_file():
        raise PriceBookError(
            f"no catalogue called {path.name!r} at the configured place"
        )  # the name, not the path: a tool result is not a filesystem map (A19-PLUG-12)
    # The kernel's loader takes a path (and reports a bad file as a `PriceBookError` rather than
    # an `OSError`), so the tool passes the path rather than reading the text itself.
    _STATE["book"] = price_book_from_json(path)
    return _STATE["book"]


def availability_list(params: dict, **kwargs) -> str:
    if (refusal := _switched_off()) is not None:
        return refusal
    raw = params.get("lines")
    if isinstance(raw, str):
        lines = [line for line in raw.splitlines() if line.strip()]
    elif isinstance(raw, list):
        lines = [str(line) for line in raw if str(line).strip()]
    else:
        return _fail("give me the items as `lines`: one entry per thing they have")
    if not lines:
        return _fail("no lines to build a list from — what do they have?")
    try:
        book = _book()
    except (PriceBookError, OSError, ValueError) as exc:
        return _fail(str(exc))
    result = build_list(
        book,
        lines,
        title=str(params.get("title") or ""),
        include_unmatched=bool(params.get("include_unmatched", True)),
    )
    return json.dumps(result, default=str)


_TOOLS: tuple[tuple[str, dict, Callable[..., str]], ...] = (
    ("availability_list", schemas.AVAILABILITY_LIST, availability_list),
)
