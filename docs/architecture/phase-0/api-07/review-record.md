# API-07 Review Record

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
| Version-0 schemas | Drafted | `game.schema.json` |
| Golden fixtures and harness | Drafted | 38 fixtures, 50 tests |
| Scenario/parity trace | Partial | Obligations mapped; concrete walkthroughs open |
| Version-1 immutable contract | Not started | Blocked by decisions, reviews, and cross-API ports |

## Checklist

- [x] Every runtime emits the same normalized transition (action + state)
- [x] One writer per instance; P2P one writer per replica
- [x] Real-time environment lock never blocked by provider/tool/storage I/O
- [x] Exact mid-episode resume requires compatible snapshot contracts
- [x] Version-0 schemas, fixtures, and semantic harness pass
- [x] All three execution modes committed to v0 with P2P schedule risk recorded; Gym/PettingZoo env contract, imperative `Surface` API, per-seat packets, env-native action spaces documented (docs and 0.2 schema bundle)
- [x] Typed `Surface` draw-command vocabulary (+ `extras=`) and per-seat packet derivation in the schema bundle; `EnvFactory` record (R-17 qualified-name factory, treatment-capable `args`, exact-pin `requires`, browser source bundle, declared hooks) re-drafted into the 0.2 bundle
- [x] RP-1/RP-2/RP-3/RP-4 decisions recorded: N-peer mesh; exact
      confirmed/verified finality and reconciliation; designated per-bot decision
      authority; no `on_game_step_code` injection surface
- [x] Folded RP-1/RP-2/RP-3/RP-4 into the 0.3 exact contract: full-mesh
      `P2PExecutionContract`; environment/platform/Python/numpy/MUG-JS snapshot
      coverage; speculative/confirmed/verified/disputed frame evidence; frozen
      minimum end barrier; episode-fixed highest-eligible-peer bot publisher;
      recorded decision replay; and rejection of `on_game_step_code`
- [ ] Exact command payload/result/view schemas for every command and query
- [ ] Accountable owner and four reviewers assigned
- [ ] Environment/trajectory codecs and deterministic state hashing defined
- [ ] Select the portable snapshot/trajectory binary codec (A07-O01); RP-2
      settled snapshot coverage and finality, not the codec
- [ ] Remaining input validity/cadence integration beyond RP-2/RP-3, with
      API-12
- [ ] Browser-importability verification (R-17): compile resolves the env
  factory's import graph against the client source bundle + `requires` +
  Pyodide's package set for `BROWSER`/`P2P` games; end-to-end in-browser
  bundle→import→`make_env()` as a Phase-1 acceptance fixture.
  **Mechanism validated 2026-07-19** in a real Pyodide runtime (0.26.2 via
  Node): a zip of plain source files (`studies/foraging/envs/foraging.py`,
  present in no wheel) → `pyodide.unpackArchive` → `sys.path` →
  `importlib.import_module("studies.foraging.envs.foraging")` →
  `make_env(n_berries=20)` → `env.reset()` succeeded — custom study code needs
  no PyPI/micropip path; only published deps do. Remaining for Phase 1: the
  same fixture in an actual browser shell + `requires` interplay.
- [ ] NS-01/NS-06/NS-07/NS-09 walkthroughs pass
- [ ] Dependent ADRs accepted; four sign-offs recorded; version-1 bytes frozen

## Open decision log

| ID | Decision needed | Proposed default | Blocks |
| --- | --- | --- | --- |
| A07-O01 | Trajectory/snapshot binary codecs | Separate binary-codec ADR; deterministic and portable | ['API-16'] |
| A07-O03 | Async decision admission | Late/stale decisions cannot cross an episode boundary or block a frame | ['API-12'] |
| A07-O04 | Env instantiation | Settled 2026-07-19 (R-17): `env=` is a factory (module-level callable or class) recorded by qualified name; every runtime (server / Pyodide client / P2P peer / simulate worker) imports the study source and constructs its own instance; recorded `args` kwargs (values may be treatments); `requires=[...]` pinned at publish. Replaces `environment_initialization_code` exec-strings and `packages_to_install` | ['API-01'] |

## Folded runtime-parity decisions in revision 0.3

| Decision | Settled input |
| --- | --- |
| RP-1 | `P2PExecutionContract.topology = full-mesh`; API-07 records the exact API-06 mesh digest/generation and self-contained frozen peer sets on finality and boundary evidence. |
| RP-2 / A07-O02 | Snapshot coverage requires environment/platform/Python/numpy/MUG-JS state; finality progresses speculative → confirmed → verified or disputed; verification requires unanimous full peer hashes; episode ends use zero-based `[0,end_frame_exclusive)` and the minimum end over all frozen peers; lower ID defers only for live repair; human delay is symmetric. |
| RP-3 | The highest eligible peer actor ID is the exclusive episode-fixed publisher; no unilateral switch is legal and a future change requires a new fenced authority generation. Applied `DecisionResult` IDs/digests are recorded and rollback reuses them exactly. Provider/LLM/tool work remains server-authoritative under ADR-0005. |
| RP-4 | `on_game_step_code` is rejected structurally; per-step behavior belongs in the versioned environment class and ordinary `step`/declared hooks. |

