#!/usr/bin/env python3
"""Provision a fully configured, published GTM container for one store.

Also creates the store's GA4 property/web data stream and its Meta pixel,
feeding both resulting IDs straight into the container - the operator only
supplies the store's name and website domain.

Usage:
    python provision_gtm.py
    python provision_gtm.py --store-name "ShopShop Pigeon" --domain store.shopshop.la
    python provision_gtm.py --dry-run
"""

import argparse
import sys

from gtm_provisioner.config import DEFAULT_CONFIG_PATH, check_local_files, load_config
from gtm_provisioner.errors import ConfigError, ProvisioningError, ValidationError
from gtm_provisioner.ga4_client import Ga4Client
from gtm_provisioner.gtm_client import GtmClient
from gtm_provisioner.meta_client import MetaClient
from gtm_provisioner.provisioner import Provisioner
from gtm_provisioner.store_inputs import collect_store_inputs
from gtm_provisioner.template import audit_template, load_template

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_BAD_SETUP = 2


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Create and publish a GTM container from the golden template."
    )
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH, help="path to config.yaml")
    parser.add_argument(
        "--store-name",
        help=(
            "human-readable store name, e.g. 'ShopShop Pigeon'; prompted for "
            "if omitted. Used to name the Meta pixel, as '<name> - Dataset'"
        ),
    )
    parser.add_argument(
        "--domain",
        help=(
            "store website domain, e.g. store.shopshop.la; prompted for if "
            "omitted. Used as both the GTM container name and the GA4 "
            "property name"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate config, input and template without calling the GTM, GA4 or Meta API",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="do not stop to confirm a duplicate container name",
    )
    return parser.parse_args(argv)


def confirm(question):
    return input(question).strip().lower() in {"y", "yes"}


def run(argv=None):
    args = parse_args(argv)

    config = load_config(args.config)
    if args.dry_run:
        if not check_template_only(config):
            return EXIT_BAD_SETUP
    else:
        check_local_files(config)

    template = load_template(config.template_path)
    constant_names = (config.ga4_variable_name, config.meta_pixel_variable_name)

    print(f"Template: {template.source_path}")
    for kind, count in sorted(template.counts.items()):
        print(f"  {kind:<18} {count:>4}")

    problems = audit_template(template, constant_names)
    if problems:
        print("\nTemplate problems found:")
        for problem in problems:
            print(f"  ! {problem}")
        print("\nFix the template or the config before provisioning.")
        return EXIT_BAD_SETUP
    print("  template audit: ok\n")

    ga4_client = None if args.dry_run else Ga4Client.from_config(config)
    meta_client = None if args.dry_run else MetaClient.from_config(config)
    store = collect_store_inputs(ga4_client, meta_client, args.store_name, args.domain)

    if args.dry_run:
        print("\nDry run - nothing was sent to the GTM, GA4 or Meta API.")
        print(f"  website domain      {store.container_name}")
        print(f"  GA4 Measurement ID  {store.ga4_measurement_id} (placeholder)")
        print(f"  Meta Pixel ID       {store.meta_pixel_id} (placeholder)")
        return EXIT_OK

    print(f"\nGA4 property created, Measurement ID: {store.ga4_measurement_id}")
    print(f"Meta pixel created, ID: {store.meta_pixel_id}\n")

    client = GtmClient.from_config(config)
    provisioner = Provisioner(
        config,
        client,
        template,
        confirm=None if args.yes else confirm,
    )
    result = provisioner.run(store)

    print("")
    print("=" * 56)
    print(f"  GTM container ID: {result.public_id}")
    print("=" * 56)
    print("  Install this ID on the store's website.")
    print("  Then open the container in the GTM UI and check that every tag")
    print("  shows its correct firing trigger before calling this done.")
    return EXIT_OK if result.counts_match else EXIT_FAILED


def check_template_only(config):
    """In a dry run only the template file has to exist."""
    import os

    if os.path.isfile(config.template_path):
        return True
    print(f"Template not found at {config.template_path!r}.", file=sys.stderr)
    return False


def main(argv=None):
    try:
        return run(argv)
    except (ConfigError, ValidationError) as exc:
        print(f"\nSetup error: {exc}", file=sys.stderr)
        return EXIT_BAD_SETUP
    except ProvisioningError as exc:
        print(f"\nProvisioning failed: {exc}", file=sys.stderr)
        if exc.container_public_id:
            print(
                f"\n  A container was already created and is now incomplete:\n"
                f"    public ID: {exc.container_public_id}\n"
                f"    path:      {exc.container_path}\n"
                f"  v1 does not roll back. Delete or repair it in the GTM UI.",
                file=sys.stderr,
            )
        return EXIT_FAILED
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main())
