# Meta Marketing API setup

One-time setup notes for the credential `meta_client.py` authenticates with.
Unlike Google, there is no single service-account-style credential that
covers everything — Meta's Marketing API requires an App, a System User, and
an explicit asset assignment, done in two different admin surfaces
(`developers.facebook.com` and `business.facebook.com`).

## 1. Create an app

At `developers.facebook.com` → **My Apps → Create App**, pick the use case
**"Create & manage ads with Marketing API"**.

During creation, associate the app with the **Business Portfolio** that owns
the target ad account — this is required later; a System User cannot
generate a token for an app the Business doesn't own. The Dashboard's
**Business and access verification** checklist item turns green once this is
done.

Nothing else on that checklist matters for this use case — **Facebook Login
for Business**, **App Review**, and **Publish** are all for a public,
consumer-facing app. This app is never published; it stays in Development
mode indefinitely and is only ever driven by a System User token.

## 2. Create a System User

In `business.facebook.com` → Business Settings → **Users → System Users** →
**Add**.

Use **Admin** access. This contradicts the usual least-privilege advice, but
it is not optional here — confirmed live, twice: an Employee System User
with an `ads_management`-only token failed pixel creation with
`(#10) ... MANAGE_PIXELS_AUDIT_NEEDED for this business account`; adding
`business_management` to that same Employee System User's token changed
nothing, same error. Switching to an Admin System User, no other change,
fixed it immediately. Creating a brand-new pixel under a Business is
apparently an admin-level action in Meta's permission model — no permission
*scope* granted to an Employee System User's token unlocks it. Accept this
as a real trade-off rather than spending more time trying to avoid it.

## 3. Generate a token

On the System User → **Generate New Token** → select the app from step 1 →
expiration **Never** → permissions: **`ads_management`** and
**`business_management`**. `ads_management` covers sharing a created pixel
to the ad account; `business_management` covers creating it under the
Business in the first place.

If either permission doesn't appear in the list, it hasn't been requested by
the app yet:

1. Go to the app's dashboard (`developers.facebook.com` → the app) →
   **Use cases** → the "Create & manage ads" use case → **Permissions and
   features**.
2. Find the missing permission in the list. If its status isn't already
   **"Ready for testing"**, use its **Actions** menu to add it to the use
   case.
3. "Ready for testing" *is* the state that's needed — it means Standard
   Access is unlocked (the app can use this permission against its own
   assets) immediately, with no further action. Do **not** click
   **"Go to App Review"**: that's for Advanced Access (acting on other
   people's ad accounts), which this script never does, and isn't needed
   here.
4. Go back to Generate Token; the permission now appears.

The token is shown once. Copy it immediately into
`secrets/meta-access-token.txt` (nothing else in the file) — there is no way
to view it again, only to revoke it and generate a new one.

## 4. Assign the ad account

Still on the System User, tab **Assigned assets** → search by the ad
account's numeric ID (the same one that goes in `meta.ad_account_id`,
without the `act_` prefix) → add it with **Full access**. Each pixel created
under the Business is shared to this ad account right after creation
(`POST /<pixel_id>/shared_accounts`), so campaigns running on that account
can use it. Without this assignment, sharing returns an HTTP 403 even with a
correctly-scoped, Admin-owned token — the token's permission and the System
User's access to this specific asset are two separate checks.

The sharing call's `account_id` parameter is the ad account's **plain
numeric ID, with no `act_` prefix** — the one place in this whole setup that
differs from every other ad-account reference. Sending it with `act_`
prefixed returns `(#100) Param account_id must be a valid ID string`.

### Why the pixel lives on the Business, not the ad account

An ad account can only ever *own* one pixel of its own. Calling
`POST /act_<ad_account_id>/adspixels` to create a second store's pixel
against the same ad account fails with
`(#6200) A pixel already exists for this account` — discovered by hitting it
for real on the second store provisioned. A Business Portfolio can own up to
100 pixels, so every pixel is created there (`POST /<business_id>/adspixels`)
and then shared out, exactly matching how a pixel made by hand in Business
Manager already looks: its **Owner** is the Business, and the ad account
only shows up under that pixel's own **Settings → Sharing → Ad accounts**.

## Naming

Pixels created here are named `<store name> - Dataset`, matching the naming
convention already used for pixels created by hand — see the "Two names for
two different naming conventions" section in the main README.
