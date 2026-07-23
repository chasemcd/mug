# Architecture Roadmap

| Field | Value |
| --- | --- |
| Status | Proposed |
| Last updated | 2026-07-18 |
| Planning assumption | Approximately four experienced engineers; ranges are not commitments |

## Delivery rule

The redesign targets functional parity without backward compatibility. There
is no legacy adapter, dual-write, legacy filesystem layout, or old experiment
API gate unless a later ADR adds a specific migration tool. Existing examples
will be ported as capability fixtures rather than run unchanged.

The first implementation release should not replace the current production
path until its declared functional-parity subset passes. During development,
the old and new architectures may coexist as separate entry points, but they
do not share a compatibility contract.

## Phase dependency map

```text
Phase 0: decisions, contracts, schemas, and scenarios
        │
        ▼
Phase 1: platform kernel, compiler, runtime, and evidence spine
        │
        ▼
Phase 2: durable study, identity, treatment, and recovery
        │
        ├──────────────┬──────────────┬──────────────┐
        ▼              ▼              ▼              ▼
Phase 3A Replay   Phase 3B Agents  Phase 3C Prefs  Phase 3D Chat
        └──────────────┴──────┬───────┴──────────────┘
                              ▼
                    Phase 4 Tools and memory
                              ▼
                    Phase 5 Longitudinal returns
                              ▼
                    Phase 6 production hardening
                              ▼
                    Phase 7 hybrid/P2P agents
```

## Phase 0 — Architecture and contracts

**Indicative duration:** 6–9 weeks

Define the domain language, functional-parity boundary, state machines,
authoring API, runtime ports, wire protocols, schemas, privacy model, recovery
semantics, and acceptance scenarios. Produce accepted ADRs and contract
fixtures. No production feature implementation is included.

Use 3–4 weeks for foundational domain/authority/trust decisions and 3–5 weeks
for the full API catalog, schemas, failure matrices, golden scenarios, and
contract validation. This estimate should be reduced only by reducing explicit
Phase 0 scope, not by moving unresolved cross-cutting semantics into feature
implementation.

