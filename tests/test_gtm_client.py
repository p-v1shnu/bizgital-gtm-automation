"""Retry behavior of the GTM API wrapper.

A dropped connection or a timed-out read never reaches an HttpError - it
fails before any HTTP response comes back - so it needs its own retry path
distinct from the one for HTTP status codes.
"""

import dataclasses

import httplib2
import pytest
from googleapiclient.errors import HttpError

from gtm_provisioner.errors import ProvisioningError
from gtm_provisioner.gtm_client import GtmClient


def make_http_error(status):
    return HttpError(httplib2.Response({"status": status}), b"{}")


class FlakyRequest:
    """A fake API request that raises each queued exception in turn, then succeeds."""

    def __init__(self, exceptions):
        self._exceptions = list(exceptions)
        self.calls = 0

    def execute(self):
        self.calls += 1
        if self._exceptions:
            raise self._exceptions.pop(0)
        return {"ok": True}


@pytest.fixture
def fast_config(config):
    """max_retries=2 (3 attempts total) with no real sleeping, for quick tests."""
    return dataclasses.replace(
        config, max_retries=2, initial_backoff_seconds=0.001, max_backoff_seconds=0.001
    )


@pytest.fixture
def client(fast_config):
    return GtmClient(service=None, config=fast_config, log=lambda *_: None)


def test_retries_a_retryable_http_status_and_then_succeeds(client):
    request = FlakyRequest([make_http_error(429), make_http_error(503)])
    assert client._execute(request, "test call") == {"ok": True}
    assert request.calls == 3


def test_does_not_retry_a_non_retryable_http_status(client):
    request = FlakyRequest([make_http_error(404)])
    with pytest.raises(ProvisioningError, match="HTTP 404"):
        client._execute(request, "test call")
    assert request.calls == 1


def test_a_403_names_the_account_level_access_hint(client):
    request = FlakyRequest([make_http_error(403)])
    with pytest.raises(ProvisioningError, match="Container-level access is not enough"):
        client._execute(request, "test call")


@pytest.mark.parametrize("error_type", [TimeoutError, ConnectionError])
def test_retries_a_network_error_and_then_succeeds(client, error_type):
    request = FlakyRequest([error_type("boom")])
    assert client._execute(request, "test call") == {"ok": True}
    assert request.calls == 2


def test_a_network_error_that_never_clears_stops_after_max_retries(client):
    request = FlakyRequest([TimeoutError("t1"), TimeoutError("t2"), TimeoutError("t3")])
    with pytest.raises(ProvisioningError, match="network error"):
        client._execute(request, "test call")
    assert request.calls == 3  # max_retries=2 -> 3 attempts, then it gives up
