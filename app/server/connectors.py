"""Composio connectors — the live connection service.

This is rail C of the Composio notes: the BFF talks to Composio's REST
API with the operator's own project key, so the Connectors screen reads state from the connection
instead of drawing a map. The key lives in the profile's `.env` (the same place every other
credential lives), is read per request so a saved key takes effect immediately, and is never
returned by a route.

Three boundaries this module keeps:

1. **The key does not leave.** It is sent only to `backend.composio.dev`, redirects are refused so
   a hop cannot carry it elsewhere, and error text is redacted before it reaches a client.
2. **The user id is opaque and per profile.** Composio's model is one project key with one
   `user_id` per end user; a bug here is a cross-tenant leak. The id is generated once, stored in
   `connectors.json` (0600) beside the profile, never an email, never `default`, and an existing
   but unreadable file is an error rather than a reason to mint a second identity.
3. **A connection is a state the service witnessed.** No route reports `connected` because a
   button was clicked; only an `ACTIVE` account from Composio does.

Standard library only. The client is deliberately small: five calls, JSON in and JSON out.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

#: Composio's project API. The service never takes this from a request.
COMPOSIO_BASE = "https://backend.composio.dev/api/v3.1"

#: The name the key has in the profile's `.env`, and the one the settings route writes.
KEY_NAME = "COMPOSIO_API_KEY"

#: A deployment-wide key for the BFF process, used when a profile does not carry its own.
#: The app never asks for it; it is an operator/server concern, like every other backend secret.
DEPLOYMENT_KEY_NAME = "PANTLER_COMPOSIO_API_KEY"

#: What a caller sees when neither source has a key. The app has no key field to point at.
NO_KEY = (
    "The connector service has no Composio project key. The backend must provide one; the app "
    "does not ask for it."
)

#: Every call is bounded, and an answer larger than this is refused rather than buffered.
TIMEOUT_SECONDS = 20.0
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
#: What a tool result may carry into the chat. A model that gets a 4 MB JSON blob is worse off
#: than one that gets the first slice and a sentence saying it was sliced.
MAX_TOOL_DATA_CHARS = 200_000

#: How long a toolkit's tool list is reused. The list is a slow-moving catalogue, and the
#: assistant may ask for it several times in one conversation.
TOOL_CACHE_SECONDS = 60.0

#: Composio account states → the four states the screen draws.
STATE_OF = {
    "ACTIVE": "connected",
    "INITIATED": "pending",
    "INITIALIZING": "pending",
    "FAILED": "needs_attention",
    "EXPIRED": "needs_attention",
    "INACTIVE": "inactive",
    "REVOKED": "not_connected",
}
_STATE_PRIORITY = ("ACTIVE", "INITIATED", "INITIALIZING", "FAILED", "EXPIRED", "INACTIVE", "REVOKED")

#: Slug evidence that a tool is a read. Anything else is treated as a write, which costs an
#: approval rather than letting a change through. Composio does not publish the hints on every
#: tool object, so this is the conservative half of the classifier.
_READ_SLUG = re.compile(
    r"_(?:GET|LIST|SEARCH|FIND|FETCH|READ|RETRIEVE|EXPORT|DOWNLOAD|DESCRIBE)(?:_|$)"
)
_WRITE_HINTS = frozenset({"createHint", "updateHint", "destructiveHint"})
_READ_HINT = "readOnlyHint"

_ACCOUNT_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_USER_ID = re.compile(r"^pantler_[0-9a-f]{32}$")
_TOOL_SLUG = re.compile(r"^[A-Z][A-Z0-9_]{1,100}$")
_SECRET_TEXT = re.compile(r"\b(?:ak|ca)_[A-Za-z0-9_-]{6,}\b")


class ConnectorError(Exception):
    """A failure with a code the route can map and a sentence a person can read."""

    def __init__(self, code: str, message: str, status: int = 502):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


@dataclass(frozen=True)
class Connector:
    """One of the ten, as both the service and the screen name it."""

    id: str
    slug: str
    name: str
    #: Whether Composio offers managed OAuth for this toolkit. Shopify and Xero do not.
    managed_oauth: bool = True
    #: False for a toolkit Composio does not carry at all.
    available: bool = True
    note: str = ""


#: The catalogue in one place. The screen owns the copy and the marks; this owns the ids and
#: slugs the API is called with. `app/server/tests/test_connectors.py` checks the two agree.
#: Order is the screen's group order: selling, money, workspace, marketing, operations.
CONNECTORS: tuple[Connector, ...] = (
    Connector("square", "square", "Square"),
    Connector("stripe", "stripe", "Stripe"),
    Connector("quickbooks", "quickbooks", "QuickBooks"),
    Connector("zoho_books", "zoho_books", "Zoho Books"),
    Connector("gmail", "gmail", "Gmail"),
    Connector("outlook", "outlook", "Outlook"),
    Connector("gdrive", "googledrive", "Google Drive"),
    Connector("gdocs", "googledocs", "Google Docs"),
    Connector("gsheets", "googlesheets", "Google Sheets"),
    Connector("gcal", "googlecalendar", "Google Calendar"),
    Connector("mailchimp", "mailchimp", "Mailchimp"),
    Connector("facebook", "facebook", "Facebook",
              note="Needs a Facebook Page, not a personal profile."),
    Connector("instagram", "instagram", "Instagram",
              note="Needs a Business or Creator account."),
    Connector("canva", "canva", "Canva"),
    Connector("hubspot", "hubspot", "HubSpot"),
    Connector("whatsapp", "whatsapp", "WhatsApp",
              note="Needs a WhatsApp Business account and a phone number."),
    Connector("eventbrite", "eventbrite", "Eventbrite"),
    Connector("calendly", "calendly", "Calendly"),
    Connector("shippo", "shippo", "Shippo"),
    Connector("google_maps", "google_maps", "Google Maps"),
)

BY_ID = {connector.id: connector for connector in CONNECTORS}
BY_SLUG = {connector.slug: connector for connector in CONNECTORS}


# ---------------------------------------------------------------- the HTTP client


class _RefuseRedirects(HTTPRedirectHandler):
    """A redirect is refused, not followed: the request carries the project key.

    Composio's endpoints do not redirect. A hop that did would be an ordinary HTTP client
    following someone else's instruction to send the key to another host, so the safe reading
    is to stop and say so.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        raise ConnectorError(
            "upstream",
            "Composio redirected the request; this client will not follow it with a key attached.",
            502,
        )


