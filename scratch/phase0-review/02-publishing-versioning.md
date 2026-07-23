# 02 — Publishing, versioning, amendments

| Field | Value |
| --- | --- |
| User | Researcher / study author (already has v1 published) |
| Goal | Ship a *change* to a study safely, understand versions, retire old ones |
| Backing contract | [API-01](../../docs/architecture/phase-0/api-01/index.md) · [authoring-and-publication](../../docs/architecture/phase-0/api-01/authoring-and-publication.md) |
| Model | **Git-native + stored compiled artifact** (foundational decision [F-1](DECISIONS.md)) |
| Status | ✅ all 8 decisions approved (see [DECISIONS.md](DECISIONS.md)) |

## What the user is trying to do

"I published v1 and ran 40 participants. I found a typo in the exit survey and one
condition needs a longer time limit. I want to ship a corrected version, keep v1's
data intact, understand exactly what changed, and stop routing *new* participants
to v1 — without breaking anything that references the study."

### Today (what we're replacing)

There is no versioning today. The running code *is* the study; editing it silently
changes what future (and sometimes in-flight) participants experience, and there's
no durable record that "v1" ever existed distinctly from "v2." We keep the
*outcome* (ship a change) but replace the mechanism.

## The model (after F-1)

Git does source versioning. The platform does the one thing Git can't: turn a
commit into an **immutable, resolved, access-partitioned artifact** and bind
results to it.

```text
YOUR GIT REPO                         THE PLATFORM
─────────────                         ────────────
commits, branches, diff, PRs   ──▶    compile(commit) ─▶ immutable StudyVersion
                                        · resolved (defaults/deps/plugins pinned)
                                        · client / server / provenance split
                                        · stored as bytes (not rebuilt later)
                                        · provenance: built_from = <git sha>
                                              │
                                        every result row ─▶ bound to version digest
```

What the platform is **not** doing anymore: no `StudyDraft`, no `DraftRevision`
chain, no "expected head" preconditions, no in-platform branch/diff. That's Git.

## Proposed surface (what the author writes)

> ⚠️ Illustrative, same caveat as surface 01.

### Publishing a version

```python
from mug import Study

study = Study.load(key="cooperative-foraging")

# The author names the version; the git commit is captured automatically.
version = study.publish(
    version="2.1",                     # hand-typed: unique within the study, immutable once used
    note="fix survey typo; longer hard-mode limit",
)
# git source is recorded automatically: current HEAD + a patch for any uncommitted changes.
print(version.string, version.built_from, version.digest)
# "2.1"   git:abc123f (+working-tree patch)   sha256:9f2c…
```

The author types the version string; they never hand-type the commit — the platform
records the repo's current HEAD **plus a patch capturing any uncommitted working-tree
changes**. You can publish from a dirty branch; the exact source state is still
reproducible as *commit + patch*. Local iteration is unchanged from surface 01 —
`study.check()` compiles/validates in-process; `publish()` stores a version.

### Seeing what changed

```python
# Structural diff between two published, resolved versions (not a git diff of source):
print(study.diff("2.0", "2.1"))   # "2 definitions changed: exit-survey, game-hard"
# Source-level history/diff is just git — the platform doesn't reimplement it.
```

### Retiring versions (availability, not deletion)

```python
study.deprecate(version=1, reason="superseded by v2")  # stop routing NEW visits to v1
study.withdraw(version=1, reason="protocol defect")    # stronger; v1 unusable for new visits
# Neither mutates v1's bytes or deletes collected data. v1 stays queryable & replayable.
```

## What happens behind the scenes

| Author action | Contract behavior (API-01, post-F-1) |
| --- | --- |
| `Study.load(key=…)` | Resolves the stable `Study` aggregate and its published-version index. No drafts. |
| `study.check()` | Local, pure compile/validate (surface 01, D01-5). No platform state. |
| `study.publish(version="2.1", …)` | Platform captures the repo's **current git HEAD plus a patch of any uncommitted changes** (dirty branches allowed), runs a **durable compile job**, verifies the transitive closure, and atomically writes the immutable `StudyVersion` (resolved bytes + client/server/provenance projections) under the author's version string. Records `built_from = <git sha> + patch` as provenance. |
| version identity vs. handle | Dedup **identity** is the resolved-content digest (scientific-manifest digest). The author's **version string** is a required, unique, immutable human handle bound 1:1 to that digest within the study. Git SHA is **provenance**. Rules: same content + same string → idempotent (returns existing); same content + a *new* string → rejected (already published as …); *new* content + a reused string → rejected (string already used). |
| result binding | Every event/result row references the resolved `StudyVersion` digest — the "exact thing that ran" is stored, not rebuilt on demand. |
| `study.diff(a, b)` | Structural diff of the two *resolved* versions (definitions + flow). Source diff is delegated to git. |
| `study.deprecate()` / `study.withdraw()` | Append-only **availability disposition**, separate from the version. Never rewrites bytes, never deletes evidence. Deletion is API-20 governance. |
| definition keys | Permanent keys (D01-3) still give longitudinal identity, but they now live **in the committed source**, not in a mutable server-side registry. The platform records, per study, the keys ever published and flags an incompatible key reuse at publish time — derived from published versions, not a separate aggregate. |

