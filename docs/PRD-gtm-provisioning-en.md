# PRD — GTM Container Provisioning Script

Document version: 1.0
Status: Ready for development (v1)

---

## 1. Problem

We operate an e-commerce platform serving multiple client brands, each with its own website. Every time a new store launches, a new GTM container must be configured from scratch — tags, triggers, variables, and data layer variables. This configuration is identical across all stores; the only differences are the GA4 Measurement ID and the Meta Pixel ID.

Today this is done entirely by hand, by copying values from an existing store's container. It is slow and carries a real risk of missing an entity or wiring a store to the wrong analytics account.

## 2. Goal

Build a script that accepts a store name, a GA4 Measurement ID, and a Meta Pixel ID, then provisions a fully configured and published GTM container. It returns the GTM container ID, which the operator installs on the store's website.

## 3. Scope

### In scope for v1
- Create a new GTM container under a configured GTM account
- Populate it with the full entity set from a template JSON exported from a golden container
- Apply the store-specific GA4 Measurement ID and Meta Pixel ID
- Create a version and publish it
- Return the container's public ID (`GTM-XXXXXXX` format)
- Terminal interface only

### Out of scope for v1
- No GUI or web interface
- Does not create the GA4 property (operator creates it and supplies the ID)
- Does not create the Meta Pixel (operator creates it and supplies the ID)
- Does not update existing containers (template rollout)
- Does not manage container user permissions
- Does not write results back to the platform database

## 4. Input and output

### Input
Collected interactively via terminal prompts.

| Field | Example | Required |
|---|---|---|
| Store / container name | `BRAND-A \| Web` | Yes |
| GA4 Measurement ID | `G-XXXXXXXXXX` | Yes |
| Meta Pixel ID | `123456789012345` | Yes |

### Output
- Progress messages during execution
- The GTM container public ID on success
- An error message identifying the failing step and entity on failure

## 5. Execution order

This order is mandatory and must not be rearranged.

1. **Create the container** under the account ID specified in config
2. **Enable built-in variables** listed in the template
3. **Create all user-defined variables** from the template
4. **Create all triggers** from the template, recording a mapping from each template `triggerId` to the `triggerId` returned by the API
5. **Create all tags**, substituting `firingTriggerId` and `blockingTriggerId` values using the mapping from step 4 before sending
6. **Apply store-specific IDs** by setting the two constant variables
7. **Create a version and publish**

**Why this order:** tags reference both triggers and variables. Those entities must already exist in the container, otherwise tag creation either fails or produces a tag pointing at something that does not exist.

## 6. Technical constraints

### Trigger IDs must be remapped
This is the single most important detail in the script.

`triggerId` is assigned by GTM at creation time, not by the caller. The IDs present in the template JSON will not match the IDs in a newly created container.

If tags are created using the template's `firingTriggerId` values directly, **the code will run without error but the tags will never fire on the live site.** This is a failure mode that passes a naive smoke test and is very expensive to diagnose later.

The script must build an `{ old_trigger_id: new_trigger_id }` map during step 4 and apply it during step 5, without exception.

### Variables do not need remapping
Tags reference variables by name using `{{Variable Name}}` syntax, not by ID. As long as names are preserved, references resolve correctly. No mapping required.

### Built-in variables are enabled separately
They are not included with user-defined variables and require their own API call to activate.

### Rate limits
The GTM API enforces request quotas. Creating several dozen entities in rapid succession can hit them. Implement retry with exponential backoff.

### Creation is not publication
Creating entities in a workspace does not make the container live. A version must be created and published explicitly.

## 7. Configuration and security

### Project files
| File | Purpose | Committed to git |
|---|---|---|
| Main script | All provisioning logic | Yes |
| Template JSON | Golden container structure | **No** |
| Service account key | GTM API credentials | **No** |
| Config file | GTM account ID, paths to the above | **No** |

The template JSON is excluded from git because it contains client analytics IDs.

A `.gitignore` covering these must exist from the first commit.

### Authentication
Uses a Google service account. The service account's email must be added to the GTM account with publish-level permission, otherwise the script cannot access or create containers.

## 8. Error handling

- Validate input format before doing any work — in particular, the GA4 Measurement ID must begin with `G-`
- On failure, report which step failed and which entity was being processed
- If failure occurs after the container was created, print the orphaned container ID so the operator can delete or repair it manually
- Automatic rollback is not required in v1

## 9. Acceptance criteria

1. A single command produces a GTM container ID
2. Tag, trigger, and variable counts in the new container match the template exactly
3. **Every tag shows its correct firing trigger when inspected in the GTM UI** — this must be verified visually on the first test run, not inferred from the script exiting successfully
4. GTM Preview mode confirms tags fire as expected on the live site
5. The GA4 Measurement ID and Meta Pixel ID belong to the correct store

## 10. Roadmap

### v2 — Automatic GA4 property and Meta Pixel creation

Goal: eliminate the manual step of creating the GA4 property and Meta Pixel beforehand, so the entire setup runs from one command.

**What gets added**

- Call the **GA4 Admin API** to create a property and web data stream under a configured Google Analytics account, returning a Measurement ID
- Call the **Meta Business / Marketing API** to create a pixel (dataset) under a configured Business Manager, returning a Pixel ID
- Feed both IDs directly into the existing container provisioning flow
- Operator input reduces to the store name alone

**Impact on v1 design**

v1 must cleanly separate *obtaining the IDs* from *provisioning the container*. v2 should only replace the source of those IDs — from operator input to API calls — without touching container provisioning logic.

**Additional prerequisites for v2**

- A second credential type: a Meta access token, which is a different mechanism from the Google service account
- Business Manager level permissions for asset creation
- A decision on account structure: whether all pixels live under one Business Manager or are separated per client

### Beyond v2

- Roll out new template versions to existing containers, with tracking of which store runs which template version
- Drift detection between live containers and the template
- GUI, or integration into the existing admin system
- Meta Conversions API for server-side event delivery
