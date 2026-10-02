import unittest
from contextlib import contextmanager
from unittest.mock import patch

from backend.server import admin_metrics, admin_mutation_authorized, remove_merchant


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
            return Cursor([{
                "merchants": 0,
                "used_categories": 0,
                "posts": 0,
                "avatars": 0,
                "descriptions": 0,
            }])
        if "SELECT COUNT" in query:
            return Cursor([{0: 0}])
        return Cursor([])


class AdminMetricsTests(unittest.TestCase):
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