def _redact(text: str) -> str:
    """Remove anything key-shaped from a sentence that came from outside."""
    return _SECRET_TEXT.sub("<redacted>", (text or "").strip())[:500]


def _json_or_empty(raw: bytes) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw.decode("utf-8", "replace"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConnectorError("upstream", "Composio's answer was not JSON.", 502) from exc
    if not isinstance(parsed, dict):
        raise ConnectorError("upstream", "Composio's answer was not an object.", 502)
    return parsed


class ComposioClient:
    """The five calls this product makes, over stdlib ``urllib``.

    `allow_insecure` exists for the test suite's loopback server. The service never sets it.
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = COMPOSIO_BASE,
        timeout: float = TIMEOUT_SECONDS,
        max_bytes: int = MAX_RESPONSE_BYTES,
        allow_insecure: bool = False,
    ):
        parsed = urlparse(base_url)
        if not parsed.scheme or not parsed.hostname:
            raise ValueError("a Composio base URL needs a scheme and a host")
        if parsed.scheme != "https" and not allow_insecure:
            raise ValueError("the Composio base URL must be https")
        if not api_key:
            raise ValueError("a Composio project key is required")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_bytes = max_bytes
        self._opener = build_opener(_RefuseRedirects())

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = self.base_url + path
        if params:
            query = [(name, str(value)) for name, value in params.items() if value is not None]
            if query:
                url += "?" + urlencode(query, doseq=True)
        data = None
        headers = {"x-api-key": self.api_key, "Accept": "application/json"}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(url, data=data, headers=headers, method=method)
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                raw = response.read(self.max_bytes + 1)
        except HTTPError as exc:
            raw = exc.read(self.max_bytes) if exc.fp is not None else b""
            raise self._error(exc.code, raw) from exc
        except URLError as exc:
            raise ConnectorError(
                "unreachable",
                f"Could not reach Composio: {_redact(str(exc.reason)) or 'the network refused'}.",
                502,
            ) from exc
        except ConnectorError:
            raise
        except OSError as exc:
            raise ConnectorError("unreachable", f"Could not reach Composio: {_redact(str(exc))}.", 502) from exc
        if len(raw) > self.max_bytes:
            raise ConnectorError("upstream", "Composio's answer was too large to read.", 502)
        return _json_or_empty(raw)

    @staticmethod
    def _error(status: int, raw: bytes) -> ConnectorError:
        detail = ""
        slug = ""
        suggested = ""
        try:
            payload = json.loads(raw.decode("utf-8", "replace")) if raw else {}
            error = payload.get("error") if isinstance(payload, dict) else None
            if isinstance(error, dict):
                detail = str(error.get("message") or "")
                slug = str(error.get("slug") or "")
                suggested = str(error.get("suggested_fix") or "")
            elif isinstance(error, str):
                detail = error
        except (UnicodeDecodeError, json.JSONDecodeError):
            detail = ""
        detail = _redact(detail)
        suggested = _redact(suggested)
        if status == 403 and (slug == "APIKey_InsufficientPermissions" or "permission" in detail.lower()):
            # A valid key that cannot perform this action is a different problem from a key
            # Composio does not know. Scoped keys cannot be edited after creation, so the fix is
            # a new key with the four permission areas this product needs — say all of it.
            fix = suggested or (
                "Grant this key write access to auth_configs and connected_accounts in the "
                "Composio dashboard, or create a key that already has it."
            )
            return ConnectorError(
                "insufficient_permissions",
                f"The connector service's Composio key is valid but read-only for this action. {fix} "
                "Scoped keys cannot be edited after creation; the backend needs Auth configs "
                "(read and write), Connected accounts (read and write), Tools (read only) and "
                "Tool execution (Legacy, write only).",
                403,
            )
        if status in (401, 403):
            return ConnectorError(
                "bad_key",
                "Composio refused the connector service's key. The backend key must be a "
                "developer project key (ak_…) from dashboard.composio.dev; a consumer “For You” "
                "key cannot reach the project API. Replace it in the profile's .env or "
                "PANTLER_COMPOSIO_API_KEY.",
                502,
            )
        if status == 429:
            return ConnectorError(
                "rate_limited",
                "Composio is rate-limiting this project right now. Try again in a moment.",
                502,
            )
        if status == 404:
            return ConnectorError("upstream", detail or "Composio could not find that.", 502)
        return ConnectorError(
            "upstream",
            f"Composio answered {status}{': ' + detail if detail else ''}.",
            502,
        )


# ---------------------------------------------------------------- the service


def _atomic_private_write(path: Path, text: str) -> None:
    """Write a 0600 file beside its target and replace atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _account_slug(account: Any) -> str:
    if not isinstance(account, dict):
        return ""
    toolkit = account.get("toolkit")
    if isinstance(toolkit, dict):
        return str(toolkit.get("slug") or "").strip().lower()
    return ""


def _public_account(account: Any) -> dict[str, Any] | None:
    """The fields a screen may see. Never `state.val`: it can hold provider credentials."""
    if not isinstance(account, dict):
        return None
    identifier = str(account.get("id") or "").strip()
    if not _ACCOUNT_ID.match(identifier):
        return None
    state = account.get("state")
    value = state.get("val") if isinstance(state, dict) else None
    display = value.get("displayName") if isinstance(value, dict) else None
    return {
        "id": identifier,
        "status": str(account.get("status") or "").strip(),
        "status_reason": _redact(str(account.get("status_reason") or ""))[:200],
        "display_name": str(display or "").strip()[:120],
        "created_at": str(account.get("created_at") or "").strip()[:40],
        "toolkit": _account_slug(account),
    }


def _looks_read(tool_slug: str) -> bool:
    return bool(_READ_SLUG.search((tool_slug or "").strip().upper()))


def read_only(tool: dict[str, Any]) -> bool:
    """Whether a Composio tool is a read, from its hints where present and its slug otherwise."""
    tags = tool.get("tags")
    if isinstance(tags, list):
        hints = {str(tag).strip() for tag in tags}
        if hints & _WRITE_HINTS:
            return False
        if _READ_HINT in hints:
            return True
    return _looks_read(str(tool.get("slug") or ""))


class Connectors:
    """Read and drive one profile's Composio connections."""

    def __init__(self, profile: Any, client: ComposioClient | None = None):
        self.profile = profile
        self._client = client
        # An injected client is a test fixture, not a key: it stays usable with no `.env`.
        self._injected = client is not None
        self._client_key: str | None = None
        self._tools: dict[str, tuple[float, list[dict[str, Any]]]] = {}

    # -- identity and key -------------------------------------------------

    @property
    def configured(self) -> bool:
        return bool(self._api_key()) or self._injected

    def _api_key(self) -> str:
        getter = getattr(self.profile, "secret", None)
        if callable(getter):
            try:
                value = getter(KEY_NAME)
            except Exception:
                value = ""
            if isinstance(value, str) and value.strip():
                return value.strip()
        return os.environ.get(DEPLOYMENT_KEY_NAME, "").strip()

    def client(self) -> ComposioClient:
        key = self._api_key()
        if not key:
            if self._injected and self._client is not None:
                return self._client
            # A removed key must stop the cached client being used: the settings writer can
            # clear `.env` while this process is alive.
            self._client = None
            self._client_key = None
            raise ConnectorError("not_configured", NO_KEY, 409)
        if self._client is None or self._client_key != key:
            self._client = ComposioClient(key)
            self._client_key = key
        return self._client

    def _injected_client(self) -> ComposioClient:
        """The test client, or the real one built from the profile's key."""
        if self._injected and self._client is not None:
            return self._client
        return self.client()

    def identity_path(self) -> Path:
        directory = getattr(self.profile, "dir", None)
        if directory is None:
            raise ConnectorError("bad_state", "This profile has no directory for its connector identity.", 500)
        return Path(directory) / "connectors.json"

    def user_id(self, *, create: bool = False) -> str | None:
        """The stable opaque id Composio keys this profile's connections by.

        Missing is normal until the first connect. Present but unreadable is an error: creating
        a new id would silently orphan every connection the operator already authorised.
        """
        path = self.identity_path()
        if not path.is_file():
            if not create:
                return None
            value = "pantler_" + secrets.token_hex(16)
            _atomic_private_write(path, json.dumps({"version": 1, "user_id": value}, indent=2) + "\n")
            return value
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ConnectorError(
                "bad_state",
                "The connector identity file is unreadable. Restore or remove connectors.json in "
                "the profile, then connect again.",
                500,
            ) from exc
        value = data.get("user_id") if isinstance(data, dict) else None
        if not isinstance(value, str) or not _USER_ID.match(value):
            raise ConnectorError(
                "bad_state",
                "The connector identity file does not hold a valid user id. Restore or remove "
                "connectors.json in the profile, then connect again.",
                500,
            )
        return value

    # -- catalogue --------------------------------------------------------

    @staticmethod
    def _require(connector_id: str) -> Connector:
        connector = BY_ID.get((connector_id or "").strip().lower())
        if connector is None:
            raise ConnectorError(
                "not_in_catalogue",
                f"{connector_id!r} is not one of the connectors this screen knows.",
                404,
            )
        return connector

    @staticmethod
    def _entry(
        connector: Connector,
        *,
        state: str = "not_connected",
        account: dict[str, Any] | None = None,
        can_connect: bool = False,
        reason: str | None = None,
    ) -> dict[str, Any]:
        return {
            "id": connector.id,
            "name": connector.name,
            "slug": connector.slug,
            "available": connector.available,
            "managed_oauth": connector.managed_oauth,
            "note": connector.note,
            "state": state,
            "account": account,
            "can_connect": can_connect,
            "reason": reason,
        }

    # -- reads ------------------------------------------------------------

    def _probe_key(self) -> None:
        """Validate the key without needing a user id: the cheapest authenticated read."""
        try:
            self._injected_client().request("GET", "/auth_configs", params={"limit": 1})
        except ConnectorError:
            raise

    def _list(self, path: str, params: dict[str, Any], key: str = "items") -> list[dict[str, Any]]:
        """Read a paginated Composio list, with a small hard bound on pages."""
        items: list[dict[str, Any]] = []
        cursor: str | None = None
        for _ in range(5):
            query = dict(params)
            if cursor:
                query["cursor"] = cursor
            payload = self._injected_client().request("GET", path, params=query)
            batch = payload.get(key)
            if not isinstance(batch, list):
                break
            items.extend(item for item in batch if isinstance(item, dict))
            next_cursor = payload.get("next_cursor")
            cursor = next_cursor if isinstance(next_cursor, str) and next_cursor else None
            if not cursor:
                break
        return items

    def _accounts(self, user_id: str) -> list[dict[str, Any]]:
        return self._list("/connected_accounts", {"user_ids": user_id, "limit": 100})

    def status(self) -> dict[str, Any]:
        """The whole screen's state. A Composio failure is reported, not raised."""
        if not self.configured:
            return {
                "available": True,
                "configured": False,
                "error": None,
                "connectors": [
                    self._entry(
                        connector,
                        can_connect=False,
                        reason=(
                            "Connectors are not set up on this machine."
                            if connector.available
                            else connector.note
                        ),
                    )
                    for connector in CONNECTORS
                ],
            }
        try:
            user_id = self.user_id(create=False)
            if user_id is None:
                self._probe_key()
                accounts = []
            else:
                accounts = self._accounts(user_id)
        except ConnectorError as exc:
            return {
                "available": True,
                "configured": True,
                "error": {"code": exc.code, "message": exc.message},
                "connectors": [
                    self._entry(
                        connector,
                        can_connect=False,
                        reason=exc.message if connector.available else connector.note,
                    )
                    for connector in CONNECTORS
                ],
            }
        rendered: list[dict[str, Any]] = []
        for connector in CONNECTORS:
            if not connector.available:
                rendered.append(
                    self._entry(connector, state="unavailable", can_connect=False, reason=connector.note)
                )
                continue
            mine = [account for account in accounts if _account_slug(account) == connector.slug]
            state, account = self._state_of(mine)
            rendered.append(
                self._entry(
                    connector,
                    state=state,
                    account=account,
                    can_connect=True,
                    reason=None,
                )
            )
        return {"available": True, "configured": True, "error": None, "connectors": rendered}

    @staticmethod
    def _state_of(accounts: list[dict[str, Any]]) -> tuple[str, dict[str, Any] | None]:
        if not accounts:
            return "not_connected", None
        for wanted in _STATE_PRIORITY:
            found = [account for account in accounts if str(account.get("status") or "") == wanted]
            if found:
                found.sort(key=lambda account: str(account.get("created_at") or ""), reverse=True)
                return STATE_OF[wanted], _public_account(found[0])
        return "not_connected", _public_account(accounts[0])

    # -- connect / disconnect ---------------------------------------------

    def _auth_config_id(self, connector: Connector) -> str:
        existing = self._injected_client().request(
            "GET", "/auth_configs", params={"toolkit_slug": connector.slug, "limit": 1}
        )
        items = existing.get("items")
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"]:
                    return item["id"]
        if not connector.managed_oauth:
            raise ConnectorError(
                "managed_auth_unavailable",
                f"Composio has no managed sign-in for {connector.name}. Create an auth config "
                f"for {connector.name} in the Composio project's Auth Configs (using our own app "
                "or credentials), then press Connect again. The backend holds that config; the "
                "app cannot create it for you.",
                409,
            )
        created = self._injected_client().request(
            "POST",
            "/auth_configs",
            body={"toolkit": {"slug": connector.slug}, "auth_config": {"type": "use_composio_managed_auth"}},
        )
        auth_config = created.get("auth_config")
        identifier = auth_config.get("id") if isinstance(auth_config, dict) else None
        if not isinstance(identifier, str) or not identifier:
            raise ConnectorError(
                "managed_auth_unavailable",
                f"Composio would not create a managed sign-in for {connector.name}. It may need "
                f"an OAuth app of our own.",
                409,
            )
        return identifier

    def connect(self, connector_id: str) -> dict[str, Any]:
        connector = self._require(connector_id)
        if not connector.available:
            raise ConnectorError("not_in_catalogue", connector.note, 409)
        if not self.configured:
            raise ConnectorError(
                "not_configured",
                NO_KEY,
                409,
            )
        user_id = self.user_id(create=True)
        assert user_id is not None
        accounts = self._accounts(user_id)
        mine = [account for account in accounts if _account_slug(account) == connector.slug]
        state, account = self._state_of(mine)
        if state == "connected":
            return {
                "connector": connector.id,
                "state": "connected",
                "account": account,
                "connect_url": None,
                "connected_account_id": account.get("id") if account else None,
                "expires_at": None,
            }
        auth_config_id = self._auth_config_id(connector)
        payload = self._injected_client().request(
            "POST",
            "/connected_accounts/link",
            body={"user_id": user_id, "auth_config_id": auth_config_id},
        )
        url = _safe_connect_url(payload.get("redirect_url"))
        if url is None:
            raise ConnectorError(
                "upstream",
                "Composio did not return a sign-in link this app is willing to open.",
                502,
            )
        return {
            "connector": connector.id,
            "state": "pending",
            "account": None,
            "connect_url": url,
            "connected_account_id": str(payload.get("connected_account_id") or "")[:128] or None,
            "expires_at": str(payload.get("expires_at") or "")[:40] or None,
        }

    def disconnect(self, connector_id: str) -> dict[str, Any]:
        connector = self._require(connector_id)
        if not self.configured:
            raise ConnectorError(
                "not_configured",
                NO_KEY,
                409,
            )
        user_id = self.user_id(create=False)
        if user_id is None:
            return {"connector": connector.id, "disconnected": 0, "state": "not_connected"}
        accounts = self._accounts(user_id)
        mine = [account for account in accounts if _account_slug(account) == connector.slug]
        removed = 0
        for account in mine:
            identifier = str(account.get("id") or "")
            if not _ACCOUNT_ID.match(identifier):
                continue
            try:
                self._injected_client().request(
                    "DELETE",
                    f"/connected_accounts/{quote(identifier, safe='')}",
                    params={"revoke_on_delete": "true"},
                )
            except ConnectorError as exc:
                if exc.code == "upstream" and "404" not in exc.message:
                    raise
                continue
            removed += 1
        return {"connector": connector.id, "disconnected": removed, "state": "not_connected"}

    # -- tools and execution ----------------------------------------------

    def tools(self, connector_id: str, tool: str | None = None) -> dict[str, Any]:
        """The connector's tools, compact by default; one tool's arguments when asked.

        The list is deliberately small: a Gmail toolkit alone has dozens of tools, and their
        full input schemas in one answer would fill the model's context for no reason. `tool`
        returns exactly one, with the `input_parameters` the model needs to call it correctly.
        """
        connector = self._require(connector_id)
        if not connector.available:
            raise ConnectorError("not_in_catalogue", connector.note, 409)
        if not self.configured:
            raise ConnectorError(
                "not_configured",
                NO_KEY,
                409,
            )
        rendered: list[dict[str, Any]] = []
        for definition in self._tool_list(connector):
            slug = definition.get("slug")
            if not isinstance(slug, str) or not slug:
                continue
            row = {
                "slug": slug,
                "name": str(definition.get("name") or ""),
                "description": str(definition.get("description") or "")[:400],
                "read_only": read_only(definition),
            }
            if tool:
                if slug != tool:
                    continue
                parameters = definition.get("input_parameters")
                row["parameters"] = parameters if isinstance(parameters, dict) else {}
                return {"connector": connector.id, "tool": row}
            rendered.append(row)
        if tool:
            raise ConnectorError(
                "not_in_catalogue",
                f"{tool} is not a tool of {connector.name}.",
                404,
            )
        return {"connector": connector.id, "tools": rendered}

    def _tool_list(self, connector: Connector) -> list[dict[str, Any]]:
        cached = self._tools.get(connector.slug)
        now = time.monotonic()
        if cached is not None and now - cached[0] < TOOL_CACHE_SECONDS:
            return cached[1]
        items = self._list(
            "/tools",
            {"toolkit_slug": connector.slug, "limit": 200, "include_deprecated": "false"},
        )
        self._tools[connector.slug] = (now, items)
        return items

    def is_read_only(self, connector_id: str, tool_slug: str) -> bool | None:
        """The classification the approval hook asks for. None when it cannot be known."""
        try:
            connector = self._require(connector_id)
            for tool in self._tool_list(connector):
                if str(tool.get("slug") or "") == tool_slug:
                    return read_only(tool)
        except ConnectorError:
            return None
        return None

    def execute(
        self,
        connector_id: str,
        tool: str,
        arguments: dict[str, Any],
        *,
        read_only_requested: bool,
    ) -> dict[str, Any]:
        connector = self._require(connector_id)
        if not connector.available:
            raise ConnectorError("not_in_catalogue", connector.note, 409)
        if not isinstance(tool, str) or not _TOOL_SLUG.match(tool):
            raise ConnectorError("bad_request", "A tool slug like GMAIL_FETCH_EMAILS is required.", 400)
        if not isinstance(arguments, dict):
            raise ConnectorError("bad_request", "Tool arguments must be an object.", 400)
        if not self.configured:
            raise ConnectorError(
                "not_configured",
                NO_KEY,
                409,
            )
        user_id = self.user_id(create=False)
        if user_id is None:
            raise ConnectorError("not_connected", f"{connector.name} is not connected yet.", 409)
        accounts = self._accounts(user_id)
        active = [
            account
            for account in accounts
            if _account_slug(account) == connector.slug
            and str(account.get("status") or "") == "ACTIVE"
        ]
        if not active:
            raise ConnectorError("not_connected", f"{connector.name} is not connected yet.", 409)
        known = {
            str(item.get("slug") or ""): item
            for item in self._tool_list(connector)
            if isinstance(item.get("slug"), str)
        }
        definition = known.get(tool)
        if definition is None:
            raise ConnectorError(
                "not_in_catalogue",
                f"{tool} is not a tool of {connector.name}.",
                404,
            )
        if read_only_requested and not read_only(definition):
            raise ConnectorError(
                "write_tool",
                f"{tool} changes data in {connector.name}; it is not a read.",
                409,
            )
        account_id = str(active[0].get("id") or "")
        payload = self._injected_client().request(
            "POST",
            f"/tools/execute/{quote(tool, safe='')}",
            body={
                "user_id": user_id,
                "connected_account_id": account_id,
                "arguments": arguments,
                "version": "latest",
            },
        )
        data = payload.get("data")
        rendered: Any = data
        if data is not None:
            text = json.dumps(data, default=str)
            if len(text) > MAX_TOOL_DATA_CHARS:
                rendered = text[:MAX_TOOL_DATA_CHARS] + "… (truncated; call a narrower tool for the rest)"
        return {
            "success": bool(payload.get("successful")),
            "connector": connector.id,
            "tool": tool,
            "data": rendered,
            "error": _redact(str(payload.get("error") or "")) if payload.get("error") else None,
            "log_id": str(payload.get("log_id") or "")[:80] or None,
        }


def _safe_connect_url(value: Any) -> str | None:
    """Only an absolute https link on Composio's own domain ever reaches an href."""
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not re.match(r"^https://[^\s]+$", candidate, re.IGNORECASE):
        return None
    try:
        parsed = urlparse(candidate)
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    if not host or not (host == "composio.dev" or host.endswith(".composio.dev")):
        return None
    return candidate
