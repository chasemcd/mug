# Commands, Receipts, and Errors

| Field | Value |
| --- | --- |
| Status | Draft |
| Contract revision | `0.2` |
| Owner | Shared kernel; command payloads and transitions remain domain-owned |
| Last updated | 2026-07-20 |
| Decision | Proposed ADR 0009 |
| Scenario anchors | NS-03, NS-04, NS-08, NS-10, NS-11 |

## Contract boundary

MUG separates caller input from trusted execution authority:

```text
WireCommandEnvelope       untrusted caller-supplied values
        ↓
CommandContext            verified, resolved, server-derived runtime authority
        ↓
CommandStatus             optional mutable view while durable work is pending
        ↓
CommandReceipt            immutable terminal domain result
```

Transport adapters may use HTTP, WebSocket, WebTransport, or an internal queue.
They must preserve these semantics and must not make transport acknowledgment
look like domain acceptance.

## Wire command envelope

The proposed exact shape is owned by the
[`WireCommandEnvelope`](schemas/v0/shared-kernel.schema.json) schema:

Every domain-owned object embedded in a shared envelope uses one exact
`TypedObject` wrapper:

```python
TypedObject(
    schema=SchemaRef(...),
    data={...},
)
```

The `SchemaRef` name, version, and digest identify the complete schema for
`data`; it is not merely a media-type hint. `TypedObject` is used for the wire
command `payload`, an accepted receipt's `result`, and a domain error's
`details`. The shared wrapper bounds `data` as a JSON object; its domain meaning
remains unusable until the referenced schema has been resolved and applied as
described below.

```json
{
  "schema": {
    "name": "mug.command-envelope",
    "version": 0,
    "digest": {
      "algorithm": "sha-256",
      "hex": "f675d9ec1f6258719da93a507421689b26babf69d36503c7df90b5039e238d6d"
    }
  },
  "protocol_version": "0.1.0",
  "command": {
    "name": "preference.response.submit",
    "version": 0
  },
  "request_id": "request_019b5ed0-14ec-7f51-89c9-d42db811f03b",
  "idempotency_key": "idem_7Gg3L2M1qPv9sXr4Nk8BzQ",
  "target": {
    "id": "prefassign_019b5ecc-14ec-7f51-89c9-d42db811f03d"
  },
  "preconditions": {
    "expected_revision": 4,
    "expected_state": "presented"
  },
  "producer": {
    "epoch_id": "prodepoch_019b5ea0-14ec-7f51-89c9-d42db811f03e",
    "sequence": 12,
    "content_digest": {
      "algorithm": "sha-256",
      "hex": "2b6f73c60f8b7ec780fb42bc7c9b31733c6f9a7f3657ee57878096c2b4f3c22b"
    }
  },
  "lease_token": "synthetic-fixture-token-never-use-as-a-credential",
  "timeout_ms": 5000,
  "client_observed_at": "2026-07-17T14:22:31.413000Z",
  "payload": {
    "schema": {
      "name": "mug.preference.response-submit-payload",
      "version": 0,
      "digest": {
        "algorithm": "sha-256",
        "hex": "bc41880bf580cc353fb9b3701e23f9781abebd3e476a3fa7e47ba70b450f1abc"
      }
    },
    "data": {
      "candidate_id": "candidate-1",
      "confidence": 0.8
    }
  }
}
```

### Wire rules

- Authentication normally lives in transport credentials, not the JSON body.
- The envelope must not contain a trusted principal, enrollment, visit, actor,
  treatment, membership, capability assignment, or effect-validity decision.
- `target` is an untrusted routing claim. The server resolves it against
  canonical runtime identity, audience, and membership state; possession never
  proves ownership.
- `request_id` is unique per transmission attempt. A retry uses a new request ID.
- `idempotency_key` identifies one logical mutation and remains stable across
  retries. It is `idem_` plus the canonical 22-character unpadded base64url
  encoding of exactly 16 CSPRNG bytes, contains no user/content identifier, and
  is not a bearer secret.
