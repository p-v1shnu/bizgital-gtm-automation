"""Local web UI for provision_gtm.py.

A thin layer over the existing command-line script: the browser form is
validated here with the same validators the script uses, and a real run is just
``provision_gtm.py`` executed as a subprocess whose output is streamed back to
the page. Nothing about provisioning is re-implemented, so the CLI and the UI
can never drift apart.

Security model: the server binds to 127.0.0.1 only, rejects any request whose
Host header is not the local address (DNS-rebinding guard), and accepts POST
bodies only as JSON. There is no authentication because only this machine can
reach it.
"""

import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .config import DEFAULT_CONFIG_PATH, check_local_files, load_config
from .errors import ValidationError
from .validators import (
    validate_meta_pixel_id,
    validate_store_name,
    validate_website_domain,
)

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "provision_gtm.py"
STATIC_DIR = Path(__file__).resolve().parent / "web"
HISTORY_PATH = ROOT / "logs" / "runs.jsonl"
DEFAULT_PORT = 8765
MAX_BODY_BYTES = 16 * 1024
MAX_LOG_LINES = 5000

# Progress steps shown in the UI, in order. "optional" ones are marked skipped
# (rather than done) when the template has nothing of that kind.
STEPS = (
    ("ga4", False),
    ("meta", False),
    ("container", False),
    ("builtin", False),
    ("folders", True),
    ("templates", True),
    ("variables", False),
    ("triggers", False),
    ("tags", False),
    ("verify", False),
    ("publish", False),
)
STEP_ORDER = [key for key, _ in STEPS]
OPTIONAL_STEPS = {key for key, optional in STEPS if optional}

# provision_gtm.py prints "[<number>. <name>]" at the start of each container
# step; the number identifies the step.
SCRIPT_STEP_KEYS = {
    "1": "container",
    "2": "builtin",
    "2a": "folders",
    "2b": "templates",
    "3": "variables",
    "4": "triggers",
    "5": "tags",
    "6": "verify",
    "7": "publish",
}

RE_SCRIPT_STEP = re.compile(r"^\[(\d+[a-z]?)\.")
RE_GA4_CREATED = re.compile(r"^GA4 property created, Measurement ID: (G-[A-Z0-9]+)")
RE_PIXEL_DONE = re.compile(r"^Meta pixel (?:created|reused and renamed), ID: (\d+)")
RE_GTM_ID = re.compile(r"GTM container ID: (GTM-[A-Z0-9]+)")
RE_ERROR = re.compile(r"^(Setup error|Provisioning failed): (.*)")
RE_PARTIAL_ID = re.compile(r"^\s+public ID:\s+(GTM-[A-Z0-9]+)")
RE_TEMPLATE_COUNT = re.compile(r"^\s{2}(\w+)\s+(\d+)$")
RE_MISMATCH = re.compile(r"MISMATCH")


class BusyError(Exception):
    """A provisioning run is already in progress."""


def build_command(params, python=None, script=None):
    """Return the argv for one provision_gtm.py run.

    ``--key=value`` form is used for free-text values so a store name that
    starts with ``-`` can never be mistaken for a flag. ``--yes`` is always
    passed: the page asks about duplicate container names itself, and a prompt
    nobody can answer would hang the run.
    """
    command = [
        python or sys.executable,
        "-u",
        str(script or SCRIPT),
        f"--store-name={params['store_name']}",
        f"--domain={params['domain']}",
        "--yes",
    ]
    if params.get("meta_pixel_id"):
        command.append(f"--meta-pixel-id={params['meta_pixel_id']}")
    if params.get("dry_run"):
        command.append("--dry-run")
    return command


FIELD_ERRORS_TH = {
    "store_name": {
        "empty": "กรุณากรอกชื่อร้าน",
        "long": "ชื่อร้านยาวเกินไป (ไม่เกิน 100 ตัวอักษร)",
        "bad": "ชื่อร้านไม่ถูกต้อง",
    },
    "domain": {
        "empty": "กรุณากรอกโดเมนเว็บไซต์",
        "long": "โดเมนยาวเกินไป (ไม่เกิน 100 ตัวอักษร)",
        "bad": "รูปแบบโดเมนไม่ถูกต้อง ต้องเป็นแบบ store.shopshop.la (ไม่มีเครื่องหมายเว้นวรรคหรือ path)",
    },
    "meta_pixel_id": {
        "empty": "กรุณากรอก Pixel ID",
        "long": "Pixel ID ไม่ถูกต้อง",
        "bad": "Pixel ID ต้องเป็นตัวเลข 15–16 หลัก",
    },
}


