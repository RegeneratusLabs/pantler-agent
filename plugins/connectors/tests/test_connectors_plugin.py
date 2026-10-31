"""The connectors plugin: the tool, its BFF client, and the write gate.

The fake BFF is a real socket. The two things that matter most are asserted against the wire:
a read carries an empty approval and runs, a write carries the approval message the engine's card
translates, and a write is refused outright when the approval hook was never registered.

    python3 -m unittest discover -s plugins/connectors/tests -t plugins/connectors/tests
"""

from __future__ import annotations

import json
import os
import socket
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parent
sys.path.insert(0, str(PLUGIN.parent))

import connectors  # noqa: E402
from connectors import tools  # noqa: E402


class FakeBff(BaseHTTPRequestHandler):
    requests: list[tuple[str, str, dict[str, str], object]] = []
    status_payload: dict = {
        "available": True,
        "configured": True,
        "error": None,
        "connectors": [
            {
                "id": "gmail",
                "name": "Gmail",
                "state": "connected",
                "account": {"display_name": "orders@bellview.example"},
                "note": "",
                "reason": None,
            }
        ],
    }
    tools_payload: dict = {
        "connector": "gmail",
        "tools": [
            {
                "slug": "GMAIL_FETCH_EMAILS",
                "name": "Fetch",
                "description": "d",
                "read_only": True,
                "parameters": {"q": {"type": "string"}},
            },
            {"slug": "GMAIL_SEND_EMAIL", "name": "Send", "description": "d", "read_only": False},
        ],
    }
    fail_status = 0
    fail_payload: dict = {}

    def log_message(self, *args):
        pass

    def _send(self, status: int, payload: object) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _record(self, body: object = None) -> None:
        type(self).requests.append(
            (self.command, self.path, {k.lower(): v for k, v in self.headers.items()}, body)
        )

    def _body(self) -> object:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        return json.loads(raw) if raw else {}

    def do_GET(self) -> None:  # noqa: N802
        self._record()
        if type(self).fail_status:
            self._send(type(self).fail_status, type(self).fail_payload)
            return
        parsed = urlparse(self.path)
        if parsed.path == "/api/connectors":
            self._send(200, type(self).status_payload)
            return
        if parsed.path.startswith("/api/connectors/") and parsed.path.endswith("/tools"):
            wanted = (parse_qs(parsed.query).get("tool") or [""])[0]
            if wanted:
                row = next(
                    (item for item in type(self).tools_payload["tools"] if item["slug"] == wanted),
                    None,
                )
                if row is None:
                    self._send(404, {"error": {"message": "no such tool", "code": "not_in_catalogue"}})
                    return
                self._send(200, {"connector": "gmail", "tool": row})
                return
            self._send(200, type(self).tools_payload)
            return
        self._send(404, {"error": {"message": "no", "code": "not_found"}})

    def do_POST(self) -> None:  # noqa: N802
        body = self._body()
        self._record(body)
        if type(self).fail_status:
            self._send(type(self).fail_status, type(self).fail_payload)
            return
        if self.path.startswith("/api/connectors/") and self.path.endswith("/execute"):
            tool = body.get("tool") if isinstance(body, dict) else ""
            self._send(
                200,
                {
                    "success": True,
                    "connector": "gmail",
                    "tool": tool,
                    "data": {"ok": True},
                    "error": None,
                    "log_id": "log_1",
                },
            )
            return
        self._send(404, {"error": {"message": "no", "code": "not_found"}})


class FakeCtx:
    def __init__(self) -> None:
        self.tools: list[tuple] = []
        self.hooks: list[tuple] = []

    def register_hook(self, name: str, callback) -> None:
        self.hooks.append((name, callback))

    def register_tool(self, name, toolset, schema, handler) -> None:
        self.tools.append((name, toolset, schema, handler))

    def get_config(self, key, default=None):
        return default


class PluginCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeBff)
        cls.server.daemon_threads = True
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.port = cls.server.server_address[1]
        cls.base = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self) -> None:
        FakeBff.requests = []
        FakeBff.fail_status = 0
        FakeBff.fail_payload = {}
        FakeBff.status_payload = {
            "available": True,
            "configured": True,
            "error": None,
            "connectors": [
                {
                    "id": "gmail",
                    "name": "Gmail",
                    "state": "connected",
                    "account": {"display_name": "orders@bellview.example"},
                    "note": "",
                    "reason": None,
                }
            ],
        }
        tools._TOOL_CACHE.clear()
        tools._HOOK_REGISTERED = False
        tools._CTX = None
        os.environ["PANTLER_BFF_URL"] = self.base
        os.environ["HERMES_PROFILE"] = "pantler"
        self.ctx = FakeCtx()

    def tearDown(self) -> None:
        os.environ.pop("PANTLER_BFF_URL", None)
        os.environ.pop("HERMES_PROFILE", None)

    def register(self) -> None:
        connectors.register(self.ctx)