- The command name/version selects one exact allowed payload `SchemaRef` from
  the deployment-pinned local registry. The caller cannot supply a schema URL
  or substitute another registered schema.
- Preconditions are scientific command content. Creation uses
  `expected_absent`; current-state mutations use exact `expected_revision` when
  required. Conflicting precondition forms fail schema validation.
- `producer` is used only by ordered producer APIs. It never becomes canonical
  stream order by itself.
- A raw `lease_token` is a credential. It is verified and removed at ingress,
  and never appears in persisted context, events, receipts, logs, or errors.
- `timeout_ms` is a requested duration capped by server and command policy. The
  authority creates the actual monotonic deadline at ingress.
- `client_observed_at` is optional untrusted evidence and never orders accepted
  commands.
- Every command schema sets message, payload, string, collection, and nesting
  limits. Unknown fields and duplicate JSON member names are rejected.

### Mandatory two-stage validation

Ingress validation is deliberately two-stage:

1. Validate the complete `WireCommandEnvelope`, including the structural
   `TypedObject`, against the shared envelope schema. Validate protocol,
   command type, IDs, limits, and the shape of the embedded `SchemaRef`.
2. Resolve the command's exact allowlisted payload `SchemaRef`; require the
   supplied name, version, and digest to match it; validate `payload.data`
   against that schema; and apply only schema-declared defaults and
   normalization.

No target resolution with observable side effects, semantic fingerprint,
idempotency claim, command execution, or durable effect may occur before both
stages succeed. Receipt results and error details undergo the same exact-schema
resolution and second-stage validation before persistence or emission. An
unknown schema, digest mismatch, or invalid embedded value fails closed.

## Trusted `CommandContext`

Only an authenticated gateway or trusted internal scheduler may construct:

```python
@dataclass(frozen=True)
class RuntimeProtocolBinding:
    study_version: StudyVersionRef
    deployment_revision: DeploymentRevisionRef
    enrollment_id: EnrollmentId | None
    visit_id: VisitId | None
    interaction_id: InteractionId | None
    actor_id: ActorInstanceId | None


@dataclass(frozen=True)
class CommandContext:
    command_id: CommandId
    request_id: RequestId
    command_type: CommandTypeRef
    target: ResourceRef
    idempotency_key: IdempotencyKey
    idempotency_scope: tuple[str, ...]
    semantic_fingerprint: Digest

    authenticated_subject: PrincipalRef
    source: Literal["browser", "worker", "admin", "webhook", "job", "internal"]

    runtime_protocol: RuntimeProtocolBinding | None

    verified_lease: FencingClaim | None

    received_at: UtcInstant
    received_clock_epoch_id: ClockEpochId
    received_monotonic_us: int
    deadline_monotonic_us: int | None

    correlation_id: CorrelationId
    causation: ResourceRef | None
    trace_context: TraceContext | None
    producer_position: ProducerPosition | None
```

Runtime commands require `RuntimeProtocolBinding`; its study version and
deployment revision are all-or-none and must agree with canonical visit/
interaction state. Publication, identity bootstrap, deployment creation, and
other platform-internal commands set `runtime_protocol=None` because inventing
a future version/revision would create false provenance. Their owning API binds
the exact study, git source state, compilation candidate, or platform scope
through the server-resolved target, typed payload, preconditions, and semantic
fingerprint.

All enrollment, visit, interaction, actor, membership, treatment, and
effect-validity scope is resolved from verified canonical state. The context
contains a verified lease reference, never the raw token; it contains no
resolved secret value, live database transaction, socket, environment instance,
or provider client.

`received_monotonic_us` and `deadline_monotonic_us` are coordinator-local and
make `CommandContext` nonportable across processes. A durable job or remote
worker request receives a bounded remaining duration/local cancellation budget,
not these foreign clock ticks; the coordinator retains and rechecks its own
deadline before effects.

