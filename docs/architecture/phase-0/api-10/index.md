# API-10: Events, Capture, Provenance, and Projections

| Field | Value |
| --- | --- |
| Status | Draft |
| Contract revision | `0.2` |
| Accountable owner | Unassigned |
| Last updated | 2026-07-19 |
| Consumers | All evidence-producing domains, API-11 (storage), API-16 (replay), API-19 (export) |
| Depends on | [Shared kernel 0.2](../shared-kernel/index.md), proposed ADRs 0004, 0006, 0010 |
| Implementation phase | Phase 1 |
| Stability tiers | Wire, archival |

## Outcome

API-10 defines canonical evidence: an append-only `EventEnvelope` with stable
occurrence identity, producer epoch/sequence, schema version, payload digest,
causation, and privacy classification. It separates the **canonical** stream
(what the system authoritatively accepted) from the **experienced** stream (what
a participant was actually delivered), so replay and analysis can tell them apart.

API-10 is the **sole home of immutable event capture for reproducibility**
(F-4, D08-6). It is explicitly **not** an admin audit trail: with governance
out of scope (ADR-0015), no authorization/audit/retention layer exists in the
platform, and this family's purpose is scientific — every action, message, and
response becomes a normalized recorded event so that runs can be replayed,
exported, and analyzed faithfully. Capture guarantees are unchanged: a durable
receipt still means "your response was saved" (D05-6, D08-6), invisible to the
participant and exact for the researcher.

## Ownership boundary

API-10 owns the event envelope, stream/cursor/append semantics, `CapturePolicy`,
and the canonical/experienced distinction. Physical storage and transactions are
API-11; replay assembly is API-16. Retention and deletion are not platform
concerns: in a self-hosted install they are the researcher's own database
operations against their own store (ADR-0015).

## Non-negotiable evidence boundary

1. A research event is immutable, schema-versioned, and carries producer epoch,
   sequence, and content digest.
2. Producer positions are monotonic within an epoch; causation is explicit.
3. Canonical and experienced streams are distinct whenever delivery, speculation,
   rollback, or streaming can differ.
4. No secret label is a research-data privacy classification.

## Current executable evidence

- 4 valid and 7 one-defect invalid examples; 15 API-10 tests including producer
  monotonicity, canonical/experienced profile enforcement, and rejection of
  retention declarations anywhere in the capture surface (ADR-0015).

## Acceptance status

`Drafted`, not `Accepted`. See the [review record](review-record.md).
