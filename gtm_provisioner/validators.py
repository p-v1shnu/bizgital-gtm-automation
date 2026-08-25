"""Input format validation, run before any API call is made."""

import re

from .errors import ValidationError

# A GA4 Measurement ID is "G-" followed by a 10-character alphanumeric suffix.
GA4_MEASUREMENT_ID_PATTERN = re.compile(r"^G-[A-Z0-9]{10}$")

# Meta Pixel IDs are numeric; currently 15 or 16 digits.
META_PIXEL_ID_PATTERN = re.compile(r"^[0-9]{15,16}$")

MAX_CONTAINER_NAME_LENGTH = 100


def validate_container_name(value):
    """Return the trimmed container name, or raise ValidationError."""
    name = (value or "").strip()
    if not name:
        raise ValidationError("Store / container name must not be empty.")
    if len(name) > MAX_CONTAINER_NAME_LENGTH:
        raise ValidationError(
            f"Store / container name must be at most {MAX_CONTAINER_NAME_LENGTH} "
            f"characters (got {len(name)})."
        )
    return name


def validate_ga4_measurement_id(value):
    """Return the normalised GA4 Measurement ID, or raise ValidationError."""
    measurement_id = (value or "").strip().upper()
    if not measurement_id:
        raise ValidationError("GA4 Measurement ID must not be empty.")
    if not measurement_id.startswith("G-"):
        raise ValidationError(
            f"GA4 Measurement ID must start with 'G-' (got {measurement_id!r}). "
            "A 'UA-' or 'GT-' ID is not a GA4 Measurement ID."
        )
    if not GA4_MEASUREMENT_ID_PATTERN.match(measurement_id):
        raise ValidationError(
            f"GA4 Measurement ID {measurement_id!r} is malformed. "
            "Expected the form G-XXXXXXXXXX."
        )
    return measurement_id


def validate_meta_pixel_id(value):
    """Return the normalised Meta Pixel ID, or raise ValidationError."""
    pixel_id = (value or "").strip()
    if not pixel_id:
        raise ValidationError("Meta Pixel ID must not be empty.")
    if not META_PIXEL_ID_PATTERN.match(pixel_id):
        raise ValidationError(
            f"Meta Pixel ID {pixel_id!r} is malformed. "
            "Expected 15 or 16 digits, e.g. 123456789012345."
        )
    return pixel_id
