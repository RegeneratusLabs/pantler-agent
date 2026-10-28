"""Tests for attachments.

Two halves, and the split is deliberate. The store and the composer are tested directly,
because that is where the rules live — caps, name sanitising, what gets inlined, the exact
frozen format the shell parses. The HTTP layer is tested over a real socket on an ephemeral
port, because raw uploads, binary replies and content types are exactly the things a
direct call cannot prove.

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
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "core" / "src"))
sys.path.insert(0, str(REPO_ROOT / "app" / "server"))

from pantler_core import PackRegistry, Store  # noqa: E402

from attachments import (  # noqa: E402
    AttachmentError,
    AttachmentStore,
    FetchedUrl,
    classify,
    compose_input,
    decode_text,
    human_size,
    html_to_text,
    sanitize_name,
    sanitize_relpath,
    sniff_mime,
)
from pantler_server import Bff, Handler  # noqa: E402

# A one-pixel PNG, so an image assertion is about bytes rather than about a mock.
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753"
    "de0000000c4944415408d763f8cfc000000301010018dd8db00000000049454e44ae426082"
)


class StoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.root = Path(self._dir.name) / "attachments"
        self.store = AttachmentStore(self.root)

    def tearDown(self) -> None:
        self._dir.cleanup()

    def test_a_file_is_stored_under_its_session_and_readable_back(self) -> None:
        record = self.store.save_bytes("web-1", "beans.csv", b"a,b\n1,2\n")
        self.assertEqual(record.kind, "text")
        self.assertEqual(record.mime, "text/csv")
        self.assertEqual(Path(record.root).read_bytes(), b"a,b\n1,2\n")
        self.assertEqual(Path(record.root).stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.store.get(record.id).name, "beans.csv")

    def test_a_name_is_never_a_path(self) -> None:
        record = self.store.save_bytes("web-1", "../../etc/passwd", b"nope")
        self.assertEqual(record.name, "passwd")
        self.assertIn(str(self.root.resolve()), str(Path(record.root).resolve()))
        self.assertEqual(sanitize_name(".."), "file")
        self.assertEqual(sanitize_name("  q1/beans.csv  "), "beans.csv")
        self.assertEqual(sanitize_relpath("../../etc/passwd"), "etc/passwd")

    def test_an_oversize_file_is_refused_with_the_limit_in_the_message(self) -> None:
        small = AttachmentStore(self.root, max_file_bytes=10)
        with self.assertRaises(AttachmentError) as caught:
            small.save_bytes("web-1", "big.bin", b"x" * 11)
        self.assertEqual(caught.exception.status, 413)
        self.assertIn("10 B", caught.exception.message)

    def test_an_empty_file_is_refused(self) -> None:
        with self.assertRaises(AttachmentError):
            self.store.save_bytes("web-1", "empty.txt", b"")

    def test_a_session_id_is_a_directory_name_and_is_never_trusted(self) -> None:
        record = self.store.save_bytes("../../evil", "x.txt", b"hi")
        self.assertEqual(record.session, "evil")
        self.assertTrue(str(Path(record.root)).startswith(str(self.root.resolve())))

    def test_magic_bytes_beat_a_wrong_content_type(self) -> None:
        record = self.store.save_bytes(
            "web-1", "photo.dat", PNG, mime_hint="application/octet-stream"
        )
        self.assertEqual(record.mime, "image/png")
        self.assertEqual(record.kind, "image")

    def test_a_browser_guessing_excel_for_a_csv_does_not_hide_the_text(self) -> None:
        record = self.store.save_bytes(
            "web-1", "orders.csv", b"a,b\n", mime_hint="application/vnd.ms-excel"
        )
        self.assertEqual(record.kind, "text")

    def test_a_folder_is_one_record_that_grows(self) -> None:
        first = self.store.save_bytes(
            "web-1", "beans.csv", b"a\n", rel_path="orders/q1/beans.csv", folder_token="tok"
        )
        second = self.store.save_bytes(
            "web-1", "eggs.csv", b"b\n", rel_path="orders/q1/eggs.csv", folder_token="tok"
        )
        self.assertEqual(first.id, second.id)
        self.assertEqual(second.kind, "folder")
        self.assertEqual(second.name, "orders")
        self.assertEqual([f["rel_path"] for f in second.files], ["q1/beans.csv", "q1/eggs.csv"])
        self.assertEqual(Path(second.root).joinpath("q1/eggs.csv").read_bytes(), b"b\n")

    def test_a_folder_stops_at_its_file_cap(self) -> None:
        import attachments as module

        store = AttachmentStore(self.root)
        original = module.MAX_FOLDER_FILES
        module.MAX_FOLDER_FILES = 2
        try:
            for index in range(2):
                store.save_bytes(
                    "web-1", f"{index}.csv", b"x", rel_path=f"many/{index}.csv", folder_token="t"
                )
            with self.assertRaises(AttachmentError) as caught:
                store.save_bytes(
                    "web-1", "3.csv", b"x", rel_path="many/3.csv", folder_token="t"
                )
            self.assertEqual(caught.exception.code, "too_many_files")
        finally:
            module.MAX_FOLDER_FILES = original

    def test_listing_is_per_session_and_ordered(self) -> None:
        a = self.store.save_bytes("web-1", "a.txt", b"a")
        b = self.store.save_bytes("web-1", "b.txt", b"b")
        self.store.save_bytes("web-2", "c.txt", b"c")
        self.assertEqual([r.id for r in self.store.list("web-1")], [a.id, b.id])
        self.assertEqual(len(self.store.list("web-2")), 1)

    def test_delete_removes_the_bytes_and_is_idempotent(self) -> None:
        record = self.store.save_bytes("web-1", "a.txt", b"a")
        self.assertTrue(self.store.delete(record.id))
        self.assertFalse(self.store.delete(record.id))
        self.assertFalse(Path(record.root).exists())
        with self.assertRaises(AttachmentError) as caught:
            self.store.get(record.id)
        self.assertEqual(caught.exception.status, 404)

    def test_an_unknown_or_malformed_id_is_an_error_not_a_traversal(self) -> None:
        with self.assertRaises(AttachmentError):
            self.store.get("../../etc/passwd")
        with self.assertRaises(AttachmentError):
            self.store.get("deadbeefcafe")

    def test_a_record_pointing_outside_the_store_is_refused_rather_than_removed(self) -> None:
        # `meta.json` is ours, but a truncated or edited one whose `root` is empty resolves its
        # parent to `.` — and `rmtree('.')` is the working directory
        # (the internal audit BFF-14).
        record = self.store.save_bytes("web-1", "a.txt", b"a")
        meta = Path(record.root).parent / "meta.json"
        payload = json.loads(meta.read_text())
        payload["root"] = ""
        meta.write_text(json.dumps(payload))

        with self.assertRaises(AttachmentError) as caught:
            self.store.delete(record.id)
        self.assertEqual(caught.exception.code, "unusable_record")
        self.assertTrue(Path(record.root).exists(), "the file was removed anyway")

    def test_the_directories_are_closed_to_other_accounts(self) -> None:
        # The files were always 0600; the directories were created with the process umask, so
        # every file name on them was readable even when the bytes were not.
        record = self.store.save_bytes("web-1", "a.txt", b"a")
        directory = Path(record.root).parent
        session = directory.parent
        for path in (directory, session):
            with self.subTest(path=path.name):
                self.assertEqual(path.stat().st_mode & 0o777, 0o700)

    def test_a_url_is_fetched_once_and_kept_as_text(self) -> None:
        store = AttachmentStore(
            self.root,
            url_fetcher=lambda url: FetchedUrl(
                url=url, body=b"Bellview price list", mime="text/plain", title="Price list"
            ),
        )
        record = store.save_url("web-1", "https://example.com/prices")
        self.assertEqual(record.kind, "url")
        self.assertEqual(record.name, "Price list")
        self.assertEqual(record.source_url, "https://example.com/prices")
        self.assertEqual(Path(record.root).read_bytes(), b"Bellview price list")

    def test_sweep_removes_only_old_attachments(self) -> None:
        import os
        import time

        old = self.store.save_bytes("web-1", "old.txt", b"old")
        fresh = self.store.save_bytes("web-1", "fresh.txt", b"fresh")
        aged = time.time() - 40 * 86400
        os.utime(Path(old.root).parent, (aged, aged))
        self.assertEqual(self.store.sweep(30), 1)
        self.assertFalse(Path(old.root).exists())
        self.assertTrue(Path(fresh.root).exists())
        self.assertEqual(self.store.sweep(0), 0)


class ComposeTest(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.store = AttachmentStore(Path(self._dir.name) / "attachments")

    def tearDown(self) -> None:
        self._dir.cleanup()

    def test_text_is_inlined_and_the_path_is_always_named(self) -> None:
        record = self.store.save_bytes("web-1", "orders.csv", b"customer,qty\nBellview,12\n")
        composed = compose_input("Invoice these", [record])
        self.assertTrue(composed.startswith("Invoice these"))
        self.assertIn("Attached files (1):", composed)
        self.assertIn("1. orders.csv — text/csv, 25 B", composed)
        self.assertIn(f"   Path: {record.root}", composed)
        self.assertIn("--- orders.csv ---", composed)
        self.assertIn("Bellview,12", composed)

    def test_an_image_is_named_and_never_inlined(self) -> None:
        record = self.store.save_bytes("web-1", "barn.png", PNG)
        composed = compose_input("What is this?", [record])
        self.assertIn("1. barn.png — image/png", composed)
        self.assertIn("vision_analyze", composed)
        self.assertNotIn("--- barn.png ---", composed)

    def test_a_folder_is_listed_as_a_folder_with_one_path(self) -> None:
        record = self.store.save_bytes(
            "web-1", "beans.csv", b"a\n", rel_path="orders/beans.csv", folder_token="t"
        )
        composed = compose_input("", [record])
        self.assertIn("1. orders — folder, 1 file, 2 B", composed)
        self.assertIn(f"   Path: {record.root}", composed)

    def test_a_large_text_file_is_named_but_not_inlined(self) -> None:
        record = self.store.save_bytes("web-1", "long.txt", b"x" * (40 * 1024))
        composed = compose_input("", [record])
        self.assertIn("not inlined", composed)
        self.assertNotIn("x" * 200, composed)

    def test_binary_masquerading_as_text_is_not_inlined(self) -> None:
        record = self.store.save_bytes("web-1", "notes.txt", bytes(range(256)) * 8)
        self.assertIsNone(decode_text(Path(record.root).read_bytes()))
        self.assertIn("not inlined", compose_input("", [record]))

    def test_no_attachments_leaves_the_text_alone(self) -> None:
        self.assertEqual(compose_input("  hello  ", []), "hello")

    def test_an_attachment_only_turn_is_still_a_turn(self) -> None:
        record = self.store.save_bytes("web-1", "a.txt", b"a")
        composed = compose_input("", [record])
        self.assertTrue(composed.startswith("Attached files (1):"))

    def test_the_python_writer_and_the_shared_parser_agree_on_the_shape(self) -> None:
        """The format is frozen (the attachment design §4): a change here breaks the shell."""
        record = self.store.save_bytes("web-1", "a.txt", b"a\n")
        lines = compose_input("hi", [record]).split("\n")
        self.assertEqual(lines[0], "hi")
        self.assertEqual(lines[1], "")
        self.assertEqual(lines[2], "Attached files (1):")
        self.assertRegex(lines[3], r"^1\. a\.txt — .+$")
        self.assertTrue(lines[4].startswith("   Path: "))


class FormatTest(unittest.TestCase):
    def test_human_size_reads_like_a_person_wrote_it(self) -> None:
        self.assertEqual(human_size(0), "0 B")
        self.assertEqual(human_size(999), "999 B")
        self.assertEqual(human_size(1024), "1.0 KB")
        self.assertEqual(human_size(1024 * 1024), "1.0 MB")
        self.assertEqual(human_size(1024 * 1024 * 150), "150 MB")

    def test_classification_is_by_mime_and_falls_back_to_the_extension(self) -> None:
        self.assertEqual(classify("image/png", "x.png"), "image")
        self.assertEqual(classify("text/csv", "x.csv"), "text")
        self.assertEqual(classify("application/pdf", "x.pdf"), "document")
        self.assertEqual(classify("application/zip", "x.zip"), "archive")
        self.assertEqual(classify("application/octet-stream", "notes.md"), "text")
        self.assertEqual(classify("application/octet-stream", "thing.bin"), "other")

    def test_an_office_document_is_not_mistaken_for_a_zip(self) -> None:
        docx = sniff_mime(b"PK\x03\x04rest", "report.docx", "")
        self.assertTrue(docx.endswith("wordprocessingml.document"))

    def test_html_becomes_text_and_a_title(self) -> None:
        text, title = html_to_text(
            b"<html><head><title>Prices</title><style>p{}</style></head>"
            b"<body><h1>List</h1><p>Beans &amp; eggs</p><script>x()</script></body></html>"
        )
        self.assertEqual(title, "Prices")
        self.assertIn("Beans & eggs", text)
        self.assertNotIn("x()", text)
        self.assertNotIn("p{}", text)


class AttachmentHttpTest(unittest.TestCase):
    """The thin layer that a direct call cannot prove: raw bytes in, bytes out."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._dir = tempfile.TemporaryDirectory()
        root = Path(cls._dir.name)
        bff = Bff(
            Store(root / "records.db"),
            PackRegistry([]),
            None,
            AttachmentStore(root / "attachments"),
        )
        cls.bff = bff

        class QuietHandler(Handler):
            def log_message(self, *args):  # a passing suite should not print a request log
                pass

        handler = type("BoundHandler", (QuietHandler,), {"bff": bff, "static_root": None})
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

    def request(
        self, method: str, path: str, body: bytes | None = None, headers: dict[str, str] | None = None
    ) -> tuple[int, bytes, dict[str, str]]:
        merged = dict(headers or {})
        if method not in ("GET", "HEAD", "OPTIONS") and not (
            {"Origin", "Referer", "Sec-Fetch-Site", "X-Pantler-Token"} & set(merged)
        ):
            # What a browser sends for this app's own writes (the internal security audit
            # A19-EX-2). A test that wants the refusal passes its own headers.
            merged["Origin"] = f"http://127.0.0.1:{self.port}"
            merged["Sec-Fetch-Site"] = "same-origin"
        connection = HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            connection.request(method, path, body=body, headers=merged)
            response = connection.getresponse()
            payload = response.read()
            return response.status, payload, dict(response.getheaders())
        finally:
            connection.close()

    def upload(self, session: str, name: str, data: bytes, **extra: str) -> dict:
        headers = {
            "Content-Type": extra.pop("content_type", "application/octet-stream"),
            "X-Attachment-Session": session,
            "X-Attachment-Name": quote(name),
        }
        for key, value in extra.items():
            headers["X-Attachment-" + key.replace("_", "-").title()] = quote(value)
        status, body, _ = self.request("POST", "/api/attachments", data, headers)
        self.assertEqual(status, 201, body)
        return json.loads(body)

    def test_a_round_trip_upload_compose_and_delete(self) -> None:
        record = self.upload("web-http", "order.csv", b"customer,qty\nBellview,12\n")
        self.assertEqual(record["kind"], "text")
        self.assertEqual(record["size"], 25)

        status, body, _ = self.request(
            "POST",
            "/api/attachments/context",
            json.dumps(
                {"session": "web-http", "text": "Invoice these", "ids": [record["id"]]}
            ).encode(),
            {"Content-Type": "application/json"},
        )
        self.assertEqual(status, 200)
        composed = json.loads(body)["input"]
        self.assertIn("Invoice these", composed)
        self.assertIn("Attached files (1):", composed)
        self.assertIn("Bellview,12", composed)

        status, _, _ = self.request("DELETE", f"/api/attachments/{record['id']}")
        self.assertEqual(status, 204)
        status, _, _ = self.request("GET", f"/api/attachments/{record['id']}")
        self.assertEqual(status, 404)

    def test_an_image_is_served_inline_and_a_document_is_not(self) -> None:
        image = self.upload("web-http", "barn.png", PNG)
        status, body, headers = self.request("GET", f"/api/attachments/{image['id']}/raw")
        self.assertEqual(status, 200)
        self.assertEqual(body, PNG)
        self.assertEqual(headers["Content-Type"], "image/png")
        self.assertTrue(headers["Content-Disposition"].startswith("inline"))
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")

        csv = self.upload("web-http", "order.csv", b"a,b\n")
        status, _, headers = self.request("GET", f"/api/attachments/{csv['id']}/raw")
        self.assertEqual(status, 200)
        # Never a page on our own origin, whatever was uploaded.
        self.assertEqual(headers["Content-Type"], "application/octet-stream")
        self.assertTrue(headers["Content-Disposition"].startswith("attachment"))

    def test_an_uploaded_html_file_cannot_become_a_page(self) -> None:
        record = self.upload("web-http", "evil.html", b"<script>alert(1)</script>")
        _, _, headers = self.request("GET", f"/api/attachments/{record['id']}/raw")
        self.assertEqual(headers["Content-Type"], "application/octet-stream")
        self.assertTrue(headers["Content-Disposition"].startswith("attachment"))

    def test_a_non_ascii_name_survives_the_header(self) -> None:
        record = self.upload("web-http", "café order €.csv", b"a,b\n")
        self.assertEqual(record["name"], "café order €.csv")
        _, _, headers = self.request("GET", f"/api/attachments/{record['id']}/raw")
        self.assertIn("filename*=UTF-8''", headers["Content-Disposition"])

    def test_an_oversize_body_is_refused_before_it_is_read(self) -> None:
        status, body, _ = self.request(
            "POST",
            "/api/attachments",
            b"x" * 32,
            {
                "Content-Type": "application/octet-stream",
                "Content-Length": str(200 * 1024 * 1024),
                "X-Attachment-Session": "web-http",
                "X-Attachment-Name": "big.bin",
            },
        )
        self.assertEqual(status, 413, body)

    def test_a_missing_name_is_a_400_rather_than_a_file_called_file(self) -> None:
        status, _, _ = self.request(
            "POST",
            "/api/attachments",
            b"x",
            {"Content-Type": "text/plain", "X-Attachment-Session": "web-http"},
        )
        self.assertEqual(status, 400)

    def test_a_folder_upload_arrives_as_one_record(self) -> None:
        first = self.upload(
            "web-http", "beans.csv", b"a\n", relpath="orders/q1/beans.csv", folder="tok-http"
        )
        second = self.upload(
            "web-http", "eggs.csv", b"b\n", relpath="orders/q1/eggs.csv", folder="tok-http"
        )
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(second["kind"], "folder")
        self.assertEqual(second["file_count"], 2)

        status, body, _ = self.request("GET", "/api/attachments?session=web-http")
        self.assertEqual(status, 200)
        names = {record["name"] for record in json.loads(body)["data"]}
        self.assertIn("orders", names)

    def test_another_sessions_attachment_cannot_be_attached_to_this_turn(self) -> None:
        record = self.upload("web-other", "secret.csv", b"a,b\n")
        status, body, _ = self.request(
            "POST",
            "/api/attachments/context",
            json.dumps({"session": "web-http", "text": "hi", "ids": [record["id"]]}).encode(),
            {"Content-Type": "application/json"},
        )
        self.assertEqual(status, 404, body)

    def test_the_url_route_refuses_a_private_address(self) -> None:
        status, body, _ = self.request(
            "POST",
            "/api/attachments/url",
            json.dumps({"session": "web-http", "url": "http://127.0.0.1:8650/api/health"}).encode(),
            {"Content-Type": "application/json"},
        )
        self.assertEqual(status, 400, body)
        self.assertEqual(json.loads(body)["error"]["code"], "private_host")

    def test_the_url_route_refuses_a_non_http_scheme(self) -> None:
        status, body, _ = self.request(
            "POST",
            "/api/attachments/url",
            json.dumps({"session": "web-http", "url": "file:///etc/passwd"}).encode(),
            {"Content-Type": "application/json"},
        )
        self.assertEqual(status, 400, body)
        self.assertEqual(json.loads(body)["error"]["code"], "bad_url")


