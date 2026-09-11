"""Input format validation, run before any API call is made."""

import re

from .errors import ValidationError

# A GA4 Measurement ID is "G-" followed by a 10-character alphanumeric suffix.
GA4_MEASUREMENT_ID_PATTERN = re.compile(r"^G-[A-Z0-9]{10}$")

# Meta Pixel IDs are numeric; currently 15 or 16 digits.
META_PIXEL_ID_PATTERN = re.compile(r"^[0-9]{15,16}$")

# Bare domain, no scheme or path: labels of letters/digits/hyphens (not
# starting or ending with a hyphen), at least one dot.
WEBSITE_DOMAIN_PATTERN = re.compile(
    r"^(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))+$"
)

MAX_CONTAINER_NAME_LENGTH = 100


def validate_website_domain(value):
    """Return the bare domain, or raise ValidationError.

    The domain doubles as both the GTM container name and the GA4 property
    name, matching the naming convention already in use, so it is checked
    against both the container name length limit and a domain shape.
    """
    domain = (value or "").strip()
    if not domain:
        raise ValidationError("Website domain must not be empty.")
    domain = re.sub(r"^https?://", "", domain, flags=re.IGNORECASE).rstrip("/")
    if len(domain) > MAX_CONTAINER_NAME_LENGTH:
        raise ValidationError(
            f"Website domain must be at most {MAX_CONTAINER_NAME_LENGTH} "
            f"characters (got {len(domain)})."
        )
    if not WEBSITE_DOMAIN_PATTERN.match(domain):
        raise ValidationError(
            f"Website domain {domain!r} is malformed. Expected a bare domain, "
            "e.g. store.shopshop.la (no https:// prefix or path)."
        )
    return domain


def validate_store_name(value):
    """Return the trimmed store name, or raise ValidationError.

    This is the human-readable name used to label the Meta Pixel (as
    "<name> - Dataset"); it is separate from the website domain, which
    labels the GA4 property and GTM container instead.
    """
    name = (value or "").strip()
    if not name:
        raise ValidationError("Store name must not be empty.")
    if len(name) > MAX_CONTAINER_NAME_LENGTH:
        raise ValidationError(
            f"Store name must be at most {MAX_CONTAINER_NAME_LENGTH} "
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
    """Return the normalised Meta Pixel ID, or raise ValidationError.

    Used both to sanity-check the ID meta_client.py gets back from creating
    a pixel (the same way validate_ga4_measurement_id checks GA4's
    response) and to validate an operator-supplied --meta-pixel-id when
    reusing an existing pixel instead of creating one.
    """
    pixel_id = (value or "").strip()
    if not pixel_id:
        raise ValidationError("Meta Pixel ID must not be empty.")
    if not META_PIXEL_ID_PATTERN.match(pixel_id):
        raise ValidationError(
            f"Meta Pixel ID {pixel_id!r} is malformed. "
            "Expected 15 or 16 digits, e.g. 123456789012345."
        )
    return pixel_id
