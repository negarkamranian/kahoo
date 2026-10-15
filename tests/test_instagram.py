import io
import json
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from backend.instagram.embed import public_embed_profile
from backend.instagram.meta import business_discovery_profile


def embed_html(profile, posts=None):
    context = {"user": profile, "graphql_media": posts or []}
    envelope = {"require": [{"contextJSON": json.dumps(context)}]}
    return f'<SCRIPT data-extra=">">server.handle( {json.dumps(envelope)});</SCRIPT>'.encode()


class InstagramTests(unittest.TestCase):
    @patch("backend.instagram.embed.urlopen")
    def test_media_refresh_can_keep_existing_name_when_embed_omits_it(self, urlopen):
        for name in (None, ""):
            with self.subTest(name=name):
                posts = [
                    {
                        "shortcode_media": {
                            "__typename": "GraphImage",
                            "id": "123",
                            "shortcode": "abc",
                            "display_url": "https://example.test/a.jpg",
                        }
                    }
                ]
                urlopen.return_value = io.BytesIO(
                    embed_html({"username": "shop", "full_name": name}, posts)
                )
                result = public_embed_profile("@shop", existing_name="Stored shop name")
                self.assertEqual("Stored shop name", result.name)
                self.assertEqual(1, len(result.posts))

    @patch("backend.instagram.embed.urlopen")
    def test_unavailable_carousel_images_do_not_reject_other_images(self, urlopen):
        posts = [
            {
                "shortcode_media": {
                    "__typename": "GraphSidecar",
                    "id": "parent",
                    "shortcode": "abc",
                    "edge_sidecar_to_children": {
                        "edges": [
                            {"node": {"id": "missing", "display_url": ""}},
                            {
                                "node": {
                                    "id": "available",
                                    "display_url": "https://example.test/a.jpg",
                                }
                            },
                        ]
                    },
                }
            },
        ]
        urlopen.return_value = io.BytesIO(
            embed_html({"username": "shop", "full_name": "Shop"}, posts)
        )
        result = public_embed_profile("@shop")
        self.assertEqual(1, len(result.posts))
        self.assertEqual(
            ["available"], [image.instagram_media_id for image in result.posts[0].media]
        )

    @patch("backend.instagram.embed.urlopen")
    def test_unrelated_empty_or_invalid_contexts_do_not_hide_profile(self, urlopen):
        unrelated = {
            "require": [
                {"contextJSON": None},
                {"contextJSON": "not-json"},
                {"contextJSON": {"unrelated": True}},
            ]
        }
        urlopen.return_value = io.BytesIO(
            f"<script>unrelated.handle(notJSON);</script><script>{json.dumps(unrelated)}</script>".encode()
            + embed_html({"username": "shop", "full_name": "Shop"})
        )
        self.assertEqual("Shop", public_embed_profile("@shop").name)

    @patch.multiple(
        "backend.instagram.meta.settings", meta_ig_user_id="test", meta_access_token="test"
    )
    @patch("backend.instagram.meta.urlopen")
    @patch("backend.instagram.embed.urlopen")
    def test_missing_or_blank_names_are_rejected_without_using_the_username(
        self, urlopen, meta_open
    ):
        for name in (None, "", "   "):
            with self.subTest(source="embed", name=name):
                urlopen.return_value = io.BytesIO(
                    embed_html({"username": "shop", "full_name": name})
                )
                with self.assertRaises(ValidationError):
                    public_embed_profile("@shop")
            with self.subTest(source="business_discovery", name=name):
                meta_open.return_value = io.BytesIO(
                    json.dumps({"business_discovery": {"name": name}}).encode()
                )
                with self.assertRaises(ValidationError):
                    business_discovery_profile("@shop")

    @patch("backend.instagram.embed.urlopen")
    def test_profile_without_a_picture_keeps_avatar_empty(self, urlopen):
        urlopen.return_value = io.BytesIO(embed_html({"username": "shop", "full_name": "Shop"}))
        self.assertIsNone(public_embed_profile("@shop").avatar_url)

    @patch("backend.instagram.embed.urlopen")
    def test_flat_embed_profile_keeps_its_posts(self, urlopen):
        context = {
            "username": "shop",
            "full_name": "Shop",
            "graphql_media": [
                {
                    "shortcode_media": {
                        "__typename": "GraphImage",
                        "id": "123",
                        "shortcode": "abc",
                        "display_url": "https://example.test/post.jpg",
                    }
                }
            ],
        }
        urlopen.return_value = io.BytesIO(
            f'<script type="application/json">{json.dumps(context)}</script>'.encode()
        )
        result = public_embed_profile("@shop")
        self.assertEqual("Shop", result.name)
        self.assertEqual("123", result.posts[0].instagram_media_id)
        urlopen.return_value = io.BytesIO(
            f'<script type="application/json">{json.dumps(context)}</script>'.encode()
        )
        with self.assertRaisesRegex(ValueError, "profile not found"):
            public_embed_profile("@other")

    @patch("backend.instagram.embed.urlopen")
    def test_public_embed_decodes_json_strings_and_keeps_carousel_children(self, urlopen):
        profile = {
            "username": "shop",
            "profile_pic_url": "https://example.test/avatar.jpg",
            "full_name": 'فروشگاه "تازه"',
            "biography": 'خط اول\nخط "دوم"',
            "edge_followed_by": {"count": 120},
            "is_verified": False,
        }
        posts = [
            {
                "shortcode_media": {
                    "__typename": "GraphSidecar",
                    "id": "parent",
                    "shortcode": "abc",
                    "taken_at_timestamp": 1728000000,
                    "edge_media_to_caption": {"edges": [{"node": {"text": 'کیف "چرمی"'}}]},
                    "edge_sidecar_to_children": {
                        "edges": [
                            {"node": {"id": "first", "display_url": "https://example.test/1.jpg"}},
                            {
                                "node": {
                                    "id": "second",
                                    "display_url": "https://example.test/2.jpg",
                                }
                            },
                        ]
                    },
                }
            }
        ]
        urlopen.return_value = io.BytesIO(embed_html(profile, posts))
        result = public_embed_profile("@shop")
        self.assertEqual(profile["full_name"], result.name)
        self.assertEqual(profile["biography"], result.biography)
        self.assertEqual(120, result.followers_count)
        self.assertFalse(result.instagram_verified)
        self.assertEqual(2, result.media_grouping_version)
        self.assertEqual('کیف "چرمی"', result.posts[0].caption)
        self.assertIsNotNone(result.posts[0].published_at.tzinfo)
        self.assertEqual(
            ["first", "second"], [image.instagram_media_id for image in result.posts[0].media]
        )

    @patch("backend.instagram.embed.urlopen")
    def test_plain_json_scripts_do_not_guess_posts_from_unrelated_nodes(self, urlopen):
        profile = {
            "username": "shop",
            "full_name": "Shop",
            "profile_pic_url": "https://example.test/avatar.jpg",
        }
        post = {"shortcode": "abc", "display_url": "https://example.test/post.jpg"}
        payload = {"user": profile, "posts": [post, post]}
        urlopen.return_value = io.BytesIO(
            f'<script type="application/json">{json.dumps(payload)}</script>'.encode()
        )
        with self.assertRaisesRegex(ValueError, "exactly one Instagram media context"):
            public_embed_profile("@shop")

    @patch("backend.instagram.embed.urlopen")
    def test_unrelated_profile_is_rejected(self, urlopen):
        urlopen.return_value = io.BytesIO(
            embed_html({"username": "other", "full_name": "Other", "profile_pic_url": "other.jpg"})
        )
        with self.assertRaisesRegex(ValueError, "profile not found"):
            public_embed_profile("@shop")

    @patch.multiple(
        "backend.instagram.meta.settings", meta_ig_user_id="test", meta_access_token="test"
    )
    @patch("backend.instagram.meta.urlopen")
    def test_business_discovery_returns_the_same_media_contract(self, urlopen):
        data = {
            "business_discovery": {
                "name": "shop",
                "media": {
                    "data": [
                        {
                            "id": "parent",
                            "media_type": "CAROUSEL_ALBUM",
                            "permalink": "https://instagram.com/p/abc/",
                            "timestamp": "2026-10-03T00:00:00+0000",
                            "children": {
                                "data": [
                                    {
                                        "id": "first",
                                        "media_type": "IMAGE",
                                        "media_url": "https://example.test/1.jpg",
                                    },
                                    {
                                        "id": "second",
                                        "media_type": "VIDEO",
                                        "thumbnail_url": "https://example.test/2.jpg",
                                    },
                                ]
                            },
                        }
                    ]
                },
            }
        }
        urlopen.return_value = io.BytesIO(json.dumps(data).encode())
        profile = business_discovery_profile("@shop")
        self.assertEqual("meta_business_discovery", profile.source)
        self.assertEqual("parent", profile.posts[0].collection_key)
        self.assertEqual([1, 2], [image.media_position for image in profile.posts[0].media])
        self.assertEqual(2026, profile.posts[0].published_at.year)
