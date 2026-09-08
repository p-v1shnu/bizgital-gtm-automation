"""Building the GA4 property/data-stream requests and reading back the ID.

The Analytics Admin API returns a Measurement ID with no "G-" prefix; this is
the one detail that makes this client easy to get subtly wrong (it would
still "work" - the container would just carry a broken GA4 ID with no error
raised anywhere), so it gets the closest attention here.
"""

import dataclasses

import pytest

from gtm_provisioner.errors import ProvisioningError
from gtm_provisioner.ga4_client import Ga4Client


class FakeRequest:
    def __init__(self, result):
        self._result = result

    def execute(self):
        return self._result


class FakeDataStreams:
    def __init__(self, result):
        self._result = result
        self.calls = []

    def create(self, parent, body):
        self.calls.append({"parent": parent, "body": body})
        return FakeRequest(self._result)


class FakeProperties:
    def __init__(self, property_result, stream_result):
        self._result = property_result
        self.calls = []
        self.data_streams = FakeDataStreams(stream_result)

    def create(self, body):
        self.calls.append(body)
        return FakeRequest(self._result)

    def dataStreams(self):
        return self.data_streams


class FakeAnalyticsService:
    def __init__(self, property_result, stream_result):
        self.properties_resource = FakeProperties(property_result, stream_result)

    def properties(self):
        return self.properties_resource


@pytest.fixture
def ga4_config(config):
    return dataclasses.replace(
        config,
        ga4_account_id="216060784",
        ga4_timezone="Asia/Vientiane",
        ga4_currency_code="USD",
        ga4_industry_category="SHOPPING",
    )


def make_client(ga4_config, property_result=None, stream_result=None):
    service = FakeAnalyticsService(
        property_result=property_result or {"name": "properties/999"},
        stream_result=stream_result or {"webStreamData": {"measurementId": "1A2BCD345E"}},
    )
    return service, Ga4Client(service, ga4_config, log=lambda *_: None)


def test_the_property_is_created_under_the_configured_account(ga4_config):
    service, client = make_client(ga4_config)
    client.create_property_and_stream("store.shopshop.la")
    body = service.properties_resource.calls[0]
    assert body["parent"] == "accounts/216060784"
    assert body["displayName"] == "store.shopshop.la"
    assert body["timeZone"] == "Asia/Vientiane"
    assert body["currencyCode"] == "USD"
    assert body["industryCategory"] == "SHOPPING"


def test_the_stream_is_created_under_the_new_property_with_an_https_uri(ga4_config):
    service, client = make_client(ga4_config, property_result={"name": "properties/999"})
    client.create_property_and_stream("store.shopshop.la")
    call = service.properties_resource.data_streams.calls[0]
    assert call["parent"] == "properties/999"
    assert call["body"]["type"] == "WEB_DATA_STREAM"
    assert call["body"]["displayName"] == "store.shopshop.la"
    assert call["body"]["webStreamData"]["defaultUri"] == "https://store.shopshop.la"


def test_an_unprefixed_measurement_id_gets_its_g_prefix_added(ga4_config):
    _, client = make_client(
        ga4_config, stream_result={"webStreamData": {"measurementId": "1A2BCD345E"}}
    )
    assert client.create_property_and_stream("store.shopshop.la") == "G-1A2BCD345E"


def test_an_already_prefixed_measurement_id_is_not_double_prefixed(ga4_config):
    """A live v1beta property returned it already prefixed, contrary to
    Google's own docs - trust what the API actually sends, not the docs."""
    _, client = make_client(
        ga4_config, stream_result={"webStreamData": {"measurementId": "G-HCCPEM777F"}}
    )
    assert client.create_property_and_stream("store.shopshop.la") == "G-HCCPEM777F"


def test_a_response_with_no_measurement_id_is_a_fatal_error(ga4_config):
    _, client = make_client(ga4_config, stream_result={"webStreamData": {}})
    with pytest.raises(ProvisioningError, match="no measurementId"):
        client.create_property_and_stream("store.shopshop.la")


def test_a_failed_stream_creation_reports_the_orphaned_property(ga4_config):
    """The property was already created; the operator needs its name to clean
    it up by hand, the same way an orphaned GTM container is reported."""
    service = FakeAnalyticsService(
        property_result={"name": "properties/999"}, stream_result=None
    )

    def explode(parent, body):
        raise ProvisioningError("creating GA4 web data stream failed with HTTP 500: boom")

    service.properties_resource.data_streams.create = explode
    client = Ga4Client(service, ga4_config, log=lambda *_: None)

    with pytest.raises(ProvisioningError, match="properties/999"):
        client.create_property_and_stream("store.shopshop.la")


def test_a_malformed_returned_id_is_a_fatal_error_not_a_silent_bad_container(ga4_config):
    """If GA4 ever returned something that doesn't survive the G- prefix as a
    valid Measurement ID, this must stop the run rather than hand a broken ID
    to the container - the same principle as the trigger ID remapping."""
    _, client = make_client(
        ga4_config, stream_result={"webStreamData": {"measurementId": "not valid!!"}}
    )
    with pytest.raises(ProvisioningError, match="does not look like a valid"):
        client.create_property_and_stream("store.shopshop.la")
