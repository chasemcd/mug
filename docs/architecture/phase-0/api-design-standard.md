# API Design Standard

| Field | Value |
| --- | --- |
| Status | Proposed |
| Last updated | 2026-07-20 |
| Applies to | All target-platform API specifications |

## Purpose

MUG's APIs cross real-time, scientific, privacy, and distributed-system
boundaries. A Python signature alone is therefore not an adequate API design.
Every API proposal must specify its audience, authority, state, durability,
failure, evidence, and evolution semantics.

## API classes

Each contract must declare one of these classes:

1. **Researcher authoring API** — typed Python objects used to define and
   compile a study.
2. **Runtime or integration protocol** — MUG-owned interfaces implemented by
   environments, controllers, providers, tools, storage backends, exporters,
   and adapters.
3. **Application command/query API** — use-case services called inside the
   server or by workers.
4. **Participant/runtime wire API** — HTTP, realtime, streaming, and upload
   protocols across a trust boundary.
5. **Evidence/export format** — immutable events, manifests, artifacts,
   bundles, tables, and external interchange.

An API family may expose more than one class, but each class gets a distinct
contract. Persistence models must not leak into authoring objects, and provider
SDK types must not leak into evidence formats.

## Required specification header

Every API specification begins with:

| Field | Required value |
| --- | --- |
| Status | Draft, Proposed, Accepted, Superseded, or Rejected |
| Owner | Accountable design owner |
| Consumers | Human and software consumers |
| Last updated | Date |
| Depends on | Accepted specifications and ADRs |
| Supersedes | Old target specifications, if any |
| Implementation phase | First phase expected to implement it |
| Stability tier | Internal, core integration, public authoring, wire, or archival |

Draft specifications may depend on Proposed work while design is underway, but
every dependency must be Accepted before the dependent specification can become
Accepted.

## Required sections

Every specification must contain:

1. Goals and non-goals
2. Terminology and owned state
3. Author-facing API, if applicable
4. Runtime/service protocols, if applicable
5. Wire and persisted schemas, if applicable
6. Lifecycle and state machine
7. Runtime authority, membership, and effect-time validity
8. Ordering, concurrency, idempotency, and transactions
9. Timeout, cancellation, reconnect, and recovery behavior
10. Errors and safe diagnostics
11. Privacy classification, disclosure, and redaction
12. Events, artifacts, provenance, and observability
13. Supported capabilities and unsupported behavior
14. Examples mapped to acceptance scenarios
15. Contract tests and golden fixtures
16. Alternatives, unresolved questions, and decision links

## Shared contract conventions

### Opaque identifiers

Definition IDs, immutable version IDs, runtime occurrence IDs,
principal/security IDs, human authoring keys, content digests, credentials,
revisions, and stream positions are distinct and never inferred from display
labels. MUG entity IDs use the registered kind-prefixed UUIDv7 encoding in the
[shared-kernel contract](shared-kernel/index.md). UUID order is never event
order, and IDs never grant access. Content digests identify bytes in a declared
domain; they do not replace occurrence identity. Generic `ResourceRef` values
carry only a registered typed ID; the prefix registry derives the kind, avoiding
two independently supplied kind claims. Where a typed ID or its UUIDv7 timing
would leak linkage or treatment, the client receives a scoped, random
`PublicHandle` instead.

### Immutability and versions

- Unpublished authoring source may change; git remains its source of truth.
- Published scientific versions are immutable.
- Runtime occurrences are append-only or revision-controlled according to
  their state machine.
- Every persisted or wire-visible schema has an exact name, integer version,
  and digest. Version 0 is proposal-only; accepted versions start at 1 and are
  immutable.
- The no-backward-compatibility decision permits replacing the old platform;
  it does not permit silently changing a published new study, replay bundle, or
  protocol.
- Each visit pins both an immutable scientific `StudyVersion` and an immutable
  operational `DeploymentRevision`. Hosted-provider configuration pins the
  requested selector/configuration and records the provider-resolved model as
  exposure rather than claiming the vendor backend is content-addressed.

### Commands, queries, and events

- Commands request a transition and return a typed receipt or error.
- Queries do not change research state.
- Events state accepted facts in past tense.
- Clients submit intents; authoritative runtimes validate and accept or reject
  them.
- A recorded correction never rewrites canonical events. It appends an
  invalidation, quarantine, annotation, or compensating event.

