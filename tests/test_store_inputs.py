"""Collecting operator input and resolving both API-created IDs from it."""

import pytest

from gtm_provisioner.store_inputs import (
    DRY_RUN_GA4_MEASUREMENT_ID,
    DRY_RUN_META_PIXEL_ID,
    collect_store_inputs,
)


class FakeGa4Client:
    """Stands in for Ga4Client, recording the domain it was asked to create."""

    def __init__(self, measurement_id="G-FAKE123456"):
        self.requested_domains = []
        self._measurement_id = measurement_id

    def create_property_and_stream(self, website_domain):
        self.requested_domains.append(website_domain)
        return self._measurement_id


class FakeMetaClient:
    """Stands in for MetaClient, recording what it was asked to create/rename."""

    def __init__(self, pixel_id="123456789012345"):
        self.requested_names = []
        self.renamed = []
        self._pixel_id = pixel_id

    def create_pixel(self, name):
        self.requested_names.append(name)
        return self._pixel_id

    def rename_pixel(self, pixel_id, name):
        self.renamed.append((pixel_id, name))


def test_supplied_values_are_validated_and_used_as_is():
    ga4_client = FakeGa4Client(measurement_id="G-ABCDE12345")
    meta_client = FakeMetaClient(pixel_id="123456789012345")
    store = collect_store_inputs(
        ga4_client,
        meta_client,
        store_name="ShopShop Pigeon",
        website_domain="store.shopshop.la",
    )
    assert store.container_name == "store.shopshop.la"
    assert store.ga4_measurement_id == "G-ABCDE12345"
    assert store.meta_pixel_id == "123456789012345"
    assert ga4_client.requested_domains == ["store.shopshop.la"]


def test_the_domain_is_what_ga4_is_asked_to_create_a_property_for():
    """The website domain doubles as both the container name and the GA4 name."""
    ga4_client = FakeGa4Client()
    store = collect_store_inputs(
        ga4_client,
        FakeMetaClient(),
        store_name="ShopShop Pigeon",
        website_domain="other-store.shopshop.la",
    )
    assert ga4_client.requested_domains == ["other-store.shopshop.la"]
    assert store.container_name == "other-store.shopshop.la"


def test_the_store_name_becomes_the_pixel_name_with_a_dataset_suffix():
    meta_client = FakeMetaClient()
    collect_store_inputs(
        FakeGa4Client(),
        meta_client,
        store_name="ShopShop Pigeon",
        website_domain="store.shopshop.la",
    )
    assert meta_client.requested_names == ["ShopShop Pigeon - Dataset"]


def test_a_dry_run_never_calls_ga4_or_meta_and_uses_placeholder_ids():
    store = collect_store_inputs(
        None, None, store_name="ShopShop Pigeon", website_domain="store.shopshop.la"
    )
    assert store.ga4_measurement_id == DRY_RUN_GA4_MEASUREMENT_ID
    assert store.meta_pixel_id == DRY_RUN_META_PIXEL_ID


def test_missing_values_are_prompted_for_and_revalidated_on_error():
    answers = iter(["", "ShopShop Pigeon", "not a domain", "store.shopshop.la"])
    store = collect_store_inputs(
        FakeGa4Client(),
        FakeMetaClient(),
        prompt=lambda _label: next(answers),
    )
    assert store.container_name == "store.shopshop.la"


def test_a_bad_supplied_domain_raises_immediately_without_prompting():
    from gtm_provisioner.errors import ValidationError

    def explode(_label):
        raise AssertionError("should not prompt when a value was supplied")

    with pytest.raises(ValidationError):
        collect_store_inputs(
            FakeGa4Client(),
            FakeMetaClient(),
            store_name="ShopShop Pigeon",
            website_domain="not a domain",
            prompt=explode,
        )


def test_reusing_a_pixel_renames_it_instead_of_creating_a_new_one():
    meta_client = FakeMetaClient()
    store = collect_store_inputs(
        FakeGa4Client(),
        meta_client,
        store_name="ShopShop Pigeon",
        website_domain="store.shopshop.la",
        meta_pixel_id="123456789012345",
    )
    assert store.meta_pixel_id == "123456789012345"
    assert meta_client.requested_names == []
    assert meta_client.renamed == [("123456789012345", "ShopShop Pigeon - Dataset")]


def test_a_malformed_reused_pixel_id_raises_immediately_without_renaming():
    from gtm_provisioner.errors import ValidationError

    meta_client = FakeMetaClient()
    with pytest.raises(ValidationError):
        collect_store_inputs(
            FakeGa4Client(),
            meta_client,
            store_name="ShopShop Pigeon",
            website_domain="store.shopshop.la",
            meta_pixel_id="not-a-real-id",
        )
    assert meta_client.renamed == []


def test_a_dry_run_with_a_reused_pixel_id_validates_but_never_calls_meta():
    """meta_client is None during a dry run; if the code tried to call
    rename_pixel on it anyway this would raise AttributeError instead of
    returning cleanly."""
    store = collect_store_inputs(
        None,
        None,
        store_name="ShopShop Pigeon",
        website_domain="store.shopshop.la",
        meta_pixel_id="123456789012345",
    )
    assert store.meta_pixel_id == "123456789012345"
