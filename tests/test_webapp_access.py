"""The web UI's view of the "grant container access" step."""

import textwrap

from gtm_provisioner import webapp

from .test_webapp import SUCCESS_SCRIPT, builder_for, config_path, wait_for  # noqa: F401

ACCESS_SCRIPT = textwrap.dedent(
    """
    print("[7. create version and publish]")
    print("  GTM container ID: GTM-ABC123")
    print("[8. grant container access] 3 to grant")
    print("    access granted: me@example.com -> publish")
    print("    access already set: other@example.com -> publish; skipped")
    print("  ! access NOT granted: bad@example.com -> publish: creating user permission failed with HTTP 400: nope")
    """
)


def test_access_lines_become_a_per_person_result(tmp_path):
    manager = webapp.JobManager(builder_for(ACCESS_SCRIPT, tmp_path), history_path=tmp_path / "h")
    job = wait_for(manager.start({"store_name": "S", "domain": "d.example.com"}))
    snapshot = job.snapshot()

    assert snapshot["state"] == "done"
    assert snapshot["steps"]["access"] == "done"
    assert snapshot["steps"]["publish"] == "done"
    assert [(a["email"], a["status"]) for a in snapshot["result"]["access"]] == [
        ("me@example.com", "granted"),
        ("other@example.com", "already"),
        ("bad@example.com", "failed"),
    ]
    assert snapshot["result"]["access"][2]["reason"].startswith("creating user permission failed")


def test_access_step_is_skipped_when_nobody_is_configured(tmp_path):
    manager = webapp.JobManager(builder_for(SUCCESS_SCRIPT, tmp_path), history_path=tmp_path / "h")
    job = wait_for(manager.start({"store_name": "S", "domain": "d.example.com"}))
    assert job.snapshot()["steps"]["access"] == "skipped"


def test_check_reports_who_will_be_given_access(config_path, tmp_path):  # noqa: F811
    text = open(config_path, encoding="utf-8").read().replace(
        'gtm: {account_id: "1", usage_context: "web"}',
        'gtm: {account_id: "1", usage_context: "web", share_with: ["me@example.com", '
        '{email: "ai@example.com", permission: "edit"}]}',
    )
    path = tmp_path / "with_share.yaml"
    path.write_text(text, encoding="utf-8")

    result = webapp.check_inputs(
        {"store_name": "S", "domain": "a.example.com", "dry_run": True}, str(path)
    )
    assert result["share_with"] == [
        {"email": "me@example.com", "permission": "publish", "account_access": "noAccess"},
        {"email": "ai@example.com", "permission": "edit", "account_access": "noAccess"},
    ]


def test_account_admin_in_the_log_is_carried_into_the_result(tmp_path):
    script = textwrap.dedent(
        """
        print("[8. grant container access] 1 to grant")
        print("    access granted: me@example.com -> publish + account admin")
        """
    )
    manager = webapp.JobManager(builder_for(script, tmp_path), history_path=tmp_path / "h")
    job = wait_for(manager.start({"store_name": "S", "domain": "d.example.com"}))
    entry = job.snapshot()["result"]["access"][0]
    assert (entry["permission"], entry["account_access"]) == ("publish", "admin")