class FetchDeadlineTest(unittest.TestCase):
    """A page that drips a byte at a time must not hold a request open for ever.

    `urlopen(timeout=…)` bounds each socket operation, not the fetch, so the loop enforces a
    deadline of its own (the internal audit BFF-14). Nothing here touches the network:
    the opener, the host check and the clock are all replaced.
    """

    def test_a_dripping_page_hits_the_deadline(self) -> None:
        import attachments
        from email.message import Message

        headers = Message()
        headers["Content-Type"] = "text/plain"

        class Dripping:
            def __init__(self) -> None:
                self.headers = headers

            def read(self, _size: int) -> bytes:
                return b"drip"

            def geturl(self) -> str:
                return "http://example.com/"

            def __enter__(self) -> "Dripping":
                return self

            def __exit__(self, *_exc: object) -> bool:
                return False

        class Opener:
            def open(self, request, timeout=None):  # noqa: ANN001, ANN201
                return Dripping()

        ticks = iter([0.0, 0.0, 0.0, 10_000.0, 10_000.0, 10_000.0])
        original = (attachments.build_opener, attachments._refuse_private_host, attachments.time.monotonic)
        attachments.build_opener = lambda *_a, **_k: Opener()
        attachments._refuse_private_host = lambda _host, _port=None: None
        attachments.time.monotonic = lambda: next(ticks, 10_000.0)
        try:
            with self.assertRaises(AttachmentError) as caught:
                attachments.fetch_url("http://example.com/")
        finally:
            (
                attachments.build_opener,
                attachments._refuse_private_host,
                attachments.time.monotonic,
            ) = original
        self.assertEqual(caught.exception.code, "fetch_timeout")

    def test_a_read_is_bounded_by_the_deadline_not_only_the_gaps_between_reads(self) -> None:
        # `read(65536)` blocks until the buffer fills, so a page dripping a byte at a time held
        # the thread past the deadline however often the loop checked the clock
        # (the internal security audit A19-EX-9). The fix is `read1` (returns what has
        # arrived) plus a socket timeout set to whatever is left of the deadline.
        import attachments
        from email.message import Message

        headers = Message()
        headers["Content-Type"] = "text/plain"
        seen: list[float] = []

        class Socket:
            def settimeout(self, value: float) -> None:
                seen.append(value)

        class Raw:
            _sock = Socket()

        class Fp:
            raw = Raw()

        class Page:
            reads = 0

            def __init__(self) -> None:
                self.headers = headers
                self.fp = Fp()

            def read1(self, _size: int) -> bytes:
                # One short read, then the end of the body: enough to prove the path taken.
                Page.reads += 1
                return b"hello" if Page.reads == 1 else b""

            def read(self, _size: int) -> bytes:
                raise AssertionError("read() waits for the whole buffer; read1 is the fix")

            def geturl(self) -> str:
                return "http://example.com/"

            def __enter__(self) -> "Page":
                return self

            def __exit__(self, *_exc: object) -> bool:
                return False

        class Opener:
            def open(self, request, timeout=None):  # noqa: ANN001, ANN201
                return Page()

        ticks = iter([0.0, 0.0, 0.0, 0.0])
        original = (
            attachments.build_opener,
            attachments._refuse_private_host,
            attachments.time.monotonic,
        )
        attachments.build_opener = lambda *_a, **_k: Opener()
        attachments._refuse_private_host = lambda _host, _port=None: None
        attachments.time.monotonic = lambda: next(ticks, 0.0)
        try:
            fetched = attachments.fetch_url("http://example.com/")
        finally:
            (
                attachments.build_opener,
                attachments._refuse_private_host,
                attachments.time.monotonic,
            ) = original
        self.assertEqual(fetched.body, b"hello")
        self.assertTrue(seen, "the socket timeout was never set from the remaining deadline")
        self.assertTrue(all(0 < value <= 15.0 for value in seen), seen)


