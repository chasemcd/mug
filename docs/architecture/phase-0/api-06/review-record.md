# API-06 Review Record

| Field | Value |
| --- | --- |
| Status | Draft |
| Contract revision | `0.3` |
| Review opened | 2026-07-17 |
| Accountable owner | Unassigned |
| Target accepted version | `1` |

## Deliverable status

| Deliverable | Status | Evidence |
| --- | --- | --- |
| Ownership, lifecycles, and boundary | Drafted | [Index](index.md) |
| Version-0 schemas | Drafted | `interaction.schema.json` |
| Golden fixtures and harness | Drafted | 34 fixtures, 40 tests |
| Scenario/parity trace | Partial | Obligations mapped; concrete walkthroughs open |
| Version-1 immutable contract | Not started | Blocked by decisions, reviews, and cross-API ports |

## Checklist

- [x] Interaction is the single coordination/evidence boundary
- [x] Channel streams are causally linked but independently ordered
- [x] Chat channels enforce total ordering
- [x] Connection lease is ephemeral and non-authoritative
- [x] Membership declares per-channel visibility and write capability
- [x] Version-0 schemas, fixtures, and semantic harness pass
- [x] Closed typed `ChannelKind` set (game/chat/annotation) and all-seats membership default documented (docs and schema)
- [x] `ChannelKind.ANNOTATION` and the all-seats default in the schema bundle
- [x] RP-1 folded into the 0.3 contract as a canonical, generation-fenced
      `P2PMeshMembership`: full N-peer topology up to `Group.size`, with
      all-peer confirmation/hash consumers bound to one membership digest
- [x] RP-6/RP-7/RP-10 decisions recorded: all-pairs latency probing,
      server-authoritative `MonitoringPolicy`, and separation of flow
      eligibility from continuous in-play exclusion
- [x] Fold RP-6/RP-7/RP-10 into exact schemas, lifecycle/semantic rules, and
      fixtures
- [ ] Exact command payload/result/view schemas for every command and query
- [ ] Accountable owner and four reviewers assigned
- [ ] Remaining matchmaking lifecycle details beyond the settled mesh/probe
      rules: group persistence, disconnect, post-formation dissolution, and
      substitution semantics. **Partly settled by W8** for a formed game group:
      a seat is given up only by a connection that finished the run, so a
      participant who reloads is given the seat they already hold rather than
      put in a new group; a connection that has gone stops being pushed to while
      its seat keeps stepping the default action; and the interaction is
      finalized once, by the connection that finished. **Group persistence
      across processes and substitution are still open.**
- [ ] Connection-lease fencing and reconnection defined with the shared kernel
- [ ] Cross-channel causation and modality anchors defined with API-07/08
- [ ] NS-04 through NS-09 walkthroughs pass
- [ ] Dependent ADRs accepted; four sign-offs recorded; version-1 bytes frozen

## Open decision log

| ID | Decision needed | Proposed default | Blocks |
| --- | --- | --- | --- |
| A06-O01 | Matchmaking group persistence and substitution | Persist groups across reconnect; substitution mints a new fenced membership | ['API-09 review'] |
| A06-O02 | Disconnect and compensation policy | Lease expiry frees a seat under an authored grace policy; evidence preserved; ungated (self-hosted; ADR-0015) | ['API-09 review'] |
| A06-O03 | Cross-channel ordering anchors | Independent per-channel sequences related by causation, never a global clock | ['ADR 0010'] |

## Settled runtime-parity input for revision 0.3

| Decision | Settled input |
| --- | --- |
| RP-1 | `ExecutionMode.P2P` is a full N-peer mesh up to `Group.size`; confirmation and hash agreement include every peer. |
| RP-6 | API-06 owns a server-authoritative `MonitoringPolicy`; API-09 supplies typed ping/visibility measurements, and enforcement follows a warn-then-exclude ladder with an optional qualified-name researcher callback. |
| RP-7 | A latency-bounded group forms only when every pair passes `max_p2p_rtt`. |
| RP-10 | API-04 owns flow eligibility; continuous in-play exclusion is the RP-6 monitoring concern here. Callback failure defaults fail-closed with explicit fail-open opt-in. |

