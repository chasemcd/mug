# API-18 Review Record

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
| Version-0 schemas | Drafted | `preference.schema.json` |
| Golden fixtures and harness | Drafted | 17 fixtures, 24 tests |
| Scenario/parity trace | Partial | Obligations mapped; concrete walkthroughs open |
| Version-1 immutable contract | Not started | Blocked by decisions, reviews, and cross-API ports |

## Checklist

- [x] Candidates are generic immutable references
- [x] Randomized display order never changes candidate identity
- [x] Blinded candidates hide raw model/provider identity
- [x] Response choice is one of the presented candidates
- [x] Version-0 schemas, fixtures, and semantic harness pass
- [ ] Exact command payload/result/view schemas for every command and query
- [ ] Accountable owner and four reviewers assigned
- [x] Typed task set (`Compare.pairwise`/`Compare.rating`) reflected in schemas (F-3)
- [x] Inline in-chat elicitation contract defined with API-08 (candidate replies, continue-with-choice, unchosen-branch retention)
- [ ] Query generation, watch history, revision, and adjudication defined
- [ ] Reward-model-oriented exporters and lineage defined with API-19
- [ ] Blinded-handle audience/lifetime policy defined with API-03
- [ ] NS-01/NS-02/NS-10 walkthroughs pass
- [ ] Dependent ADRs accepted; four sign-offs recorded; version-1 bytes frozen

## Open decision log

| ID | Decision needed | Proposed default | Blocks |
| --- | --- | --- | --- |
| A18-O01 | Blinded handle audience and non-linkability | Per-audience handle; not linkable across audiences (shared PublicHandle policy) | ['API-03'] |
| A18-O02 | Response revision and resume | Durable response with explicit revision; resume reloads presented order | ['Version 1'] |
| A18-O03 | Adjudication and disagreement | Multiple responses adjudicated by an authored rule; disagreement recorded | ['Version 1'] |

## Required sign-off

| Review | Reviewer | Decision | Date | Focus |
| --- | --- | --- | --- | --- |
| Domain/scientific validity | Unassigned | Pending | — | Candidate/blinding/adjudication semantics |
| Runtime/distributed systems | Unassigned | Pending | — | Persistence-before-progression, resume, revision |
| Data/replay | Unassigned | Pending | — | Export lineage and reward-model shapes |
| Security/privacy | Unassigned | Pending | — | Blinding leakage, handle non-linkability |

## Change log

| Date | Revision | Change |
| --- | --- | --- |
| 2026-07-17 | `0.1` | Opened API-18: preference-protocol, candidate-ref, assignment, response, quality-evidence schemas, blinding, display-order integrity, choice-is-presented, 10 fixtures, 14 tests |
| 2026-07-18 | `0.2 (docs)` | Folded user-surface-review decisions (docs only; schema bundle remains `0.1` pending re-draft): typed pairwise+rating task set, per-presentation blinding/order recording, candidate sources, inline in-chat elicitation |
| 2026-07-19 | `0.2` | Re-drafted the schema bundle to the 0.2 docs: typed `ComparisonTask` closed set pairwise+rating with optional prompt (F-3, D12-3; `ranking` retired); per-presentation blinding/order recording — `randomize_order` on the protocol, `blinded` recorded on the assignment (D12-4); response records the shown `presented_order` (replacing the `presented` boolean) with semantic choice-is-presented enforcement (D12-5); fixtures conformed to shared-kernel 0.2 `data_handling` (retention_policy and retired ids removed); 6 valid + 6 invalid fixtures, 17 tests; bundle digests restamped |
| 2026-07-27 | `0.3` | Opened the response beyond one bit for the inline elicitation W19 needs (D12-8, D12-9): `PreferenceResponse.verdict` (`choice`/`tie`/`both-bad`, absent means `choice`) so a tie is recordable without a phantom choice, with `choice` retained under a tie as the candidate the response resolves to; `ComparisonTask.allow_tie` so an absent tie is readable as "none offered" rather than "none chosen"; and per-dimension annotation -- `ComparisonTask.dimensions` (`Dimension`: `scope` `pair`/`each`, `points` 1..10, scale end labels) with `PreferenceResponse.ratings` (`DimensionRating`: `dimension_key`, optional `candidate_key`, `value`), where a rating names a candidate key and never a screen position and the zero value is the midpoint that favours neither. Every added field is optional, so every 0.2 record stays valid. 5 fixtures added (17 total), 24 tests; bundle digest `717b95bd…`; freeze ledger rebuilt |

## Folded decisions (2026-07-18)

Applied from the approved user-surface review (`scratch/phase0-review/DECISIONS.md`):

- **D12-3** — Preference/annotation is a first-class activity over immutable
  candidate references; v0 comparison tasks are pairwise + rating
  (`Compare.pairwise(...)`, `Compare.rating(...)`); candidate sources include
  model generations, trajectory slices (API-16), and chat messages (API-08).
- **D12-4** — Blinding (`blind=True`) and order randomization
  (`randomize_order=True`) are recorded per presentation and never change
  candidate identity.
- **D12-5** — A recorded choice must be one of the presented candidates, with
  the display order that was shown.
- **D12-8** — Inline in-chat elicitation (with API-08): two candidate replies
  are presented mid-chat, the choice is recorded, and the conversation
  continues with the selected reply; the unchosen branch is retained as data.
- **F-3** — Comparison tasks and options are typed constructors, never magic
  strings.

## New decisions (2026-07-27)

- **D12-9** — **A comparison is answered on more than one axis.** A protocol may
  declare dimensions beside the overall preference, and each is answered either
  once over the presented set (`scope="pair"` -- which reply is more helpful) or
  once for each candidate (`scope="each"` -- how verbose each reply is). A
  dimension with one point is a plain pick; more than one point is a Likert scale.
  *Why it matters:* one preference bit can not separate "more helpful" from "more
  agreeable", and multi-attribute preference data is what a steerable reward model
  needs. *Recorded shape:* a rating names the **candidate key** it is about and
  never a screen position, so a randomized display order can not invert a
  dimension; the zero value names no candidate and is the midpoint that favours
  neither.
- **D12-10** — **A tie is recordable, and it is still resolved.** `verdict` says
  what the participant meant (`choice`, `tie`, `both-bad`) and `choice` says which
  candidate the response resolved to. In a live conversation the thread has to go
  on with one reply whatever the judgement was, so the two are separate facts and
  both are kept. `allow_tie` on the task records whether a tie was on offer.
