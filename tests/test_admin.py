import json
import unittest
from contextlib import contextmanager
from datetime import datetime
from unittest.mock import Mock, patch

from backend.models.analytics import AdminMetrics, MetricsPeriod
from backend.models.merchants import AdminMerchantQuery

from backend.search.metadata import sync_search_metadata
from backend.serialization import json_default
from backend.server.http import admin_mutation_authorized
from backend.services.analytics import admin_metrics
from backend.services.merchants import admin_merchants, remove_merchant


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
        sync_search_metadata(database)
        category_calls = [
            call.args
            for call in database.execute.call_args_list
            if "merchant_categories" in call.args[0]
        ]
        self.assertEqual(2, len(category_calls))
        self.assertIn("DELETE FROM merchant_categories", category_calls[0][0])
        self.assertIn("source='merchant_primary'", category_calls[0][0])
        self.assertIn("'merchant_primary'", category_calls[1][0])
        self.assertEqual("new", category_calls[1][1][1])

    def test_daily_query_uses_a_postgres_safe_alias(self):
        database = AdminDatabase()

        @contextmanager
        def fake_connect():
            yield database

        with patch("backend.services.analytics.connect", fake_connect):
            result = admin_metrics(MetricsPeriod.WEEK)

        self.assertIsInstance(result, AdminMetrics)
        self.assertEqual(MetricsPeriod.WEEK, result.period_days)
        self.assertIn("AS event_day", database.daily_query)
        self.assertIn("GROUP BY 1 ORDER BY 1", database.daily_query)
        self.assertNotIn("GROUP BY day", database.daily_query)

    @patch("backend.services.analytics.connect")
    def test_metrics_periods_fill_missing_days_and_serialize_nested_models(self, connect):
        today = datetime.now().strftime("%Y-%m-%d")

        class PopulatedDatabase(AdminDatabase):
            def execute(self, query, params=None):
                if "to_char(created_at" in query:
                    return Cursor(
                        [
                            {
                                "event_day": today,
                                "searches": 4,
                                "clicks": 2,
                                "visitors": 3,
                                "zero_results": 1,
                            }
                        ]
                    )
                if "ROUND(AVG(result_count)" in query:
                    return Cursor(
                        [
                            {
                                "query": "shop",
                                "searches": 4,
                                "avg_results": None,
                                "zero_results": 1,
                            }
                        ]
                    )
                if "SELECT m.id,m.name,m.handle" in query:
                    return Cursor([{"id": 1, "name": "Shop", "handle": "@shop", "clicks": 2}])
                if "SELECT c.label_fa label" in query:
                    return Cursor([{"label": "Category", "views": 3}])
                return super().execute(query, params)

        connect.return_value.__enter__.return_value = PopulatedDatabase()
        for period in MetricsPeriod:
            with self.subTest(period=period):
                metrics = admin_metrics(period)
                self.assertEqual(period.value, len(metrics.daily))
                self.assertEqual(0, metrics.daily[0].searches)
                self.assertEqual(4, metrics.daily[-1].searches)
                payload = json.loads(json.dumps(metrics, default=json_default))
                self.assertEqual(period.value, payload["period_days"])
                self.assertEqual(today, payload["daily"][-1]["date"])
                self.assertNotIn("event_day", payload["daily"][-1])
                self.assertIsNone(payload["top_queries"][0]["avg_results"])
                self.assertEqual("@shop", payload["top_merchants"][0]["handle"])
                self.assertEqual(3, payload["top_categories"][0]["views"])
                self.assertEqual(0, payload["kpis"]["zero_rate"])

    @patch("backend.services.merchants.connect")
    def test_admin_page_preserves_pagination_and_avatar_urls(self, connect):
        database = connect.return_value.__enter__.return_value
        database.execute.side_effect = [
            Cursor([{"count": 2}]),
            Cursor(
                [
                    {
                        "id": 1,
                        "name": "Shop",
                        "handle": "@shop",
                        "category_code": "1",
                        "city": "Tehran",
                        "followers_count": None,
                        "post_count": 3,
                        "has_avatar": True,
                    },
                    {
                        "id": 2,
                        "name": "Other",
                        "handle": "@other",
                        "category_code": "1",
                        "city": "Tehran",
                        "followers_count": 10,
                        "post_count": 0,
                        "has_avatar": False,
                    },
                ]
            ),
        ]
        page = admin_merchants(AdminMerchantQuery(query=" shop ", limit=2, offset=3))
        self.assertEqual((2, 2, 3), (page.total, page.limit, page.offset))
        self.assertEqual("/api/avatars/1", page.items[0].avatar_url)
        self.assertIsNone(page.items[1].avatar_url)
        self.assertEqual(("%shop%", "%shop%", 2, 3), database.execute.call_args.args[1])

    def test_admin_token_is_required_only_when_configured(self):
        with patch.multiple("backend.server.http.settings", admin_token=""):
            self.assertTrue(admin_mutation_authorized({}))
        with patch.multiple("backend.server.http.settings", admin_token="secret"):
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

        with patch("backend.services.merchants.connect", fake_connect):
            removed = remove_merchant(12)

        self.assertEqual("@shop", removed.handle)
        statements = [query for query, _ in database.queries]
        self.assertIn("INSERT INTO merchant_exclusions", statements[1])
        self.assertIn("DELETE FROM merchants", statements[2])


if __name__ == "__main__":
    unittest.main()
