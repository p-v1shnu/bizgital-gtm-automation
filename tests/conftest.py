"""Shared fixtures: a miniature golden container and a fake GTM API."""

import itertools
import json

import pytest

from gtm_provisioner.config import Config

# Template trigger IDs are deliberately unlike the IDs the fake API hands out,
# so a test fails loudly if remapping is skipped.
TEMPLATE_EXPORT = {
    "exportFormatVersion": 2,
    "containerVersion": {
        "accountId": "111",
        "containerId": "222",
        "fingerprint": "1600000000000",
        "builtInVariable": [
            {"accountId": "111", "containerId": "222", "type": "PAGE_URL", "name": "Page URL"},
            {"accountId": "111", "containerId": "222", "type": "pageHostname", "name": "Page Hostname"},
        ],
        "folder": [
            {
                "accountId": "111",
                "containerId": "222",
                "folderId": "9",
                "name": "Analytics",
                "fingerprint": "1",
            }
        ],
        "customTemplate": [
            {
                "accountId": "111",
                "containerId": "222",
                "templateId": "77",
                "name": "Meta Pixel Template",
                "templateData": "___INFO___",
                "fingerprint": "1",
            }
        ],
        "variable": [
            {
                "accountId": "111",
                "containerId": "222",
                "variableId": "31",
                "name": "GA4 Measurement ID",
                "type": "c",
                "parentFolderId": "9",
                "parameter": [{"type": "template", "key": "value", "value": "G-OLDOLDOLD"}],
                "fingerprint": "1",
            },
            {
                "accountId": "111",
                "containerId": "222",
                "variableId": "32",
                "name": "Meta Pixel ID",
                "type": "c",
                "parameter": [{"type": "template", "key": "value", "value": "999999999999999"}],
                "fingerprint": "1",
            },
        ],
        "trigger": [
            {
                "accountId": "111",
                "containerId": "222",
                "triggerId": "41",
                "name": "All Pages",
                "type": "pageview",
                "parentFolderId": "9",
                "fingerprint": "1",
            },
            {
                "accountId": "111",
                "containerId": "222",
                "triggerId": "42",
                "name": "Purchase",
                "type": "customEvent",
                "fingerprint": "1",
            },
        ],
        "tag": [
            {
                "accountId": "111",
                "containerId": "222",
                "tagId": "51",
                "name": "GA4 Configuration",
                "type": "gaawc",
                "firingTriggerId": ["41"],
                "parentFolderId": "9",
                "fingerprint": "1",
            },
            {
                "accountId": "111",
                "containerId": "222",
                "tagId": "52",
                "name": "Meta Pixel Base",
                "type": "cvt_222_77",
                "firingTriggerId": ["2147479553"],
                "blockingTriggerId": ["42"],
                "fingerprint": "1",
            },
        ],
    },
}


@pytest.fixture
def template_path(tmp_path):
    path = tmp_path / "golden-container.json"
    path.write_text(json.dumps(TEMPLATE_EXPORT), encoding="utf-8")
    return str(path)


@pytest.fixture
def config(tmp_path):
    return Config(
        account_id="111",
        usage_context="web",
        service_account_key_path=str(tmp_path / "key.json"),
        template_path=str(tmp_path / "golden-container.json"),
        ga4_variable_name="GA4 Measurement ID",
        meta_pixel_variable_name="Meta Pixel ID",
        ga4_account_id="216060784",
        meta_ad_account_id="1451413912465476",
        meta_access_token_path=str(tmp_path / "meta-access-token.txt"),
        request_interval_seconds=0.0,
        warn_on_duplicate_name=False,
    )


class FakeGtmClient:
    """Stands in for GtmClient, handing out IDs unlike the template's."""

    NEW_CONTAINER_ID = "888"

    def __init__(self):
        self._ids = itertools.count(start=1000)
        self.created = {"folder": [], "customTemplate": [], "variable": [], "trigger": [], "tag": []}
        self.builtin_variable_types = []
        self.published_paths = []
        self.container = None

    def _next_id(self):
        return str(next(self._ids))

    def list_containers(self):
        return []

    def create_container(self, name, usage_context):
        self.container = {
            "path": f"accounts/111/containers/{self.NEW_CONTAINER_ID}",
            "accountId": "111",
            "containerId": self.NEW_CONTAINER_ID,
            "name": name,
            "publicId": "GTM-NEW1234",
            "usageContext": [usage_context],
        }
        return self.container

    def get_default_workspace(self, container_path):
        return {"path": f"{container_path}/workspaces/1", "name": "Default Workspace"}

    def enable_builtin_variables(self, workspace_path, types):
        self.builtin_variable_types = list(types)
        return {"builtInVariable": [{"type": t} for t in types]}

    def _create(self, kind, body, id_field):
        stored = dict(body)
        stored[id_field] = self._next_id()
        self.created[kind].append(stored)
        return stored

    def create_folder(self, workspace_path, body):
        return self._create("folder", body, "folderId")

    def create_custom_template(self, workspace_path, body):
        return self._create("customTemplate", body, "templateId")

    def create_variable(self, workspace_path, body):
        return self._create("variable", body, "variableId")

    def create_trigger(self, workspace_path, body):
        return self._create("trigger", body, "triggerId")

    def create_tag(self, workspace_path, body):
        return self._create("tag", body, "tagId")

    def list_variables(self, workspace_path):
        return self.created["variable"]

    def create_version(self, workspace_path, name, notes):
        return {
            "compilerError": False,
            "containerVersion": {
                "path": f"{self.container['path']}/versions/3",
                "containerVersionId": "3",
                "name": name,
                "notes": notes,
            },
        }

    def publish_version(self, version_path):
        self.published_paths.append(version_path)
        return {"containerVersion": {"path": version_path}}

    def tag_named(self, name):
        return next(tag for tag in self.created["tag"] if tag["name"] == name)

    def variable_named(self, name):
        return next(var for var in self.created["variable"] if var["name"] == name)


@pytest.fixture
def fake_client():
    return FakeGtmClient()
