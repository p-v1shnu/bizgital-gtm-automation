"""Granting the configured people access to each container the script creates."""

import dataclasses

from gtm_provisioner.provisioner import Provisioner
from gtm_provisioner.store_inputs import StoreInputs
from gtm_provisioner.template import load_template

STORE = StoreInputs(
    container_name="BRAND-A | Web",
    ga4_measurement_id="G-NEWNEWNEW",
    meta_pixel_id="123456789012345",
)

CONTAINER_ID = "888"  # FakeGtmClient.NEW_CONTAINER_ID


def run_with_access(config, fake_client, template_path, people):
    """`people` entries are (email, permission) or (email, permission, account_access)."""
    people = [tuple(p) + ("noAccess",) * (3 - len(p)) for p in people]
    logs = []
    provisioner = Provisioner(
        dataclasses.replace(config, gtm_share_with=tuple(people)),
        fake_client,
        load_template(template_path),
        log=logs.append,
    )
    return provisioner.run(STORE), logs


def test_a_new_person_gets_container_level_access_only(config, fake_client, template_path):
    result, logs = run_with_access(
        config, fake_client, template_path, [("me@example.com", "publish")]
    )

    record = fake_client.user_permissions[0]
    assert record["emailAddress"] == "me@example.com"
    assert record["accountAccess"] == {"permission": "noAccess"}  # not account-wide
    assert record["containerAccess"] == [{"containerId": CONTAINER_ID, "permission": "publish"}]
    assert any("access granted: me@example.com -> publish" in line for line in logs)
    assert result.counts_match


def test_an_existing_person_keeps_their_other_access(config, fake_client, template_path):
    fake_client.user_permissions = [
        {
            "path": "accounts/111/user_permissions/7",
            "emailAddress": "Me@Example.com",
            "accountAccess": {"permission": "admin"},
            "containerAccess": [{"containerId": "555", "permission": "edit"}],
        }
    ]
    run_with_access(config, fake_client, template_path, [("me@example.com", "publish")])

    assert len(fake_client.user_permissions) == 1
    record = fake_client.user_permissions[0]
    assert record["accountAccess"] == {"permission": "admin"}
    assert {"containerId": "555", "permission": "edit"} in record["containerAccess"]
    assert {"containerId": CONTAINER_ID, "permission": "publish"} in record["containerAccess"]
    assert fake_client.updated_user_permission_paths == ["accounts/111/user_permissions/7"]


def test_someone_who_already_has_the_wanted_level_is_skipped(config, fake_client, template_path):
    fake_client.user_permissions = [
        {
            "path": "accounts/111/user_permissions/7",
            "emailAddress": "me@example.com",
            "accountAccess": {"permission": "noAccess"},
            "containerAccess": [{"containerId": CONTAINER_ID, "permission": "publish"}],
        }
    ]
    _, logs = run_with_access(config, fake_client, template_path, [("me@example.com", "publish")])

    assert fake_client.updated_user_permission_paths == []
    assert any("access already set: me@example.com -> publish; skipped" in l for l in logs)


def test_one_rejected_email_does_not_fail_the_run_or_block_the_others(
    config, fake_client, template_path
):
    fake_client.reject_emails = {"nobody@example.com"}
    result, logs = run_with_access(
        config,
        fake_client,
        template_path,
        [("nobody@example.com", "publish"), ("me@example.com", "edit")],
    )

    assert result.public_id == "GTM-NEW1234"  # still published and returned
    assert [r["emailAddress"] for r in fake_client.user_permissions] == ["me@example.com"]
    assert any("access NOT granted: nobody@example.com -> publish" in l for l in logs)
    assert any("access granted: me@example.com -> edit" in l for l in logs)


def test_if_permissions_cannot_be_listed_everyone_is_reported_and_the_run_survives(
    config, fake_client, template_path
):
    fake_client.fail_listing_permissions = True
    result, logs = run_with_access(
        config,
        fake_client,
        template_path,
        [("a@example.com", "publish"), ("b@example.com", "publish")],
    )
    assert result.public_id == "GTM-NEW1234"
    assert sum("access NOT granted" in l for l in logs) == 2


def test_a_new_person_can_be_made_account_admin_like_the_service_account(
    config, fake_client, template_path
):
    _, logs = run_with_access(
        config, fake_client, template_path, [("me@example.com", "publish", "admin")]
    )

    record = fake_client.user_permissions[0]
    assert record["accountAccess"] == {"permission": "admin"}
    assert record["containerAccess"] == [{"containerId": CONTAINER_ID, "permission": "publish"}]
    assert any("access granted: me@example.com -> publish + account admin" in l for l in logs)


def test_account_access_is_raised_but_never_lowered(config, fake_client, template_path):
    fake_client.user_permissions = [
        {
            "path": "accounts/111/user_permissions/1",
            "emailAddress": "viewer@example.com",
            "accountAccess": {"permission": "user"},
            "containerAccess": [],
        },
        {
            "path": "accounts/111/user_permissions/2",
            "emailAddress": "boss@example.com",
            "accountAccess": {"permission": "admin"},
            "containerAccess": [],
        },
    ]
    run_with_access(
        config,
        fake_client,
        template_path,
        [("viewer@example.com", "publish", "admin"), ("boss@example.com", "publish", "user")],
    )

    by_email = {r["emailAddress"]: r for r in fake_client.user_permissions}
    assert by_email["viewer@example.com"]["accountAccess"] == {"permission": "admin"}  # raised
    assert by_email["boss@example.com"]["accountAccess"] == {"permission": "admin"}  # kept


def test_an_admin_who_only_lacks_the_container_entry_gets_it_without_losing_admin(
    config, fake_client, template_path
):
    fake_client.user_permissions = [
        {
            "path": "accounts/111/user_permissions/2",
            "emailAddress": "boss@example.com",
            "accountAccess": {"permission": "admin"},
            "containerAccess": [],
        }
    ]
    _, logs = run_with_access(
        config, fake_client, template_path, [("boss@example.com", "publish", "admin")]
    )

    record = fake_client.user_permissions[0]
    assert record["accountAccess"] == {"permission": "admin"}
    assert record["containerAccess"] == [{"containerId": CONTAINER_ID, "permission": "publish"}]
    # account level did not change, so the log must not claim it did
    assert any("access granted: boss@example.com -> publish" in l for l in logs)
    assert not any("+ account" in l for l in logs)


def test_nothing_is_granted_when_share_with_is_empty(config, fake_client, template_path):
    _, logs = run_with_access(config, fake_client, template_path, [])
    assert fake_client.user_permissions == []
    assert not any("grant container access" in l for l in logs)
