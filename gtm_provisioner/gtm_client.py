"""A thin wrapper over the Tag Manager API v2.

Everything goes through `_execute`, which throttles requests and retries the
transient failures the GTM quota produces when several dozen entities are
created back to back.
"""

import random
import ssl
import time

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .errors import ConfigError, ProvisioningError

RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

# A dropped connection or a read timing out never reaches HttpError - it fails
# before any HTTP response comes back, so it needs its own retry path.
RETRYABLE_NETWORK_ERRORS = (TimeoutError, ConnectionError, ssl.SSLError)

API_NAME = "tagmanager"
API_VERSION = "v2"


class GtmClient:
    """Authenticated access to one GTM account."""

    def __init__(self, service, config, log=print):
        self._service = service
        self._config = config
        self._log = log
        self._last_request_at = 0.0

    @classmethod
    def from_config(cls, config, log=print):
        """Build a client from a service account key file."""
        try:
            credentials = service_account.Credentials.from_service_account_file(
                config.service_account_key_path,
                scopes=list(config.scopes),
            )
        except (ValueError, KeyError) as exc:
            raise ConfigError(
                f"Service account key at {config.service_account_key_path!r} could "
                f"not be read as a Google service account key: {exc}"
            ) from exc

        if config.impersonate_subject:
            credentials = credentials.with_subject(config.impersonate_subject)

        service = build(
            API_NAME,
            API_VERSION,
            credentials=credentials,
            cache_discovery=False,
        )
        return cls(service, config, log=log)

    # -- request plumbing ------------------------------------------------

    def _throttle(self):
        """Keep a minimum gap between requests to stay under the write quota."""
        interval = self._config.request_interval_seconds
        if interval <= 0:
            return
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < interval:
            time.sleep(interval - elapsed)

    def _execute(self, request, description):
        """Run one API request, retrying transient failures with backoff."""
        delay = self._config.initial_backoff_seconds
        attempts = self._config.max_retries + 1

        for attempt in range(1, attempts + 1):
            self._throttle()
            try:
                response = request.execute()
            except HttpError as exc:
                self._last_request_at = time.monotonic()
                status = exc.resp.status if exc.resp is not None else None
                if status not in RETRYABLE_STATUS_CODES or attempt == attempts:
                    raise ProvisioningError(self._describe(exc, status, description)) from exc
                delay = self._wait_before_retry(
                    f"hit HTTP {status}", description, delay, attempt, attempts
                )
            except RETRYABLE_NETWORK_ERRORS as exc:
                self._last_request_at = time.monotonic()
                if attempt == attempts:
                    raise ProvisioningError(
                        f"{description} failed with a network error: {exc}"
                    ) from exc
                delay = self._wait_before_retry(
                    f"hit a network error ({exc})", description, delay, attempt, attempts
                )
            else:
                self._last_request_at = time.monotonic()
                return response

        raise ProvisioningError(f"{description} exhausted all retries.")

    def _wait_before_retry(self, reason, description, delay, attempt, attempts):
        """Sleep with jittered backoff and return the next delay to use."""
        wait = min(delay, self._config.max_backoff_seconds)
        wait *= 1.0 + random.random() * 0.25  # jitter, to de-sync retries
        self._log(
            f"    ~ {description} {reason}; "
            f"retrying in {wait:.1f}s (attempt {attempt}/{attempts})"
        )
        time.sleep(wait)
        return min(delay * 2, self._config.max_backoff_seconds)

    @staticmethod
    def _describe(exc, status, description):
        message = f"{description} failed with HTTP {status}: {exc}"
        if status == 403:
            message += (
                "\n    Hint: the service account needs GTM *account-level* access "
                "with publish permission. Container-level access is not enough to "
                "create a new container."
            )
        if status == 404:
            message += "\n    Hint: check 'gtm.account_id' in config.yaml."
        return message

    # -- containers ------------------------------------------------------

    @property
    def _account_path(self):
        return f"accounts/{self._config.account_id}"

    def list_containers(self):
        """Return every container under the configured account."""
        response = self._execute(
            self._service.accounts().containers().list(parent=self._account_path),
            "listing existing containers",
        )
        return response.get("container", [])

    def create_container(self, name, usage_context):
        """Create a container and return the API's container resource."""
        return self._execute(
            self._service.accounts()
            .containers()
            .create(
                parent=self._account_path,
                body={"name": name, "usageContext": [usage_context]},
            ),
            f"creating container {name!r}",
        )

    def get_default_workspace(self, container_path):
        """Return the workspace GTM creates automatically with a new container."""
        response = self._execute(
            self._service.accounts()
            .containers()
            .workspaces()
            .list(parent=container_path),
            "listing workspaces",
        )
        workspaces = response.get("workspace", [])
        if not workspaces:
            raise ProvisioningError(
                f"Container {container_path!r} has no workspace to write into."
            )
        return workspaces[0]

    # -- workspace entities ----------------------------------------------

    def _workspaces(self):
        return self._service.accounts().containers().workspaces()

    def enable_builtin_variables(self, workspace_path, types):
        """Activate built-in variables; they are not part of the variable list."""
        return self._execute(
            self._workspaces()
            .built_in_variables()
            .create(parent=workspace_path, type=list(types)),
            f"enabling {len(types)} built-in variables",
        )

    def create_folder(self, workspace_path, body):
        return self._execute(
            self._workspaces().folders().create(parent=workspace_path, body=body),
            f"creating folder {body.get('name')!r}",
        )

    def create_custom_template(self, workspace_path, body):
        return self._execute(
            self._workspaces().templates().create(parent=workspace_path, body=body),
            f"creating custom template {body.get('name')!r}",
        )

    def create_variable(self, workspace_path, body):
        return self._execute(
            self._workspaces().variables().create(parent=workspace_path, body=body),
            f"creating variable {body.get('name')!r}",
        )

    def create_trigger(self, workspace_path, body):
        return self._execute(
            self._workspaces().triggers().create(parent=workspace_path, body=body),
            f"creating trigger {body.get('name')!r}",
        )

    def create_tag(self, workspace_path, body):
        return self._execute(
            self._workspaces().tags().create(parent=workspace_path, body=body),
            f"creating tag {body.get('name')!r}",
        )

    def list_variables(self, workspace_path):
        response = self._execute(
            self._workspaces().variables().list(parent=workspace_path),
            "reading back variables",
        )
        return response.get("variable", [])

    # -- version and publish ---------------------------------------------

    def create_version(self, workspace_path, name, notes):
        return self._execute(
            self._workspaces().create_version(
                path=workspace_path,
                body={"name": name, "notes": notes},
            ),
            f"creating version {name!r}",
        )

    def publish_version(self, version_path):
        return self._execute(
            self._service.accounts()
            .containers()
            .versions()
            .publish(path=version_path),
            f"publishing version {version_path!r}",
        )
