import io
import json
import unittest
from contextlib import redirect_stderr
from datetime import datetime, timezone
from decimal import Decimal
from http.server import ThreadingHTTPServer
from unittest.mock import Mock, patch

from backend.models.analytics import MetricsPeriod
from backend.models.merchants import AdminMerchantQuery, ImportResult, MerchantImport
from backend.server.http import Handler


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
        for body in (b"", b"{", b"[]", b"null", b'"text"', b"\xff"):
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

    @patch("backend.server.http.connect")
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

    @patch("backend.server.http.admin_mutation_authorized", return_value=True)
    @patch("backend.server.http.add_or_refresh_merchant")
    def test_import_validates_once_and_passes_a_model(self, import_merchant, authorized):
        import_merchant.return_value = ImportResult(handle="@shop", created=True, merchant_id=7)
        handler = self.handler(
            "/api/admin/merchants", b'{"identifier":"@shop","category_code":"1"}'
        )
        handler.do_POST()
        import_merchant.assert_called_once_with(
            MerchantImport(identifier="@shop", category_code="1")
        )
        handler.send_response.assert_called_once_with(201)
        self.assertEqual(
            {"handle": "@shop", "created": True, "merchant_id": 7},
            json.loads(handler.wfile.getvalue()),
        )

    @patch("backend.server.http.admin_mutation_authorized", return_value=True)
    @patch("backend.server.http.add_or_refresh_merchant")
    def test_invalid_import_types_never_reach_the_service(self, import_merchant, authorized):
        for payload in (
            {"identifier": []},
            {"identifier": "@shop", "name": "Manual name"},
            {"identifier": "@shop", "description": "Manual description"},
        ):
            handler = self.handler("/api/admin/merchants", json.dumps(payload).encode())
            handler.do_POST()
            handler.send_response.assert_called_once_with(400)
        import_merchant.assert_not_called()

    @patch("backend.server.http.record_event")
    def test_invalid_event_types_are_rejected_at_the_http_boundary(self, record_event):
        for value in (True, "7", []):
            payload = {
                "event_type": "merchant_click",
                "session_id": "session-123",
                "merchant_id": value,
            }
            handler = self.handler("/api/analytics/event", json.dumps(payload).encode())
            handler.headers["X-Kahoo-Session"] = "session-123"
            handler.do_POST()
            handler.send_response.assert_called_once_with(400)
        record_event.assert_not_called()

    @patch("backend.server.http.record_event")
    def test_event_session_comes_only_from_the_session_header(self, record_event):
        body = b'{"event_type":"search","session_id":"body-session"}'
        handler = self.handler("/api/analytics/event", body)
        handler.do_POST()
        handler.send_response.assert_called_once_with(400)
        record_event.assert_not_called()
        handler = self.handler("/api/analytics/event", body)
        handler.headers["X-Kahoo-Session"] = "header-session"
        handler.do_POST()
        handler.send_response.assert_called_once_with(201)
        self.assertEqual("header-session", record_event.call_args.args[0].session_id)

    def test_response_serialization_preserves_dates_and_numeric_decimals(self):
        handler = self.handler("/")
        handler.send_json(
            {"date": datetime(2026, 10, 3, tzinfo=timezone.utc), "score": Decimal("1.25")}
        )
        self.assertEqual(
            {"date": "2026-10-03T00:00:00+00:00", "score": 1.25},
            json.loads(handler.wfile.getvalue()),
        )

    @patch("backend.server.http.category_tree", side_effect=[RuntimeError("database failed"), []])
    def test_request_failure_logs_traceback_and_next_request_still_works(self, categories):
        server = ThreadingHTTPServer.__new__(ThreadingHTTPServer)
        server.RequestHandlerClass = Handler
        logs = io.StringIO()
        responses = []
        with redirect_stderr(logs):
            for _ in range(2):
                connection = Mock()
                connection.makefile.return_value = io.BytesIO(
                    b"GET /api/categories HTTP/1.0\r\n\r\n"
                )
                server.process_request_thread(connection, ("127.0.0.1", 12345))
                responses.append(
                    b"".join(call.args[0] for call in connection.sendall.call_args_list)
                )
        self.assertEqual(b"", responses[0])
        self.assertIn(b"200 OK", responses[1])
        self.assertIn("Traceback (most recent call last)", logs.getvalue())
        self.assertIn("RuntimeError: database failed", logs.getvalue())

    @patch("backend.server.http.add_or_refresh_merchant", side_effect=ValueError("bad profile"))
    @patch("backend.server.http.admin_mutation_authorized", return_value=True)
    def test_import_service_failure_is_not_converted_to_a_client_error(self, authorized, service):
        handler = self.handler("/api/admin/merchants", b'{"identifier":"@shop"}')
        with self.assertRaisesRegex(ValueError, "bad profile"):
            handler.do_POST()
        handler.send_response.assert_not_called()

    @patch("backend.server.http.admin_metrics")
    def test_invalid_metrics_period_does_not_default_to_thirty_days(self, metrics):
        for value in ("invalid", "", "0", "8", "-7", "7.0", "true"):
            with self.subTest(value=value):
                handler = self.handler(f"/api/admin/metrics?days={value}")
                handler.do_GET()
                handler.send_response.assert_called_once_with(400)
                self.assertEqual(
                    {"error": "invalid_metrics_period"}, json.loads(handler.wfile.getvalue())
                )
        metrics.assert_not_called()

    @patch("backend.server.http.admin_metrics", return_value={})
    def test_metrics_passes_only_period_enum_values_to_service(self, metrics):
        for query, period in (
            ("", MetricsPeriod.MONTH),
            ("?days=7", MetricsPeriod.WEEK),
            ("?days=30", MetricsPeriod.MONTH),
            ("?days=90", MetricsPeriod.QUARTER),
        ):
            with self.subTest(query=query):
                metrics.reset_mock()
                handler = self.handler(f"/api/admin/metrics{query}")
                handler.do_GET()
                self.assertIs(period, metrics.call_args.args[0])
                handler.send_response.assert_called_once_with(200)

    @patch("backend.server.http.admin_merchants", return_value={})
    def test_admin_pagination_is_validated_before_service_call(self, merchants):
        for query in ("limit=0", "limit=101", "offset=-1", "limit=", "offset=bad"):
            handler = self.handler(f"/api/admin/merchants?{query}")
            handler.do_GET()
            handler.send_response.assert_called_once_with(400)
        merchants.assert_not_called()
        handler = self.handler("/api/admin/merchants?q=shop&limit=100&offset=2")
        handler.do_GET()
        merchants.assert_called_once_with(AdminMerchantQuery(query="shop", limit=100, offset=2))

    def test_login_verification_requires_a_five_character_string(self):
        for code in (None, 12345, "", "1234", "123456"):
            handler = self.handler("/api/login/verify", json.dumps({"code": code}).encode())
            handler.do_POST()
            handler.send_response.assert_called_once_with(400)
        handler = self.handler("/api/login/verify", b'{"code":"12345"}')
        handler.do_POST()
        handler.send_response.assert_called_once_with(200)
