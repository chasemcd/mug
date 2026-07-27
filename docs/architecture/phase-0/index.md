# Phase 0: Architecture and Contracts

| Field | Value |
| --- | --- |
| Status | Proposed |
| Last updated | 2026-07-20 |
| Indicative duration | 6–9 weeks: 3–4 weeks foundations, then 3–5 weeks contract specifications |
| Production implementation | Out of scope |
| Exit condition | All contract gates pass |

## Objective

Phase 0 produces an implementable platform contract. It does not merely agree
on a component diagram. Before production feature code begins, the team will
know:

- Which capabilities the platform must provide
- Which concepts own each piece of state
- Which API families exist and who consumes them
- Which commands are synchronous or asynchronous
- Which operations are transactional, idempotent, resumable, or cancellable
- Which actor or service is authoritative for every transition
- Which schemas are stored, placed on the wire, or exported
- Which content is public, private, sensitive, or forbidden
- Which recovery and replay claims are supportable
- Which acceptance scenarios prove the contracts fit together

Schema fixtures, sequence diagrams, interface sketches, and throwaway contract
prototypes are allowed. Shipping runtime implementations are not Phase 0 work.

The earlier 2–4 week estimate is not credible now that Phase 0 explicitly owns
the complete public API catalog, threat model, failure semantics, schemas, and
cross-runtime contract walkthroughs. Phase 0 is split conceptually into:

- **Foundation track, 3–4 weeks:** charter, parity, quality attributes, terminology,
  authority, trust model, data model, and foundational ADRs.
- **Contract track, 3–5 weeks:** domain API specifications, schemas, failure matrices,
  golden scenarios, feasibility validation, and the implementation backlog.

## Inputs

- [North-star architecture](../north-star.md)
- [Functional-parity contract](../functional-parity.md)
- [Quality attributes](../quality-attributes.md)
- [API design standard](api-design-standard.md)
- [API catalog](api-catalog.md)
- [Public Python authoring API](python-authoring-api.md)
- [API review tracker](api-review-tracker.md)
- [Contract freeze tracker](contract-freeze.md) — what each bundle pins now that
  the code is here, and what it still needs
- [Acceptance scenarios](acceptance-scenarios.md)
- [Failure and recovery matrix](failure-matrix.md)
- [Shared-kernel contract](shared-kernel/index.md)
- Current MUG examples, tests, and implementation documentation as capability
  evidence, not compatibility requirements

## Current work

The first concrete review is shared-kernel revision `0.2`. It now has proposed
cross-runtime contracts for identifiers, references, schema evolution,
commands/receipts/errors, clocks/order/fencing, privacy/secrets,
version-0 JSON Schema, and golden valid/invalid fixtures. The schema harness has
50 passing tests. The [review record](shared-kernel/review-record.md) is the
source of truth for open decisions and sign-offs; version 0 remains explicitly
unpublishable.

The Phase 0 user-surface review concluded with four foundational decisions,
now folded into the contracts:

- **F-1 git-native versioning** ([ADR-0013](../decisions/0013-git-native-study-versioning.md)):
  git owns study source; `publish` compiles a named git state (commit + patch
  if dirty) into an immutable stored `StudyVersion` with a hand-typed unique
  version string and content digest. No drafts, draft revisions, or definition
  registry. [API-01 revision 0.2](api-01/index.md) reflects this model.
- **F-2 identity, not recruitment** ([ADR-0014](../decisions/0014-mug-scope-identity-not-recruitment.md)):
  [API-03 revision 0.2](api-03/index.md) reduces to pseudonymous `Enrollment`,
  opaque `LaunchTicket`, blinded `ExternalIdentityLink`, and stable return
  links. Consent is an ordinary flow activity; longitudinal designs are
  multi-part flows plus the return link. No accounts, waves, invitations, or
  consent-record subsystem.
- **F-3 no magic strings:** every closed vocabulary is a typed constant or
  enum (`ExecutionMode.SERVER`, `Assign.balanced()`, `Dataset.TRAJECTORIES`);
  author-defined identifiers stay plain strings.
