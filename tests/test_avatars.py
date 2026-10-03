import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from backend.services.media import cache_merchant_avatar
from backend.services.merchants import merchant_avatar_url


class AvatarCacheTests(unittest.TestCase):
    @patch("backend.services.media.download_image", side_effect=OSError("temporary failure"))
    def test_failed_remote_download_preserves_the_existing_avatar(self, _download):
        database = Mock()

        result = cache_merchant_avatar(
            database, 7, "ک", "#e3e7e1", "https://example.test/avatar.jpg"
        )

        self.assertFalse(result)
        database.execute.assert_not_called()

    def test_missing_avatar_gets_a_generated_fallback(self):
        database = Mock()

        result = cache_merchant_avatar(database, 7, "ک", "#e3e7e1")

        self.assertEqual("image/svg+xml", result)
        database.execute.assert_called_once()

    def test_avatar_url_changes_with_the_cached_image_timestamp(self):
        first = merchant_avatar_url(
            {
                "id": 7,
                "avatar_updated_at": datetime(2026, 10, 1, tzinfo=timezone.utc),
            }
        )
        second = merchant_avatar_url(
            {
                "id": 7,
                "avatar_updated_at": datetime(2026, 10, 2, tzinfo=timezone.utc),
            }
        )

        self.assertNotEqual(first, second)
        self.assertTrue(first.startswith("/api/avatars/7?v="))


if __name__ == "__main__":
    unittest.main()
