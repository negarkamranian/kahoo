import json
import unittest
from unittest.mock import MagicMock, Mock, patch
from uuid import uuid4

from fastapi.testclient import TestClient

from backend.cli.taxonomy import normalize
from backend.config import settings
from backend.models.products import ProductResult
from backend.server.app import app
from backend.services.product_vision import extract_product, request_json, validated_attributes
from backend.services.product_worker import finish_product, process_next_product
from backend.services.products import enqueue_products, source_hash
from backend.services.taxonomy import TaxonomyStore
from tests.test_taxonomy import upstream_fixture


def taxonomy_fixture():
    return TaxonomyStore(normalize(json.dumps(upstream_fixture()).encode()))


def image_fixture(position=1, data=b"jpeg"):
    return {
        "merchant_id": 7,
        "collection_key": "carousel-1",
        "caption": "کفش آبی",
        "permalink": "https://instagram.com/p/abc/",
        "media_position": position,
        "image_url": f"https://example.test/{position}.jpg",
        "image_blob": data,
        "mime_type": "image/jpeg",
    }


def result_fixture():
    return ProductResult(
        title="کفش",
        category_code="aa",
        category_name="Apparel",
        confidence=0.9,
        evidence="کپشن: کفش",
        images_used=1,
    )


class ProductVisionTests(unittest.TestCase):
    @patch("backend.services.product_vision.product_taxonomy")
    @patch("backend.services.product_vision.request_json")
    def test_classifies_then_extracts_using_caption_and_every_carousel_image(self, request, store):
        store.return_value = taxonomy_fixture()
        choices = [
            {
                "category_code": "aa" + "-1" * level,
                "is_product": True,
                "confidence": 0.9,
                "evidence": "کپشن و تصویر ۱",
            }
            for level in range(8)
        ]
        request.side_effect = [
            *choices,
            {
                "title": "کفش آبی",
                "description": "کفش با رنگ آبی",
                "attributes": [
                    {
                        "handle": "liner-color",
                        "value": None,
                        "value_ids": ["gid://shopify/TaxonomyValue/1"],
                        "confidence": 0.8,
                        "evidence": "رنگ آبی در تصویر ۲",
                        "source": "image",
                    }
                ],
            },
        ]
        images = [image_fixture(), image_fixture(2)]
        result = extract_product("کفش آبی", images)
        self.assertEqual("aa" + "-1" * 7, result.category_code)
        self.assertEqual(["Blue"], result.attributes[0].values)
        self.assertEqual("liner-color", result.attributes[0].handle)
        self.assertEqual(2, result.images_used)
        self.assertEqual(9, request.call_count)
        for call in request.call_args_list:
            self.assertEqual("کفش آبی", call.args[1])
            self.assertEqual(images, call.args[2])

    @patch("backend.services.product_vision.product_taxonomy", return_value=taxonomy_fixture())
    @patch("backend.services.product_vision.request_json")
    def test_non_product_posts_skip_attribute_extraction(self, request, _store):
        request.return_value = {
            "category_code": None,
            "is_product": False,
            "confidence": 0.95,
            "evidence": "پست تبریک",
        }
        result = extract_product("تبریک", [image_fixture()])
        self.assertIsNone(result.category_code)
        self.assertEqual([], result.attributes)
        request.assert_called_once()

    @patch("backend.services.product_vision.product_taxonomy", return_value=taxonomy_fixture())
    @patch("backend.services.product_vision.request_json")
    def test_category_outside_allowed_branch_is_rejected(self, request, _store):
        request.return_value = {
            "category_code": "hallucinated",
            "is_product": True,
            "confidence": 1,
            "evidence": "test",
        }
        with self.assertRaisesRegex(ValueError, "outside the allowed"):
            extract_product("caption", [image_fixture()])

    def test_missing_attributes_remain_unknown_and_invalid_values_are_rejected(self):
        from backend.models.products import ProductExtraction

        definitions = taxonomy_fixture().category_attributes("aa")
        empty = ProductExtraction(title="محصول", description="", attributes=[])
        unknown = validated_attributes(empty, definitions)[0]
        self.assertIsNone(unknown.value)
        self.assertEqual([], unknown.value_ids)
        self.assertEqual(0, unknown.confidence)
        self.assertEqual("unknown", unknown.source)
        base = {
            "handle": "liner-color",
            "value": None,
            "value_ids": [],
            "confidence": 0.8,
            "evidence": "تصویر ۱",
            "source": "image",
        }
        invalid = [
            {**base, "handle": "made-up-attribute"},
            {**base, "value_ids": ["unknown-value"]},
            {**base, "value_ids": ["gid://shopify/TaxonomyValue/1"], "evidence": None},
            {**base, "value": "invented color"},
        ]
        for attribute in invalid:
            with self.subTest(attribute=attribute), self.assertRaises(ValueError):
                validated_attributes(
                    ProductExtraction(title="محصول", description="", attributes=[attribute]),
                    definitions,
                )

    @patch("backend.services.product_vision.urlopen")
    @patch("backend.services.product_vision.settings")
    def test_vision_wire_format_contains_caption_images_and_json_mode(self, config, urlopen):
        config.product_vision_api_url = "https://vision.test/v1/chat/completions"
        config.product_vision_model = "vision-model"
        config.product_vision_api_key = "private-key"
        config.product_vision_timeout = 90
        urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(
            {"choices": [{"finish_reason": "stop", "message": {"content": '{"ok":true}'}}]}
        ).encode()
        self.assertEqual({"ok": True}, request_json("JSON instructions", "کپشن", [image_fixture()]))
        request = urlopen.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual({"type": "json_object"}, payload["response_format"])
        content = payload["messages"][1]["content"]
        self.assertIn("کپشن", json.loads(content[1]["text"].split(": ", 1)[1]))
        self.assertTrue(content[2]["image_url"]["url"].startswith("data:image/jpeg;base64,"))
        self.assertEqual("Bearer private-key", request.get_header("Authorization"))

    @patch("backend.services.product_vision.product_taxonomy", return_value=taxonomy_fixture())
    @patch("backend.services.product_vision.request_json")
    def test_image_limit_is_disclosed_as_a_warning(self, request, _store):
        request.return_value = {
            "category_code": None,
            "is_product": False,
            "confidence": 0.9,
            "evidence": "تبریک",
        }
        with patch.object(settings, "product_vision_max_images", 1):
            result = extract_product("", [image_fixture(), image_fixture(2)])
        self.assertEqual(1, result.images_used)
        self.assertIn("1 of 2", result.warnings[0])