class PinnedFetchTest(unittest.TestCase):
    """The address that was checked is the address that is dialled.

    Resolving for the check and letting the connection resolve again is what made the
    private-host guard advisory: a name whose answers alternate got a public answer for the
    check and a loopback one for the connection
    (the internal security audit A19-EX-6). Nothing here touches the network.
    """

    PUBLIC = ("93.184.216.34", 80)
    LOOPBACK = ("127.0.0.1", 80)

    def _answers(self, addresses):
        import socket as socket_module

        family = socket_module.AF_INET6 if ":" in addresses[0][0] else socket_module.AF_INET
        return [(family, socket_module.SOCK_STREAM, 6, "", address) for address in addresses]

    def _with_resolver(self, answers):
        import attachments

        original = attachments.socket.getaddrinfo
        attachments.socket.getaddrinfo = lambda *_a, **_k: self._answers(answers)
        self.addCleanup(lambda: setattr(attachments.socket, "getaddrinfo", original))

    def test_the_validated_address_is_what_comes_back(self) -> None:
        import attachments

        self._with_resolver([self.PUBLIC])
        self.assertEqual(attachments._refuse_private_host("rebind.test", 80), self.PUBLIC)

    def test_one_private_answer_refuses_the_whole_name(self) -> None:
        # The rebinding shape: the first answer looks public and the second is loopback.
        import attachments

        self._with_resolver([self.PUBLIC, self.LOOPBACK])
        with self.assertRaises(AttachmentError) as caught:
            attachments._refuse_private_host("rebind.test", 80)
        self.assertEqual(caught.exception.code, "private_host")

    def test_the_connection_dials_the_pin_rather_than_the_name(self) -> None:
        import attachments

        seen: list[tuple[str, int]] = []
        original = attachments.socket.create_connection

        class FakeSocket:
            pass

        def record(address, *_args, **_kwargs):
            seen.append(address)
            return FakeSocket()

        attachments.socket.create_connection = record
        self.addCleanup(lambda: setattr(attachments.socket, "create_connection", original))
        pin = attachments._Pin(self.PUBLIC)
        connection = attachments._PinnedHTTPConnection("rebind.test", 80, pin=pin)
        connection.connect()
        self.assertEqual(seen, [self.PUBLIC])

    def test_a_folded_content_type_cannot_reach_the_stored_mime(self) -> None:
        # A folded header arrives with CRLF in it; the value was stored and then echoed as a
        # response header (the internal security audit A19-EX-10).
        mime = sniff_mime(b"\x00\x00\x00\x18ftypmp42", "clip.mp4", "video/mp4\r\n X-Injected: yes")
        self.assertNotIn("\r", mime)
        self.assertNotIn("\n", mime)
        self.assertNotIn("x-injected", mime)

    def test_a_record_pointing_outside_the_store_is_refused(self) -> None:
        import tempfile

        from attachments import Attachment

        with tempfile.TemporaryDirectory() as directory:
            store = AttachmentStore(Path(directory) / "attachments")
            store.root.mkdir(parents=True, exist_ok=True)
            for root in ("", "/home/you/.ssh", str(Path(directory) / "elsewhere")):
                with self.subTest(root=root):
                    record = Attachment(
                        id="0123456789ab",
                        session="web-1",
                        name="x.txt",
                        mime="text/plain",
                        size=1,
                        kind="text",
                        created_at=0.0,
                        root=root,
                    )
                    with self.assertRaises(AttachmentError) as caught:
                        store.path_of(record)
                    self.assertEqual(caught.exception.code, "unusable_record")


