import io
import json
import unittest
from unittest.mock import Mock, patch

from backend.server import Handler


class HttpTests(unittest.TestCase):
    def handler(self, path, body=b"", length=None):
        handler = Handler.__new__(Handler)
        handler.path = path
        handler.headers = {"Content-Length": str(len(body) if length is None else length)}
        handler.rfile = io.BytesIO(body)
        handler.wfile = io.BytesIO()
        handler.send_response = Mock()
        handler.send_header = Mock()
        handler.end_headers = Mock()
        return handler

    def test_post_rejects_invalid_json_and_non_object_payloads(self):
        for body in (b"{", b"[]", b"null", b'"text"', b"\xff"):
            with self.subTest(body=body):
                handler = self.handler("/api/login/request", body)
                handler.do_POST()
                handler.send_response.assert_called_once_with(400)
                self.assertEqual({"error": "invalid_json"}, json.loads(handler.wfile.getvalue()))

    def test_post_rejects_invalid_lengths_before_reading_body(self):
        for length, status in (("bad", 400), (-1, 400), (1_048_577, 413)):
            with self.subTest(length=length):
                handler = self.handler("/api/login/request", b"{}", length)
                handler.do_POST()
                handler.send_response.assert_called_once_with(status)
                self.assertEqual(0, handler.rfile.tell())

    def test_json_response_has_utf8_content_length(self):
        handler = self.handler("/")
        handler.send_json({"name": "فروشگاه"}, 201)
        handler.send_response.assert_called_once_with(201)
        handler.send_header.assert_any_call("Content-Length", str(len(handler.wfile.getvalue())))
        self.assertEqual({"name": "فروشگاه"}, json.loads(handler.wfile.getvalue()))

    @patch("backend.server.connect")
    def test_cached_media_preserves_content_and_cache_headers(self, connect):
        for path, row in (
            ("/api/media/1", {"image_blob": b"image", "mime_type": "image/jpeg"}),
            ("/api/avatars/1", {"avatar_blob": b"image", "avatar_mime_type": "image/jpeg"}),
        ):
            with self.subTest(path=path):
                connect.return_value.__enter__.return_value.execute.return_value.fetchone.return_value = row
                handler = self.handler(path)
                handler.do_GET()
                handler.send_response.assert_called_once_with(200)
                handler.send_header.assert_any_call("Content-Type", "image/jpeg")
                handler.send_header.assert_any_call("Cache-Control", "public, max-age=86400")
                self.assertEqual(b"image", handler.wfile.getvalue())

    def test_shared_browser_module_is_served(self):
        handler = self.handler("/assets/js/shared.js")
        handler.do_GET()
        handler.send_response.assert_called_once_with(200)
        self.assertIn(b"export function escapeHtml", handler.wfile.getvalue())