The internal `idempotency_scope` tuple begins with a scope-class discriminator.
A runtime scope then contains deployment revision ID and study version ID; a
publication/platform scope contains neither. Both then contain the verified
subject reference, command family, target aggregate reference, and key in that
order. The tuple is never caller-supplied or exposed as a portable wire value.
The semantic fingerprint always binds the exact typed payload, target, and
preconditions; authoring publication additionally binds source revision,
registry snapshot, and candidate manifest digest through its domain payload.
`causation` is constrained by the command family to a command, event, decision,
message, tool call, invocation, or job `ResourceRef`.

All reference-valued fields above use shared-kernel types already defined in
the identifier/reference or time/fencing contracts: `PrincipalRef`,
`DeploymentRevisionRef`, `StudyVersionRef`, typed occurrence IDs,
`ResourceRef`, `TraceContext`, and `FencingClaim`. A service-triggered command
uses a `PrincipalRef` whose kind is `service` or `system`; it does not add a
second, undefined service-identity reference. Every `ResourceRef` in this
contract is exactly `{id}`, where `id` is a registered typed MUG ID and its
prefix is the sole kind discriminator. Revisions, ETags, labels, and other
resource state remain in their dedicated fields rather than being embedded in
the reference.

Initial validation does not guarantee later effect acceptance. Long-running
provider, tool, job, upload, and controller work must recheck runtime identity,
membership, lifecycle state, deadline, and fencing at effect time. Internal
jobs use a service principal and retain causation to the originating
command/event.

## Semantic fingerprint and idempotency scope

After exact schema validation and default resolution, the server computes an
RFC 8785/SHA-256 fingerprint over:

- Command name and version
- Exact payload `SchemaRef` and its schema-normalized `data`
- Pinned `study_version_id`
- Pinned `deployment_revision_id`
- Resolved target's domain-declared type and canonical ID
- Expected revision/state/absence and other scientific preconditions

It excludes request ID, trace data, transport metadata, client timestamp, raw
lease/auth token, server receive time, timeout budget consumed, and delivery
attempt. Lease generation is excluded so an already committed command can be
looked up after reconnect; an uncommitted effect still must pass the current
fence before execution.

The server, not the caller, derives an idempotency scope from:

```text
deployment revision ID + study version ID + verified runtime subject
+ command family + resolved target aggregate + idempotency key
```

Actor commands scope to the resolved actor/seat binding rather than merely the
participant principal. The scope survives connection replacement for the same
logical actor but prevents another actor from discovering or replaying a result.

### Required idempotency behavior

| Situation | Required result |
| --- | --- |
| New scope/key and valid command | Claim and execute once |
| Same scope/key/fingerprint, terminal | Return the same byte-equivalent immutable receipt |
| Same scope/key/fingerprint, running | Return/poll the existing status; do not start more work |
| Same scope/key, different fingerprint | `command.idempotency_conflict`; do not reveal the original payload |
| Same key in another derived scope | Independent command with no cross-scope disclosure |
| Failure before a terminal idempotency record | Retry the same logical command under its execution policy |
| External side effect may have occurred | Commit terminal `indeterminate`; never retry automatically |

Retry-specific facts never change the receipt. A delivery wrapper or transport
header carries the new request ID and `replayed=true`.

An idempotency record has `claimed → running → accepted | rejected |
indeterminate`. Pure database commands can claim and finish in one transaction.
Slow work commits a durable job before leaving that transaction; no transaction
or environment lock remains open over provider, tool, or object-store I/O. A
possibly executed non-idempotent external effect never returns to `claimed`.

Research-significant idempotency records live at least as long as their retained
evidence. Ephemeral realtime input may declare a bounded deduplication window in
its capture profile. Networked side effects must not claim an unprovable
“at-most-once and non-retryable” guarantee.

## Transport acknowledgment, status, and terminal receipt

- `TransportAck`: bytes were parsed, framed, or queued. It makes no scientific
  acceptance or durability claim.
- `CommandStatus`: mutable `queued`, `running`, `awaiting_external`, or
  `cancelling` projection with a poll/subscription reference.
- `CommandReceipt`: immutable `accepted`, `rejected`, or `indeterminate` result.