class RegistrationTest(PluginCase):
    def test_registers_the_hook_before_the_tool(self) -> None:
        self.register()
        self.assertEqual([name for name, _ in self.ctx.hooks], ["pre_tool_call"])
        self.assertEqual([row[0] for row in self.ctx.tools], ["connector_use"])
        self.assertEqual(self.ctx.tools[0][1], "connectors")
        self.assertTrue(tools._HOOK_REGISTERED)

    def test_the_manifest_names_what_is_registered(self) -> None:
        text = (PLUGIN / "plugin.yaml").read_text(encoding="utf-8")
        self.assertIn("connector_use", text)
        self.assertIn("pre_tool_call", text)
        self.assertIn("license: MIT", text)


class StatusTest(PluginCase):
    def setUp(self) -> None:
        super().setUp()
        self.register()

    def test_status_reads_the_service_and_carries_the_profile(self) -> None:
        payload = json.loads(tools.connector_use({"action": "status"}))
        self.assertTrue(payload["success"])
        self.assertTrue(payload["configured"])
        self.assertEqual(payload["connectors"][0]["state"], "connected")
        headers = FakeBff.requests[-1][2]
        self.assertEqual(headers.get("x-pantler-profile"), "pantler")
        self.assertEqual(headers.get("sec-fetch-site"), "same-origin")
        self.assertTrue(headers.get("origin", "").startswith("http://127.0.0.1"))

    def test_status_says_when_no_key_is_set(self) -> None:
        FakeBff.status_payload = {
            "available": True,
            "configured": False,
            "error": None,
            "connectors": [],
        }
        payload = json.loads(tools.connector_use({"action": "status"}))
        self.assertFalse(payload["configured"])
        self.assertIn("not configured", payload["hint"])
        self.assertNotIn("Capabilities", payload["hint"])

    def test_a_bad_key_is_not_reported_as_success(self) -> None:
        FakeBff.status_payload = {
            "available": True,
            "configured": True,
            "error": {
                "code": "bad_key",
                "message": "Composio refused this key. It needs a developer project key.",
            },
            "connectors": [],
        }
        payload = json.loads(tools.connector_use({"action": "status"}))
        self.assertFalse(payload["success"])
        self.assertEqual(payload["code"], "bad_key")
        self.assertIn("developer project key", payload["error"])

    def test_a_service_that_is_not_running_is_a_sentence(self) -> None:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            dead_port = probe.getsockname()[1]
        os.environ["PANTLER_BFF_URL"] = f"http://127.0.0.1:{dead_port}"
        payload = json.loads(tools.connector_use({"action": "status"}))
        self.assertFalse(payload["success"])
        self.assertIn("not running", payload["error"])

    def test_a_refusal_is_passed_through_with_its_code(self) -> None:
        FakeBff.fail_status = 409
        FakeBff.fail_payload = {"error": {"message": "No key is set.", "code": "not_configured"}}
        payload = json.loads(tools.connector_use({"action": "tools", "connector": "gmail"}))
        self.assertFalse(payload["success"])
        self.assertEqual(payload["code"], "not_configured")
        self.assertEqual(payload["error"], "No key is set.")


