# API-04: Visit Plans, Flow, Treatment, Exposure, and State

| Field | Value |
| --- | --- |
| Status | Draft |
| Contract revision | `0.3` |
| Accountable owner | Unassigned |
| Last updated | 2026-07-20 |
| Consumers | API-06 (interaction start, group assignment), API-09 (delivery), API-10 (evidence), API-16 (replay) |
| Depends on | [Shared kernel 0.1](../shared-kernel/index.md), [API-01 0.1](../api-01/index.md), [API-02 0.1](../api-02/index.md), [API-03 0.1](../api-03/index.md), proposed ADRs 0003, 0013, 0014 |
| Implementation phase | Phase 2 |
| Stability tiers | Application command/query, archival |

## Outcome

API-04 is the seam where an immutable study version and an immutable deployment
revision meet a participant. It materializes and persists a `VisitPlan` before
participation begins, records randomization once, and keeps **assignment**
(intended treatment) separate from **exposure** (delivered treatment) so that
recovery restores an exact plan without reshuffling and analysis can tell intent
from delivery (D05-1, D05-2).

## Declarative treatment surface

Authors declare the design; MUG samples, balances, and records (D06-1). No
hand-coded `random.choice()` assigns a condition. Illustrative authoring shape
(compiled by API-01 into the specs API-04 executes; F-3 typed constants
throughout):

```python
from mug import Treatment, Design, Assign, Scope, Unit

# A Treatment is declared INLINE at its point of effect (settled 2026-07-19,
# R-15) — the manipulation sits exactly where it takes effect:
game = activities.Interaction(
    key="foraging",
    seats=["forager-1", "forager-2"],
    cast={"forager-2": Treatment(                            # seat occupant per level
        key="partner",
        levels={"human": Actor.human(), "ai": Actor.agent(ai_partner)},
        assign=Assign.balanced(unit=Unit.GROUPS))},          # scope=GROUP inferred (shared seat)
    channels=[...],
)

# Multi-effect: reuse the same Treatment object at each site (t.map({...}) for
# per-site values). True factorial: declare only the statistical crossing:
difficulty = Treatment(key="difficulty", levels=["easy", "hard"], assign=Assign.balanced())
study.set_design(Design(cross=[difficulty, partner], assign=Assign.balanced()))
# without set_design, treatments assign independently (balanced marginally)
```

| Declaration | Contract behavior |
| --- | --- |
| `Treatment(factors=…)` / `conditions=…` | The full design space (all cells) is known at compile time (D06-4); export can enumerate cells with zero participants; a typo'd condition is a compile error. |
| `assign=Assign.random() / .balanced() / .blocked() / .stratified(by=…)` | Closed, typed policy set (D06-2, F-3). No arbitrary allocator code in v0. |
| `within=True, order=Order.*` | Within-subjects order is an assignment like any other, recorded (D06-3). |
| `Assign.stratified(by=activity.field(…))` | Assignment defers to the flow point after its input, then is recorded once, immutably — never re-rolled (D06-6). |
| `scope=Scope.PARTICIPANT` (default) / `Scope.GROUP` | Typed assignment scope (D06-7). A `Scope.GROUP` treatment assigns one condition to a whole matched group when the group forms (with API-06); every member shares the assignment, and the shared outcome is recorded once per group. |
| Inline placement (cast slot / spec field) + `t.map({...})` | The treatment's **effects** are its placements (R-15). Resolved from the recorded assignment at group formation (cast) / occurrence start (spec param); the author never reads a raw random value. Scope is inferred where placement forces it (shared seat ⇒ `GROUP`); `check()` prints the effect map; a `Design(cross=…)` naming an unplaced treatment is a compile error. |

**Balance window (D06-2/settled):** `Assign.balanced()` balances across the
whole study-version lifetime — allocation counts are **durable per-cell state**
that survives process restart, `mug stop`, and redeploy. Balance is never
per-process memory. **Balancing unit (settled 2026-07-18, A04-O05):** for
`Scope.GROUP` with varying group sizes it is a typed author knob —
`Assign.balanced(unit=Unit.GROUPS)` (default) balances group counts;
`Assign.balanced(unit=Unit.PARTICIPANTS)` balances person counts (F-3).

