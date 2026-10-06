import unittest
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

from fastapi.testclient import TestClient

from backend.models.analytics import AdminMetrics, AnalyticsEvent, MetricsPeriod
from backend.models.auth import LoginChallenge, LoginResult, LoginUser, SessionContext
from backend.models.categories import CategoryNode
from backend.models.merchants import (
    AdminMerchantPage,
    AdminMerchantQuery,
    ImportResult,
    Merchant,
    MerchantImport,
    MerchantSummary,
)
from backend.models.search import SearchSuggestion
from backend.server.app import app


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app, headers={"X-Kahoo-Saved": "1"})
        self.addCleanup(self.client.close)
        context = SessionContext(owner_id=1, session_id="00000000-0000-4000-8000-000000000001")
        session = patch(
            "backend.server.account_routes.open_session",
            return_value=SimpleNamespace(context=context, new_token=None),
        )
        session.start()
        self.addCleanup(session.stop)

    def test_post_rejects_invalid_json_and_non_object_payloads(self):
        for path in ("/api/login/request", "/api/merchants/import-demo"):
            for body in (b"", b"{", b"[]", b"null", b'"text"', b"\xff"):
                with self.subTest(path=path, body=body):
                    response = self.client.post(path, content=body)
                    self.assertEqual(400, response.status_code)
                    self.assertEqual({"error": "invalid_json"}, response.json())

    def test_post_rejects_invalid_lengths(self):
        for length, status, code in (
            ("bad", 400, "invalid_content_length"),
            ("-1", 400, "invalid_content_length"),
            ("1048577", 413, "request_too_large"),
        ):
            with self.subTest(length=length):
                response = self.client.post(
                    "/api/login/request", content=b"\xff", headers={"Content-Length": length}
                )
                self.assertEqual(status, response.status_code)
                self.assertEqual({"error": code}, response.json())

    @patch("backend.server.routes.merchant_detail")
    def test_json_response_has_utf8_content_length(self, detail):
        detail.return_value = Merchant(
            id=1, name="فروشگاه", handle="@shop", category_code="1", city="Tehran"
        )
        response = self.client.get("/api/merchants/1")
        self.assertEqual(200, response.status_code)
        self.assertEqual("application/json", response.headers["Content-Type"])
        self.assertEqual(str(len(response.content)), response.headers["Content-Length"])
        self.assertEqual("فروشگاه", response.json()["name"])
        self.assertIn("فروشگاه".encode(), response.content)

    @patch("backend.server.routes.merchants")
    def test_list_response_remains_an_array_and_omits_unset_fields(self, service):
        for merchants in (
            [],
            [Merchant(id=1, name="Shop", handle="@shop", category_code="1", city="Tehran")],
        ):
            with self.subTest(merchants=merchants):
                service.return_value = merchants
                response = self.client.get("/api/merchants")
                self.assertEqual(
                    []
                    if not merchants
                    else [
                        {
                            "id": 1,
                            "name": "Shop",
                            "handle": "@shop",
                            "category_code": "1",
                            "city": "Tehran",
                        }
                    ],
                    response.json(),
                )

    def test_list_endpoints_return_typed_arrays(self):
        category = CategoryNode(
            code="1",
            parent_code=None,
            level=1,
            label_fa="دسته",
            label_en=None,
            icon=None,
            count=0,
            children=[],
        )
        suggestion = SearchSuggestion(value="@shop", label="Shop", type="merchant")
        for path, service, model, field, value in (
            ("/api/categories", "category_tree", category, "children", []),
            ("/api/search/suggestions?q=shop", "search_suggestions", suggestion, "value", "@shop"),
        ):
            with (
                self.subTest(path=path),
                patch(f"backend.server.routes.{service}", return_value=[model]),
            ):
                response = self.client.get(path)
                self.assertEqual(200, response.status_code)
                self.assertIsInstance(response.json(), list)
                self.assertEqual(value, response.json()[0][field])

    @patch("backend.server.routes.connect")
    def test_cached_media_preserves_content_and_cache_headers(self, connect):
        for path, row in (
            ("/api/media/1", {"image_blob": b"image", "mime_type": "image/jpeg"}),
            ("/api/avatars/1", {"avatar_blob": b"image", "avatar_mime_type": "image/jpeg"}),
        ):
            with self.subTest(path=path):
                connect.return_value.__enter__.return_value.execute.return_value.fetchone.return_value = row
                response = self.client.get(path)
                self.assertEqual(200, response.status_code)
                self.assertEqual("image/jpeg", response.headers["Content-Type"])
                self.assertEqual("public, max-age=86400", response.headers["Cache-Control"])
                self.assertEqual(b"image", response.content)

    def test_browser_pages_and_shared_module_are_served(self):
        for path, content in (
            ("/", b"<!doctype html>"),
            ("/admin.html", b"<!doctype html>"),
            ("/assets/js/shared.js", b"export function escapeHtml"),
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(200, response.status_code)
                self.assertIn(content, response.content)

    def test_static_files_cannot_escape_public_directory(self):
        for path in ("/../.env", "/%2e%2e/.env", "/backend/config.py"):
            with self.subTest(path=path):
                self.assertEqual(404, self.client.get(path).status_code)

    @patch("backend.server.routes.admin_mutation_authorized", return_value=True)
    @patch("backend.server.routes.add_or_refresh_merchant")
    def test_import_passes_a_model_and_uses_created_status(self, import_merchant, _authorized):
        for created, status in ((True, 201), (False, 200)):
            with self.subTest(created=created):
                import_merchant.reset_mock()
                import_merchant.return_value = ImportResult(
                    handle="@shop", created=created, merchant_id=7
                )
                response = self.client.post(
                    "/api/admin/merchants", json={"identifier": "@shop", "category_code": "1"}
                )
                import_merchant.assert_called_once_with(
                    MerchantImport(identifier="@shop", category_code="1")
                )
                self.assertEqual(status, response.status_code)
                self.assertEqual(
                    {"handle": "@shop", "created": created, "merchant_id": 7}, response.json()
                )

    @patch("backend.server.routes.admin_mutation_authorized", return_value=True)
    @patch("backend.server.routes.add_or_refresh_merchant")
    def test_invalid_import_types_never_reach_the_service(self, import_merchant, _authorized):
        for payload in (
            {"identifier": []},
            {"identifier": "@shop", "name": "Manual name"},
            {"identifier": "@shop", "description": "Manual description"},
        ):
            with self.subTest(payload=payload):
                response = self.client.post("/api/admin/merchants", json=payload)
                self.assertEqual(400, response.status_code)
                self.assertEqual("merchant_import_failed", response.json()["error"])
        import_merchant.assert_not_called()

    @patch("backend.server.routes.add_or_refresh_merchant")
    @patch("backend.server.routes.remove_merchant")
    def test_admin_mutations_require_configured_token(self, remove, add):
        with patch.multiple("backend.server.routes.settings", admin_token="secret"):
            for token in (None, "wrong"):
                headers = {} if token is None else {"X-Kahoo-Admin-Token": token}
                for method, path in (
                    ("POST", "/api/admin/merchants"),
                    ("DELETE", "/api/admin/merchants/1"),
                ):
                    with self.subTest(method=method, token=token):
                        response = self.client.request(
                            method, path, json={"identifier": "@shop"}, headers=headers
                        )
                        self.assertEqual(401, response.status_code)
                        self.assertEqual("unauthorized", response.json()["error"])
        add.assert_not_called()
        remove.assert_not_called()

    @patch("backend.server.routes.record_event")
    def test_invalid_event_types_are_rejected_at_the_http_boundary(self, record_event):
        for value in (True, "7", []):
            response = self.client.post(
                "/api/analytics/event",
                json={
                    "event_type": "merchant_click",
                    "merchant_id": value,
                    "query": "",
                    "category_code": "",
                    "result_count": 0,
                },
                headers={"X-Kahoo-Session": "session-123"},
            )
            self.assertEqual(400, response.status_code)
            self.assertEqual({"saved": False}, response.json())
        record_event.assert_not_called()

    @patch("backend.server.routes.record_event")
    def test_event_session_comes_only_from_the_session_header(self, record_event):
        body = {
            "event_type": "search",
            "session_id": "body-session",
            "query": "shop",
            "category_code": "1",
            "merchant_id": 0,
            "result_count": 0,
        }
        response = self.client.post("/api/analytics/event", json=body)
        self.assertEqual(400, response.status_code)
        record_event.assert_not_called()
        response = self.client.post(
            "/api/analytics/event", json=body, headers={"X-Kahoo-Session": "header-session"}
        )
        self.assertEqual(201, response.status_code)
        self.assertEqual({"saved": True}, response.json())
        self.assertIsInstance(record_event.call_args.args[0], AnalyticsEvent)
        self.assertEqual("header-session", record_event.call_args.args[0].session_id)

    @patch("backend.server.routes.record_event")
    @patch("backend.server.routes.merchants", return_value=[])
    def test_search_records_a_complete_event_with_header_session(self, service, record_event):
        response = self.client.get(
            "/api/merchants?q=shop", headers={"X-Kahoo-Session": "session-123"}
        )
        self.assertEqual(200, response.status_code)
        service.assert_called_once_with(None, "shop")
        record_event.assert_called_once_with(
            AnalyticsEvent(
                event_type="search",
                session_id="session-123",
                query="shop",
                category_code="",
                merchant_id=0,
                result_count=0,
            )
        )

    @patch("backend.server.routes.merchant_detail")
    def test_response_preserves_dates_and_numeric_decimals_and_omits_private_blobs(self, detail):
        date = datetime(2026, 10, 3, tzinfo=timezone.utc)
        detail.return_value = Merchant(
            id=1,
            name="Shop",
            handle="@shop",
            category_code="1",
            city="Tehran",
            description_updated_at=date,
            directory_quality_score=Decimal("1.25"),
            avatar_blob=b"private",
        )
        payload = self.client.get("/api/merchants/1").json()
        self.assertEqual(date, datetime.fromisoformat(payload["description_updated_at"]))
        self.assertEqual(1.25, payload["directory_quality_score"])
        self.assertNotIn("avatar_blob", payload)

    @patch("backend.server.routes.category_tree", side_effect=[RuntimeError("database failed"), []])
    def test_request_failure_propagates_and_next_request_still_works(self, _categories):
        with self.assertRaisesRegex(RuntimeError, "database failed"):
            self.client.get("/api/categories")
        response = self.client.get("/api/categories")
        self.assertEqual(200, response.status_code)
        self.assertEqual([], response.json())

    @patch("backend.server.routes.add_or_refresh_merchant", side_effect=ValueError("bad profile"))
    @patch("backend.server.routes.admin_mutation_authorized", return_value=True)
    def test_import_service_failure_is_not_converted_to_a_client_error(self, _authorized, _service):
        with self.assertRaisesRegex(ValueError, "bad profile"):
            self.client.post("/api/admin/merchants", json={"identifier": "@shop"})

    @patch("backend.server.routes.admin_metrics")
    def test_invalid_metrics_period_is_rejected_before_service_call(self, metrics):
        for value in ("invalid", "", "0", "8", "-7", "7.0", "true"):
            with self.subTest(value=value):
                response = self.client.get(f"/api/admin/metrics?days={value}")
                self.assertEqual(400, response.status_code)
                self.assertEqual({"error": "invalid_period"}, response.json())
        metrics.assert_not_called()

    @patch("backend.server.routes.admin_metrics")
    def test_metrics_passes_period_enum_and_serializes_nested_models(self, metrics):
        for query, period in (
            ("", MetricsPeriod.MONTH),
            ("?days=7", MetricsPeriod.WEEK),
            ("?days=30", MetricsPeriod.MONTH),
            ("?days=90", MetricsPeriod.QUARTER),
        ):
            with self.subTest(query=query):
                metrics.reset_mock()
                metrics.return_value = AdminMetrics(
                    period_days=period,
                    generated_at=datetime(2026, 10, 3, tzinfo=timezone.utc),
                    kpis={
                        "searches": 0,
                        "visitors": 0,
                        "clicks": 0,
                        "zero_rate": 0,
                        "search_to_click": 0,
                    },
                    catalog={
                        "merchants": 0,
                        "used_categories": 0,
                        "posts": 0,
                        "avatars": 0,
                        "descriptions": 0,
                    },
                    daily=[],
                    top_queries=[],
                    missed_queries=[],
                    top_merchants=[],
                    top_categories=[],
                    funnel={
                        "visitors": 0,
                        "searched": 0,
                        "clicked": 0,
                        "oauth_started": 0,
                        "oauth_completed": 0,
                    },
                )
                response = self.client.get(f"/api/admin/metrics{query}")
                self.assertEqual(200, response.status_code)
                self.assertEqual(period.value, response.json()["period_days"])
                self.assertEqual(0, response.json()["kpis"]["searches"])
                self.assertEqual([], response.json()["daily"])
                self.assertIs(period, metrics.call_args.args[0])

    @patch(
        "backend.server.routes.admin_merchants",
        return_value=AdminMerchantPage(items=[], total=0, limit=100, offset=2),
    )
    def test_admin_pagination_is_validated_before_service_call(self, merchants):
        for query in ("limit=0", "limit=101", "offset=-1", "limit=", "offset=bad"):
            response = self.client.get(f"/api/admin/merchants?{query}")
            self.assertEqual(400, response.status_code)
            self.assertEqual({"error": "invalid_pagination"}, response.json())
        merchants.assert_not_called()
        response = self.client.get("/api/admin/merchants?q=shop&limit=100&offset=2")
        merchants.assert_called_once_with(AdminMerchantQuery(query="shop", limit=100, offset=2))
        self.assertEqual({"items": [], "total": 0, "limit": 100, "offset": 2}, response.json())

    @patch("backend.server.account_routes.verify_login")
    def test_login_verification_requires_a_five_character_string(self, verify):
        verify.return_value = LoginResult(
            user=LoginUser(id=1, phone="09123456789", display_name="حساب من")
        )
        challenge = "00000000-0000-4000-8000-000000000001"
        for code in (None, 12345, "", "1234", "123456"):
            response = self.client.post(
                "/api/login/verify",
                json={"phone": "09123456789", "code": code, "challenge_id": challenge},
            )
            self.assertEqual(400, response.status_code)
            self.assertEqual({"error": "invalid_code"}, response.json())
        response = self.client.post(
            "/api/login/verify",
            json={"phone": "09123456789", "code": "12345", "challenge_id": challenge},
        )
        self.assertEqual(200, response.status_code)
        self.assertEqual(
            {
                "user": {
                    "id": 1,
                    "phone": "09123456789",
                    "display_name": "حساب من",
                    "phone_verified": False,
                }
            },
            response.json(),
        )

    @patch("backend.server.account_routes.request_login")
    def test_login_request_returns_a_challenge_model(self, request_login):
        request_login.return_value = LoginChallenge(
            phone="09123456789", challenge_id="00000000-0000-4000-8000-000000000001"
        )
        response = self.client.post("/api/login/request", json={"phone": "09123456789"})
        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual("09123456789", payload["phone"])
        self.assertEqual(4, UUID(payload["challenge_id"]).version)

    def test_demo_import_returns_its_original_response_shape(self):
        response = self.client.post("/api/merchants/import-demo", json={})
        self.assertEqual(201, response.status_code)
        self.assertEqual({"created": False, "mode": "oauth_demo"}, response.json())

    @patch("backend.server.routes.remove_merchant")
    def test_removal_returns_a_nested_merchant_model(self, remove):
        remove.return_value = MerchantSummary(id=7, name="Shop", handle="@shop")
        response = self.client.delete("/api/admin/merchants/7")
        remove.assert_called_once_with(7)
        self.assertEqual(200, response.status_code)
        self.assertEqual({"removed": {"id": 7, "name": "Shop", "handle": "@shop"}}, response.json())

    @patch("backend.server.routes.remove_merchant", return_value=None)
    def test_removal_errors_keep_their_codes(self, remove):
        response = self.client.delete("/api/admin/merchants/invalid")
        self.assertEqual(400, response.status_code)
        self.assertEqual({"error": "invalid_merchant_id"}, response.json())
        remove.assert_not_called()
        response = self.client.delete("/api/admin/merchants/7")
        self.assertEqual(404, response.status_code)
        self.assertEqual({"error": "not_found"}, response.json())
