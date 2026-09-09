# GTM Container Provisioning

Creates a GA4 property and web data stream, a Meta pixel, and a fully
configured, published Google Tag Manager container for a new store from a
golden-container template, and prints the `GTM-XXXXXXX` ID to install on the
store's website.

v1 scope is `docs/PRD-gtm-provisioning-en.md`; automatically creating the GA4
property and the Meta Pixel are pieces of the PRD's v2 roadmap, brought
forward early. The operator supplies just a store name and website domain —
neither ID is typed in by hand.

## What it does

1. Creates a GA4 property and web data stream for the store's website domain,
   and reads back the Measurement ID
2. Creates a Meta pixel named `<store name> - Dataset` under the configured
   ad account, and reads back its Pixel ID
3. Creates the container under the configured GTM account
4. Enables the built-in variables listed in the template
5. Creates folders and custom templates, if the template has any
6. Creates every user-defined variable, with this store's GA4 and Pixel IDs
   already substituted into the two Constant variables
7. Creates every trigger, recording `{template trigger ID: new trigger ID}`
8. Creates every tag, rewriting `firingTriggerId` and `blockingTriggerId`
   through that map
9. Reads the two Constants back to confirm they hold this store's IDs
10. Creates a version and publishes it

Step 5 is not in the PRD's numbered order for container provisioning. Folders
and custom templates are prerequisites — variables and tags reference them —
so they are created before step 6 rather than reordering anything the PRD
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
- put the Meta System User access token at `secrets/meta-access-token.txt`
  (nothing but the token string)
- put the golden container export at `templates/golden-container.json`
- fill in `config.yaml`

### Google service account permission

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

### Meta System User token and app

Unlike Google, one credential does not cover both products used here — the
Meta pixel needs its own, entirely separate setup:

1. Create an app at `developers.facebook.com` with the "Create & manage ads
   with Marketing API" use case, and claim it under the Business that owns
   the target ad account.
2. In `business.facebook.com` → Business Settings → **Users → System Users**,
   add one (Employee access is enough — least privilege; it does not need to
   be an Admin System User).
3. Generate a token for that System User, scoped to the app from step 1 with
   the **`ads_management`** permission and no expiration.
4. Under that System User's **Assigned assets**, add the Business Portfolio
   configured under `meta.business_id` with access to create pixels — this
   is where pixels are actually created (see "Pixel ownership" below).
5. Also under **Assigned assets**, add the ad account configured under
   `meta.ad_account_id` with Full access — this is where each created pixel
   is shared to afterward, so campaigns on that account can use it.

### Pixel ownership: the Business, not the ad account

Pixels are created under `meta.business_id`, not `meta.ad_account_id`. An ad
account can only ever *own* one pixel of its own — creating a second one
under it fails with `(#6200) A pixel already exists for this account`, a
failure discovered by hitting it for real on the second store provisioned.
A Business Portfolio can own up to 100 pixels, so `meta_client.py` creates
each pixel there and then shares it to the ad account, mirroring exactly how
every pixel already made by hand in Business Manager is set up: **Owner** is
the Business, and the ad account only appears under that pixel's own
**Sharing → Ad accounts** list.

