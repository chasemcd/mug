# 06 — Treatment & randomization (author's side)

| Field | Value |
| --- | --- |
| User | Researcher / study author designing an experiment |
| Goal | Declare an experimental design (conditions, factors, how participants are assigned) once, and get correct, recorded, reproducible assignment for free |
| Backing contract | [API-04](../../docs/architecture/phase-0/api-04/index.md) · authored via API-01 specs (`TreatmentSpec`/`FactorSpec`/`ConditionSpec`/`AssignmentPolicySpec`) |
| Status | ✅ all 7 decisions approved (see [DECISIONS.md](DECISIONS.md)) |

## What the user is trying to do

"I have a 2×2 design — difficulty (easy/hard) × partner (human/AI). I want
participants balanced across the four cells, the assignment recorded so I know
exactly who got what and why, and I don't want to hand-roll `random.choice()` and
hope it's balanced and reproducible."

### Today (what we're replacing)

Today randomization is hand-written in study code: `random.choice(...)`, balance by
luck, seeds rarely recorded, and the assignment often only exists implicitly in
whatever the participant happened to see. Surface 05 (D05-1/D05-2) made the *runtime*
honest; this surface is how the author *declares* the design so that runtime has
something correct to enforce.

## Treatment vs. flow randomization

Two different things, kept distinct:

