# Runtime Data-Flow Parity Audit

| Field | Value |
| --- | --- |
| Status | Complete; RP-1..RP-10 settled and folded into the affected families' `0.3` revisions (2026-07-20) |
| Audit date | 2026-07-19 |
| Method | Seven read-only dimension audits of the legacy `mug/` runtime, each mapped mechanism-by-mechanism onto the Phase 0 contracts at revision 0.2 (schema corpus: 446 passing tests) |
| Scope | How data actually moves through current MUG — P2P, server-authoritative, Pyodide, capture, matchmaking, flow, policies — and where the rewrite's contracts achieve parity, leave gaps, or deliberately improve |

The legacy runtime is the **reference implementation** for behavior, not for
architecture. Every dimension report cites `file:line` for each mechanism so
claims are checkable, classifies each against the contracts as **PARITY**
(contract covers it), **GAP** (contract or runtime is missing something), or
**IMPROVE** (contract deliberately replaces a defect), and closes with an
*intricacies register* of load-bearing behaviors a rewrite must preserve — or
knowingly change.

## Dimension reports

1. [P2P transport & authority](01-p2p-transport-authority.md) — GGPO symmetric replicas, binary DataChannel protocol, rollback/hash chain, reconnection regimes
2. [Server-authoritative game execution](02-server-authoritative-loop.md) — tick loop, Surface delta protocol, input paths, reset barrier
3. [Pyodide environment lifecycle](03-pyodide-env-lifecycle.md) — bootstrap, the init-code-string contract R-17 replaces, determinism, failure posture
4. [Data capture & persistence](04-data-capture-persistence.md) — every durable path, every loss window, identity/joinability
5. [Matchmaking, probes, monitoring](05-matchmaking-probes-monitoring.md) — matchmaker algorithms, two-stage RTT probing, group reunion, continuous monitoring
6. [Scene flow & mugGlobals](06-scene-flow-globals.md) — stager, advancement protocol, the complete mugGlobals use-pattern inventory vs the R-13 bridge
7. [Client policies & determinism](07-client-policies-determinism.md) — ONNX/heuristic execution, seeding, decision evidence, what `OnnxPolicy` must carry

## Cross-cutting findings

### A. Authority inversion is the single largest rewrite change

Today the client's buffered batch *is* the scientific record: episode data is
client-buffered, filename-keyed, last-write-wins, keyed by a
participant-supplied `subject_id`, with one ack'd retry loop (multiplayer
episodes) and one append-only file (the match JSONL) as the only delivery
guarantees. API-10/11 flip authority to a server-side append-only accepted
stream with digests and receipts. Everything downstream — dedup, identity,
partial-session handling, export — changes shape with it. (Dimensions 4, 1, 6.)

### B. The experienced stream does not exist yet

The P2P runtime already draws the canonical/experienced distinction the
contracts formalize — speculative buffers, `wasSpeculative` flags, promotion at
confirmation — but discards the experienced record: rollback overwrites
predicted frames and only corrected canonical data exports. The mapping onto
`ExperiencedFrame.delivery_kind` (delivered / speculative / corrected /
skipped) is direct; capturing both streams is new work. (Dimensions 1, 4.)

### C. Evidence is missing at every decision point

No decision-level records exist for automated seats (no observation digest,
model identity, fresh-vs-fallback status); server-mode games record no
per-step evidence at all; episode boundaries are ephemeral broadcasts, not
records; the measured P2P probe RTT is never persisted. The API-10/12/16
evidence surfaces (GameTransition, DecisionRequest/Result, DecisionTape,
EpisodeBoundary, StateHashCheck) are almost entirely net-new implementation.
(Dimensions 1, 2, 5, 7.)

### D. Determinism is real but partial — and the runtime knows things the contracts don't

Multiplayer determinism (shared seed, RNG-inclusive snapshots, float-normalized
hash chain, min-frame episode barrier) genuinely works and supplies the settled
answer to finality/reconciliation item A07-O02. It also fixes what state a
snapshot must cover, but it does **not** choose the portable binary codec tracked
by A07-O01; that remains open. But: single-player is entirely unseeded
(`env_seed` is dead config), LSTM hidden state never resets, the JS RNG is not
part of snapshots, `"random"` policies bypass the seeded stream, and rollback
replays recorded bot actions instead of re-deciding. The runtime's concrete
answers should be folded into API-07 rather than reinvented. (Dimensions 1, 3, 7.)

### E. Trust boundaries are advisory today

Client-asserted identity (URL subject_id + spoofable fallback on episode data),
unvalidated `game_id` on actions, client-authoritative exclusion and waitroom
timeout, crash tracebacks broadcast to participants, TURN credentials cleartext
to the browser, `admin123` default admin password, raw console content and
wholesale mugGlobals dumps in research storage. The contracts' LaunchTicket,
idempotent commands, reserved-key bridge rules, and privacy labels are the
fixes; the audit confirms each has a live counterpart problem. (Dimensions 2, 4, 5, 6.)

