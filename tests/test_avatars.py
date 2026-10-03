import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from backend.services.media import cache_merchant_avatar
from backend.services.merchants import merchant_avatar_url, merchant_detail


class AvatarCacheTests(unittest.TestCase):
    @patch("backend.services.media.download_image", side_effect=OSError("temporary failure"))
    def test_failed_remote_download_preserves_the_existing_avatar(self, _download):
        database = Mock()

        with self.assertRaisesRegex(OSError, "temporary failure"):
            cache_merchant_avatar(
                database, 7, "https://example.test/avatar.jpg", "https://example.test/avatar.jpg"
            )
        database.execute.assert_not_called()

    @patch("backend.services.merchants.connect")
    def test_missing_avatar_has_no_image_url(self, connect):
        database = connect.return_value.__enter__.return_value

        def execute(sql, params=None):
            if "SELECT m.*" in sql:
                return Mock(
                    fetchone=lambda: {
                        "id": 7,
                        "name": "Shop",
                        "handle": "@shop",
                        "category_code": "1",
                        "city": "تهران",
                        "avatar_blob": None,
                    }
                )
            return []

        database.execute.side_effect = execute
        self.assertIsNone(merchant_detail(7).avatar_url)

    def test_avatar_url_changes_with_the_cached_image_timestamp(self):
        first = merchant_avatar_url(7, datetime(2026, 10, 1, tzinfo=timezone.utc))
        second = merchant_avatar_url(7, datetime(2026, 10, 2, tzinfo=timezone.utc))

        self.assertNotEqual(first, second)
        self.assertTrue(first.startswith("/api/avatars/7?v="))


if __name__ == "__main__":
    unittest.main()