These are no longer open policy questions. Revision 0.3 now folds all four into
exact bytes: RP-1 (`P2PMeshMembership`) and RP-6/RP-7/RP-10 (`MonitoringPolicy`
with its fail-closed callback boundary, and the all-pairs `MeshLatencyProbe`).

## Folded runtime-parity decisions in revision 0.3

| Decision | Settled input |
| --- | --- |
| RP-6 | API-06 owns a server-authoritative `MonitoringPolicy` (inside the `mug.api-06.interaction` bundle, referenced by an optional `Interaction.monitoring`): typed `max_rtt` ping/latency and `max_hidden` tab-focus/blur thresholds, an ordered warn-then-exclude `ladder` (closed `warn`/`exclude` actions, strictly increasing `at_violations` enforced by the `ladderOrder` semantic rule), and an optional researcher `callback` by dotted qualified name. Enforcement is `server-authoritative` contract state evaluated against the typed measurements API-09 supplies, replacing client-trusted exclusion. |
| RP-7 | The pairwise-probe formation gate is encoded as `MeshLatencyProbe` (`mug.api-06.mesh-latency-probe`): it carries `max_p2p_rtt` and the complete all-pairs set of probed RTTs over the mesh peers, coherent with `P2PMeshMembership` and the latency `MatchmakingTicket`. The `allPairsWithinRtt` semantic rule fails when any pair exceeds `max_p2p_rtt` or when the pair set is not exactly the all-pairs set over the peers. API-05 owns the author-facing match-strategy declaration; API-06 owns this probe evidence. |
| RP-10 | The monitoring `callback` has a fail-closed boundary: `on_error` is exactly `["fail_closed","fail_open"]`, default `"fail_closed"`. This callback governs continuous in-play exclusion only; flow/screening eligibility remains API-04-owned and is not decided here. |

## Required sign-off

| Review | Reviewer | Decision | Date | Focus |
| --- | --- | --- | --- | --- |
| Domain/scientific validity | Unassigned | Pending | — | Interaction/channel/membership semantics |
| Runtime/distributed systems | Unassigned | Pending | — | Lease fencing, reconnection, matchmaking concurrency |
| Data/replay | Unassigned | Pending | — | Stream identity, ordering, archival readability |
| Security/privacy | Unassigned | Pending | — | Channel membership, write validity, and visibility |

## Change log

| Date | Revision | Change |
| --- | --- | --- |
| 2026-07-17 | `0.1` | Opened API-06: interaction/channel/membership/lease/matchmaking schemas, chat total-ordering rule, lease fencing, 11 fixtures, 15 tests |
| 2026-07-18 | `0.2 (docs)` | Folded approved user-surface-review decisions (docs only; schema bundle stays 0.1): closed typed `ChannelKind` set, all-seats membership default |
| 2026-07-19 | `0.2` | Re-drafted the schema bundle to the 0.2 docs: closed `ChannelKind` set (game/chat/annotation, `system` removed) with kind-bound ordering, `Membership` access vocabulary (`read_write`/`read_only`/`none`, D08-3), R-16 total cast on `Interaction`, R-18 group execution (`Group` record with durable identity and N-size formation rule, group-scoped `MatchmakingTicket` with typed `Match` strategies fifo/latency/custom, `on_missing` wait/regroup persistence semantics); conformed to shared-kernel 0.2; 21 fixtures, 24 tests; digests restamped |
| 2026-07-20 | `0.3 input (docs)` | Recorded settled RP-1/RP-6/RP-7/RP-10 mesh, monitoring, probing, and callback-ownership decisions; exact contract/schema/fixture fold remains pending |
| 2026-07-20 | `0.3` | Folded RP-1 into the schema bundle: added `P2PMeshMembership` (`mug.api-06.p2p-mesh-membership`) binding interaction/group/game channel, canonical unique 2–64 peer actor IDs, `full-mesh` topology, positive membership generation, and a version stamp; documented cross-object actor/enrollment resolution and generation fencing; added a valid four-peer mesh plus bad-topology, noncanonical-order, and duplicate-peer fixtures; 25 fixtures, 29 tests; bundle digests restamped. RP-6/RP-7/RP-10 remain pending. |
| 2026-07-20 | `0.3` | Folded RP-6/RP-7/RP-10 into the same `mug.api-06.interaction` bundle: added a server-authoritative `MonitoringPolicy` (`max_rtt`/`max_hidden` thresholds, ordered warn-then-exclude `ladder` with the `ladderOrder` semantic rule, dotted qualified-name researcher `callback` with a fail-closed `on_error` boundary, default `fail_closed`) referenced by a new optional `Interaction.monitoring`; and the all-pairs `MeshLatencyProbe` (`mug.api-06.mesh-latency-probe`) carrying `max_p2p_rtt` and the complete pairwise-RTT set, gated by the `allPairsWithinRtt` semantic rule and coherent with `P2PMeshMembership` and the latency `MatchmakingTicket`. Added four valid (warn-then-exclude policy, fail-open callback, monitored interaction, all-pairs probe) and five invalid (ladder out of order, bad `on_error`, non-qualified callback name, pair over `max_p2p_rtt`, missing pair) fixtures; 34 fixtures, 40 tests; bundle digest restamped to `538a17e3…`. |

