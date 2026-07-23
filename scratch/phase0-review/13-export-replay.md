# 13 — Export & replay

| Field | Value |
| --- | --- |
| User | Analyst / researcher getting trustworthy data out, and auditing/reproducing sessions |
| Goal | Export clean, schema-bound datasets with full lineage, and replay any recorded session exactly — without re-calling models or re-firing side effects |
| Backing contract | [API-16](../../docs/architecture/phase-0/api-16/index.md) (replay) · [API-19](../../docs/architecture/phase-0/api-19/index.md) (export/lineage) |
| Status | ✅ all 7 decisions approved (JSONL export; see [DECISIONS.md](DECISIONS.md)) |

## What the user is trying to do

"I ran the study. Now I want (1) clean data out — trajectories, preferences, survey
responses, conversations — in a format I can analyze, with enough provenance that I
could reproduce a figure. And (2) I want to *replay* specific sessions: watch what
happened, verify it's exactly what the data says, and even branch a run to ask 'what
if the AI partner had been different?'"

### Today (what we're replacing)

Today data comes out as ad-hoc logs with inconsistent schemas and thin provenance, and
there's no principled replay — you can't cheaply re-run a session, verify it, or branch
it. Every capture guarantee in the earlier surfaces exists so that *this* surface can be
trustworthy. We keep the outcome (data + the ability to review sessions) and make both
schema-bound, lineage-complete, and exactly replayable.

## What the user does

### Export

```bash
mug export cooperative-foraging@2.1 --dataset trajectories
mug export cooperative-foraging@2.1 --dataset preferences
```

```python
from mug import Dataset

ds = study.export(Dataset.TRAJECTORIES)   # one standard format — JSONL
print(ds.schema)      # the exact row schema
print(ds.lineage)     # every source this was derived from
# ...then: pandas.read_json(ds.path, lines=True) / datasets.load_dataset("json", ...) / jq, etc.
```

**One export format: JSONL** (one JSON object per line). No format menu. Dataset kinds
— **events, trajectories, preferences, conversations** — each bind an exact row schema;
nested/variable data (conversations, tool calls) is just nested JSON, no second format
needed. A **redacted or aggregated** export is a *new* object with its own lineage,
never a silent edit of the original.

### Replay

```python
run = mug.replay("run_abc.mugrun")            # exact replay: makes NO provider/tool calls
run.watch()                                    # visual playback
report = run.verify()                          # deterministic state-hash check (or declared visual fallback)

# counterfactual branch
what_if = run.branch(at_step=1200, recast={"forager-2": other_agent})
```

## What happens behind the scenes

| Action | Contract behavior (API-16 / API-19) |
| --- | --- |
| `study.export(...)` | Produces an `ExportBundle`: a normalized dataset (events/trajectories/preferences/conversations) bound to an exact **row schema**, in **one standard format (JSONL)** — nested/variable data is just nested JSON. |
| lineage | Every bundle carries a **`LineageRecord`** naming its sources — you can trace any row back to the exact recorded evidence that produced it. |
| redaction/aggregation | A redacted/aggregated export is a **new lineage-bearing object**, never a mutation of the original — de-identified derivatives are tracked, the source stays intact. |
| `mug.replay(...)` | Exact replay **makes no provider calls and repeats no external tool side effects**; recorded model/tool outputs are substituted from a **`DecisionTape`**. |
| `run.verify()` | Runs a **deterministic state-hash check**; if exact determinism isn't achievable it **declares a visual fallback** honestly (never fakes a match). |
| bundle integrity | Validation **detects modified artifacts** and reports validity accordingly — a tampered `.mugrun` is caught. |
| `run.branch(...)` | Forks the recorded run at a point and lets you change something (recast an actor, alter a decision) to explore a counterfactual — a new run derived with lineage to the original. |
| trajectory slices | Slices of a replay are exactly the immutable **candidates** a preference task consumes (D12-3) — annotation links back to real recorded behavior. |

## Decisions to review

Mark each `Status:` line.

### D13-1 — Exports are schema-bound datasets in ONE standard format (JSONL)
Each dataset kind (events, trajectories, preferences, conversations) binds an exact row
schema and exports as **JSONL** (one JSON object per line) — a single, familiar,
easy-to-work-with format, no menu. Nested/variable data is just nested JSON.
- **Why it matters:** JSONL is human-readable, greppable, streamable/appendable, and the default of the LLM/RLHF ecosystem (HuggingFace `datasets`, fine-tuning pipelines) — it mimics workflows MUG's audience already uses, and handles ragged/deeply-nested conversation and tool-call data without awkward flattening. Loads directly via `pandas.read_json(lines=True)` / `datasets`.
- **Trade-off (accepted):** less storage-efficient than a columnar format for very large numeric trajectory data; familiarity and ease chosen over raw tabular efficiency.
- **Status:** ✅ approved

### D13-2 — Every export carries a complete lineage record
An export names all its sources; any row traces back to the recorded evidence that
produced it.
- **Why it matters:** reproducibility and defensibility — "where did this number come from?" always has an answer, down to the exact events/versions.
- **Status:** ✅ approved

### D13-3 — Redacted/aggregated exports are new lineage-bearing objects, never silent edits
De-identification or aggregation produces a new tracked object; the original is never
mutated in place.
- **Why it matters:** you can share a safe derivative without destroying or altering the source, and the derivation itself is auditable (what was redacted/aggregated, from what).
- **Status:** ✅ approved

### D13-4 — Exact replay makes no provider/tool calls; recorded outputs are substituted
Replaying a session substitutes recorded model/tool outputs from a decision tape — it
never re-calls a provider or re-fires a side effect.
- **Why it matters:** replay is free (no token cost), safe (no real-world side effects), and faithful (you see exactly what happened, not a fresh generation).
- **Status:** ✅ approved

### D13-5 — Replay declares a capability level; determinism is verified or a visual fallback is declared
Replay levels are **visual / deterministic / outcome**; deterministic replay verifies
exact state via hash, and when that isn't achievable a visual fallback is declared —
never a faked match.
- **Why it matters:** you know exactly how trustworthy a given replay is; the system is honest about when it can and can't reproduce bit-exact state.
- **Status:** ✅ approved

### D13-6 — Replay validation detects modified/tampered artifacts
Bundle validation reports validity and flags altered artifacts.
- **Why it matters:** a `.mugrun` you were sent (or archived years ago) can be trusted or flagged — integrity, not just availability.
- **Status:** ✅ approved

### D13-7 — Replay supports counterfactual branching
A recorded run can be forked at a point and altered (recast an actor, change a decision)
to explore "what if," producing a new run with lineage to the original.
- **Why it matters:** enables counterfactual analysis and agent comparison directly from real sessions, and trajectory slices from replays feed preference tasks (D12-3). Trade-off: branched runs *do* recompute (and may call models) beyond the recorded tape — clearly distinct from exact replay.
- **Status:** ✅ approved

## Open questions for you

- **Replay levels in v0** (D13-5): all three (visual/deterministic/outcome), or start
  with visual + deterministic?
- **Branching scope** (D13-7): is counterfactual branching a v0 goal, or is exact
  replay + export enough for v0 with branching as a fast-follow?
- **Who can export** (authority): analyst self-serve, or export gated by governance
  grants (ties to surface 14) — especially for non-redacted / identity-adjacent data?
- **Live vs. batch export:** streaming/incremental export while a study is running, or
  export as a batch operation after (or during) collection?
