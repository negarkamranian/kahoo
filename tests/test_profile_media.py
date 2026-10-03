import json
import unittest
from unittest.mock import Mock, patch

from backend.models.media import InstagramImage, InstagramPost, InstagramProfile, MerchantMedia

from backend.instagram import extract_embed_posts
from backend.services.media import replace_profile_posts


class ProfileMediaTests(unittest.TestCase):
    def test_media_backfill_detects_generated_avatar_and_old_post_sync(self):
        merchant = MerchantMedia.model_validate(
            {
                "id": 1,
                "handle": "@shop",
                "avatar_blob": b"svg",
                "avatar_mime_type": "image/svg+xml",
                "avatar_source_url": None,
                "cached_images": 4,
                "instagram_media_sync_version": 1,
            }
        )

        self.assertTrue(merchant.needs_avatar)
        self.assertTrue(merchant.needs_posts(3))

    def test_media_backfill_skips_complete_saved_media(self):
        merchant = MerchantMedia.model_validate(
            {
                "id": 1,
                "handle": "@shop",
                "avatar_blob": b"jpeg",
                "avatar_mime_type": "image/jpeg",
                "avatar_source_url": "https://example.test/avatar.jpg",
                "cached_images": 3,
                "instagram_media_sync_version": 2,
            }
        )

        self.assertFalse(merchant.needs_avatar)
        self.assertFalse(merchant.needs_posts(3))

    def test_embed_carousel_children_share_the_parent_collection(self):
        media = {
            "context": {
                "graphql_media": [
                    {
                        "shortcode_media": {
                            "__typename": "GraphSidecar",
                            "id": "parent-1",
                            "shortcode": "carousel-code",
                            "edge_sidecar_to_children": {
                                "edges": [
                                    {
                                        "node": {
                                            "id": "child-1",
                                            "display_url": "https://example.test/1.jpg",
                                        }
                                    },
                                    {
                                        "node": {
                                            "id": "child-2",
                                            "display_url": "https://example.test/2.jpg",
                                        }
                                    },
                                ]
                            },
                        }
                    }
                ]
            }
        }
        server_data = {"require": [{"contextJSON": json.dumps(media)}]}
        payload = f"<script>server.handle({json.dumps(server_data)});</script>"

        posts = extract_embed_posts(payload)

        self.assertEqual(1, len(posts))
        self.assertEqual("parent-1", posts[0].collection_key)
        self.assertEqual([1, 2], [item.media_position for item in posts[0].media])
        self.assertEqual(
            ["child-1", "child-2"], [item.instagram_media_id for item in posts[0].media]
        )

    @patch("backend.services.media.download_image", return_value=(b"jpeg", "image/jpeg"))
    def test_profile_posts_are_downloaded_and_inserted(self, _download):
        database = Mock()
        profile = InstagramProfile(
            name="shop",
            posts=[
                InstagramPost(
                    permalink=f"https://www.instagram.com/p/{code}/",
                    instagram_media_id=code,
                    media=[
                        InstagramImage(
                            instagram_media_id=code, image_url=f"https://example.test/{code}.jpg"
                        )
                    ],
                )
                for code in ("one", "two")
            ],
        )
        saved = replace_profile_posts(database, 3, profile)

        self.assertEqual(2, saved)
        self.assertEqual(4, database.execute.call_count)
        self.assertIn("DELETE FROM merchant_posts", database.execute.call_args_list[0].args[0])

    @patch("backend.services.media.download_image", side_effect=OSError("offline"))
    def test_failed_downloads_preserve_posts_and_sync_version(self, download):
        database = Mock()
        profile = InstagramProfile(
            name="shop",
            posts=[
                InstagramPost(
                    permalink="https://instagram.com/p/abc/",
                    instagram_media_id="abc",
                    media=[
                        InstagramImage(
                            instagram_media_id="one", image_url="https://example.test/1.jpg"
                        )
                    ],
                )
            ],
        )
        with self.assertRaisesRegex(OSError, "offline"):
            replace_profile_posts(database, 3, profile)
        database.execute.assert_not_called()

    @patch("backend.services.media.download_image")
    def test_partial_download_failure_does_not_replace_the_gallery(self, download):
        def fetch(url):
            if url.endswith("bad.jpg"):
                raise OSError("download failed")
            return b"jpeg", "image/jpeg"

        download.side_effect = fetch
        database = Mock()
        profile = InstagramProfile(
            name="shop",
            posts=[
                InstagramPost(
                    permalink="https://instagram.com/p/abc/",
                    instagram_media_id="abc",
                    media=[
                        InstagramImage(
                            instagram_media_id="good", image_url="https://example.test/good.jpg"
                        ),
                        InstagramImage(
                            instagram_media_id="bad", image_url="https://example.test/bad.jpg"
                        ),
                    ],
                )
            ],
        )
        with self.assertRaisesRegex(OSError, "download failed"):
            replace_profile_posts(database, 3, profile)
        database.execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
