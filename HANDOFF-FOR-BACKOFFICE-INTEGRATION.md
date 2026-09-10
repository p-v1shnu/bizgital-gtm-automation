# Handoff — folding GTM/GA4/Meta provisioning into ShopShop Back Office

Status: draft brief, not an approved feature PRD
Audience: whoever (human or AI coding agent) implements this inside
`shopshop-backoffice`

This document exists because this whole folder (`bizgital-gtm-automation`) is
being copied into the `shopshop-backoffice` working tree so its logic can be
folded into the Back Office as a real feature, instead of staying a
standalone CLI script. It explains what already works, what still needs a
product decision, and what `shopshop-backoffice`'s own contracts require of
any implementation here. It is not itself the feature PRD that
`docs/MASTERPRD.md` §7 requires — write that separately, in
`shopshop-backoffice/docs/prd/`, before implementing, and treat everything
below as input to it.

## 1. What this folder is, and what already works

A CLI tool that takes a store's **website domain** and **store name** and
produces, fully automatically:

1. a GA4 property + web data stream (Google Analytics Admin API) →
   Measurement ID
2. a Meta Pixel named `<store name> - Dataset` (Meta Marketing API) →
   Pixel ID
3. a GTM container cloned from a golden template, with both IDs already
   wired into it, published and ready to install on the store's site