def thai_field_error(field, message):
    """Translate a validator's English message into Thai for the form."""
    kind = "bad"
    if "must not be empty" in message:
        kind = "empty"
    elif "at most" in message:
        kind = "long"
    return FIELD_ERRORS_TH[field][kind]


def check_inputs(payload, config_path=DEFAULT_CONFIG_PATH, list_container_names=None):
    """Validate form input and local setup without creating anything.

    Returns ``{"ok", "errors", "values", "setup_problems", "duplicates"}``.
    ``errors`` maps a form field to a message. ``duplicates`` lists the public
    IDs of existing containers that already have this domain's name.
    ``list_container_names`` is injected by tests; by default it asks the GTM
    API (and is skipped on a dry run, which needs no credentials).
    """
    errors = {}
    values = {}
    for field, label, validate in (
        ("store_name", "store name", validate_store_name),
        ("domain", "domain", validate_website_domain),
    ):
        try:
            values[field] = validate(payload.get(field))
        except ValidationError as exc:
            errors[field] = thai_field_error(field, exc.message)
    pixel = (payload.get("meta_pixel_id") or "").strip()
    if pixel:
        try:
            values["meta_pixel_id"] = validate_meta_pixel_id(pixel)
        except ValidationError as exc:
            errors["meta_pixel_id"] = thai_field_error("meta_pixel_id", exc.message)

    dry_run = bool(payload.get("dry_run"))
    setup_problems = []
    config = None
    try:
        config = load_config(config_path)
        if dry_run:
            if not os.path.isfile(config.template_path):
                setup_problems.append(f"Template not found at {config.template_path!r}.")
        else:
            check_local_files(config)
    except Exception as exc:  # ConfigError, or anything odd in the YAML
        setup_problems.append(str(exc))

    duplicates = []
    wants_duplicate_check = not dry_run and not payload.get("setup_only")
    if (
        not errors
        and not setup_problems
        and wants_duplicate_check
        and config.warn_on_duplicate_name
    ):
        try:
            lister = list_container_names or _list_containers(config)
            duplicates = [
                public_id
                for name, public_id in lister()
                if name == values["domain"]
            ]
        except Exception as exc:
            setup_problems.append(f"Could not check for duplicate containers: {exc}")

    return {
        "ok": not errors and not setup_problems,
        "errors": errors,
        "values": values,
        "setup_problems": setup_problems,
        "duplicates": duplicates,
    }


def _list_containers(config):
    def lister():
        from .gtm_client import GtmClient

        client = GtmClient.from_config(config, log=lambda *_: None)
        return [(c.get("name"), c.get("publicId", "?")) for c in client.list_containers()]

    return lister


