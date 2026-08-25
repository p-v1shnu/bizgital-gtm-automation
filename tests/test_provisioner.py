"""End-to-end coverage of the seven steps against a fake GTM API."""

import json

import pytest

from gtm_provisioner.errors import ProvisioningError
from gtm_provisioner.provisioner import Provisioner
from gtm_provisioner.store_inputs import StoreInputs
from gtm_provisioner.template import load_template

from .conftest import TEMPLATE_EXPORT

STORE = StoreInputs(
    container_name="BRAND-A | Web",
    ga4_measurement_id="G-NEWNEWNEW",
    meta_pixel_id="123456789012345",
)


@pytest.fixture
def result(config, fake_client, template_path):
    template = load_template(template_path)
    provisioner = Provisioner(config, fake_client, template, log=lambda *_: None)
    return provisioner.run(STORE)


def test_returns_the_public_container_id(result):
    assert result.public_id == "GTM-NEW1234"


def test_entity_counts_match_the_template(result):
    assert result.counts_match
    assert result.created_counts["tag"] == 2
    assert result.created_counts["trigger"] == 2
    assert result.created_counts["variable"] == 2
    assert result.created_counts["builtInVariable"] == 2


def test_every_tag_points_at_a_trigger_that_exists_in_the_new_container(
    result, fake_client
):
    """The acceptance criterion the PRD calls out as expensive to get wrong."""
    new_trigger_ids = {trigger["triggerId"] for trigger in fake_client.created["trigger"]}
    template_trigger_ids = {"41", "42"}

    for tag in fake_client.created["tag"]:
        for field in ("firingTriggerId", "blockingTriggerId"):
            for trigger_id in tag.get(field) or []:
                assert trigger_id not in template_trigger_ids, (
                    f"tag {tag['name']!r} kept the template's {field}"
                )
                assert trigger_id in new_trigger_ids or trigger_id == "2147479553"


def test_named_tag_wiring_is_preserved(fake_client, result):
    all_pages = next(t for t in fake_client.created["trigger"] if t["name"] == "All Pages")
    purchase = next(t for t in fake_client.created["trigger"] if t["name"] == "Purchase")

    ga4 = fake_client.tag_named("GA4 Configuration")
    assert ga4["firingTriggerId"] == [all_pages["triggerId"]]

    pixel = fake_client.tag_named("Meta Pixel Base")
    assert pixel["firingTriggerId"] == ["2147479553"]
    assert pixel["blockingTriggerId"] == [purchase["triggerId"]]


def test_store_ids_are_applied_at_creation_time(fake_client, result):
    ga4 = fake_client.variable_named("GA4 Measurement ID")
    pixel = fake_client.variable_named("Meta Pixel ID")
    assert ga4["parameter"][0]["value"] == "G-NEWNEWNEW"
    assert pixel["parameter"][0]["value"] == "123456789012345"


def test_custom_template_type_is_rebuilt(fake_client, result):
    created_template = fake_client.created["customTemplate"][0]
    pixel = fake_client.tag_named("Meta Pixel Base")
    assert pixel["type"] == f"cvt_888_{created_template['templateId']}"


def test_folders_are_recreated_and_referenced(fake_client, result):
    folder_id = fake_client.created["folder"][0]["folderId"]
    assert fake_client.tag_named("GA4 Configuration")["parentFolderId"] == folder_id


def test_no_server_assigned_field_is_sent_back(fake_client, result):
    for kind, entities in fake_client.created.items():
        for entity in entities:
            for field in ("accountId", "containerId", "fingerprint"):
                assert field not in entity, f"{kind} {entity.get('name')!r} kept {field}"


def test_the_version_is_published(fake_client, result):
    assert result.version_id == "3"
    assert fake_client.published_paths == [
        "accounts/111/containers/888/versions/3"
    ]


def test_a_failure_reports_the_orphaned_container(config, fake_client, template_path):
    def explode(workspace_path, body):
        raise ProvisioningError("simulated quota failure")

    fake_client.create_tag = explode
    template = load_template(template_path)
    provisioner = Provisioner(config, fake_client, template, log=lambda *_: None)

    with pytest.raises(ProvisioningError) as excinfo:
        provisioner.run(STORE)

    error = excinfo.value
    assert error.container_public_id == "GTM-NEW1234"
    assert error.step == "5. create tags"
    assert error.entity == "GA4 Configuration"


def test_a_compiler_error_prevents_publishing(config, fake_client, template_path):
    fake_client.create_version = lambda *args, **kwargs: {"compilerError": True}
    template = load_template(template_path)
    provisioner = Provisioner(config, fake_client, template, log=lambda *_: None)

    with pytest.raises(ProvisioningError, match="compiler error"):
        provisioner.run(STORE)
    assert fake_client.published_paths == []


def test_unsupported_entity_kinds_are_reported(config, fake_client, tmp_path):
    export = json.loads(json.dumps(TEMPLATE_EXPORT))
    export["containerVersion"]["zone"] = [{"zoneId": "1", "name": "Zone A"}]
    path = tmp_path / "with-zone.json"
    path.write_text(json.dumps(export), encoding="utf-8")

    messages = []
    provisioner = Provisioner(
        config, fake_client, load_template(str(path)), log=messages.append
    )
    provisioner.run(STORE)
    assert any("zone x1" in message for message in messages)