### F. Loss windows that `completeness: complete` must eliminate

Partial episodes silently discarded on every abnormal end (metrics-only
export); no `beforeunload` flush anywhere; single-player fire-and-forget
emission after the logger was already reset; the multiplayer 5×2 s retry
ceiling with buffers cleared at first attempt; server restart re-admitting
completed participants and orphaning pending metric aggregation. (Dimension 4.)

### G. A do-not-port defect inventory exists

Each report closes with dead/vestigial/broken code that must not become parity
requirements: dead `pyodide_state_hash`/`pyodide_send_full_state` handlers
calling nonexistent methods, the dormant state-resync layer, unenforced
timeouts (probe, validation, reconnection, waitroom, `matchmaking_max_rtt`),
the reset-barrier deadlock, the shared-scene asset mutation, the probe-state
leak, the `this.socket` completion-code no-op, `arc`/`ellipse` render
dead-ends, and the resume-reshuffle defect.

## Contract verdict rollup

| Contract family | Strongest parity seeds in legacy | Biggest gaps |
| --- | --- | --- |
| API-03 identity | duplicate-tab intent | LaunchTicket net-new; completion-blocking rule needs a deliberate decision; two-live-tabs semantics unspecified |
| API-04 flow | stager ≈ VisitPlan; wrappers ≈ ordering vocabulary | advancement/completion state machine (already flagged as remaining API-04 work); 0.3 callback-spec fold for settled RP-10; migration path for client-side JS randomization |
| API-05/06 casting & groups | matchmaker ABC + two-stage latency strategy; total-cast runtime check | 0.3 must encode RP-1/RP-6/RP-7 (N-peer mesh, all-pairs probes, API-06 `MonitoringPolicy`); REGROUP's effect on `group_id`; post-formation dissolution in the ticket lifecycle |
| API-07 game | per-replica writer; Surface delta protocol; rollback smoothing | GameTransition/EpisodeBoundary evidence net-new; the 0.3 fold must encode RP-1/RP-2 (N-peer mesh, RNG-inclusive snapshot coverage, confirmed/verified frames, min-frame barrier, tie-breakers) while A07-O01 still chooses a binary codec; keyframes; per-seat render |
| API-09 client | input modes, no-input fill, input_delay | held-key streaming (server-auth is edge-triggered today); SeatDelivery vs broadcast; signaling/TURN/DataChannel wire surface entirely uncontracted; 0.3 folds settled `mug.gate` while the general state→env-args path remains open |
| API-10/11 evidence & storage | speculative→canonical discipline; bilateral frame-window equality; match JSONL as outbox baseline | envelopes/receipts/staging all net-new; experienced stream capture; quarantine-on-disagreement and single-uploader-partial unimplemented |
| API-12 scheduler | async ONNX buffer is the germ of the scheduler; fallback semantics match one-to-one | decision identity/staleness/deadline; per-policy `decides_every`; synchronous server-side bots; 0.3 must encode RP-3's settled designated P2P bot authority |
| API-13 providers | `load_policy_fn` escape hatch as the ancestor | everything typed is net-new |
| API-16 replay | hash chain + verified actions ≈ `run.verify()` raw material | one canonical `state_hash`; declared capability levels; 0.3 schema/bundle fold for settled RP-2/RP-3/RP-9 finality, decisions, and experienced lineage |
| API-17 content | scene_body ≈ Content bodies; form scenes ≈ Field set | `vars()`-dump metadata escape hatch; MultipleChoice export mapping; CompletionCodeScene placement; 0.3 `mug.gate` component fold |

## Resolved decisions (RP-1..RP-10, settled 2026-07-20)

These ten decisions were put to the study owner via structured questions and
settled. Each has now been folded to exact bytes into the affected api-*
family's `0.3` revision (RP-1..RP-4 into API-06/07/12/16; RP-5..RP-10 into
API-04/05/06/09/10/16/17), with cross-family schema-digest pins restamped
through the API-06→API-07/12/16 and API-10→API-16 cascades. A07-O01 (portable
binary snapshot codec) remains deliberately open. The runtime-parity registers
remain the implementation reference.

