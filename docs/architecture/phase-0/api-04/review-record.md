# API-04 Review Record

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
| Version-0 schemas | Drafted | `visit-plan.schema.json` |
| Golden fixtures and harness | Drafted | 23 fixtures, 31 tests |
| Scenario/parity trace | Partial | Obligations mapped; concrete walkthroughs open |
| Version-1 immutable contract | Not started | Blocked by decisions, reviews, and cross-API ports |

## Checklist

- [x] Visit pins one immutable study version and one deployment revision
- [x] Visit plan is materialized/committed before participation; plan_digest closes over it
- [x] Randomization is recorded once with a seed commitment
- [x] Assignment (intent) and exposure (delivery) are separate records
- [x] Namespaced state documents are optimistically versioned
- [x] Version-0 schemas, fixtures, and semantic harness pass
- [x] Declarative treatment surface documented and encoded: typed `Assign.*`/`Order.*`/`Scope.*`/`Unit.*`, inline point-of-effect treatments with shared refs and `Design` crossing (R-15, superseding R-14)
- [x] `Scope.GROUP` assignment and durable per-cell allocation state in the schema bundle
- [x] RP-10 policy decision recorded: screening/eligibility callbacks are
      flow-level, continuous exclusion belongs to API-06 monitoring, and callback
      failure is fail-closed unless the author explicitly opts into fail-open
- [x] Folded RP-10 into the 0.3 exact contract: an `EligibilityCallback` record
      (server-side qualified-name callback addressed at a flow node, plan-level
      `VisitPlan.eligibility` attachment) with the shared `on_error`
      `fail_closed`/`fail_open` vocabulary defaulting to `fail_closed`; typed
      qualified-name and enum validation with bad-enum and malformed-callback
      one-defect fixtures; flow-level screening documented as distinct from API-06
      continuous in-play monitoring exclusion
- [ ] Exact command payload/result/view schemas for every command and query
- [ ] Accountable owner and four reviewers assigned
- [ ] Flow materialization from API-01 (sequence/branch/repeat/randomized-select) defined
- [ ] Activity-advancement, completion, and abandonment state machines defined
- [ ] Recovery fault injection at each activity boundary restores exact plan/treatment
- [ ] API-06 interaction-start and API-09 delivery compatibility reviewed
- [ ] NS-01, NS-08, and NS-10 walkthroughs pass. **One NS-08 clause is now
      closed by W10**: "only state namespaces declared for the second part are
      carried forward". A `StateDocument` per visit and namespace is written
      through `mug/visits/state.py` under a declared read/write policy, and a
      return link that finds the part finished and a different study version
      served opens a new visit under the same enrollment carrying only the
      namespaces that version declares. The other clauses (restart never rebuilds
      the plan, stable receipts, assignment and exposure distinct, blinded
      external identity) are **not** claimed here.
- [ ] Dependent ADRs accepted; four sign-offs recorded; version-1 bytes frozen

## Open decision log

| ID | Decision needed | Proposed default | Blocks |
| --- | --- | --- | --- |
| A04-O01 | Flow-to-plan materialization and re-entry | Compile-time flow drives a one-time materialization; re-entry reloads the committed plan | ['API-01 review'] |
| A04-O02 | Randomization seed custody | Server-held seed with a published commitment; outcome immutable; ungated (self-hosted; ADR-0015) | ['Version 1'] |
| A04-O03 | Activity advancement durability boundary | Advance only after a durable commit receipt (shared-kernel Unit of Work) | ['API-10/API-11'] |
| A04-O04 | Treatment amendment across a longitudinal flow | A treatment change requires a new study version; exposure records remain immutable; multi-part participation is flow-based (ADR-0014) | ['Version 1'] |
| A04-O05 | `Scope.GROUP` balancing unit | Settled 2026-07-18: typed author knob `Assign.balanced(unit=Unit.GROUPS \| Unit.PARTICIPANTS)`, default `GROUPS` | — |
| A04-O06 | Treatment↔activity linkage | Settled 2026-07-19, revised same day (R-15, supersedes the interim R-14 `applies=` shape): a `Treatment` is declared **inline at its point of effect** (cast slot / spec field), `levels={label: value}`; multi-effect reuses the same object with `t.map({...})` per site; joint factorial balance via optional `study.set_design(Design(cross=[...]))` (independent assignment otherwise); scope inferred where placement forces it; `check()` prints the effect map | ['API-05'] |

## Settled runtime-parity input for revision 0.3

RP-10 settles the ownership and failure-policy question: API-04 owns
flow-level screening/eligibility callbacks; API-06 owns continuous in-play
exclusion through `MonitoringPolicy`; callbacks are server-side qualified-name
references and fail closed on error/timeout unless the author explicitly opts
into fail-open. **Folded into the exact 0.3 bundle** as the `EligibilityCallback`
record and `VisitPlan.eligibility` attachment (see below); the remaining
callback lifecycle/evidence and timeout-mechanics detail beyond the on-error
policy stays open for later revisions.

## Folded runtime-parity decisions in revision 0.3

