import json
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import Mock, patch

from backend.serialization import json_default
from backend.services.merchants import merchant_detail, merchant_posts


class MerchantModelsTests(unittest.TestCase):
    @patch("backend.services.merchants.connect")
    def test_detail_serializes_nested_models_without_private_blobs(self, connect):
        database = connect.return_value.__enter__.return_value
        updated = datetime(2026, 10, 3, tzinfo=timezone.utc)

        def execute(sql, params=None):
            if "SELECT m.*" in sql:
                return Mock(
                    fetchone=lambda: {
                        "id": 1,
                        "name": "shop",
                        "handle": "@shop",
                        "category_code": "child",
                        "city": "تهران",
                        "avatar_blob": b"private",
                        "avatar_mime_type": "image/jpeg",
                        "avatar_updated_at": updated,
                    }
                )
            if "FROM merchant_posts" in sql:
                return [
                    {
                        "id": 2,
                        "image_url": "remote.jpg",
                        "permalink": "https://instagram.com/p/abc/",
                        "position": 1,
                        "collection_key": "abc",
                        "media_position": 1,
                    }
                ]
            if "FROM merchant_categories" in sql:
                return [{"code": "child", "label": "کفش", "confidence": Decimal("0.9")}]
            return [
                {"code": "child", "parent_code": "parent", "label_fa": "کفش"},
                {"code": "parent", "parent_code": None, "label_fa": "پوشاک"},
            ]

        database.execute.side_effect = execute
        result = json.loads(json.dumps(merchant_detail(1), default=json_default))
        self.assertNotIn("avatar_blob", result)
        self.assertNotIn("avatar_mime_type", result)
        self.assertEqual(["parent", "child"], [item["code"] for item in result["category_path"]])
        self.assertEqual(0.9, result["categories"][0]["confidence"])
        self.assertEqual("/api/media/2", result["posts"][0]["media"][0]["media_url"])
        self.assertTrue(result["avatar_url"].startswith("/api/avatars/1?v="))

    def test_post_collections_keep_grouping_and_deduplicate_images(self):
        database = Mock()
        database.execute.return_value = [
            {
                "id": i,
                "image_url": image,
                "permalink": "https://instagram.com/p/abc/",
                "position": i,
                "collection_key": "abc",
                "media_position": i,
            }
            for i, image in enumerate(("one.jpg", "one.jpg", "two.jpg"), 1)
        ]
        posts = merchant_posts(database, 1)
        self.assertEqual(1, len(posts))
        self.assertEqual(2, posts[0].image_count)
        self.assertEqual([1, 2], [image.position for image in posts[0].media])

    def test_migrated_legacy_posts_keep_distinct_keys_despite_similar_urls(self):
        database = Mock()
        database.execute.return_value = [
            {
                "id": i,
                "image_url": "same.jpg",
                "permalink": f"https://instagram.com/p/abc{i}/",
                "position": i,
                "collection_key": str(i),
                "media_position": 1,
            }
            for i in (1, 2)
        ]
        posts = merchant_posts(database, 1)
        self.assertEqual(2, len(posts))
        self.assertEqual(["1", "2"], [post.key for post in posts])
