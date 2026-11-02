"""The `/seam` proxy: one origin for the packaged app, and the engine's key stays out of it.

The window loads the BFF's origin, so `/seam/*` is forwarded from here with the key added on the
way through (the desktop notes §3–4). These tests bind real sockets on both sides: a fake engine
records what actually arrived, and the BFF is spoken to over HTTP, because the two things this
route must get right — header replacement and unbuffered SSE — are invisible to a dict-level call.

Run from the repo root:

    PYTHONPATH=core/src:app/server python -m unittest discover -s app/server/tests -t app/server/tests
"""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "core" / "src"))
sys.path.insert(0, str(REPO_ROOT / "app" / "server"))

from pantler_core import PackRegistry, Store  # noqa: E402

from attachments import AttachmentStore  # noqa: E402
from pantler_server import Bff, FileRoots, Handler  # noqa: E402


class FakeEngine:
    """A stand-in for the gateway that remembers exactly what the proxy sent it."""

    def __init__(self) -> None:
        self.requests: list[dict] = []
        engine = self

        class EngineHandler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args) -> None:  # a passing suite prints nothing
                pass

            def _record(self) -> bytes:
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                engine.requests.append(
                    {
                        "method": self.command,
                        "path": self.path,
                        "auth": self.headers.get("Authorization"),
                        "content_type": self.headers.get("Content-Type"),
                        "accept": self.headers.get("Accept"),
                        "body": body,
                    }
                )
                return body

            def do_GET(self) -> None:  # noqa: N802
                self._record()
                if self.path.startswith("/v1/runs/") and self.path.endswith("/events"):
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    for frame in (b"data: {\"event\": \"run.started\"}\n\n", b"data: {\"event\": \"run.completed\"}\n\n"):
                        self.wfile.write(frame)
                        self.wfile.flush()
                    self.close_connection = True
                    return
                payload = json.dumps({"ok": True, "path": self.path}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_POST(self) -> None:  # noqa: N802
                self._record()
                payload = json.dumps({"ok": True, "path": self.path}).encode()
                self.send_response(202)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_DELETE(self) -> None:  # noqa: N802
                self._record()
                self.send_response(204)
                self.send_header("Content-Length", "0")
                self.end_headers()

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), EngineHandler)
        self.httpd.daemon_threads = True
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


class SeamProxyCase(unittest.TestCase):
    engine_url: str | None = None
    key_text = "API_SERVER_KEY=test-key-123\n"

    @classmethod
    def setUpClass(cls) -> None:
        cls._dir = tempfile.TemporaryDirectory()
        root = Path(cls._dir.name)
        cls.key_file = root / ".env"
        cls.key_file.write_text(cls.key_text, encoding="utf-8")

        cls.engine = FakeEngine()
        bff = Bff(
            Store(root / "records.db"),
            PackRegistry([]),
            None,
            AttachmentStore(root / "attachments"),
            FileRoots.build(None),
        )
        cls.bff = bff

        class QuietHandler(Handler):
            def log_message(self, *args):
                pass

        handler = type(
            "BoundHandler",
            (QuietHandler,),
            {
                "bff": bff,
                "static_root": None,
                "engine_url": cls.engine_url if cls.engine_url is not None else cls.engine.url,
                "engine_key_file": cls.key_file,
                "cors_origins": (),
                "trusted_hosts": (),
                "token": "",
            },
        )
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.httpd.daemon_threads = True
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.port = cls.httpd.server_address[1]

    @classmethod
    def tearDownClass(cls) -> None:
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.engine.close()
        cls.bff.store.close()
        cls._dir.cleanup()

    def request(self, method, path, body=None, headers=None):
        merged = {"Host": f"127.0.0.1:{self.port}", **(headers or {})}
        connection = HTTPConnection("127.0.0.1", self.port, timeout=15)
        try:
            connection.request(method, path, body=body, headers=merged)
            response = connection.getresponse()
            return response.status, response.read(), {k.lower(): v for k, v in response.getheaders()}
        finally:
            connection.close()


