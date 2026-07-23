# 01 — Researcher authoring a study

| Field | Value |
| --- | --- |
| User | Researcher / study author |
| Goal | Describe a study in Python and get an immutable, publishable artifact |
| Backing contract | [API-01](../../docs/architecture/phase-0/api-01/index.md) |
| Status | ✅ all 8 decisions approved (see [DECISIONS.md](DECISIONS.md)) |

## What the user is trying to do

"I want to define a flow — a welcome screen, then a multiplayer game (randomly one
of two variants), then an exit survey — and hand it to the platform so it can run
it with real participants and give me clean data back."

### Today (what we're replacing)

Currently the author builds mutable objects: an `ExperimentConfig`, a `Stager`
that sequences `Scene`s, and `app.run()`. Identity, randomization, capture, and
deployment are tangled together, and there is no immutable published artifact —
the running code *is* the study. There is deliberately **no compatibility** with
this; we keep the *outcomes*, not the API.

## Proposed surface (what the author writes)

> ⚠️ Illustrative. The wire/persisted contracts (API-01) are drafted and
> test-backed; this Python authoring API is what we're designing *now*, against
> those contracts.

```python
from mug import Study, activities, flow

study = Study(key="cooperative-foraging")   # stable program identity

# --- Definitions: each has a stable, author-chosen key ---
welcome = activities.Content(
    key="welcome",
    slot="welcome-copy",            # neutral slot; real content bound at deploy
    response_required=False,
)
game_a = activities.Interaction(key="game-easy", spec=ForagingSpec(difficulty="easy"))
game_b = activities.Interaction(key="game-hard", spec=ForagingSpec(difficulty="hard"))
survey = activities.Form(key="exit-survey", form=exit_survey_form)

study.add(welcome, game_a, game_b, survey)   # register definitions (explicit call)

# --- Flow: set via a method, never attribute assignment ---
study.set_flow(
    flow.sequence(
        welcome,
        flow.randomized_select(choose=1, among=[game_a, game_b], rule="balanced"),
        survey,
        flow.terminal(outcome="complete"),
    )
)

# --- Validate & compile locally (pure, no side effects) ---
report = study.check()          # returns diagnostics; never publishes
report.raise_if_errors()

# --- Publish: produces an immutable version ---
version = study.publish(note="baseline v1")
print(version.id, version.number)     # studyver_…  2
```

## What happens behind the scenes

| Author action | Contract behavior (API-01) |
| --- | --- |
| `Study(key=…)` + `study.add(…)` | Each definition is registered in a **definition registry** under its key; keys are permanent (rename/tombstone are explicit, forks get fresh IDs). |
| `study.set_flow(…)` | Method call (not attribute assignment): validates and lowers the flow to a normalized `AuthoringDocument` (closed `FlowNode` union: sequence / activity / randomized_select / repeat / branch / terminal). |
| `study.check()` | Pure compile: validates references, reachability, cycles, terminal coverage, randomization bounds. Returns diagnostics; **errors block, warnings must be acknowledged**. |
| `study.publish()` | Compiles to a `ScientificManifest` + client / private-server / provenance manifests, verifies the closure, and atomically writes an **immutable `StudyVersion`**. Re-publishing identical content returns the same version (content-idempotent). |
| randomization | The compiler records the *rule*; it **never samples**. Sampling happens per-participant at visit time (API-04). |
| secrets | The author declares a *requirement* ("this needs a chat-provider credential"), never a value. Binding happens at deploy (API-02). |

## Decisions to review

Mark each `Status:` line.

### D01-1 — Vocabulary: `Study`, not `Experiment`
The top-level object is a `Study` (a stable research program that can have many
immutable versions and longitudinal waves). `Scene`, `Stager`, `ExperimentConfig`
are gone.
- **Why it matters to the user:** they relearn one core noun; everything hangs off `Study`.
- **Status:** Approved

