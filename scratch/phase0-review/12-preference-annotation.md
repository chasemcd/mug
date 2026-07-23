# 12 — Preference & annotation studies

| Field | Value |
| --- | --- |
| User | Researcher building surveys, content, and preference/annotation tasks (RLHF-style, human eval) |
| Goal | Collect form responses and human judgments over candidates (trajectories, model outputs, chats, media) — blinded, order-randomized, reliably saved |
| Backing contract | [API-17](../../docs/architecture/phase-0/api-17/index.md) (content/forms/a11y) · [API-18](../../docs/architecture/phase-0/api-18/index.md) (preferences/annotation/quality) |
| Status | ✅ all 8 decisions approved (see [DECISIONS.md](DECISIONS.md)) |

## What the user is trying to do

"Two things. (1) Plain surveys — a debrief with a Likert scale, a multiple choice, a
free-text box — that reliably save. (2) A preference task: show annotators two agent
trajectories (or two model outputs, or two chat responses) and ask which is better,
blinded and in random order, so I can build an RLHF/eval dataset."

### Today (what we're replacing)

Today forms are ad-hoc HTML in a scene, responses can be lost on a bad connection, and
there's no first-class way to elicit preferences over recorded candidates. We keep the
outcomes (surveys + human judgments) and make them declarative, reliable, and blinded.

## What the user writes

### Forms (declarative, default widgets, accessible by default)

```python
from mug import activities, Field

debrief = activities.Form(key="debrief", fields=[
    Field.likert("enjoyment", "How much did you enjoy this?", scale=7),
    Field.choice("strategy", "Which strategy did you use?", options=["hoard", "share"]),
    Field.text("comments", "Anything else?", required=False),
])
```

### Preference / annotation over candidates

```python
from mug import Preference, Compare

which_better = activities.Preference(
    key="cooperativeness",
    candidates=trajectory_slices,          # immutable REFERENCES (from replays/outputs/chats/media)
    task=Compare.pairwise(prompt="Which agent behaved more cooperatively?"),
    blind=True,                            # hide which model/source produced each
    randomize_order=True,                  # display order randomized; identity unchanged
)
```

Candidates can be **trajectory slices** (from recorded episodes, surface 13), **model
outputs**, **chat messages/segments**, or **media** — all referenced immutably, never copied.

### Inline preference *within* a chat (live A/B, RLHF-in-the-loop)

Preference elicitation can also happen live inside a conversation: you chat with an
LLM, **two candidate replies** appear to your message, you pick one, the preference is
recorded, and the **conversation continues with your choice**.

```python
Chat(
    key="assistant",
    respond_with=partner,                        # an LLMAgent (surface 11)
    elicit_preference=Compare.pairwise(n=2),     # generate 2 candidate replies; record the pick; continue with it
    blind=True,                                   # optional: don't reveal which is which
)
```

