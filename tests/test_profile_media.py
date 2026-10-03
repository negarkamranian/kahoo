import json
import unittest
from unittest.mock import Mock, patch

from backend.instagram import extract_embed_posts
from backend.server.media import replace_profile_posts
from backend.server.profiles import merchant_media_needs


class ProfileMediaTests(unittest.TestCase):
    def test_media_backfill_detects_generated_avatar_and_old_post_sync(self):
        needs_avatar, needs_posts = merchant_media_needs(
            {
                "avatar_blob": b"svg",
                "avatar_mime_type": "image/svg+xml",
                "avatar_source_url": None,
                "cached_images": 4,
                "instagram_media_sync_version": 1,
            }
        )

        self.assertTrue(needs_avatar)
        self.assertTrue(needs_posts)

    def test_media_backfill_skips_complete_saved_media(self):
        needs_avatar, needs_posts = merchant_media_needs(
            {
                "avatar_blob": b"jpeg",
                "avatar_mime_type": "image/jpeg",
                "avatar_source_url": "https://example.test/avatar.jpg",
                "cached_images": 3,
                "instagram_media_sync_version": 2,
            }
        )

        self.assertFalse(needs_avatar)
        self.assertFalse(needs_posts)

    def test_embed_carousel_children_share_the_parent_collection(self):
        media = {
            "context": {
                "graphql_media": [
                    {
                        "shortcode_media": {
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
        self.assertEqual("parent-1", posts[0]["collection_key"])
        self.assertEqual([1, 2], [item["media_position"] for item in posts[0]["media"]])
        self.assertEqual(
            ["child-1", "child-2"], [item["instagram_media_id"] for item in posts[0]["media"]]
        )

    @patch("backend.server.media.download_image", return_value=(b"jpeg", "image/jpeg"))
    def test_profile_posts_are_downloaded_and_inserted(self, _download):
        database = Mock()
        profile = {
            "source": "instagram_public_embed",
            "posts": [
                {
                    "image_url": "https://example.test/one.jpg",
                    "permalink": "https://www.instagram.com/p/one/",
                },
                {
                    "image_url": "https://example.test/two.jpg",
                    "permalink": "https://www.instagram.com/p/two/",
                },
            ],
        }

        saved = replace_profile_posts(database, 3, "shop", profile)

        self.assertEqual(2, saved)
        self.assertEqual(3, database.execute.call_count)
        self.assertIn("DELETE FROM merchant_posts", database.execute.call_args_list[0].args[0])


if __name__ == "__main__":
    unittest.main()
