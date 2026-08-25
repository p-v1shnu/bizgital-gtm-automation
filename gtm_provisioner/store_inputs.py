"""Where the store-specific IDs come from.

This module is deliberately the only place that knows how the GA4 Measurement
ID and Meta Pixel ID are obtained. In v1 the operator supplies them. v2 is
expected to replace the body of `collect_store_inputs` with GA4 Admin API and
Meta Marketing API calls without touching any provisioning logic.
"""

from dataclasses import dataclass

from .errors import ValidationError
from .validators import (
    validate_container_name,
    validate_ga4_measurement_id,
    validate_meta_pixel_id,
)


@dataclass(frozen=True)
class StoreInputs:
    """The three values that make one provisioning run store-specific."""

    container_name: str
    ga4_measurement_id: str
    meta_pixel_id: str


_FIELDS = (
    ("container_name", "Store / container name (e.g. BRAND-A | Web)", validate_container_name),
    ("ga4_measurement_id", "GA4 Measurement ID (G-XXXXXXXXXX)", validate_ga4_measurement_id),
    ("meta_pixel_id", "Meta Pixel ID (15-16 digits)", validate_meta_pixel_id),
)


def collect_store_inputs(
    container_name=None,
    ga4_measurement_id=None,
    meta_pixel_id=None,
    prompt=input,
):
    """Return validated StoreInputs.

    Values supplied by the caller (CLI flags) are validated once and a bad one
    is fatal, so an unattended run fails loudly instead of hanging on a prompt.
    Values left out are asked for interactively and re-asked until valid.
    """
    supplied = {
        "container_name": container_name,
        "ga4_measurement_id": ga4_measurement_id,
        "meta_pixel_id": meta_pixel_id,
    }
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

    return StoreInputs(**collected)
