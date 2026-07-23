# Architecture Decision Register

| Field | Value |
| --- | --- |
| Status | Accepted |
| Purpose | Active register of accepted and proposed architecture decisions |
| Last updated | 2026-07-20 |

ADRs capture decisions that affect more than one API family or phase. Accepted
ADRs are binding until superseded by another ADR. Use the [ADR template](template.md)
for new decisions.

## Current ADRs

| ADR | Decision | Status |
| --- | --- | --- |
| [0001](0001-functional-parity-not-backward-compatibility.md) | Functional parity, no backward compatibility | Accepted |
| [0002](0002-actor-channel-interaction-model.md) | Principal/actor/seat/controller/channel interaction model | Accepted (2026-07-20) |
| [0003](0003-immutable-study-versions-and-materialized-plans.md) | Immutable study versions and materialized visit plans | Accepted (2026-07-20); refined by 0013 |
| [0004](0004-relational-event-and-artifact-storage.md) | Relational state, event evidence, and artifact storage | Accepted (2026-07-20) |
| [0005](0005-server-authoritative-external-agents.md) | Server-authoritative external agents and async scheduling | Accepted (2026-07-20) |
| [0006](0006-canonical-and-experienced-streams.md) | Canonical and participant-experienced evidence streams | Accepted (2026-07-20) |
| [0007](0007-explicit-client-server-provenance-manifests.md) | Explicit client, private server, and provenance manifests | Accepted (2026-07-20) |
| [0008](0008-shared-identifiers-serialization-and-schema-evolution.md) | Shared identifiers, canonical serialization, and schema evolution | Accepted (core layer, 2026-07-20) |
| [0009](0009-command-receipt-idempotency-and-concurrency.md) | Commands, receipts, idempotency, and concurrency | Accepted (2026-07-20) |
| [0010](0010-clocks-stream-ordering-and-lease-fencing.md) | Clocks, stream ordering, and lease fencing | Accepted (2026-07-20) |
| [0011](0011-data-classification-retention-and-secret-references.md) | Data classification, retention, and secret references | Accepted (core layer, 2026-07-20); superseded in part by 0015 |
| [0012](0012-deterministic-study-compilation-and-atomic-publication.md) | Deterministic study compilation and atomic publication | Accepted (2026-07-20); superseded in part by 0013 |
| [0013](0013-git-native-study-versioning.md) | Git-native study versioning and stored compiled artifacts | Accepted (2026-07-20) |
| [0014](0014-mug-scope-identity-not-recruitment.md) | MUG owns participant identity, not recruitment | Accepted (2026-07-20) |
| [0015](0015-governance-out-of-scope.md) | Governance out of scope; API-20 removed, API-21 retracted for v0 | Accepted (2026-07-20) |

## Required Phase 0 decision queue

The following decisions must be accepted or deliberately merged into another
ADR before Phase 0 exits:

### Product, domain, and publication

- Product boundary, deployment profiles, tenancy, and trust assumptions
- Canonical resource hierarchy, identifiers, and terminology
- Study publication, amendment, deployment, and version pinning (git-native per
  ADR-0013; drafts removed)
- Authoring API and compile/publish boundary (see the
  [Python authoring API spec](../phase-0/python-authoring-api.md))
- Environment, controller, renderer, and client packaging (extension packaging
  retracted for v0 per ADR-0015)
- Visit-plan branching, randomization, treatment, and amendment semantics

### Authority, protocols, and evidence

- Command, intent, receipt, event, and acknowledgment semantics
- Authority for browser, P2P, server, worker, chat, deployment, and operational
  actions
- Clocks, sequences, causality, cross-modal anchors, and finalization barriers
- Serialization, Gym/PettingZoo codecs, canonical hashing, and portable state
- Schema and protocol evolution for published vNext studies
- Transaction boundaries, optimistic concurrency, outbox, and idempotency
- Artifact staging, encryption, digesting, deduplication, and garbage collection
- Capture profiles, buffering, backpressure, completeness, and degraded operation

### Identity, security, and privacy

- Participant principal, enrollment, blinded external identity, opaque launch,
  and stable return-link model (accounts are retired by ADR-0014)
- Launch/return verification, connection fencing, and channel membership/write
  validity (admin RBAC removed per ADR-0015)
- Data classification and export (consent is a flow activity per ADR-0014;
  retention/withdrawal/deletion workflows removed per ADR-0015)
- Secret management, provider privacy/residency, and external processors
- Trusted experiment code, tool sandboxing, egress, and supply-chain policy

### Game, chat, agents, tools, memory, and preferences

- Game action validity, cadence, rollback authority, and episode finalization
- Conversation ordering, routing, context, streaming, delivery, moderation, and
  activation-loop prevention
- Agent request snapshots, scheduling, cancellation, fallback, and acceptance
- Compound game/chat effect independence versus atomicity
- Tool proposal, validation, side effects, unknown outcomes, and approval
- Conversation context versus working, episodic, and longitudinal memory
- Preference candidate, assignment, presentation, response revision, quality,
  adjudication, and export semantics
- Replay capabilities, bundle format, safe playback, and counterfactual branching
- Matchmaking, group persistence, disconnects, substitution, and compensation

### Interfaces and operations

- API stability tiers, schema generation, and client handshake (plugin
  contracts retracted for v0 per ADR-0015)
- Scientific evidence versus operational metrics, logs, and OpenTelemetry; MUG
  has no administrative audit subsystem (ADR-0015)
- Performance and cost budgets, quotas, RPO/RTO, and failure policy
- Functional-parity fixtures and vNext cutover gate

## ADR acceptance requirements

An ADR is not ready for acceptance unless it includes:

- Context and concrete decision
- Scope and non-goals
- Invariants created by the decision
- At least one credible rejected alternative
- Failure and operational consequences
- Security and privacy effects
- API, schema, and migration effects
- Required acceptance and contract tests
- Follow-up decisions with owners
