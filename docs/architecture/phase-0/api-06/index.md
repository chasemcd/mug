# API-06: Interactions, Channels, Membership, Matchmaking, and Leases

| Field | Value |
| --- | --- |
| Status | Draft |
| Contract revision | `0.3` |
| Accountable owner | Unassigned |
| Last updated | 2026-07-20 |
| Consumers | API-07/API-08 (channel execution), API-09 (connections), API-05 (actors), API-10 (evidence) |
| Depends on | [Shared kernel 0.2](../shared-kernel/index.md), [API-04 0.2](../api-04/index.md), [API-05 0.2](../api-05/index.md), proposed ADRs 0002, 0010 |
| Implementation phase | Phase 1-2 |
| Stability tiers | Application command/query, wire, archival |

## Outcome

API-06 is the shared coordination and evidence boundary for a running activity:
one `Interaction` owns seats, actor instances, channels, membership, matchmaking,
and connection leases. A multiplayer game with chat is **one interaction with
multiple channels** whose streams are causally linked but independently ordered
(D08-1), not two unrelated sessions — which is what lets replay line up "what
was on screen when this message was sent."

## Channel kinds

Channel kinds are a **typed, closed set** (D08-2, F-3): `ChannelKind.GAME`,
`ChannelKind.CHAT`, `ChannelKind.ANNOTATION`. Each kind carries its own
ordering guarantee — the author picks the kind, never the ordering mechanics:

| Kind | Ordering guarantee |
| --- | --- |
| `ChannelKind.GAME` | Per-producer ordering; execution contract in API-07 |
| `ChannelKind.CHAT` | Total order + idempotent delivery; execution contract in API-08 |
| `ChannelKind.ANNOTATION` | Total order + idempotent; judgments/annotations attached to the interaction (API-17/18 activities) |

No other kinds exist in v0; extension is a vocabulary change to this contract,
not author-defined.

## Membership

Membership **defaults to all seats read/write** (D08-3): a channel declared
with no membership means every seat sees and can write — the common case is
zero lines. Explicit `Membership` is **opt-out narrowing** for asymmetry only
(observers, spectators, one-way announcements, asymmetric-information designs):
per actor per channel, one of `Membership.READ_WRITE`, `Membership.READ_ONLY`,
`Membership.NONE` (F-3 typed constants).

## Group execution (R-18)

API-06 executes the authored `Group` declaration from API-05 (D07-7/R-18):

- A runtime `Group` record carries durable group identity: the authored
  `group_key`, the declared `size` (N members, not pair-only), the member
  enrollments, and a `forming / formed / released` lifecycle. A **formed group
  has exactly its declared N members** (semantic rule `groupSize`).
- A `MatchmakingTicket` enqueues one enrollment for one authored group under a
  **typed `Match` strategy**: `fifo` (default, arrival order), `latency`
  (two-stage: server-RTT pre-filter bound plus P2P probe bound, with
  rejection/re-pooling — the `probing` ticket status), or `custom` (a
  `mug.Matchmaker` subclass recorded by qualified name, versioned with the
  study). A `matched` ticket must reference the formed `group_id`.
- **Persistence across activities**: the durable `group_id` on later
  `Interaction`s reunites the same participants; `on_missing`
  (`wait` / `regroup`, the `OnMissing` vocabulary) declares at execution time
  what a later interaction does when a member is gone, and is only meaningful
  with a `group_id`. Group-scoped treatment assignment (`Scope.GROUP`, API-04)
  is resolved when the group forms and rides with the group.

## Total cast (R-16)

The runtime `Interaction` receives a **total cast**: a non-empty
`cast` map binds every seat key to exactly one actor instance. There are no
partial casts — an unbound or null seat is a contract violation, mirroring the
authoring rule that a declared cast must name every seat.

## P2P mesh membership (RP-1)

`P2PMeshMembership` is the durable coordination record for one P2P game
channel. It binds an interaction, formed group, channel key, positive
`membership_generation`, and canonical lexicographically sorted peer actor IDs.
The topology is always `full-mesh`; pair-only and star topologies are not
alternate modes. A mesh may contain from two peers through the formed
`Group.size`, so the same record covers N-player games rather than assuming a
two-player special case.

The following cross-object rules are semantic obligations:

1. `interaction_id`, `group_id`, and `channel_key` resolve to one active
   `Interaction`, its formed `Group`, and a game `ChannelInstance`.
2. Every `peer_actor_id` resolves through the interaction cast to an eligible
   human actor with read/write game membership. Group members are enrollment
   IDs, so implementations resolve enrollment-to-actor identity rather than
   comparing the two arrays directly.
