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


def test_creates_under_the_business_then_shares_with_the_ad_account(monkeypatch, client):
    """An ad account can only ever own one pixel of its own - see
    meta_client.py's create_pixel docstring for the "(#6200) A pixel
    already exists for this account" failure this avoids. Pixels are
    created under the Business, then shared to the ad account."""
    calls = []

    def fake_post(url, data, timeout):
        calls.append({"url": url, "data": data, "timeout": timeout})
        if url.endswith("/adspixels"):
            return FakeResponse(200, {"id": "123456789012345"})
        return FakeResponse(200, {"success": True})

    monkeypatch.setattr("gtm_provisioner.meta_client.requests.post", fake_post)

    pixel_id = client.create_pixel("ShopShop Pigeon - Dataset")

    assert pixel_id == "123456789012345"
    assert calls[0]["url"] == f"{GRAPH_API_BASE}/495054980697867/adspixels"
    assert calls[0]["data"]["name"] == "ShopShop Pigeon - Dataset"
    assert calls[0]["data"]["access_token"] == "fake-system-user-token"
    assert calls[1]["url"] == f"{GRAPH_API_BASE}/123456789012345/shared_accounts"
    assert calls[1]["data"]["business"] == "495054980697867"
    assert calls[1]["data"]["account_id"] == "1451413912465476"
    assert calls[1]["data"]["access_token"] == "fake-system-user-token"


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
    with pytest.raises(ProvisioningError, match="business_management permissions"):
        client.create_pixel("ShopShop Pigeon - Dataset")


def test_a_manage_pixels_audit_error_names_the_admin_requirement(monkeypatch, client):
    """Confirmed live: an Employee System User with both ads_management and
    business_management on its token still can't create a pixel under a
    Business - only an Admin System User can. No permission scope fixes
    this, so the hint must say so plainly instead of pointing back at
    permissions."""
    monkeypatch.setattr(
        "gtm_provisioner.meta_client.requests.post",
        lambda *a, **k: FakeResponse(
            400,
            {
                "error": {
                    "message": (
                        "You do not have permission to perform this action. "
                        "This action requires that you can "
                        "MANAGE_PIXELS_AUDIT_NEEDED for this business account."
                    ),
                    "code": 10,
                }
            },
        ),
    )
    with pytest.raises(ProvisioningError, match="Admin System User"):
        client.create_pixel("ShopShop Pigeon - Dataset")


def test_retries_a_retryable_status_and_then_succeeds(monkeypatch, client):
    responses = iter(
        [
            FakeResponse(429, {"error": {"message": "rate limited"}}),
            FakeResponse(200, {"id": "123456789012345"}),
            FakeResponse(200, {"success": True}),
        ]
    )
    calls = []

    def fake_post(*a, **k):
        calls.append(1)
        return next(responses)

    monkeypatch.setattr("gtm_provisioner.meta_client.requests.post", fake_post)

    assert client.create_pixel("ShopShop Pigeon - Dataset") == "123456789012345"
    assert len(calls) == 3


def test_a_failed_share_reports_the_orphaned_pixel(monkeypatch, client):
    """The pixel was already created under the Business; the operator needs
    its ID to fix sharing or delete it by hand, the same way an orphaned
    GA4 property or GTM container is reported."""

    def fake_post(url, data, timeout):
        if url.endswith("/adspixels"):
            return FakeResponse(200, {"id": "123456789012345"})
        return FakeResponse(500, {"error": {"message": "boom"}})

    monkeypatch.setattr("gtm_provisioner.meta_client.requests.post", fake_post)

    with pytest.raises(ProvisioningError, match="123456789012345.*not shared"):
        client.create_pixel("ShopShop Pigeon - Dataset")


def test_a_network_error_retries_then_gives_up(monkeypatch, client):
    import requests

    def always_times_out(*a, **k):
        raise requests.exceptions.Timeout("timed out")

    monkeypatch.setattr("gtm_provisioner.meta_client.requests.post", always_times_out)

    with pytest.raises(ProvisioningError, match="network error"):
        client.create_pixel("ShopShop Pigeon - Dataset")


def test_rename_pixel_posts_the_new_name_to_the_pixel_itself(monkeypatch, client):
    calls = []

    def fake_post(url, data, timeout):
        calls.append({"url": url, "data": data})
        return FakeResponse(200, {"success": True})

    monkeypatch.setattr("gtm_provisioner.meta_client.requests.post", fake_post)

    client.rename_pixel("123456789012345", "ShopShop Pigeon - Dataset")

    assert calls[0]["url"] == f"{GRAPH_API_BASE}/123456789012345"
    assert calls[0]["data"]["name"] == "ShopShop Pigeon - Dataset"
    assert calls[0]["data"]["access_token"] == "fake-system-user-token"


