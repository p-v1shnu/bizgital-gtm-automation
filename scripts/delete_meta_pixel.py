#!/usr/bin/env python3
"""One-off utility: delete one or more Meta pixels via the Graph API.

Business Manager's UI has no delete button for pixels at all - deleting via
the API is the only way to actually remove one, and Meta only allows it for
a pixel with no event history. A rejection here usually means the pixel
already has activity and can't be deleted that way; rename it (e.g.
"UNUSED - ...") and remove it from the ad account's Sharing list by hand
instead - see docs/meta-marketing-api-setup.md.

Uses the same config.yaml and Meta access token as provision_gtm.py - no
separate credential needed.

Usage:
    python scripts/delete_meta_pixel.py 1068404792566487 1390764302550071
    python scripts/delete_meta_pixel.py --config path/to/config.yaml 123456789012345
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gtm_provisioner.config import DEFAULT_CONFIG_PATH, load_config  # noqa: E402
from gtm_provisioner.errors import ConfigError, ProvisioningError  # noqa: E402
from gtm_provisioner.meta_client import MetaClient  # noqa: E402

EXIT_OK = 0
EXIT_SOME_FAILED = 1
EXIT_BAD_SETUP = 2


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pixel_ids", nargs="+", help="one or more Pixel IDs to delete")
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH, help="path to config.yaml")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    try:
        config = load_config(args.config)
        client = MetaClient.from_config(config)
    except ConfigError as exc:
        print(f"Setup error: {exc}", file=sys.stderr)
        return EXIT_BAD_SETUP

    exit_code = EXIT_OK
    for pixel_id in args.pixel_ids:
        try:
            client.delete_pixel(pixel_id)
            print(f"{pixel_id}: deleted")
        except ProvisioningError as exc:
            print(f"{pixel_id}: FAILED - {exc}", file=sys.stderr)
            exit_code = EXIT_SOME_FAILED
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