`pending` is a status, never a terminal receipt. Creating a slow job is itself a
transactional command: its receipt proves `JobCreated`, while job completion has
a separate terminal transition/receipt or result artifact.

This shared-kernel contract defines the distinction but deliberately does not
define either portable shape. API-09 owns the exact `TransportAck` wire shape
for each transport. API-22 owns the exact durable-job `CommandStatus` query and
subscription shapes. Neither may reuse `CommandReceipt` or imply its acceptance
semantics.

A malformed/unsupported request, failed authentication, concealed resource, or
transient dependency failure before a terminal record returns `DomainError`.
A deterministic domain rejection after idempotency claim—revision, lifecycle,
lease, deadline, uniqueness, or policy rejection—gets an immutable rejected
receipt so retry cannot produce a different decision under the same key.

## Receipt and effect durability

A receipt states three related facts:

1. `receipt_class`: compatibility with the public `IngressReceipt`,
   `CommitReceipt`, or `ArtifactCommitReceipt` contract.
2. Durability of the receipt record: `runtime`, `journaled`, or `transactional`.
3. Durability of the accepted effect: `none`, `runtime`, `journaled`,
   `transactional`, `artifact_committed`, or `unknown`.

| Value | Meaning |
| --- | --- |
| `runtime` | Accepted by the currently fenced runtime; process failure may lose it |
| `journaled` | Written to the named durable append/WAL profile before acknowledgment |
| `transactional` | Committed with aggregate revision, idempotency result, canonical research event, and outbox in one relational Unit of Work |
| `artifact_committed` | Bytes were finalized, digest/size verified and readable, then the relational Unit of Work committed the reference |
| `none` | No effect was accepted |
| `unknown` | An external side effect may have happened and requires reconciliation |

The required `profile` identifies a deployment-pinned failure model, for
example process-crash-safe versus replicated host-loss-safe. “Journaled” or
“transactional” without a named profile is not a complete operational promise.

Mapping rules:

- An accepted `ingress` receipt has runtime or journaled receipt/effect
  durability and is never proof of committed workflow/scientific state.
- An accepted `commit` receipt has transactional receipt/effect durability.
- An accepted `artifact_commit` receipt has transactional receipt durability
  and `artifact_committed` effect durability.
- A rejected receipt has `effect=none`; its receipt durability still states
  whether the rejection/idempotency result survives a failure.
- An indeterminate external outcome must have a durable terminal receipt with
  `effect=unknown`, error code `external.unknown_outcome`, and retry mode
  `operator_reconciliation`. No other retry directive is valid for an
  indeterminate receipt.

Minimum accepted effect durability:

| Command category | Minimum |
| --- | --- |
| Assignment, visit plan, advancement, completion | `transactional` |
| Form or preference response | `transactional` |
| Committed chat message and membership/role change | `transactional` |
| Model/tool/job enqueue | `transactional` |
| Artifact finalization | `artifact_committed` |
| High-rate game input | `runtime` or `journaled`, exactly as capture profile declares |
| Final game transition/trajectory chunk | `journaled` or `artifact_committed`, exactly as capture profile declares |
| Streaming presentation delta | Usually `runtime`; it is not a committed chat message |

Later object outage or bit rot does not falsify a historical receipt. It creates
an integrity/availability incident and withdraws affected replay, preference,
or export capabilities.

## Receipt shape

