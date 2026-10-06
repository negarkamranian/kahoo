import unittest
from unittest.mock import patch

import httpx

from backend.models.auth import SessionContext
from backend.models.saved import (
    SavedCollections,
    SavedImport,
    SavedImportResult,
    SavedPostReference,
)
from backend.server.account_routes import ensure_session
from backend.server.app import app

HEADERS = {"X-Kahoo-Saved": "1"}


class SavedHttpTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        )
        self.addAsyncCleanup(self.client.aclose)
        app.dependency_overrides[ensure_session] = lambda: SessionContext(
            owner_id=101, session_id="issued-session", user=None
        )
        self.addCleanup(app.dependency_overrides.pop, ensure_session)

    @patch("backend.server.saved_routes.saved_collections", return_value=SavedCollections())
    async def test_get_reads_current_owner_and_ignores_analytics_identifier(self, collections):
        response = await self.client.get("/api/saved", headers={"X-Kahoo-Session": "another-owner"})
        self.assertEqual(200, response.status_code)
        self.assertEqual({"merchants": [], "posts": []}, response.json())
        self.assertEqual("private, no-store", response.headers["Cache-Control"])
        collections.assert_called_once_with(101)

    @patch("backend.server.saved_routes.save_merchant", return_value=SavedCollections())
    @patch("backend.server.saved_routes.unsave_merchant", return_value=SavedCollections())
    @patch("backend.server.saved_routes.save_post", return_value=SavedCollections())
    @patch("backend.server.saved_routes.unsave_post", return_value=SavedCollections())
    async def test_mutations_receive_only_current_owner_and_canonical_reference(
        self, unsave_post, save_post, unsave_merchant, save_merchant
    ):
        for method, path, service, args in (
            ("PUT", "/api/saved/merchants/7", save_merchant, (101, 7)),
            ("DELETE", "/api/saved/merchants/7", unsave_merchant, (101, 7)),
            ("PUT", "/api/saved/posts/7/stable%2Fkey", save_post, (101, 7, "stable/key")),
            ("DELETE", "/api/saved/posts/7/stable%2Fkey", unsave_post, (101, 7, "stable/key")),
        ):
            with self.subTest(method=method, path=path):
                response = await self.client.request(
                    method, path, headers=HEADERS, json={"owner_id": 999}
                )
                self.assertEqual(200, response.status_code)
                service.assert_called_once_with(*args)

    @patch("backend.server.saved_routes.save_merchant")
    @patch("backend.server.saved_routes.unsave_merchant")
    @patch("backend.server.saved_routes.import_saved")
    async def test_cross_site_and_plain_mutations_never_reach_services(
        self, import_service, remove, save
    ):
        for headers in (
            {},
            {"X-Kahoo-Saved": "wrong"},
            {**HEADERS, "Sec-Fetch-Site": "cross-site"},
            {**HEADERS, "Origin": "https://attacker.test"},
            {**HEADERS, "Origin": "https://testserver"},
            {**HEADERS, "Origin": "http://["},
        ):
            for method, path in (
                ("PUT", "/api/saved/merchants/7"),
                ("DELETE", "/api/saved/merchants/7"),
                ("POST", "/api/saved/import"),
            ):
                with self.subTest(headers=headers, method=method):
                    response = await self.client.request(method, path, headers=headers, json={})
                    self.assertEqual(403, response.status_code)
                    self.assertEqual({"error": "saved_request_forbidden"}, response.json())
        import_service.assert_not_called()
        remove.assert_not_called()
        save.assert_not_called()

    @patch("backend.server.saved_routes.save_merchant", return_value=SavedCollections())
    async def test_same_origin_mutations_are_allowed(self, save):
        response = await self.client.put(
            "/api/saved/merchants/7", headers={**HEADERS, "Origin": "http://testserver"}
        )
        self.assertEqual(200, response.status_code)
        save.assert_called_once_with(101, 7)

    @patch("backend.server.saved_routes.save_merchant", return_value=None)
    @patch("backend.server.saved_routes.save_post", return_value=None)
    async def test_missing_canonical_references_return_stable_not_found_code(
        self, _post, _merchant
    ):
        for path in ("/api/saved/merchants/7", "/api/saved/posts/7/missing"):
            with self.subTest(path=path):
                response = await self.client.put(path, headers=HEADERS)
                self.assertEqual(404, response.status_code)
                self.assertEqual({"error": "saved_reference_not_found"}, response.json())

    @patch("backend.server.saved_routes.import_saved")
    async def test_import_passes_references_and_returns_unresolved_items(self, service):
        payload = {"merchants": [{"id": 7}], "posts": [{"permalink": "canonical"}]}
        skipped = SavedPostReference(permalink="canonical")
        service.return_value = SavedImportResult(skipped_posts=[skipped])
        response = await self.client.post("/api/saved/import", headers=HEADERS, json=payload)
        self.assertEqual(200, response.status_code)
        self.assertEqual([skipped.model_dump()], response.json()["skipped_posts"])
        service.assert_called_once_with(101, SavedImport.model_validate(payload))

    @patch("backend.server.saved_routes.import_saved")
    @patch("backend.server.saved_routes.save_merchant")
    @patch("backend.server.saved_routes.save_post")
    async def test_invalid_references_never_reach_the_database(
        self, post, merchant, import_service
    ):
        for method, path, body in (
            ("POST", "/api/saved/import", {"posts": [{"key": "missing-merchant"}]}),
            ("POST", "/api/saved/import", {"merchants": [{"id": "7"}]}),
            ("POST", "/api/saved/import", {"merchants": [{"id": 7, "name": "Fake"}]}),
            ("PUT", "/api/saved/merchants/0", None),
            ("PUT", "/api/saved/merchants/bad", None),
            ("DELETE", "/api/saved/posts/0/key", None),
        ):
            with self.subTest(method=method, path=path, body=body):
                response = await self.client.request(method, path, headers=HEADERS, json=body)
                self.assertEqual(400, response.status_code)
                self.assertEqual({"error": "invalid_saved_request"}, response.json())
        import_service.assert_not_called()
        merchant.assert_not_called()
        post.assert_not_called()

    @patch("backend.server.saved_routes.saved_media")
    async def test_snapshot_media_requires_ownership_and_is_never_publicly_cached(self, media):
        media.return_value = {"image_blob": b"canonical-thumbnail", "mime_type": "image/jpeg"}
        response = await self.client.get("/api/saved/media/7/stable")
        self.assertEqual(200, response.status_code)
        self.assertEqual(b"canonical-thumbnail", response.content)
        self.assertEqual("image/jpeg", response.headers["Content-Type"])
        self.assertEqual("private, no-store", response.headers["Cache-Control"])
        media.assert_called_once_with(101, 7, "stable")
        media.return_value = None
        response = await self.client.get("/api/saved/media/7/stable")
        self.assertEqual(404, response.status_code)
        self.assertEqual({"error": "saved_reference_not_found"}, response.json())