`ads_management` may not appear when generating the token until the app's use
case has actually requested it — if it's missing, go to the app's dashboard →
the use case → **Permissions and features** and add it there first; that
unlocks it for Standard Access (the app's own ad account) immediately, with
no App Review needed. App Review is only for Advanced Access (acting on
*other* people's ad accounts), which this script never does.

A step-by-step walkthrough of the same setup, with the exact screens
encountered, is in
[`docs/meta-marketing-api-setup.md`](docs/meta-marketing-api-setup.md) (or
[the Thai version](docs/meta-marketing-api-setup.th.md)).

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

### Two names for two different naming conventions

There are two operator inputs because GA4/GTM and Meta already name things
differently, and this just follows each product's existing convention rather
than inventing a third one:

- the **website domain** (e.g. `store.shopshop.la`, no `https://` or path) is
  used as the GTM container name and the GA4 property/stream display name,
  and becomes the web data stream's `defaultUri` (as `https://<domain>`)
- the **store name** (e.g. `ShopShop Pigeon`) is used only to name the Meta
  pixel, as `<store name> - Dataset`

### The GA4 Measurement ID prefix

Google's docs describe the Measurement ID as returned **without** its `G-`
prefix (e.g. `1A2BCD345E`, not `G-1A2BCD345E`), but a live property created
against v1beta returned it already prefixed. `ga4_client.py` checks for the
prefix rather than assuming either way, and validates the result before it
goes anywhere near the container — a silently mishandled prefix here would be
the same failure mode as the trigger ID remapping: no error, just a container
permanently wired to the wrong GA4 property. `meta_client.py` validates the
Pixel ID it gets back the same way, for the same reason.

## Running

```bash
# interactive
.venv/bin/python provision_gtm.py

# unattended
.venv/bin/python provision_gtm.py --store-name "ShopShop Pigeon" --domain store.shopshop.la

# validate config, input and template without touching the GTM, GA4 or Meta API
.venv/bin/python provision_gtm.py --dry-run
```

`--dry-run` needs no credentials. It runs every consistency check the live run
would hit mid-flight, so a freshly exported template can be validated before
any container, GA4 property or Meta pixel exists. Nothing is created in a dry
run; placeholder IDs stand in for the real ones.

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
4. Confirm the created GA4 property's Measurement ID and the created Meta
   pixel's ID belong to this store.

## If a run fails

There is no automatic rollback. On failure the script prints the failing
step, the entity it was processing, and:

- if the GTM container was already created, its public ID and path, so it
  can be deleted or repaired in the GTM UI
- if the GA4 property was created but its web data stream creation then
  failed, the property's resource name, so it can be deleted or repaired in
  Google Analytics
- if the Meta pixel was created but sharing it to the ad account then
  failed, the pixel's ID, so sharing can be fixed by hand in Business
  Manager or the pixel deleted

GA4 property creation runs first, then the Meta pixel, then the GTM
container — each stage happens before the next resource is created, so a
failure at any stage only ever leaves the resources from earlier stages
behind, never anything created after it.

## Tests

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

The suite runs entirely against fake GTM, GA4 and Meta APIs (the Meta one by
monkeypatching `requests.post`, since Meta has no client library to fake
through a service object the way GTM and GA4 do). The fake GTM client hands
out IDs unlike the template's, so any tag that keeps a template trigger ID
fails a test; the fake GA4 and Meta responses cover their missing-ID,
malformed-ID and (for GA4) orphaned-property failure modes explicitly.

## Layout

| Path | Purpose | In git |
|---|---|---|
| `provision_gtm.py` | CLI entry point | yes |
| `gtm_provisioner/store_inputs.py` | where the store IDs come from | yes |
| `gtm_provisioner/ga4_client.py` | GA4 property/stream creation | yes |
| `gtm_provisioner/meta_client.py` | Meta pixel creation | yes |
| `gtm_provisioner/api_retry.py` | shared retry/backoff/throttle for the googleapiclient-based clients | yes |
| `gtm_provisioner/template.py` | template parsing and offline audit | yes |
| `gtm_provisioner/remap.py` | trigger, folder and custom template ID maps | yes |
| `gtm_provisioner/gtm_client.py` | GTM API wrapper | yes |
| `gtm_provisioner/provisioner.py` | the GTM container provisioning steps | yes |
| `config.yaml` | account IDs and local paths | no |
| `secrets/service-account.json` | GTM and GA4 API credentials | no |
| `secrets/meta-access-token.txt` | Meta System User access token | no |
| `templates/golden-container.json` | contains client analytics IDs | no |

`store_inputs.py` is the only module that knows how the GA4 Measurement ID
and Meta Pixel ID are obtained: the website domain resolves to a Measurement
ID via `ga4_client.py`, and the store name resolves to a Pixel ID via
`meta_client.py`. Neither ID is operator-supplied any more.
