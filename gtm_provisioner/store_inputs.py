"""Where the store-specific IDs come from.

This module is deliberately the only place that knows how the GA4 Measurement
ID and Meta Pixel ID are obtained. The operator supplies the store's name and
website domain; both IDs are obtained automatically:

- the website domain doubles as the GTM container name and the GA4
  property/stream name (via `ga4_client`), matching the naming convention
  already in use for GA4 properties
- the store name becomes the Meta Pixel's name, as "<store name> - Dataset"
  (via `meta_client`), matching the naming convention already in use there

Neither ID is typed in by hand by default. The one deliberate exception is
`meta_pixel_id`: an operator may pass an *existing* Pixel ID to reuse instead
of creating a new one - useful because Meta pixels cannot be deleted (API
and UI both refuse it - see HANDOFF-META-PIXEL-FIX.md), so a pixel created
by mistake or during testing, that never received any real event traffic,
is otherwise permanent dead weight. A reused pixel is renamed to match the
new store, so it never keeps a stale name in Business Manager.
"""

from dataclasses import dataclass

from .errors import ValidationError
from .validators import validate_meta_pixel_id, validate_store_name, validate_website_domain

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
    meta_pixel_id=None,
    prompt=input,
):
    """Return validated StoreInputs.

    Values supplied by the caller (CLI flags) are validated once and a bad one
    is fatal, so an unattended run fails loudly instead of hanging on a prompt.
    Values left out are asked for interactively and re-asked until valid.

    `ga4_client` and `meta_client` are None during a dry run: no GA4 property
    or Meta pixel is created, and the DRY_RUN_* constants stand in for the
    real IDs.

    `meta_pixel_id`, if given, is an existing Pixel ID to reuse: it is
    validated and renamed to this store's name instead of creating a new
    pixel. Unlike `store_name`/`website_domain` there is no interactive
    prompt for it - omitting it always means "create a new pixel", so an
    unattended run's behaviour never depends on whether a terminal is
    attached.
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

    pixel_name = f"{name}{PIXEL_NAME_SUFFIX}"
    if meta_pixel_id is not None:
        pixel_id = validate_meta_pixel_id(meta_pixel_id)
        if meta_client is not None:
            meta_client.rename_pixel(pixel_id, pixel_name)
    elif meta_client is None:
        pixel_id = DRY_RUN_META_PIXEL_ID
    else:
        pixel_id = meta_client.create_pixel(pixel_name)

    return StoreInputs(
        container_name=domain,
        ga4_measurement_id=ga4_measurement_id,
        meta_pixel_id=pixel_id,
    )
