# Get your whole study's data out

*For study authors. When your study is done, you ask for the dataset and MUG
hands you back a set of clean, newline-delimited-JSON files -- one per kind of
data you collected -- each reproducible from the record and safe to share.*

> Status: **the runtime is built.** `mug.export.export_study_dataset` reads a
> study's whole record and produces one export bundle per dataset kind. The
> one-word command line that calls it for you (`mug export`) lands with the CLI;
> today you call the one function, or the platform calls it for you. The
> plumbing under this surface is in the runtime; you do not read it.

---

## The whole thing

Your study ran. Participants filled in forms, played the game, and answered a
comparison or two. Every one of those left a durable record. To get all of it
as data, you ask for the dataset once:

```python
from mug.export import export_study_dataset

dataset = await export_study_dataset(
    store=store,               # where your study recorded everything
    artifacts=store,           # where the export files are written
    study_version=my_study,    # which study, which version
    git_provenance=my_git,     # the code state that produced it
)
```

That is the entire thing. You get back a `dataset` with one **bundle per kind of
data** your study collected:

| Kind | What it holds |
| --- | --- |
| `events` | everything, in order -- the complete record of the study |
| `trajectories` | the game episodes: a row per frame and the episode's end |
| `preferences` | the comparison answers: who was shown what, and their choice |
| `conversations` | the chat messages, if your study had any |

A kind you did not collect simply is not in the set -- a study with no chat has
no `conversations` bundle, not an empty one. Each bundle names a file
(`bundle.artifact`), how many rows it has (`bundle.row_count`), and where those
rows came from (a lineage record). You never write an id, a seed, or a schema --
MUG fills all of that in.

---

## What you get back

Each bundle is one **newline-delimited-JSON** file: one record per line, in
order. Every line is a canonical *event* -- the durable, timestamped fact that
something happened -- and every event points at its data by a **digest**, never
by copying a raw value in. So the export is safe to share: a form answer, a
game observation, or a secret never travels inside it, only the fingerprint that
proves which recorded value produced the row.

You load a bundle the same way you would any JSONL dataset:

```python
import json

path = dataset.bundles[0].artifact           # the events file's reference
rows = [json.loads(line) for line in open_bundle(path)]
```

Each row carries where it sits in the record (`stream_position`), when it was
recorded (`recorded_at`), what kind of event it is (`event_schema`), and the
digest of its payload (`payload_digest`). To join a preference answer back to
the two runs it judged, or a game frame back to its episode, you follow those
references -- they are the same references your replay bundles and comparison
records use, so the whole dataset stitches together.

---

## Reproducible and accountable -- for free

Two guarantees come with every export, and you ask for neither:

- **The same study exports the same bytes.** The export orders its rows the same
  way every time and is built only from the record, so exporting twice gives you
  byte-identical files with identical digests. A reviewer who re-runs the export
  gets exactly what you got. Nothing depends on when you asked or on a hidden
  random choice.
- **Every file states where it came from.** Each bundle carries a *lineage
  record*: the git commit that produced it, whether the working tree was clean,
  and the exact source streams the rows were read from. So a dataset is never a
  loose file -- it names the code and the records behind it, and a
  redistribution can be checked against them.

Together that means your dataset is *reproducible* (anyone can rebuild it) and
*accountable* (it says what it was built from) without you writing a line to
make it so.

---

## How it reaches you day to day

You will normally not call the function above by hand. Two paths surface it:

- **The command line (with the CLI).** `mug export` runs the same call over your
  deployed study and writes the bundles to a folder you name -- the everyday way
  a researcher pulls their data down.
- **The platform.** A finished study can export itself on a schedule or on a
  button, using exactly this runtime.

Either way, what lands is the same: one JSONL file per kind, each reproducible
and each naming its origin.

---

## Under the hood (you do not write this)

For completeness: `export_study_dataset` reads the whole record once, sorts each
canonical event into the kinds it belongs to (every event into `events`, a game
event also into `trajectories`, a comparison answer also into `preferences`,
and so on), writes each kind's rows to a content-addressed file, and builds the
`ExportBundle` and `LineageRecord` that describe it. You never call the pieces --
the platform does, from the one request you made. This section is here only so
you know where the reproducibility comes from.
