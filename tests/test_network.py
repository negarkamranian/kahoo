import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

from backend.network import retry_network


class NetworkRetryTests(unittest.TestCase):
    @patch("backend.network.sleep")
    def test_transient_connection_errors_retry_then_return_response(self, sleep):
        for error in (URLError("offline"), TimeoutError("SSL handshake timed out")):
            with self.subTest(error=type(error).__name__):
                operation = Mock(side_effect=[error, error, b"response"])
                self.assertEqual(b"response", retry_network(operation)())
                self.assertEqual(3, operation.call_count)

    @patch("backend.network.sleep")
    def test_retries_stop_after_three_attempts(self, sleep):
        operation = Mock(side_effect=URLError("offline"))
        with self.assertRaises(URLError):
            retry_network(operation)()
        self.assertEqual(3, operation.call_count)
        self.assertEqual(2, sleep.call_count)

    @patch("backend.network.sleep")
    def test_unavailable_server_retries(self, sleep):
        operation = Mock(
            side_effect=[HTTPError("https://example.test", 503, "busy", {}, None), b"ok"]
        )
        self.assertEqual(b"ok", retry_network(operation)())
        self.assertEqual(2, operation.call_count)

    @patch("backend.network.sleep")
    def test_permanent_http_and_validation_errors_are_not_retried(self, sleep):
        for error in (
            HTTPError("https://example.test", 404, "missing", {}, None),
            ValueError("invalid"),
        ):
            with self.subTest(error=type(error).__name__):
                operation = Mock(side_effect=error)
                with self.assertRaises(type(error)):
                    retry_network(operation)()
                self.assertEqual(1, operation.call_count)
        sleep.assert_not_called()