### D01-2 — Flow is an explicit algebra, not imperative staging
Authors compose `sequence / randomized_select / repeat / branch / terminal`
instead of appending scenes to a stager.
- **Why it matters:** the whole flow is inspectable and analyzable before anyone runs it; but it's a new mental model and more verbose for the simple linear case.
- **Alternative:** offer a thin `flow.linear(a, b, c)` sugar for the common case. No need to do this. 
- **Status:** Approved

### D01-3 — Definitions carry permanent author-chosen keys
Every activity/definition has a stable `key`. Renaming is an explicit operation;
a deleted key is tombstoned and never silently reused.
- **Why it matters:** longitudinal integrity (a "game-hard" in wave 1 means the same thing in wave 3) — but authors can't casually rename things.
- **Status:** Approved

### D01-4 — Closed set of activity types
`Content`, `Form`, `Interaction`, `Preference`, `Terminal` — a fixed vocabulary,
each with a typed spec. No free-form scene.
- **Why it matters:** predictable compilation and capture; extensibility comes through plugins (API-21), not ad-hoc scenes.
- **Status:** Approved

### D01-5 — `check()` is pure and local; `publish()` is the only committing call
Authors can validate/compile as many times as they want with no side effects;
only `publish()` creates state.
- **Why it matters:** fast, safe iteration; a clear "point of no return."
- **Open question:** does `check()` run fully offline, or does it need to resolve
  packages/plugins (which may require network)? A: Check may need to run offline. 
- **Status:** Approved, but check() may require online package resolution. 

### D01-6 — Authors declare secret *requirements*, never values
`activities.Interaction` needing an LLM declares it needs `chat-provider-key`; the
credential is bound at deploy time by an operator (API-02).
- **Why it matters:** authors literally cannot leak a secret into a study; but author and operator are now two roles/steps.
- **Status:** Approved

### D01-7 — Publish returns an immutable, content-addressed version
`publish()` yields a `StudyVersion` with a number and ID; identical content
re-published returns the *same* version rather than a duplicate.
- **Why it matters:** reproducibility and "did I already publish this?" safety — but authors must think in versions, not "the current study."
- **Status:** Approved

### D01-8 — No public attribute assignment; state changes go through methods
The authoring surface never exposes settable attributes (`study.flow = …`,
`study.definitions = …`). Every mutation is a named method: `study.add(...)`,
`study.set_flow(...)`, `study.set_metadata(...)`. This gives each change a
validation/normalization hook, keeps `=` from silently doing real work, and makes
the "point of no return" (`publish()`) the only place state escapes the process.
- **Why it matters:** authors get clear errors at the call site instead of a bad value sitting on a field until `check()`; the API can evolve validation without breaking attribute access.
- **Two idioms to choose between** (pick one, applied consistently):
  - **(a) Mutable builder** — `study.set_flow(...)` mutates in place, returns `None` (or `self` for chaining). Freezes only at `publish()`. *Simplest; matches "build then publish."*
  - **(b) Immutable/fluent** — `study = study.with_flow(...)` returns a *new* `Study`; the old one is unchanged. *Philosophically aligned with the immutable-everything theme, but easy to forget the reassignment and verbose.*
- **Recommendation:** (a) mutable builder with `set_*`/`add`, since `check()`/`publish()` are already the explicit freeze points — reserve immutability for the *published* artifact, not the in-progress authoring object.
- **Status:** Approved, do (a) and return self for chaining flexibility. 

## Open questions for you

- Is the author writing plain Python modules, or do we want a project/CLI
  scaffold (`mug new`, `mug check`, `mug publish`)?

  For now, we'll stick to plain Python modules. We may want a CLI in the future. 

- How much should `check()` show — a compiler-style diagnostic list, or a
  rendered preview of the flow?

  Compiler-Style diagnostic list. 

- Do authors ever need to see the client/server/provenance split, or is that
  entirely the platform's concern?

  Platform's concern. 
