---
id: ADR-0001
title: Resolve capture settings before worker launch
revision: 1
state:
decision_date:
revision_date: 2026-11-22
approved_by:
approved_revision:
approval_ref:
---

# Resolve capture settings before worker launch — proposal, edition 1

## Scope and context

The [5.0.0 PRD](2026-11-22-xpwebapi-5.0.0-prd.md) includes capture profiles
for people starting capture manually. `xpwebapi-capture` currently takes an
explicit protocol-v1 request file and hashes its bytes for provenance. Existing
programmatic callers produce that file and own the output paths.

## Alternatives

- Keep the current CLI alone. This preserves one input source, with profile
  merging left to each caller.
- Add layered settings inside the worker. This saves a launcher entry point
  but allows values from outside the request file to affect captures and
  requires a new provenance contract to account for those values.
- Resolve settings in a human-facing launcher and pass a materialized request
  to the existing worker. This adds an entry point and retains the worker's
  existing evidence contract.

## Proposed decision

Add a separate launcher using `pydantic-settings`. It accepts an explicit base
request and optionally a named profile from an explicitly selected TOML file.
For launcher-managed fields, use this order from highest to lowest priority:
explicit flags, `XPWEBAPI_CAPTURE_` environment variables, the selected
profile, and values from the base request or its existing protocol defaults.
An omitted flag does not replace a lower-priority value. The launcher does not
discover dotenv files or accept policy fields through its settings sources.

Limit the initial settings surface to transport connection and timeout fields
for the transport declared in the base request, and the capture time limit.
Keep transport choice, identity checks, sample declarations, output paths, and
read-only enforcement under the existing explicit request and CLI contracts.
Validate the resolved request with the existing protocol-v1 model. Write it to
an explicitly named, new file beside the base request so relative stop paths
retain their meaning. Launch the existing worker with that file and explicit
output paths. The worker hashes exactly the file it executes.

## Confirmation

Tests must cover source precedence, invalid and forbidden overrides, relative
path preservation, and matching executed-request and provenance hashes. Run
the existing worker tests to verify machine-oriented invocations and read-only
controls. This decision applies only to xpwebapi. The gzkit and GZ Starter issues
are independent proposals.

## Approval evidence

Pending separate approval of ADR-0001 edition 1. The PRD approval establishes
release scope and the intended audience for profiles.
