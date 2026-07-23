# ADR 0004: Relational State, Event Evidence, and Artifact Storage

| Field | Value |
| --- | --- |
| Status | Accepted |
| Accepted | 2026-07-20 (ratification; relational / event / artifact storage tiers folded in API-11; per-family freeze separate) |
| Date | 2026-07-16 |
| Last updated | 2026-07-20 |
| Owners | Unassigned |
| Affects | API-04, API-06, API-10, API-11, API-16, API-18, API-19 |

## Context

The platform needs transactional participant progression and treatment state,
append-only research evidence, and high-volume binary/trajectory content. No
single storage representation serves all three well.

## Decision

Use:

- A relational system of record for current domain state, revisions, searchable
  metadata, idempotency, lifecycle projections, and a transaction outbox
- Append-only versioned event streams for scientific and lifecycle evidence
- Immutable object/artifact storage for trajectories, render data, snapshots,
  media, model/tool content, source packages, bundles, and exports
- Ephemeral lease/presence storage only for coordination

Use SQLite/local artifacts as a reference development backend and
PostgreSQL/S3-compatible storage as the production target. High-frequency
events are chunked; one relational row per frame is not the default.

For a durable domain command, one relational Unit of Work atomically commits
the aggregate revision, idempotency key/result, canonical research events, and
outbox entries. Artifact bytes are staged and integrity-verified before that
transaction commits their metadata/reference. APIs distinguish
volatile high-rate `IngressReceipt`, relational `CommitReceipt`, and
`ArtifactCommitReceipt` rather than returning an ambiguous success.

## Invariants

- No committed record points to artifact bytes that were uncommitted or
  unverified at acceptance time.
- Later object outage or bit rot changes explicit availability/integrity state
  and retracts dependent capabilities; storage is not assumed infallible.
- Artifact staging/orphan states are explicit and recoverable.
- Redis or process memory is never canonical research state.
- A recorded correction appends evidence rather than rewriting history.
- Operational telemetry is not the scientific source of truth.

## Alternatives considered

### Fully event-source every domain object

Rejected for the initial architecture because it raises projection and
operational complexity without clear value for all control-plane state.

### Store everything as database rows

Rejected because trajectories, render streams, media, and model/tool artifacts
are large, chunked, and naturally object-oriented.

### Store everything as files

Rejected because visits, assignments, idempotency, leases, responses, and
concurrent progression need transactional constraints and queries.

## Validation

Backend conformance tests cover duplicate commands, optimistic conflicts,
interrupted uploads, transaction/object-store crash ordering, orphan cleanup,
integrity failure, backup/restore, lineage, and the honest consequences of
institution-executed deletion.