| Decision | Settled input |
| --- | --- |
| RP-10 | Screening/eligibility callbacks are flow-level (ADR-0014 flow-based eligibility), owned by API-04, and encoded as the `EligibilityCallback` record: a server-side callback addressed by qualified name (the corpus `module.path:attribute` convention) evaluated at a `flow_node_id`, attached plan-level via optional `VisitPlan.eligibility`. On callback error/timeout the default is `on_error = fail_closed` (exclude/block); `fail_open` is an explicit per-callback opt-in. The `on_error` enum (`fail_closed`/`fail_open`, default `fail_closed`) matches the identical vocabulary API-06 encodes for its monitoring callback. Continuous in-play exclusion remains a separate concern owned by API-06 `MonitoringPolicy` and is referenced by prose only, not pinned here. |

## Required sign-off

| Review | Reviewer | Decision | Date | Focus |
| --- | --- | --- | --- | --- |
| Domain/scientific validity | Unassigned | Pending | — | Plan/treatment/exposure semantics and recovery |
| Runtime/distributed systems | Unassigned | Pending | — | Advancement concurrency, idempotency, crash recovery |
| Data/replay | Unassigned | Pending | — | Schemas, plan digest, archival readability |
| Security/privacy | Unassigned | Pending | — | Blinding, exposure integrity, state isolation |

## Change log

| Date | Revision | Change |
| --- | --- | --- |
| 2026-07-17 | `0.1` | Opened API-04: visit/plan/assignment/exposure/state schemas, version+deployment pinning, plan-digest closure, assignment/exposure separation, 10 fixtures, 15 tests |
| 2026-07-18 | `0.2 (docs)` | Folded approved user-surface-review decisions (docs only; schema bundle stays 0.1): declarative treatment surface, `Scope.GROUP`, lifetime balance, wave references removed (ADR-0014) |
| 2026-07-19 | `0.2` | Schema bundle re-drafted to the 0.2 docs: inline point-of-effect treatments with shared refs and `Design` crossing (R-15), typed `Assign`/`Scope`/`Unit`/`Order` vocabulary with explicit balanced `unit` knob (A04-O05), group-scoped `TreatmentAssignment`, durable `AllocationState`, `wave_key` removed (ADR-0014); 19 fixtures, 26 tests |
| 2026-07-20 | `0.3 input (docs)` | Recorded settled RP-10 callback ownership/failure policy; exact contract/schema/fixture fold remains pending |
| 2026-07-20 | `0.3` | Folded RP-10 into exact bytes: `EligibilityCallback` flow-level record (server-side qualified-name callback at a `flow_node_id`, plan-level `VisitPlan.eligibility` attachment) with the shared `on_error` `fail_closed`/`fail_open` enum defaulting to `fail_closed`; qualified-name and enum structural validation with default-fail-closed and explicit-fail-open valid fixtures plus bad-enum and malformed-callback invalid fixtures; flow screening documented distinct from API-06 continuous monitoring exclusion. Bundle digest `5985bd0d…`; 23 fixtures, 31 tests. |
| 2026-07-30 | `0.3` | **`SeatKey` split from `AuthoringKey`.** A seat key may now start with a digit (`^[a-z0-9][a-z0-9]*(?:[-_.][a-z0-9]+)*$`). A seat is named by the environment's own agent, and both standard environment APIs number their agents freely -- a PettingZoo environment answers `possible_agents == [0, 1]`. The contract already accepted `0` as an `env_agent_id` and refused it as a `seat_key`, which was an oversight: a study seating a numbering environment composed, mounted, and stepped, then was refused on the **first drawn frame**. Bundle digest restamped. |

## Folded decisions (2026-07-18)

Approved user-surface-review decisions applied to the API-04 docs (schema
bundle unchanged at 0.1; re-draft pending):

- **D06-1** — authors declare the design; MUG samples, balances, records. No hand-coded randomization assigns conditions.
- **D06-2** — assignment policies are a closed, typed set (`Assign.random/balanced/blocked/stratified`); no plugin allocator in v0. Balance holds across the whole study-version lifetime via durable per-cell allocation counts.
- **D06-3** — between- and within-subjects both first-class; within-subject order (`Order.*`) recorded like any assignment.
- **D06-4** — conditions referenced via typed effect declarations (`applies=[Cast/Param]` per R-14, superseding the earlier `design.level(...)` point-of-use handles); the full design space is known at compile time.
- **D06-5** — assignment (intent) and exposure (delivery) both reach the author's data.
- **D06-6** — covariate-dependent assignment (`Assign.stratified`) happens at a defined flow point, recorded once, never re-rolled.
- **D06-7** — assignment scope is typed: `Scope.PARTICIPANT` (default) or `Scope.GROUP` (a matched group shares one assignment, made when the group forms). Balancing unit settled 2026-07-18 as the typed `unit=` knob (A04-O05).
- **D05-1** — visit plan and all randomization fixed and committed up front; recovery never re-rolls.
- **D05-2** — assignment/exposure split kept exactly as drafted.
- **F-2 / ADR-0014** — no wave gating; wave references replaced with flow-based multi-part participation.