### Receipt durability

Transport acknowledgment, mutable command status, immutable terminal receipt,
and public error are separate contracts. Every terminal receipt declares one of
these compatibility classes:

- `IngressReceipt`: a high-rate intent reached the current authoritative
  runtime. It may later be rejected, lost with volatile runtime state, or become
  part of a committed transition. It is not proof of durable scientific
  acceptance.
- `CommitReceipt`: aggregate state/revision, idempotency record/result,
  canonical research event, and outbox entries committed atomically in the
  relational Unit of Work.
- `ArtifactCommitReceipt`: artifact bytes were staged and integrity-verified,
  then artifact metadata/reference and the corresponding relational commit were
  accepted. Later outage or bit rot is represented by availability/integrity
  state rather than denying the original commit.

Activity advancement, treatment/plan decisions, committed chat messages,
form/preference responses, completion, and memory writes require a
`CommitReceipt`. High-rate game input may use `IngressReceipt`; the resulting
canonical transition has a separate commit/finality event and receipt policy.
APIs may define a stronger subtype but may not return an unqualified "success."
Each receipt also declares receipt durability (`runtime`, `journaled`, or
`transactional`), effect durability (`none`, `runtime`, `journaled`,
`transactional`, `artifact_committed`, or `unknown`), and a deployment-pinned
failure profile. `pending` is a status, not a terminal receipt. An ambiguous
external side effect becomes a durable `indeterminate` result and is never
retried automatically.

### Command context

The wire carries an untrusted `WireCommandEnvelope`; only the authenticated
gateway constructs a trusted context equivalent to:

```python
@dataclass(frozen=True)
class CommandContext:
    command_id: CommandId
    request_id: RequestId
    authenticated_subject: PrincipalRef
    target: ResourceRef
    idempotency_key: IdempotencyKey
    idempotency_scope: IdempotencyScope
    semantic_fingerprint: Digest
    runtime_protocol: RuntimeProtocolBinding | None
    verified_lease: FencingClaim | None
    clock_epoch_id: ClockEpochId
    deadline_monotonic_us: int | None
    trace_context: TraceContext | None
```

`RuntimeProtocolBinding` contains an all-or-none pinned `StudyVersionRef` and
`DeploymentRevisionRef` plus any server-resolved enrollment/visit/interaction/
actor scope. Runtime commands require it. Publication, deployment, identity
bootstrap, and other platform-internal commands set it to `None` and bind their
exact domain scope through target, typed payload, preconditions, and
fingerprint; they never invent a future version.

The server derives enrollment, visit, interaction, actor, treatment,
membership, and effect-validity scope from verified launch/return state and
durable runtime state. It does not trust a client to assert ownership by
including an identifier. Wire payloads, receipt results, and safe error details
use a `TypedObject` containing an exact `SchemaRef` and schema-normalized data.
The gateway resolves and validates that schema from the offline allowlist
before fingerprinting or effects. Long-running work rechecks membership, write
validity, lifecycle state, deadline, and fencing immediately before applying
effects.

### Idempotency

Each command specifies exactly one retry/deduplication policy:

- Naturally idempotent
- Idempotent by caller key
- Idempotent by resource uniqueness
- Durable job/status for long-running work
- Indeterminate with explicit reconciliation for an ambiguous external effect

For keyed operations, the server derives the scope and hashes schema-normalized
semantic content. Repeating the same scope/key/fingerprint returns the
byte-equivalent original receipt. Reusing the key with a conflicting fingerprint
returns an idempotency conflict. Networked side effects must not claim an
unprovable “at-most-once, nonretryable” guarantee.

### Optimistic concurrency

Durable aggregates expose a revision or ETag. Commands that depend on current
state carry an expected revision. Conflicts do not silently retry scientific
decisions such as randomization or preference assignment.

### Time and ordering

Every time field declares whether it is fixed-microsecond wall-clock UTC,
coordinator-local monotonic time/epoch, duration, untrusted client/provider
time, environment step, render frame, conversation turn, producer position, or
stream sequence. Wall-clock timestamps and UUIDs do not establish canonical
order.

An authoritative monotonic deadline or lease expiry never crosses a process
boundary as if another process could read the same clock. The coordinator keeps
the authoritative `(clock_epoch, deadline)`; remote work receives only a
bounded remaining duration or local cancellation deadline. The coordinator
rechecks its own deadline, current lease generation, and authority immediately
before applying an effect.

