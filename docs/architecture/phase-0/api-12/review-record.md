# API-12 Review Record

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
| Version-0 schemas | Drafted | `scheduler.schema.json` |
| Golden fixtures and harness | Drafted | 23 fixtures, 28 tests |
| Scenario/parity trace | Partial | Obligations mapped; concrete walkthroughs open |
| Version-1 immutable contract | Not started | Blocked by decisions, reviews, and cross-API ports |

## Checklist

- [x] Slow work never blocks a frame, input, or heartbeat
- [x] Decisions accepted only while generation/observation/deadline/window match
- [x] Produced decisions name an action; stale produced decisions are discarded
- [x] Timeout/staleness resolve through explicit fallback
- [x] Version-0 schemas, fixtures, and semantic harness pass
- [x] `0.2` schema/fixture re-draft encoding the folded decisions: typed
      `Fallback` constants (`repeat-last` / `default-action`; `noop` and
      `apply-if-valid` retired — stale decisions are discarded, never
      applied), and the scheduled `ControllerPolicy` homing `decides_every`
      with a fallback declaration mandatory for realtime seats
- [x] RP-3 authority decision recorded: one deterministically selected peer
      owns publication/injection for each P2P bot seat and emits recorded
      `DecisionResult` evidence; rollback replays accepted bot actions rather
      than re-deciding
- [x] RP-3 folded into the 0.3 contract: canonical-highest eligible peer is the
      episode-scoped action publisher/injector; mesh and authority fences,
      request/result claims, producer evidence, and exact-action replay are
      schema-bound and fixture-tested
- [x] ADR-0005 boundary preserved: provider/tool inference remains on the
      server scheduler; the designated P2P peer publishes accepted results and
      may locally compute only scripted/ONNX-style decisions
- [ ] Exact command payload/result/view schemas for every command and query
- [ ] Accountable owner and four reviewers assigned
- [ ] Cancellation propagation and emergency-stop defined
- [ ] Executor boundary and per-interaction budgets defined with API-13/14
- [ ] Action-plan vs single-action cadence defined with API-07/08
- [ ] NS-03 through NS-07 and NS-11 walkthroughs pass
- [ ] Dependent ADRs accepted; four sign-offs recorded; version-1 bytes frozen

## Open decision log

| ID | Decision needed | Proposed default | Blocks |
| --- | --- | --- | --- |
| A12-O01 | Deadline/lease clock authority | Coordinator holds the authoritative deadline; remote work gets a bounded budget and effect-time recheck | ['ADR 0010'] |
| A12-O02 | Fallback on timeout/stale | Settled by D11-3: explicit typed policy (`Fallback.REPEAT_LAST` etc.), mandatory per realtime seat binding; never a silent late apply | ['API-07/08'] |
| A12-O03 | Cancellation and emergency stop | Cancellable in-flight decisions; emergency stop halts activation immediately | ['API-14'] |

## Settled runtime-parity input for revision 0.3

RP-3 is encoded as one deterministic action-publication authority per P2P bot
seat. Revision 0.3 additionally fixes the selection policy to the canonical
highest eligible peer actor ID and prohibits mid-episode failover. The
authority record and every P2P request/result bind the mesh digest/generation,
episode generation, target frame, bot/authority actors, and `LeaseRef` fence.
Rollback applies the recorded action; it does not re-decide. Provider/tool
inference remains server-scheduled under ADR-0005, so the selected peer is the
exclusive mesh publisher/injector rather than necessarily the compute origin.

## Required sign-off

| Review | Reviewer | Decision | Date | Focus |
| --- | --- | --- | --- | --- |
| Domain/scientific validity | Unassigned | Pending | — | Decision admission and acceptance semantics |
| Runtime/distributed systems | Unassigned | Pending | — | Concurrency, latency isolation, cancellation, staleness |
| Data/replay | Unassigned | Pending | — | Decision evidence and replay |
| Security/privacy | Unassigned | Pending | — | Runaway/abuse prevention, budget enforcement |

## Change log

| Date | Revision | Change |
| --- | --- | --- |
| 2026-07-17 | `0.1` | Opened API-12: decision request/result, scheduler-state, fallback-policy schemas, staleness/deadline admission, produced-evidence and stale-rejection rules, 9 fixtures, 13 tests |
| 2026-07-18 | `0.2 (docs)` | Folded user-surface-review decisions (docs only; schema bundle stays `0.1`): never-block guarantee named as north star, mandatory typed fallback for realtime seats, `decides_every` homed on the policy/agent definition |
| 2026-07-19 | `0.2` | Re-drafted the schema bundle to the `0.2` docs: typed `Fallback` enum (`repeat-last`, `default-action`) replacing the free `on_timeout`/`on_stale` branches — `noop` (implicit wait/no-action) and `apply-if-valid` (stale ever applied) retired per D11-3; new `ControllerPolicy` (`mug.api-12.controller-policy`) homing `decides_every` on the immutable policy/agent definition (D11-4) with `fallback` structurally required when `realtime_seat` is true; `DecisionRequest`/`DecisionResult`/`SchedulerState` unchanged; 14 fixtures (6 valid, 8 invalid), 17 tests; bundle digests restamped |
| 2026-07-20 | `0.3 input (docs)` | Recorded settled RP-3 designated P2P bot authority; exact contract/schema/fixture fold remains pending |
| 2026-07-20 | `0.3` | Folded RP-3 into the schema bundle: added episode-scoped `P2PBotAuthority` with canonical-highest selection, API-06 mesh digest/generation binding, `LeaseRef` fencing, and no mid-episode failover; added P2P authority claims to requests/results, explicit server-vs-local decision origin, producer evidence, and `apply-recorded-action` replay; preserved ADR-0005 server-only provider/tool execution; added valid authority/request/result and wrong, stale, missing, and re-decide rejection fixtures; 23 fixtures, 28 tests; bundle digests restamped. |
| 2026-07-20 | `0.3` | Cascade digest restamp: api-06 0.3 (RP-6/RP-7/RP-10) fold moved the interaction bundle + four-peer mesh canonical digests; restamped all transitively-dependent membership/authority/decision digests. No schema or semantic change. |

## Folded decisions (2026-07-18)

Approved user-surface-review decisions applied to this family's docs
(schema bundle re-drafted to match at `0.2`, 2026-07-19):

| ID | Applied as |
| --- | --- |
| D11-2 | Slow decisions are scheduled asynchronously; a slow or failed provider/tool decision never blocks a game frame, human input, or heartbeat — stated as the family's north-star guarantee |
| D11-3 | Stale decisions are discarded, never applied; timeout/staleness resolves via an explicit typed `Fallback` (`Fallback.REPEAT_LAST` etc.), which is mandatory for realtime seats |
| D11-4 | `decides_every` (frame-skip / decision cadence) lives on the immutable policy/agent definition scheduled here, not on input config (with D10-3; human `input_delay` stays in API-09) |
| F-3 | Illustrative Python uses typed constants (`Fallback.*`, `Provider.*`), never magic strings |
