# 14 — Governance — OUT OF SCOPE

| Field | Value |
| --- | --- |
| Status | ❌ cut — governance is out of scope (foundational decision [F-4](DECISIONS.md)) |
| Backing contract | ~~API-20~~ retracted as a user-facing family |

## Decision

**MUG does not implement governance.** No authorization/roles/permissions, no admin
audit trails, no retention schedules, no deletion/data-rights workflows, no compliance
tooling.

MUG is **self-hosted**: the researcher and their institution own the database and
infrastructure, and handle access control, IRB/compliance, retention, and deletion
through their own means (their DB, their institutional processes). MUG's job is to *not
get in the way* of that — data lives in a store the researcher controls and can query,
export, or delete directly.

## Why

A permissions-and-audit platform is a large subsystem that duplicates what the
institution and the hosting infrastructure already provide. For a self-hosted research
tool driven (usually) by one lab, it's pure overhead. Cutting it removes a whole family
(API-20) and a lot of ceremony from every other surface.

## What this resolves (previously deferred to "governance")

| Deferred item | Resolution under F-4 |
| --- | --- |
| Author/operator split (D03-2) | **Not an enforced feature.** Whoever operates MUG can do everything; any split is social convention, not a grant system. |
| Deprecate/withdraw authority (D02-5) | **Author-callable, no approval gating.** |
| Who can export (surface 13) | **Ungated** — whoever runs MUG can export. |
| "Delete my data" / consent withdrawal (surface 04) | **Not a MUG feature.** The researcher handles it directly against their own data store. |
| Re-identification of `enroll_…` (surface 04) | **Not a MUG feature.** The external-ref-kept-apart mapping exists in the researcher's DB; resolving it is their own DB access, not a MUG grant. |

## What is NOT cut (deliberately preserved — these aren't governance)

- **Immutable event capture for reproducibility** (API-10; surfaces 5, 8, 13). This is
  the evidence substrate that makes replay/export trustworthy — it is *not* an admin
  audit trail and stays.
- **Secret handling** (surface 03): secrets bound by reference, never in the
  client/science, remains as a minimal **security** mechanism. Only the governance/audit/
  rotation-*authority* around secrets is cut — storing and referencing a secret is not.
- **Pseudonymous identity + external refs kept apart** (D04-1): a data-hygiene default,
  not a permission system — stays.

## Consequence for the review

There is nothing to review here — the surface is cut. The user index keeps this entry
as a tombstone so the decision is visible. Surfaces that referenced "governance
(surface 14)" now resolve per the table above.
