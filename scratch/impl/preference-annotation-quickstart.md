# Ask participants which run is better

*For study authors. You write one line. MUG shows each participant a clean, blinded
comparison, records their choice, and keeps it reproducible -- you never touch
shuffling, seeds, handles, or the data store.*

> Status: **the author surface and its runtime are built.** `mug.authoring.Comparison`
> (this surface) compiles into the annotation records and the built loop
> (`mug.preferences`: `compile_comparison`, `PreferenceService`) drives the whole
> thing -- assign a blinded comparison, record the one choice, keep it reproducible.
> Not yet wired: the comparison *screen* onto the live transport, so today the
> platform runs the compiled comparison for each participant rather than a browser
> rendering it. The plumbing under this surface is in the runtime; you do not read it.

---

## The whole thing

You ran a study -- say two agent policies played the same cooking game, and MUG
recorded both runs. Now you want participants to tell you which one played better.
You write one object:

```python
from mug.authoring import Comparison

Comparison(
    key="which-chef",
    ask="Which chef cooked better?",
    options={"Policy A": run_a, "Policy B": run_b},   # your two recorded runs
)
```

That is the entire thing. `run_a` and `run_b` are runs your study already recorded
(a captured episode, or a replay bundle). You label them for *your own* analysis;
the participant never sees those labels.

Everything else has a sensible default, so you only override what you mean to change:

| You write | Default | What it does |
| --- | --- | --- |
| `ask=` | — | the question shown above the two runs |
| `options=` | — | your labels → the recorded runs to compare (two or more) |
| `blind=` | `True` | hide your labels from the participant behind neutral names |
| `shuffle=` | `True` | randomize the left/right order per participant |
| `style=` | `"compare"` | `"compare"` = pick the better one; `"rate"` = rate each |

To compare more than two runs, add more options; to stop blinding or shuffling, set
the flag to `False`. You never write an id, a seed, a handle, or a protocol object --
MUG fills all of that in.

---

## How it runs in your study

A comparison is one step in your study flow, the same as a form or a game. You drop
it into the flow where you want participants to reach it:

```python
from mug.authoring import Comparison

study.flow = [
    consent_form,                 # a form
    play_the_game,                # an interaction
    Comparison(                   # the comparison -- one step
        key="which-chef",
        ask="Which chef cooked better?",
        options={"Policy A": run_a, "Policy B": run_b},
    ),
    debrief_form,                 # another form
]
```

When a participant reaches that step, MUG:

1. picks the order they see (shuffled from a per-participant seed it commits to),
2. shows them the question and the runs behind neutral labels,
3. records their one choice, and
4. advances them to the next step.

You do not write any of that loop. You wrote the `Comparison`; MUG runs it.

---

## What the participant sees

A clean, blinded screen -- the question, the two runs side by side under neutral
names, and a choice:

```
┌──────────────────────────────────────────────────────────┐
│  Which chef cooked better?                                 │
│                                                            │
│   ┌───────────────┐        ┌───────────────┐              │
│   │   Option 1    │        │   Option 2    │              │
│   │  ▶ [run plays]│        │  ▶ [run plays]│              │
│   └───────────────┘        └───────────────┘              │
│                                                            │
│        ( ) Option 1            ( ) Option 2                │
│                                                            │
│                     [  Submit  ]                           │
└──────────────────────────────────────────────────────────┘
```

- **Neutral names.** Because `blind=True`, the participant sees "Option 1 / Option 2",
  never "Policy A / Policy B". Their choice carries no signal from the label.
- **A per-participant order.** Because `shuffle=True`, "Option 1" is Policy A for some
  participants and Policy B for others, so a left/right bias averages out. MUG maps
  their pick back to the right run for you.
- **The runs themselves.** Each option plays back the recorded run -- the same durable
  trajectory your dataset export ships -- so what the participant judges is exactly
  what you recorded.

A `style="rate"` comparison shows a rating control under each run instead of a single
pick; everything else is the same.

---

## Blinding and shuffling -- trustworthy for free

You did not shuffle with a hidden coin. MUG derives the order from a per-participant
seed and records only a *commitment* to that seed -- not the seed itself. Later,
revealing the seed reproduces the exact order the participant saw, so no one can claim
the order was rigged after the fact, and no one can read the order from the record
alone. You get reproducible, tamper-evident randomization without writing a line of it.

---

## Answered once, recorded once

MUG records each participant's comparison as one durable lineage: the assignment, then
their choice, then quality signals (how long they took, whether they passed an
attention check). Because it goes through the same recording spine as everything else,
you get two guarantees without asking:

- **A dropped connection never double-records.** If a participant's browser retries the
  submit, MUG replays the original -- the choice is recorded once, not twice.
- **A participant answers once.** A second, different answer to the same comparison is
  refused, not appended.

So your data has exactly one response per participant per comparison, every one joined
to the runs it judged. When you export the dataset, each response points straight back
at the recorded evidence that produced it -- and your `Policy A` / `Policy B` labels
are there for the analysis, even though the participant never saw them.

---

## Under the hood (you do not write this)

For completeness: `mug.preferences.compile_comparison` turns your one `Comparison`
into the blinded records the annotation loop needs (a protocol and one candidate per
option, with the ids, handles, and task kind filled in), and `PreferenceService`
drives the per-participant `assign → respond → attest` loop over the recording spine.
You never call either -- the platform does, from the `Comparison` you wrote. This
section is here only so you know where the simplicity comes from.