3. Peer count cannot exceed `Group.size`. Every eligible human game writer is
   present exactly once, and all peers use the same canonical record digest and
   membership generation.
4. A membership change creates a new, higher fenced generation. Evidence from
   different generations cannot be combined to claim all-peer confirmation or
   hash agreement; API-07 owns those frame-finality rules.

## Server-authoritative monitoring (RP-6/RP-10)

Continuous in-play integrity is a **server-authoritative** `MonitoringPolicy`,
not a client-trusted exclusion. The policy is contract state owned by API-06 and
carried by an optional `Interaction.monitoring`; it is evaluated **server-side**
against the typed ping/latency and tab-focus/blur measurements API-09 supplies.
`max_rtt` bounds a ping/latency measurement and `max_hidden` bounds cumulative
tab-focus/blur time; exceeding either accrues an in-play violation. An ordered
**warn-then-exclude ladder** escalates by accumulated violation count — each rung
is a `warn` or `exclude` action at a strictly increasing `at_violations`
threshold (semantic rule `ladderOrder`). An optional researcher `callback`,
declared by **dotted qualified name** (the same convention as a `custom`
Matchmaker ref, never inline code), may run at each step under a **fail-closed
boundary** (RP-10): `on_error` is exactly `fail_closed` (default) or `fail_open`,
where fail-closed treats a callback error/timeout as the safest ladder outcome
rather than trusting the client. This monitoring callback governs **continuous
in-play exclusion only**; flow/screening eligibility is API-04-owned and is not
decided here.

## All-pairs latency probe (RP-7)

A latency-bounded group forms only when **every unordered pair** of the
prospective mesh peers has a probed RTT within `max_p2p_rtt`. `MeshLatencyProbe`
is the formation evidence: it carries `max_p2p_rtt` and the **complete all-pairs
set** of pairwise RTT measurements over the peers, and it binds the same
interaction, group, game channel, peer set, and membership generation as the
`P2PMeshMembership` it gates, at the same `max_p2p_rtt` the latency
`MatchmakingTicket` declares. The semantic rule `allPairsWithinRtt` fails when
any pair exceeds `max_p2p_rtt` or when the recorded pairs are not exactly the
all-pairs set over the peers. API-05 owns the author-facing match-strategy
declaration; API-06 owns this mesh probe evidence.

## Ownership boundary

API-06 owns `Interaction`, `ChannelInstance`, `Membership`,
`P2PMeshMembership`, `MeshLatencyProbe`, `MonitoringPolicy`, `Group`,
`ConnectionLease`, and `MatchmakingTicket`.
API-05 owns the authored `Group`
declaration and seat castings; API-06 owns matchmaking ticket/group state and
interaction lifecycle. Game and conversation execution live in API-07/API-08;
connection transport in API-09; ordering/fencing primitives in the shared
kernel.

## Non-negotiable interaction boundary

1. One interaction is the coordination and evidence boundary; its channel streams
   are causally linked but do not imply one physical global order (D08-1).
2. Channel kinds are the closed typed set above; chat and annotation channels
   use total ordering, game channels use per-producer ordering (D08-2).
3. A channel with no declared membership grants every seat read/write;
   `Membership` only narrows (D08-3).
4. The runtime cast is total (R-16): every seat bound to exactly one actor,
   never a partial cast.
5. A formed group has exactly its declared N members, and its identity is
   durable across the interactions that share it (R-18).
6. A connection lease is ephemeral ownership and is never the sole evidence that a
   visit or interaction exists.
7. A P2P game uses one canonical, generation-fenced `P2PMeshMembership` with
   `full-mesh` topology; confirmation and hash agreement must include every
   peer named by that record (RP-1).
8. In-play exclusion is server-authoritative `MonitoringPolicy` state evaluated
   against API-09 measurements, never client-trusted; the researcher callback is
   fail-closed by default (RP-6/RP-10). A latency-bounded mesh forms only when
   every peer pair is probed within `max_p2p_rtt` (RP-7).

## Current executable evidence

- 15 valid and 19 one-defect invalid examples; 40 API-06 tests including
  kind-bound ordering (chat/annotation total, game per-producer), closed
  `ChannelKind` set, total-cast, group-size, matched-ticket enforcement, a
  four-peer canonical full-mesh membership with topology/order/uniqueness
  rejection cases, a server-authoritative warn-then-exclude `MonitoringPolicy`
  with fail-closed/fail-open callback boundary and `ladderOrder` rejection, and
  an all-pairs `MeshLatencyProbe` with over-bound and missing-pair rejection.

## Acceptance status

`Drafted`, not `Accepted`. See the [review record](review-record.md).
