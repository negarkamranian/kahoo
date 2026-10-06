import unittest
from contextlib import contextmanager
from unittest.mock import Mock, patch

from pydantic import ValidationError

from backend.models.saved import SavedCollections, SavedImport, SavedPostReference
from backend.services.saved import (
    CANONICAL_SNAPSHOT,
    MERCHANT_VIEWS,
    POST_VIEWS,
    canonical_post,
    import_saved,
    read_collections,
    save_merchant,
    save_post,
    saved_media,
    unsave_merchant,
    unsave_post,
)


def cursor(row):
    result = Mock()
    result.fetchone.return_value = row
    return result


class SavedModelTests(unittest.TestCase):
    def test_migration_accepts_references_and_rejects_client_snapshots(self):
        payload = SavedImport.model_validate(
            {
                "merchants": [{"id": 7}],
                "posts": [{"merchant_id": 7, "key": "stable"}, {"permalink": "canonical"}],
            }
        )
        self.assertEqual(7, payload.merchants[0].id)
        self.assertEqual("canonical", payload.posts[1].permalink)
        for payload in (
            {"merchants": [{"id": "7"}]},
            {"merchants": [{"id": 0}]},
            {"posts": [{"key": "stable"}]},
            {"posts": [{"merchant_id": 7, "key": ""}]},
            {"posts": [{"merchant_id": 7, "key": "stable", "media_url": "evil"}]},
            {"merchants": [{"id": 7, "name": "Invented"}]},
            {"merchants": [{"id": 7}] * 1001},
        ):
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                SavedImport.model_validate(payload)


