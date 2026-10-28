"""The connector tool and its approval gate.

The BFF's connector service owns the Composio key, the connection and the profile's opaque
``user_id``. This plugin asks it over loopback and holds nothing sensitive. The one policy it
owns is the write gate: ``pre_tool_call`` escalates a write to the engine's human-approval card,
and the handler refuses to run a write when that hook is not loaded.

The tool result is a JSON string, like every other first-party tool here. A write is reported as
what the service said, never as "sent" before the service said it.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from . import schemas

TOOLSET = "connectors"

DEFAULT_BFF_URL = "http://127.0.0.1:8650"
TIMEOUT_SECONDS = 15.0
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
TOOL_CACHE_SECONDS = 60.0

_CTX = None
#: Set by `register` once the approval hook is live. The handler refuses writes without it.
_HOOK_REGISTERED = False
_TOOL_CACHE: dict[str, tuple[float, dict[str, dict[str, Any]]]] = {}

_CONNECTOR_NAMES = {
    "square": "Square",
    "stripe": "Stripe",
    "quickbooks": "QuickBooks",
    "zoho_books": "Zoho Books",
    "gmail": "Gmail",
    "outlook": "Outlook",
    "gdrive": "Google Drive",
    "gdocs": "Google Docs",
    "gsheets": "Google Sheets",
    "gcal": "Google Calendar",
    "mailchimp": "Mailchimp",
    "facebook": "Facebook",
    "instagram": "Instagram",
    "canva": "Canva",
    "hubspot": "HubSpot",
    "whatsapp": "WhatsApp",
    "eventbrite": "Eventbrite",
    "calendly": "Calendly",
    "shippo": "Shippo",
    "google_maps": "Google Maps",
}


class _ServiceError(Exception):
    """The connector service refused or could not be reached."""

    def __init__(self, message: str, code: str = "service_error"):
        super().__init__(message)
        self.code = code


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


def _bff_url() -> str:
    configured = _setting("bff_url") or os.environ.get("PANTLER_BFF_URL") or DEFAULT_BFF_URL
    text = str(configured).strip().rstrip("/")
    parsed = urlparse(text)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise _ServiceError(
            "plugins.entries.connectors.bff_url is not an http(s) address, so the connector "
            "service cannot be reached.",
            "bad_config",
        )
    return text


def _request(method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    base = _bff_url()
    parsed = urlparse(base)
    headers = {
        "Accept": "application/json",
        # The BFF's write guard asks a write to come from the app's own origin. This plugin is
        # the app: it is loopback, it is ours, and the human decision happened in the engine's
        # approval card one layer above.
        "Origin": f"{parsed.scheme}://{parsed.netloc}",
        "Sec-Fetch-Site": "same-origin",
    }
    profile = (os.environ.get("HERMES_PROFILE") or "").strip()
    if profile:
        headers["X-Pantler-Profile"] = profile

    data = None
    if body is not None:
        data = json.dumps(body, default=str).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = Request(f"{base}{path}", data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        raw = exc.read(MAX_RESPONSE_BYTES) if exc.fp is not None else b""
        message, code = _error_of(raw, exc.code)
        raise _ServiceError(message, code) from exc
    except URLError as exc:
        raise _ServiceError(
            "The connector service is not running. Start the BFF, or check "
            "plugins.entries.connectors.bff_url.",
            "unreachable",
        ) from exc
    except OSError as exc:
        raise _ServiceError(f"The connector service could not be reached: {exc}.", "unreachable") from exc

    if len(raw) > MAX_RESPONSE_BYTES:
        raise _ServiceError("The connector service's answer was too large to read.", "too_large")
    if not raw:
        return {}
    try:
        payload = json.loads(raw.decode("utf-8", "replace"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _ServiceError("The connector service answered with something that is not JSON.", "bad_answer") from exc
    if not isinstance(payload, dict):
        raise _ServiceError("The connector service answered with something that is not an object.", "bad_answer")
    return payload


def _error_of(raw: bytes, status: int) -> tuple[str, str]:
    try:
        payload = json.loads(raw.decode("utf-8", "replace")) if raw else {}
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict):
            message = str(error.get("message") or "").strip()
            code = str(error.get("code") or "").strip()
            if message:
                return message, code or "service_error"
    except (UnicodeDecodeError, json.JSONDecodeError):
        pass
    return f"The connector service answered HTTP {status}.", "service_error"


def _ok(**payload: Any) -> str:
    return json.dumps({"success": True, **payload}, default=str)


def _fail(message: str, code: str = "error", **extra: Any) -> str:
    return json.dumps({"success": False, "error": message, "code": code, **extra}, default=str)


def _connector_of(params: dict[str, Any]) -> str:
    connector = params.get("connector")
    return connector.strip().lower() if isinstance(connector, str) else ""


def _tool_of(params: dict[str, Any]) -> str:
    tool = params.get("tool")
    return tool.strip() if isinstance(tool, str) else ""


def _tools_for(connector: str, *, refresh: bool = False) -> dict[str, dict[str, Any]]:
    """The connector's tool list, cached briefly. Raises when the service cannot answer."""
    now = time.monotonic()
    cached = _TOOL_CACHE.get(connector)
    if not refresh and cached is not None and now - cached[0] < TOOL_CACHE_SECONDS:
        return cached[1]
    payload = _request("GET", f"/api/connectors/{quote(connector, safe='')}/tools")
    tools: dict[str, dict[str, Any]] = {}
    rows = payload.get("tools")
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict) and isinstance(row.get("slug"), str):
                tools[row["slug"]] = row
    _TOOL_CACHE[connector] = (now, tools)
    return tools


