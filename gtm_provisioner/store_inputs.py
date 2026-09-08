"""Where the store-specific IDs come from.

This module is deliberately the only place that knows how the GA4 Measurement
ID and Meta Pixel ID are obtained. The operator supplies the store's website
domain and Meta Pixel ID; the GA4 Measurement ID is obtained by creating a
GA4 property and web data stream for that domain (via `ga4_client`) rather
than being typed in. The website domain doubles as the GTM container name,
matching the naming convention already in use for GA4 properties.

A future step to also create the Meta Pixel itself (via the Meta Marketing
API) would extend this module the same way, without touching any GTM
provisioning logic.
"""

from dataclasses import dataclass

from .errors import ValidationError
from .validators import validate_meta_pixel_id, validate_website_domain

# Used only when ga4_client is None (a dry run): a well-formed placeholder so
# the rest of the pipeline can be exercised without ever calling the GA4 API.
DRY_RUN_GA4_MEASUREMENT_ID = "G-DRYRUN0000"


@dataclass(frozen=True)
class StoreInputs:
    """The three values that make one provisioning run store-specific."""

    container_name: str
    ga4_measurement_id: str
    meta_pixel_id: str


_FIELDS = (
    ("website_domain", "Store website domain (e.g. store.shopshop.la)", validate_website_domain),
    ("meta_pixel_id", "Meta Pixel ID (15-16 digits)", validate_meta_pixel_id),
)


def collect_store_inputs(
    ga4_client,
    website_domain=None,
    meta_pixel_id=None,
    prompt=input,
):
    """Return validated StoreInputs.

    Values supplied by the caller (CLI flags) are validated once and a bad one
    is fatal, so an unattended run fails loudly instead of hanging on a prompt.
    Values left out are asked for interactively and re-asked until valid.

    `ga4_client` is None during a dry run: no GA4 property is created, and
    `DRY_RUN_GA4_MEASUREMENT_ID` stands in for the real Measurement ID.
    """
    supplied = {"website_domain": website_domain, "meta_pixel_id": meta_pixel_id}
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
    if ga4_client is None:
        ga4_measurement_id = DRY_RUN_GA4_MEASUREMENT_ID
    else:
        ga4_measurement_id = ga4_client.create_property_and_stream(domain)

    return StoreInputs(
        container_name=domain,
        ga4_measurement_id=ga4_measurement_id,
        meta_pixel_id=collected["meta_pixel_id"],
    )
