"""Shared retry, backoff and throttling behaviour for Google API clients.

Both the GTM and GA4 clients hit the same two failure modes: the API quota
(HTTP 429/5xx) and a dropped connection or timed-out read that never reaches
an HTTP response at all. Both need identical retry semantics, so it lives
here once rather than duplicated per client.
"""

import random
import ssl
import time

from googleapiclient.errors import HttpError

from .errors import ProvisioningError

RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

# A dropped connection or a read timing out never reaches HttpError - it fails
# before any HTTP response comes back - so it needs its own retry path.
RETRYABLE_NETWORK_ERRORS = (TimeoutError, ConnectionError, ssl.SSLError)


class RetryingApiClient:
    """Mixin: throttled, retrying execution of a googleapiclient request.

    A subclass must set `self._config` (needs `max_retries`,
    `initial_backoff_seconds`, `max_backoff_seconds`,
    `request_interval_seconds`) and `self._log` before calling `_execute`.
    Override `_describe_http_error` to add product-specific hints to a
    non-retryable HTTP error's message.
    """

    def __init__(self):
        self._last_request_at = 0.0

    def _throttle(self):
        """Keep a minimum gap between requests to stay under the write quota."""
        interval = self._config.request_interval_seconds
        if interval <= 0:
            return
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < interval:
            time.sleep(interval - elapsed)

    def _execute(self, request, description):
        """Run one API request, retrying transient failures with backoff."""
        delay = self._config.initial_backoff_seconds
        attempts = self._config.max_retries + 1

        for attempt in range(1, attempts + 1):
            self._throttle()
            try:
                response = request.execute()
            except HttpError as exc:
                self._last_request_at = time.monotonic()
                status = exc.resp.status if exc.resp is not None else None
                if status not in RETRYABLE_STATUS_CODES or attempt == attempts:
                    raise ProvisioningError(
                        self._describe_http_error(exc, status, description)
                    ) from exc
                delay = self._wait_before_retry(
                    f"hit HTTP {status}", description, delay, attempt, attempts
                )
            except RETRYABLE_NETWORK_ERRORS as exc:
                self._last_request_at = time.monotonic()
                if attempt == attempts:
                    raise ProvisioningError(
                        f"{description} failed with a network error: {exc}"
                    ) from exc
                delay = self._wait_before_retry(
                    f"hit a network error ({exc})", description, delay, attempt, attempts
                )
            else:
                self._last_request_at = time.monotonic()
                return response

        raise ProvisioningError(f"{description} exhausted all retries.")

    def _wait_before_retry(self, reason, description, delay, attempt, attempts):
        """Sleep with jittered backoff and return the next delay to use."""
        wait = min(delay, self._config.max_backoff_seconds)
        wait *= 1.0 + random.random() * 0.25  # jitter, to de-sync retries
        self._log(
            f"    ~ {description} {reason}; "
            f"retrying in {wait:.1f}s (attempt {attempt}/{attempts})"
        )
        time.sleep(wait)
        return min(delay * 2, self._config.max_backoff_seconds)

    @staticmethod
    def _describe_http_error(exc, status, description):
        return f"{description} failed with HTTP {status}: {exc}"
