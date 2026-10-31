"""Tests for previews — the serving door and its jail.

Two halves, matching the module's own split, and for the same reason `test_attachments.py`
gives: the rules (the disposition, the jail, the range) are tested directly because that is
where they live, and the HTTP layer is tested over a real socket because a content type, a 206
and a 416 are exactly the things a direct call cannot prove.

The security cases are the point of this file. Every one of them is a way a served file could
stop being data and start being a page, or a path could stop being a name and start being a
door — so each is a named test rather than a comment.

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

from attachments import AttachmentStore  # noqa: E402
from previews import (  # noqa: E402
    MAX_PREVIEW_BYTES,
    FileRoots,
    PreviewError,
    describe_file,
    disposition_of,
    kind_of,
    parse_range,
)
from pantler_server import Bff, Handler  # noqa: E402

PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753"
    "de0000000c4944415408d763f8cfc000000301010018dd8db00000000049454e44ae426082"
)
PDF = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< >>\n%%EOF\n"
HTML = b"<html><body><script>alert(1)</script></body></html>"
SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'


class DispositionTest(unittest.TestCase):
    """One function decides what may be inline. Nothing else may decide it differently."""

    def test_a_raster_image_is_served_as_itself_and_inline(self) -> None:
        self.assertEqual(disposition_of("image/png", "barn.png", PNG), ("image/png", "inline"))
        self.assertEqual(disposition_of("image/jpeg", "barn.jpg"), ("image/jpeg", "inline"))

    def test_a_pdf_is_inline_only_when_its_bytes_agree(self) -> None:
        self.assertEqual(
            disposition_of("application/pdf", "docket.pdf", PDF),
            ("application/pdf", "inline"),
        )
        # Named .pdf, sniffed as one, and not one: a download, because the type we would hand a
        # browser's PDF viewer is a claim about the bytes.
        self.assertEqual(
            disposition_of("application/pdf", "docket.pdf", b"not really a pdf"),
            ("application/octet-stream", "attachment"),
        )

    def test_a_page_type_is_never_inline(self) -> None:
        for mime, name, head in (
            ("text/html", "evil.html", HTML),
            ("application/xhtml+xml", "evil.xhtml", HTML),
            ("image/svg+xml", "evil.svg", SVG),
        ):
            content_type, disposition = disposition_of(mime, name, head)
            self.assertEqual(content_type, "application/octet-stream", name)
            self.assertEqual(disposition, "attachment", name)

    def test_text_is_a_download_because_the_sheet_fetches_it(self) -> None:
        # Deliberate: the inline set is two families, and text is drawn by the sheet from bytes
        # it fetched, which gives a renderer we control rather than the browser's text view.
        self.assertEqual(
            disposition_of("text/csv", "order.csv", b"customer,qty\n"),
            ("application/octet-stream", "attachment"),
        )
        self.assertEqual(
            disposition_of("text/markdown", "notes.md", b"# Notes\n"),
            ("application/octet-stream", "attachment"),
        )

    def test_sound_and_moving_pictures_play_from_the_route(self) -> None:
        # Inert in the way a raster is: a browser hands these to a decoder, never to its HTML
        # parser. They need a range to seek, which the byte route already answers.
        self.assertEqual(disposition_of("video/mp4", "clip.mp4"), ("video/mp4", "inline"))
        self.assertEqual(disposition_of("audio/mpeg", "note.mp3"), ("audio/mpeg", "inline"))
        self.assertEqual(kind_of("video/mp4", "clip.mp4"), "media")

    def test_an_unpaintable_image_is_a_download(self) -> None:
        self.assertEqual(
            disposition_of("image/tiff", "scan.tif", b"II*\x00"),
            ("application/octet-stream", "attachment"),
        )

    def test_kinds_route_the_shell(self) -> None:
        self.assertEqual(kind_of("image/png", "barn.png"), "image")
        self.assertEqual(kind_of("application/pdf", "docket.pdf"), "pdf")
        self.assertEqual(kind_of("text/csv", "order.csv"), "text")
        self.assertEqual(kind_of("text/html", "evil.html"), "other")
        self.assertEqual(kind_of("image/svg+xml", "evil.svg"), "other")
        self.assertEqual(
            kind_of(
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "quote.docx",
            ),
            "other",
        )


class RangeTest(unittest.TestCase):
    def test_no_header_is_the_whole_file(self) -> None:
        self.assertIsNone(parse_range(None, 100))
        self.assertIsNone(parse_range("", 100))

    def test_a_bounded_range(self) -> None:
        chosen = parse_range("bytes=10-19", 100)
        assert chosen is not None
        self.assertEqual((chosen.start, chosen.end, chosen.length), (10, 19, 10))
        self.assertEqual(chosen.header(100), "bytes 10-19/100")

    def test_an_open_ended_range(self) -> None:
        chosen = parse_range("bytes=90-", 100)
        assert chosen is not None
        self.assertEqual((chosen.start, chosen.end), (90, 99))

    def test_a_suffix_range_is_the_last_n_bytes(self) -> None:
        chosen = parse_range("bytes=-10", 100)
        assert chosen is not None
        self.assertEqual((chosen.start, chosen.end), (90, 99))
        # A suffix longer than the file is the whole file, not an error.
        chosen = parse_range("bytes=-500", 100)
        assert chosen is not None
        self.assertEqual((chosen.start, chosen.end), (0, 99))

    def test_an_end_past_the_file_is_clamped(self) -> None:
        chosen = parse_range("bytes=95-9999", 100)
        assert chosen is not None
        self.assertEqual((chosen.start, chosen.end), (95, 99))

    def test_a_malformed_or_multi_range_is_ignored(self) -> None:
        # The RFC lets a server ignore Range entirely, and ignoring is the kinder failure: a
        # client that asked badly still gets its file.
        for header in ("bytes=abc", "bytes=1-2-3", "items=0-1", "bytes=0-1,5-6", "bytes=-"):
            self.assertIsNone(parse_range(header, 100), header)

    def test_an_unsatisfiable_range_is_a_416(self) -> None:
        for header in ("bytes=100-", "bytes=200-300", "bytes=-0"):
            with self.assertRaises(PreviewError) as caught:
                parse_range(header, 100)
            self.assertEqual(caught.exception.status, 416, header)

    def test_an_empty_file_has_no_range(self) -> None:
        with self.assertRaises(PreviewError) as caught:
            parse_range("bytes=0-10", 0)
        self.assertEqual(caught.exception.status, 416)


class JailTest(unittest.TestCase):
    """The one door from a caller's string to a path on disk."""

    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.base = Path(self._dir.name)
        self.root = self.base / "workspace"
        self.root.mkdir()
        self.outside = self.base / "outside"
        self.outside.mkdir()
        (self.outside / "secret.txt").write_text("not yours\n")
        (self.root / "notes.md").write_text("# Notes\n")
        (self.root / ".env").write_text("API_SERVER_KEY=hunter2\n")
        (self.root / ".git").mkdir()
        (self.root / ".git" / "config").write_text("[core]\n")
        (self.root / "sub").mkdir()
        (self.root / "escape").symlink_to(self.outside / "secret.txt")
        self.roots = FileRoots.build([self.root])

    def tearDown(self) -> None:
        self._dir.cleanup()

    def refusal(self, raw: str) -> PreviewError:
        with self.assertRaises(PreviewError) as caught:
            self.roots.resolve(raw)
        return caught.exception

    def test_no_root_configured_refuses_with_a_sentence(self) -> None:
        with self.assertRaises(PreviewError) as caught:
            FileRoots().resolve(str(self.root / "notes.md"))
        exc = caught.exception
        self.assertEqual(exc.status, 403)
        self.assertEqual(exc.code, "no_roots")
        self.assertIn("--files-root", exc.message)

    def test_a_file_inside_the_root_is_served(self) -> None:
        self.assertEqual(self.roots.resolve(str(self.root / "notes.md")), (self.root / "notes.md").resolve())

    def test_a_relative_path_is_refused(self) -> None:
        # There is no cwd in a transcript, so resolving one would be a guess. the file-preview design
        # §4 D8.
        exc = self.refusal("notes.md")
        self.assertEqual((exc.status, exc.code), (400, "relative_path"))

    def test_a_parent_segment_is_refused(self) -> None:
        exc = self.refusal(str(self.root / ".." / "outside" / "secret.txt"))
        self.assertEqual((exc.status, exc.code), (400, "bad_path"))

    def test_a_file_outside_every_root_is_refused(self) -> None:
        exc = self.refusal(str(self.outside / "secret.txt"))
        self.assertEqual((exc.status, exc.code), (403, "outside_roots"))

    def test_a_symlink_out_of_a_root_is_refused(self) -> None:
        # Containment is checked on the resolved path, so this is caught here rather than by hope.
        exc = self.refusal(str(self.root / "escape"))
        self.assertEqual((exc.status, exc.code), (403, "outside_roots"))

    def test_a_missing_file_is_a_404(self) -> None:
        exc = self.refusal(str(self.root / "nope.md"))
        self.assertEqual((exc.status, exc.code), (404, "not_found"))

    def test_a_directory_is_not_a_file(self) -> None:
        exc = self.refusal(str(self.root / "sub"))
        self.assertEqual((exc.status, exc.code), (400, "not_a_file"))

    def test_the_engine_key_is_never_served(self) -> None:
        exc = self.refusal(str(self.root / ".env"))
        self.assertEqual((exc.status, exc.code), (403, "denied"))
        self.assertIn(".env", exc.message)

    def test_dot_git_is_never_served(self) -> None:
        exc = self.refusal(str(self.root / ".git" / "config"))
        self.assertEqual((exc.status, exc.code), (403, "denied"))

    def test_a_credential_backup_is_never_served(self) -> None:
        # The exact name was denied and every spelling beside it was served: `auth.json` was
        # refused while `auth.json.bak-anon-probe` came back as a download
        # (the internal security audit A19-EX-5). A backup of a credential is a credential.
        for name in (
            "auth.json.bak-anon-probe",
            "auth.json.probe-anon-old",
            "auth.lock",
            "credentials.bak",
            "credential.json",
            "id_rsa_old",
            "id_ed25519.pub",
            "state.db-wal",
            "response_store.db",
            "records.db-shm",
        ):
            with self.subTest(name=name):
                exc = self.refusal(str(self.root / name))
                self.assertEqual((exc.status, exc.code), (403, "denied"), name)

    def test_the_engine_home_is_never_walked_into(self) -> None:
        # Transcripts, request dumps, logs and memories live under here, and the default read
        # root is the checkout that contains them.
        for relative in (
            ".hermes-dev/profiles/pantler/sessions/sessions.json",
            ".hermes-dev/profiles/pantler/logs/agent.log",
            ".hermes/profiles/pantler/memories/MEMORY.md",
            ".data/attachments/web-1/abc/meta.json",
        ):
            with self.subTest(relative=relative):
                exc = self.refusal(str(self.root / relative))
                self.assertEqual((exc.status, exc.code), (403, "denied"))

    def test_the_outside_answer_does_not_say_whether_the_path_exists(self) -> None:
        # Resolving before the containment test made this an existence oracle for any path on
        # the machine: 404 and 403 were different answers, and the 400 branch echoed the
        # operating system's errno (the internal security audit A19-EX-7).
        missing = self.refusal(str(self.outside / "definitely-not-here-404"))
        present = self.refusal(str(self.outside / "secret.txt"))
        self.assertEqual((missing.status, missing.code), (403, "outside_roots"))
        self.assertEqual((present.status, present.code), (403, "outside_roots"))

    def test_a_missing_file_inside_a_root_is_still_a_404(self) -> None:
        # Inside a declared root there is nothing to hide: the roots are the operator's own.
        exc = self.refusal(str(self.root / "not-here.md"))
        self.assertEqual((exc.status, exc.code), (404, "not_found"))

    def test_a_null_byte_is_not_a_path(self) -> None:
        exc = self.refusal(str(self.root) + "/notes.md\x00.png")
        self.assertEqual((exc.status, exc.code), (400, "bad_path"))


