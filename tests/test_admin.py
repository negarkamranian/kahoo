import unittest
from contextlib import contextmanager
from unittest.mock import Mock, patch

from backend.server import (
    admin_metrics,
    admin_mutation_authorized,
    remove_merchant,
    seed_search_metadata,
)


class Cursor:
    def __init__(self, rows):
        self.rows = rows

    def __iter__(self):
        return iter(self.rows)

    def fetchone(self):
        return self.rows[0]


class AdminDatabase:
    def __init__(self):
        self.daily_query = ""

    def execute(self, query, params=None):
        if "to_char(created_at" in query:
            self.daily_query = query
            return Cursor([])
        if "FROM merchants) merchants" in query:
            return Cursor(
                [
                    {
                        "merchants": 0,
                        "used_categories": 0,
                        "posts": 0,
                        "avatars": 0,
                        "descriptions": 0,
                    }
                ]
            )
        if "SELECT COUNT" in query:
            return Cursor([{"count": 0}])
        return Cursor([])


class AdminMetricsTests(unittest.TestCase):
    def test_category_refresh_removes_stale_primary_and_preserves_primary_priority(self):
        merchant = {
            "id": 12,
            "handle": "@shop",
            "category_code": "new",
            "description": "",
            "description_source_url": "https://example.test",
            "biography": "",
            "instagram_url": "https://www.instagram.com/shop/",
        }
        database = Mock()
        database.execute.side_effect = lambda query, params=None: (
            [merchant] if "SELECT id,handle,category_code" in query else []
        )
        with patch("backend.server.MERCHANT_CATEGORY_SEED", {"@shop": ("new", "extra")}):
            seed_search_metadata(database)
        category_calls = [
            call.args
            for call in database.execute.call_args_list
            if "merchant_categories" in call.args[0]
        ]
        self.assertEqual(3, len(category_calls))
        self.assertIn("DELETE FROM merchant_categories", category_calls[0][0])
        self.assertIn("source IN ('merchant_primary','curated_catalog')", category_calls[0][0])
        self.assertIn("'merchant_primary'", category_calls[1][0])
        self.assertEqual("new", category_calls[1][1][1])
        self.assertEqual("extra", category_calls[2][1][1])

    def test_daily_query_uses_a_postgres_safe_alias(self):
        database = AdminDatabase()

        @contextmanager
        def fake_connect():
            yield database

        with patch("backend.server.connect", fake_connect):
            result = admin_metrics(7)

        self.assertEqual(7, result["period_days"])
        self.assertIn("AS event_day", database.daily_query)
        self.assertIn("GROUP BY 1 ORDER BY 1", database.daily_query)
        self.assertNotIn("GROUP BY day", database.daily_query)

    def test_admin_token_is_required_only_when_configured(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertTrue(admin_mutation_authorized({}))
        with patch.dict("os.environ", {"KAHOO_ADMIN_TOKEN": "secret"}, clear=True):
            self.assertFalse(admin_mutation_authorized({}))
            self.assertFalse(admin_mutation_authorized({"X-Kahoo-Admin-Token": "wrong"}))
            self.assertTrue(admin_mutation_authorized({"X-Kahoo-Admin-Token": "secret"}))

    def test_removal_creates_a_persistent_exclusion_before_deleting(self):
        class RemovalDatabase:
            def __init__(self):
                self.queries = []

            def execute(self, query, params=None):
                self.queries.append((query, params))
                if "SELECT id,name,handle FROM merchants" in query:
                    return Cursor([{"id": 12, "name": "Shop", "handle": "@shop"}])
                return Cursor([])

        database = RemovalDatabase()

        @contextmanager
        def fake_connect():
            yield database

        with patch("backend.server.connect", fake_connect):
            removed = remove_merchant(12)

        self.assertEqual("@shop", removed["handle"])
        statements = [query for query, _ in database.queries]
        self.assertIn("INSERT INTO merchant_exclusions", statements[1])
        self.assertIn("DELETE FROM merchants", statements[2])


if __name__ == "__main__":
    unittest.main()
