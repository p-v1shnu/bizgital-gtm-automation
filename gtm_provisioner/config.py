"""Loading and validating the local (git-ignored) config file."""

import os
from dataclasses import dataclass, field

import yaml

from .errors import ConfigError

DEFAULT_CONFIG_PATH = "config.yaml"

# Scopes required to create a container, populate a workspace, cut a version
# and publish it. The service account must hold GTM account-level access.
DEFAULT_SCOPES = (
    "https://www.googleapis.com/auth/tagmanager.edit.containers",
    "https://www.googleapis.com/auth/tagmanager.edit.containerversions",
    "https://www.googleapis.com/auth/tagmanager.publish",
    "https://www.googleapis.com/auth/tagmanager.manage.accounts",
)


@dataclass(frozen=True)
class Config:
    account_id: str
    usage_context: str
    service_account_key_path: str
    template_path: str
    ga4_variable_name: str
    meta_pixel_variable_name: str
    impersonate_subject: str = ""
    scopes: tuple = DEFAULT_SCOPES
    max_retries: int = 5
    initial_backoff_seconds: float = 1.0
    max_backoff_seconds: float = 60.0
    request_interval_seconds: float = 0.4
    warn_on_duplicate_name: bool = True
    version_name_prefix: str = "Initial provisioning"
    extra: dict = field(default_factory=dict)


def _require(mapping, key, where):
    """Fetch a non-empty value from the config, or raise ConfigError."""
    value = mapping.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ConfigError(f"Config is missing required key '{where}.{key}'.")
    return value


def load_config(path=DEFAULT_CONFIG_PATH):
    """Read the YAML config and return a Config with paths resolved.

    Relative paths in the config are resolved against the config file's own
    directory, so the script can be run from anywhere.
    """
    if not os.path.isfile(path):
        raise ConfigError(
            f"Config file not found at {path!r}. "
            "Copy config.example.yaml to config.yaml and fill it in."
        )

    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"Config file {path!r} is not valid YAML: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError(f"Config file {path!r} must contain a YAML mapping.")

    gtm = raw.get("gtm") or {}
    paths = raw.get("paths") or {}
    variables = raw.get("variables") or {}
    api = raw.get("api") or {}
    behaviour = raw.get("behaviour") or {}

    base_dir = os.path.dirname(os.path.abspath(path))

    def resolve(value):
        return value if os.path.isabs(value) else os.path.join(base_dir, value)

    config = Config(
        account_id=str(_require(gtm, "account_id", "gtm")),
        usage_context=str(gtm.get("usage_context") or "web"),
        service_account_key_path=resolve(str(_require(paths, "service_account_key", "paths"))),
        template_path=resolve(str(_require(paths, "template", "paths"))),
        ga4_variable_name=str(_require(variables, "ga4_measurement_id", "variables")),
        meta_pixel_variable_name=str(_require(variables, "meta_pixel_id", "variables")),
        impersonate_subject=str(gtm.get("impersonate_subject") or ""),
        max_retries=int(api.get("max_retries", 5)),
        initial_backoff_seconds=float(api.get("initial_backoff_seconds", 1.0)),
        max_backoff_seconds=float(api.get("max_backoff_seconds", 60.0)),
        request_interval_seconds=float(api.get("request_interval_seconds", 0.4)),
        warn_on_duplicate_name=bool(behaviour.get("warn_on_duplicate_name", True)),
        version_name_prefix=str(behaviour.get("version_name_prefix") or "Initial provisioning"),
        extra=raw,
    )

    if config.max_retries < 0:
        raise ConfigError("Config key 'api.max_retries' must not be negative.")
    return config


def check_local_files(config):
    """Raise ConfigError if a file the config points at is missing."""
    for label, file_path in (
        ("paths.service_account_key", config.service_account_key_path),
        ("paths.template", config.template_path),
    ):
        if not os.path.isfile(file_path):
            raise ConfigError(f"File for '{label}' not found at {file_path!r}.")