## Ownership boundary

API-04 owns `Visit`, `VisitPlan`, `PlannedActivity`/`ActivityOccurrence`,
`RandomizationOutcome`, `TreatmentAssignment`, `TreatmentExposure`, durable
per-cell allocation state, namespaced `StateDocument`s, and flow-level
`EligibilityCallback`s. It composes API-01 flow/definitions, API-02 deployment
binding, and API-03 enrollment; eligibility and multi-part participation are
flow-based (ADR-0014) — there is no wave gating. It does not own their schemas,
nor interaction execution (API-06+), nor evidence storage (API-10/11).

## Flow-level eligibility/screening callbacks (RP-10)

Eligibility is enforced at the flow, not the wave (ADR-0014). An
`EligibilityCallback` names a server-side study-repo callable by qualified name
(the corpus `module.path:attribute` convention, as with the API-07 env
factory), evaluated at a `flow_node_id` to admit or exclude a participant before
or at a flow step; the plan attaches them plan-level through the optional
`VisitPlan.eligibility` array. On callback error or timeout the default is
**fail-closed** (`on_error = "fail_closed"`: exclude/block); an author opts into
**fail-open** (`on_error = "fail_open"`) explicitly, per callback. This
`on_error` vocabulary is shared verbatim with API-06's monitoring callback.

This flow-level screening is deliberately distinct from **continuous in-play
exclusion**, which removes an already-admitted participant during an interaction
and is owned by API-06's `MonitoringPolicy` (referenced here by prose only, not
pinned). API-04 decides who is admitted to a step; API-06 decides who is dropped
mid-interaction.

## Non-negotiable visit boundary

1. A `Visit` pins exactly one `StudyVersionRef` and one `DeploymentRevisionRef`;
   the plan pins the same study version (NS-08).
2. The `VisitPlan` is materialized and committed before participation; recovery
   loads it and never re-samples randomization (D05-1). `plan_digest` closes
   over the materialized activities and randomization outcomes.
3. `RandomizationOutcome` is recorded once, immutably, with a seed commitment.
   Covariate-dependent assignment (D06-6) is recorded once at its defined flow
   point — "recorded once" is the invariant, not "all at t=0".
4. `TreatmentAssignment` (intent) and `TreatmentExposure` (delivery) are separate
   records (D05-2, D06-5); assignment never references an occurrence, exposure
   always does.
5. A `Scope.GROUP` assignment is made when the group forms and is shared by all
   members; recovery of any member reloads the same group outcome.
6. Balanced allocation counts are durable across the study-version lifetime.
7. `StateDocument`s are namespaced and optimistically versioned per visit.

## Current executable evidence

- 11 valid examples (visit, plan, inline-cast treatment plan, shared/crossed
  treatment plan, participant- and group-scoped assignments, exposure,
  allocation state, state document, a default fail-closed eligibility callback,
  and an explicit fail-open eligibility callback) and 12 one-defect invalid
  examples (duplicate ordinal, visit missing deployment, exposure missing
  occurrence, assignment carrying an occurrence, group assignment missing its
  group, malformed namespace, balanced assign missing the unit knob, empty
  treatment levels, dangling shared-treatment reference, design crossing an
  unplaced treatment, a bad `on_error` enum, and a malformed callback qualified
  name).
- 31 API-04 tests including version/deployment pinning, plan-digest closure,
  assignment/exposure separation, group-shared assignment, the explicit
  balanced-unit knob, and the flow-level fail-closed-by-default eligibility
  callback.

The 0.2 bundle encodes the folded surface: inline point-of-effect treatments
with shared-treatment references and an optional `Design` crossing (R-15), the
typed `Assign`/`Scope`/`Unit`/`Order` vocabulary with an explicit balanced
`unit` knob (A04-O05), group-scoped assignment records, durable per-cell
allocation state, and no wave references (ADR-0014).

## Acceptance status

`Drafted`, not `Accepted`. See the [review record](review-record.md). Remaining:
exact flow-materialization from API-01, branch/repeat/randomized-select
evaluation, activity-advancement and completion state machines, recovery fault
injection at each activity boundary, and NS-01/NS-08/NS-10 walkthroughs.