| ID | Decision | Resolution | Affected contracts |
| --- | --- | --- | --- |
| RP-1 | P2P topology bound | **Specify N-peer mesh now.** API-07 defines full mesh for `ExecutionMode.P2P` up to `Group.size` (input exchange with every peer, confirmation = all peers, hash agreement across the mesh). Not constrained to pairs. The hidden-information-incompatibility rule is *not* adopted as a blanket constraint — revisit per-study if a hidden-info P2P design appears. | API-07, API-06 |
| RP-2 | A07-O02 finality & reconciliation; A07-O01 snapshot-codec input | **Adopt the runtime's finality answers as-is.** Snapshots include env state + RNG state (numpy/python/JS); finality = `confirmedFrame` (all inputs received) then `verifiedFrame` (hash-agreed); episode barrier = `min` end frame across the mesh; tie-break = lower-ID-defers; input delay applies symmetrically to all human seats. This closes A07-O02. It constrains snapshot coverage but deliberately leaves A07-O01's portable binary codec open. | API-07, API-16 |
| RP-3 | P2P bot decision authority | **Designated authority.** One peer owns each bot seat's decisions and streams them like a remote human's inputs. Revision-0.3 hardening selects the canonical highest eligible peer actor ID, fixed for the episode; there is no unilateral mid-episode election, and any later assignment requires a new non-overlapping fenced authority generation. Bot actions become recorded `DecisionResult` evidence; rollback replays them exactly; RNG alignment stops being load-bearing. | API-12, API-07, API-16 |
| RP-4 | `on_game_step_code` | **Drop.** Known uses are covered by the env factory (R-17), env hooks (R-8), and the env's own `step`. Per-step logic lives in the env class, versioned with the study. No per-step code-injection surface. | API-07 |
| RP-5 | `custom_inference_fn` | **Drop.** Custom pre/post-processing moves into the typed `OnnxPolicy` spec (declared preprocessing rule + selection mode) or a scripted `Policy` in study code — both versioned/digested. No inline-JS inference escape hatch. | API-05, authoring spec |
| RP-6 | In-play quality monitoring | **Typed contract home.** A `MonitoringPolicy` on the Interaction surface (API-06 owns the policy record; API-09 carries client measurements as typed events): ping/visibility thresholds, warn-then-exclude ladder, researcher callback by qualified name. Enforcement is **server-authoritative**, replacing today's client-trusted exclusion. | API-06, API-09 |
| RP-7 | N>2 probe semantics | **Pairwise mesh, all pairs pass.** A latency-bounded group forms only when every pair's probed RTT is within `max_p2p_rtt`. Consistent with the RP-1 mesh topology. Probes may run sequentially or in parallel; O(N²) but N is small. | API-05, API-06 |
| RP-8 | Bridge/parametrization affordances | **Readiness-gating op adopted.** A typed `mug.gate` op lets trusted page JS block/unblock advancing or joining an interaction (the startButton/advanceButton patterns), replacing the interval hacks. *Not adopted:* the state→env-args resolution path and the read-only participant handle — see open sub-items below. | API-09, API-17 |
| RP-9 | Experienced-stream scope | **Full experienced stream.** Capture both canonical (post-rollback truth) and experienced (frames as rendered, `delivery_kind` delivered/speculative/corrected/skipped). Complete API-10 fidelity. | API-10, API-16 |
| RP-10 | Callback contract home & failure policy | **API-04 flow eligibility, fail-closed.** Screening/eligibility callbacks are flow-level (ADR-0014 flow-based eligibility); continuous exclusion is part of the RP-6 `MonitoringPolicy`. Callbacks run server-side by qualified name; on error/timeout the default is **fail-closed** (exclude/block), with an explicit per-callback opt-in to fail-open. | API-04, API-06 |

### Open sub-items (surfaced by RP-8, still need a path)

- **State → env-args resolution** — the typed replacement for the legacy
  `mugGlobals` → init-code parametrization channel (recorded `StateDocument`
  values / treatment assignments flowing into `EnvFactory` args at activity
  start). RP-8 did not adopt a specific mechanism; R-15 treatment placement
  covers condition values, but the general state→args path is unspecified. A
  study that parametrizes an env from an earlier page's response has no typed
  path yet.
- **Read-only participant handle** — whether page JS gets a read-only
  pseudonymous handle (replacing `subjectName` reads) for labeling/debug. Not
  adopted; revisit if a migrated study needs it.

## How to use this audit

- Phase-1 design docs for each subsystem should start from the corresponding
  dimension report's intricacies register: every entry is either *preserve*,
  *fix deliberately*, or *do-not-port*, and the report says which.
- Contract deltas implied by the audit (e.g., the settled A07-O02 finality
  answer, MatchLatency mesh rules, and full ExperiencedFrame mapping) should be
  folded into the affected api-* families' 0.3 revisions. A07-O01's binary codec
  is still a separate open decision and is not closed by RP-2.
- Legacy data compatibility: the registers name every file-layout and encoding
  contract analysts currently depend on (CSV padding, `_globals.json`, match
  JSONL, metrics JSON, per-episode pseudo-scene IDs). Export-compat mapping is
  API-19 work.