- **`Treatment`** — a participant-level **experimental condition** that goes into your
  analysis (which arm they're in). Assigned once, recorded, balanced.
- **`flow.randomized_select`** (surface 01) — structural variety in the *flow* that
  isn't an analysis arm (e.g. presenting practice items in random order).

Rule of thumb: if you'll `group_by` it in analysis, it's a `Treatment`, not a
`randomized_select`.

## Proposed surface (what the author writes)

> ⚠️ Illustrative, same caveat as prior surfaces.

> Per **F-3**, MUG's own option vocabulary is typed constants (`Assign.*`, `Order.*`),
> never bare strings. Author-defined labels (condition names like `"easy"`) stay
> strings — they're the researcher's data, not MUG vocabulary.

### Between-subjects, factorial, balanced

```python
from mug import Treatment, Factor, Assign, activities

difficulty = Factor("difficulty", levels=["easy", "hard"])   # levels are the author's own labels (data)
partner    = Factor("partner",    levels=["human", "ai"])

design = study.set_treatment(
    Treatment(key="design", factors=[difficulty, partner], assign=Assign.balanced()),
)

# Reference the assigned condition via a typed handle — no string path:
game = activities.Interaction(
    key="game",
    spec=ForagingSpec(difficulty=design.level(difficulty)),
)
```

### Within-subjects (counterbalanced order)

```python
from mug import Order

study.set_treatment(
    Treatment(key="block-order", conditions=["A", "B"], within=True, order=Order.COUNTERBALANCED),
)
```

### Stratified on a screening response

```python
screening = activities.Form(key="screening", form=screening_form)

study.set_treatment(
    Treatment(
        key="design",
        conditions=["control", "treated"],
        assign=Assign.stratified(by=screening.field("age_band")),   # typed ref to a real activity's field
    ),
)
```

## What happens behind the scenes

| Author action | Contract behavior (API-04) |
| --- | --- |
| `set_treatment(...)` | Declares the full **design space** (all cells) at compile time, so export/analysis knows every condition that could exist — not just the ones that happened to occur. |
| `assign=Assign.balanced()` etc. | A **closed set of typed allocation policies** (F-3). MUG samples per participant, once, and can *guarantee* the balance property the policy names — because it owns the sampler, not your code. |
| sampling | Recorded as an immutable **`RandomizationOutcome` with a seed commitment** (D05-1): you can reconstruct exactly why participant X landed in cell Y; a refresh never re-rolls it. |
| `design.level(difficulty)` | A **typed reference** resolved from the participant's assignment — the author never reads a raw random value or a string path, so the design stays declarative and analyzable. |
| assignment vs. exposure | **`TreatmentAssignment`** (intent) is written up front; **`TreatmentExposure`** (delivery) is written only when the participant reaches that activity (D05-2). Both land in your data. |
| `Assign.stratified(by=…)` | Assignment is deferred to the flow point *after* the input it needs, then recorded once, immutably — still never re-rolled (reconciles with D05-1: "recorded once," not necessarily "all at t=0"). |

## Decisions to review

Mark each `Status:` line.

### D06-1 — You declare the design; you never hand-code randomization
Authors declare factors/conditions and an assignment policy; MUG does the sampling,
balancing, and recording. `random.choice()` in study code is not how conditions are
assigned.
- **Why it matters:** balance and reproducibility become guarantees instead of things you hope you got right; the runtime honesty from surface 05 has a correct design to enforce.
- **Status:** ✅ approved

### D06-2 — Assignment policies are a closed, typed set (not arbitrary code, not magic strings)
`Assign.random()`, `Assign.balanced()`, `Assign.blocked()`, `Assign.stratified(by=…)` —
a fixed vocabulary MUG owns, exposed as typed constants (F-3), each with a property
it can guarantee and record.
- **Why it matters:** MUG can promise "balanced across cells" only if it owns the sampler; arbitrary author code can't be verified or reliably reproduced. Typed policies also give autocomplete and catch typos at author time.
- **Open question:** is this closed set enough for v0, or do we need an escape hatch (a plugin-provided allocator, API-21) for adaptive/custom designs — accepting it can't carry the same guarantees?
- **Status:** ✅ approved

### D06-3 — Between- and within-subjects are both first-class
Between-subjects (one condition per participant) and within-subjects (sees multiple,
order randomized/counterbalanced) are both declarable; within-subject order is
recorded like any other assignment.
- **Why it matters:** covers the two dominant experimental structures without the author bolting order-randomization on by hand.
- **Status:** ✅ approved

### D06-4 — Conditions are referenced symbolically, so the full design space is known at compile time
Activity specs and flow reference `condition("design.difficulty")`, not a raw value.
The compiler therefore knows every cell that can exist.
- **Why it matters:** export/analysis can enumerate all conditions (including ones with zero participants so far), and a typo'd condition name is a compile error, not a silent mis-assignment.
- **Status:** ✅ approved

### D06-5 — Assignment (intent) and exposure (delivery) both reach the author's data
The author gets both records — what each participant was assigned, and what they were
actually exposed to — not just one collapsed value.
- **Why it matters:** enables intent-to-treat vs. per-protocol analysis directly from the data; the authoring surface makes surface 05's D05-2 visible to the researcher.
- **Status:** ✅ approved

### D06-6 — Covariate-dependent assignment happens at a defined flow point, recorded once
`Assign.stratified(by=…)` (and any design needing a participant input) assigns *after*
the activity that supplies the input, then records the outcome immutably — never re-rolled.
- **Why it matters:** supports stratified/screening-dependent designs while preserving the "recorded once, never reshuffled" integrity from surface 05.
- **Status:** ✅ approved

### D06-7 — Assignment scope is typed: per-participant or per-group
A treatment declares its scope — `Scope.PARTICIPANT` (default) assigns per person;
`Scope.GROUP` assigns one condition to a whole session/room. Both first-class.
```python
Treatment(key="partner", conditions=["human", "ai"],
          assign=Assign.balanced(), scope=Scope.GROUP)   # the whole room shares one condition
```
- **Why it matters:** interaction studies often manipulate the *shared session* (e.g. "this room has an AI partner"), not the individual — this makes that a first-class, recorded assignment rather than a hack. Ties into surface 07 (seats/actors): a group condition is assigned when the group forms.
- **Open question:** for `Scope.GROUP`, does balancing count *groups* or *participants* across cells (they differ when group sizes vary)?
- **Status:** ✅ approved *(your call: per-participant + per-group both)*

## Settled (your calls)

- **Custom/adaptive designs → closed set only for v0** (D06-2). No plugin allocator
  escape hatch yet; every design MUG runs carries a guaranteed, recorded balance
  property. Adaptive/custom allocation is deferred to a later version.
- **Assignment scope → per-participant *and* per-group** (new D06-7 above).
- **Balance window → across the study-version lifetime.** `Assign.balanced()` balances
  over *all* enrollments for a study version, surviving restarts/redeploys — which
  requires **durable allocation state** (a persistent per-cell counter), not per-run
  memory. This is the behavior, not an author knob.

## Open questions for you

- **Group balancing unit** (D06-7): with `Scope.GROUP`, balance across cells by
  *group count* or by *participant count* when group sizes vary?