```json
{
  "schema": {
    "name": "mug.command-receipt",
    "version": 0,
    "digest": {
      "algorithm": "sha-256",
      "hex": "f675d9ec1f6258719da93a507421689b26babf69d36503c7df90b5039e238d6d"
    }
  },
  "receipt_id": "receipt_019b5ed4-14ec-7f51-89c9-d42db811f040",
  "command_id": "command_019b5ed1-14ec-7f51-89c9-d42db811f041",
  "command": {
    "name": "preference.response.submit",
    "version": 0
  },
  "idempotency_key": "idem_7Gg3L2M1qPv9sXr4Nk8BzQ",
  "outcome": "accepted",
  "receipt_class": "commit",
  "durability": {
    "receipt": "transactional",
    "effect": "transactional",
    "profile": "postgres-synchronous-v1"
  },
  "recorded_at": "2026-07-17T14:22:31.439000Z",
  "resource": {
    "id": "prefresponse_019b5ed4-14ec-7f51-89c9-d42db811f042"
  },
  "version_stamp": {
    "revision": 1,
    "etag": "sha256:7fdf5d353a83b3a1c0414b2a175d49d1e612db83bb376edc6ee1d826203bc45e"
  },
  "stream_positions": {
    "stream_019b5ecd-14ec-7f51-89c9-d42db811f043": 9
  },
  "result": {
    "schema": {
      "name": "mug.preference.response-submit-result",
      "version": 0,
      "digest": {
        "algorithm": "sha-256",
        "hex": "e80fad50984383eb0e6417d1b726f38225b23417a3b6da3f4e79ee8ac9b22e89"
      }
    },
    "data": {
      "response_id": "prefresponse_019b5ed4-14ec-7f51-89c9-d42db811f042"
    }
  }
}
```

Accepted receipts carry `result`; rejected and indeterminate receipts carry a
privacy-safe `error`. The schema makes those branches disjoint. Domain result
and error-detail objects have exact command-owned schemas even though the shared
envelope treats them as typed domain-owned slots.

`stream_positions` is an object keyed by canonical `StreamId`, with a positive
accepted sequence as each value. Canonical serialization sorts those keys.
Every accepted `commit` or `artifact_commit` receipt contains at least one
entry, proving where its canonical acceptance fact was recorded. An `ingress`
receipt uses an empty object when no canonical stream position exists yet.

## Transactional Unit of Work

For every transactional domain command, one relational commit atomically
writes:

```text
aggregate state and next revision
terminal idempotency record and immutable receipt
canonical domain event
outbox entries
already-finalized artifact metadata/reference, if applicable
```

No accepted `CommitReceipt` may exist for a subset. Event chunks may later be
compacted into artifacts, but the Unit of Work contains a durable authoritative
event/outbox record before acknowledgment.

Artifact creation is ordered:

```text
create staging ticket → upload → verify expected size/digest → finalize object
→ verify readable → relational Unit of Work commits ArtifactRef + receipt
→ asynchronously collect unreferenced staging/finalized orphans
```

Object-store finalization returns an internal finalized-object token, not a
domain-visible committed `ArtifactRef`.

## Optimistic concurrency and uniqueness

- New durable aggregates begin at revision `1`.
- Each successful aggregate mutation increments the revision exactly once.
- A current-state-dependent command requires exact `expected_revision`.
- Creation uses `expected_absent`.
- Omission is allowed only for a documented commutative append,
  uniqueness-constrained create, or blind observation.
- Randomization, assignment, preference finalization, plan decisions, and
  memory commits are never silently recomputed after conflict.
- A conflict response may return the current revision to the request's valid
  audience, but not protected state. The caller refreshes, makes a new semantic
  decision, and uses a new idempotency key.
- Multi-aggregate commands declare every precondition, execute in one database
  transaction, and use deterministic lock ordering. Distributed transactions
  across authoritative services are not the default.

Uniqueness is distinct from idempotency. A new key attempting to finalize an
already finalized preference assignment returns `preference.already_finalized`;
it never creates a second response.

## Domain error envelope

```json
{
  "schema": {
    "name": "mug.domain-error",
    "version": 0,
    "digest": {
      "algorithm": "sha-256",
      "hex": "f675d9ec1f6258719da93a507421689b26babf69d36503c7df90b5039e238d6d"
    }
  },
  "error_id": "error_019b5ed9-14ec-7f51-89c9-d42db811f044",
  "request_id": "request_019b5ed0-14ec-7f51-89c9-d42db811f03b",
  "recorded_at": "2026-07-17T14:22:31.440000Z",
  "command": {
    "name": "preference.response.submit",
    "version": 0
  },
  "code": "command.revision_conflict",
  "category": "conflict",
  "safe_message": "The assignment changed. Refresh it before submitting again.",
  "retry": {
    "mode": "refresh_then_new_command"
  },
  "details": {
    "schema": {
      "name": "mug.error.command-revision-conflict-details",
      "version": 0,
      "digest": {
        "algorithm": "sha-256",
        "hex": "f55aa68443d9fc110655dfe412abdf6c1131f81917c7f9236c3f1ff2da55309e"
      }
    },
    "data": {
      "expected_revision": 3,
      "current_revision": 4
    }
  },
  "support_reference": "error_019b5ed9-14ec-7f51-89c9-d42db811f044"
}
```

