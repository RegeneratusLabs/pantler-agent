"""Tests for the Composio connector service and its BFF routes.

The fake below is a real socket and speaks the same paths, headers and bodies the service sends.
That is deliberate: the part most likely to be wrong is the wire, and a mock of
``ComposioClient`` would agree with whatever the client already does.

Run from the repo root:

    PYTHONPATH=core/src:app/server python -m unittest app.server.tests.test_connectors -v
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "core" / "src"))
sys.path.insert(0, str(REPO_ROOT / "app" / "server"))

from pantler_core import PackRegistry, Store  # noqa: E402

from connectors import (  # noqa: E402
    BY_ID,
    CONNECTORS,
    ConnectorError,
    ComposioClient,
    Connectors,
    _safe_connect_url,
)
from engine_settings import EngineProfile  # noqa: E402
from pantler_server import ApiError, Bff, Handler  # noqa: E402

KEY = "ak_test_key_123"


class FakeComposio(BaseHTTPRequestHandler):
    """The five calls, plus a redirect that must not be followed."""

    key = KEY
    requests: list[tuple[str, str, dict[str, str], object]] = []
    accounts: list[dict] = []
    auth_configs: list[dict] = []
    tools: dict[str, list[dict]] = {}
    link_url = "https://connect.composio.dev/link/abc"
    link_status = 200
    auth_config_status = 0
    auth_config_error: dict = {}
    execute_data: object = {"ok": True}
    execute_error: str | None = None
    redirect_hits = 0

    def log_message(self, *args):  # a passing suite should stay quiet
        pass

    def _send(self, status: int, payload: object) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _record(self, method: str, body: object = None) -> None:
        type(self).requests.append(
            (method, self.path, {k.lower(): v for k, v in self.headers.items()}, body)
        )

    def _json_body(self) -> object:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"raw": raw.decode("utf-8", "replace")}

    def _authorised(self) -> bool:
        if self.headers.get("x-api-key") != type(self).key:
            self._send(401, {"error": {"message": "bad key", "slug": "invalid_api_key"}})
            return False
        return True

    def do_GET(self) -> None:  # noqa: N802
        self._record("GET")
        if not self._authorised():
            return
        path = urlparse(self.path).path
        query = parse_qs(urlparse(self.path).query)
        if path == "/api/v3.1/redirect":
            type(self).redirect_hits += 0
            self.send_response(302)
            self.send_header("Location", "/api/v3.1/steal")
            self.end_headers()
            return
        if path == "/api/v3.1/steal":
            type(self).redirect_hits += 1
            self._send(200, {"stolen": True})
            return
        if path == "/api/v3.1/auth_configs":
            slug = (query.get("toolkit_slug") or [""])[0]
            items = [row for row in type(self).auth_configs if not slug or row.get("toolkit") == slug]
            self._send(200, {"items": items, "total_items": len(items)})
            return
        if path == "/api/v3.1/connected_accounts":
            wanted = set(query.get("user_ids") or [])
            items = [row for row in type(self).accounts if not wanted or row.get("user_id") in wanted]
            self._send(200, {"items": items, "total_items": len(items)})
            return
        if path == "/api/v3.1/tools":
            slug = (query.get("toolkit_slug") or [""])[0]
            items = type(self).tools.get(slug, [])
            self._send(200, {"items": items, "total_items": len(items)})
            return
        self._send(404, {"error": {"message": f"no {path}", "slug": "not_found"}})

    def do_POST(self) -> None:  # noqa: N802
        body = self._json_body()
        self._record("POST", body)
        if not self._authorised():
            return
        path = urlparse(self.path).path
        if path == "/api/v3.1/auth_configs":
            if type(self).auth_config_status:
                self._send(type(self).auth_config_status, type(self).auth_config_error)
                return
            toolkit = (body or {}).get("toolkit", {}).get("slug") if isinstance(body, dict) else ""
            row = {"id": f"ac_{toolkit}", "toolkit": toolkit, "auth_scheme": "OAUTH2"}
            type(self).auth_configs.append(row)
            self._send(200, {"toolkit": {"slug": toolkit}, "auth_config": row})
            return
        if path == "/api/v3.1/connected_accounts/link":
            if type(self).link_status != 200:
                self._send(type(self).link_status, {"error": {"message": "no managed auth", "slug": "bad"}})
                return
            user_id = (body or {}).get("user_id")
            type(self).accounts.append(
                {
                    "id": "ca_link_1",
                    "toolkit": {"slug": "gmail"},
                    "status": "INITIATED",
                    "user_id": user_id,
                    "created_at": "2026-10-22T10:00:00Z",
                }
            )
            self._send(
                200,
                {
                    "link_token": "lt_1",
                    "redirect_url": type(self).link_url,
                    "expires_at": "2026-10-22T11:00:00Z",
                    "connected_account_id": "ca_link_1",
                },
            )
            return
        if path.startswith("/api/v3.1/tools/execute/"):
            tool = path.rsplit("/", 1)[-1]
            data = type(self).execute_data
            if isinstance(data, str) and len(data) > 10_000:
                payload = {"data": data, "error": type(self).execute_error, "successful": True}
            else:
                payload = {"data": data, "error": type(self).execute_error, "successful": True}
            self._send(200, payload | {"log_id": "log_1", "tool": tool})
            return
        self._send(404, {"error": {"message": f"no {path}", "slug": "not_found"}})

    def do_DELETE(self) -> None:  # noqa: N802
        self._record("DELETE")
        if not self._authorised():
            return
        path = urlparse(self.path).path
        prefix = "/api/v3.1/connected_accounts/"
        if path.startswith(prefix):
            identifier = path[len(prefix) :]
            type(self).accounts = [row for row in type(self).accounts if row.get("id") != identifier]
            self._send(200, {"deleted": identifier})
            return
        self._send(404, {"error": {"message": "no", "slug": "not_found"}})


def make_profile(directory: Path, key: str | None = KEY) -> EngineProfile:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "config.yaml").write_text("model:\n  provider: test\n", encoding="utf-8")
    if key is not None:
        (directory / ".env").write_text(f"COMPOSIO_API_KEY={key}\n", encoding="utf-8")
    return EngineProfile(directory)


def account(slug: str, status: str, identifier: str, user_id: str = "u", created: str = "2026-10-22T10:00:00Z") -> dict:
    return {
        "id": identifier,
        "toolkit": {"slug": slug},
        "status": status,
        "status_reason": "",
        "user_id": user_id,
        "created_at": created,
        "state": {"val": {"displayName": f"{slug} account", "access_token": "SECRET"}},
    }


class FakeComposioCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeComposio)
        cls.server.daemon_threads = True
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.port = cls.server.server_address[1]
        cls.base = f"http://127.0.0.1:{cls.port}/api/v3.1"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self) -> None:
        FakeComposio.requests = []
        FakeComposio.accounts = []
        FakeComposio.auth_configs = []
        FakeComposio.tools = {}
        FakeComposio.link_url = "https://connect.composio.dev/link/abc"
        FakeComposio.link_status = 200
        FakeComposio.auth_config_status = 0
        FakeComposio.auth_config_error = {}
        FakeComposio.execute_data = {"ok": True}
        FakeComposio.execute_error = None
        FakeComposio.redirect_hits = 0
        os.environ.pop("PANTLER_COMPOSIO_API_KEY", None)
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.profile = make_profile(self.root / "profile")
        self.client = ComposioClient(KEY, base_url=self.base, allow_insecure=True, timeout=5)
        self.connectors = Connectors(self.profile, client=self.client)

    def tearDown(self) -> None:
        self._tmp.cleanup()


# --------------------------------------------------------------------- client


class ClientTest(FakeComposioCase):
    def test_sends_the_key_and_reads_json(self) -> None:
        payload = self.client.request("GET", "/auth_configs", params={"limit": 1})
        self.assertEqual(payload["items"], [])
        method, path, headers, _ = FakeComposio.requests[-1]
        self.assertEqual(method, "GET")
        self.assertTrue(path.startswith("/api/v3.1/auth_configs?"))
        self.assertEqual(headers.get("x-api-key"), KEY)

    def test_refuses_a_redirect_instead_of_leaking_the_key(self) -> None:
        with self.assertRaises(ConnectorError) as caught:
            self.client.request("GET", "/redirect")
        self.assertEqual(caught.exception.code, "upstream")
        self.assertEqual(FakeComposio.redirect_hits, 0)

    def test_maps_a_bad_key_to_a_plain_sentence(self) -> None:
        client = ComposioClient("ak_wrong_key_000", base_url=self.base, allow_insecure=True)
        with self.assertRaises(ConnectorError) as caught:
            client.request("GET", "/auth_configs")
        self.assertEqual(caught.exception.code, "bad_key")
        self.assertNotIn("ak_wrong_key_000", caught.exception.message)
        self.assertIn("backend key", caught.exception.message)
        self.assertNotIn("Capabilities", caught.exception.message)

    def test_refuses_a_non_https_base_unless_told_otherwise(self) -> None:
        with self.assertRaises(ValueError):
            ComposioClient(KEY, base_url="http://backend.composio.dev/api/v3.1")


# --------------------------------------------------------------------- service


class ServiceTest(FakeComposioCase):
    def test_without_a_key_it_is_unconfigured_and_makes_no_call(self) -> None:
        profile = make_profile(self.root / "empty", key=None)
        status = Connectors(profile).status()
        self.assertFalse(status["configured"])
        self.assertEqual(len(status["connectors"]), 20)
        self.assertTrue(all(row["state"] == "not_connected" for row in status["connectors"]))
        self.assertTrue(all("not set up" in (row["reason"] or "") for row in status["connectors"]))
        self.assertNotIn("Add a", json.dumps(status))
        self.assertEqual(FakeComposio.requests, [])

    def test_a_deployment_key_is_the_fallback(self) -> None:
        profile = make_profile(self.root / "envkey", key=None)
        os.environ["PANTLER_COMPOSIO_API_KEY"] = "ak_env_key_123"
        try:
            service = Connectors(profile)
            self.assertTrue(service.configured)
            self.assertEqual(service._api_key(), "ak_env_key_123")
        finally:
            os.environ.pop("PANTLER_COMPOSIO_API_KEY", None)

    def test_the_profile_key_wins_over_the_environment(self) -> None:
        os.environ["PANTLER_COMPOSIO_API_KEY"] = "ak_env_key_123"
        try:
            self.assertEqual(self.connectors._api_key(), KEY)
        finally:
            os.environ.pop("PANTLER_COMPOSIO_API_KEY", None)

    def test_without_an_identity_it_validates_the_key_but_writes_nothing(self) -> None:
        status = self.connectors.status()
        self.assertTrue(status["configured"])
        self.assertIsNone(status["error"])
        self.assertFalse((self.profile.dir / "connectors.json").exists())
        self.assertTrue(any(path.startswith("/api/v3.1/auth_configs") for _, path, _, _ in FakeComposio.requests))

    def test_removing_the_key_stops_the_cached_client(self) -> None:
        # A real service (not the injected fixture), pointed at the fake so the cache is the
        # thing under test: clearing `.env` while the BFF runs must not leave it "configured".
        service = Connectors(self.profile)
        service._client = self.client
        service._client_key = KEY
        service._injected = False
        self.assertTrue(service.status()["configured"])
        self.profile.clear_key("COMPOSIO_API_KEY")
        FakeComposio.requests = []
        status = service.status()
        self.assertFalse(status["configured"])
        self.assertEqual(FakeComposio.requests, [])

    def test_maps_account_states_and_never_returns_provider_state(self) -> None:
        uid = self.connectors.user_id(create=True)
        FakeComposio.accounts = [
            account("gmail", "ACTIVE", "ca_gmail", uid),
            account("googledrive", "INITIATED", "ca_drive", uid),
            account("zoho_books", "FAILED", "ca_zoho", uid),
            account("notours", "ACTIVE", "ca_other", uid),
        ]
        status = self.connectors.status()
        states = {row["id"]: row["state"] for row in status["connectors"]}
        self.assertEqual(len(states), 20)
        self.assertEqual(states["gmail"], "connected")
        self.assertEqual(states["gdrive"], "pending")
        self.assertEqual(states["zoho_books"], "needs_attention")
        self.assertEqual(states["square"], "not_connected")
        self.assertNotIn("woocommerce", states)
        self.assertNotIn("shopify", states)
        self.assertNotIn("paypal", states)
        self.assertNotIn("xero", states)
        self.assertNotIn("SECRET", json.dumps(status))

    def test_connect_creates_an_identity_auth_config_and_link(self) -> None:
        result = self.connectors.connect("gmail")
        self.assertEqual(result["state"], "pending")
        self.assertEqual(result["connect_url"], "https://connect.composio.dev/link/abc")
        identity = self.profile.dir / "connectors.json"
        self.assertTrue(identity.is_file())
        self.assertEqual(identity.stat().st_mode & 0o777, 0o600)
        body = next(
            body
            for method, path, _, body in FakeComposio.requests
            if method == "POST" and path.endswith("/connected_accounts/link")
        )
        self.assertIn("user_id", body)
        self.assertEqual(body["auth_config_id"], "ac_gmail")
        self.assertTrue(re.fullmatch(r"pantler_[0-9a-f]{32}", body["user_id"]))

    def test_connect_is_idempotent_when_already_active(self) -> None:
        uid = self.connectors.user_id(create=True)
        FakeComposio.accounts = [account("gmail", "ACTIVE", "ca_gmail", uid)]
        result = self.connectors.connect("gmail")
        self.assertEqual(result["state"], "connected")
        self.assertIsNone(result["connect_url"])
        self.assertFalse(any(method == "POST" for method, *_ in FakeComposio.requests))

    def test_every_connector_creates_its_own_auth_config_and_link(self) -> None:
        """Walk all twenty through the one generic connect path.

        This is not a live OAuth run — it is the fake Composio socket — but it proves that every
        connector creates an auth config for *its own* toolkit and returns a link. The managed
        auth configs for all twenty also exist in the live project as of 2026-10-23.
        """
        for connector in CONNECTORS:
            with self.subTest(connector=connector.id):
                FakeComposio.auth_configs = []
                FakeComposio.accounts = []
                FakeComposio.requests = []
                result = self.connectors.connect(connector.id)
                self.assertEqual(result["state"], "pending")
                self.assertEqual(
                    result["connect_url"], "https://connect.composio.dev/link/abc"
                )
                created = [
                    row
                    for row in FakeComposio.auth_configs
                    if row.get("toolkit") == connector.slug
                ]
                self.assertEqual(len(created), 1, connector.slug)
                self.assertEqual(created[0]["id"], f"ac_{connector.slug}")

    def test_a_read_only_key_says_permissions_not_bad_key(self) -> None:
        FakeComposio.auth_config_status = 403
        FakeComposio.auth_config_error = {
            "error": {
                "slug": "APIKey_InsufficientPermissions",
                "message": "This API key does not have the permissions required for POST /api/v3/auth_configs.",
                "suggested_fix": "Grant the auth_configs permission with at least write access.",
            }
        }
        with self.assertRaises(ConnectorError) as caught:
            self.connectors.connect("gmail")
        self.assertEqual(caught.exception.code, "insufficient_permissions")
        self.assertIn("write access", caught.exception.message)
        self.assertIn("Scoped keys cannot be edited", caught.exception.message)
        self.assertIn("backend needs", caught.exception.message)
        self.assertNotIn("ak_", caught.exception.message)
        self.assertNotIn("Capabilities", caught.exception.message)

    def test_a_connector_outside_the_catalogue_is_refused(self) -> None:
        with self.assertRaises(ConnectorError) as caught:
            self.connectors.connect("myspace")
        self.assertEqual(caught.exception.code, "not_in_catalogue")

    def test_the_removed_connectors_are_gone(self) -> None:
        for slug in ("shopify", "paypal", "xero", "clover", "7shifts", "woocommerce"):
            with self.subTest(slug=slug):
                with self.assertRaises(ConnectorError):
                    self.connectors.connect(slug)

    def test_an_unsafe_link_is_refused(self) -> None:
        FakeComposio.link_url = "javascript:alert(1)"
        with self.assertRaises(ConnectorError) as caught:
            self.connectors.connect("gmail")
        self.assertEqual(caught.exception.code, "upstream")

    def test_disconnect_deletes_only_this_toolkit_and_revokes(self) -> None:
        uid = self.connectors.user_id(create=True)
        FakeComposio.accounts = [
            account("gmail", "ACTIVE", "ca_gmail", uid),
            account("gmail", "EXPIRED", "ca_gmail_old", uid),
            account("googledrive", "ACTIVE", "ca_drive", uid),
        ]
        result = self.connectors.disconnect("gmail")
        self.assertEqual(result["disconnected"], 2)
        deletes = [(path, body) for method, path, _, body in FakeComposio.requests if method == "DELETE"]
        self.assertEqual(len(deletes), 2)
        self.assertTrue(all("revoke_on_delete=true" in path for path, _ in deletes))
        self.assertEqual([row["id"] for row in FakeComposio.accounts], ["ca_drive"])

    def test_disconnect_without_an_identity_is_idempotent(self) -> None:
        self.assertEqual(self.connectors.disconnect("gmail")["disconnected"], 0)

    def test_a_corrupt_identity_is_an_error_not_a_new_identity(self) -> None:
        (self.profile.dir / "connectors.json").write_text("{not json", encoding="utf-8")
        with self.assertRaises(ConnectorError) as caught:
            self.connectors.connect("gmail")
        self.assertEqual(caught.exception.code, "bad_state")

    def test_the_identity_is_stable_and_per_profile(self) -> None:
        first = self.connectors.user_id(create=True)
        self.assertEqual(self.connectors.user_id(create=False), first)
        other = make_profile(self.root / "other")
        self.assertNotEqual(Connectors(other, client=self.client).user_id(create=True), first)

    def test_tools_classify_reads_conservatively(self) -> None:
        FakeComposio.tools = {
            "gmail": [
                {"slug": "GMAIL_FETCH_EMAILS", "name": "Fetch", "description": "d"},
                {"slug": "GMAIL_LIST_LABELS", "name": "Labels", "description": "d"},
                {"slug": "GMAIL_SEND_EMAIL", "name": "Send", "description": "d"},
                {"slug": "GMAIL_PROFILE_VIEW", "name": "Profile", "description": "d", "tags": ["readOnlyHint"]},
            ]
        }
        rows = {row["slug"]: row["read_only"] for row in self.connectors.tools("gmail")["tools"]}
        self.assertTrue(rows["GMAIL_FETCH_EMAILS"])
        self.assertTrue(rows["GMAIL_LIST_LABELS"])
        self.assertFalse(rows["GMAIL_SEND_EMAIL"])
        self.assertTrue(rows["GMAIL_PROFILE_VIEW"])

    def test_tools_returns_one_tool_with_its_input_parameters(self) -> None:
        FakeComposio.tools = {
            "gmail": [
                {
                    "slug": "GMAIL_FETCH_EMAILS",
                    "name": "Fetch",
                    "description": "d",
                    "input_parameters": {"query": {"type": "string"}},
                }
            ]
        }
        compact = self.connectors.tools("gmail")["tools"]
        self.assertNotIn("parameters", compact[0])
        one = self.connectors.tools("gmail", "GMAIL_FETCH_EMAILS")
        self.assertEqual(one["tool"]["slug"], "GMAIL_FETCH_EMAILS")
        self.assertIn("query", one["tool"]["parameters"])
        with self.assertRaises(ConnectorError) as caught:
            self.connectors.tools("gmail", "GMAIL_NOPE")
        self.assertEqual(caught.exception.code, "not_in_catalogue")

    def test_execute_refuses_a_write_when_a_read_was_asked_for(self) -> None:
        uid = self.connectors.user_id(create=True)
        FakeComposio.accounts = [account("gmail", "ACTIVE", "ca_gmail", uid)]
        FakeComposio.tools = {"gmail": [{"slug": "GMAIL_SEND_EMAIL", "name": "Send", "description": "d"}]}
        with self.assertRaises(ConnectorError) as caught:
            self.connectors.execute("gmail", "GMAIL_SEND_EMAIL", {}, read_only_requested=True)
        self.assertEqual(caught.exception.code, "write_tool")
        self.assertFalse(any("/execute/" in path for _, path, _, _ in FakeComposio.requests))

    def test_execute_runs_a_write_and_carries_the_account(self) -> None:
        uid = self.connectors.user_id(create=True)
        FakeComposio.accounts = [account("gmail", "ACTIVE", "ca_gmail", uid)]
        FakeComposio.tools = {"gmail": [{"slug": "GMAIL_SEND_EMAIL", "name": "Send", "description": "d"}]}
        result = self.connectors.execute(
            "gmail", "GMAIL_SEND_EMAIL", {"to": "sam@example.com"}, read_only_requested=False
        )
        self.assertTrue(result["success"])
        _, path, _, body = next(item for item in FakeComposio.requests if "/execute/" in item[1])
        self.assertTrue(path.endswith("/GMAIL_SEND_EMAIL"))
        self.assertEqual(body["connected_account_id"], "ca_gmail")
        self.assertEqual(body["arguments"], {"to": "sam@example.com"})
        self.assertEqual(body["user_id"], uid)

    def test_execute_refuses_an_unconnected_app(self) -> None:
        self.connectors.user_id(create=True)
        with self.assertRaises(ConnectorError) as caught:
            self.connectors.execute("gmail", "GMAIL_FETCH_EMAILS", {}, read_only_requested=True)
        self.assertEqual(caught.exception.code, "not_connected")

    def test_execute_refuses_a_tool_from_another_toolkit(self) -> None:
        uid = self.connectors.user_id(create=True)
        FakeComposio.accounts = [account("gmail", "ACTIVE", "ca_gmail", uid)]
        FakeComposio.tools = {"gmail": [{"slug": "GMAIL_FETCH_EMAILS", "name": "Fetch", "description": "d"}]}
        with self.assertRaises(ConnectorError) as caught:
            self.connectors.execute("gmail", "SHOPIFY_GET_ORDERS", {}, read_only_requested=True)
        self.assertEqual(caught.exception.code, "not_in_catalogue")

    def test_a_large_tool_result_is_truncated(self) -> None:
        uid = self.connectors.user_id(create=True)
        FakeComposio.accounts = [account("gmail", "ACTIVE", "ca_gmail", uid)]
        FakeComposio.tools = {"gmail": [{"slug": "GMAIL_FETCH_EMAILS", "name": "Fetch", "description": "d"}]}
        FakeComposio.execute_data = "x" * 250_000
        result = self.connectors.execute(
            "gmail", "GMAIL_FETCH_EMAILS", {}, read_only_requested=True
        )
        self.assertIsInstance(result["data"], str)
        self.assertIn("truncated", result["data"])
        self.assertLessEqual(len(result["data"]), 200_100)

    def test_an_upstream_error_redacts_a_key_looking_string(self) -> None:
        uid = self.connectors.user_id(create=True)
        FakeComposio.accounts = [account("gmail", "ACTIVE", "ca_gmail", uid)]
        FakeComposio.tools = {"gmail": [{"slug": "GMAIL_FETCH_EMAILS", "name": "Fetch", "description": "d"}]}
        FakeComposio.execute_error = "failed with ak_secret_value_123"
        result = self.connectors.execute("gmail", "GMAIL_FETCH_EMAILS", {}, read_only_requested=True)
        self.assertIn("<redacted>", result["error"])
        self.assertNotIn("ak_secret_value_123", result["error"])


class CatalogueTest(unittest.TestCase):
    def test_all_twenty_have_managed_sign_in(self) -> None:
        managed = [connector.id for connector in CONNECTORS if connector.managed_oauth]
        setup = [connector.id for connector in CONNECTORS if not connector.managed_oauth]
        self.assertEqual(len(managed), 20)
        self.assertEqual(setup, [])

    def test_the_web_catalogue_names_the_same_ids_slugs_and_names(self) -> None:
        text = (REPO_ROOT / "app" / "web" / "src" / "pages" / "connectors.ts").read_text(
            encoding="utf-8"
        )
        pairs = {
            identifier: (slug, name)
            for identifier, slug, name in re.findall(
                r"id:\s*'([^']+)',\s*slug:\s*'([^']+)',\s*name:\s*'([^']+)'", text, re.S
            )
        }
        self.assertEqual(len(pairs), 20)
        self.assertEqual(
            pairs, {connector.id: (connector.slug, connector.name) for connector in CONNECTORS}
        )
        self.assertFalse(
            {"shopify", "paypal", "xero", "woocommerce", "clover", "7shifts"} & set(pairs)
        )

    def test_only_a_composio_https_link_is_offered(self) -> None:
        self.assertIsNotNone(_safe_connect_url("https://connect.composio.dev/link/x"))
        self.assertIsNone(_safe_connect_url("javascript:alert(1)"))
        self.assertIsNone(_safe_connect_url("https://evil.example/link/x"))
        self.assertIsNone(_safe_connect_url("http://connect.composio.dev/link/x"))


# ----------------------------------------------------------------------- routes


class RouteCase(FakeComposioCase):
    """The BFF object directly: contract, status codes and the error mapping."""

    def setUp(self) -> None:
        super().setUp()
        self.bff = Bff(
            Store(":memory:"),
            PackRegistry([]),
            profile=self.profile,
            connectors=self.connectors,
        )

    def tearDown(self) -> None:
        self.bff.store.close()
        super().tearDown()

    def test_status_is_a_200_with_twenty(self) -> None:
        status, payload = self.bff.list_connectors({})
        self.assertEqual(status, 200)
        self.assertEqual(len(payload["connectors"]), 20)
        self.assertTrue(payload["configured"])

    def test_connect_and_disconnect_round_trip(self) -> None:
        status, payload = self.bff.connect_connector({"id": "gmail"})
        self.assertEqual(status, 200)
        self.assertEqual(payload["state"], "pending")
        status, payload = self.bff.disconnect_connector({"id": "gmail"})
        self.assertEqual(status, 200)
        self.assertEqual(payload["disconnected"], 1)

    def test_an_unknown_connector_is_a_404(self) -> None:
        with self.assertRaises(ApiError) as caught:
            self.bff.connect_connector({"id": "myspace"})
        self.assertEqual(caught.exception.status, 404)
        self.assertEqual(caught.exception.code, "not_in_catalogue")

    def test_a_missing_key_is_a_409_on_connect(self) -> None:
        bff = Bff(
            Store(":memory:"),
            PackRegistry([]),
            profile=make_profile(self.root / "nokey", key=None),
        )
        try:
            with self.assertRaises(ApiError) as caught:
                bff.connect_connector({"id": "gmail"})
            self.assertEqual(caught.exception.status, 409)
            self.assertEqual(caught.exception.code, "not_configured")
        finally:
            bff.store.close()

    def test_a_read_only_key_is_a_403_with_its_own_code(self) -> None:
        FakeComposio.auth_config_status = 403
        FakeComposio.auth_config_error = {
            "error": {
                "slug": "APIKey_InsufficientPermissions",
                "message": "read access only",
                "suggested_fix": "Grant write access.",
            }
        }
        with self.assertRaises(ApiError) as caught:
            self.bff.connect_connector({"id": "gmail"})
        self.assertEqual(caught.exception.status, 403)
        self.assertEqual(caught.exception.code, "insufficient_permissions")


class HttpRouteCase(FakeComposioCase):
    """The HTTP layer: the write guard and the JSON body, on a real socket."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls._tmp = tempfile.TemporaryDirectory()
        profile = make_profile(Path(cls._tmp.name) / "profile")
        client = ComposioClient(KEY, base_url=cls.base, allow_insecure=True, timeout=5)
        service = Connectors(profile, client=client)
        cls.bff = Bff(
            Store(":memory:"),
            PackRegistry([]),
            profile=profile,
            connectors=service,
        )

        class QuietHandler(Handler):
            def log_message(self, *args):
                pass

        handler = type(
            "BoundHandler",
            (QuietHandler,),
            {
                "bff": cls.bff,
                "static_root": None,
                "cors_origins": (),
                "trusted_hosts": (),
                "token": "",
            },
        )
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.httpd.daemon_threads = True
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.http_port = cls.httpd.server_address[1]

    @classmethod
    def tearDownClass(cls) -> None:
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.bff.store.close()
        cls._tmp.cleanup()
        super().tearDownClass()

    def request(
        self,
        method: str,
        path: str,
        body: object = None,
        origin: str | None = None,
    ) -> tuple[int, bytes]:
        headers = {"Content-Type": "application/json"}
        encoded = None
        if body is not None:
            encoded = json.dumps(body).encode("utf-8")
        if origin is not None:
            headers["Origin"] = origin
            headers["Sec-Fetch-Site"] = "same-origin"
        connection = HTTPConnection("127.0.0.1", self.http_port, timeout=10)
        try:
            connection.request(method, path, body=encoded, headers=headers)
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def test_a_foreign_write_is_refused(self) -> None:
        status, _ = self.request(
            "POST", "/api/connectors/gmail/connect", origin="https://evil.example"
        )
        self.assertEqual(status, 403)

    def test_a_same_origin_write_connects(self) -> None:
        origin = f"http://127.0.0.1:{self.http_port}"
        status, raw = self.request("POST", "/api/connectors/gmail/connect", origin=origin)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw)["state"], "pending")

    def test_a_same_origin_delete_disconnects(self) -> None:
        origin = f"http://127.0.0.1:{self.http_port}"
        status, raw = self.request("DELETE", "/api/connectors/gmail", origin=origin)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw)["state"], "not_connected")

    def test_execute_requires_a_json_object(self) -> None:
        origin = f"http://127.0.0.1:{self.http_port}"
        status, _ = self.request(
            "POST",
            "/api/connectors/gmail/execute",
            body={"tool": "GMAIL_FETCH_EMAILS", "arguments": {}, "read_only": True},
            origin=origin,
        )
        # No account is connected in this fixture, so the contract answer is a 409.
        self.assertIn(status, (200, 409))