def test_rename_pixel_raises_on_failure(monkeypatch, client):
    monkeypatch.setattr(
        "gtm_provisioner.meta_client.requests.post",
        lambda *a, **k: FakeResponse(
            400, {"error": {"message": "No such pixel"}}
        ),
    )
    with pytest.raises(ProvisioningError, match="No such pixel"):
        client.rename_pixel("999999999999999", "ShopShop Pigeon - Dataset")


# -- sharing a reused pixel ------------------------------------------------


def _share_list(*account_ids, next_url=None):
    page = {"data": [{"id": account_id} for account_id in account_ids]}
    if next_url:
        page["paging"] = {"next": next_url}
    return page


def test_an_already_shared_pixel_is_skipped_without_posting(monkeypatch, client):
    gets = []

    def fake_get(url, params=None, timeout=None):
        gets.append({"url": url, "params": params})
        return FakeResponse(200, _share_list("act_111", "act_1451413912465476"))

    def no_post(*a, **k):
        raise AssertionError("must not share a pixel the ad account already has")

    monkeypatch.setattr("gtm_provisioner.meta_client.requests.get", fake_get)
    monkeypatch.setattr("gtm_provisioner.meta_client.requests.post", no_post)

    assert client.ensure_shared_with_ad_account("123456789012345") == "already"
    assert gets[0]["url"] == f"{GRAPH_API_BASE}/123456789012345/shared_accounts"
    assert gets[0]["params"]["business"] == "495054980697867"
    assert gets[0]["params"]["access_token"] == "fake-system-user-token"


def test_a_pixel_missing_the_ad_account_is_shared(monkeypatch, client):
    posts = []
    monkeypatch.setattr(
        "gtm_provisioner.meta_client.requests.get",
        lambda url, params=None, timeout=None: FakeResponse(200, _share_list("act_111")),
    )

    def fake_post(url, data, timeout):
        posts.append({"url": url, "data": data})
        return FakeResponse(200, {"success": True})

    monkeypatch.setattr("gtm_provisioner.meta_client.requests.post", fake_post)

    assert client.ensure_shared_with_ad_account("123456789012345") == "shared"
    assert posts[0]["url"] == f"{GRAPH_API_BASE}/123456789012345/shared_accounts"
    assert posts[0]["data"]["account_id"] == "1451413912465476"
    assert posts[0]["data"]["business"] == "495054980697867"


def test_the_ad_account_on_a_later_page_is_found(monkeypatch, client):
    pages = {
        "first": FakeResponse(200, _share_list("act_111", next_url="https://graph/next")),
        "https://graph/next": FakeResponse(200, _share_list("1451413912465476")),
    }

    def fake_get(url, params=None, timeout=None):
        return pages["first"] if params else pages[url]

    monkeypatch.setattr("gtm_provisioner.meta_client.requests.get", fake_get)
    monkeypatch.setattr(
        "gtm_provisioner.meta_client.requests.post",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should skip")),
    )
    assert client.ensure_shared_with_ad_account("123456789012345") == "already"


def test_if_the_share_list_cannot_be_read_the_share_is_attempted_anyway(monkeypatch, client):
    monkeypatch.setattr(
        "gtm_provisioner.meta_client.requests.get",
        lambda url, params=None, timeout=None: FakeResponse(
            400, {"error": {"message": "Unsupported get request"}}
        ),
    )
    posts = []
    monkeypatch.setattr(
        "gtm_provisioner.meta_client.requests.post",
        lambda url, data, timeout: posts.append(url) or FakeResponse(200, {"success": True}),
    )
    assert client.ensure_shared_with_ad_account("123456789012345") == "shared"
    assert len(posts) == 1


def test_a_failed_share_of_a_reused_pixel_names_the_pixel_and_the_fix(monkeypatch, client):
    monkeypatch.setattr(
        "gtm_provisioner.meta_client.requests.get",
        lambda url, params=None, timeout=None: FakeResponse(200, _share_list()),
    )
    monkeypatch.setattr(
        "gtm_provisioner.meta_client.requests.post",
        lambda *a, **k: FakeResponse(403, {"error": {"message": "No permission"}}),
    )
    with pytest.raises(ProvisioningError, match="share it by hand") as caught:
        client.ensure_shared_with_ad_account("123456789012345")
    assert "123456789012345" in str(caught.value)
