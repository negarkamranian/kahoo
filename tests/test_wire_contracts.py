import io
import json
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from backend.instagram import extract_embed_posts
from backend.models.instagram.embed import EmbedPosts
from backend.models.instagram.meta import MetaProfile
from backend.models.media import InstagramImage, InstagramPost
from backend.models.search import SearchBenchmark
from backend.services.media import download_image


class WireContractTests(unittest.TestCase):
    def embed(self, media):
        return EmbedPosts.model_validate({"graphql_media": [{"shortcode_media": media}]}).posts()

    def test_single_embed_post_uses_its_declared_image_and_id(self):
        post = self.embed(
            {
                "__typename": "GraphVideo",
                "id": "video-id",
                "shortcode": "abc",
                "display_url": "https://example.test/cover.jpg",
                "thumbnail_src": "https://example.test/other.jpg",
                "taken_at_timestamp": 0,
            }
        )[0]
        self.assertEqual("https://example.test/cover.jpg", post.media[0].image_url)
        self.assertEqual("video-id", post.collection_key)
        self.assertEqual("", post.caption)
        self.assertEqual(1970, post.published_at.year)

    def test_embed_rejects_missing_fields_instead_of_trying_alternatives(self):
        base = {"__typename": "GraphImage", "id": "image-id", "shortcode": "abc"}
        for fields in (
            {"thumbnail_src": "https://example.test/alternate.jpg"},
            {"display_url": None, "thumbnail_src": "https://example.test/alternate.jpg"},
            {"display_url": "https://example.test/a.jpg", "edge_media_to_caption": {"wrong": []}},
            {"__typename": "GraphSidecar", "display_url": "https://example.test/a.jpg"},
            {"__typename": "GraphSidecar", "edge_sidecar_to_children": {"edges": []}},
        ):
            with self.subTest(fields=fields), self.assertRaises(ValidationError):
                self.embed({**base, **fields})
        with self.assertRaises(ValidationError):
            EmbedPosts.model_validate({"graphql_media": [base]})

    def test_meta_video_uses_thumbnail_even_when_video_url_is_present(self):
        profile = MetaProfile.model_validate(
            {
                "name": "Shop",
                "media": {
                    "data": [
                        {
                            "id": "video-id",
                            "media_type": "VIDEO",
                            "permalink": "https://instagram.com/p/abc/",
                            "media_url": "https://example.test/video.mp4",
                            "thumbnail_url": "https://example.test/cover.jpg",
                        }
                    ]
                },
            }
        ).to_profile()
        self.assertEqual("https://example.test/cover.jpg", profile.posts[0].media[0].image_url)
        self.assertEqual("video-id", profile.posts[0].media[0].instagram_media_id)

    def test_meta_missing_video_thumbnail_is_not_replaced_with_media_url(self):
        with self.assertRaises(ValidationError):
            MetaProfile.model_validate(
                {
                    "name": "Shop",
                    "media": {
                        "data": [
                            {
                                "id": "video-id",
                                "media_type": "VIDEO",
                                "permalink": "https://instagram.com/p/abc/",
                                "media_url": "https://example.test/video.mp4",
                            }
                        ]
                    },
                }
            )

    def test_ambiguous_media_contexts_fail_instead_of_picking_the_first(self):
        payload = json.dumps({"contexts": [{"graphql_media": []}, {"graphql_media": []}]})
        with self.assertRaisesRegex(ValueError, "exactly one"):
            extract_embed_posts(f"<script>server.handle({payload});</script>")

    def test_post_identity_is_required_and_cannot_be_overridden(self):
        fields = {
            "permalink": "https://instagram.com/p/abc/",
            "media": [
                InstagramImage(
                    instagram_media_id="image-id", image_url="https://example.test/a.jpg"
                )
            ],
        }
        with self.assertRaises(ValidationError):
            InstagramPost(**fields)
        with self.assertRaises(ValidationError):
            InstagramPost(**fields, instagram_media_id="post-id", collection_key="other")

    def test_benchmark_has_one_input_shape(self):
        with self.assertRaises(ValidationError):
            SearchBenchmark.model_validate(
                {"queries": [{"query": "shop", "expected_handles": ["@shop"]}]}
            )
        for relevance in ({}, {"@shop": -1}, {"@shop": True}):
            with self.subTest(relevance=relevance), self.assertRaises(ValidationError):
                SearchBenchmark.model_validate(
                    {"queries": [{"query": "shop", "relevance": relevance}]}
                )
        benchmark = SearchBenchmark.model_validate(
            {"queries": [{"query": "shop", "relevance": {"@shop": 3}}]}
        )
        self.assertEqual({"@shop": 3}, benchmark.queries[0].relevance)

    @patch("backend.services.media.urlopen")
    def test_image_bytes_are_authoritative_and_non_images_fail(self, urlopen):
        for content, mime in (
            (b"\xff\xd8\xffimage", "image/jpeg"),
            (b"\x89PNG\r\n\x1a\nimage", "image/png"),
        ):
            urlopen.return_value = io.BytesIO(content)
            self.assertEqual((content, mime), download_image("https://example.test/image"))
        urlopen.return_value = io.BytesIO(b"<html>not an image</html>")
        with self.assertRaisesRegex(ValueError, "invalid image response"):
            download_image("https://example.test/image")
