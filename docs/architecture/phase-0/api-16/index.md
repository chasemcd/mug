# API-16: Replay Capture, Bundles, Validation, Reading, and Branching

| Field | Value |
| --- | --- |
| Status | Draft |
| Contract revision | `0.3` |
| Accountable owner | Unassigned |
| Last updated | 2026-07-20 |
| Consumers | Researchers/auditors, API-07/10/11 (evidence), API-12/13/14 (recorded decisions), API-18 (candidates) |
| Depends on | [Shared kernel 0.1](../shared-kernel/index.md), [API-07 0.1](../api-07/index.md), [API-10 0.1](../api-10/index.md), proposed ADR 0006 |
| Implementation phase | Phase 3A |
| Stability tiers | Archival, wire (bundle) |

## Outcome

API-16 defines replay of a recorded run at **separately declared capability
levels** — visual, seekable, deterministic, forkable — decision tapes that
substitute recorded model/tool outputs, deterministic state-hash verification,
and **counterfactual branching with lineage**. Exact replay performs no model or
tool calls, detects modified artifacts, and either verifies deterministic state
or declares a visual fallback.

**v0 scope (settled 2026-07-18):** visual and deterministic replay ship in v0.
Outcome-level replay and counterfactual branching (`run.branch`) are
fast-follows; their contract shapes here are the committed direction, not v0
deliverables.

Every replay manifest records the source execution mode. A P2P manifest also
contains a closed `P2PReplayEvidence` index that binds the frozen API-06 mesh
membership, API-07 frame-finality and minimum-end-frame boundary records,
API-12 bot-authority and decision-result schemas, and the API-16 decision-tape
artifact. The index records one honest aggregate outcome:

- `verified` means the verified high-water mark does not exceed the confirmed
  high-water mark and the mesh agreed on one state-hash chain;
- `confirmed-only` means complete authoritative inputs exist without mesh-wide
  hash agreement;
- `disputed` preserves a conflicting frame and carries no agreed hash; and
- `partial` preserves missing evidence without presenting it as verification.

The finality and episode-boundary artifacts remain the source records. The
index is an integrity/lookup closure, not a second finality authority.

## Deterministic snapshot declaration

Deterministic replay requires both `snapshot_restore` and `state_hash`. Its
closed logical snapshot coverage is environment state, MUG platform state,
Python `random`, numpy RNG, and MUG's JavaScript RNG state. This states **what
must be restored**, not how those values are encoded. A07-O01 still owns the
portable snapshot/trajectory binary codec; revision 0.3 deliberately adds no
codec field or implied pickle/JSON representation.

## Decision tape

The tape has two closed entry branches:

- `model-output` retains exact model/tool substitution; and
- `p2p-bot-action` binds the decision ID plus immutable result digest, bot and
  designated publisher actors, episode/frame, mesh and authority generations,
  action/output digests, and `replay_behavior=apply-recorded-action`.

The designated peer is the exclusive publisher/injector for that P2P bot seat.
A local deterministic policy may execute there (`authority-local`), but
provider-backed decisions remain server-authoritative under ADR-0005
(`server-scheduler`) and may be injected by the peer.
The P2P peer never gains provider/tool authority. Rollback and exact replay
apply the recorded action and never re-run either path.

`StateHashCheck` likewise has two disjoint branches. Deterministic verification
records expected and observed hashes plus the honest `match`/`mismatch` result;
visual fallback records only its explicit reason and cannot carry a fabricated
deterministic comparison.

```python
run = mug.replay("run.mugrun")     # exact replay: no provider/tool calls; tape substituted
report = run.verify()              # deterministic state-hash check (or declared visual fallback)
fork = run.branch(at_step=1200, recast={"forager-2": other_agent})
```

`run.branch(at_step=..., recast={...})` forks a recorded run at a step and can
**recast a seat** (e.g. human → agent) from that point — a counterfactual run
derived with lineage to its source. Branched runs recompute (and may call
models); they are new evidence, never labeled a replay. Trajectory slices of a
replay are the immutable candidates a preference task consumes (API-18).

## Ownership boundary

API-16 owns `ReplayManifest` (`.mugrun`), `DecisionTape`, `StateHashCheck`, and
`ReplayBundleValidation`, including the P2P replay index and aggregate finality
claim. API-06 owns mesh membership; API-07 owns live frame finality, episode
boundaries, and capture; API-10/11 own evidence/artifact persistence; API-12
owns live bot authority and decisions; provider/tool outputs are API-13/14.

## Non-negotiable replay boundary

1. Exact replay makes no provider calls and repeats no external tool side effects.
2. Recorded model decisions and tool results are substituted from the tape.
3. A validation detects modified artifacts and reports validity accordingly.
4. Replay either verifies deterministic state (`run.verify()`) or declares a
   visual fallback — never a faked match.
5. Capability levels (visual / seekable / deterministic / forkable) are declared
   separately per bundle, never inferred.
6. A branched run is new evidence with lineage to its source, never labeled a
   replay; its trajectory slices are immutable preference candidates (API-18).
7. A P2P bundle cannot call confirmed-only, disputed, partial, or missing peer
   evidence verified; lower-ID live resynchronization never erases disagreement.
8. A P2P bot action is applied from the recorded designated-authority result;
   rollback and replay never recompute it.

## Current executable evidence

- 11 valid and 16 one-defect invalid examples; 34 API-16 tests including
  zero-external-call, validity-consistency, declared-capability enforcement,
  four-peer mesh/tape closure, codec-neutral snapshot coverage, disjoint P2P
  finality outcomes, designated bot-action replay, and honest state-hash
  comparisons. Branching structures remain a fast-follow and are absent from
  the v0 bundle.

## Acceptance status

`Drafted`, not `Accepted`. See the [review record](review-record.md).
