"""A thin wrapper over the Google Analytics Admin API (v1beta).

Creates one GA4 property and its web data stream per store, mirroring the
retry/throttle behaviour gtm_client.py uses against the same kind of quota
errors and transient network failures (see api_retry.py).
"""

from google.oauth2 import service_account
from googleapiclient.discovery import build

from .api_retry import RetryingApiClient
from .errors import ConfigError, ProvisioningError, ValidationError
from .validators import validate_ga4_measurement_id

API_NAME = "analyticsadmin"
API_VERSION = "v1beta"

STREAM_TYPE_WEB = "WEB_DATA_STREAM"


class Ga4Client(RetryingApiClient):
    """Authenticated access to one Google Analytics account."""

    def __init__(self, service, config, log=print):
        super().__init__()
        self._service = service
        self._config = config
        self._log = log

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

    @staticmethod
    def _describe_http_error(exc, status, description):
        message = f"{description} failed with HTTP {status}: {exc}"
        if status == 403:
            message += (
                "\n    Hint: the service account needs Editor access on the GA4 "
                "Account, granted from Admin > Account Access Management in "
                "Google Analytics itself - this is separate from GTM's permissions."
            )
        if status == 404:
            message += "\n    Hint: check 'ga4.account_id' in config.yaml."
        return message

    # -- properties and data streams --------------------------------------

    def create_property_and_stream(self, website_domain):
        """Create a GA4 property and web data stream, return its Measurement ID.

        Google's own docs describe `measurementId` as returned without its
        "G-" prefix, but a live property created against v1beta returned it
        already prefixed - so the prefix is added only when it's actually
        missing, rather than assumed either way.
        """
        property_ = self._create_property(website_domain)
        try:
            stream = self._create_data_stream(property_["name"], website_domain)
        except ProvisioningError as exc:
            raise ProvisioningError(
                f"{exc}\n    A GA4 property was already created and now has no "
                f"data stream: {property_['name']}. This run does not roll it "
                "back - delete or repair it in Google Analytics.",
                entity=website_domain,
            ) from exc
        measurement_id = stream.get("webStreamData", {}).get("measurementId")
        if not measurement_id:
            raise ProvisioningError(
                f"GA4 created a web data stream for {website_domain!r} but the "
                "response carried no measurementId.",
                entity=website_domain,
            )
        prefixed = measurement_id if measurement_id.upper().startswith("G-") else f"G-{measurement_id}"
        try:
            # Confirm the result still looks like a real Measurement ID before
            # it goes anywhere near the container template.
            return validate_ga4_measurement_id(prefixed)
        except ValidationError as exc:
            raise ProvisioningError(
                f"GA4 returned measurementId {measurement_id!r} for "
                f"{website_domain!r}, which does not look like a valid "
                "Measurement ID.",
                entity=website_domain,
            ) from exc

    def _create_property(self, website_domain):
        body = {
            "parent": f"accounts/{self._config.ga4_account_id}",
            "displayName": website_domain,
            "timeZone": self._config.ga4_timezone,
            "currencyCode": self._config.ga4_currency_code,
            "industryCategory": self._config.ga4_industry_category,
        }
        return self._execute(
            self._service.properties().create(body=body),
            f"creating GA4 property for {website_domain!r}",
        )

    def _create_data_stream(self, property_name, website_domain):
        body = {
            "displayName": website_domain,
            "type": STREAM_TYPE_WEB,
            "webStreamData": {"defaultUri": f"https://{website_domain}"},
        }
        return self._execute(
            self._service.properties()
            .dataStreams()
            .create(parent=property_name, body=body),
            f"creating GA4 web data stream for {website_domain!r}",
        )
