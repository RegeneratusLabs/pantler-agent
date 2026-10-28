"""The profile header, over a real socket.

The router's own tests call it with a dict. This one proves the HTTP layer actually reads
``X-Pantler-Profile`` and hands it to the router — the piece between a browser tab and the
per-profile store, which no direct call can cover.
"""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "core" / "src"))
sys.path.insert(0, str(REPO_ROOT / "app" / "server"))

from pantler_core import PackRegistry, Store, pack_from_dict  # noqa: E402

from attachments import AttachmentStore  # noqa: E402
from engine_settings import EngineProfile  # noqa: E402
from pantler_server import Bff, BffRouter, Handler  # noqa: E402
from profiles import ProfileManager  # noqa: E402

PACK = {
    "id": "example",
    "name": "Example",
    "records": [
        {
            "type": "note",
            "label": "Note",
            "plural": "Notes",
            "id_prefix": "NOTE",
            "id_sequence": True,
            "fields": [{"name": "title", "label": "Title", "required": True}],
        }
    ],
}


class ProfileHttpCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._dir = tempfile.TemporaryDirectory()
        root = Path(cls._dir.name)
        home = root / ".hermes-dev"
        profiles = home / "profiles"
        install = profiles / "pantler"
        install.mkdir(parents=True)
        (install / "config.yaml").write_text(
            "model:\n  provider: test\n  default: test-model\n", encoding="utf-8"
        )
        (install / ".env").write_text("API_SERVER_KEY=test-key-that-is-long-enough\n", encoding="utf-8")
        cls.base_store = root / ".data" / "records.db"
        cls.base_attachments = root / ".data" / "attachments"
        cls.manager = ProfileManager(
            install,
            store_path=cls.base_store,
            attachments_dir=cls.base_attachments,
            repo_root=root,
        )
        cls.manager.create("garden")
        cls.registry = PackRegistry([pack_from_dict(PACK)])

        def make(name: str) -> Bff:
            return Bff(
                Store(cls.manager.store_for(name)),
                cls.registry,
                EngineProfile(cls.manager.path_for(name)),
                AttachmentStore(cls.manager.attachments_for(name)),
            )

        cls.base = make("pantler")
        cls.router = BffRouter(cls.base, cls.manager, make)

        class QuietHandler(Handler):
            def log_message(self, *args):
                pass

        handler = type("BoundHandler", (QuietHandler,), {"bff": cls.router})
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.httpd.daemon_threads = True
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.port = cls.httpd.server_address[1]

    @classmethod
    def tearDownClass(cls) -> None:
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.router.close()
        cls._dir.cleanup()

    def request(self, method: str, path: str, body: dict | None = None, profile: str | None = None):
        headers = {
            "Origin": f"http://127.0.0.1:{self.port}",
            "Sec-Fetch-Site": "same-origin",
        }
        if body is not None:
            headers["Content-Type"] = "application/json"
        if profile is not None:
            headers["X-Pantler-Profile"] = profile
        connection = HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            connection.request(
                method, path, body=None if body is None else json.dumps(body), headers=headers
            )
            response = connection.getresponse()
            return response.status, json.loads(response.read().decode() or "{}")
        finally:
            connection.close()

    def test_the_header_selects_the_store(self) -> None:
        status, created = self.request(
            "POST", "/api/records/note", {"title": "garden note"}, profile="garden"
        )
        self.assertEqual(status, 201)
        self.assertEqual(created["id"], "NOTE-0001")

        status, page = self.request("GET", "/api/records/note", profile="garden")
        self.assertEqual(page["total"], 1)

        status, page = self.request("GET", "/api/records/note", profile="pantler")
        self.assertEqual(page["total"], 0)

    def test_an_unknown_profile_is_a_404_not_the_installed_profile(self) -> None:
        status, body = self.request("GET", "/api/records/note", profile="nope")
        self.assertEqual(status, 404)
        self.assertEqual(body["error"]["code"], "not_found")

    def test_profiles_are_listed_over_http(self) -> None:
        status, body = self.request("GET", "/api/profiles")
        self.assertEqual(status, 200)
        self.assertTrue(body["available"])
        self.assertEqual([profile["name"] for profile in body["profiles"]], ["pantler", "garden"])


if __name__ == "__main__":
    unittest.main()
