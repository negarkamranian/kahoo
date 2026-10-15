"""Bounded retries for transient outbound connection failures."""

from functools import wraps
from time import sleep
from urllib.error import HTTPError, URLError


def retry_network(operation):
    @wraps(operation)
    def request_with_retries(*args, **kwargs):
        for attempt in range(3):
            try:
                return operation(*args, **kwargs)
            except (URLError, TimeoutError, ConnectionError) as error:
                permanent_http_error = isinstance(error, HTTPError) and getattr(
                    error, "code", None
                ) not in (
                    429,
                    500,
                    502,
                    503,
                    504,
                )
                if permanent_http_error or attempt == 2:
                    raise
                sleep(0.5 * (attempt + 1))
        return None

    return request_with_retries
