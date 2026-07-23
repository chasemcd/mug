# API-08: Conversation, Routing, History, Streaming, and Delivery

| Field | Value |
| --- | --- |
| Status | Draft |
| Contract revision | `0.2` |
| Accountable owner | Unassigned |
| Last updated | 2026-07-19 |
| Consumers | API-06 (chat channels), API-09 (delivery), API-12/13 (model activation), API-18 (inline preference), API-10/16 (evidence/replay) |
| Depends on | [Shared kernel 0.1](../shared-kernel/index.md), [API-06 0.1](../api-06/index.md), proposed ADRs 0002, 0010 |
| Implementation phase | Phase 3D |
| Stability tiers | Wire, archival |

## Outcome

API-08 defines deterministic conversation: totally ordered chat messages,
idempotent submission, delivery evidence, per-channel turn/activation policy that
prevents model activation loops, and the exact context snapshot captured for each
model request so a conversation can be replayed exactly.

A default chat widget ships with the platform: `Chat(key="talk")` yields a
working UI (input box, scrolling transcript, streaming display) with zero UI
code; custom presentation is an override, never a prerequisite (D10-7).
Model replies stream; streaming deltas are **experienced-delivery evidence**
(what the participant actually saw arrive), distinct from the canonical
accepted message (D10-5, API-10).

Preference elicitation can occur inline within a live conversation (D12-8):
the model produces `n` candidate replies for a turn
(`Chat(elicit_preference=Compare.pairwise(n=2))`), the participant's choice is
recorded as an API-18 preference response, and the conversation continues with
the selected reply. The unchosen candidate is retained as recorded data;
candidate generation is turn-bounded like any activation.

## Ownership boundary

API-08 owns `ChatMessage`, `ConversationSegment`, `ContextSnapshot`,
`TurnPolicy`, `DeliveryReceipt`, and inline candidate-reply capture (the
candidate messages a turn produced and which one continued the thread).
Channel identity/membership is API-06; delivery transport is API-09; model
activation is API-12/13; the preference response elicited over inline
candidates is API-18.

## Authoring surface (illustrative)

```python
from mug import Chat, Compare

talk = Chat(key="talk")                          # default widget: working chat UI, zero UI code

assistant = Chat(
    key="assistant",
    respond_with=partner,                        # an immutable LLM agent version (API-13)
    elicit_preference=Compare.pairwise(n=2),     # inline A/B: pick is an API-18 response;
)                                                # chat continues with the chosen reply
```

## Non-negotiable conversation boundary

1. Chat messages are totally ordered by sequence and idempotent on submission.
2. A conversation segment's declared span equals its message count.
3. The exact context snapshot used for each model request is persisted.
4. Turn policy bounds model activations per turn to prevent activation loops;
   inline candidate generation counts against the same per-turn budget.
5. Streaming deltas are experienced-delivery evidence; the canonical message is
   the accepted, totally ordered one (canonical vs experienced, API-10).
6. An inline preference turn records every presented candidate reply; the
   conversation continues only with the participant-selected candidate, and the
   choice is recorded as an API-18 preference response.

## Current executable evidence

- 7 valid and 8 one-defect invalid examples; 19 API-08 tests including segment
  contiguity, context-snapshot capture, canonical vs experienced delivery
  evidence, and selected-candidate-must-be-presented enforcement.

## Acceptance status

`Drafted`, not `Accepted`. See the [review record](review-record.md).
