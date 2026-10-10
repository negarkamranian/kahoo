import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.models.media import InstagramProfile
from backend.models.merchants import ImportResult, MerchantRecommendation
from backend.server.app import app
from backend.services.merchants import recommend_merchant


class MerchantRecommendationTests(unittest.TestCase):
    def test_handle_normalization_and_validation(self):
        for identifier in ("shop.name", "@Shop.Name", " @shop.name "):
            self.assertEqual("@shop.name", MerchantRecommendation(identifier=identifier).identifier)
        for identifier in ("", "@", "a/b", "https://instagram.com/shop", "x" * 31):
            with self.subTest(identifier=identifier), self.assertRaises(ValidationError):
                MerchantRecommendation(identifier=identifier)

    @patch("backend.services.merchants.instagram_profile")
    @patch("backend.services.merchants.connect")
    def test_existing_shop_is_returned_without_refresh(self, connect, profile):
        database = connect.return_value.__enter__.return_value
        database.execute.side_effect = [
            Mock(),
            Mock(fetchone=lambda: None),
            Mock(fetchone=lambda: {"id": 7, "name": "Shop", "category_code": "123"}),
        ]
        result = recommend_merchant(MerchantRecommendation(identifier="shop"))
        self.assertFalse(result.created)
        self.assertEqual(7, result.merchant_id)
        profile.assert_not_called()

    @patch("backend.services.merchants.instagram_profile")
    @patch("backend.services.merchants.connect")
    def test_excluded_shop_cannot_be_reintroduced(self, connect, profile):
        connect.return_value.__enter__.return_value.execute.side_effect = [
            Mock(),
            Mock(fetchone=lambda: {"handle": "@shop"}),
        ]
        with self.assertRaises(ValueError):
            recommend_merchant(MerchantRecommendation(identifier="shop"))
        profile.assert_not_called()

    @patch("backend.services.merchants.sync_search_index")
    @patch("backend.services.merchants.replace_profile_posts", return_value=3)
    @patch("backend.services.merchants.save_imported_avatar", return_value=True)
    @patch("backend.services.merchants.create_imported_merchant", return_value=7)
    @patch(
        "backend.services.merchants.instagram_profile", return_value=InstagramProfile(name="Shop")
    )
    @patch("backend.services.merchants.connect")
    def test_new_shop_imports_profile_media_and_search_index(
        self, connect, profile, create, avatar, posts, index
    ):
        database = connect.return_value.__enter__.return_value
        database.execute.return_value.fetchone.return_value = None
        result = recommend_merchant(MerchantRecommendation(identifier="shop"))
        self.assertTrue(result.created)
        self.assertEqual(7, result.merchant_id)
        self.assertEqual("unclassified", result.category_code)
        self.assertEqual(3, result.post_images_saved)
        profile.assert_called_once_with("@shop")
        create.assert_called_once()
        avatar.assert_called_once_with(database, 7, profile.return_value)
        posts.assert_called_once_with(database, 7, profile.return_value)
        index.assert_called_once_with(database)

    @patch("backend.server.routes.recommend_merchant")
    def test_public_route_imports_username_and_rejects_cross_origin(self, service):
        service.return_value = ImportResult(handle="@shop", merchant_id=7, created=True)
        with TestClient(app) as client:
            response = client.post(
                "/api/merchants/recommend",
                json={"identifier": "Shop"},
                headers={"X-Kahoo-Saved": "1"},
            )
            self.assertEqual(201, response.status_code)
            service.assert_called_once_with(MerchantRecommendation(identifier="@shop"))
            service.reset_mock()
            response = client.post(
                "/api/merchants/recommend",
                json={"identifier": "shop"},
                headers={"X-Kahoo-Saved": "1", "Origin": "https://other.test"},
            )
            self.assertEqual(403, response.status_code)
            service.assert_not_called()
            response = client.post(
                "/api/merchants/recommend",
                json={"identifier": "bad/id"},
                headers={"X-Kahoo-Saved": "1"},
            )
            self.assertEqual(400, response.status_code)
            service.assert_not_called()

    @patch("backend.server.routes.recommend_merchant", side_effect=OSError("Instagram unavailable"))
    def test_failed_import_does_not_report_success(self, _service):
        with TestClient(app) as client:
            response = client.post(
                "/api/merchants/recommend",
                json={"identifier": "shop"},
                headers={"X-Kahoo-Saved": "1"},
            )
        self.assertEqual(502, response.status_code)
        self.assertEqual("merchant_import_failed", response.json()["error"])