class ProductQueueTests(unittest.TestCase):
    def test_evidence_hash_changes_with_caption_or_any_image_but_not_url_or_post_id(self):
        images = [image_fixture(), image_fixture(2)]
        original = source_hash("کپشن", images)
        self.assertEqual(
            original,
            source_hash(
                "کپشن", [{**images[0], "image_url": "refreshed-cdn-url", "id": 500}, images[1]]
            ),
        )
        self.assertNotEqual(original, source_hash("کپشن جدید", images))
        self.assertNotEqual(
            original, source_hash("کپشن", [images[0], image_fixture(2, b"changed")])
        )

    def test_carousel_is_enqueued_once_with_a_durable_copy_of_all_images(self):
        db = MagicMock()
        source = [image_fixture(), image_fixture(2)]
        db.execute.side_effect = [source, Mock(fetchone=lambda: {"id": 42}), None, None, None]
        self.assertEqual(1, enqueue_products(db, 7))
        insert = db.execute.call_args_list[1]
        self.assertIn("ON CONFLICT(merchant_id,collection_key)", insert.args[0])
        self.assertEqual("carousel-1", insert.args[1][1])
        saved_images = db.execute.call_args_list[3:]
        self.assertEqual([1, 2], [call.args[1][1] for call in saved_images])
        self.assertEqual([b"jpeg", b"jpeg"], [call.args[1][3] for call in saved_images])

    @patch("backend.services.product_worker.finish_product", return_value="failed")
    @patch("backend.services.product_worker.extract_product", side_effect=ValueError("bad value"))
    @patch("backend.services.product_worker.claim_product")
    @patch("backend.services.product_worker.vision_configured", return_value=True)
    def test_model_failure_is_recorded_and_does_not_escape_the_worker(
        self, _config, claim, _extract, finish
    ):
        row, token = {"id": 42, "caption": "کپشن"}, uuid4()
        claim.return_value = row, [image_fixture()], token
        self.assertEqual({"id": 42, "status": "failed"}, process_next_product())
        finish.assert_called_once_with(row, token, None, "bad value")

    @patch("backend.services.product_worker.connect")
    @patch("backend.services.product_worker.product_taxonomy", return_value=taxonomy_fixture())
    def test_late_results_are_audited_but_never_replace_newer_evidence(self, _store, connect):
        token = uuid4()
        db = connect.return_value.__enter__.return_value
        db.execute.return_value.fetchone.return_value = {
            "source_hash": "new",
            "claim_token": uuid4(),
        }
        row = {"id": 42, "source_hash": "old", "attempts": 1}
        self.assertEqual("superseded", finish_product(row, token, result_fixture(), None))
        self.assertEqual(2, db.execute.call_count)
        audit = db.execute.call_args_list[-1]
        self.assertEqual("superseded", audit.args[1][5])
        self.assertNotIn("UPDATE products", audit.args[0])

    @patch("backend.services.product_worker.connect")
    @patch("backend.services.product_worker.product_taxonomy", return_value=taxonomy_fixture())
    def test_success_is_saved_with_model_taxonomy_and_input_provenance(self, _store, connect):
        token = uuid4()
        db = connect.return_value.__enter__.return_value
        db.execute.return_value.fetchone.return_value = {
            "source_hash": "same",
            "claim_token": token,
        }
        row = {"id": 42, "source_hash": "same", "attempts": 1}
        self.assertEqual("ready", finish_product(row, token, result_fixture(), None))
        update = db.execute.call_args_list[-1]
        self.assertIn("UPDATE products SET status", update.args[0])
        self.assertEqual("ready", update.args[1][0])
        self.assertEqual("2026-08", update.args[1][4])


class ProductRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    @patch.object(settings, "admin_token", "secret")
    @patch("backend.server.product_routes.products.list_products")
    def test_all_product_review_and_image_routes_require_the_admin_token(self, listing):
        for method, path, body in [
            ("get", "/api/admin/products", None),
            ("get", "/api/admin/products/1/images/1", None),
            ("get", "/api/admin/products/1/history", None),
            ("post", "/api/admin/products/1/review", {"status": "approved"}),
            ("post", "/api/admin/products/1/retry", None),
            ("post", "/api/admin/products/enqueue", None),
        ]:
            with self.subTest(path=path):
                response = self.client.request(method, path, json=body)
                self.assertEqual(401, response.status_code)
        listing.assert_not_called()

    @patch("backend.server.product_routes.products.get_product_image")
    def test_product_images_return_snapshot_bytes_with_private_cache_control(self, image):
        image.return_value = {"image_blob": b"jpeg", "mime_type": "image/jpeg"}
        with patch.object(settings, "admin_token", ""):
            response = self.client.get("/api/admin/products/1/images/2")
        self.assertEqual(200, response.status_code)
        self.assertEqual(b"jpeg", response.content)
        self.assertEqual("private, no-store", response.headers["cache-control"])

    @patch.object(settings, "admin_token", "")
    @patch("backend.server.product_routes.products.list_products")
    def test_invalid_filters_and_pagination_are_rejected_before_database_access(self, listing):
        for query in ("status=made-up", "review=made-up", "offset=-1", "limit=101"):
            self.assertEqual(400, self.client.get(f"/api/admin/products?{query}").status_code)
        listing.assert_not_called()