class SavedServiceTests(unittest.TestCase):
    @patch("backend.services.saved.connect")
    @patch("backend.services.saved.read_collections", return_value=SavedCollections())
    def test_remove_always_scopes_the_owner_and_post_merchant(self, _views, connection):
        db = connection.return_value.__enter__.return_value
        unsave_merchant(101, 7)
        unsave_post(101, 7, "stable")
        queries = db.execute.call_args_list
        self.assertEqual((101, 7), queries[0].args[1])
        self.assertEqual((101, 7, "stable"), queries[1].args[1])
        self.assertIn("WHERE owner_id=%s AND merchant_id=%s", queries[0].args[0])
        self.assertIn("collection_key=%s", queries[1].args[0])

    @patch("backend.services.saved.connect")
    @patch("backend.services.saved.read_collections", return_value=SavedCollections())
    def test_save_post_uses_stable_key_and_only_canonical_snapshots(self, _views, connection):
        db = connection.return_value.__enter__.return_value
        db.execute.side_effect = [
            cursor({"merchant_id": 7, "collection_key": "stable"}),
            cursor(None),
            cursor({"merchant_id": 7}),
        ]
        self.assertEqual(SavedCollections(), save_post(101, 7, "stable"))
        calls = db.execute.call_args_list
        self.assertEqual((7, "stable", 7, "stable"), calls[0].args[1])
        self.assertEqual(CANONICAL_SNAPSHOT, calls[1].args[0])
        self.assertEqual((7, "stable"), calls[1].args[1])
        self.assertEqual((101, 7, "stable"), calls[2].args[1])
        self.assertIn("FROM merchant_posts", CANONICAL_SNAPSHOT)
        self.assertIn("ON CONFLICT", calls[2].args[0])

    @patch("backend.services.saved.connect")
    @patch("backend.services.saved.read_collections", return_value=SavedCollections())
    def test_missing_canonical_references_never_create_saved_data(self, _views, connection):
        db = connection.return_value.__enter__.return_value
        db.execute.return_value = cursor(None)
        self.assertIsNone(save_merchant(101, 7))
        self.assertIsNone(save_post(101, 7, "missing"))
        self.assertFalse(
            any("INSERT INTO saved_posts" in call.args[0] for call in db.execute.call_args_list)
        )
        _views.assert_not_called()

    def test_permalink_lookup_is_parameterized_and_never_fetches_client_url(self):
        db = Mock()
        db.execute.return_value = cursor(None)
        url = "https://example.test/';DELETE FROM merchants;--"
        self.assertIsNone(canonical_post(db, SavedPostReference(permalink=url)))
        query, params = db.execute.call_args.args
        self.assertNotIn(url, query)
        self.assertEqual((url, url), params)
        self.assertIn("FROM saved_post_snapshots", query)

    @patch("backend.services.saved.connect")
    @patch("backend.services.saved.read_collections", return_value=SavedCollections())
    @patch("backend.services.saved.insert_saved_post", side_effect=[True, True, False])
    @patch("backend.services.saved.insert_saved_merchant", side_effect=[True, True, False])
    def test_import_returns_only_unresolved_references_and_keeps_owner(
        self, merchants, posts, views, connection
    ):
        payload = SavedImport.model_validate(
            {
                "merchants": [{"id": 7}, {"id": 7}, {"id": 99}],
                "posts": [
                    {"merchant_id": 7, "key": "stable"},
                    {"permalink": "https://www.instagram.com/p/known/"},
                    {"permalink": "https://www.instagram.com/p/missing/"},
                ],
            }
        )
        result = import_saved(101, payload)
        self.assertEqual([payload.merchants[2]], result.skipped_merchants)
        self.assertEqual([payload.posts[2]], result.skipped_posts)
        self.assertTrue(all(call.args[1] == 101 for call in merchants.call_args_list))
        self.assertTrue(all(call.args[1] == 101 for call in posts.call_args_list))
        views.assert_called_once_with(connection.return_value.__enter__.return_value, 101)
        connection.return_value.__exit__.assert_called_once_with(None, None, None)

    def test_failed_import_does_not_commit_a_partial_collection(self):
        events = []

        @contextmanager
        def connection():
            try:
                yield Mock()
            except RuntimeError:
                events.append("rollback")
                raise
            events.append("commit")

        payload = SavedImport.model_validate({"merchants": [{"id": 7}, {"id": 8}]})
        with (
            patch("backend.services.saved.connect", connection),
            patch(
                "backend.services.saved.insert_saved_merchant",
                side_effect=[True, RuntimeError("failure")],
            ),
            self.assertRaisesRegex(RuntimeError, "failure"),
        ):
            import_saved(101, payload)
        self.assertEqual(["rollback"], events)

    def test_views_resolve_current_media_and_keep_snapshot_fallback(self):
        db = Mock()
        db.execute.side_effect = [
            [],
            [
                {
                    "key": "stable/key",
                    "merchant_id": 7,
                    "merchant_name": "Canonical shop",
                    "permalink": "https://www.instagram.com/p/known/",
                    "media_url": "https://canonical.test/image.jpg",
                    "image_count": 3,
                    "has_image": True,
                }
            ],
        ]
        result = read_collections(db, 101)
        self.assertEqual("/api/saved/media/7/stable%2Fkey", result.posts[0].media_url)
        self.assertEqual("stable/key", result.posts[0].key)
        self.assertEqual(3, result.posts[0].image_count)
        self.assertEqual((MERCHANT_VIEWS, (101,)), db.execute.call_args_list[0].args)
        self.assertEqual((POST_VIEWS, (101,)), db.execute.call_args_list[1].args)
        self.assertIn("LEFT JOIN LATERAL", POST_VIEWS)
        self.assertIn("snapshot.image_blob", POST_VIEWS)

    @patch("backend.services.saved.connect")
    def test_saved_media_checks_owner_even_when_snapshot_exists(self, connection):
        db = connection.return_value.__enter__.return_value
        db.execute.return_value = cursor(None)
        self.assertIsNone(saved_media(102, 7, "stable"))
        query, params = db.execute.call_args.args
        self.assertEqual((102, 7, "stable"), params)
        self.assertIn("s.owner_id=%s", query)
