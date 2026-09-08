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

Use **Employee** access, not Admin. Admin System Users have broad,
business-wide administrative power; this task only needs to create pixels
under one ad account, so Employee access plus a narrow asset assignment
(step 4) is the least-privilege choice.

## 3. Generate a token

On the System User → **Generate New Token** → select the app from step 1 →
expiration **Never** → permissions: **`ads_management`** only.

If `ads_management` doesn't appear in the permission list, it hasn't been
requested by the app yet:

1. Go to the app's dashboard (`developers.facebook.com` → the app) →
   **Use cases** → the "Create & manage ads" use case → **Permissions and
   features**.
2. Find `ads_management` in the list. If its status isn't already
   **"Ready for testing"**, use its **Actions** menu to add it to the use
   case.
3. "Ready for testing" *is* the state that's needed — it means Standard
   Access is unlocked (the app can use this permission against its own
   assets) immediately, with no further action. Do **not** click
   **"Go to App Review"**: that's for Advanced Access (acting on other
   people's ad accounts), which this script never does, and isn't needed
   here.
4. Go back to Generate Token; `ads_management` now appears.

The token is shown once. Copy it immediately into
`secrets/meta-access-token.txt` (nothing else in the file) — there is no way
to view it again, only to revoke it and generate a new one.

## 4. Assign the ad account

Still on the System User, tab **Assigned assets** → search by the ad
account's numeric ID (the same one that goes in `meta.ad_account_id` in
`config.yaml`, without the `act_` prefix) → add it with **Full access**.

Without this, `POST /act_<id>/adspixels` returns an HTTP 403 even with a
valid, correctly-scoped token — the token's permission and the System User's
access to the specific asset are two separate checks.

## Naming

Pixels created here are named `<store name> - Dataset`, matching the naming
convention already used for pixels created by hand — see the "Two names for
two different naming conventions" section in the main README.