The unchosen branch is still recorded (it's valuable preference data); only the chosen
reply continues the thread.

## What happens behind the scenes

| Author action | Contract behavior (API-17 / API-18) |
| --- | --- |
| `activities.Form(fields=[…])` | A typed `FormSpec`; field keys unique; default accessible widgets (no hand-built HTML). |
| a gating response | If the form/preference **gates progression**, MUG requires a **durable receipt before advancing** — "your answer was saved" is guaranteed, so a bad connection can't silently drop a response. |
| `candidates=…` | Each is a generic **immutable `CandidateRef`** (trajectory slice / output / chat / media) — content lives in its owning family, not duplicated into the task. |
| `blind=True` | Candidates are referenced by **blinded display handle**; raw model/provider identity never appears in the candidate reference or the participant's view. |
| `randomize_order=True` | Display order is randomized per annotator but **never changes candidate identity**; the recorded choice maps back to the true candidate. |
| a choice | Must be **one of the presented candidates** (no phantom choices); recorded with the display order that was shown. |
| `elicit_preference=` on a chat | The LLM generates **n candidate replies** (live model outputs, turn-bounded per D08-5); both are recorded as candidates; the participant's pick is a `PreferenceResponse`; the **chosen reply continues the conversation**, the unchosen branch is retained as data (API-08 candidates + API-18 elicitation). |
| accessibility | Every presentation component declares an **accessibility profile with an enforced WCAG floor** (AA ⇒ keyboard nav + screen-reader). |

## Decisions to review

Mark each `Status:` line.

### D12-1 — Forms are a declarative, typed activity with default accessible widgets
Authors declare fields (`likert`/`choice`/`text`/…) with unique keys; MUG renders
accessible default widgets. No hand-built survey HTML.
- **Why it matters:** the common case (a survey) is a few lines and works/accessible out of the box, consistent with the chat widget (D10-7).
- **Status:** ✅ approved

### D12-2 — Progression-gating responses require a durable receipt before advancing
If a response must be recorded to continue, MUG will not advance until it's durably
saved.
- **Why it matters:** the classic "participant submitted, connection blipped, data lost" failure can't happen for gating responses — survey/annotation data integrity.
- **Status:** ✅ approved

### D12-3 — Preference/annotation is a first-class activity over immutable candidate *references*
Candidates (trajectory slices, model outputs, chat segments, media) are referenced
immutably from their owning families, not copied into the task.
- **Why it matters:** RLHF/eval datasets link back to the exact recorded thing that was judged (reproducible, no drift), and any recorded artifact can become a candidate.
- **Status:** ✅ approved

### D12-4 — Candidates are blinded and display-order randomized without changing identity
Blinding hides the source (which model/agent produced a candidate); order is randomized
per annotator; neither alters the true candidate the choice records against.
- **Why it matters:** removes order and brand bias from preference data — a core validity requirement for RLHF/human-eval — while keeping the judgment linked to the real candidate.
- **Status:** ✅ approved

### D12-5 — A choice must be one of the presented candidates
The recorded choice is constrained to what was actually shown, with the shown order.
- **Why it matters:** no phantom or out-of-set choices corrupt the dataset; every judgment is interpretable.
- **Status:** ✅ approved

### D12-6 — Content/forms have an enforced accessibility floor (WCAG), even though game-input a11y is deferred
Presentation components declare an accessibility profile with a WCAG floor (keyboard +
screen-reader at AA). This is distinct from — and not blocked by — the game-input
rebinding/a11y deferral in surface 10.
- **Why it matters:** surveys/content reach the widest participant pool and are where a11y is both most expected and most achievable; deferring *game-input* a11y doesn't mean forms should be inaccessible.
- **Status:** ✅ approved

### D12-8 — Preference can be elicited inline within a live chat (RLHF-in-the-loop)
During an LLM conversation, MUG can present multiple candidate replies, record the
participant's choice, and continue the thread with the selected reply (the unchosen
branch retained as data). Same blinding/order guarantees as the standalone task.
- **Why it matters:** captures interactive preference data in the natural flow of a conversation (the dominant modern RLHF pattern), not only as a separate side-by-side task — and it reuses the chat (surface 08/10) and preference machinery rather than a bespoke path.
- **Settled:** **author-configurable, sampled by default** — the author sets whether A/B is every turn or sampled, blocking or skippable, and `n` (default 2; best-of-n via config). Default: sampled on a fraction of turns, `n=2`, choosing continues the thread.
- **Status:** ✅ approved

### D12-7 — Multi-annotator quality & adjudication are first-class
Multiple annotators can judge the same candidates; quality evidence (agreement,
attention checks) and adjudication of disagreements are supported.
- **Why it matters:** real annotation pipelines need inter-annotator reliability and a way to resolve disagreement; building it in beats bolting it on per study.
- **Settled:** v0 captures **multiple judgments + agreement metrics**; a full multi-rater *resolution* workflow (third rater / researcher adjudicates) is deferred.
- **Status:** ✅ approved

## Settled (your calls)

- **Form field types (D12-1) → core set + slider/rating**: single/multi choice, Likert, short/long text, number, slider, rating. (Ranking/matrix and file/media upload deferred.)
- **Standalone task types (D12-3) → pairwise A/B + rating/scoring**. (K-way ranking and free-form annotation deferred.)
- **Candidate sources → all four in v0**: model outputs, chat messages/segments, trajectory slices, and media.
- **Inline in-chat preference (D12-8) → author-configurable, sampled by default** (`n=2` default).
- **Adjudication (D12-7) → multiple judgments + agreement metrics in v0**; full resolution workflow later.