class DescribeTest(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.root = Path(self._dir.name)

    def tearDown(self) -> None:
        self._dir.cleanup()

    def write(self, name: str, data: bytes) -> Path:
        path = self.root / name
        path.write_bytes(data)
        return path

    def test_a_pdf_promises_a_frame_and_a_csv_a_text_view(self) -> None:
        pdf = describe_file(self.write("docket.pdf", PDF))
        self.assertEqual((pdf.kind, pdf.render, pdf.inline), ("pdf", "pdf", True))
        self.assertEqual(pdf.content_type, "application/pdf")

        csv = describe_file(self.write("order.csv", b"customer,qty\n"))
        self.assertEqual((csv.kind, csv.render, csv.inline), ("text", "text", False))
        self.assertEqual(csv.mime, "text/csv")
        # Text is a `text` render and not an inline one: the sheet fetches the bytes.
        self.assertEqual(csv.content_type, "application/octet-stream")

    def test_an_image_promises_a_picture_and_a_tiff_does_not(self) -> None:
        png = describe_file(self.write("barn.png", PNG))
        self.assertEqual((png.render, png.inline), ("image", True))
        tiff = describe_file(self.write("scan.tif", b"II*\x00" + b"\x00" * 32))
        self.assertEqual((tiff.kind, tiff.render, tiff.inline), ("image", "download", False))

    def test_an_html_file_is_download_only(self) -> None:
        page = describe_file(self.write("report.html", HTML))
        self.assertEqual((page.kind, page.render, page.inline), ("other", "download", False))

    def test_a_video_promises_a_player_and_a_docx_does_not(self) -> None:
        video = describe_file(self.write("clip.mp4", b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 32))
        self.assertEqual((video.kind, video.render, video.inline), ("media", "media", True))
        self.assertEqual(video.content_type, "video/mp4")
        doc = describe_file(self.write("quote.docx", b"PK\x03\x04" + b"\x00" * 32))
        self.assertEqual((doc.kind, doc.render, doc.inline), ("other", "download", False))

    def test_a_big_file_is_refused_with_a_sentence_rather_than_read(self) -> None:
        path = self.root / "huge.bin"
        with path.open("wb") as handle:
            handle.truncate(MAX_PREVIEW_BYTES + 1)
        with self.assertRaises(PreviewError) as caught:
            describe_file(path)
        self.assertEqual(caught.exception.status, 413)
        self.assertIn("larger than", caught.exception.message)


class PreviewHttpTest(unittest.TestCase):
    """The thin layer a direct call cannot prove: headers, statuses, and the bytes of a range."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._dir = tempfile.TemporaryDirectory()
        root = Path(cls._dir.name)
        cls.root = root / "workspace"
        cls.root.mkdir()
        (cls.root / "docket.pdf").write_bytes(PDF)
        (cls.root / "order.csv").write_bytes(b"customer,qty\nBellview,12\n")
        (cls.root / "barn.png").write_bytes(PNG)
        (cls.root / "evil.html").write_bytes(HTML)

        bff = Bff(
            Store(root / "records.db"),
            PackRegistry([]),
            None,
            AttachmentStore(root / "attachments"),
            FileRoots.build([cls.root]),
        )
        cls.bff = bff

        class QuietHandler(Handler):
            def log_message(self, *args):
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

    def url(self, route: str, name: str) -> str:
        """`/api/files/<route>?path=<absolute path>` — the one shape both routes take."""
        return f"/api/files/{route}?path=" + quote(str(self.root / name))

    def upload(self, session: str, name: str, data: bytes) -> dict:
        status, body, _ = self.request(
            "POST",
            "/api/attachments",
            data,
            {
                "Content-Type": "application/octet-stream",
                "X-Attachment-Session": session,
                "X-Attachment-Name": quote(name),
            },
        )
        self.assertEqual(status, 201, body)
        return json.loads(body)

    def test_meta_says_what_a_path_is_without_moving_its_bytes(self) -> None:
        status, body, headers = self.request("GET", self.url("meta", "docket.pdf"))
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertEqual(payload["render"], "pdf")
        self.assertEqual(payload["mime"], "application/pdf")
        self.assertEqual(payload["name"], "docket.pdf")
        self.assertTrue(payload["inline"])
        self.assertEqual(payload["size"], len(PDF))
        self.assertIn("application/json", headers["Content-Type"])

    def test_a_pdf_is_served_inline_and_a_page_is_not(self) -> None:
        status, body, headers = self.request("GET", self.url("raw", "docket.pdf"))
        self.assertEqual(status, 200)
        self.assertEqual(body, PDF)
        self.assertEqual(headers["Content-Type"], "application/pdf")
        self.assertTrue(headers["Content-Disposition"].startswith("inline"))
        self.assertEqual(headers["Accept-Ranges"], "bytes")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")

        status, _, headers = self.request("GET", self.url("raw", "evil.html"))
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "application/octet-stream")
        self.assertTrue(headers["Content-Disposition"].startswith("attachment"))

    def test_a_range_is_206_with_the_slice_and_its_bookkeeping(self) -> None:
        status, body, headers = self.request(
            "GET",
            self.url("raw", "docket.pdf"),
            headers={"Range": "bytes=0-9"},
        )
        self.assertEqual(status, 206)
        self.assertEqual(body, PDF[:10])
        self.assertEqual(headers["Content-Range"], f"bytes 0-9/{len(PDF)}")
        self.assertEqual(headers["Content-Length"], "10")

    def test_an_unsatisfiable_range_is_416_with_the_size(self) -> None:
        status, _, headers = self.request(
            "GET",
            self.url("raw", "order.csv"),
            headers={"Range": "bytes=99999-"},
        )
        self.assertEqual(status, 416)
        self.assertEqual(headers["Content-Range"], f"bytes */{len(b'customer,qty\nBellview,12\n')}")

    def test_a_path_outside_the_roots_is_refused_with_a_sentence(self) -> None:
        status, body, _ = self.request("GET", "/api/files/raw?path=" + quote("/etc/hostname"))
        self.assertEqual(status, 403)
        self.assertEqual(json.loads(body)["error"]["code"], "outside_roots")
        self.assertIn("outside the directories", json.loads(body)["error"]["message"])

    def test_a_denied_name_is_refused_over_the_wire_too(self) -> None:
        (self.root / ".env").write_text("API_SERVER_KEY=hunter2\n")
        status, body, _ = self.request("GET", self.url("meta", ".env"))
        self.assertEqual(status, 403)
        self.assertEqual(json.loads(body)["error"]["code"], "denied")

    def test_an_uploaded_pdf_previews_and_an_uploaded_page_does_not(self) -> None:
        """One disposition function, two doors: this is the pair that proves it."""
        pdf = self.upload("web-http", "scan.pdf", PDF)
        status, body, headers = self.request("GET", f"/api/attachments/{pdf['id']}/raw")
        self.assertEqual(status, 200)
        self.assertEqual(body, PDF)
        self.assertEqual(headers["Content-Type"], "application/pdf")
        self.assertTrue(headers["Content-Disposition"].startswith("inline"))

        page = self.upload("web-http", "evil.html", HTML)
        _, _, headers = self.request("GET", f"/api/attachments/{page['id']}/raw")
        self.assertEqual(headers["Content-Type"], "application/octet-stream")
        self.assertTrue(headers["Content-Disposition"].startswith("attachment"))

    def test_attachment_meta_answers_the_same_shape_as_a_path(self) -> None:
        pdf = self.upload("web-http", "meta.pdf", PDF)
        status, body, _ = self.request("GET", f"/api/attachments/{pdf['id']}/meta")
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertEqual(payload["render"], "pdf")
        self.assertTrue(payload["inline"])
        self.assertEqual(payload["name"], "meta.pdf")

        # The same file reached by path, because an attachment lives inside a root.
        status, by_path, _ = self.request("GET", self.url("meta", "docket.pdf"))
        self.assertEqual(status, 200)
        self.assertEqual(set(json.loads(by_path)), set(payload))

        page = self.upload("web-http", "meta.html", HTML)
        _, body, _ = self.request("GET", f"/api/attachments/{page['id']}/meta")
        self.assertEqual(json.loads(body)["render"], "download")

    def test_an_attachment_range_is_206_too(self) -> None:
        pdf = self.upload("web-http", "range.pdf", PDF)
        status, body, headers = self.request(
            "GET", f"/api/attachments/{pdf['id']}/raw", headers={"Range": "bytes=5-14"}
        )
        self.assertEqual(status, 206)
        self.assertEqual(body, PDF[5:15])
        self.assertEqual(headers["Content-Range"], f"bytes 5-14/{len(PDF)}")

    def test_a_snapshot_refuses_a_bad_scheme_and_a_private_host_without_fetching(self) -> None:
        for url, code in (("ftp://example.com/x", "bad_url"), ("http://127.0.0.1:9/x", "fetch_failed")):
            status, body, _ = self.request(
                "POST",
                "/api/urls/snapshot",
                json.dumps({"url": url}).encode(),
                {"Content-Type": "application/json"},
            )
            self.assertGreaterEqual(status, 400, url)
            # A refusal, never a hang and never a request to the operator's own network.
            self.assertIn("error", json.loads(body))

    def test_a_snapshot_needs_a_url(self) -> None:
        status, body, _ = self.request(
            "POST", "/api/urls/snapshot", b"{}", {"Content-Type": "application/json"}
        )
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(body)["error"]["code"], "bad_body")


if __name__ == "__main__":
    unittest.main()
