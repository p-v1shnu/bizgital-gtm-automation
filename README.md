# GTM Container Provisioning

Creates a GA4 property, its web data stream, and a fully configured, published
Google Tag Manager container for a new store from a golden-container
template, and prints the `GTM-XXXXXXX` ID to install on the store's website.

v1 scope is `docs/PRD-gtm-provisioning-en.md`; automatically creating the GA4
property is a piece of the PRD's v2 roadmap, brought forward early. The
operator still creates the Meta Pixel beforehand and supplies its ID — only
GA4 is automated so far.

## What it does

1. Creates a GA4 property and web data stream for the store's website domain,
   and reads back the Measurement ID
2. Creates the container under the configured GTM account
3. Enables the built-in variables listed in the template
4. Creates folders and custom templates, if the template has any
5. Creates every user-defined variable, with this store's GA4 and Pixel IDs
   already substituted into the two Constant variables
6. Creates every trigger, recording `{template trigger ID: new trigger ID}`
7. Creates every tag, rewriting `firingTriggerId` and `blockingTriggerId`
   through that map
8. Reads the two Constants back to confirm they hold this store's IDs
9. Creates a version and publishes it

Step 4 is not in the PRD's numbered order for container provisioning. Folders
and custom templates are prerequisites — variables and tags reference them —
so they are created before step 5 rather than reordering anything the PRD
mandates.

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

Two separate grants are needed, in two separate admin UIs — neither implies
the other:

- The service account's email must be added to the **GTM account** (not just
  a container) with publish permission. Account-level access is what allows a
  new container to be created; container-level access is not enough and
  produces an HTTP 403.
- The same service account's email must also be added to the **GA4 Account**
  configured under `ga4.account_id`, from Google Analytics' own
  **Admin → Account Access Management**, with Editor access. Without it,
  creating a property returns an HTTP 403 naming this exact requirement.

Creating the GCP project and service account this key belongs to, including
the Google Workspace/Cloud Identity setup behind it, is documented separately
in [`docs/gcp-and-workspace-setup.md`](docs/gcp-and-workspace-setup.md).

### Other admins only get read access to a newly created container

GTM has two separate permission layers: account-level (Admin/User) and
container-level (No Access/Read/Edit/Approve/Publish). Account Admin does not
imply Publish on a container it didn't create — only the service account,
as the container's creator, gets full access automatically. Every other
account admin starts with a lower default on that specific new container and
needs an explicit container-level grant to edit or publish it.

This is deliberate, not a bug: PRD section 3 lists "manage container user
permissions" as out of scope for v1. An operator who needs to edit or publish
a container this script created adds themselves under that container's own
**User Management** (not the account's) in the GTM UI.

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

### GA4 property naming and the Measurement ID prefix

The store's website domain (e.g. `store.shopshop.la`, no `https://` or path)
is used as both the GTM container name and the GA4 property/stream display
name, matching the convention already in use for existing properties. It also
becomes the web data stream's `defaultUri` (as `https://<domain>`).

Google's docs describe the Measurement ID as returned **without** its `G-`
prefix (e.g. `1A2BCD345E`, not `G-1A2BCD345E`), but a live property created
against v1beta returned it already prefixed. `ga4_client.py` checks for the
prefix rather than assuming either way, and validates the result before it
goes anywhere near the container — a silently mishandled prefix here would be
the same failure mode as the trigger ID remapping: no error, just a container
permanently wired to the wrong GA4 property.

## Running

```bash
# interactive
.venv/bin/python provision_gtm.py

# unattended
.venv/bin/python provision_gtm.py --domain store.shopshop.la --pixel 123456789012345

# validate config, input and template without touching the GTM or GA4 API
.venv/bin/python provision_gtm.py --dry-run
```

`--dry-run` needs no credentials. It runs every consistency check the live run
would hit mid-flight, so a freshly exported template can be validated before
any container or GA4 property exists. No GA4 property is created in a dry
run; a placeholder Measurement ID stands in for the real one.

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
4. Confirm the created GA4 property's Measurement ID and the Meta Pixel ID
   belong to this store.

## If a run fails

There is no automatic rollback. On failure the script prints the failing
step, the entity it was processing, and:

- if the GTM container was already created, its public ID and path, so it
  can be deleted or repaired in the GTM UI
- if the GA4 property was created but its web data stream creation then
  failed, the property's resource name, so it can be deleted or repaired in
  Google Analytics — this is checked before the GTM container is even
  created, so a failure here never leaves a broken GTM container behind

## Tests

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

The suite runs entirely against fake GTM and GA4 APIs. The fake GTM client
hands out IDs unlike the template's, so any tag that keeps a template trigger
ID fails a test; the fake GA4 responses cover the missing-prefix and
orphaned-property failure modes explicitly.

## Layout

| Path | Purpose | In git |
|---|---|---|
| `provision_gtm.py` | CLI entry point | yes |
| `gtm_provisioner/store_inputs.py` | where the store IDs come from | yes |
| `gtm_provisioner/ga4_client.py` | GA4 property/stream creation | yes |
| `gtm_provisioner/api_retry.py` | shared retry/backoff/throttle for both API clients | yes |
| `gtm_provisioner/template.py` | template parsing and offline audit | yes |
| `gtm_provisioner/remap.py` | trigger, folder and custom template ID maps | yes |
| `gtm_provisioner/gtm_client.py` | GTM API wrapper | yes |
| `gtm_provisioner/provisioner.py` | the GTM container provisioning steps | yes |
| `config.yaml` | account IDs and local paths | no |
| `secrets/service-account.json` | GTM and GA4 API credentials | no |
| `templates/golden-container.json` | contains client analytics IDs | no |

`store_inputs.py` is the only module that knows how the GA4 Measurement ID
and Meta Pixel ID are obtained: the website domain resolves to a Measurement
ID via `ga4_client.py`, while the Pixel ID is still operator-supplied. A
future step to create the Meta Pixel itself (via the Meta Marketing API)
would extend this module the same way, without touching GTM provisioning.
