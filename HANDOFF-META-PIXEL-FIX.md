# Handoff — Meta Pixel creation fix

Status: describes work already done and verified live in this project;
written for whoever is porting Meta pixel creation into
`shopshop-backoffice` and has hit the same wall this document explains.
Companion to `HANDOFF-FOR-BACKOFFICE-INTEGRATION.md` (the broader
architecture brief) - read that one for the M9 signed-command boundary,
idempotency requirements, and open product decisions; this one is scoped
narrowly to "how do you actually get Meta to create a pixel."

## What was broken

The obvious, natural-looking implementation is: create the pixel directly
under the ad account (`POST /act_<ad_account_id>/adspixels`), using a
System User with Employee access and the `ads_management` permission. This
is exactly what this project's own first version did, and it works for
*one* pixel - the failure only shows up on the second store, which makes it
an easy trap to ship without noticing.

## Root causes found, in the order they were hit (each confirmed against the
real Meta API, not guessed or taken from docs)

1. **An ad account can only ever own one pixel of its own.** Real error on
   the second store: `(#6200) A pixel already exists for this account`.
   Fix: create the pixel under the **Business Portfolio** instead
   (`POST /{business_id}/adspixels`), then separately **share** it to the ad
   account. A Business can own up to 100 pixels; an ad account cannot own
   more than one.

2. **Sharing is a second, separate API call**:
   `POST /{pixel_id}/shared_accounts`. The ad account is no longer the
   pixel's *owner* - it's just something the pixel is shared *with*, so
   campaigns run from that account can use it. This is the same
   relationship every pixel created by hand in Business Manager already
   has: **Owner** = the Business; the ad account only appears under that
   pixel's own **Settings → Sharing → Ad accounts**.

3. **Creating a pixel under a Business requires an Admin System User, not
   Employee.** Confirmed live, twice, with no other variable changed each
   time: an Employee System User failed pixel creation with
   `(#10) ... requires that you can MANAGE_PIXELS_AUDIT_NEEDED for this
   business account` - first with only `ads_management` on its token, then
   again after adding `business_management` too. Switching that exact same
   setup to an Admin System User fixed it immediately. No OAuth permission
   scope unlocks this for an Employee-level System User; it is a role-level
   restriction in Meta's own permission model. Whatever System User /
   service credential the backoffice uses to call this API must be Admin,
   not Employee - a deliberate trade-off forced by Meta, not a design
   preference either of us made.

4. **The sharing call needs two required body parameters**, both confirmed
   by hitting Meta's own validation errors one at a time:
   - `business` - the Business Portfolio ID. Omit it and Meta returns
     `(#100) The parameter business is required`.
   - `account_id` - the ad account's ID as a **plain number, no `act_`
     prefix**. This is the one inconsistency in the whole setup: the
     original (wrong) creation endpoint wants `act_<id>`; this endpoint
     rejects that same prefixed form with
     `(#100) Param account_id must be a valid ID string`.

5. **Token permissions needed: `ads_management` AND `business_management`**,
   both on the same token. `business_management` covers creating the pixel
   under the Business; `ads_management` covers the sharing call.

## What not to build

Also tried: making pixels deletable via `DELETE /{pixel_id}`, to clean up
test/orphaned pixels. Confirmed dead end - Meta's Graph API rejects it
outright with `Unsupported delete request ... does not support this
operation`, even against a pixel with zero event history. Not a permission
problem: Meta simply does not support deleting a pixel, via the API or the
Business Manager UI, ever. Don't spend time on a delete feature for pixels.
The only real option for a leftover one is renaming it (e.g.
`"UNUSED - ..."`) and removing it from the ad account's Sharing list by
hand; an unshared pixel with no activity is harmless.

## The exact request shapes now in production (reference implementation)

```
POST /{business_id}/adspixels
  body: { name: "<store name> - Dataset" }
  -> { id: "<pixel_id>" }

POST /{pixel_id}/shared_accounts
  body: { business: "<business_id>", account_id: "<ad_account_id, no act_ prefix>" }
```

Both calls carry `access_token` in the same request body - a token from an
Admin System User, scoped to `ads_management` + `business_management`.

## Where to look in this project

- **`gtm_provisioner/meta_client.py`** - the tested, working reference
  implementation. Read `create_pixel()` and its docstring; every design
  decision above is explained inline, next to the code that embodies it.
- **`tests/test_meta_client.py`** - exact expected request URLs/bodies for
  both calls, plus a dedicated test per failure mode above (the
  `MANAGE_PIXELS_AUDIT_NEEDED` hint, the missing `business` param, the
  `act_`-prefix rejection). Good source to mirror when writing the
  backoffice's own tests for this.
- **`docs/meta-marketing-api-setup.md`** (English) /
  **`docs/meta-marketing-api-setup.th.md`** (Thai) - the full step-by-step
  Business Manager setup this depends on: creating the app, creating an
  **Admin** System User, generating a token with both permissions, assigning
  the ad account. Hand this to whoever administers the real Meta Business
  Manager account, not just to a coding agent.
- **`README.md`**, sections "Meta System User token and app" and "Pixel
  ownership: the Business, not the ad account" - a shorter version of the
  same story, with the config wiring.
- **`config.example.yaml`**, the `meta:` section - the three config values
  needed (`business_id`, `ad_account_id`, `access_token_path`), each with an
  inline comment explaining why it's shaped the way it is.

## Config field needed

Whatever config/settings store the backoffice integration uses needs a
**Business Portfolio ID** as its own distinct field, separate from the ad
account ID already in use for other purposes - see `config.example.yaml`'s
`meta.business_id` comment for the exact reasoning to carry over.
