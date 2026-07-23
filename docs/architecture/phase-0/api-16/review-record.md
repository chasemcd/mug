# API-16 Review Record

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
| Version-0 schemas | Drafted | `replay.schema.json` |
| Golden fixtures and harness | Drafted | 31 fixtures, 38 tests |
| Scenario/parity trace | Partial | Obligations mapped; concrete walkthroughs open |
| Version-1 immutable contract | Not started | Blocked by decisions, reviews, and cross-API ports |

## Checklist

- [x] Exact replay makes no provider/tool calls
- [x] Recorded model/tool outputs are substituted from a decision tape
- [x] Validation detects modified artifacts
- [x] Deterministic verification or declared visual fallback
- [x] Version-0 schemas, fixtures, and semantic harness pass
- [x] RP-2/RP-3/RP-9 decisions recorded: confirmed/verified P2P finality,
      recorded designated-authority bot decisions, and full experienced-stream
      capture alongside canonical truth
- [x] RP-2/RP-3 folded into the 0.3 replay contract: execution-mode binding,
      closed P2P mesh/finality/boundary/authority/tape index, honest aggregate
      finality outcomes, RNG-inclusive codec-neutral snapshot coverage,
      designated-authority bot-action tape, and expected/observed state hashes
- [x] Fold RP-9 full experienced-stream lineage and delivery kinds: replay
      declares a `reproduction_scope` (`canonical-only` vs
      `canonical-and-experienced`) and binds the API-10 evidence bundle
      (`ExperiencedFrame`) with per-frame `delivered`/`speculative`/`corrected`/
      `skipped` lineage; a `corrected` frame resolves to a canonical event in the
      replay's canonical stream
- [ ] Exact command payload/result/view schemas for every command and query
- [ ] Accountable owner and four reviewers assigned
- [ ] Bundle construction, offline completeness, and integrity defined
- [x] Capability levels reflected in schemas: v0 levels (visual/deterministic) declared separately with a conditional determinism declaration (R-8 env hooks, state-hash chain); seekable/forkable are fast-follows and carry no v0 schema structures
- [ ] Safe visual player and counterfactual branching (`run.branch`, seat recast) defined
- [ ] Portable snapshot/trajectory and deterministic state-hash codecs defined
      with API-07 (A07-O01 remains open)
- [ ] NS-01/NS-06/NS-07/NS-09/NS-11 walkthroughs pass
- [ ] Dependent ADRs accepted; four sign-offs recorded; version-1 bytes frozen

## Open decision log

| ID | Decision needed | Proposed default | Blocks |
| --- | --- | --- | --- |
| A16-O01 | Bundle packaging and signing | Offline-complete immutable bundle; container/signature defined in-family (no plugin system in v0 — API-21 retracted; ADR-0015) | ['API-01'] |
| A16-O02 | Counterfactual branching | Settled by D13-7: `run.branch(at_step=..., recast={...})` forks with lineage, may recast a seat, recomputes (may call models), and is new evidence never labeled replay. Scheduling settled 2026-07-18: **fast-follow, not v0**; v0 ships visual + deterministic replay | ['Version 1'] |
| A16-O03 | Visual fallback declaration | When determinism is unavailable, replay declares visual fallback explicitly | ['ADR 0006'] |

## Runtime-parity fold status for revision 0.3

- **RP-2 — folded:** `execution_mode` is mandatory. A P2P replay binds frozen
  mesh membership, API-07 frame finality and minimum-exclusive-end episode
  boundaries, and one disjoint verified/confirmed-only/disputed/partial outcome.
  Deterministic snapshots require env, platform, Python/numpy, and MUG-JS RNG
  coverage plus `snapshot_restore=true`, without choosing bytes or a codec.
- **RP-3 — folded:** the P2P decision-tape branch binds the decision and exact
  result, bot and designated publisher actors, episode/frame, membership and
  authority generations, and action/output digests. Its only replay behavior is
  `apply-recorded-action`. A server-originated provider decision may be injected
  by the designated peer; the peer does not gain provider/tool authority.
- **RP-9 — folded:** a replay manifest declares `reproduction_scope`
  (`canonical-only` or `canonical-and-experienced`) and, when it reproduces the
  experienced stream, binds the API-10 evidence bundle (`ExperiencedFrame` at
  `urn:mug:schema:mug.api-10.evidence:0#/$defs/ExperiencedFrame`) and an
  `experienced_stream_replay` carrying the per-frame `delivered`/`speculative`/
  `corrected`/`skipped` lineage. A `corrected` frame structurally carries its
  `canonical_event_id` + `supersedes_experienced_position`, and semantically must
  resolve to a canonical event present in the replay's canonical stream
  (`experiencedCorrectedLineage`).

