import json
import sys
import textwrap
import threading
import time
import urllib.error
import urllib.request

import pytest

from gtm_provisioner import webapp

SUCCESS_SCRIPT = textwrap.dedent(
    """
    import sys
    print("Template: x.json")
    print("  tag                  14")
    print("  trigger               7")
    print("  template audit: ok")
    print()
    print("GA4 property created, Measurement ID: G-ABCDEF1234")
    print("Meta pixel created, ID: 123456789012345")
    print("[1. create container] store.example.com")
    print("[2. enable built-in variables] 5 to enable")
    print("[3. create user-defined variables] 27 to create")
    print("[4. create triggers] 7 to create")
    print("[5. create tags] 14 to create")
    print("[6. verify store-specific IDs] reading")
    print("[7. create version and publish]")
    print("  GTM container ID: GTM-ABC123")
    """
)

FAIL_AFTER_CONTAINER_SCRIPT = textwrap.dedent(
    """
    import sys
    print("GA4 property created, Measurement ID: G-ABCDEF1234")
    print("Meta pixel created, ID: 123456789012345")
    print("[1. create container] store.example.com")
    print("[4. create triggers] 7 to create")
    print("Provisioning failed: boom", file=sys.stderr)
    print("    public ID: GTM-PART123", file=sys.stderr)
    sys.exit(1)
    """
)


def builder_for(script_text, tmp_path):
    script = tmp_path / "fake_script.py"
    script.write_text(script_text, encoding="utf-8")
    return lambda params: [sys.executable, str(script)]


def wait_for(job, timeout=10):
    deadline = time.time() + timeout
    while job.state == "running" and time.time() < deadline:
        time.sleep(0.02)
    return job


def test_build_command_uses_equals_form_so_dashes_are_not_flags():
    command = webapp.build_command(
        {"store_name": "--evil", "domain": "a.example.com", "dry_run": True,
         "meta_pixel_id": "123456789012345"},
        python="py", script="s.py",
    )
    assert "--store-name=--evil" in command
    assert "--yes" in command and "--dry-run" in command
    assert "--meta-pixel-id=123456789012345" in command


def test_build_command_omits_optional_flags():
    command = webapp.build_command(
        {"store_name": "S", "domain": "a.example.com"}, python="py", script="s.py"
    )
    assert "--dry-run" not in command
    assert not any(part.startswith("--meta-pixel-id") for part in command)


def test_successful_run_tracks_steps_and_result(tmp_path):
    manager = webapp.JobManager(
        builder_for(SUCCESS_SCRIPT, tmp_path), history_path=tmp_path / "runs.jsonl"
    )
    job = wait_for(manager.start({"store_name": "S", "domain": "d.example.com"}))

    snapshot = job.snapshot()
    assert snapshot["state"] == "done"
    assert snapshot["result"]["gtm_public_id"] == "GTM-ABC123"
    assert snapshot["result"]["ga4_measurement_id"] == "G-ABCDEF1234"
    assert snapshot["result"]["meta_pixel_id"] == "123456789012345"
    assert snapshot["template_counts"] == {"tag": 14, "trigger": 7}
    assert snapshot["steps"]["folders"] == "skipped"
    assert snapshot["steps"]["templates"] == "skipped"
    required = [k for k in webapp.STEP_ORDER if k not in webapp.OPTIONAL_STEPS]
    assert all(snapshot["steps"][k] == "done" for k in required)


def test_failed_run_after_container_keeps_ids_and_flags_partial(tmp_path):
    manager = webapp.JobManager(
        builder_for(FAIL_AFTER_CONTAINER_SCRIPT, tmp_path),
        history_path=tmp_path / "runs.jsonl",
    )
    job = wait_for(manager.start({"store_name": "S", "domain": "d.example.com"}))

    snapshot = job.snapshot()
    assert snapshot["state"] == "failed"
    assert snapshot["error"] == "boom"
    assert snapshot["partial_container"] == "GTM-PART123"
    assert snapshot["result"]["meta_pixel_id"] == "123456789012345"
    assert snapshot["steps"]["triggers"] == "failed"
    assert snapshot["steps"]["tags"] == "pending"