def _is_read_only(connector: str, tool: str) -> bool | None:
    """Whether the service says this action is a read. None when it cannot be known."""
    if not connector or not tool:
        return None
    try:
        definition = _tools_for(connector).get(tool)
    except _ServiceError:
        return None
    if not isinstance(definition, dict):
        return None
    value = definition.get("read_only")
    return value if isinstance(value, bool) else None


def connector_use(params: dict, **kwargs) -> str:
    action = str(params.get("action") or "").strip().lower()
    if action == "status":
        try:
            payload = _request("GET", "/api/connectors")
        except _ServiceError as exc:
            return _fail(str(exc), exc.code)
        rows = payload.get("connectors")
        connectors = []
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                account = row.get("account") if isinstance(row.get("account"), dict) else {}
                connectors.append(
                    {
                        "id": row.get("id"),
                        "name": row.get("name"),
                        "state": row.get("state"),
                        "display_name": account.get("display_name") or "",
                        "note": row.get("note") or row.get("reason") or "",
                    }
                )
        configured = payload.get("configured") is True
        error = payload.get("error")
        if isinstance(error, dict) and error.get("message"):
            # A configured-but-broken service is not a success: the model must say what the
            # service said rather than reporting an empty grid as "nothing is connected".
            return _fail(
                str(error["message"]),
                str(error.get("code") or "connector_error"),
                configured=configured,
                connectors=connectors,
            )
        return _ok(
            configured=configured,
            connectors=connectors,
            hint=(
                ""
                if configured
                else "The connector service is not configured on this machine. The backend "
                "provides the Composio key; the app does not ask for it."
            ),
        )

    if action == "tools":
        connector = _connector_of(params)
        if not connector:
            return _fail("Which connector? Give `connector` — for example gmail.", "bad_request")
        try:
            tools = _tools_for(connector)
        except _ServiceError as exc:
            return _fail(str(exc), exc.code)
        return _ok(
            connector=connector,
            tools=[
                {
                    "slug": row.get("slug"),
                    "name": row.get("name"),
                    "description": row.get("description"),
                    "read_only": row.get("read_only") is True,
                }
                for row in tools.values()
            ],
        )

    if action == "schema":
        connector = _connector_of(params)
        tool = _tool_of(params)
        if not connector:
            return _fail("Which connector? Give `connector` — for example gmail.", "bad_request")
        if not tool:
            return _fail("Which action? Give `tool` — the slug from the tools action.", "bad_request")
        try:
            payload = _request(
                "GET",
                f"/api/connectors/{quote(connector, safe='')}/tools?tool={quote(tool, safe='')}",
            )
        except _ServiceError as exc:
            return _fail(str(exc), exc.code)
        row = payload.get("tool")
        if not isinstance(row, dict):
            return _fail(f"{tool} is not one of that connector's tools.", "unknown_tool")
        return _ok(connector=connector, tool=row)

    if action == "run":
        connector = _connector_of(params)
        tool = _tool_of(params)
        arguments = params.get("arguments")
        if not connector:
            return _fail("Which connector? Give `connector` — for example gmail.", "bad_request")
        if not tool:
            return _fail("Which action? Give `tool` — the slug from the tools action.", "bad_request")
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            return _fail("`arguments` has to be an object, exactly as the tool names its inputs.", "bad_request")
        try:
            definition = _tools_for(connector).get(tool)
        except _ServiceError as exc:
            return _fail(str(exc), exc.code)
        if definition is None:
            return _fail(
                f"{tool} is not one of {_CONNECTOR_NAMES.get(connector, connector)}'s tools. "
                f"Ask for tools again and use the exact slug.",
                "unknown_tool",
            )
        read_only = definition.get("read_only") is True
        if not read_only and not _HOOK_REGISTERED:
            return _fail(
                "The approval gate is not loaded in this session, so I will not run a write. "
                "Nothing was sent.",
                "no_gate",
            )
        try:
            payload = _request(
                "POST",
                f"/api/connectors/{quote(connector, safe='')}/execute",
                {"tool": tool, "arguments": arguments, "read_only": read_only},
            )
        except _ServiceError as exc:
            return _fail(str(exc), exc.code)
        if payload.get("success") is not True:
            return _fail(
                str(payload.get("error") or "The connector service did not report success."),
                "connector_failed",
            )
        return _ok(
            connector=payload.get("connector") or connector,
            tool=payload.get("tool") or tool,
            data=payload.get("data"),
            log_id=payload.get("log_id"),
        )

    return _fail(
        "`action` has to be status, tools or run.",
        "bad_request",
    )