class SeamProxyTests(SeamProxyCase):
    def test_it_forwards_the_path_query_and_method(self) -> None:
        self.engine.requests.clear()
        status, payload, headers = self.request("GET", "/seam/v1/capabilities?profile=pantler")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(payload)["path"], "/v1/capabilities?profile=pantler")
        self.assertEqual(self.engine.requests[-1]["method"], "GET")
        self.assertEqual(headers["content-type"], "application/json")

    def test_it_replaces_the_callers_authorization_with_the_profile_key(self) -> None:
        self.engine.requests.clear()
        status, _, _ = self.request(
            "GET", "/seam/v1/toolsets", headers={"Authorization": "Bearer attacker-supplied"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(self.engine.requests[-1]["auth"], "Bearer test-key-123")

    def test_it_forwards_a_json_body_and_its_content_type(self) -> None:
        self.engine.requests.clear()
        body = json.dumps({"input": "hello"}).encode()
        status, _, _ = self.request(
            "POST", "/seam/v1/runs", body=body, headers={"Content-Type": "application/json"}
        )
        self.assertEqual(status, 202)
        self.assertEqual(self.engine.requests[-1]["body"], body)
        self.assertEqual(self.engine.requests[-1]["content_type"], "application/json")

    def test_an_sse_response_is_relayed_unbuffered(self) -> None:
        status, payload, headers = self.request(
            "GET", "/seam/v1/runs/run_1/events", headers={"Accept": "text/event-stream"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(headers["content-type"], "text/event-stream")
        self.assertIn(b"run.started", payload)
        self.assertIn(b"run.completed", payload)
        self.assertEqual(self.engine.requests[-1]["accept"], "text/event-stream")

    def test_delete_passes_through_with_its_status(self) -> None:
        status, payload, _ = self.request("DELETE", "/seam/api/jobs/job_1")
        self.assertEqual(status, 204)
        self.assertEqual(payload, b"")
        self.assertEqual(self.engine.requests[-1]["method"], "DELETE")

    def test_a_path_outside_the_seam_allowlist_is_refused(self) -> None:
        status, payload, _ = self.request("GET", "/seam/dashboard")
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(payload)["error"]["code"], "not_on_seam")

    def test_an_unreachable_engine_is_a_bad_gateway(self) -> None:
        # A port nothing listens on, on the loopback interface.
        with tempfile.TemporaryDirectory() as tmp:
            handler = type(
                "UnreachableHandler",
                (Handler,),
                {
                    "bff": self.bff,
                    "static_root": None,
                    "engine_url": "http://127.0.0.1:1",
                    "engine_key_file": self.key_file,
                    "cors_origins": (),
                    "trusted_hosts": (),
                    "token": "",
                },
            )
            httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            httpd.daemon_threads = True
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
            try:
                connection = HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=10)
                connection.request("GET", "/seam/v1/capabilities")
                response = connection.getresponse()
                payload = response.read()
                connection.close()
                self.assertEqual(response.status, 502)
                self.assertEqual(json.loads(payload)["error"]["code"], "engine_unreachable")
            finally:
                httpd.shutdown()
                httpd.server_close()


class SeamDisabledTests(SeamProxyCase):
    """No engine configured: the route says so instead of forwarding anywhere."""

    engine_url = ""

    def test_seam_is_not_served_without_an_engine(self) -> None:
        status, payload, _ = self.request("GET", "/seam/v1/capabilities")
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(payload)["error"]["code"], "no_engine")


class SeamWithoutKeyTests(SeamProxyCase):
    """The engine is configured but the key file is missing: refuse, do not call the engine."""

    key_text = ""

    def test_a_missing_key_is_a_service_unavailable(self) -> None:
        status, payload, _ = self.request("GET", "/seam/v1/capabilities")
        self.assertEqual(status, 503)
        self.assertEqual(json.loads(payload)["error"]["code"], "no_engine_key")


if __name__ == "__main__":
    unittest.main()
