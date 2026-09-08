"""Where the store-specific IDs come from.

This module is deliberately the only place that knows how the GA4 Measurement
ID and Meta Pixel ID are obtained. The operator supplies the store's name and
website domain; both IDs are obtained automatically:

- the website domain doubles as the GTM container name and the GA4
  property/stream name (via `ga4_client`), matching the naming convention
  already in use for GA4 properties
- the store name becomes the Meta Pixel's name, as "<store name> - Dataset"
  (via `meta_client`), matching the naming convention already in use there

Neither ID is typed in by hand any more.
"""

from dataclasses import dataclass

from .errors import ValidationError
from .validators import validate_store_name, validate_website_domain

# Used only when the matching client is None (a dry run): well-formed
# placeholders so the rest of the pipeline can be exercised without ever
# calling the GA4 or Meta API.
DRY_RUN_GA4_MEASUREMENT_ID = "G-DRYRUN0000"
DRY_RUN_META_PIXEL_ID = "999999999999999"

PIXEL_NAME_SUFFIX = " - Dataset"


@dataclass(frozen=True)
class StoreInputs:
    """The three values that make one provisioning run store-specific."""

    container_name: str
    ga4_measurement_id: str
    meta_pixel_id: str


_FIELDS = (
    ("store_name", "Store name (e.g. ShopShop Pigeon)", validate_store_name),
    ("website_domain", "Store website domain (e.g. store.shopshop.la)", validate_website_domain),
)


def collect_store_inputs(
    ga4_client,
    meta_client,
    store_name=None,
    website_domain=None,
    prompt=input,
):
    """Return validated StoreInputs.

    Values supplied by the caller (CLI flags) are validated once and a bad one
    is fatal, so an unattended run fails loudly instead of hanging on a prompt.
    Values left out are asked for interactively and re-asked until valid.

    `ga4_client` and `meta_client` are None during a dry run: no GA4 property
    or Meta pixel is created, and the DRY_RUN_* constants stand in for the
    real IDs.
    """
    supplied = {"store_name": store_name, "website_domain": website_domain}
    collected = {}

    for field, label, validate in _FIELDS:
        given = supplied[field]
        if given is not None:
            collected[field] = validate(given)
            continue
        while True:
            try:
                collected[field] = validate(prompt(f"{label}: "))
                break
            except ValidationError as exc:
                print(f"  ! {exc.message}")

    domain = collected["website_domain"]
    name = collected["store_name"]

    if ga4_client is None:
        ga4_measurement_id = DRY_RUN_GA4_MEASUREMENT_ID
    else:
        ga4_measurement_id = ga4_client.create_property_and_stream(domain)

    if meta_client is None:
        meta_pixel_id = DRY_RUN_META_PIXEL_ID
    else:
        meta_pixel_id = meta_client.create_pixel(f"{name}{PIXEL_NAME_SUFFIX}")

    return StoreInputs(
        container_name=domain,
        ga4_measurement_id=ga4_measurement_id,
        meta_pixel_id=meta_pixel_id,
    )
