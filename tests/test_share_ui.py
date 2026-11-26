"""The page's editable, remembered list of who gets access to new containers."""

import json
import threading
import urllib.error
import urllib.request

import pytest

import provision_gtm
from gtm_provisioner import webapp
from gtm_provisioner.config import (
    MANAGE_USERS_SCOPE,
    parse_share_flag,
    parse_share_with,
    with_share_with,
)
from gtm_provisioner.errors import ConfigError

from .test_webapp import SUCCESS_SCRIPT, builder_for, call, config_path, wait_for  # noqa: F401

PERSON = {"email": "me@example.com", "permission": "publish", "account_access": "admin"}


# -- validating the list ------------------------------------------------------


def test_defaults_are_filled_in_and_values_normalised():
    people, error = webapp.normalise_share_list(
        [{"email": " Me@Example.com "}, {"email": "b@example.com", "permission": "EDIT"}]
    )
    assert error is None
    assert people == [
        {"email": "Me@Example.com", "permission": "publish", "account_access": "noAccess"},
        {"email": "b@example.com", "permission": "edit", "account_access": "noAccess"},
    ]


@pytest.mark.parametrize(
    "raw, expected",
    [
        ([{"email": "nope"}], "อีเมลไม่ถูกต้อง"),
        ([{"email": "a@example.com"}, {"email": "A@example.com"}], "ซ้ำ"),
        ([{"email": "a@example.com", "permission": "owner"}], "ระดับสิทธิ์ใน container"),
        ([{"email": "a@example.com", "account_access": "owner"}], "ระดับสิทธิ์ของ Account"),
        ("a@example.com", "รูปแบบ"),
        (["a@example.com"], "รูปแบบ"),
    ],
)
def test_bad_lists_get_a_thai_message(raw, expected):
    people, error = webapp.normalise_share_list(raw)
    assert people == []
    assert expected in error


def test_an_empty_list_is_valid_and_means_nobody():
    assert webapp.normalise_share_list([]) == ([], None)


# -- building the command ----------------------------------------------------


def test_each_person_becomes_a_share_with_flag():
    command = webapp.build_command(
        {"store_name": "S", "domain": "a.example.com", "share_with": [PERSON]},
        python="py",
        script="s.py",
    )
    assert "--share-with=me@example.com:publish:admin" in command
    assert "--no-share" not in command


def test_an_empty_list_overrides_the_config_with_no_share():
    command = webapp.build_command(
        {"store_name": "S", "domain": "a.example.com", "share_with": []},
        python="py",
        script="s.py",
    )
    assert "--no-share" in command


def test_an_unspecified_list_leaves_the_config_in_charge():
    command = webapp.build_command(
        {"store_name": "S", "domain": "a.example.com"}, python="py", script="s.py"
    )
    assert "--no-share" not in command
    assert not any(part.startswith("--share-with") for part in command)


# -- the command line the page drives ---------------------------------------


def test_share_flag_parsing():
    assert parse_share_flag("a@example.com") == {"email": "a@example.com"}
    assert parse_share_flag("a@example.com:edit") == {"email": "a@example.com", "permission": "edit"}
    assert parse_share_flag("a@example.com:publish:admin") == {
        "email": "a@example.com",
        "permission": "publish",
        "account_access": "admin",
    }
    with pytest.raises(ConfigError):
        parse_share_flag("a@example.com:publish:admin:extra")


def test_the_flags_replace_the_config_and_request_the_scope_only_when_needed(config):
    people = parse_share_with([parse_share_flag("a@example.com:publish:admin")])
    granted = with_share_with(config, people)
    assert granted.gtm_share_with == (("a@example.com", "publish", "admin"),)
    assert MANAGE_USERS_SCOPE in granted.scopes

    nobody = with_share_with(granted, ())
    assert nobody.gtm_share_with == ()
    assert MANAGE_USERS_SCOPE not in nobody.scopes


def test_a_bad_share_with_flag_stops_the_run_before_anything_happens(config_path):  # noqa: F811
    code = provision_gtm.main(
        ["--config", config_path, "--dry-run", "--store-name", "S", "--domain", "a.example.com",
         "--share-with", "not-an-email"]
    )
    assert code == provision_gtm.EXIT_BAD_SETUP


# -- the page's checks and saved settings -----------------------------------


def test_check_validates_the_list_the_page_sends(config_path):  # noqa: F811
    bad = webapp.check_inputs(
        {"store_name": "S", "domain": "a.example.com", "dry_run": True,
         "share_with": [{"email": "nope"}]},
        config_path,
    )
    assert not bad["ok"]
    assert "อีเมลไม่ถูกต้อง" in bad["errors"]["share_with"]

    good = webapp.check_inputs(
        {"store_name": "S", "domain": "a.example.com", "dry_run": True, "share_with": [PERSON]},
        config_path,
    )
    assert good["ok"]
    assert good["share_with"] == [PERSON]


@pytest.fixture
def server(tmp_path, config_path):  # noqa: F811
    seen = []

    def builder(params):
        seen.append(params)
        return builder_for(SUCCESS_SCRIPT, tmp_path)(params)

    manager = webapp.JobManager(builder, history_path=tmp_path / "runs.jsonl")
    httpd, _ = webapp.create_server(
        0, manager, config_path, list_container_names=lambda: [],
        settings_path=tmp_path / "ui_settings.json",
    )
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", manager, seen, tmp_path / "ui_settings.json"
    httpd.shutdown()
    httpd.server_close()


def test_settings_start_from_the_config_then_remember_what_was_saved(server):
    base, _, _, settings_file = server
    status, body = call(base, "/api/settings")
    assert status == 200 and json.loads(body)["source"] == "config"

    status, body = call(base, "/api/settings", {"share_with": [PERSON]})
    assert status == 200
    assert json.loads(settings_file.read_text(encoding="utf-8"))["share_with"] == [PERSON]

    status, body = call(base, "/api/settings")
    assert json.loads(body) == {"share_with": [PERSON], "source": "saved"}


def test_a_saved_empty_list_is_remembered_as_nobody(server):
    base, *_ = server
    call(base, "/api/settings", {"share_with": [PERSON]})
    call(base, "/api/settings", {"share_with": []})
    status, body = call(base, "/api/settings")
    assert json.loads(body) == {"share_with": [], "source": "saved"}


def test_an_invalid_list_is_refused_and_not_saved(server):
    base, _, _, settings_file = server
    status, body = call(base, "/api/settings", {"share_with": [{"email": "nope"}]})
    assert status == 422
    assert "อีเมลไม่ถูกต้อง" in json.loads(body)["error"]
    assert not settings_file.exists()


def test_a_run_uses_the_list_the_page_sent(server):
    base, manager, seen, _ = server
    status, body = call(
        base, "/api/run",
        {"store_name": "S", "domain": "a.example.com", "share_with": [PERSON]},
    )
    assert status == 202
    wait_for(manager.get(json.loads(body)["job_id"]))
    assert seen[0]["share_with"] == [PERSON]


def test_settings_survive_a_restart_of_the_server(tmp_path, config_path):  # noqa: F811
    path = tmp_path / "ui_settings.json"
    webapp.write_saved_share(path, [PERSON])
    assert webapp.read_saved_share(path) == [PERSON]


def test_a_damaged_settings_file_is_ignored_not_fatal(tmp_path):
    path = tmp_path / "ui_settings.json"
    path.write_text("{not json", encoding="utf-8")
    assert webapp.read_saved_share(path) is None