- **F-4 governance out of scope** ([ADR-0015](../decisions/0015-governance-out-of-scope.md)):
  API-20 is removed (tombstone retained) and API-21 is retracted for v0. MUG
  is self-hosted and ungated; the researcher owns the store. Immutable event
  capture stays in API-10 and minimal secret storage in API-02/shared kernel.

The author-facing surface these contracts back is specified in the
[public Python authoring API](python-authoring-api.md).

[API-02](api-02/index.md) collapses to a two-verb operator surface (`deploy`
and `stop`) with secrets passed at deploy time; immutable
`DeploymentRevision`s remain as internal pinning for in-flight visits.

**All 20 active API families have a `Drafted` contract** (API-20 removed and
API-21 retracted, with tombstones) — a version-0 JSON Schema bundle, golden
valid/one-defect-invalid fixtures, a semantic conformance harness, an index,
and a review record — plus the three cross-cutting gate documents: the
[threat model and data-flow inventory](threat-model.md)
(gate 0H), the [integrated north-star walkthrough](integrated-walkthrough.md)
(gate 0I), and the [Phase 1 implementation backlog](implementation-backlog.md).
The focused architecture suite passes across the shared kernel and all
families, plus a corpus test that checks every family is present and the gate
documents cover every scenario and trust boundary.

Every family is `Drafted`, **not `Accepted`**. Acceptance still requires the four
named reviewer sign-offs per family, acceptance of ADRs 0002–0015, the
shared-kernel version-1 freeze, per-scenario golden end-to-end fixtures, and an
independent browser-side runner — all tracked in the family review records and
still open. The Phase 0 exit gates below are satisfied in *shape* (owned state,
versioned payloads, named authority, defined failures, valid/invalid fixtures)
but remain formally open until those human sign-offs are recorded.

## Required outputs

Phase 0 is expected to leave the repository with:

1. An accepted glossary and domain relationship model
2. An accepted functional-parity matrix
3. Accepted ADRs for every cross-cutting decision
4. One reviewed specification for every API family in the catalog
5. JSON Schema examples for every persisted or wire-visible contract
6. State machines for every durable lifecycle
7. Sequence diagrams for normal, retry, reconnect, timeout, and crash paths
8. A threat model and data-flow/privacy inventory
9. Contract-test plans and golden fixtures
10. A dependency-ordered implementation backlog
11. A reviewed integrated north-star scenario proving the APIs compose

## Work packages

### 0A — Charter, capability boundary, and quality attributes

**Questions**

- What platform outcomes must survive the redesign?
- What is explicitly not backward compatible?
- Which availability, latency, throughput, integrity, privacy, accessibility,
  and reproducibility properties are required?
- Which deployment profiles are supported initially?

**Deliverables**

- Accepted ADR 0001
- Accepted functional-parity matrix
- Prioritized quality-attribute scenarios with measurable thresholds
- Accepted product boundaries and non-goals

**Gate 0A:** every current capability is retained, deliberately replaced, or
removed by an explicit product decision.

### 0B — Vocabulary, identifiers, ownership, and lifecycles

**Questions**

- What distinguishes principal, enrollment, visit, interaction, seat, actor,
  controller binding, channel, activity occurrence, and episode?
- Which identifiers represent definitions, immutable versions, and runtime
  occurrences?
- Which aggregate owns each transition?
- Which lifecycles can be resumed, retried, invalidated, or deleted?

**Deliverables**

- Accepted glossary and entity-relationship model
- Opaque identifier and versioning specification
- State machines for study publication, deployment, enrollment, visit,
  activity, interaction, episode, assignment, artifact, agent run, message,
  preference assignment, and response
- Ownership and transaction-boundary map

**Gate 0B:** no API relies on the unqualified terms `session`, `run`, `user`, or
`agent`; every mutable aggregate has one declared owner and revision model.

### 0C — Authoring, compilation, and publication

**Questions**

- How do researchers declare flows, activities, actors, channels, treatments,
  capture, privacy, and preferences?