Each canonical stream has one append authority and a contiguous sequence from 1.
Cross-stream relationships use correlation, causation, and explicit modality
coordinates rather than assuming clocks are synchronized.

An optional interaction-wide coordinator sequence means server acceptance order
only. It is not physical event order or participant-experienced order. P2P has
one writer per deterministic replica and explicit finality/reconciliation
authority, not one fictional global environment writer.

### Async and real-time boundaries

I/O-bound application and integration APIs are asynchronous. Environment
`step()` and pure compilation/validation may be synchronous. No API may perform
provider, tool, database, or object-store I/O while holding an environment
mutation lock.

Cancellation is best effort and is not rollback. Cancelled, expired, fenced, or
otherwise stale completions are always rejected at the authoritative effect
boundary.

### Errors

All APIs use stable machine-readable error codes and safe structured details.
At minimum, the shared model covers:

- Validation failure
- Runtime identity, membership, or write validity rejected
- Not found
- Revision conflict
- Idempotency conflict
- Stale generation or lease
- Deadline exceeded or cancelled
- Unsupported capability
- Provider/tool unavailable
- Privacy-classification or disclosure violation
- Artifact integrity failure
- Event sequence conflict

Provider stack traces, credentials, prompt contents, and protected participant
data are never included in client-safe errors.

### Privacy and secrets

Every persisted data-bearing field declares or inherits a `DataHandlingRef`
containing canonical privacy labels. Every value has exactly one base-disclosure
label: `public` or `research`. `sensitive` and `pii` are independent
restrictions that may be added to `research`; adding either to public data
promotes the base to `research`. Effective classification uses the stricter
base plus the normalized union of restrictions, so label inheritance can only
tighten handling. Secret is not a storable research label: secret material is
forbidden in ordinary contracts and is referenced only by `SecretRef` in
declared private deployment configuration. Retention and data-rights operations
belong to the self-hosting institution, not `DataHandlingRef` or a MUG policy
engine.

APIs specify whether content may enter:

- A client manifest
- A canonical event
- An artifact
- An operational trace or log
- A researcher export
- A model-provider request
- A tool invocation

### Evidence

For every accepted command, the specification identifies:

- The resulting canonical event or durable projection
- The artifact references, if any
- The acknowledgment durability boundary
- Correlation and causation identifiers
- Assignment/exposure effects
- Operational telemetry that is deliberately non-canonical

## Python authoring conventions

- Prefer immutable typed specifications over mutable fluent builders.
- Separate authoring specifications from compiled manifests and runtime state.
- Make defaults explicit in compiled output.
- Reject unsupported capability combinations during compilation.
- Do not serialize arbitrary Python attributes or silently drop
  unserializable values.
- Callables and code must become versioned artifacts with an explicit execution
  location and trust boundary.
- Secret values are never accepted where a `SecretRef` is expected.

The choice of dataclasses, Pydantic, or another validation implementation is a
Phase 0 ADR. Public semantics must not depend on incidental library behavior.

## Core integration conventions

Version 0 has no plugin framework, discovery/negotiation layer, trust-class
hierarchy, or distribution mechanism (ADR 0015). Integrations follow these
rules instead:

- Researcher-authored environments, policies, renderers, and native tools are
  ordinary study code in the study repository and are pinned at publication.
- Built-in provider, storage, export, and transport adapters implement
  MUG-owned typed protocols; their SDK types do not enter unrelated domain or
  evidence contracts.
- Each compiled integration declares its configuration schema, execution
  location, data flow, capabilities, failure behavior, and shutdown behavior.
- Closed vocabularies remain closed. An unsupported kind or capability
  combination fails before deployment rather than triggering discovery.
- No integration can silently alter an immutable published study version.

## Contract-test requirements

Every implementation-facing protocol has a reusable conformance suite. Tests
cover at least:

- Valid and invalid schemas
- Duplicate and conflicting idempotency keys
- Optimistic-concurrency conflicts
- Timeout, cancellation, and stale completion
- Crash or disconnect at each acknowledgment boundary
- Runtime membership/write validity and cross-actor isolation
- Secret and privacy leakage
- Unsupported capabilities
- Event and artifact lineage
- Schema-version handling and unknown fields

An API cannot become Accepted without representative golden request, success,
failure, event, and persisted-artifact fixtures.
