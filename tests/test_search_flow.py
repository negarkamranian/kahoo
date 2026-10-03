import unittest
from unittest.mock import Mock, patch

from backend.search.metadata import sync_search_metadata
from backend.search.service import merchants
from backend.search.suggestions import search_suggestions


class SearchFlowTests(unittest.TestCase):
    @patch("backend.search.service.semantic_merchant_scores", side_effect=OSError("offline"))
    @patch("backend.search.service.lexical_merchant_matches", return_value={})
    @patch("backend.search.service.connect")
    def test_embedding_failure_aborts_search(self, connect, lexical, semantic):
        connect.return_value.__enter__.return_value.execute.return_value = []
        with self.assertRaisesRegex(OSError, "offline"):
            merchants(query="کیف")

    @patch("backend.search.service.merchant_posts", return_value=[])
    @patch("backend.search.service.semantic_merchant_scores", return_value={})
    @patch("backend.search.service.lexical_merchant_matches", return_value={})
    @patch("backend.search.service.connect")
    def test_search_matches_new_merchant_content_without_seeded_vocabulary(
        self, connect, lexical, semantic, posts
    ):
        row = {
            "id": 1,
            "handle": "@new",
            "name": "فروشگاه تازه",
            "city": "تهران",
            "description": "فرفره مغناطیسی",
            "biography": "",
            "category_code": "new-category",
            "avatar_blob": None,
        }

        def execute(sql, params=None):
            if "FROM search_aliases" in sql:
                self.fail("search must not read a manually maintained synonym table")
            if sql.startswith("SELECT m.* FROM merchants"):
                return [row]
            return []

        connect.return_value.__enter__.return_value.execute.side_effect = execute
        results = merchants(query="فرفره مغناطیسی")
        self.assertEqual([1], [item.id for item in results])
        self.assertEqual(1, results[0].match_coverage)
        self.assertEqual("exact", results[0].match_quality)

    def test_metadata_is_derived_from_stored_text_and_preserves_imported_categories(self):
        row = {
            "id": 1,
            "handle": "@new",
            "category_code": "new-category",
            "description": "محصول تازه",
            "description_source_url": "https://example.test",
            "biography": "ابزار جدید",
            "instagram_url": "https://instagram.com/new/",
        }
        db = Mock()
        db.execute.side_effect = lambda sql, params=None: (
            [row] if sql.startswith("SELECT id,handle") else []
        )
        sync_search_metadata(db)
        calls = [call.args for call in db.execute.call_args_list]
        terms = {args[1][1] for args in calls if "INSERT INTO merchant_search_terms" in args[0]}
        self.assertTrue({"محصول", "تازه", "ابزار", "جدید"} <= terms)
        for sql, *_ in calls:
            self.assertNotIn("search_aliases", sql)
            if "DELETE FROM merchant_categories" in sql:
                self.assertIn("source='merchant_primary'", sql)
                self.assertNotIn("curated_catalog", sql)

    @patch("backend.search.suggestions.connect")
    def test_newly_stored_terms_become_suggestions_without_a_code_change(self, connect):
        def execute(sql, params=None):
            if "FROM merchant_search_terms" in sql:
                return [{"term": "محصول تازه", "weight": 1}]
            if "FROM search_aliases" in sql:
                self.fail("suggestions must not depend on a manually maintained synonym table")
            return []

        connect.return_value.__enter__.return_value.execute.side_effect = execute
        results = search_suggestions("محصول")
        self.assertEqual(["محصول تازه"], [row.value for row in results])
