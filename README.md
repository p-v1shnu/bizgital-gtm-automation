# GTM Container Provisioning

Creates a fully configured, published Google Tag Manager container for a new
store from a golden-container template, and prints the `GTM-XXXXXXX` ID to
install on the store's website.

Scope is v1 of `docs/PRD-gtm-provisioning-en.md`: the operator creates the GA4
property and the Meta Pixel beforehand and supplies both IDs.

## What it does

1. Creates the container under the configured GTM account
2. Enables the built-in variables listed in the template
3. Creates folders and custom templates, if the template has any
4. Creates every user-defined variable, with this store's GA4 and Pixel IDs
   already substituted into the two Constant variables
5. Creates every trigger, recording `{template trigger ID: new trigger ID}`
6. Creates every tag, rewriting `firingTriggerId` and `blockingTriggerId`
   through that map
7. Reads the two Constants back to confirm they hold this store's IDs
8. Creates a version and publishes it

Step 3 is not in the PRD's numbered order. Folders and custom templates are
prerequisites — variables and tags reference them — so they are created before
step 4 rather than reordering anything the PRD mandates.

## Why the trigger remapping matters

GTM assigns `triggerId` at creation time. A tag created with the template's own
trigger IDs is accepted by the API and then never fires on the live site: the
script exits 0 and the container is silently broken.

The same trap applies to two references the PRD does not mention:

- `parentFolderId`, also assigned at creation time
- custom template tag types, of the form `cvt_<containerId>_<templateId>`,
  which embed the *old* container ID

All three are resolved through a map. An ID that cannot be resolved stops the
run rather than being passed through, except for GTM's own reserved built-in
trigger IDs (Initialization, Consent Initialization), which are passed through
deliberately.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp config.example.yaml config.yaml
```

Then, all of which stay out of git:

- put the service account key at `secrets/service-account.json`
- put the golden container export at `templates/golden-container.json`
- fill in `config.yaml`

### Service account permission

The service account's email must be added to the **GTM account** — not just to
a container — with publish permission. Account-level access is what allows a
new container to be created; container-level access is not enough and produces
an HTTP 403.

### The template file

Either shape works:

- a GTM UI export (Admin → Export Container)
- a raw `ContainerVersion` from the API's `versions.get`

A UI export writes enum values as `SCREAMING_SNAKE` (`"TEMPLATE"`,
`"CUSTOM_EVENT"`, `"ONCE_PER_EVENT"`) while the API only accepts lowerCamelCase
(`"template"`, `"customEvent"`, `"oncePerEvent"`). The loader converts them.
A template that already came from the API passes through unchanged.

The two Constant variable names in `config.yaml` must match the template
exactly. If they do not, the run stops before any container is created and
lists the Constant variables the template does contain.

## Running

```bash
# interactive
.venv/bin/python provision_gtm.py

# unattended
.venv/bin/python provision_gtm.py \
  --name "BRAND-A | Web" --ga4 G-XXXXXXXXXX --pixel 123456789012345

# validate config, input and template without touching the GTM API
.venv/bin/python provision_gtm.py --dry-run
```

`--dry-run` needs no credentials. It runs every consistency check the live run
would hit mid-flight, so a freshly exported template can be validated before
any container exists.

Exit codes: `0` success, `1` provisioning failed, `2` bad config, input or
template.

## After a successful run

The script exiting cleanly is not the acceptance test. Per PRD section 9:

1. Open the new container in the GTM UI and confirm **every tag shows its
   correct firing trigger**. Verify this visually on the first run for a new
   template — do not infer it from the exit code.
2. Confirm the tag, trigger and variable counts match the template. The script
   prints this comparison.
3. Install the container ID on the store's site and confirm in GTM Preview mode
   that the tags fire.
4. Confirm the GA4 Measurement ID and Meta Pixel ID belong to this store.

## If a run fails

There is no automatic rollback in v1. On failure the script prints the failing
step, the entity it was processing, and — if the container was already created
— its public ID and path, so it can be deleted or repaired in the GTM UI.

## Tests

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

The suite runs entirely against a fake GTM API. The fake hands out IDs unlike
the template's, so any tag that keeps a template trigger ID fails a test.

## Layout

| Path | Purpose | In git |
|---|---|---|
| `provision_gtm.py` | CLI entry point | yes |
| `gtm_provisioner/store_inputs.py` | where the store IDs come from | yes |
| `gtm_provisioner/template.py` | template parsing and offline audit | yes |
| `gtm_provisioner/remap.py` | trigger, folder and custom template ID maps | yes |
| `gtm_provisioner/gtm_client.py` | API wrapper, retry and throttling | yes |
| `gtm_provisioner/provisioner.py` | the seven steps | yes |
| `config.yaml` | account ID and local paths | no |
| `secrets/service-account.json` | GTM API credentials | no |
| `templates/golden-container.json` | contains client analytics IDs | no |

`store_inputs.py` is the only module that knows how the GA4 and Pixel IDs are
obtained. v2 replaces its body with GA4 Admin API and Meta Marketing API calls
and touches nothing else.
