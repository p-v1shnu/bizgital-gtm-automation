import pytest

from gtm_provisioner.errors import ValidationError
from gtm_provisioner.validators import (
    validate_ga4_measurement_id,
    validate_meta_pixel_id,
    validate_store_name,
    validate_website_domain,
)


def test_store_name_is_trimmed():
    assert validate_store_name("  ShopShop Pigeon  ") == "ShopShop Pigeon"


@pytest.mark.parametrize("value", ["", "   ", None, "x" * 101])
def test_store_name_rejects_empty_and_overlong(value):
    with pytest.raises(ValidationError):
        validate_store_name(value)


def test_website_domain_is_trimmed():
    assert validate_website_domain("  store.shopshop.la  ") == "store.shopshop.la"


@pytest.mark.parametrize(
    "value, expected",
    [
        ("https://store.shopshop.la", "store.shopshop.la"),
        ("http://store.shopshop.la/", "store.shopshop.la"),
        ("HTTPS://Store.Shopshop.La", "Store.Shopshop.La"),
    ],
)
def test_website_domain_strips_scheme_and_trailing_slash(value, expected):
    assert validate_website_domain(value) == expected


@pytest.mark.parametrize(
    "value",
    ["", "   ", None, "x" * 101, "no-dot-at-all", "-leading-hyphen.com", "trailing-.com"],
)
def test_website_domain_rejects_empty_overlong_and_malformed(value):
    with pytest.raises(ValidationError):
        validate_website_domain(value)


def test_ga4_id_is_upper_cased():
    assert validate_ga4_measurement_id(" g-abcde12345 ") == "G-ABCDE12345"


@pytest.mark.parametrize(
    "value",
    ["UA-12345-1", "GT-ABCDE12345", "G-SHORT", "G-TOOLONG12345", "", "12345"],
)
def test_ga4_id_rejects_non_ga4_ids(value):
    with pytest.raises(ValidationError):
        validate_ga4_measurement_id(value)


def test_ga4_error_names_the_g_prefix_rule():
    with pytest.raises(ValidationError, match="must start with 'G-'"):
        validate_ga4_measurement_id("UA-12345-1")


@pytest.mark.parametrize("value", ["123456789012345", "1234567890123456"])
def test_pixel_id_accepts_15_and_16_digits(value):
    assert validate_meta_pixel_id(value) == value


@pytest.mark.parametrize("value", ["12345", "12345678901234a", "", None])
def test_pixel_id_rejects_malformed_values(value):
    with pytest.raises(ValidationError):
        validate_meta_pixel_id(value)
