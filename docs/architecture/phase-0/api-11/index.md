# API-11: Storage, Artifacts, Repositories, Transactions, and Outbox

| Field | Value |
| --- | --- |
| Status | Draft |
| Contract revision | `0.2` |
| Accountable owner | Unassigned |
| Last updated | 2026-07-19 |
| Consumers | Every durable domain, API-10 (events), API-22 (jobs), API-19 (export), API-01 (stored compiled study versions) |
| Depends on | [Shared kernel 0.1](../shared-kernel/index.md), proposed ADRs 0004, 0009 |
| Implementation phase | Phase 1-2 |
| Stability tiers | SPI, archival |

## Outcome

API-11 defines how state, events, and artifacts reach a consistent durable state:
content-addressed artifact staging and finalization, a relational Unit of Work
that commits aggregate state, idempotency, canonical events, and a transaction
outbox together, and the repository/outbox SPIs the rest of the platform builds on.

The **compiled `StudyVersion` artifact** (ADR-0013) is a stored object class:
publication compiles a git commit into an immutable, resolved,
access-partitioned artifact whose bytes are stored — not rebuilt on demand — via
the same content-addressed staging/finalization path as any artifact, so
reproducibility survives toolchain rot.

## Ownership boundary

API-11 owns `ArtifactStaging`, `FinalizedArtifact`, `OutboxRecord`, and
`UnitOfWorkReceipt` plus the repository/outbox SPI. Event semantics are API-10;
job execution is API-22. Retention and deletion are not platform concerns: in a
self-hosted install they are the researcher's own database operations against
their own store (ungated; ADR-0015).

## Non-negotiable durability boundary

1. A finalized artifact's digest equals its staged intended digest; a mismatch
   is never finalized.
2. A research-significant commit writes aggregate state, idempotency record,
   canonical event, and outbox record in one relational transaction.
3. A confirmed outbox record names the events it carries.
4. Acknowledgment durability is explicit (`ReceiptDurability`).

## Current executable evidence

- 4 valid and 6 one-defect invalid examples; 13 API-11 tests including
  artifact-digest closure, outbox evidence, and rejection of retention-policy
  metadata on the durability surface (shared-kernel 0.2; ADR-0015).

## Acceptance status

`Drafted`, not `Accepted`. See the [review record](review-record.md).
