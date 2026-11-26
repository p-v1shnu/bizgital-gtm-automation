"""Loading and validating the local (git-ignored) config file."""

import os
import re
from dataclasses import dataclass, field, replace

import yaml

from .errors import ConfigError

DEFAULT_CONFIG_PATH = "config.yaml"

# Scopes required to create a container, populate a workspace, cut a version
# and publish it, plus create a GA4 property and web data stream. The service
# account must hold GTM account-level access and GA4 Account-level Editor
# access (granted separately in each product's own admin UI).
DEFAULT_SCOPES = (
    "https://www.googleapis.com/auth/tagmanager.edit.containers",
    "https://www.googleapis.com/auth/tagmanager.edit.containerversions",
    "https://www.googleapis.com/auth/tagmanager.publish",
    "https://www.googleapis.com/auth/tagmanager.manage.accounts",
    "https://www.googleapis.com/auth/analytics.edit",
)

# Only requested when gtm.share_with is set: managing who can use a container
# is a separate, broader permission than anything the script needs otherwise.
MANAGE_USERS_SCOPE = "https://www.googleapis.com/auth/tagmanager.manage.users"

# GTM container-level permission levels, lowest to highest.
SHARE_PERMISSIONS = ("read", "edit", "approve", "publish")
DEFAULT_SHARE_PERMISSION = "publish"

# GTM account-level access, lowest to highest. "admin" is what the service
# account itself has: full control of the whole account, including every
# container and who has access to it.
ACCOUNT_ACCESS_LEVELS = ("noAccess", "user", "admin")
DEFAULT_ACCOUNT_ACCESS = "noAccess"

_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass(frozen=True)
class Config:
    account_id: str
    usage_context: str
    service_account_key_path: str
    template_path: str
    ga4_variable_name: str
    meta_pixel_variable_name: str
    ga4_account_id: str
    meta_business_id: str
    meta_ad_account_id: str
    meta_access_token_path: str
    impersonate_subject: str = ""
    scopes: tuple = DEFAULT_SCOPES
    max_retries: int = 5
    initial_backoff_seconds: float = 1.0
    max_backoff_seconds: float = 60.0
    request_interval_seconds: float = 0.4
    warn_on_duplicate_name: bool = True
    version_name_prefix: str = "Initial provisioning"
    ga4_timezone: str = "Asia/Vientiane"
    ga4_currency_code: str = "USD"
    ga4_industry_category: str = "SHOPPING"
    # ((email, container_permission, account_access), ...) granted on every
    # container this script creates.
    gtm_share_with: tuple = ()
    extra: dict = field(default_factory=dict)


def _require(mapping, key, where):
    """Fetch a non-empty value from the config, or raise ConfigError."""
    value = mapping.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ConfigError(f"Config is missing required key '{where}.{key}'.")
    return value


def parse_share_with(value):
    """Turn `gtm.share_with` into ((email, permission), ...), or raise ConfigError.

    Each entry is an email string (permission defaults to publish) or a
    mapping with `email` and optional `permission`. Duplicate emails are
    rejected rather than silently picking one of two permission levels.
    """
    if value in (None, ""):
        return ()
    if not isinstance(value, list):
        raise ConfigError("Config key 'gtm.share_with' must be a list.")
    people = []
    seen = set()
    for entry in value:
        if isinstance(entry, str):
            email, permission = entry, DEFAULT_SHARE_PERMISSION
            account_access = DEFAULT_ACCOUNT_ACCESS
        elif isinstance(entry, dict):
            email = entry.get("email")
            permission = entry.get("permission") or DEFAULT_SHARE_PERMISSION
            account_access = entry.get("account_access") or DEFAULT_ACCOUNT_ACCESS
        else:
            raise ConfigError(
                "Each 'gtm.share_with' entry must be an email or a mapping "
                "with 'email' and 'permission'."
            )
        email = str(email or "").strip()
        permission = str(permission).strip().lower()
        if not _EMAIL_PATTERN.match(email):
            raise ConfigError(f"'gtm.share_with' has an invalid email address: {email!r}.")
        if permission not in SHARE_PERMISSIONS:
            raise ConfigError(
                f"'gtm.share_with' permission for {email} must be one of "
                f"{', '.join(SHARE_PERMISSIONS)} (got {permission!r})."
            )
        account_access = {level.lower(): level for level in ACCOUNT_ACCESS_LEVELS}.get(
            str(account_access).strip().lower()
        )
        if account_access is None:
            raise ConfigError(
                f"'gtm.share_with' account_access for {email} must be one of "
                f"{', '.join(ACCOUNT_ACCESS_LEVELS)}."
            )
        if email.lower() in seen:
            raise ConfigError(f"'gtm.share_with' lists {email} more than once.")
        seen.add(email.lower())
        people.append((email, permission, account_access))
    return tuple(people)


def parse_share_flag(text):
    """Turn a --share-with value, EMAIL[:PERMISSION[:ACCOUNT_ACCESS]], into the
    mapping form parse_share_with understands."""
    parts = (text or "").split(":")
    if len(parts) > 3 or not parts[0].strip():
        raise ConfigError(
            f"--share-with {text!r} must look like EMAIL[:PERMISSION[:ACCOUNT_ACCESS]]."
        )
    entry = {"email": parts[0]}
    if len(parts) > 1 and parts[1].strip():
        entry["permission"] = parts[1]
    if len(parts) > 2 and parts[2].strip():
        entry["account_access"] = parts[2]
    return entry


def with_share_with(config, people):
    """Return `config` with who gets container access replaced by `people`.

    The user-management scope is requested only when there is somebody to
    grant, matching what load_config does for the config file.
    """
    scopes = tuple(s for s in config.scopes if s != MANAGE_USERS_SCOPE)
    if people:
        scopes += (MANAGE_USERS_SCOPE,)
    return replace(config, gtm_share_with=tuple(people), scopes=scopes)


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
    ga4 = raw.get("ga4") or {}
    meta = raw.get("meta") or {}

    base_dir = os.path.dirname(os.path.abspath(path))

    def resolve(value):
        return value if os.path.isabs(value) else os.path.join(base_dir, value)

    share_with = parse_share_with(gtm.get("share_with"))
    scopes = DEFAULT_SCOPES + ((MANAGE_USERS_SCOPE,) if share_with else ())

    config = Config(
        gtm_share_with=share_with,
        scopes=scopes,
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
        ga4_account_id=str(_require(ga4, "account_id", "ga4")),
        ga4_timezone=str(ga4.get("timezone") or "Asia/Vientiane"),
        ga4_currency_code=str(ga4.get("currency_code") or "USD"),
        ga4_industry_category=str(ga4.get("industry_category") or "SHOPPING"),
        meta_business_id=str(_require(meta, "business_id", "meta")),
        meta_ad_account_id=str(_require(meta, "ad_account_id", "meta")),
        meta_access_token_path=resolve(str(_require(meta, "access_token_path", "meta"))),
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
        ("meta.access_token_path", config.meta_access_token_path),
    ):
        if not os.path.isfile(file_path):
            raise ConfigError(f"File for '{label}' not found at {file_path!r}.")
