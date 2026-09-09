"""A thin wrapper over the Meta Marketing API for creating an ad pixel.

Meta has no official Google-style client library, so this talks to the Graph
API directly over HTTPS with `requests`, authenticated as a System User. The
retry/backoff shape mirrors api_retry.py (retry a 429/5xx or a dropped
connection, give up after config.max_retries) but is implemented separately
since `requests`' exceptions and response objects don't fit the
googleapiclient-shaped RetryingApiClient mixin.
"""

import random
import time

import requests

from .api_retry import RETRYABLE_STATUS_CODES
from .errors import ConfigError, ProvisioningError, ValidationError
from .validators import validate_meta_pixel_id

GRAPH_API_VERSION = "v21.0"
GRAPH_API_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

RETRYABLE_REQUEST_ERRORS = (requests.exceptions.ConnectionError, requests.exceptions.Timeout)


class MetaClient:
    """Authenticated access to one Meta ad account, via a System User token."""

    def __init__(self, access_token, config, log=print):
        self._access_token = access_token
        self._config = config
        self._log = log
        self._last_request_at = 0.0

    @classmethod
    def from_config(cls, config, log=print):
        """Build a client from the System User access token file."""
        try:
            with open(config.meta_access_token_path, "r", encoding="utf-8") as handle:
                token = handle.read().strip()
        except OSError as exc:
            raise ConfigError(
                f"Meta access token file at {config.meta_access_token_path!r} "
                f"could not be read: {exc}"
            ) from exc
        if not token:
            raise ConfigError(
                f"Meta access token file at {config.meta_access_token_path!r} is empty."
            )
        return cls(token, config, log=log)

    def create_pixel(self, name):
        """Create a pixel under the configured Business, then share it to the
        configured ad account. Returns its ID.

        Pixel *ownership* and ad-account *usage* are separate things in
        Meta's model. `POST /act_<id>/adspixels` makes the ad account itself
        the pixel's owner - and an ad account can only ever own one pixel
        that way, so a second store's pixel creation fails outright with
        "(#6200) A pixel already exists for this account". A Business
        Portfolio can own up to 100 pixels, so pixels are created there
        instead and then shared to the ad account that runs traffic for
        them - the same relationship every pixel created by hand in
        Business Manager already has (owner: the Business; the ad account
        appears only under that pixel's "Ad accounts" sharing list).

        The returned ID is validated with the same rules that used to check
        an operator-typed Pixel ID directly - a malformed ID here would
        otherwise become a container silently wired to nothing.
        """
        response = self._post(
            f"{GRAPH_API_BASE}/{self._config.meta_business_id}/adspixels",
            {"name": name},
            f"creating Meta pixel {name!r}",
        )
        pixel_id = response.get("id")
        if not pixel_id:
            raise ProvisioningError(
                f"Meta created a pixel for {name!r} but the response carried no id.",
                entity=name,
            )
        try:
            validated_id = validate_meta_pixel_id(str(pixel_id))
        except ValidationError as exc:
            raise ProvisioningError(
                f"Meta returned pixel id {pixel_id!r} for {name!r}, which does "
                "not look like a valid Pixel ID.",
                entity=name,
            ) from exc

        try:
            self._post(
                f"{GRAPH_API_BASE}/{validated_id}/shared_accounts",
                {"account_id": f"act_{self._config.meta_ad_account_id}"},
                f"sharing Meta pixel {validated_id} with the configured ad account",
            )
        except ProvisioningError as exc:
            raise ProvisioningError(
                f"{exc}\n    Pixel {validated_id} ({name!r}) was created under "
                f"the Business but is not shared with any ad account yet: fix "
                "sharing by hand in Business Manager, or delete the pixel and "
                "retry.",
                entity=name,
            ) from exc
        return validated_id

    # -- request plumbing -------------------------------------------------

    def _throttle(self):
        interval = self._config.request_interval_seconds
        if interval <= 0:
            return
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < interval:
            time.sleep(interval - elapsed)

    def _post(self, url, data, description):
        """POST once, retrying a 429/5xx or a network error with backoff."""
        delay = self._config.initial_backoff_seconds
        attempts = self._config.max_retries + 1
        payload = dict(data, access_token=self._access_token)

        for attempt in range(1, attempts + 1):
            self._throttle()
            try:
                response = requests.post(url, data=payload, timeout=30)
            except RETRYABLE_REQUEST_ERRORS as exc:
                self._last_request_at = time.monotonic()
                if attempt == attempts:
                    raise ProvisioningError(
                        f"{description} failed with a network error: {exc}"
                    ) from exc
                delay = self._wait_before_retry(
                    f"hit a network error ({exc})", description, delay, attempt, attempts
                )
                continue

            self._last_request_at = time.monotonic()
            if response.status_code == 200:
                return response.json()

            if response.status_code not in RETRYABLE_STATUS_CODES or attempt == attempts:
                raise ProvisioningError(self._describe_error(response, description))

            delay = self._wait_before_retry(
                f"hit HTTP {response.status_code}", description, delay, attempt, attempts
            )

        raise ProvisioningError(f"{description} exhausted all retries.")

    def _wait_before_retry(self, reason, description, delay, attempt, attempts):
        wait = min(delay, self._config.max_backoff_seconds)
        wait *= 1.0 + random.random() * 0.25  # jitter, to de-sync retries
        self._log(
            f"    ~ {description} {reason}; "
            f"retrying in {wait:.1f}s (attempt {attempt}/{attempts})"
        )
        time.sleep(wait)
        return min(delay * 2, self._config.max_backoff_seconds)

    @staticmethod
    def _describe_error(response, description):
        status = response.status_code
        try:
            detail = response.json().get("error", {}).get("message", response.text)
        except ValueError:
            detail = response.text
        message = f"{description} failed with HTTP {status}: {detail}"
        if status in (400, 403):
            message += (
                "\n    Hint: pixel creation needs the System User to have "
                "access to create pixels under 'meta.business_id'; sharing a "
                "pixel needs 'Full access' to the ad account under "
                "'meta.ad_account_id'. Both are granted separately in "
                "Business Settings. Also check that the token in "
                "'meta.access_token_path' has the ads_management permission "
                "and has not expired or been revoked."
            )
        return message
