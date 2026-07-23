# API-20: Governance — REMOVED (out of scope)

| Field | Value |
| --- | --- |
| Status | Removed (foundational decision F-4, recorded in ADR-0015) |
| Contract revision | — (retired; no schemas or fixtures) |
| Last updated | 2026-07-18 |

## Decision

**MUG does not implement governance.** No authorization/roles/permissions, no admin
audit trails, no retention schedules, no deletion/data-rights workflows, no compliance
tooling. API-20 is removed as a contract family; this page is a tombstone kept so the
decision stays visible.

MUG is **self-hosted**: the researcher and their institution own the database and
infrastructure, and handle access control, IRB/compliance, retention, and deletion
through their own means (their DB, their institutional processes). MUG's job is to *not
get in the way* of that — data lives in a store the researcher controls and can query,
export, or delete directly.

## Why

A permissions-and-audit platform is a large subsystem that duplicates what the
institution and the hosting infrastructure already provide. For a self-hosted research
tool driven (usually) by one lab, it is pure overhead. Cutting it removes a whole
family and a lot of ceremony from every other surface.

## What this resolves (previously deferred to "governance")

| Deferred item | Resolution under F-4 |
| --- | --- |
| Author/operator split (D03-2) | **Not an enforced feature.** Whoever operates MUG can do everything; any split is social convention, not a grant system. |
| Deprecate/withdraw authority (D02-5) | **Author-callable, no approval gating.** |
| Who can export (surface 13) | **Ungated** — whoever runs MUG can export. |
| "Delete my data" / consent withdrawal (surface 04) | **Not a MUG feature.** The researcher handles it directly against their own data store. |
| Re-identification of `enroll_…` (surface 04) | **Not a MUG feature.** The external-ref-kept-apart mapping exists in the researcher's DB; resolving it is their own DB access, not a MUG grant. |

## What is NOT cut (deliberately re-homed — these aren't governance)

- **Immutable event capture for reproducibility** → lives in
  [API-10](../api-10/index.md). This is the evidence substrate that makes replay and
  export trustworthy — it is *not* an admin audit trail and stays.
- **Minimal secret storage/reference** → lives in [API-02](../api-02/index.md) and the
  [shared kernel](../shared-kernel/index.md). Secrets are bound by reference and never
  enter the client, the science, or a study artifact — a minimal **security** mechanism.
  Only the governance/audit/rotation-*authority* around secrets is cut; storing and
  referencing a secret is not.
- **Pseudonymous identity + external refs kept apart** (API-03): a data-hygiene
  default, not a permission system — stays.

## References

- Foundational decision **F-4** (governance is out of scope), approved in the
  phase-0 user-surface review.
- **ADR-0015**, which records the removal (supersedes the governance half of
  [ADR-0011](../../decisions/0011-data-classification-retention-and-secret-references.md);
  the data-classification and secret-reference parts remain as security concerns).
- [Review record](review-record.md) for the removal decision.
