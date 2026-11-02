"""Tests for the HTTP layer itself.

`test_api.py` drives the :class:`Bff` application object directly and says so: "the HTTP layer
above it is thin and deliberately boring". That assumption is what let five defects live in it
(the internal audit SEC-1, BFF-4, BFF-5, BFF-6, BFF-7) — an origin check that could not see
intent, a refusal that left the request body in the socket, a containment check made of string
prefixes, a query string that could replace a path parameter, and an exception whose text was
echoed to the client. Every one of those failures is invisible to a call that builds a dict and
passes it to a method, so these tests bind a real socket and speak HTTP to it.

Run from the repo root:

    PYTHONPATH=core/src:app/server python -m unittest discover -s app/server/tests -t app/server/tests
"""

from __future__ import annotations

import json
import os
import socket
import sys
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "core" / "src"))
sys.path.insert(0, str(REPO_ROOT / "app" / "server"))

from pantler_core import PackRegistry, Store  # noqa: E402

import pantler_server  # noqa: E402
from attachments import AttachmentStore  # noqa: E402
from pantler_server import MAX_BODY_BYTES, Bff, FileRoots, Handler, Route  # noqa: E402


class HttpCase(unittest.TestCase):
    """A real server on a real port, with the real handler."""

    static_root: Path | None = None
    cors_origins: tuple[str, ...] = ()
    #: Names the server was told to answer to, as `--allow-host`/`$PANTLER_ALLOWED_HOSTS`
    #: would supply them. Empty means only the machine's own addresses are trusted.
    trusted_hosts: tuple[str, ...] = ()
    files_root: Path | None = None
    token: str = ""

    @classmethod
    def setUpClass(cls) -> None:
        cls._dir = tempfile.TemporaryDirectory()
        root = Path(cls._dir.name)
        bff = Bff(
            Store(root / "records.db"),
            PackRegistry([]),
            None,
            AttachmentStore(root / "attachments"),
            FileRoots.build([str(cls.files_root)] if cls.files_root else None),
        )
        cls.bff = bff

        class QuietHandler(Handler):
            def log_message(self, *args):  # a passing suite should not print a request log
                pass

        handler = type(
            "BoundHandler",
            (QuietHandler,),
            {
                "bff": bff,
                "static_root": cls.static_root,
                "cors_origins": cls.cors_origins,
                "trusted_hosts": cls.trusted_hosts,
                "token": cls.token,
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
        cls.bff.store.close()
        cls._dir.cleanup()

    @property
    def own_origin(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def request(
        self,
        method: str,
        path: str,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, bytes, dict[str, str]]:
        merged = dict(headers or {})
        if method not in ("GET", "HEAD", "OPTIONS") and not (
            {"Origin", "Referer", "Sec-Fetch-Site", "X-Pantler-Token"} & set(merged)
        ):
            # What a browser sends for the app's own writes. The guard asks a write for one
            # positive signal (the internal security audit A19-EX-2); tests that want to
            # prove the refusal pass their own headers instead.
            merged["Origin"] = self.own_origin
            merged["Sec-Fetch-Site"] = "same-origin"
        connection = HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            connection.request(method, path, body=body, headers=merged)
            response = connection.getresponse()
            payload = response.read()
            return response.status, payload, {k.lower(): v for k, v in response.getheaders()}
        finally:
            connection.close()

    def json_request(self, method: str, path: str, body, headers: dict[str, str] | None = None):
        merged = {"Content-Type": "application/json", **(headers or {})}
        return self.request(method, path, json.dumps(body).encode(), merged)

    def raw_request(
        self,
        method: str,
        path: str,
        body: bytes | None,
        headers: dict[str, str] | None,
    ) -> tuple[int, bytes, dict[str, str]]:
        """No signal injection: the caller's headers are the whole request."""
        connection = HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            payload = response.read()
            return response.status, payload, {k.lower(): v for k, v in response.getheaders()}
        finally:
            connection.close()


# ---------------------------------------------------------------- SEC-1 · origins


class OriginTests(HttpCase):
    """A page on another origin must not read a response or make a write."""

    def test_a_foreign_origin_gets_no_cors_headers_on_a_read(self) -> None:
        # The read itself is not the door — the header is. Serving it costs nothing; the
        # browser withholds the body because no origin was granted.
        status, _, headers = self.request(
            "GET", "/api/health", headers={"Origin": "https://evil.example"}
        )
        self.assertEqual(status, 200)
        self.assertNotIn("access-control-allow-origin", headers)
        self.assertNotIn("access-control-allow-methods", headers)

    def test_our_own_origin_is_answered_with_itself(self) -> None:
        status, _, headers = self.request("GET", "/api/health", headers={"Origin": self.own_origin})
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("access-control-allow-origin"), self.own_origin)
        self.assertEqual(headers.get("vary"), "Origin")

    def test_a_preflight_from_a_foreign_origin_is_refused_without_cors_headers(self) -> None:
        status, body, headers = self.request(
            "OPTIONS",
            "/api/settings/model",
            headers={
                "Origin": "https://evil.example",
                "Access-Control-Request-Method": "PUT",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        self.assertEqual(status, 403)
        self.assertEqual(json.loads(body)["error"]["code"], "cross_origin")
        self.assertNotIn("access-control-allow-origin", headers)
        self.assertNotIn("access-control-allow-methods", headers)

    def test_a_preflight_from_our_own_origin_is_answered(self) -> None:
        status, _, headers = self.request(
            "OPTIONS",
            "/api/settings/model",
            headers={
                "Origin": self.own_origin,
                "Access-Control-Request-Method": "PUT",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        self.assertEqual(status, 204)
        self.assertEqual(headers.get("access-control-allow-origin"), self.own_origin)

    def test_a_write_from_a_foreign_origin_is_refused(self) -> None:
        status, body, _ = self.json_request(
            "PUT",
            "/api/settings/model",
            {"default": "evil/model"},
            {"Origin": "https://evil.example"},
        )
        self.assertEqual(status, 403)
        self.assertEqual(json.loads(body)["error"]["code"], "cross_origin")

    def test_a_write_the_browser_calls_cross_site_is_refused_even_with_no_origin(self) -> None:
        status, body, _ = self.json_request(
            "PUT", "/api/settings/model", {"default": "x"}, {"Sec-Fetch-Site": "cross-site"}
        )
        self.assertEqual(status, 403)
        self.assertEqual(json.loads(body)["error"]["code"], "cross_origin")

    def test_a_write_with_a_foreign_referer_is_refused(self) -> None:
        status, _, _ = self.json_request(
            "PUT",
            "/api/settings/model",
            {"default": "x"},
            {"Referer": "https://evil.example/page"},
        )
        self.assertEqual(status, 403)

    def test_a_write_from_our_own_origin_reaches_the_application(self) -> None:
        # No profile is configured, so the application answers 503 — the point is that it is
        # not the 403 the origin guard gives: a legitimate write got past the guard.
        status, body, _ = self.json_request(
            "PUT", "/api/settings/model", {"default": "x"}, {"Origin": self.own_origin}
        )
        self.assertNotEqual(status, 403, body)


# ------------------------------------------- A19-EX-1/EX-2 · what a host is worth


class HostTrustTests(HttpCase):
    """A Host header is only this app when it names an address this machine holds.

    Before this, the check was `host_of(Origin) == Host`, and DNS rebinding sends both — the
    attacker's page is served from `http://evil.example:<port>` and, once that name resolves to
    127.0.0.1, its own same-origin requests carry exactly that pair
    (the internal security audit A19-EX-1).
    """

    def bare(self, method: str, path: str, body: bytes | None = None, **headers: str):
        """A request with exactly the headers given — no browser-signal injection."""
        return self.raw_request(method, path, body, headers)

    def test_a_rebound_host_gets_no_cors_headers_on_a_read(self) -> None:
        status, _, headers = self.bare(
            "GET",
            "/api/health",
            Host=f"evil.example:{self.port}",
            Origin=f"http://evil.example:{self.port}",
            **{"Sec-Fetch-Site": "same-origin"},
        )
        self.assertEqual(status, 200)
        self.assertNotIn("access-control-allow-origin", headers)

    def test_a_rebound_host_cannot_write(self) -> None:
        status, body, _ = self.bare(
            "PUT",
            "/api/settings/model",
            json.dumps({"default": "evil/model"}).encode(),
            Host=f"evil.example:{self.port}",
            Origin=f"http://evil.example:{self.port}",
            **{"Sec-Fetch-Site": "same-origin", "Content-Type": "application/json"},
        )
        self.assertEqual(status, 403)
        self.assertEqual(json.loads(body)["error"]["code"], "cross_origin")

    def test_a_rebound_host_cannot_write_even_with_a_matching_referer(self) -> None:
        status, _, _ = self.bare(
            "PUT",
            "/api/settings/model",
            json.dumps({"default": "evil/model"}).encode(),
            Host=f"evil.example:{self.port}",
            Referer=f"http://evil.example:{self.port}/settings",
            **{"Content-Type": "application/json"},
        )
        self.assertEqual(status, 403)

    def test_the_machines_own_name_still_works(self) -> None:
        # The honest case must not be collateral damage: same origin, real host.
        status, _, headers = self.raw_request(
            "GET", "/api/health", None, {"Origin": self.own_origin}
        )
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("access-control-allow-origin"), self.own_origin)

    def test_a_write_with_no_signal_at_all_is_refused(self) -> None:
        # A script sends none of these headers. It must present the token instead of being
        # assumed friendly (the internal security audit A19-EX-2).
        status, body, _ = self.bare(
            "PUT",
            "/api/settings/model",
            json.dumps({"default": "x"}).encode(),
            **{"Content-Type": "application/json"},
        )
        self.assertEqual(status, 403)
        self.assertEqual(json.loads(body)["error"]["code"], "cross_origin")

    def test_an_unrecognised_front_door_is_told_which_setting_is_missing(self) -> None:
        # The operator is in the app, reached by a name the server was never told about — a
        # tailnet/MagicDNS name through the dev proxy. The refusal used to say "come from the
        # app", which is where they already are; it names the setting that fixes it now.
        # This is the deployed failure of 2026-10-22 (a feature brief).
        status, body, _ = self.bare(
            "POST",
            "/api/profiles",
            json.dumps({"name": "garden"}).encode(),
            Host=f"pantler.example:{self.port}",
            Origin=f"http://pantler.example:{self.port}",
            **{"Sec-Fetch-Site": "same-origin", "Content-Type": "application/json"},
        )
        self.assertEqual(status, 403)
        payload = json.loads(body)["error"]
        self.assertEqual(payload["code"], "cross_origin")
        self.assertIn("PANTLER_ALLOWED_HOSTS", payload["message"])

    def test_a_page_from_another_site_still_gets_the_ordinary_refusal(self) -> None:
        status, body, _ = self.bare(
            "PUT",
            "/api/settings/model",
            json.dumps({"default": "x"}).encode(),
            Origin="https://evil.example",
            **{"Sec-Fetch-Site": "same-origin", "Content-Type": "application/json"},
        )
        self.assertEqual(status, 403)
        self.assertNotIn("PANTLER_ALLOWED_HOSTS", json.loads(body)["error"]["message"])


class AllowedHostTests(HttpCase):
    """A name the deployment declares is this app, so its own writes are accepted.

    `--allow-host` / `$PANTLER_ALLOWED_HOSTS` is how a tailnet front door stops looking like a
    foreign page: the browser's Origin names the same host as its Host, and that host is now
    one this server was told to answer to.
    """

    trusted_hosts = ("pantler.example",)

    def bare(self, method: str, path: str, body: bytes | None = None, **headers: str):
        return self.raw_request(method, path, body, headers)

    def test_a_declared_name_can_write(self) -> None:
        status, body, _ = self.bare(
            "PUT",
            "/api/settings/model",
            json.dumps({"default": "x"}).encode(),
            Host=f"pantler.example:{self.port}",
            Origin=f"http://pantler.example:{self.port}",
            **{"Sec-Fetch-Site": "same-origin", "Content-Type": "application/json"},
        )
        # No profile is configured, so 503 is the application answering — the point is that
        # it is not the 403 the origin guard gives.
        self.assertNotEqual(status, 403, body)

    def test_a_declared_name_is_answered_with_its_own_origin(self) -> None:
        origin = f"http://pantler.example:{self.port}"
        status, _, headers = self.bare(
            "GET", "/api/health", None, Host=f"pantler.example:{self.port}", Origin=origin
        )
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("access-control-allow-origin"), origin)

    def test_an_undeclared_name_is_still_refused(self) -> None:
        status, body, _ = self.bare(
            "PUT",
            "/api/settings/model",
            json.dumps({"default": "x"}).encode(),
            Host=f"other.example:{self.port}",
            Origin=f"http://other.example:{self.port}",
            **{"Sec-Fetch-Site": "same-origin", "Content-Type": "application/json"},
        )
        self.assertEqual(status, 403)
        self.assertEqual(json.loads(body)["error"]["code"], "cross_origin")


class AllowedHostsEnvTests(unittest.TestCase):
    """`PANTLER_ALLOWED_HOSTS` names the front door for the dev server and the BFF alike."""

    def parse(self, value: str):
        with patch.dict(os.environ, {"PANTLER_ALLOWED_HOSTS": value}, clear=False):
            return pantler_server.hosts_from_env()

    def test_a_comma_separated_list_is_split_and_trimmed(self) -> None:
        self.assertEqual(self.parse(" a.example , b.example "), ["a.example", "b.example"])

    def test_an_empty_variable_names_nothing(self) -> None:
        self.assertIsNone(self.parse(""))
        self.assertIsNone(self.parse(" , "))

    def test_a_domain_wildcard_is_not_trusted(self) -> None:
        # Vite's leading-dot spelling is a wildcard; this server only ever trusts a whole name.
        self.assertEqual(self.parse(".example, c.example"), ["c.example"])


class TokenWriteTests(HttpCase):
    """With `--token`, a non-browser caller carries a secret instead of a browser signal."""

    token = "s3cret-token-for-the-test"

    def test_a_script_with_the_token_may_write(self) -> None:
        status, body, _ = self.raw_request(
            "PUT",
            "/api/settings/model",
            json.dumps({"default": "x"}).encode(),
            {"Content-Type": "application/json", "X-Pantler-Token": self.token},
        )
        # No profile: 503 is the application answering, which is the point — not 403.
        self.assertNotEqual(status, 403, body)

    def test_a_script_with_the_wrong_token_is_refused(self) -> None:
        status, _, _ = self.raw_request(
            "PUT",
            "/api/settings/model",
            json.dumps({"default": "x"}).encode(),
            {"Content-Type": "application/json", "X-Pantler-Token": "not-the-token"},
        )
        self.assertEqual(status, 403)

    def test_the_token_is_not_needed_by_a_browser_shaped_write(self) -> None:
        status, body, _ = self.raw_request(
            "PUT",
            "/api/settings/model",
            json.dumps({"default": "x"}).encode(),
            {"Content-Type": "application/json", "Origin": self.own_origin},
        )
        self.assertNotEqual(status, 403, body)


# ------------------------------------------------------- BFF-4 · the unread body


class BodyDrainTests(HttpCase):
    """A refusal that leaves a body in the socket must not desynchronise the connection."""

    def read_one_response(self, connection: socket.socket) -> tuple[str, dict[str, str], bytes]:
        """One whole HTTP response off a raw socket, so a test can look at what follows it."""
        buffer = b""
        while b"\r\n\r\n" not in buffer:
            chunk = connection.recv(65536)
            if not chunk:
                break
            buffer += chunk
        head, _, rest = buffer.partition(b"\r\n\r\n")
        lines = head.decode("latin-1").split("\r\n")
        headers = {}
        for line in lines[1:]:
            name, _, value = line.partition(":")
            headers[name.strip().lower()] = value.strip()
        length = int(headers.get("content-length") or 0)
        while len(rest) < length:
            chunk = connection.recv(65536)
            if not chunk:
                break
            rest += chunk
        return lines[0], headers, rest[:length]

    def test_an_oversize_body_does_not_poison_the_next_request(self) -> None:
        connection = socket.create_connection(("127.0.0.1", self.port), timeout=10)
        try:
            connection.sendall(
                f"POST /api/records/nothing HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\n".encode()
                # The write guard runs before the body cap, so a browser-shaped signal is what
                # gets this request as far as the oversize refusal.
                + f"Origin: http://127.0.0.1:{self.port}\r\n".encode()
                + b"Content-Type: application/json\r\n"
                + f"Content-Length: {MAX_BODY_BYTES + 1}\r\n\r\n".encode()
                + b"x" * 40
            )
            status_line, headers, body = self.read_one_response(connection)
            self.assertIn("413", status_line)
            self.assertEqual(headers.get("connection"), "close")
            self.assertIn(b"too_large", body)

            # The connection must now be finished: either the server closed it, or the body
            # was drained and a fresh request is answered. What must not happen is the
            # leftover body being parsed as the next request line.
            connection.sendall(b"GET /api/health HTTP/1.1\r\nHost: h\r\n\r\n")
            try:
                following = connection.recv(65536)
            except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
                # Windows reports a peer close as WSAECONNABORTED rather than a reset.
                following = b""
            self.assertTrue(
                following == b"" or following.startswith(b"HTTP/1.1 200"),
                f"the connection desynchronised: {following[:160]!r}",
            )
        finally:
            connection.close()

    def test_a_body_carrying_request_to_an_unknown_route_ends_the_connection(self) -> None:
        # Nothing read this body, so the socket still holds it. Reusing the connection would
        # parse those bytes as the next request line.
        status, _, headers = self.request("POST", "/api/health", b"{}", {"Content-Length": "2"})
        self.assertEqual(status, 405)
        self.assertEqual(headers.get("connection"), "close")

    def test_a_bodyless_request_to_an_unknown_route_keeps_the_connection(self) -> None:
        status, _, headers = self.request("GET", "/api/nothing-here")
        self.assertEqual(status, 404)
        self.assertNotEqual(headers.get("connection"), "close")

    def test_a_body_the_handler_reads_keeps_the_connection(self) -> None:
        # A parsed body is consumed, so the connection is reusable — the close is not blanket.
        status, body, headers = self.json_request("PUT", "/api/settings/model", {"default": "x"})
        self.assertEqual(status, 503)  # no profile configured
        self.assertNotEqual(headers.get("connection"), "close")

    # ------------------------------------------- A19-EX-4 · a negative Content-Length

    def test_a_negative_content_length_is_refused_rather_than_read_forever(self) -> None:
        # `int("-1")` used to fall through every check into `rfile.read(-1)`, which is "read
        # until the peer closes": unbounded memory and a parked thread
        # (the internal security audit A19-EX-4). The refusal must be immediate, and must
        # not wait for the client to close.
        for path in ("/api/records/nothing", "/api/attachments"):
            with self.subTest(path=path):
                connection = socket.create_connection(("127.0.0.1", self.port), timeout=10)
                try:
                    connection.sendall(
                        f"POST {path} HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\n".encode()
                        + f"Origin: http://127.0.0.1:{self.port}\r\n".encode()
                        + b"Content-Type: application/json\r\n"
                        + b"X-Attachment-Name: x.bin\r\n"
                        + b"Content-Length: -1\r\n\r\n"
                    )
                    # No shutdown, no more bytes: a server that reads until EOF answers nothing.
                    status_line, _, body = self.read_one_response(connection)
                    self.assertIn("400", status_line)
                    self.assertIn(b"bad_body", body)
                finally:
                    connection.close()

    def test_a_get_with_a_declared_body_ends_the_connection(self) -> None:
        # A success path that leaves a body unread is the same smuggling primitive as a refusal
        # that does (the internal security audit A19-EX-13).
        connection = socket.create_connection(("127.0.0.1", self.port), timeout=10)
        try:
            connection.sendall(
                f"GET /api/health HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\n".encode()
                + b"Content-Length: 44\r\n\r\n"
                + f"GET /api/health HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\n\r\n".encode()
            )
            status_line, headers, _ = self.read_one_response(connection)
            self.assertIn("200", status_line)
            self.assertEqual(headers.get("connection"), "close")
            # And nothing else is answered on this connection.
            try:
                following = connection.recv(65536)
            except (ConnectionResetError, BrokenPipeError):
                following = b""
            self.assertTrue(
                following == b"" or not following.startswith(b"HTTP/1.1 200"),
                f"a second response came back on one connection: {following[:120]!r}",
            )
        finally:
            connection.close()


# ------------------------------------------------- BFF-5 · the static-file jail


class StaticJailTests(HttpCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._outer = tempfile.TemporaryDirectory()
        outer = Path(cls._outer.name)
        (outer / "shell").mkdir()
        (outer / "shell" / "index.html").write_text("PUBLIC", encoding="utf-8")
        (outer / "shell-evil").mkdir()
        (outer / "shell-evil" / "secret.txt").write_text("SECRET", encoding="utf-8")
        cls.static_root = outer / "shell"
        super().setUpClass()

    @classmethod
    def tearDownClass(cls) -> None:
        super().tearDownClass()
        cls._outer.cleanup()

    def test_the_root_itself_is_served(self) -> None:
        status, body, _ = self.request("GET", "/index.html")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"PUBLIC")

    def test_a_sibling_directory_is_not_reachable_through_dot_dot(self) -> None:
        for target in (
            "/../shell-evil/secret.txt",
            "/%2e%2e/shell-evil/secret.txt",
            "/..%2fshell-evil/secret.txt",
        ):
            with self.subTest(target=target):
                status, body, _ = self.request("GET", target)
                self.assertNotEqual(status, 200, f"{target} escaped the static root: {body!r}")
                self.assertNotIn(b"SECRET", body)


# ------------------------------------------------- BFF-6 · query and path params


class ParameterTests(HttpCase):
    def test_a_query_parameter_cannot_replace_a_path_parameter(self) -> None:
        plain = self.request("GET", "/api/attachments/zzz")
        self.assertEqual(plain[0], 400)
        self.assertEqual(json.loads(plain[1])["error"]["code"], "invalid_id")

        overridden = self.request("GET", "/api/attachments/zzz?id=0123456789ab")
        self.assertEqual(
            overridden[0],
            400,
            f"the query string replaced the id in the path: {overridden[1]!r}",
        )
        self.assertEqual(json.loads(overridden[1])["error"]["code"], "invalid_id")

    def test_the_route_still_reads_its_own_query_parameters(self) -> None:
        # `limit` is genuinely a query parameter, and must keep working.
        status, body, _ = self.request("GET", "/api/records/note?limit=5")
        self.assertEqual(status, 404)  # no pack declares `note` in this server
        self.assertEqual(json.loads(body)["error"]["code"], "unknown_record_type")


# ------------------------------------------------------ BFF-7 · what a 500 says


class ErrorDisclosureTests(HttpCase):
    def test_an_unhandled_exception_is_not_echoed_to_the_client(self) -> None:
        def explode(_params):
            raise ValueError("the secret is hunter2 at /home/you/private")

        self.bff.explode_for_the_test = explode  # type: ignore[attr-defined]
        original = pantler_server.ROUTES
        pantler_server.ROUTES = original + (
            Route("GET", r"/api/explode", "explode_for_the_test"),
        )
        try:
            status, body, _ = self.request("GET", "/api/explode")
        finally:
            pantler_server.ROUTES = original

        self.assertEqual(status, 500)
        text = body.decode()
        self.assertNotIn("hunter2", text)
        self.assertNotIn("ValueError", text)
        self.assertNotIn("/home/you/private", text)
        self.assertEqual(json.loads(body)["error"]["code"], "internal")


class MediaTypeTests(HttpCase):
    """The one write a cross-site request could still reach, and why it cannot.

    `text/plain` is one of the three content types a browser may send without a preflight, so
    before this check a page on any origin could POST a JSON body to a route that parses
    whatever it is given. `PATCH` and `DELETE` need the preflight the origin guard refuses;
    `POST` did not (the internal audit SEC-1).
    """

    def test_a_json_body_must_say_it_is_json(self) -> None:
        status, body, _ = self.request(
            "POST",
            "/api/records/note",
            b'{"title": "from another page"}',
            {"Content-Type": "text/plain"},
        )
        self.assertEqual(status, 415)
        self.assertEqual(json.loads(body)["error"]["code"], "unsupported_media_type")

    def test_a_form_encoded_body_is_not_read_as_json(self) -> None:
        status, _, _ = self.request(
            "POST",
            "/api/records/note",
            b"title=x",
            {"Content-Type": "application/x-www-form-urlencoded"},
        )
        self.assertEqual(status, 415)

    def test_the_right_type_still_reaches_the_route(self) -> None:
        status, body, _ = self.json_request("POST", "/api/records/note", {"title": "x"})
        # This server's registry is empty, so the *route* answers — the point is that it is
        # reached at all rather than refused by the transport.
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(body)["error"]["code"], "unknown_record_type")

    def test_a_bodyless_request_is_not_asked_about_its_type(self) -> None:
        status, _, _ = self.request("PATCH", "/api/records/note/NOTE-1", b"", {})
        self.assertEqual(status, 404)  # no pack declares `note` here


class HostileInputTests(HttpCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._files = tempfile.TemporaryDirectory()
        root = Path(cls._files.name)
        (root / "probe.txt").write_text("hello", encoding="utf-8")
        cls.files_root = root
        super().setUpClass()

    @classmethod
    def tearDownClass(cls) -> None:
        super().tearDownClass()
        cls._files.cleanup()

    def test_a_range_header_with_absurd_digits_is_not_a_500(self) -> None:
        status, body, _ = self.request(
            "GET",
            "/api/files/raw?path=" + str(self.files_root / "probe.txt"),
            headers={"Range": "bytes=" + "9" * 5000 + "-"},
        )
        self.assertNotEqual(status, 500, body)
        self.assertNotIn(b"ValueError", body)
        self.assertNotIn(b"Traceback", body)

    def test_a_sane_range_still_works(self) -> None:
        status, body, headers = self.request(
            "GET",
            "/api/files/raw?path=" + str(self.files_root / "probe.txt"),
            headers={"Range": "bytes=0-1"},
        )
        self.assertEqual(status, 206)
        self.assertEqual(body, b"he")
        self.assertEqual(headers.get("content-range"), "bytes 0-1/5")

    def test_an_unsatisfiable_range_still_answers_416(self) -> None:
        status, _, headers = self.request(
            "GET",
            "/api/files/raw?path=" + str(self.files_root / "probe.txt"),
            headers={"Range": "bytes=99-"},
        )
        self.assertEqual(status, 416)
        self.assertEqual(headers.get("content-range"), "bytes */5")


if __name__ == "__main__":
    unittest.main()


class StaticHeaderTests(HttpCase):
    """The built shell is the one document that renders model output — it carries the policy."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._outer = tempfile.TemporaryDirectory()
        root = Path(cls._outer.name) / "shell"
        root.mkdir(parents=True)
        (root / "index.html").write_text(
            "<!doctype html><html><head>"
            "<script>var t = 1</script>"
            "<script type=\"module\" src=\"/src/main.tsx\"></script>"
            "</head><body></body></html>",
            encoding="utf-8",
        )
        cls.static_root = root
        super().setUpClass()

    @classmethod
    def tearDownClass(cls) -> None:
        super().tearDownClass()
        cls._outer.cleanup()

    def test_the_shell_carries_a_policy_hashed_from_its_own_bytes(self) -> None:
        import base64
        import hashlib

        status, body, headers = self.request("GET", "/")
        self.assertEqual(status, 200)
        csp = headers.get("content-security-policy") or ""
        self.assertIn("script-src 'self'", csp)
        self.assertIn("frame-ancestors 'none'", csp)
        expected = base64.b64encode(hashlib.sha256(b"var t = 1").digest()).decode()
        self.assertIn(f"'sha256-{expected}'", csp)
        # The module script is not inline, so it must not be hashed.
        self.assertEqual(csp.count("sha256-"), 1)
        self.assertEqual(headers.get("x-frame-options"), "DENY")
        self.assertEqual(headers.get("x-content-type-options"), "nosniff")
        self.assertEqual(headers.get("referrer-policy"), "no-referrer")


class LocalAddressTest(unittest.TestCase):
    """A Host is this machine only when the machine says so, and it is asked, not resolved."""

    def test_loopback_and_this_machines_own_addresses_are_local(self) -> None:
        for name in ("127.0.0.1", "::1"):
            with self.subTest(name=name):
                self.assertTrue(pantler_server.is_local_address(name))

    def test_an_address_this_machine_does_not_hold_is_not_local(self) -> None:
        # TEST-NET-1: reserved for documentation, never an interface address.
        self.assertFalse(pantler_server.is_local_address("192.0.2.1"))
        self.assertFalse(pantler_server.is_local_address("198.51.100.7"))

    def test_the_machines_default_route_address_is_recognised(self) -> None:
        # The case `getaddrinfo(hostname)` misses on a normal machine — and the one the tailnet
        # and LAN phone tiers arrive as. A UDP connect sends nothing; it only picks a route.
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(("192.0.2.1", 9))
            primary = probe.getsockname()[0]
        except OSError:
            self.skipTest("this machine has no default route to ask")
        finally:
            probe.close()
        self.assertTrue(pantler_server.is_local_address(primary), primary)

    def test_a_name_is_not_local_merely_because_it_resolves(self) -> None:
        # `localhost` is in the static set; an arbitrary name is not, and resolving it is exactly
        # what a rebinding attacker controls (the internal security audit A19-EX-1).
        self.assertFalse(pantler_server.is_local_address("evil.example"))
        self.assertTrue(pantler_server.host_name("evil.example:8650"))