class Job:
    """One provisioning run: its output, progress and eventual result."""

    def __init__(self, params):
        self.id = uuid.uuid4().hex[:12]
        self.params = params
        self.dry_run = bool(params.get("dry_run"))
        self.lines = []
        self.state = "running"  # running | done | warning | failed
        self.exit_code = None
        self.result = {}
        self.error = None
        self.partial_container = None
        self.template_counts = {}
        self.started_at = time.time()
        self.finished_at = None
        self.steps = {key: "pending" for key in STEP_ORDER}
        self._in_template_summary = False
        self._lock = threading.Lock()
        if not self.dry_run:
            self.steps["ga4"] = "running"

    # -- progress ---------------------------------------------------------

    def _advance_to(self, key):
        """Mark `key` running and everything before it finished."""
        target = STEP_ORDER.index(key)
        for earlier in STEP_ORDER[:target]:
            if self.steps[earlier] in ("pending", "running"):
                self.steps[earlier] = "skipped" if earlier in OPTIONAL_STEPS else "done"
        self.steps[key] = "running"

    def feed(self, line):
        """Record one output line and update progress from it."""
        with self._lock:
            if len(self.lines) < MAX_LOG_LINES:
                self.lines.append(line)
            self._interpret(line)

    def _interpret(self, line):
        if line.startswith("Template:"):
            self._in_template_summary = True
        elif "template audit" in line:
            self._in_template_summary = False
        elif self._in_template_summary:
            counted = RE_TEMPLATE_COUNT.match(line)
            if counted:
                self.template_counts[counted.group(1)] = int(counted.group(2))

        match = RE_GA4_CREATED.match(line)
        if match:
            self.result["ga4_measurement_id"] = match.group(1)
            self.steps["ga4"] = "done"
            self.steps["meta"] = "running"
            return
        match = RE_PIXEL_DONE.match(line)
        if match:
            self.result["meta_pixel_id"] = match.group(1)
            self.result["pixel_reused"] = "reused" in line
            self.steps["ga4"] = "done"
            self.steps["meta"] = "done"
            self.steps["container"] = "running"
            return
        match = RE_SCRIPT_STEP.match(line)
        if match and match.group(1) in SCRIPT_STEP_KEYS:
            self._advance_to(SCRIPT_STEP_KEYS[match.group(1)])
            return
        match = RE_GTM_ID.search(line)
        if match:
            self.result["gtm_public_id"] = match.group(1)
            return
        match = RE_ERROR.match(line)
        if match and self.error is None:
            self.error = match.group(2)
            return
        match = RE_PARTIAL_ID.match(line)
        if match:
            self.partial_container = match.group(1)
        if RE_MISMATCH.search(line):
            self.result["count_mismatch"] = True

    def finish(self, exit_code):
        with self._lock:
            self.exit_code = exit_code
            self.finished_at = time.time()
            if exit_code == 0:
                self.state = "done"
                for key in STEP_ORDER:
                    if self.steps[key] == "running":
                        self.steps[key] = "done"
                    elif self.steps[key] == "pending":
                        self.steps[key] = (
                            "skipped" if key in OPTIONAL_STEPS or self.dry_run else "done"
                        )
            else:
                has_container = "gtm_public_id" in self.result
                self.state = "warning" if has_container else "failed"
                for key in STEP_ORDER:
                    if self.steps[key] == "running":
                        self.steps[key] = "done" if has_container else "failed"

    def snapshot(self, since=0):
        with self._lock:
            return {
                "id": self.id,
                "state": self.state,
                "dry_run": self.dry_run,
                "exit_code": self.exit_code,
                "steps": dict(self.steps),
                "lines": self.lines[since:],
                "next": len(self.lines),
                "result": dict(self.result),
                "template_counts": dict(self.template_counts),
                "error": self.error,
                "partial_container": self.partial_container,
                "elapsed": round((self.finished_at or time.time()) - self.started_at, 1),
            }


