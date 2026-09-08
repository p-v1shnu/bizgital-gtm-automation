# GCP and Google Workspace setup

One-time setup notes for the account and project this script authenticates
against. Most of this only needs to happen once per Google Cloud
organization, not once per store.

A more detailed, narrative walkthrough of the same setup is available in
Thai at [`gcp-and-workspace-setup.th.md`](gcp-and-workspace-setup.th.md).

## Background: why a domain claim was needed

`bizgital.com` had no Google Workspace or Cloud Identity organization when
this project started, but Google still refused new signups for the domain
with:

> Someone at your organization is already using your domain for a Google
> service.

Google auto-creates a lightweight, unmanaged organization for a domain the
first time *anyone* verifies a business email on that domain with any Google
service (Ads, Analytics, an old Workspace trial, etc.). Nobody at the company
had knowingly set this up, and Search Console domain verification alone did
not clear the block — that flow is unrelated to Workspace/Cloud Identity's
own conflict check.

### Resolution

Google documents this exact case: [Can't sign up my domain for a Google
service](https://support.google.com/a/answer/80610). The fix is a specific
3-step "takeover" flow, not a normal signup:

1. Sign up for a **Business edition** Workspace trial using the business
   email address you want as your real admin (`pele@bizgital.com`),
   verified by an email code — not Search Console.
2. Complete the domain-ownership DNS verification the trial requires (a
   Cloudflare TXT record, `Name: @`). This step **merges** any other
   email-verified account already sitting on the domain into the new
   organization as a child org unit, rather than deleting or blocking it.
   In this case it surfaced one such account
   (`youtthasone@bizgital.com`, a Workspace Essentials Starter trial nobody
   at the company recognized). It was left as a suspended user rather than
   deleted outright, in case it turns out to belong to someone.
3. Once verified, add **Cloud Identity Free** from
   **Admin console → Billing → Buy or upgrade → Google Cloud management →
   Cloud Identity Free**, confirm it shows *Active*, then cancel the
   Business Starter trial from **Billing → Subscriptions** before its
   trial period ends — Cloud Identity Free is the only edition actually
   needed; Business was only the vehicle to claim the domain.

**If you ever need to redo this for another domain:** don't start at
`workspace.google.com/signup/gcpidentity/welcome` directly — it will hit the
same conflict message with no way through. Start with a Business (or
Essentials/Chrome Enterprise Upgrade) trial signup instead, as above.

## GCP project

Create the project the service account will live in **under the
organization**, not under a personal account:

1. `console.cloud.google.com` → sign in as the Workspace admin
   (`pele@bizgital.com`).
2. New Project → name it, and set **Organization / Parent resource** to
   `bizgital.com` explicitly. It will not default there.
   - If the organization doesn't show up in the picker yet, it can take a
     while to propagate from Cloud Identity into Cloud Resource Manager
     after the org is first created. It is safe to create the project under
     "No organization" and move it into the org later instead of waiting —
     the project ID does not change on a move, so nothing downstream
     (service account email, key, GTM permissions) needs to be redone.
2. Enable the **Tag Manager API** for the project.

## Service account

1. **IAM & Admin → Service Accounts → Create service account.**
   Name it something like `gtm-provisioner`. Skip the "grant access" step —
   this account needs no IAM roles; its permissions come entirely from being
   added inside GTM (see below), not from GCP IAM.
2. **Keys → Add key → Create new key → JSON.**

### Blocked key creation: organization policy

New Cloud Identity organizations enforce
`iam.managed.disableServiceAccountKeyCreation` by default (part of Google's
"Secure by Default"), which blocks creating a downloadable JSON key
entirely. To allow it for this project only, without loosening it
organization-wide:

1. **IAM & Admin → Organization Policies**, with the
   `bizgital-gtm-automation` project selected (not the organization) in the
   resource picker at the top.
2. Search for **"Disable service account key creation"**.
3. **Manage policy** → **Policy source: Override parent's policy** → **Add a
   rule** → set enforcement **Off** → **Set policy**.
4. Retry creating the key under Service Accounts → Keys.

Save the downloaded file to `secrets/service-account.json` (git-ignored).
Note the service account's email — it looks like
`gtm-provisioner@<project-id>.iam.gserviceaccount.com` — it's needed next.

## GTM permissions

In `tagmanager.google.com` → **Admin → Account** (the account column, not a
container) → **User Management → +**, add both, each as **Administrator**:

- `pele@bizgital.com` — the human admin
- the service account email from above — what the script authenticates as

Account-level access is required specifically because the script *creates*
new containers; container-level access is not enough and produces an HTTP
403 from the API.
