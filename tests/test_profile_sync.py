import unittest
from unittest.mock import patch
from urllib.error import URLError

from pydantic import ValidationError

from backend.instagram.schemas import EmbedContext
from backend.models.media import InstagramProfile, MerchantMedia
from backend.services.profiles import refresh_instagram_avatars, refresh_instagram_profiles


class ProfileSyncTests(unittest.TestCase):
    @patch("backend.services.profiles.instagram_profile")
    @patch("backend.services.profiles.merchant_media_rows")
    def test_ssl_timeout_is_reported_without_aborting_batch(self, rows, profile):
        rows.return_value = [MerchantMedia(id=1, handle="@timeout")]
        profile.side_effect = URLError(TimeoutError("SSL handshake timed out"))
        results = refresh_instagram_profiles()
        self.assertEqual(1, len(results))
        self.assertEqual("@timeout", results[0].handle)
        self.assertFalse(results[0].updated)
        self.assertIn("SSL handshake timed out", results[0].error)

    @patch("backend.services.profiles.instagram_profile")
    @patch("backend.services.profiles.merchant_media_rows")
    def test_invalid_response_reports_handle_without_exposing_payload(self, rows, profile):
        rows.return_value = [MerchantMedia(id=1, handle="@bad")]
        try:
            EmbedContext.model_validate({"graphql_media": [], "token": "secret-token"})
        except ValidationError as error:
            profile.side_effect = error
        result = refresh_instagram_profiles()[0]
        self.assertFalse(result.updated)
        self.assertEqual("@bad", result.handle)
        self.assertIn("user", result.error)
        self.assertNotIn("secret-token", result.error)

    @patch(
        "backend.services.profiles.cache_merchant_avatar", side_effect=OSError("download failed")
    )
    @patch("backend.services.profiles.connect")
    @patch("backend.services.profiles.instagram_profile")
    @patch("backend.services.profiles.merchant_media_rows")
    def test_save_failure_rolls_back_merchant_and_continues(self, rows, profile, connect, cache):
        rows.return_value = [
            MerchantMedia(id=1, handle="@bad"),
            MerchantMedia(id=2, handle="@good"),
        ]
        profile.side_effect = [
            InstagramProfile(name="Bad", avatar_url="https://example.test/a.jpg"),
            InstagramProfile(name="Good"),
        ]
        results = refresh_instagram_avatars()
        self.assertEqual("download failed", results[0].error)
        self.assertIsNone(results[1].error)
        self.assertIs(OSError, connect.return_value.__exit__.call_args_list[0].args[0])
        self.assertEqual(2, profile.call_count)

    @patch("backend.services.profiles.sync_search_index")
    @patch("backend.services.profiles.connect")
    @patch("backend.services.profiles.instagram_profile")
    @patch("backend.services.profiles.merchant_media_rows")
    def test_completed_profile_has_a_current_index_when_the_next_profile_fails(
        self, rows, profile, connect, index
    ):
        rows.return_value = [
            MerchantMedia(id=1, name="Good", handle="@good"),
            MerchantMedia(id=2, name="Bad", handle="@bad"),
        ]
        profile.side_effect = [InstagramProfile(name="Good"), OSError("offline")]
        results = refresh_instagram_profiles()
        self.assertTrue(results[0].updated)
        self.assertEqual("offline", results[1].error)
        index.assert_called_once_with(connect.return_value.__enter__.return_value)
        connect.return_value.__exit__.assert_called_once_with(None, None, None)
        self.assertEqual(2, profile.call_count)

    @patch("backend.services.profiles.cache_merchant_avatar")
    @patch("backend.services.profiles.connect")
    @patch(
        "backend.services.profiles.instagram_profile", return_value=InstagramProfile(name="Shop")
    )
    @patch("backend.services.profiles.merchant_media_rows")
    def test_avatar_refresh_leaves_missing_profile_picture_empty(
        self, rows, profile, connect, cache
    ):
        rows.return_value = [MerchantMedia(id=7, handle="@shop")]
        results = refresh_instagram_avatars(["@shop"])
        self.assertFalse(results[0].updated)
        self.assertIsNone(results[0].mime_type)
        cache.assert_not_called()
        connect.return_value.__enter__.return_value.execute.assert_not_called()

    @patch("backend.services.profiles.sync_search_index")
    @patch("backend.services.profiles.replace_profile_posts")
    @patch("backend.services.profiles.cache_merchant_avatar", return_value="image/jpeg")
    @patch("backend.services.profiles.connect")
    @patch("backend.services.profiles.instagram_profile")
    @patch("backend.services.profiles.merchant_media_rows")
    def test_avatar_refresh_filters_limits_and_never_replaces_posts(
        self, rows, profile, connect, cache, posts, index
    ):
        complete = MerchantMedia(
            id=1,
            handle="@complete",
            avatar_blob=b"jpeg",
            avatar_mime_type="image/jpeg",
            avatar_source_url="https://example.test/a.jpg",
        )
        missing = MerchantMedia(id=2, handle="@missing")
        rows.return_value = [complete, missing, MerchantMedia(id=3, handle="@later")]
        profile.return_value = InstagramProfile(
            name="Shop", avatar_url="https://example.test/a.jpg"
        )
        results = refresh_instagram_avatars(
            ["@complete", "@missing", "@later"], only_missing=True, limit=1
        )
        profile.assert_called_once_with("@missing", existing_name="")
        self.assertEqual("image/jpeg", results[0].mime_type)
        self.assertEqual(["@missing"], [result.handle for result in results])
        cache.assert_called_once_with(
            connect.return_value.__enter__.return_value, 2, "https://example.test/a.jpg"
        )
        posts.assert_not_called()
        index.assert_not_called()

    @patch("backend.services.profiles.sync_search_index")
    @patch("backend.services.profiles.connect")
    @patch("backend.services.profiles.instagram_profile")
    @patch("backend.services.profiles.merchant_media_rows")
    def test_full_refresh_continues_after_a_failed_profile(self, rows, profile, connect, index):
        rows.return_value = [
            MerchantMedia(id=1, name="Bad", handle="@bad"),
            MerchantMedia(id=2, name="Good", handle="@good"),
        ]
        profile.side_effect = [
            OSError("offline"),
            InstagramProfile(name="Good", biography="فروشگاه"),
        ]
        results = refresh_instagram_profiles()
        self.assertEqual("@bad", results[0].handle)
        self.assertFalse(results[0].updated)
        self.assertEqual("offline", results[0].error)
        self.assertTrue(results[1].updated)
        self.assertEqual(2, profile.call_count)
        index.assert_called_once_with(connect.return_value.__enter__.return_value)