**Gate:** all [Phase 0 exit gates](phase-0/index.md#exit-gates) pass.

## Phase 1 — Platform kernel and evidence spine

**Indicative duration:** 8–12 weeks

- Implement the study compiler and explicit client/server/provenance manifests.
- Replace module-global coupling with an application composition root and
  explicit runtime services.
- Implement stable occurrence identifiers and the canonical event envelope.
- Implement the local relational/artifact backend and export APIs.
- Implement the cross-runtime episode ledger for browser, server, and P2P.
- Rebuild the core flow, environment, controller, rendering, and multiplayer
  capabilities through the new APIs.
- Implement baseline launch authentication, secret isolation, immutable event
  capture, safe content rendering, transport-security requirements, and
  capture enforcement needed by these capabilities.

**Gate:** the selected Phase 1 parity fixtures pass; every runtime produces the
same normalized transition contract; private manifest data cannot reach a
client.

## Phase 2 — Durable study core

**Indicative duration:** 8–12 weeks

- Add PostgreSQL, object storage, migrations, and a transaction outbox — all
  researcher-owned and directly queryable (self-hosted; F-4).
- Add study versions, immutable deployment revisions, principals, enrollments,
  visits, treatment assignment/exposure, and namespaced state documents.
  Consent ships as an ordinary flow activity, not a subsystem.
- Materialize and persist visit plans before participation begins.
- Add durable activity advancement, interaction membership, completion,
  connection leases, and recovery semantics.
- Add authenticated opaque launch tickets and stable return links.
- Add blinded external-identity links stored apart from research data; export
  stays ungated against the researcher-owned store.

**Gate:** fault injection at each activity boundary always restores the exact
visit plan and treatment without duplicate evidence or progression.

## Phase 3A — Replay and provenance

**Indicative duration:** 8–12 weeks

- Add trajectory, event, render, and experienced-view streams.
- Add logical-renderer keyframes and random seeking.
- Add replay manifests, bundle construction, integrity validation, and a safe
  visual player.
- Add decision tapes and deterministic state-hash verification.

**Gate:** offline replay performs no model/tool calls, detects modified
artifacts, and either verifies deterministic state or declares visual fallback.

## Phase 3B — Agent and provider runtime

**Indicative duration:** 10–16 weeks

- Add immutable agent definitions and versions.
- Add observation encoders, structured action/message decoders, the policy
  scheduler, executor boundary, cancellation, staleness, deadlines, and
  fallback policies.
- Add a fake provider, a generic compatible provider adapter, and one direct
  provider adapter.
- Add normalized provenance, usage, cost, and failure records.
- Add provider secret isolation, per-study/interaction budgets, safe output
  handling, and emergency cancellation before live provider use.

**Gate:** a deliberately slow provider cannot stall game frames, human input,
or connection heartbeats; late decisions cannot cross episode boundaries.

## Phase 3C — Preference and annotation runtime

**Indicative duration:** 8–12 weeks

- Add immutable preference protocols and generic artifact candidates.
- Add query generation, randomized/blinded assignments, presentation exposure,
  durable responses, resume, revision, quality evidence, and adjudication.
- Add trajectory, model-output, chat-message, and conversation-segment
  candidates.
- Add normalized and reward-model-oriented exporters.

**Gate:** response persistence is acknowledged before progression; browser
payloads cannot reveal blinded identities; exports retain complete lineage.

## Phase 3D — Conversation and composite interaction runtime

**Indicative duration:** 8–14 weeks

- Add chat channels, memberships, routing, visibility, moderation, turn and
  activation policies, message ordering, idempotent submission, and delivery
  evidence.
- Add accessible one-to-one and group chat UI, streaming presentation, and game
  chat panels/overlays.
- Persist canonical conversation history and the exact context snapshots used
  for each model request.
- Relate independently ordered game and conversation streams through causation
  and explicit modality anchors; do not invent a physical global order.
- Enforce output escaping/safe rendering, channel authorization, message limits,
  moderation policy, and model-activation budgets from the first chat release.

Basic multi-turn conversation context belongs here. Phase 4 memory adds
research-configurable episodic and longitudinal memory beyond the durable
conversation record.

**Gate:** the one-human/one-LLM, multi-human/one-LLM, multi-human/multi-LLM,
and game-plus-chat scenarios pass with deterministic message ordering and
correct visibility.

## Phase 4 — Tools and experimental memory

**Indicative duration:** 8–12 weeks

- Add native tools, optional MCP discovery, authorization, approval,
  idempotency, sandboxing, environment-command mailboxes, and tool-result
  substitution during replay.
- Require egress allowlists, SSRF defenses, execution isolation, side-effect
  budgets, and emergency stop before any external or mutating tool is enabled.
- Add working, episodic, and longitudinal agent memory with explicit treatment
  modes, immutable reads, compare-and-swap writes, provenance, and scope
  deletion.

**Gate:** side effects execute at most as authorized; stale decisions cannot
commit memory; tool and memory isolation holds across actors and treatments.

## Phase 5 — Longitudinal multi-part studies and integrations

**Indicative duration:** 8–12 weeks

- Harden multi-part flows and stable return links across intentional study
  version transitions (ADR-0014): part/version transition rules, eligibility
  branches expressed in the flow, and carried-forward state namespaces.
- Add blinded external-identity round-trips (completion redirect/code) for
  panel providers. Recruitment, reminders, and panel management remain in the
  researcher's own tools — MUG owns identity, not recruitment.
- Add external annotation round-trips over the ungated JSONL export/lineage
  contracts; there is no plugin layer.

**Gate:** a participant completes multiple parts across an intentional study
version transition while preserving only authorized assignment, exposure, and
state.

## Phase 6 — Production hardening

**Indicative duration:** 12+ weeks

- Scale and harden the secret-isolation, encryption, quota, budget, and
  emergency-stop controls introduced with their owning features.
- Add durable worker queues, multi-process coordination, Redis-backed ephemeral
  leases, backpressure, key rotation, backup/restore, and operational
  dashboards. Organizational access control remains the self-hosting
  institution's (F-4), not a MUG feature.
- Run load, fault, privacy, and security testing.

**Gate:** provider, worker, database, object-store, and network failure drills
preserve declared integrity and recovery guarantees.

## Phase 7 — Hybrid and P2P external agents

Live external agents initially require server authority. This later research
phase may add an authoritative remote-policy bridge or frame-numbered external
decision events to browser/P2P environments. Independent provider calls by
each peer are not an acceptable design.

**Gate:** a separate ADR demonstrates authority, rollback, side-effect,
latency, cost, and replay semantics before implementation is accepted.
