"""Building the Meta pixel-creation request and validating what comes back.

Meta has no client library to fake through a service object the way GTM and
GA4 do, so `requests.post` itself is monkeypatched.
"""

import dataclasses

import pytest

from gtm_provisioner.errors import ProvisioningError
from gtm_provisioner.meta_client import GRAPH_API_BASE, MetaClient


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self):
        return self._payload


@pytest.fixture
def meta_config(config):
    return dataclasses.replace(
        config,
        meta_ad_account_id="1451413912465476",
        initial_backoff_seconds=0.001,
        max_backoff_seconds=0.001,
        max_retries=2,
    )


@pytest.fixture
def client(meta_config):
    return MetaClient("fake-system-user-token", meta_config, log=lambda *_: None)


def test_posts_to_the_configured_ad_account_with_the_name_and_token(monkeypatch, client):
    calls = []

    def fake_post(url, data, timeout):
        calls.append({"url": url, "data": data, "timeout": timeout})
        return FakeResponse(200, {"id": "123456789012345"})

    monkeypatch.setattr("gtm_provisioner.meta_client.requests.post", fake_post)

    pixel_id = client.create_pixel("ShopShop Pigeon - Dataset")

    assert pixel_id == "123456789012345"
    assert calls[0]["url"] == f"{GRAPH_API_BASE}/act_1451413912465476/adspixels"
    assert calls[0]["data"]["name"] == "ShopShop Pigeon - Dataset"
    assert calls[0]["data"]["access_token"] == "fake-system-user-token"


def test_a_response_with_no_id_is_a_fatal_error(monkeypatch, client):
    monkeypatch.setattr(
        "gtm_provisioner.meta_client.requests.post",
        lambda *a, **k: FakeResponse(200, {}),
    )
    with pytest.raises(ProvisioningError, match="no id"):
        client.create_pixel("ShopShop Pigeon - Dataset")


def test_a_malformed_returned_id_is_a_fatal_error(monkeypatch, client):
    """Same principle as the GA4 measurement ID check: a bad ID must stop the
    run, not silently wire the container to nothing."""
    monkeypatch.setattr(
        "gtm_provisioner.meta_client.requests.post",
        lambda *a, **k: FakeResponse(200, {"id": "not-a-real-id"}),
    )
    with pytest.raises(ProvisioningError, match="does not look like a valid"):
        client.create_pixel("ShopShop Pigeon - Dataset")


def test_a_403_names_the_permission_and_asset_hint(monkeypatch, client):
    monkeypatch.setattr(
        "gtm_provisioner.meta_client.requests.post",
        lambda *a, **k: FakeResponse(
            403, {"error": {"message": "Permissions error", "code": 200}}
        ),
    )
    with pytest.raises(ProvisioningError, match="ads_management permission"):
        client.create_pixel("ShopShop Pigeon - Dataset")


def test_retries_a_retryable_status_and_then_succeeds(monkeypatch, client):
    responses = iter([FakeResponse(429, {"error": {"message": "rate limited"}}), FakeResponse(200, {"id": "123456789012345"})])
    calls = []

    def fake_post(*a, **k):
        calls.append(1)
        return next(responses)

    monkeypatch.setattr("gtm_provisioner.meta_client.requests.post", fake_post)

    assert client.create_pixel("ShopShop Pigeon - Dataset") == "123456789012345"
    assert len(calls) == 2


def test_a_network_error_retries_then_gives_up(monkeypatch, client):
    import requests

    def always_times_out(*a, **k):
        raise requests.exceptions.Timeout("timed out")

    monkeypatch.setattr("gtm_provisioner.meta_client.requests.post", always_times_out)

    with pytest.raises(ProvisioningError, match="network error"):
        client.create_pixel("ShopShop Pigeon - Dataset")