- What is validated at authoring, compilation, publication, deployment, and
  visit-materialization time?
- Which change creates a new study version?
- What content belongs in client, private server, and provenance manifests?

**Deliverables**

- Researcher authoring API specification
- Compiler validation and diagnostic contract
- Canonical study-version serialization and digest rules
- Manifest JSON Schemas and safe example fixtures
- Publication and deployment state machines

**Gate 0C:** the compiler can be specified to reject an invalid north-star
study before recruitment, and no secret or blinded condition is required by a
client manifest.

### 0D — Actors, channels, interaction, game, and conversation semantics

**Questions**

- How are seats filled by human and software actor instances?
- How are controller bindings authorized per modality?
- How do game, chat, annotation, and system channels order accepted intents?
- How are game steps, render frames, conversation turns, and wall/monotonic
  time related?
- What does server, browser, or peer authority mean for each event?

**Deliverables**

- Actor/controller/channel API specification
- Unified intent and receipt schemas
- Interaction and channel state machines
- Game execution, snapshot, and authority contracts
- Conversation routing, activation, streaming, and delivery contracts
- Cross-channel clock and ordering ADR

**Gate 0D:** all seven north-star capabilities can be represented without a
custom socket event, global variable, or ad hoc browser script.

### 0E — Events, artifacts, transactions, recovery, and replay evidence

**Questions**

- What is canonical evidence versus operational telemetry?
- What is durably committed before each acknowledgment?
- How are duplicate, late, conflicting, out-of-order, and partial submissions
  handled?
- How do object uploads and relational transactions reach a consistent state?
- Which replay capabilities can each capture profile truthfully claim?

**Deliverables**

- Event envelope, stream, cursor, and append contracts
- Artifact staging/finalization and integrity contracts
- Unit-of-work, outbox, lease, and repository SPIs
- Capture-policy and trajectory schemas
- Canonical-versus-experienced stream specification
- `.mugrun` manifest and replay capability schema
- Failure and recovery sequence diagrams

**Gate 0E:** retry and crash outcomes are defined for every north-star command,
and exact replay requires no external provider or tool execution.

### 0F — Automated agents, providers, tools, and memory

**Questions**

- How do slow decisions enter a synchronous environment without blocking it?
- What makes a completion stale, invalid, or eligible for fallback?
- Which provider capabilities are normalized and which remain extensions?
- Who authorizes tools and prevents duplicate side effects?
- When may working, episodic, or longitudinal memory commit?

**Deliverables**

- Controller request/decision and scheduler state-machine specifications
- Provider request, stream, response, usage, and error schemas
- Tool catalog, authority, approval, idempotency, and environment-command APIs
- Memory scope, read, search, proposal, commit, conflict, and provenance APIs
- Provenance and capture policy for model/tool/memory content

**Gate 0F:** slow, late, cancelled, or malicious external work cannot block or
silently mutate an interaction, replay, another actor, or longitudinal memory.

### 0G — Preferences, forms, presentation, and client experience

**Questions**

- How do generic candidate references cover trajectories and LLM outputs?
- What is recorded about randomization, blinding, presentation, watch history,
  revision, and quality?
- Which client commands require a durable receipt before progression?
- How are accessibility and technical-problem paths represented?

**Deliverables**

- Form and response schema
- Preference protocol, candidate, query, assignment, presentation, response,
  quality, and adjudication schemas
- Client component and realtime command contract
- Export and lineage contracts
- Accessibility acceptance plan

**Gate 0G:** randomized display labels can never change candidate identity,
private metadata cannot break blinding, and a refresh cannot duplicate or lose
an accepted response.

### 0H — Security, privacy, and operations

**Questions**

- Which trust boundaries exist among browser, peer, server, worker, author
  study code, provider, tool, database, and object store?
- Where may PII, research-sensitive content, prompts, tool results, and secrets
  flow?
- Which operator commands are allowed without rewriting evidence?