No ID is typed by hand anywhere in this flow. It has been run end-to-end
against live Google/Meta accounts (not just tests) and produced a working
container, GA4 property, and Meta pixel in one command. 107 automated tests
pass against faked GTM/GA4/Meta APIs. Full detail, including two real bugs
found and fixed during live testing (a GA4 Measurement ID double-prefix bug,
and a raw network timeout that wasn't being retried), is in `README.md` and
`docs/PRD-gtm-provisioning-en.md`.

Explicitly **not** built, on purpose:

- Meta Conversions API (server-side events) — client-side pixel only
- GTM container-level permission management for other admins
- Any GUI — this is a terminal script today

## 2. What the user wants next

Fold this capability into `shopshop-backoffice` so an operator provisions a
store's entire analytics stack (GTM + GA4 + Meta Pixel) from inside the Back
Office UI they already use to manage shops — specifically the screen shown
in the "Edit `<shop>`" modal, under **Integrations**, which today has plain
text inputs for "Google Tag Manager ID" and "Google Analytics ID" that an
operator fills in by hand. The ask is to replace (or augment) that manual
entry with the automation this folder already does.

This is a distinct, later step than the v1/v2 roadmap already recorded in
`docs/PRD-gtm-provisioning-en.md` §10 — that document already anticipated it
("GUI, or integration into the existing admin system" under "Beyond v2").

## 3. Hard constraints inherited from `shopshop-backoffice` itself

These come directly from `docs/MASTERPRD.md` and `API-CONTRACT.md` in the
backoffice repo (as of the versions read on 2026-09-08). They are not
optional preferences — they're the same rules every other Back Office
feature already follows. Read the full documents; this is a summary of the
parts most likely to be missed by someone porting logic from this Python
CLI without knowing that history.

### 3.1 The Back Office cannot write these IDs directly

`API-CONTRACT.md` documents that "Google Tag Manager ID" / "Google Analytics
ID" are part of the **Platform Brands full override** of tenant
configuration (M9), and that `tenants` is a `shopshop`-owned (Storefront)
table. Back Office **never** writes it directly — it sends a signed,
HMAC-authenticated command:

```
PATCH /api/internal/tenants/{tenantId}
Auth: BACKOFFICE_TENANT_INTERNAL_SECRET, HMAC-SHA256, 5-minute timestamp window
```

and records the attempt first in its own `backoffice_tenant_command_requests`
table (UUID + canonical payload snapshot, so a retry replays safely). So:
**the provisioning feature's job is to obtain the three IDs, then hand them
to the existing M9 command path** — it must not add a second, competing way
to write `tenants`.

### 3.2 Meta Pixel ID has no field yet

The Back Office UI currently only has GTM ID and GA ID inputs. There is no
Meta Pixel field in the schema or the M9 allow-list at all. Adding one is a
schema/contract change and needs the same approval `MASTERPRD.md` requires
for any schema change ("additive... unless explicitly approved otherwise"),
plus an `API-CONTRACT.md` update in the same session per §7. Don't assume a
column name — confirm it as part of writing the feature PRD.

### 3.3 This is exactly the "risky mutation" the Master PRD warns about

`MASTERPRD.md` §5 requires: *"Risky or cross-application mutations are
idempotent and preserve a stable request ID and payload across uncertain
outcomes."* Calling three external APIs (Google GTM, Google GA4, Meta) in
sequence, where any one of them can fail mid-way, is precisely this case —
and this Python CLI already lived through the failure mode directly: a real
test run once crashed on a network timeout *after* a GTM container had
already been created, leaving it orphaned. The CLI's answer today is "print
the orphaned resource ID so a human can clean it up" (see `README.md` → "If
a run fails"), which is fine for a human operator watching a terminal but is
**not sufficient** for a Back Office feature.

Porting this into the Back Office needs its own durable state — a table in
the same shape as `backoffice_tenant_command_requests`, tracking something
like: which store, which stage (`ga4_created`, `pixel_created`,
`gtm_created`, `applied_to_tenant`, `needs_review`), the resulting IDs so
far, and a stable idempotency key — so that a retried "Provision" click
resumes instead of creating duplicate GA4 properties / pixels / containers.
This state table doesn't exist yet in this Python project; it only exists
implicitly as printed console output. This is the single biggest piece of
new design work, not a straight port.

### 3.4 Audit and secrets rules apply unchanged

- Never write the Google service account key or the Meta System User token
  anywhere `admin_activity_logs` (or any log) can capture them. Only log the
  semantic outcome and the resulting IDs, matching how every other Back
  Office write is audited today.
- Both credentials are bearer secrets and belong in Back Office's own
  deployment secret store — the same tier as its existing R2/media
  credentials — never in a place `shopshop` (Storefront) can read.

### 3.5 Role scope

Platform Brands is a Platform-level surface. The natural role for this
action is **Platform Owner** (matching who can already edit these fields by
hand today) — confirm this explicitly in the feature PRD rather than
defaulting Shop Owner into it; `API-CONTRACT.md` is explicit that the Shop
Owner M9 sub-allow-list **excludes** analytics IDs entirely.

### 3.6 Process

`MASTERPRD.md` §7 requires, before implementation: read the Master PRD, the
applicable feature PRD, and `API-CONTRACT.md`; write or update the feature
PRD in the same session if scope/ownership/write-path changes; update
`API-CONTRACT.md` in the same session for any shared schema/API change (this
almost certainly qualifies, given §3.2 above); and §5 requires Docker
verification before any completion claim, plus focused automated test
coverage. This project's own test approach (fake GTM/GA4/Meta services
instead of hitting real APIs in tests — see `README.md` → "Tests") is a
reasonable model to mirror in Laravel/PHPUnit form.

## 4. What can be reused as design, module by module

Nothing here is copy-paste (this CLI is Python; `shopshop-backoffice` is
Laravel/Livewire), but each module is a working, tested reference for what
the equivalent PHP code needs to do:

