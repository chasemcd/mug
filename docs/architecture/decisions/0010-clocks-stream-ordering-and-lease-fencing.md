# ADR 0010: Clocks, Stream Ordering, and Lease Fencing

| Field | Value |
| --- | --- |
| Status | Accepted |
| Accepted | 2026-07-20 (decision ratified; the runtime-layer schema byte-freeze lands with the API-06/API-12 runtime-layer freeze per decision D3) |
| Date | 2026-07-17 |
| Owners | Unassigned |
| Supersedes | None |
| Superseded by | None |
| Affects | API-06 through API-10, API-12, API-14 through API-16, API-22 |

## Context

MUG will coordinate game steps, browser frames, chat messages, provider/tool
work, P2P rollback, uploads, and worker ownership. Wall clocks can skew; clients
are untrusted; independently ordered modalities can be concurrent; old sockets
and workers can continue after reassignment. A single timestamp, socket ID, or
process-local lock cannot establish scientific order or authority.

## Decision

Adopt the [time, ordering, and fencing contract](../phase-0/shared-kernel/time-ordering-and-fencing.md):

- Type UTC audit time, coordinator-local monotonic time, durations,
  client/provider source times, environment steps, render frames, channel turns,
  stream sequences, and producer positions separately.
- Create authoritative deadlines from capped durations on the authority's
  monotonic clock; those ticks never cross a process/clock epoch. Remote work
  receives a bounded duration and derives its own local cancellation deadline;
  the owning authority rechecks its original deadline and semantic validity
  before effects.
- Give each canonical stream one append authority and contiguous sequence from
  1. Conditional append establishes order; event IDs, UUIDs, revisions, and
  timestamps do not.
- Relate streams through explicit correlation, causation, modality coordinates,
  state/context hashes, and same-clock monotonic anchors. An optional
  interaction acceptance sequence means server acceptance order only.
- Give ordered untrusted producers their own epoch, sequence, and content digest;
  canonical acceptance assigns a separate stream position.
- Separate connection leases from runtime ownership leases. Every takeover
  increments a fencing generation; effect-time application conditionally checks
  namespace epoch and generation.
- On ephemeral lease-state loss, change namespace epoch before accepting
  effects, invalidating every old token.
- In P2P, each replica owns its assertion/experienced stream and a separate
  finality authority reconciles matching, missing, or conflicting evidence.

## Scope and non-goals

This ADR defines shared clock/order/lease semantics, not the game cadence,
rollback algorithm, chat activation policy, stream partition key, lease backend,
or event envelope. Owning APIs must make those concrete without violating the
invariants.

## Invariants

- Wall-clock or UUID order is never canonical order.
- Monotonic values are compared only within one clock epoch.
- A remote worker never evaluates a coordinator's monotonic deadline or lease
  expiry; only the clock-owning authority does so.
- Canonical stream sequences are contiguous, unique, and authority-assigned.
- Producer sequence never becomes canonical sequence directly.
- Aggregate revision and stream sequence remain different types.
- Lease namespace epochs and generations are never reused.
- Every live effect checks current fence, authorization, lifecycle state, and
  semantic validity at application time.
- Stale work cannot mutate game/workflow state, publish chat, call a new tool,
  or write memory.
- Independent modality streams are not forced into a false universal order.

## Consequences

### Positive

- Reconnect, duplicate tabs, worker failover, late provider completion, and P2P
  disagreement have explicit deterministic handling.
- Replay/preferences can state which canonical or experienced perspective and
  modality coordinates they use.
- Slow work can run asynchronously without holding the environment lock while
  stale completions remain harmless.

### Costs and constraints

- Effects must carry/check generations and semantic coordinates all the way to
  the owning authority.
- Multi-stream analysis must reason from causal anchors rather than one easy but
  misleading timestamp sort.
- Lease-store disaster recovery requires a durable/current namespace epoch.
- Producer gap/equivocation and P2P reconciliation need explicit evidence states.

### Failure consequences

- Sequence gap/conflict produces no canonical allocation until resolved under a
  bounded declared policy.
- Old-generation socket/worker/provider output is rejected at effect time.
- Missing P2P evidence is partial/unverified; conflicting evidence is disputed
  or quarantined, never silently chosen.
- Loss of monotonic epoch prevents comparing old/new ticks; UTC remains
  diagnostic only. Remote completion before a worker-local timeout never proves
  that a coordinator deadline was met.

## Security and privacy

Lease tokens are credentials, removed after verification and forbidden in
events/logs/receipts. Connection ownership does not grant enrollment or channel
rights. Client/provider timestamps cannot manipulate order/deadlines. Producer
equivocation can trigger quarantine/fencing. Cross-stream anchors are classified
data and exported only under policy.

## API and schema impact

Shared types include `UtcInstant`, duration, `StreamPosition`, `EventCursor`,
producer position, `LeaseRef`, and trusted fencing claims. Coordinator
monotonic ticks remain internal; async requests cross processes with bounded
durations/local cancellation rather than foreign ticks. API-06 owns lease and
interaction policy; API-07 owns game coordinates/finality; API-08 owns channel
order/delivery; API-10 owns event streams; API-12/14/22 carry stale/deadline
coordinates through async work; API-16 represents replay synchronization.

## Alternatives considered

### One global interaction sequence as physical truth

Rejected because server ingest order cannot describe physical causality or what
different participants experienced.

### Sort by wall-clock or UUIDv7

Rejected because clocks skew and UUID issuance time is not acceptance authority.

### Rely on socket disconnect or lease expiry without fencing

Rejected because delayed work can apply after reassignment. Effect-time
generation checks are required.

### Pick one peer's P2P log as canonical

Rejected because clients can be missing, divergent, buggy, or malicious. Claims
and reconciliation status must remain visible.

## Validation

- Conditional append concurrency, producer duplicate/equivocation/gap tests
- Clock skew, malicious timestamp, deadline race, and new-clock-epoch tests
- Duplicate-tab takeover, worker takeover, lease-store loss, stale provider/tool
  result, and conditional database write tests
- NS-04 concurrent chat, NS-06 cross-modal synchronization, NS-07 late decision,
  NS-09 P2P rollback/reconciliation, NS-11 tool timeout

## Follow-up decisions

- Interaction/channel/lease lifecycle and backend — API-06
- Game action cadence, rollback/finality, state hash — API-07
- Chat activation/publication/delivery ordering — API-08
- Event envelope, partitioning, append, compaction — API-10
- Replay synchronization and completeness capability — API-16