## What W18 settles, and what it does not (2026-07-27)

W18 (peer-to-peer across processes) is a **runtime** change. It adds no record, no
field, and no fixture, and the bundle digest is unchanged. It is noted here because
it changes what the family's runtime can do, and a reviewer should read it against
the matchmaking and lease clauses rather than be surprised by it.

**What it settles.**

- **R-18 group formation now spans a deployment.** `MatchmakingTicket` and `Group`
  were formed from the tickets one process held, so a deployment of several replicas
  had several waiting rooms and formed no group across them.
  `mug/interactions/rendezvous.py` puts the waiting list in the shared store, and the
  store's own revision check makes a claim exactly-once: two processes claiming at
  the same moment means one of them reads again and finds the tickets gone. The
  formation itself is unchanged -- the claimed enrollments are cast through the same
  `MeshFormationService`, so the seats, the actors, the frozen mesh, and the leases
  are what they always were.
- **`P2PMeshMembership` is reachable from more than one process.** The room a mesh
  forms into now names the process that runs it, so a process holding a member's
  socket knows where to send what that member did.

**What it does not claim.**

- **Lease fencing is unchanged and still per process.** `LeaseBook` holds the current
  generation for the formation service that issued it, which now means the process
  that claimed the group. That is sound while one process owns a room, and it is why
  a room's owner is recorded rather than inferred. A lease is not fenced across a
  **change** of owner, because ownership does not change.
- **A room whose owner dies is not taken over.** Its members are aborted and
  re-pooled, exactly as when a peer disconnects. Taking one over would need the room
  core's live state in the store, and it is not there.
- **Nothing about monitoring (RP-6/RP-10) is distributed.** A monitoring callback and
  its warn-then-exclude ladder run in the process that owns the room, on that room's
  evidence, which is all the evidence there is.
- **No sign-off is claimed.** The four reviews above are still Pending, and the
  runtime/distributed-systems focus line ("lease fencing, reconnection, matchmaking
  concurrency") now has more to read, not less.

## Folded decisions (2026-07-18)

Approved user-surface-review decisions applied to the API-06 docs and folded
into the schema bundle at revision 0.2:

- **D08-1** — a game-with-chat is one `Interaction` with multiple channels, causally linked but independently ordered; one coordination + evidence boundary, never two sessions.
- **D08-2** — channel kinds are a typed, closed set (`ChannelKind.GAME` / `ChannelKind.CHAT` / `ChannelKind.ANNOTATION`), each carrying its own ordering guarantee; the author picks the kind, not the ordering mechanics.
- **D08-3** — membership defaults to all seats read/write; explicit `Membership` (`READ_WRITE`/`READ_ONLY`/`NONE`) is opt-out narrowing for asymmetry only.