class JobManager:
    """Runs at most one provisioning subprocess at a time."""

    def __init__(self, command_builder=build_command, history_path=HISTORY_PATH, cwd=ROOT):
        self._build = command_builder
        self._history_path = history_path
        self._cwd = cwd
        self._jobs = {}
        self._current = None
        self._lock = threading.Lock()

    def start(self, params):
        with self._lock:
            if self._current and self._current.state == "running":
                raise BusyError("A run is already in progress.")
            job = Job(params)
            self._jobs[job.id] = job
            self._current = job
        threading.Thread(target=self._run, args=(job,), daemon=True).start()
        return job

    def get(self, job_id):
        return self._jobs.get(job_id)

    def _run(self, job):
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
        try:
            process = subprocess.Popen(
                self._build(job.params),
                cwd=str(self._cwd),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            for raw in process.stdout:
                job.feed(raw.rstrip("\r\n"))
            exit_code = process.wait()
        except Exception as exc:  # could not even start the script
            job.feed(f"Setup error: could not start provision_gtm.py: {exc}")
            exit_code = 2
        job.finish(exit_code)
        if not job.dry_run:
            self._record_history(job)

    def _record_history(self, job):
        entry = {
            "time": datetime.now().isoformat(timespec="seconds"),
            "state": job.state,
            "store_name": job.params.get("store_name"),
            "domain": job.params.get("domain"),
            **{
                key: job.result.get(key)
                for key in ("gtm_public_id", "ga4_measurement_id", "meta_pixel_id")
            },
            "partial_container": job.partial_container,
            "error": job.error,
        }
        try:
            self._history_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._history_path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            pass  # history is a convenience; never fail a run over it

    def history(self, limit=20):
        try:
            with open(self._history_path, "r", encoding="utf-8") as handle:
                rows = [json.loads(line) for line in handle if line.strip()]
        except (OSError, ValueError):
            return []
        return list(reversed(rows[-limit:]))


def make_handler(manager, config_path=DEFAULT_CONFIG_PATH, list_container_names=None):
    class Handler(BaseHTTPRequestHandler):
        server_version = "GtmProvisionerUI"

        def log_message(self, fmt, *args):  # keep the console quiet
            pass

        # -- helpers ------------------------------------------------------

        def _host_ok(self):
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
            return host in ("127.0.0.1", "localhost", "::1")

        def _send(self, status, body, content_type="application/json; charset=utf-8"):
            if not isinstance(body, bytes):
                body = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _read_json(self):
            if "application/json" not in (self.headers.get("Content-Type") or ""):
                self._send(415, {"error": "ต้องส่งข้อมูลแบบ JSON"})
                return None
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = -1
            if not 0 <= length <= MAX_BODY_BYTES:
                self._send(413, {"error": "ข้อมูลที่ส่งมาใหญ่เกินไป"})
                return None
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                self._send(400, {"error": "รูปแบบ JSON ไม่ถูกต้อง"})
                return None
            if not isinstance(payload, dict):
                self._send(400, {"error": "รูปแบบข้อมูลไม่ถูกต้อง"})
                return None
            return payload

        # -- routes -------------------------------------------------------

        def do_GET(self):
            if not self._host_ok():
                return self._send(403, {"error": "forbidden"})
            path, _, query = self.path.partition("?")
            if path in ("/", "/index.html"):
                try:
                    page = (STATIC_DIR / "index.html").read_bytes()
                except OSError:
                    return self._send(500, {"error": "ไม่พบไฟล์หน้าเว็บ"})
                return self._send(200, page, "text/html; charset=utf-8")
            if path == "/api/history":
                return self._send(200, {"runs": manager.history()})
            if path.startswith("/api/job/"):
                job = manager.get(path[len("/api/job/"):])
                if job is None:
                    return self._send(404, {"error": "ไม่พบงานนี้"})
                since = 0
                for pair in query.split("&"):
                    key, _, value = pair.partition("=")
                    if key == "since" and value.isdigit():
                        since = int(value)
                return self._send(200, job.snapshot(since))
            return self._send(404, {"error": "not found"})

        def do_POST(self):
            if not self._host_ok():
                return self._send(403, {"error": "forbidden"})
            payload = self._read_json()
            if payload is None:
                return None
            if self.path == "/api/check":
                return self._send(
                    200, check_inputs(payload, config_path, list_container_names)
                )
            if self.path == "/api/run":
                checked = check_inputs(payload, config_path, list_container_names)
                if not checked["ok"]:
                    return self._send(422, checked)
                if checked["duplicates"] and not payload.get("allow_duplicate"):
                    return self._send(409, {**checked, "error": "duplicate"})
                params = {
                    "store_name": checked["values"]["store_name"],
                    "domain": checked["values"]["domain"],
                    "meta_pixel_id": checked["values"].get("meta_pixel_id"),
                    "dry_run": bool(payload.get("dry_run")),
                }
                try:
                    job = manager.start(params)
                except BusyError:
                    return self._send(409, {"error": "busy"})
                return self._send(202, {"job_id": job.id})
            return self._send(404, {"error": "not found"})

    return Handler


class _LocalServer(ThreadingHTTPServer):
    # On Windows SO_REUSEADDR lets a second server bind a port another program
    # is already listening on, so requests land on either one. Turn it off so a
    # taken port fails loudly and create_server moves on to the next one.
    allow_reuse_address = False
    daemon_threads = True


def create_server(port=DEFAULT_PORT, manager=None, config_path=DEFAULT_CONFIG_PATH,
                  list_container_names=None):
    """Bind the UI server on 127.0.0.1, trying the next ports if `port` is taken."""
    manager = manager or JobManager()
    handler = make_handler(manager, config_path, list_container_names)
    last_error = None
    for candidate in range(port, port + 20) if port else (0,):
        try:
            return _LocalServer(("127.0.0.1", candidate), handler), manager
        except OSError as exc:
            last_error = exc
    raise last_error