| Python module | What it proves and what to preserve |
|---|---|
| `gtm_provisioner/ga4_client.py` | GA4 property + stream creation; the Measurement ID prefix quirk (Google's docs say no `G-` prefix comes back, live API disagreed) — validate defensively, don't trust either assumption |
| `gtm_provisioner/meta_client.py` | Meta Pixel creation via raw HTTP (no official client library exists for this); the exact permission/asset-assignment setup this depends on is in `docs/meta-marketing-api-setup.md` |
| `gtm_provisioner/gtm_client.py` | GTM container/variable/trigger/tag creation and publish sequence |
| `gtm_provisioner/remap.py` | **The most load-bearing logic in the whole project.** GTM assigns trigger/folder/custom-template IDs at creation time; a tag created with the template's own IDs is accepted by the API and then silently never fires. Any reimplementation must remap IDs exactly as described in `README.md` → "Why the trigger remapping matters" — this is the failure mode that passes a naive test and is expensive to debug in production |
| `gtm_provisioner/template.py` | Parses a GTM export or raw API `ContainerVersion`; normalizes `SCREAMING_SNAKE` enums from UI exports to the lowerCamelCase the API needs |
| `gtm_provisioner/api_retry.py` | Retry/backoff for GTM/GA4 rate limits (429/5xx) and raw network errors (a real crash source — see §3.3) |
| `gtm_provisioner/provisioner.py` | Orchestrates the whole 10-step pipeline in the mandatory order (`README.md` → "What it does") |
| `gtm_provisioner/validators.py` | Input/ID format validation, including validating IDs *returned by* Google/Meta before trusting them |
| `gtm_provisioner/store_inputs.py` | Single place that knows how each ID is obtained — a good model for keeping "get the IDs" cleanly separated from "wire them into the container", the same separation the Back Office job needs between "call the three APIs" and "apply via the M9 command" |
| `tests/` | Fake-service test pattern per client (fake GTM/GA4 objects, `monkeypatch` for Meta's raw `requests` calls) — a reasonable model for PHPUnit fakes of the same three APIs |

## 5. Configuration this feature will need

Currently in `config.yaml` (see `config.example.yaml` for the annotated
version) — all of this needs a home in Back Office's own config/secrets,
not reused as files:

- GTM account ID, GA4 account ID, Meta Business Portfolio ID, Meta ad
  account ID
- Google service account key (JSON)
- Meta System User access token (see `docs/meta-marketing-api-setup.md` for
  the exact one-time setup this depends on — App, System User, token scope,
  asset assignment; it is not obvious and has a specific gotcha around the
  `ads_management` permission not appearing until requested through the
  app's use case)
- The golden container template JSON (currently a git-ignored local file;
  decide where this template is versioned once it's inside a real app —
  it defines every tag/trigger/variable a provisioned store gets)

Pixels are created under the **Business Portfolio** ID, not the ad account —
an ad account can only ever own one pixel of its own, discovered by hitting
`(#6200) A pixel already exists for this account` on the second store
provisioned during testing. Each pixel is created under the Business, then
shared to the ad account (see `meta_client.py`'s `create_pixel` docstring
and `docs/meta-marketing-api-setup.md`). See
**`HANDOFF-META-PIXEL-FIX.md`** for the full account of this and two more
issues found the same way (an Admin System User is required, not Employee;
the sharing call's exact required parameters) — required reading before
touching this part of the integration. Both IDs are currently global config
values in this CLI, shared by every store; that may need to become per-brand
later if a client brand gets its own ad account, but is not yet needed.

## 6. Open product decisions — do not guess these

Per this org's own rule of asking rather than assuming on PRD-ambiguous
points, these need an explicit answer (in the feature PRD, from the product
owner) before or during implementation, not an implementation-time guess:

1. **Trigger and UX**: is provisioning a synchronous action on the shop edit
   modal (with the operator waiting), or a queued background job with a
   visible status (matching the `needs_review` pattern used everywhere else
   in this contract)? Given §3.3, a queued job with visible state is
   strongly implied by the existing architecture, but the PRD should say so
   explicitly.
2. **Where does Meta Pixel ID live** — new `tenants` column, alongside the
   existing GTM/GA fields? Needs sign-off and an `API-CONTRACT.md` update
   (§3.2).
3. **Partial-failure recovery UX**: if GA4 succeeds but Meta fails, does the
   operator retry the whole thing, or just the failed stage? The state table
   in §3.3 needs to support whichever answer is chosen.
4. **Re-provisioning**: what happens if "Provision" is clicked for a shop
   that already has a GTM/GA/Meta ID set — hard block, confirmation, or
   silently allowed (creating a second, orphaned set of resources)?
5. **Who can trigger it** — confirm Platform Owner-only (§3.5) rather than
   assuming.
