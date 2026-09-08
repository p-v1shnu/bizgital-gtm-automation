"""Collecting operator input and resolving the GA4 Measurement ID from it."""

import pytest

from gtm_provisioner.store_inputs import DRY_RUN_GA4_MEASUREMENT_ID, collect_store_inputs


class FakeGa4Client:
    """Stands in for Ga4Client, recording the domain it was asked to create."""

    def __init__(self, measurement_id="G-FAKE123456"):
        self.requested_domains = []
        self._measurement_id = measurement_id

    def create_property_and_stream(self, website_domain):
        self.requested_domains.append(website_domain)
        return self._measurement_id


def test_supplied_values_are_validated_and_used_as_is():
    ga4_client = FakeGa4Client(measurement_id="G-ABCDE12345")
    store = collect_store_inputs(
        ga4_client, website_domain="store.shopshop.la", meta_pixel_id="123456789012345"
    )
    assert store.container_name == "store.shopshop.la"
    assert store.ga4_measurement_id == "G-ABCDE12345"
    assert store.meta_pixel_id == "123456789012345"
    assert ga4_client.requested_domains == ["store.shopshop.la"]


def test_the_domain_is_what_ga4_is_asked_to_create_a_property_for():
    """The website domain doubles as both the container name and the GA4 name."""
    ga4_client = FakeGa4Client()
    store = collect_store_inputs(
        ga4_client, website_domain="other-store.shopshop.la", meta_pixel_id="123456789012345"
    )
    assert ga4_client.requested_domains == ["other-store.shopshop.la"]
    assert store.container_name == "other-store.shopshop.la"


def test_a_dry_run_never_calls_ga4_and_uses_a_placeholder_id():
    store = collect_store_inputs(
        None, website_domain="store.shopshop.la", meta_pixel_id="123456789012345"
    )
    assert store.ga4_measurement_id == DRY_RUN_GA4_MEASUREMENT_ID


def test_missing_values_are_prompted_for_and_revalidated_on_error():
    answers = iter(["not a domain", "store.shopshop.la", "too-short", "123456789012345"])
    messages = []
    store = collect_store_inputs(
        FakeGa4Client(),
        prompt=lambda _label: next(answers),
    )
    # print() calls inside collect_store_inputs go to stdout, not captured here;
    # the real assertion is that it recovered from two bad answers and finished.
    assert store.container_name == "store.shopshop.la"
    assert store.meta_pixel_id == "123456789012345"
    del messages


def test_a_bad_supplied_domain_raises_immediately_without_prompting():
    from gtm_provisioner.errors import ValidationError

    def explode(_label):
        raise AssertionError("should not prompt when a value was supplied")

    with pytest.raises(ValidationError):
        collect_store_inputs(
            FakeGa4Client(), website_domain="not a domain", prompt=explode
        )