class RunTest(PluginCase):
    def setUp(self) -> None:
        super().setUp()
        self.register()

    def test_a_read_runs_without_an_approval(self) -> None:
        answer = tools.pre_tool_call(
            "connector_use",
            {"action": "run", "connector": "gmail", "tool": "GMAIL_FETCH_EMAILS", "arguments": {}},
        )
        self.assertIsNone(answer)
        payload = json.loads(
            tools.connector_use(
                {
                    "action": "run",
                    "connector": "gmail",
                    "tool": "GMAIL_FETCH_EMAILS",
                    "arguments": {"query": "invoice"},
                }
            )
        )
        self.assertTrue(payload["success"])
        _, path, _, body = FakeBff.requests[-1]
        self.assertTrue(path.endswith("/api/connectors/gmail/execute"))
        self.assertEqual(body["read_only"], True)
        self.assertEqual(body["tool"], "GMAIL_FETCH_EMAILS")
        self.assertEqual(body["arguments"], {"query": "invoice"})

    def test_a_write_is_escalated_with_the_card_s_phrase(self) -> None:
        answer = tools.pre_tool_call(
            "connector_use",
            {
                "action": "run",
                "connector": "gmail",
                "tool": "GMAIL_SEND_EMAIL",
                "arguments": {"to": "sam@example.com"},
            },
        )
        self.assertIsNotNone(answer)
        assert answer is not None
        self.assertEqual(answer["action"], "approve")
        self.assertIn("Connected app change", answer["message"])
        self.assertIn("GMAIL_SEND_EMAIL", answer["message"])
        self.assertIn("sam@example.com", answer["message"])
        self.assertEqual(answer["rule_key"], "connector:gmail:GMAIL_SEND_EMAIL")

    def test_an_unclassifiable_tool_is_treated_as_a_write(self) -> None:
        answer = tools.pre_tool_call(
            "connector_use",
            {"action": "run", "connector": "gmail", "tool": "NOT_A_REAL_TOOL", "arguments": {}},
        )
        self.assertEqual(answer["action"], "approve")  # type: ignore[index]

    def test_status_and_other_tools_are_not_escalated(self) -> None:
        self.assertIsNone(tools.pre_tool_call("connector_use", {"action": "status"}))
        self.assertIsNone(tools.pre_tool_call("read_file", {"path": "x"}))

    def test_a_write_without_the_gate_is_refused_and_never_sent(self) -> None:
        tools._HOOK_REGISTERED = False
        payload = json.loads(
            tools.connector_use(
                {
                    "action": "run",
                    "connector": "gmail",
                    "tool": "GMAIL_SEND_EMAIL",
                    "arguments": {},
                }
            )
        )
        self.assertFalse(payload["success"])
        self.assertEqual(payload["code"], "no_gate")
        self.assertFalse(any(path.endswith("/execute") for _, path, _, _ in FakeBff.requests))

    def test_arguments_must_be_an_object(self) -> None:
        payload = json.loads(
            tools.connector_use(
                {
                    "action": "run",
                    "connector": "gmail",
                    "tool": "GMAIL_FETCH_EMAILS",
                    "arguments": "query=invoice",
                }
            )
        )
        self.assertFalse(payload["success"])
        self.assertEqual(payload["code"], "bad_request")

    def test_an_unknown_tool_is_refused_before_the_service(self) -> None:
        payload = json.loads(
            tools.connector_use(
                {
                    "action": "run",
                    "connector": "gmail",
                    "tool": "GMAIL_WRITE_EVERYTHING",
                    "arguments": {},
                }
            )
        )
        self.assertFalse(payload["success"])
        self.assertEqual(payload["code"], "unknown_tool")
        self.assertFalse(any(path.endswith("/execute") for _, path, _, _ in FakeBff.requests))

    def test_a_failed_execution_is_not_reported_as_success(self) -> None:
        FakeBff.fail_status = 409
        FakeBff.fail_payload = {"error": {"message": "Gmail is not connected.", "code": "not_connected"}}
        payload = json.loads(
            tools.connector_use(
                {
                    "action": "run",
                    "connector": "gmail",
                    "tool": "GMAIL_FETCH_EMAILS",
                    "arguments": {},
                }
            )
        )
        self.assertFalse(payload["success"])
        self.assertEqual(payload["code"], "not_connected")
        self.assertIn("not connected", payload["error"])

    def test_tools_lists_the_exact_slugs_and_read_flags(self) -> None:
        payload = json.loads(tools.connector_use({"action": "tools", "connector": "gmail"}))
        self.assertTrue(payload["success"])
        rows = {row["slug"]: row["read_only"] for row in payload["tools"]}
        self.assertTrue(rows["GMAIL_FETCH_EMAILS"])
        self.assertFalse(rows["GMAIL_SEND_EMAIL"])

    def test_schema_returns_one_tool_and_its_arguments(self) -> None:
        payload = json.loads(
            tools.connector_use(
                {"action": "schema", "connector": "gmail", "tool": "GMAIL_FETCH_EMAILS"}
            )
        )
        self.assertTrue(payload["success"])
        self.assertEqual(payload["tool"]["slug"], "GMAIL_FETCH_EMAILS")
        self.assertIn("q", payload["tool"]["parameters"])

    def test_the_service_is_asked_once_for_a_tool_list(self) -> None:
        tools.connector_use({"action": "tools", "connector": "gmail"})
        tools.connector_use({"action": "tools", "connector": "gmail"})
        calls = [path for _, path, _, _ in FakeBff.requests if path.endswith("/tools")]
        self.assertEqual(len(calls), 1)