A07-O01 remains open. Revision 0.3 fixes logical snapshot coverage and evidence
bindings but deliberately selects no snapshot, trajectory, or state-hash binary
codec.

## Required sign-off

| Review | Reviewer | Decision | Date | Focus |
| --- | --- | --- | --- | --- |
| Domain/scientific validity | Unassigned | Pending | — | Replay capability truthfulness |
| Runtime/distributed systems | Unassigned | Pending | — | Zero-external-call guarantee, determinism |
| Data/replay | Unassigned | Pending | — | Bundle integrity and archival readability |
| Security/privacy | Unassigned | Pending | — | Safe playback, no side-effect re-execution |

## Change log

| Date | Revision | Change |
| --- | --- | --- |
| 2026-07-17 | `0.1` | Opened API-16: replay-manifest, decision-tape, state-hash-check, bundle-validation schemas, zero-external-call and validity rules, 9 fixtures, 12 tests |
| 2026-07-18 | `0.2 (docs)` | Folded user-surface-review decisions (docs only; schema bundle remained `0.1` pending re-draft): separately declared capability levels, `mug.replay`/`run.verify()` surface, counterfactual branching with seat recast, trajectory-slice candidates |
| 2026-07-19 | `0.2` | Re-drafted the schema bundle to the `0.2` docs: `capability_level` enum replaced by separately declared `capability_levels` (`visual`/`deterministic`; no outcome/forkable/branching structures — fast-follows), conditional `determinism` declaration (env `snapshot_restore`/`state_hash` hooks, `state_hash_chain_digest`) required exactly when deterministic replay is declared, `replayCapability` semantic rule; fixtures conformed to shared-kernel `0.2` (`data_handling` = `privacy_labels` only, no retired-kind IDs); 14 fixtures, 17 tests; digests restamped |
| 2026-07-20 | `0.3 input (docs)` | Recorded settled RP-2/RP-3/RP-9 finality, bot-decision, and experienced-stream inputs; A07-O01 binary codec and exact contract/schema/fixture fold remain pending |
| 2026-07-20 | `0.3` | Folded RP-2/RP-3 into the executable bundle: mandatory execution mode; P2P evidence index binding API-06 mesh, API-07 finality/boundaries, API-12 bot authority/results, and the API-16 decision tape; verified/confirmed-only/disputed/partial outcomes; closed env/platform/Python/numpy/MUG-JS snapshot coverage with no codec; exact recorded P2P bot actions; honest expected/observed state-hash checks with a disjoint visual fallback; 27 fixtures, 34 tests. RP-9 and A07-O01 remain pending. |
| 2026-07-20 | `0.3` | Folded RP-9 experienced-stream lineage into the executable bundle: mandatory `reproduction_scope` (`canonical-only`/`canonical-and-experienced`); an `experienced_stream_replay` binding the API-10 evidence bundle (`ExperiencedFrame`, digest `f8d8da4c…`) with per-frame `delivered`/`speculative`/`corrected`/`skipped` lineage; a structural `corrected`-frame canonical-linkage rule and the `experiencedCorrectedLineage` semantic rule tying a corrected frame to a canonical event in the replay's canonical stream; 31 fixtures, 38 tests. Restamped the api-16 bundle self-pins to `73201d6c…` and recomputed the internal decision-tape → replay-manifest chain digest to `5dc8fdf4…`. The foreign api-06 (mesh `5f9103cf…` / interaction bundle `538a17e3…`) and api-12 (authority `17dbeeb8…` / decision-result `d6ab38d6…`) 0.3 cascade digests were already restamped upstream and remain pinned intact. A07-O01 remains pending. |

## Folded decisions (2026-07-18)

Applied from the approved user-surface review (`scratch/phase0-review/DECISIONS.md`):

- **D13-4** — Exact replay (`mug.replay("run.mugrun")`) makes no provider/tool
  calls; recorded outputs are substituted from the decision tape.
- **D13-5** — Capability levels (visual / seekable / deterministic / forkable)
  are declared separately; `run.verify()` performs the deterministic state-hash
  check or a visual fallback is declared honestly.
- **D13-6** — Bundle validation detects tampered/modified artifacts.
- **D13-7** — Counterfactual branching: `run.branch(at_step=..., recast={...})`
  can recast a seat (e.g. human → agent) from a step; a branched run recomputes
  with lineage to its source and is never labeled a replay; trajectory slices
  become preference candidates (API-18).
- **F-3 / ADR-0015** — Typed surface in illustrative code; API-21 packaging
  dependency removed (no plugin system in v0, retracted).