def pre_tool_call(tool_name: str, args: dict | None = None, **_kwargs) -> dict | None:
    """Escalate a connected-app write to the engine's human-approval gate.

    Reads return None and run. Anything the service cannot classify is treated as a write, and a
    failure inside this hook is also a write: fail closed, never open. The message starts with
    "Connected app change" because that is the phrase `approval.ts` translates for the card.
    """
    try:
        if tool_name != "connector_use" or not isinstance(args, dict):
            return None
        if str(args.get("action") or "").strip().lower() != "run":
            return None
        connector = _connector_of(args)
        tool = _tool_of(args)
        if not connector or not tool:
            return None
        if _is_read_only(connector, tool) is True:
            return None
        arguments = args.get("arguments")
        detail = json.dumps(arguments, default=str)[:400] if isinstance(arguments, dict) else "no arguments"
        display = _CONNECTOR_NAMES.get(connector, connector.replace("_", " ").title())
        return {
            "action": "approve",
            "message": (
                f"Connected app change: {tool} on {display}. This can change data in that app. "
                f"Arguments: {detail}"
            ),
            "rule_key": f"connector:{connector}:{tool}",
        }
    except Exception:
        # A hook that raises is skipped by the engine, which would let a write through. Returning
        # an approval is the only fail-closed answer available from here.
        return {
            "action": "approve",
            "message": "Connected app change: the connector service could not classify this action.",
            "rule_key": "connector:unclassified",
        }


_TOOLS: tuple[tuple[str, dict, Callable[..., str]], ...] = (
    ("connector_use", schemas.CONNECTOR_USE, connector_use),
)
