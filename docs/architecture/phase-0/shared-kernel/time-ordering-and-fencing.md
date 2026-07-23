# Time, Ordering, and Fencing

| Field | Value |
| --- | --- |
| Status | Draft |
| Contract revision | `0.2` |
| Owner | Shared kernel; stream and lease policies remain domain-owned |
| Last updated | 2026-07-20 |
| Decision | Proposed ADR 0010; complements ADR 0006 |
| Scenario anchors | NS-04, NS-06, NS-07, NS-09, NS-11 |

## Clock types

Every time-like field has exactly one declared clock or coordinate type.

| Type | Meaning | Ordering scope |
| --- | --- | --- |
| `UtcInstant` | Authority-assigned diagnostic/human correlation time | Never canonical order |
| `MonotonicInstant` | Integer ticks plus one coordinator clock epoch | Only within that exact clock epoch |
| `Duration` | Nonnegative quantity with explicit unit | Not a timestamp |
| `ClientObservedInstant` | Untrusted device-reported evidence, optionally calibrated | Never authority order |
| `ProviderInstant` | Provider-reported evidence | Never authority order |
| Environment step | Transition coordinate in one episode/generation | Environment-owned |
| Render frame | Presented/speculative frame coordinate in one renderer stream | Renderer-owned |
| Conversation sequence/turn | Accepted message/context coordinate in one channel | Channel-owned |
| Stream sequence | Canonical append position in one stream | Stream authority-owned |
| Producer sequence | Producer-local submission position in one epoch | Evidence for ingest, not canonical order |

Canonical JSON encodes UTC and portable durations as defined in
[serialization](serialization-and-schema-evolution.md). Internal monotonic
instants use `(clock_epoch_id, ticks_us)` and never cross coordinator process or
clock-epoch boundaries. Only the authority that owns that clock may compare
those ticks or decide that its deadline/lease expiry has passed.

Recommended event time fields are:

- `occurred_at`: UTC instant assigned when the domain authority accepted the
  transition; diagnostic/correlation evidence only.
- `recorded_at`: UTC instant assigned when durable evidence committed.
- `client_observed_at`: separately labeled untrusted device evidence.
- `provider_reported_at`: separately labeled provider evidence.

None establishes canonical order. Higher-precision external values are retained
as typed source data rather than silently rounded into `UtcInstant`.

## Deadlines

Wire callers request a timeout duration. At ingress, the authority caps it and
creates a deadline on its current monotonic clock. A client-supplied wall-clock
deadline never controls acceptance.

The coordinator retains the authoritative `(clock_epoch_id,
deadline_monotonic_us)`. Same-process work may receive that value because it can
read the same monotonic clock. Work dispatched to another process or host never
receives coordinator ticks as a portable deadline. It instead receives:

- A bounded remaining-duration budget computed at dispatch
- Its own cancellation signal/handle and enough correlation to report timeout
- Interaction/episode/channel generation
- Source state hash or context cursor
- Required lease/fencing generation
- The declared fallback policy

The remote worker derives a local best-effort deadline from its own monotonic
clock. Queue and network time can consume the coordinator's budget, so worker
completion before its local timeout is never proof that the authoritative
deadline was met. UTC deadline values, if included for diagnostics, are also not
authority.

Success before a provider's own timeout is insufficient. Before applying an
effect, the coordinator/owning authority rechecks its own authoritative
monotonic deadline and every semantic validity coordinate. A late result remains
provider provenance but is disposed as stale; it cannot step the environment,
publish chat, call another tool, advance a visit, or write memory.

## Canonical streams

Each canonical stream has:

1. One declared append authority at any instant
2. A monotonically increasing, contiguous safe-integer sequence beginning at 1
3. Conditional append against the expected tail
4. A unique `EventId` independent of sequence
5. An immutable schema/capture/authority policy

A transaction appending multiple events reserves one contiguous range. Stream
sequence and aggregate revision remain separate: one command can append several
events but increment its aggregate once, and one event can describe an
observation without mutating that aggregate.

`EventCursor.after_sequence=0` means before the first event. A stream never
reuses a sequence after invalidation or quarantine; corrections append new
facts.

## Cross-stream relationships

There is no universal physical order among game, chat, render, provider, tool,
and participant-experienced evidence. Relationships use explicit fields:

- Correlation ID for one workflow or interaction
- Causation command/event/decision reference
- Episode plus environment step/generation/state hash
- Render stream plus frame/generation
- Channel stream plus message sequence/context cursor
- Participant delivery stream plus delivery/display position
- Coordinator monotonic anchor only where values share one clock epoch

An optional `interaction_acceptance_sequence` means only “accepted by this
server coordinator in this order.” It must not be called global, physical,
causal, rendered, or participant-experienced order.

ADR 0006 keeps canonical accepted facts separate from participant-experienced
delivery/speculation evidence. Missing experienced evidence changes
completeness claims; it does not invent or reorder canonical facts.

## Ordered producers

Browser, peer, sensor, uploader, or replica streams that require duplicate/gap
detection carry:

```text
producer identity + producer epoch + producer sequence + content digest
```

The producer sequence begins at 1 within a fresh epoch. Canonical acceptance
assigns a separate server stream sequence.