def test_history_is_written_for_real_runs_only(tmp_path):
    history = tmp_path / "runs.jsonl"
    manager = webapp.JobManager(builder_for(SUCCESS_SCRIPT, tmp_path), history_path=history)
    wait_for(manager.start({"store_name": "S", "domain": "d.example.com", "dry_run": True}))
    assert manager.history() == []

    wait_for(manager.start({"store_name": "S", "domain": "d.example.com"}))
    rows = manager.history()
    assert rows[0]["gtm_public_id"] == "GTM-ABC123"
    assert rows[0]["state"] == "done"


def test_second_run_is_refused_while_one_is_running(tmp_path):
    slow = "import time; time.sleep(1.5)"
    manager = webapp.JobManager(builder_for(slow, tmp_path), history_path=tmp_path / "h")
    first = manager.start({"store_name": "S", "domain": "d.example.com"})
    with pytest.raises(webapp.BusyError):
        manager.start({"store_name": "S", "domain": "d.example.com"})
    wait_for(first)


def test_unstartable_script_becomes_failed_job(tmp_path):
    manager = webapp.JobManager(
        lambda params: ["definitely-not-a-real-binary-xyz"], history_path=tmp_path / "h"
    )
    job = wait_for(manager.start({"store_name": "S", "domain": "d.example.com"}))
    assert job.state == "failed"
    assert "could not start" in job.error


# -- check_inputs --------------------------------------------------------


@pytest.fixture
def config_path(tmp_path):
    template = tmp_path / "t.json"
    template.write_text("{}", encoding="utf-8")
    key = tmp_path / "k.json"
    key.write_text("{}", encoding="utf-8")
    token = tmp_path / "meta.txt"
    token.write_text("x", encoding="utf-8")
    path = tmp_path / "config.yaml"
    path.write_text(
        textwrap.dedent(
            f"""
            gtm: {{account_id: "1", usage_context: "web"}}
            paths: {{service_account_key: "{key.as_posix()}", template: "{template.as_posix()}"}}
            variables: {{ga4_measurement_id: "A", meta_pixel_id: "B"}}
            ga4: {{account_id: "1", timezone: "Asia/Vientiane", currency_code: "USD", industry_category: "SHOPPING"}}
            meta: {{business_id: "1", ad_account_id: "1", access_token_path: "{token.as_posix()}"}}
            """
        ),
        encoding="utf-8",
    )
    return str(path)


def test_check_inputs_reports_field_errors(config_path):
    result = webapp.check_inputs(
        {"store_name": " ", "domain": "no-dot", "meta_pixel_id": "12"}, config_path
    )
    assert not result["ok"]
    assert set(result["errors"]) == {"store_name", "domain", "meta_pixel_id"}
    assert result["errors"]["store_name"] == "กรุณากรอกชื่อร้าน"
    assert "รูปแบบโดเมน" in result["errors"]["domain"]
    assert "15–16" in result["errors"]["meta_pixel_id"]


def test_check_inputs_normalises_domain_and_finds_duplicates(config_path):
    result = webapp.check_inputs(
        {"store_name": " Shop ", "domain": "https://Store.Example.com/"},
        config_path,
        list_container_names=lambda: [("Store.Example.com", "GTM-DUP1"), ("other.com", "GTM-X")],
    )
    assert result["values"]["domain"] == "Store.Example.com"
    assert result["values"]["store_name"] == "Shop"
    assert result["duplicates"] == ["GTM-DUP1"]


def test_check_inputs_missing_config_is_a_setup_problem(tmp_path):
    result = webapp.check_inputs(
        {"store_name": "S", "domain": "a.example.com"}, str(tmp_path / "missing.yaml")
    )
    assert not result["ok"]
    assert result["setup_problems"]


def test_setup_only_skips_duplicate_lookup(config_path):
    def explode():
        raise AssertionError("must not call the GTM API")

    result = webapp.check_inputs(
        {"store_name": "S", "domain": "a.example.com", "setup_only": True},
        config_path,
        list_container_names=explode,
    )
    assert result["ok"]


# -- HTTP layer ----------------------------------------------------------


@pytest.fixture
def server(tmp_path, config_path):
    manager = webapp.JobManager(
        builder_for(SUCCESS_SCRIPT, tmp_path), history_path=tmp_path / "runs.jsonl"
    )
    httpd, _ = webapp.create_server(
        0, manager, config_path, list_container_names=lambda: [("dup.example.com", "GTM-DUP1")]
    )
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", manager
    httpd.shutdown()
    httpd.server_close()


