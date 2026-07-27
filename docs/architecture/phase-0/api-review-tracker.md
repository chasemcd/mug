# Phase 0 API Review Tracker

| Field | Value |
| --- | --- |
| Status | Phase 0 CLOSED as-is (2026-07-20) |
| Purpose | Phase 0 planning tracker (closed; carried forward to implementation) |
| Last updated | 2026-07-20 |

> **Phase 0 closed as-is (2026-07-20).** The decision ledger is final — all 15
> ADRs (0001–0015) Accepted — and the shared-kernel **core layer is frozen**
> (ADR-0008/0011; digest `f675d9ec`), the one locked v1 contract. The remaining
> families stay **Drafted (design-accepted)**: their schemas + fixtures pass the
> 638-test suite, but their per-family byte-freeze (G8) — plus the kernel runtime
> layer (ADR-0009/0010), the new evidence classes (NS golden traces, fault
> fixtures), and the routed family follow-ups — are **deferred to the
> implementation phase**, where each family runs its own G0–G8 (adversarial panel
> + freeze) against running code. See `scratch/phase0-review/PROMOTION-PLAN.md`
> §17 for the closure record. A `Drafted` status below therefore means
> design-accepted, not frozen.
>
> **Update (2026-07-25): the mechanical half of that deferred freeze now runs.**
> The [contract freeze tracker](contract-freeze.md) pins every bundle's bytes to
> a digest, reads that digest back through the runtime package that serves the
> contract, and refuses a change that is not recorded. Every record the corpus
> declares now has a fixture behind it: the last five that no `$ref` walk reached
> (API-01's compiler and publication records, the kernel's `EventCursor`) were
> closed with golden fixtures on the same date, with no schema change. `Drafted`
> still means what it says above -- the adversarial panel and the accountable
> owner's sign-off are a person's work, and no bundle carries one yet.

The [API catalog](api-catalog.md) establishes scope. This tracker establishes
the working order and evidence required to accept each contract. `Not started`
means that the catalog entry exists but no dedicated API specification has yet
passed review. `Drafted` means a concrete specification and fixtures exist but
review sign-off and acceptance gates remain open.

## Foundational decisions

These are blockers for every domain specification:

| Foundation | Status | Required output |
| --- | --- | --- |
| [Shared IDs and resource hierarchy](shared-kernel/identifiers-and-resource-hierarchy.md) | Core-layer Accepted (ADR-0008, 2026-07-20) | Identifier types, canonical serialization, occurrence/version rules |
| [Schema and protocol evolution](shared-kernel/serialization-and-schema-evolution.md) | Core-layer Accepted (ADR-0008, 2026-07-20) | Schema language, reader/upcaster policy, unknown-version behavior |
| [Commands, receipts, events, and errors](shared-kernel/commands-receipts-and-errors.md) | ADR-0009 Accepted 2026-07-20 (decision); runtime-layer byte-freeze with API-06/12 | Common envelopes, durability, idempotency, safe error taxonomy |
| [Authority, clocks, ordering, and fencing](shared-kernel/time-ordering-and-fencing.md) | ADR-0010 Accepted 2026-07-20 (decision); runtime-layer byte-freeze with API-06/12 | Per-stream authorities, sequences, clocks, causality, lease generations |
| [Privacy, secrets, and data classification](shared-kernel/privacy-retention-and-secrets.md) | Core-layer Accepted (ADR-0011, 2026-07-20) | Field/artifact classes, allowed flows, secret references, redaction |
| [API stability tiers](shared-kernel/serialization-and-schema-evolution.md#stability-tiers) | Core-layer Accepted (ADR-0008, 2026-07-20) | Public/internal/wire/archival compatibility policy for vNext |

## Domain API tracker

| Order | API family | Status | Primary dependencies | Required scenario coverage |
| ---: | --- | --- | --- | --- |
| 1 | [API-01 Study authoring/compiler/publication](api-01/index.md) | Drafted 0.2 (git-native, ADR-0013) | Shared foundations | NS-01 through NS-08 |
| 2 | [API-02 Platform composition/deployment](api-02/index.md) | Drafted 0.2 | API-01, storage ports | NS-08, NS-12 |
| 3 | [API-03 Identity/enrollment/launch/return links](api-03/index.md) | Drafted 0.2 (identity-not-recruitment, ADR-0014) | Shared foundations, API-01 | NS-08, NS-12 |
| 4 | [API-04 Visit plans/flow/treatment/state](api-04/index.md) | Drafted 0.3 (RP-10) | API-01, API-03, storage | NS-01, NS-08, NS-10 |
| 5 | [API-05 Seats/actors/controllers](api-05/index.md) | Drafted 0.3 (RP-5/RP-7) | Shared foundations, API-01 | NS-03 through NS-07 |
| 6 | [API-06 Interactions/channels/matchmaking/leases](api-06/index.md) | Drafted 0.3 | API-04, API-05 | NS-04 through NS-09 |
| 7 | [API-10 Events/capture/provenance](api-10/index.md) | Drafted 0.3 (RP-9) | Shared schemas/order/privacy | All scenarios |
| 8 | [API-11 Storage/artifacts/transactions/outbox](api-11/index.md) | Drafted 0.2 | Shared commands/events | NS-01, NS-02, NS-08 through NS-12 |
| 9 | [API-22 Durable jobs and workers](api-22/index.md) | Drafted 0.2 | Shared foundations, API-10, API-11 | NS-02, NS-08, NS-11, NS-12 |
| 10 | [API-09 Participant client/realtime/uploads](api-09/index.md) | Drafted 0.3 (RP-6/RP-8) | API-06, API-10, API-11 | NS-03 through NS-10 |
| 11 | [API-07 Environment/game/rendering/execution](api-07/index.md) | Drafted 0.3 | API-05, API-06, API-09 through API-11 | NS-01, NS-06, NS-07, NS-09 |
| 12 | [API-08 Conversation/routing/history/delivery](api-08/index.md) | Drafted 0.2 | API-05, API-06, API-09 through API-11 | NS-02 through NS-07 |
| 13 | [API-12 Automated-controller scheduler/executor](api-12/index.md) | Drafted 0.3 | API-05 through API-08, API-10 | NS-03 through NS-07, NS-11 |
| 14 | [API-13 Model providers](api-13/index.md) | Drafted 0.2 | API-10 through API-12 | NS-02 through NS-07 |
| 15 | [API-16 Replay](api-16/index.md) | Drafted 0.3 | API-07 through API-11, API-12 | NS-01, NS-06, NS-07, NS-09, NS-11 |
| 16 | [API-17 Content/forms/presentation/UI](api-17/index.md) | Drafted 0.3 (RP-8) | API-01, API-04, API-09 through API-11 | NS-01, NS-02, NS-10 |
| 17 | [API-18 Preferences/annotation/QC](api-18/index.md) | Drafted 0.2 | API-10, API-11, API-16, API-17 | NS-01, NS-02, NS-10 |
| 18 | [API-14 Tools/authority/approval](api-14/index.md) | Drafted 0.2 | API-06, API-10 through API-13 | NS-07, NS-11, NS-12 |
| 19 | [API-15 Experimental agent memory](api-15/index.md) | Drafted 0.2 | API-08, API-10 through API-14 | NS-03 through NS-08, NS-11 |
| 20 | [API-19 Dataset query/export/lineage (JSONL)](api-19/index.md) | Drafted 0.2 | API-10, API-11, API-16, API-18 | NS-01, NS-02, NS-08, NS-12 |
| 21 | [API-20 Governance — removed](api-20/index.md) | Removed (F-4, ADR-0015; tombstone) | — | — |
| 22 | [API-21 Plugins — retracted for v0](api-21/index.md) | Retracted (D15-1..3; tombstone) | — | — |

## Acceptance checklist per API family

An API family moves from `Not started` to `Accepted` only when all boxes are
complete:

- [ ] Accountable design owner assigned
- [ ] Goals, non-goals, consumers, and source of truth defined
- [ ] Vocabulary and owned state reviewed
- [ ] Authoring/API/SPI signatures sketched where applicable
- [ ] State machine and lifecycle transitions documented
- [ ] Runtime authority, participant/channel access, and effect-time validity documented
- [ ] Ordering, clocks, concurrency, and fencing documented
- [ ] Transaction and acknowledgment boundary documented
- [ ] Idempotency, retries, timeout, cancellation, and recovery documented
- [ ] Stable error codes and privacy-safe diagnostics defined
- [ ] Persisted and wire JSON Schemas drafted
- [ ] Privacy classification, redaction, and disclosure boundaries reviewed
- [ ] Canonical events, artifacts, provenance, and telemetry defined
- [ ] Supported capabilities and unsupported behavior defined
- [ ] Golden valid, duplicate, stale, conflicting, and invalid fixtures added
- [ ] Contract-test and fault-injection plan accepted
- [ ] North-star and functional-parity scenarios traced
- [ ] ADR dependencies accepted
- [ ] Implementation dependencies and phase backlog created

## First working session

The first API session should cover the shared foundations, not study authoring.
Its required outputs are:

1. The complete identifier taxonomy
2. `SchemaRef`, `ArtifactRef`, `SecretRef`, `ResourceRef`, `PublicHandle`,
   `VersionStamp`, `EventCursor`, and `LeaseToken`
3. `TypedObject`, `CommandContext`, command receipt, and stable domain-error
   envelope
4. Idempotency and optimistic-concurrency rules
5. Canonical timestamp, sequence, numeric, binary, and JSON encoding rules
6. Privacy-classification lattice and secret references
7. Version negotiation and unknown-schema behavior
8. Golden Python and browser JSON fixtures

No domain API can be accepted while it uses an undefined dictionary or invents
an identifier, error, clock, idempotency, or privacy convention outside this
shared contract.

The first working session is at shared-kernel contract revision `0.2` (the
ADR-0013/0014/0015 re-draft executed 2026-07-19).
Its [review record](shared-kernel/review-record.md) identifies completed drafts,
passing schema fixtures, unresolved decisions, and the four sign-offs required
before freezing version 1. Domain API work may use revision 0.2 for design, but
may not treat it as Accepted or publish version-0 data.

## Second working session

The second session is [API-01, now at revision 0.2](api-01/index.md) after the
git-native versioning decision (F-1, ADR-0013). It defines `publish` as the
only committing call: a named git state (commit + stored patch when dirty)
compiles into an immutable stored `StudyVersion` with a hand-typed unique
version string, resolved-content digest, and `GitProvenance`. Drafts, draft
revisions, and the mutable definition registry are gone; manifest/package
contracts and the parity map remain. Its
[review record](api-01/review-record.md) lists the decisions, cross-domain
reviews, scenario walkthroughs, and sign-offs still required.

## Third working session

The third session is [API-02](api-02/index.md), now folded to the two-verb
operator surface (`deploy`/`stop`) with secrets passed at deploy time.
Immutable `DeploymentRevision`s remain as internal pinning; requirement
satisfaction and the science-versus-operations split are unchanged, and the
family still supplies the `DeploymentRequirement` schema that API-01 composes
(open decision A01-O14). It also now hosts the minimal secret store re-homed
from the removed governance family (F-4). Its
[review record](api-02/review-record.md) lists the remaining API-11/API-22
ports, scenario walkthroughs, and sign-offs.
