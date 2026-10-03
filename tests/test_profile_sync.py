import unittest
from unittest.mock import Mock, patch

from backend.models.media import InstagramProfile, MerchantMedia

from backend.services.profiles import refresh_instagram_avatars, refresh_instagram_profiles


class ProfileSyncTests(unittest.TestCase):
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
        callback = Mock()
        with self.assertRaisesRegex(OSError, "offline"):
            refresh_instagram_profiles(on_result=callback)
        index.assert_called_once_with(connect.return_value.__enter__.return_value)
        connect.return_value.__exit__.assert_called_once_with(None, None, None)
        self.assertEqual("@good", callback.call_args.args[0].handle)

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
        callback = Mock()
        results = refresh_instagram_avatars(
            ["@complete", "@missing", "@later"], callback, only_missing=True, limit=1
        )
        profile.assert_called_once_with("@missing")
        self.assertEqual("image/jpeg", results[0].mime_type)
        callback.assert_called_once_with(results[0])
        posts.assert_not_called()
        index.assert_not_called()

    @patch("backend.services.profiles.sync_search_index")
    @patch("backend.services.profiles.connect")
    @patch("backend.services.profiles.instagram_profile")
    @patch("backend.services.profiles.merchant_media_rows")
    def test_full_refresh_stops_at_a_failed_profile(self, rows, profile, connect, index):
        rows.return_value = [
            MerchantMedia(id=1, name="Bad", handle="@bad"),
            MerchantMedia(id=2, name="Good", handle="@good"),
        ]
        profile.side_effect = [
            OSError("offline"),
            InstagramProfile(name="Good", biography="فروشگاه"),
        ]
        on_start, on_result = Mock(), Mock()
        with self.assertRaisesRegex(OSError, "offline"):
            refresh_instagram_profiles(on_start=on_start, on_result=on_result)
        profile.assert_called_once_with("@bad")
        on_start.assert_called_once_with("@bad")
        on_result.assert_not_called()
        connect.assert_not_called()
        index.assert_not_called()
