"""Parsing and validating gtm.share_with."""

import pytest

from gtm_provisioner.config import (
    DEFAULT_SCOPES,
    MANAGE_USERS_SCOPE,
    parse_share_with,
)
from gtm_provisioner.errors import ConfigError


def test_nothing_configured_means_nobody():
    assert parse_share_with(None) == ()
    assert parse_share_with([]) == ()


def test_a_plain_email_defaults_to_publish_on_the_container_only():
    assert parse_share_with(["me@bizgital.com"]) == (("me@bizgital.com", "publish", "noAccess"),)


def test_a_mapping_can_choose_the_level():
    people = parse_share_with(
        [{"email": "a@example.com", "permission": "Edit"}, {"email": "b@example.com"}]
    )
    assert people == (
        ("a@example.com", "edit", "noAccess"),
        ("b@example.com", "publish", "noAccess"),
    )


def test_account_access_can_be_set_to_match_the_service_account():
    people = parse_share_with([{"email": "a@example.com", "account_access": "Admin"}])
    assert people == (("a@example.com", "publish", "admin"),)


def test_an_unknown_account_access_is_rejected():
    with pytest.raises(ConfigError, match="account_access"):
        parse_share_with([{"email": "a@example.com", "account_access": "owner"}])


@pytest.mark.parametrize(
    "bad",
    [
        "not-an-email",
        {"email": "a@example.com", "permission": "owner"},
        {"permission": "edit"},
        42,
    ],
)
def test_bad_entries_are_rejected(bad):
    with pytest.raises(ConfigError):
        parse_share_with([bad])


def test_a_non_list_is_rejected():
    with pytest.raises(ConfigError):
        parse_share_with("me@example.com")


def test_the_same_email_twice_is_rejected_case_insensitively():
    with pytest.raises(ConfigError, match="more than once"):
        parse_share_with(["Me@example.com", {"email": "me@example.com", "permission": "edit"}])


def test_the_user_management_scope_is_not_requested_by_default():
    assert MANAGE_USERS_SCOPE not in DEFAULT_SCOPES