class NoStoreTest(unittest.TestCase):
    """A server built without an attachment store answers honestly rather than crashing."""

    def test_attachments_are_off_when_no_store_was_configured(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / "records.db")
            bff = Bff(store, PackRegistry([]))
            try:
                with self.assertRaises(Exception) as caught:
                    bff.list_attachments({"session": "web-1"})
                self.assertEqual(getattr(caught.exception, "status", None), 503)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()


class ModeRepairTest(unittest.TestCase):
    """The 0700/0600 rule has to reach what was written before the rule existed."""

    def test_an_old_store_is_repaired_at_startup(self) -> None:
        import os

        with tempfile.TemporaryDirectory() as directory:
            store = AttachmentStore(Path(directory) / "attachments")
            record = store.save_bytes("web-1", "notes.txt", b"hello")
            old = Path(record.root)
            os.chmod(old.parent, 0o775)
            os.chmod(old, 0o644)
            os.chmod(store.root, 0o775)
            repaired = store.repair_modes()
            self.assertGreaterEqual(repaired, 3)
            self.assertEqual(store.root.stat().st_mode & 0o777, 0o700)
            self.assertEqual(old.parent.stat().st_mode & 0o777, 0o700)
            self.assertEqual(old.stat().st_mode & 0o777, 0o600)