`code` is machine-stable; `safe_message` is localizable explanatory text and is
not stable. Retry modes are:

- `never`
- `same_command`
- `poll_existing`
- `refresh_then_new_command`
- `after_reauthentication`
- `operator_reconciliation`

`request_id` is optional in `DomainError`. It is present only after the
envelope's request ID has passed structural validation; errors for malformed
JSON, duplicate members, invalid IDs, or an invalid envelope may omit it.
When present, `details` is a `TypedObject` using the one exact details
`SchemaRef` registered for that error code. Codes with no public details omit
the field rather than using an untyped empty object.

Initial stable code families are:

| Family | Required codes |
| --- | --- |
| Protocol/schema | `protocol.invalid_envelope`, `protocol.unsupported_version`, `schema.validation_failed` |
| Runtime identity/membership | `auth.unauthenticated`, `auth.forbidden` |
| Resource | `resource.not_found`, `resource.already_exists` |
| Commands | `command.idempotency_conflict`, `command.revision_conflict`, `command.state_conflict`, `command.uniqueness_conflict`, `command.deadline_exceeded`, `command.cancelled` |
| Lease/decision | `lease.expired`, `lease.stale_generation`, `decision.stale_generation` |
| Ordering | `sequence.gap`, `sequence.conflict`, `sequence.stale`, `event.cursor_expired` |
| Capability/quota | `capability.unsupported`, `quota.rate_limited`, `quota.budget_exceeded`, `runtime.backpressure` |
| Dependency/effect | `dependency.unavailable`, `external.unknown_outcome` |
| Artifact/privacy | `artifact.integrity_failed`, `artifact.unavailable`, `privacy.policy_violation` |
| Internal | `internal.unexpected` |

Each code owns a strict `details` schema. Public details never contain raw
exceptions, stack traces, SQL/provider messages, credentials, prompts, model or
tool bodies, external identity, PII, protected object names, or undisclosed
existence. Where existence is sensitive, forbidden and nonexistent produce the
same observable public envelope. Private diagnostics correlate by `error_id`.

## Cancellation and recovery

Cancellation is a best-effort command, not rollback. It may prevent a pending
effect, but cannot erase an already accepted fact or guarantee an external side
effect did not occur. A terminal receipt wins over a racing cancellation;
otherwise the command contract records cancelled, rejected, or indeterminate.

After process failure:

- No terminal record: retry under the same key according to execution policy.
- Transaction committed before reply: retry returns the original receipt.
- Durable job exists: return its status, never enqueue a second job.
- External effect is ambiguous: return the committed indeterminate receipt and
  require reconciliation/compensation.
- Artifact bytes without relational reference: treat as an orphan; never expose
  a committed reference.

## Required command-specific declarations

Every domain command specification must declare:

1. Payload/result/error-detail schemas and maximum sizes, each embedded through
   an exact `TypedObject`/`SchemaRef` and mandatory second-stage validation
2. Aggregate owner and target resolution
3. Required runtime identity/membership and effect-time validity checks
4. Idempotency scope/fingerprint fields and bounded lifetime
5. Required preconditions and uniqueness constraints
6. Minimum receipt/effect durability and named deployment profile
7. Transaction/canonical-event/outbox/artifact effects
8. Deadline, cancellation, retry, reconnect, and crash behavior
9. Stable rejection/error codes and concealment policy
10. Golden success, duplicate, conflict, stale, failure, and redaction fixtures
