# ADR 0009: Commands, Receipts, Idempotency, and Concurrency

| Field | Value |
| --- | --- |
| Status | Accepted |
| Accepted | 2026-07-20 (decision ratified; the runtime-layer schema byte-freeze plus the runtime review-panel findings and the D1 self-contained-receipt change land with the API-06/API-12 runtime-layer freeze per decision D3) |
| Date | 2026-07-17 |
| Last updated | 2026-07-20 |
| Owners | Unassigned |
| Supersedes | None |
| Superseded by | [ADR 0015](0015-governance-out-of-scope.md) in part: governance authorization and admin-audit requirements removed; runtime authority and canonical evidence remain |
| Affects | Every mutable command API; especially API-04, API-06, API-08 through API-11, API-14, API-18, API-22 |

## Context

Participant reconnects, duplicate browser submissions, worker crashes, provider
timeouts, artifact uploads, and multi-process deployment make transport-level
“success” scientifically ambiguous. A preference response, visit advance, game
input, streaming token, tool side effect, and finalized artifact have different
durability. Client-supplied participant/actor fields are also not trustworthy
runtime identity or membership context.

## Decision

Adopt the [commands, receipts, and errors contract](../phase-0/shared-kernel/commands-receipts-and-errors.md):

- Separate untrusted `WireCommandEnvelope`, trusted server-derived
  `CommandContext`, mutable `CommandStatus`, immutable terminal
  `CommandReceipt`, transport delivery metadata, and `DomainError`.
- Wrap command payloads, receipt results, and public error details in a
  `TypedObject` carrying their exact `SchemaRef`; resolve and validate the
  embedded `data` a second time before fingerprinting, executing, persisting,
  or emitting it.
- Derive principal, enrollment, visit, interaction, actor, treatment,
  membership, effect validity, and idempotency scope on the server.
- Use a caller-generated random idempotency key and a schema-normalized semantic
  fingerprint. Runtime commands include and scope by their pinned study version
  and deployment revision. Pre-publication/platform commands have no fabricated
  runtime binding; they scope by a discriminator, authenticated subject,
  command family, and target while their fingerprint binds domain source/
  candidate/preconditions. Same scope/key/fingerprint returns the same byte-
  equivalent receipt; conflicting content returns
  `command.idempotency_conflict`.
- Record terminal `accepted`, `rejected`, or `indeterminate`. `pending` is a
  mutable status, not a receipt; unknown external side effects become durable
  indeterminate results, require `operator_reconciliation`, and are never
  retried automatically.
- Retain public receipt classes `ingress`, `commit`, and `artifact_commit`, and
  also state receipt/effect durability plus a deployment-pinned failure profile.
- For transactional commands, atomically commit aggregate revision, terminal
  idempotency record/receipt, canonical research event, and outbox.
  Artifact bytes are finalized and verified before that transaction commits a
  domain-visible reference.
- Require exact optimistic revisions for current-state decisions and explicit
  absence for creation. Never silently recompute a scientific decision after a
  conflict.
- Use stable privacy-safe error codes/details and explicit retry directives.
- Represent receipt stream positions as a stream-ID-keyed object. Every
  accepted commit or artifact-commit receipt cites at least one canonical
  stream position.

## Scope and non-goals

This ADR defines shared command processing and durability claims. Domain APIs
still own transitions, payload/result/error-detail schemas, minimum durability,
runtime identity/membership checks, effect validity, and aggregate boundaries.
It does not promise exactly-once delivery or distributed transactions over
providers/tools/object stores.

## Invariants

- Wire input cannot construct trusted authority.
- Embedded domain objects cannot be fingerprinted or acted on until their exact
  allowlisted schema reference and `data` pass second-stage validation.
- One idempotency scope/key has one fingerprint and at most one terminal receipt.
- Retried delivery does not mutate the original receipt.
- A transactional accepted receipt cannot exist without the complete Unit of
  Work.
- No committed artifact reference points to bytes that were unfinalized,
  unverified, or unreadable at commit time.
- An aggregate revision increments once per committed mutation and is distinct
  from event sequence.
- Stale/conflicting commands do not silently retry randomization, assignment,
  preference, plan, or memory decisions.
- No database transaction or environment mutation lock spans provider, tool, or
  object-store I/O.

## Consequences

### Positive

- Lost replies and reconnects have a precise, testable outcome.
- Receipts make the exact research durability boundary visible.
- Slow work enters through durable jobs rather than blocking sockets/game loops.
- Stable rejected/indeterminate results prevent retries from changing past
  decisions or duplicating uncertain side effects.

### Costs and constraints

- Every mutable domain needs idempotency storage, revision/precondition rules,
  receipt schemas, safe errors, and fault tests.
- High-rate runtime inputs need declared bounded deduplication/capture policy.
- A relational Unit of Work and outbox become mandatory infrastructure for
  transactional commands.
- Callers must refresh and submit a new key after a semantic conflict.

### Failure consequences

- Crash before terminal commit permits the declared safe retry path.
- Crash after commit but before reply returns the original receipt.
- Ambiguous external side effect blocks automatic retry and requires explicit
  reconciliation or compensation.
- Uploaded but unreferenced bytes remain an orphan eligible for safe cleanup.
- Later artifact unavailability appends an incident/availability state and
  retracts capabilities without falsifying the historical receipt.

## Security and privacy

Authentication and resource resolution precede receipt disclosure. Idempotency
keys contain no participant/content identity and are scoped server-side.
Forbidden/nonexistent protected resources can share one public response.
Receipts/errors exclude raw prompts, chat/tool bodies, provider/SQL exceptions,
credentials, PII, and secret/lease/auth tokens. Private diagnostics correlate
by opaque IDs through the trusted operator's protected store.

## API and schema impact

API-09 owns transport framing but uses the shared envelope. Every command API
declares payload/result/detail schemas and minimum receipt class. API-10/11
implement event/outbox and Unit-of-Work semantics. API-22 represents slow work
with durable jobs and owns `CommandStatus`; API-09 owns the exact
`TransportAck` shape. API-14 uses `indeterminate` for unknown external effects.

## Alternatives considered

### Treat HTTP/WebSocket acknowledgment as success

Rejected because it does not state whether scientific state, evidence, an
artifact, or merely volatile bytes were accepted.

### Trust participant/actor IDs from the body

Rejected because identifiers are routing claims, not authenticated ownership.

### Use request ID as both transmission and idempotency identity

Rejected because each retry attempt needs separate operational correlation
while one logical mutation needs stable deduplication.

### Retry every timeout automatically

Rejected because external tools may have performed a side effect and scientific
decisions may be stale after provider completion.

### Advertise at-most-once nonretryable network effects

Rejected because ambiguous failures generally cannot prove whether a remote
effect happened. Durable indeterminate state is more honest.

## Validation

- SK-11 through SK-30 in the
  [conformance plan](../phase-0/shared-kernel/conformance.md)
- Transaction fault injection before/after each Unit-of-Work and artifact stage
- Concurrent duplicate, conflicting key, revision, state, and uniqueness tests
- NS-08 lost completion receipt, NS-10 preference retry, NS-11 unknown tool
  outcome, and database/object outage walks

## Follow-up decisions

- Aggregate/transaction ownership map — each domain API plus API-11
- Initial deployment durability profiles — API-02/API-07/API-10/API-11
- Ephemeral game-input deduplication windows — API-07/API-09
- Job status/result/cancellation schema — API-22