| Input | Required behavior |
| --- | --- |
| Same epoch/sequence/digest already accepted | Return the prior producer receipt; allocate no event |
| Same epoch/sequence with different digest | `sequence.conflict`; quarantine/fence as policy requires |
| Sequence below expected and not a known duplicate | `sequence.stale` |
| Sequence above expected | `sequence.gap` with the safe next expected position |
| Gap under a declared buffer policy | Buffer within exact count/byte/time limits; do not allocate canonical order yet |

A producer epoch is not a connection ID: reconnect can resume it when the
signed policy permits. Focus loss, rollback, speculative frames, skipped
delivery, and correction remain participant-experienced evidence rather than
being smuggled into the finalized trajectory.

## Lease types

MUG keeps two ownership concepts distinct:

- `ConnectionLease`: which live participant connection may currently act for an
  actor/binding.
- `OwnershipLease`: which worker/coordinator owns an interaction, environment
  replica, channel sequencer, job, or other runtime authority.

Neither proves enrollment, channel membership, role capability, or effect
validity.

A verified internal `FencingClaim` contains:

```python
@dataclass(frozen=True)
class FencingClaim:
    lease_id: LeaseId
    namespace_epoch_id: LeaseNamespaceEpochId
    resource: ResourceRef
    holder: PrincipalRef | ResourceRef
    generation: int
    expires_clock_epoch_id: ClockEpochId
    expires_monotonic_us: int
```

The public `LeaseRef` omits holder and expiry. The raw signed `LeaseToken` is a
credential verified into this claim and then discarded.

`expires_clock_epoch_id` and `expires_monotonic_us` are meaningful only to the
lease authority that owns that clock. A remote worker may carry the reference
for diagnostics and may use a separately supplied local renewal/cancellation
budget, but it must not decide that the authoritative lease is current by
comparing foreign monotonic ticks. Effect-time validity comes from an
authoritative lease check or an atomic stored epoch/generation condition.

## Fencing rules

1. Creating or taking over ownership atomically increments the resource's
   generation. Generations start at 1 and are never reused or decremented.
2. Renewal of the same lease extends expiry without changing generation.
3. Effect application checks the current namespace epoch and generation at the
   authoritative resource, not only at request start.
4. Database writes owned by a worker include a conditional generation check in
   the same transaction as the effect.
5. A delayed old-generation command is stale even if the same participant later
   reacquires the same seat.
6. Duplicate-tab policy either rejects takeover or deliberately fences the old
   tab; implicit last-socket-wins behavior is forbidden.
7. If ephemeral lease state is lost, the coordinator changes its namespace
   epoch before serving effects. Every pre-loss token becomes invalid even if a
   generation value collides.
8. Events may retain non-secret lease ID/epoch/generation when scientifically
   useful, but never the token.
9. Expiry uses the lease authority's monotonic clock. Only that authority
   compares its epoch/ticks; remote workers use renewal/cancellation budgets and
   the effect owner verifies the current epoch/generation. UTC expiry in a
   client display is advisory only.

A caller retrieving an already committed idempotent result does not need the
old lease: verify the current runtime subject and receipt audience, then return
it without applying anything. An uncommitted stale-lease command gets a
terminal rejection; a new action after reacquisition uses a new idempotency key
because it is a new authority decision.

## Modality-specific defaults

| Case | Default |
| --- | --- |
| Concurrent chat messages | Channel authority assigns canonical sequence; client clocks do not |
| Concurrent agent completions | Publication authority applies the declared ordering/activation policy after effect-time checks |
| Game input for finalized past step | Reject stale |
| Game input too far ahead | Reject or bounded-buffer under declared step policy |
| Multiple actions for one actor/step | Apply published `first_accepted`, `latest_before_cutoff`, or aggregation rule |
| Realtime reconnect after generation change | Snapshot/current terminal outcome; reject obsolete-generation commands |
| P2P deterministic replicas | Each peer owns its assertion/experienced streams; finality authority reconciles claims |
| P2P matching final digests | Append reconciled finality evidence |
| P2P missing/conflicting claims | Mark partial/unverified or disputed/quarantined; never invent a canonical winner |
| Chat plus game action from one LLM decision | Validate/publish effects independently by default under one decision ID |

P2P therefore has one writer per deterministic replica plus an explicit
reconciliation/finality authority, not one fictional global environment writer.

## Invariants

1. Event ID, request ID, command ID, idempotency key, revision, sequence, and
   clock coordinate remain distinct types.
2. Canonical order is never inferred from a UUID or timestamp.
3. Monotonic values are never compared across clock epochs.
4. One canonical stream sequence has one current append authority.
5. Producer position never directly becomes canonical position.
6. Lease namespace epochs and generations are never reused.
7. Every effect checks the current fence, runtime identity/membership,
   lifecycle state, and semantic validity immediately before application.
8. Stale/rejected work cannot publish chat, mutate environment state, create a
   new tool effect, advance workflow, or write memory.

## Required validation

- Concurrent conditional appends allocate one contiguous order with no gaps.
- Same producer position/digest deduplicates; equivocation is detected.
- Clock skew and malicious client timestamps do not affect order/deadline.
- Generation takeover fences delayed sockets, workers, provider completions, and
  database writes.
- Lease-store loss invalidates every prior token through namespace epoch.
- NS-06 relates independently ordered game/chat/render evidence without a false
  global order.
- NS-09 exercises rollback, reconciliation, partial evidence, and disagreement.
