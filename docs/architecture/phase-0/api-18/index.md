# API-18: Preferences, Annotation, Quality, and Adjudication

| Field | Value |
| --- | --- |
| Status | Draft |
| Contract revision | `0.2` |
| Accountable owner | Unassigned |
| Last updated | 2026-07-19 |
| Consumers | Researchers, API-16 (trajectory/output candidates), API-08 (chat candidates, inline elicitation), API-17 (presentation), API-19 (export) |
| Depends on | [Shared kernel 0.1](../shared-kernel/index.md), [API-16 0.1](../api-16/index.md), [API-17 0.1](../api-17/index.md), proposed ADR 0006 |
| Implementation phase | Phase 3C |
| Stability tiers | Application command/query, archival |

## Outcome

API-18 elicits preferences over generic immutable candidates — **model
generations, trajectory slices, and chat messages/segments**. v0 comparison
tasks are a typed closed set: **pairwise and rating** (`Compare.pairwise(...)`,
`Compare.rating(...)` — F-3). Blinding and display-order randomization are
**recorded per presentation** and never change candidate identity; a
progression-gating response requires a durable receipt. Preference can also be
elicited **inline in a live chat** (with API-08).

```python
which_better = activities.Preference(
    key="cooperativeness",
    candidates=trajectory_slices,          # immutable references (API-16)
    task=Compare.pairwise(prompt="Which agent behaved more cooperatively?"),
    blind=True,                            # recorded per presentation
    randomize_order=True,                  # recorded per presentation; identity unchanged
)
```

Inline in-chat elicitation: mid-conversation, two candidate replies are
presented for the participant's message; the choice is recorded as a preference
and the chat continues with the selected reply — the unchosen branch is
retained as data (API-08).

## Ownership boundary

API-18 owns `PreferenceProtocol`, `CandidateRef`, `PreferenceAssignment`,
`PreferenceResponse`, and `QualityEvidence`. Candidate content lives in
API-16/08/17; export is API-19.

## Non-negotiable preference boundary

1. Candidates are generic immutable references (model generations, trajectory
   slices, chat messages/segments); display order is randomized but never
   changes candidate identity.
2. Blinded candidates are referenced by display handle; raw model/provider
   identity never appears in a candidate reference. Blinding and display order
   are recorded per presentation.
3. A response choice must be one of the presented candidates — no phantom or
   out-of-set choices.
4. A progression-gating response requires a durable receipt before advancing.
5. Inline in-chat elicitation reuses this same machinery: all candidate replies
   are recorded as candidates, the choice is a `PreferenceResponse`, and the
   selected reply continues the conversation (API-08).

## Current executable evidence

- 6 valid and 6 one-defect invalid examples; 17 API-18 tests including
  display-order uniqueness, no-raw-identity, choice-is-presented (with the
  display order that was shown), and the typed pairwise+rating task set.

## Acceptance status

`Drafted`, not `Accepted`. See the [review record](review-record.md).
