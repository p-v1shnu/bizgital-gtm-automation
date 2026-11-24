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

# A pixel is shared with a handful of ad accounts; this only bounds a runaway
# paging loop.
MAX_SHARE_LIST_PAGES = 10


def _plain_account_id(value):
    """Ad account ID without Meta's 'act_' prefix, as a string."""
    text = str(value or "").strip()
    return text[4:] if text.startswith("act_") else text


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

        self._log(f"    pixel {validated_id} created under Business {self._config.meta_business_id}")
        try:
            self._share_with_ad_account(validated_id)
            self._log(
                f"    pixel {validated_id} shared with ad account {self._config.meta_ad_account_id}"
            )
        except ProvisioningError as exc:
            raise ProvisioningError(
                f"{exc}\n    Pixel {validated_id} ({name!r}) was created under "
                f"the Business but is not shared with any ad account yet: fix "
                "sharing by hand in Business Manager (it cannot be deleted - "
                "see HANDOFF-META-PIXEL-FIX.md), or reuse it for a later "
                "store via --meta-pixel-id.",
                entity=name,
            ) from exc
        return validated_id

    def _share_with_ad_account(self, pixel_id):
        return self._post(
            f"{GRAPH_API_BASE}/{pixel_id}/shared_accounts",
            {
                "business": self._config.meta_business_id,
                "account_id": self._config.meta_ad_account_id,
            },
            f"sharing Meta pixel {pixel_id} with the configured ad account",
        )

    def is_shared_with_ad_account(self, pixel_id):
        """True if the configured ad account is already on the pixel's share list.

        Reads `GET /{pixel_id}/shared_accounts?business=...`, following the
        paging links. Meta returns each ad account as `act_<id>` (and, on some
        responses, also a plain `account_id`), so both forms are compared
        with the `act_` prefix stripped.
        """
        wanted = _plain_account_id(self._config.meta_ad_account_id)
        description = f"listing the ad accounts Meta pixel {pixel_id} is shared with"
        page = self._get(
            f"{GRAPH_API_BASE}/{pixel_id}/shared_accounts",
            {"business": self._config.meta_business_id, "limit": 100},
            description,
        )
        for _ in range(MAX_SHARE_LIST_PAGES):
            for account in page.get("data") or []:
                for key in ("account_id", "id"):
                    if _plain_account_id(account.get(key)) == wanted:
                        return True
            next_url = (page.get("paging") or {}).get("next")
            if not next_url:
                return False
            page = self._send(lambda url=next_url: requests.get(url, timeout=30), description)
        return False

    def ensure_shared_with_ad_account(self, pixel_id):
        """Share an existing pixel with the configured ad account unless it
        already is. Returns "already" or "shared".

        Used when an operator reuses a pixel via --meta-pixel-id: creating a
        pixel shares it as a side effect, but a reused one may never have
        been given to this ad account. If the share list cannot be read the
        share is attempted anyway - it is the call that matters, the list is
        only there to skip a needless one.
        """
        try:
            if self.is_shared_with_ad_account(pixel_id):
                self._log(
                    f"    pixel {pixel_id} is already shared with ad account "
                    f"{self._config.meta_ad_account_id}; skipping"
                )
                return "already"
        except ProvisioningError as exc:
            self._log(
                f"    ~ could not check existing sharing ({exc}); sharing anyway"
            )
        try:
            self._share_with_ad_account(pixel_id)
        except ProvisioningError as exc:
            raise ProvisioningError(
                f"{exc}\n    Pixel {pixel_id} was renamed but is not shared with "
                f"ad account {self._config.meta_ad_account_id}: share it by hand "
                "in Business Manager (pixel Settings -> Ad accounts), or fix the "
                "access and run again with the same --meta-pixel-id.",
                entity=pixel_id,
            ) from exc
        self._log(
            f"    pixel {pixel_id} shared with ad account {self._config.meta_ad_account_id}"
        )
        return "shared"

    def rename_pixel(self, pixel_id, name):
        """Rename an existing pixel - used when an operator reuses one via
        --meta-pixel-id instead of creating a new one, so it doesn't keep a
        stale name (e.g. from an earlier test store) in Business Manager.
        """
        self._post(
            f"{GRAPH_API_BASE}/{pixel_id}",
            {"name": name},
            f"renaming Meta pixel {pixel_id} to {name!r}",
        )
        self._log(f"    pixel {pixel_id} renamed to {name!r}")

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
        payload = dict(data, access_token=self._access_token)
        return self._send(
            lambda: requests.post(url, data=payload, timeout=30), description
        )

    def _get(self, url, params, description):
        """GET once, retrying a 429/5xx or a network error with backoff."""
        query = dict(params, access_token=self._access_token)
        return self._send(
            lambda: requests.get(url, params=query, timeout=30), description
        )

    def _send(self, send, description):
        """Run `send()` until it answers 200, retrying only transient failures."""
        delay = self._config.initial_backoff_seconds
        attempts = self._config.max_retries + 1

        for attempt in range(1, attempts + 1):
            self._throttle()
            try:
                response = send()
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
        if "MANAGE_PIXELS_AUDIT_NEEDED" in detail:
            message += (
                "\n    Hint: creating a pixel under a Business needs an Admin "
                "System User, not Employee - confirmed live, permission scope "
                "alone (even with business_management) does not unlock it for "
                "an Employee System User. See README.md's 'Meta System User "
                "token and app' section."
            )
        elif status in (400, 403):
            message += (
                "\n    Hint: pixel creation needs an Admin System User (see "
                "README.md); sharing a pixel needs 'Full access' to the ad "
                "account under 'meta.ad_account_id', granted in Business "
                "Settings. Also check that the token in "
                "'meta.access_token_path' has the ads_management and "
                "business_management permissions and has not expired or been "
                "revoked."
            )
        return message