def call(base, path, body=None, headers=None):
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(base + path, data=data, headers=headers or {})
    if body is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def test_index_page_is_served(server):
    status, body = call(server[0], "/")
    assert status == 200
    assert "<html" in body.decode("utf-8")


def test_foreign_host_header_is_rejected(server):
    status, _ = call(server[0], "/", headers={"Host": "evil.example.com"})
    assert status == 403


def test_post_requires_json_content_type(server):
    request = urllib.request.Request(
        server[0] + "/api/check", data=b"x=1", headers={"Content-Type": "text/plain"}
    )
    with pytest.raises(urllib.error.HTTPError) as caught:
        urllib.request.urlopen(request, timeout=10)
    assert caught.value.code == 415


def test_run_refuses_duplicate_until_confirmed_then_completes(server):
    base, manager = server
    payload = {"store_name": "S", "domain": "dup.example.com"}

    status, body = call(base, "/api/run", payload)
    assert status == 409 and json.loads(body)["error"] == "duplicate"

    status, body = call(base, "/api/run", {**payload, "allow_duplicate": True})
    assert status == 202
    job = wait_for(manager.get(json.loads(body)["job_id"]))
    assert job.state == "done"

    status, body = call(base, f"/api/job/{job.id}?since=0")
    snapshot = json.loads(body)
    assert snapshot["result"]["gtm_public_id"] == "GTM-ABC123"
    status, body = call(base, f"/api/job/{job.id}?since={snapshot['next']}")
    assert json.loads(body)["lines"] == []


def test_run_rejects_invalid_input(server):
    status, body = call(server[0], "/api/run", {"store_name": "", "domain": "bad"})
    assert status == 422
    assert "store_name" in json.loads(body)["errors"]


def test_taken_port_moves_to_the_next_one(tmp_path):
    first, _ = webapp.create_server(0, webapp.JobManager(history_path=tmp_path / "h"))
    taken = first.server_address[1]
    try:
        second, _ = webapp.create_server(taken, webapp.JobManager(history_path=tmp_path / "h"))
        try:
            assert second.server_address[1] != taken
        finally:
            second.server_close()
    finally:
        first.server_close()


# -- pixel sharing step ------------------------------------------------------

SHARE_SCRIPT = textwrap.dedent(
    """
    print("GA4 property created, Measurement ID: G-ABCDEF1234")
    print("    pixel 123456789012345 renamed to 'S - Dataset'")
    print("    pixel 123456789012345 is already shared with ad account 1451413912465476; skipping")
    print("Meta pixel reused and renamed, ID: 123456789012345")
    print("[1. create container] x")
    """
)


def test_share_step_is_tracked_and_reports_when_it_was_skipped(tmp_path):
    manager = webapp.JobManager(
        builder_for(SHARE_SCRIPT, tmp_path), history_path=tmp_path / "h"
    )
    job = wait_for(manager.start({"store_name": "S", "domain": "d.example.com"}))
    snapshot = job.snapshot()
    assert snapshot["steps"]["meta"] == "done"
    assert snapshot["steps"]["share"] == "done"
    assert snapshot["result"]["pixel_share"] == "already"
    assert snapshot["result"]["pixel_reused"] is True


def test_share_step_shows_running_between_pixel_ready_and_shared():
    job = webapp.Job({"store_name": "S", "domain": "d.example.com"})
    job.feed("GA4 property created, Measurement ID: G-ABCDEF1234")
    job.feed("    pixel 123456789012345 renamed to 'S - Dataset'")
    steps = job.snapshot()["steps"]
    assert (steps["ga4"], steps["meta"], steps["share"]) == ("done", "done", "running")


def test_a_failed_share_marks_that_step_failed(tmp_path):
    script = textwrap.dedent(
        """
        import sys
        print("GA4 property created, Measurement ID: G-ABCDEF1234")
        print("    pixel 123456789012345 renamed to 'S - Dataset'")
        print("Provisioning failed: sharing failed", file=sys.stderr)
        sys.exit(1)
        """
    )
    manager = webapp.JobManager(builder_for(script, tmp_path), history_path=tmp_path / "h")
    job = wait_for(manager.start({"store_name": "S", "domain": "d.example.com"}))
    assert job.snapshot()["steps"]["share"] == "failed"