## Decisions to review

Mark each `Status:` line. (These refine F-1, which set the overall direction.)

### D02-1 — Publish auto-records the git commit plus a patch for uncommitted changes
The author does **not** hand-type a commit. `publish()` records the repo's current
HEAD, and if the working tree is dirty it also stores a patch of the uncommitted
changes. Dirty branches are allowed; exact source is reproducible as *commit + patch*.
- **Why it matters:** zero friction — no forced commit before publishing — while every version is still exactly reproducible. Caveat: a patch captures work that isn't in git history, so the platform stores the patch bytes itself (not just a reference) to keep provenance whole.
- **Open question:** do we also allow publishing from an uploaded source artifact for authors who don't use git, or is git the *only* accepted source?
- **Status:** ✅ approved *(per your directive: git source auto-recorded, dirty tree OK)*

### D02-2 — The platform stores the compiled artifact, not just the recipe
The resolved `StudyVersion` bytes are stored and bound to results. We do **not**
merely record `commit + lockfile` and rebuild later.
- **Why it matters:** reproducibility survives toolchain rot — a study from 2026 replays in 2031 even if `mug`/plugins/deps have moved on. Cost is storage of resolved artifacts.
- **Status:** ✅ approved (this is the F-1 tradeoff, restated for explicit sign-off)

### D02-3 — Author assigns a version string; content digest is identity; git SHA is provenance
Three distinct things per version: (1) a **required, hand-typed version string** —
the unique, immutable, citable handle authors and papers use; (2) the
**resolved-content digest** — the dedup identity underneath; (3) the **git SHA** —
auto-recorded provenance. The string is a 1:1 label on a content digest within the
study (see the table for the collision rules).
- **Why it matters:** authors get a name they control (`"2.1"`, `"pilot-3"`) instead of an opaque ordinal, while content-addressing still prevents cosmetic commits from spawning spurious versions and stops a divergent commit from posing as "the same version."
- **Open question:** any format constraints on the string (semver-ish? free-form?), or is any non-empty unique string allowed?
- **Status:** ✅ approved *(per your directive: hand-typed version string)*

### D02-4 — Amendments are new versions; no in-place edit
Every change ships as a new numbered version compiled from a new commit. v1 bytes
and data are permanent.
- **Why it matters:** anyone citing "v1" gets exactly what ran; but even a typo fix is a new version.
- **Status:** ✅ approved

### D02-5 — Deprecate/withdraw is availability only; never deletion
`deprecate`/`withdraw` change routing for *new* visits and are append-only facts.
They never mutate version bytes or delete data. Deletion is separate, governed
(API-20).
- **Why it matters:** "retire this version" and "erase this data" are different acts with different authority; conflating them loses data.
- **Open question:** are these author-callable, or operator actions an author only *requests*? (affects surfaces 03/13)
- **Status:** ✅ approved

### D02-6 — `diff(a, b)` compares *resolved* versions, not source
The platform's diff is over compiled protocol (definitions/flow); source-level diff
is git's job.
- **Why it matters:** "what actually differs in what participants experience?" is answerable at the resolved level, which source diff can't tell you (a dependency bump can change behavior with zero source diff).
- **Status:** ✅ approved

### D02-7 — Definition-key identity is derived from published versions, not a mutable registry
Longitudinal key identity (D01-3) is enforced by checking a new version's keys
against the study's published history, not by a separate mutable `DefinitionRegistry`
aggregate with its own revisions and preconditions.
- **Why it matters:** keeps the longitudinal-integrity guarantee while deleting a whole stateful subsystem — keys live in source (git), the platform only validates them at publish.
- **Status:** ✅ approved

### D02-8 — Fork is a new study bound to (forked) source, with recorded lineage
Forking creates a new `Study` namespace pointing at a new source location (typically
a forked/branched repo), with a lineage link to the parent version and **no** copied
enrollment, data, secrets, or deployments.
- **Why it matters:** spinning off a variant is mostly a git operation plus a thin platform record; no heavyweight in-platform copy of definition graphs.
- **Status:** ✅ approved

## Open questions for you

- **Git-only, or also uploaded artifacts?** (D02-1) Must every author use git, or do
  we accept a source bundle for non-git workflows?
- **Version-string format** (D02-3): free-form unique string, or a constrained shape
  (semver-ish)? What characters/length are allowed?
- **Who deprecates/withdraws** (D02-5): author, operator, or author-requests-operator-approves?
- **Monorepo vs one-repo-per-study:** does `Study.load(key=…)` + `source="git:sha"`
  assume the study is the whole repo, or can one repo hold several studies (subdir)?