Governance (RBAC, audit trails, retention schedules, deletion workflows) and a
plugin layer are explicitly out of scope (F-4, API-21 retraction): MUG is
self-hosted and ungated, and the researcher's institution owns access control,
compliance, retention, and deletion against its own store. Consent is an
ordinary flow activity, not a policy subsystem.

**Deliverables**

- Threat model and data-flow diagrams
- Privacy classification and redaction contracts (redaction as new
  lineage-bearing objects)
- Minimal secret storage/reference contract (API-02/shared kernel; security,
  not governance)
- Immutable event-capture semantics (API-10; evidence, not an audit trail)
- Backup, restore, and incident-test plan

**Gate 0H:** the threat model covers every external boundary; no API requires a
secret in a browser or canonical event; the self-hosted, researcher-owned-store
stance is stated explicitly wherever deletion or access control would
otherwise be implied.

### 0I — Integrated contract validation and implementation backlog

**Tasks**

- Walk every [acceptance scenario](acceptance-scenarios.md) through the proposed
  APIs and state machines.
- Produce golden JSON fixtures for the north-star scenario.
- Trace every event, artifact, acknowledgment, authority decision, and failure.
- Run a final consistency, privacy, and naming review.
- Convert accepted specifications into dependency-ordered implementation work.

**Gate 0I:** the integrated north-star walkthrough has no undefined API,
unowned state, unversioned payload, ambiguous authority, or unhandled failure.

## Recommended working order

Detailed API sessions should proceed in this order:

1. Shared identifiers, versions, schemas, errors, command context, and privacy
2. Study definition, compiler, manifests, and publication
3. Identity, enrollment, visits, treatment, and materialized plans
4. Seats, actors, controller bindings, channels, intents, and interactions
5. Events, artifacts, transactions, leases, durable jobs, and the client protocol
6. Environment, game, rendering, and execution modes
7. Conversation, routing, delivery, and multi-turn context
8. Automated-controller scheduler and provider normalization
9. Replay capture, bundle, validation, and playback
10. Preferences, presentation, quality, and export
11. Tools, authority, and memory
12. Security review and operations (no governance layer; no plugin layer)

Earlier sessions may leave explicitly tracked open decisions for a later
domain, but they may not assume an undefined ownership or durability boundary.

## Review method for each API family

Every specification receives four reviews:

1. **Domain review:** terminology, ownership, state machine, and invariants
2. **Runtime review:** concurrency, authority, latency, cancellation, and
   failure semantics
3. **Data review:** schemas, versioning, idempotency, persistence, replay, and
   provenance
4. **Trust review:** privacy, secrets, disclosure boundaries, and abuse cases

An API becomes Accepted only after all four reviews pass and its golden
fixtures validate.

## Exit gates

Phase 0 is complete only when all of these are true:

- **Capability gate:** the functional-parity contract and seven new target
  capabilities have accepted acceptance scenarios.
- **Vocabulary gate:** identifiers, definitions, occurrences, actors, and
  lifecycle terms are unambiguous.
- **API gate:** every catalog entry has an owner, specification, versioning
  policy, error model, and contract-test plan.
- **Authority gate:** every state transition names its sole authority and
  ordering domain.
- **Durability gate:** every acknowledgment names what has been committed and
  how retries are handled.
- **Schema gate:** every persisted and wire-visible payload is versioned and has
  valid/invalid fixtures.
- **Security gate:** the threat model, data inventory, redaction, and secret
  decisions are accepted; the self-hosted researcher-owned-store stance is
  recorded wherever retention or deletion would otherwise be implied.
- **Recovery gate:** restart, reconnect, timeout, partial upload, stale result,
  and provider/tool failure paths are specified.
- **Replay gate:** canonicality, completeness, deterministic verification, and
  zero-external-call semantics are explicit.
- **Scenario gate:** the integrated north-star walkthrough has no missing or
  contradictory contract.
- **Backlog gate:** Phase 1 work is dependency ordered and estimated from
  accepted contracts.

No gate may be waived implicitly to begin implementation. A waiver requires a
time-bounded ADR naming the risk, owner, and decision date.
