import unittest
from contextlib import nullcontext
from unittest.mock import Mock, patch

from backend.models.analytics import AnalyticsEvent
from backend.services.analytics import record_event


class AnalyticsPersistenceTests(unittest.TestCase):
    @patch("backend.services.analytics.connect")
    def test_optional_foreign_keys_use_null_and_real_references_are_retained(self, connect):
        database = Mock()
        connect.return_value = nullcontext(database)
        for category, merchant, expected in (
            ("", 0, (None, None)),
            ("67010300", 7, ("67010300", 7)),
        ):
            event = AnalyticsEvent(
                event_type="merchant_click",
                session_id="public-session",
                query="",
                category_code=category,
                merchant_id=merchant,
                result_count=0,
            )
            self.assertTrue(record_event(event))
            parameters = database.execute.call_args.args[1]
            self.assertEqual(expected, parameters[3:5])
            self.assertEqual("public-session", parameters[1])