A07-O01 remains open: RP-2 and this 0.3 fold fix what a snapshot covers but do
not choose its portable binary encoding. The schema deliberately contains no
snapshot codec or media-type claim.

## Required sign-off

| Review | Reviewer | Decision | Date | Focus |
| --- | --- | --- | --- | --- |
| Domain/scientific validity | Unassigned | Pending | — | Game semantics, authority, episode finalization |
| Runtime/distributed systems | Unassigned | Pending | — | One-writer discipline, rollback, latency isolation |
| Data/replay | Unassigned | Pending | — | Transition/render/state hashing, replay readiness |
| Security/privacy | Unassigned | Pending | — | Action validity and authority |

## Change log

| Date | Revision | Change |
| --- | --- | --- |
| 2026-07-17 | `0.1` | Opened API-07: game-transition, render-packet, episode-boundary, execution-mode schemas, writer/mode rule, normalized transition, 10 fixtures, 14 tests |
| 2026-07-18 | `0.2 (docs)` | Folded approved user-surface-review decisions (docs only; schema bundle stays 0.1): three execution modes in v0 (P2P risk flagged), Gym/PettingZoo env contract, imperative `Surface` API preserved, per-seat render packets, env-native action spaces |
| 2026-07-19 | `0.2` | Re-drafted the schema bundle to the 0.2 docs: `EnvFactory` record (R-17 qualified-name factory, treatment-capable `args`, exact-pin `requires`, browser source bundle mandated for `browser`/`p2p`, declared hooks), `ExecutionMode` renamed `server`/`browser`/`p2p` with P2P-determinism semantic rule, per-seat `RenderPacket` (`seat_key`) with typed `Surface` commands + explicit `extras=`; 19 fixtures, 25 tests |
| 2026-07-20 | `0.3 input (docs)` | Recorded settled RP-1/RP-2/RP-3/RP-4 topology, finality, bot-authority, and hook-removal decisions; A07-O01 binary codec and the exact contract/schema/fixture fold remain pending |
| 2026-07-20 | `0.3` | Folded RP-1..RP-4 into exact bytes: N-peer full mesh; mesh-digest/generation fencing; four-state `P2PFrameFinality` with complete action/hash set semantics; exclusive minimum episode barrier; RNG-inclusive snapshot coverage without selecting a codec; highest-eligible, episode-fixed bot publisher with exact `DecisionResult` linkage and recorded-decision rollback; P2P factory snapshot/hash hooks; no per-step injection. Bundle digest `2c41f0fe…`; 38 fixtures, 50 tests. |
| 2026-07-20 | `0.3` | Cascade digest restamp: api-06 0.3 (RP-6/RP-7/RP-10) fold moved the interaction bundle + four-peer mesh canonical digests; restamped all transitively-dependent membership/authority/decision digests. No schema or semantic change. |

## Folded decisions (2026-07-18)

Approved user-surface-review decisions applied to the API-07 docs (schema
bundle unchanged at 0.1; re-draft pending):

- **D08-4** — execution mode is a typed per-game-channel choice (`ExecutionMode.BROWSER`/`SERVER`/`P2P`); identical data shape across modes; all three ship in v0, with the P2P schedule risk recorded in the index.
- **D08-7** — the game env is a Gym/PettingZoo-style env class in the study repo, versioned with the study (ADR-0013); MUG drives it and normalizes each step into the transition contract.
- **D09-1** — rendering stays imperative per-frame Python (`render(state, surface, seat=None)`), separated from the headless env; Python-in-Pyodide default, optional JS/HTML custom renderer.
- **D09-2** — the full `Surface` primitive set and semantics preserved (delta compression, object identity/tweening, depth, alpha, fills, coords, resolution independence); typed params plus explicit `extras=` (F-3), no silent `**kwargs`.
- **D09-3** — client-side Pyodide execution is first-class; three transports carry one draw format; Worker ticks survive tab backgrounding.
- **D09-4** — per-seat rendering is a v0 goal: platform-derived per-seat `RenderPacket` (hidden state never sent), HTML overlay/DOM HUD preserved.
- **D09-5** — assets bundled and versioned with the study, content-addressed.
- **D09-6** — integrity is mode-specific and stated honestly (server-auth thin client vs Pyodide/P2P determinism + reconciliation).
- **D09-7** — seat ↔ env agent-id binding is explicit and recorded (owned in API-05; consumed here for input routing and per-seat packets).
- **D09-8** — non-Surface render paths (Unity/WebGL) remain a supported alternate mode.
- **D10-1** — actions map to the env's own action space (env-provided `IntEnum` or raw `Discrete`/`Box`); MUG never invents action names.
