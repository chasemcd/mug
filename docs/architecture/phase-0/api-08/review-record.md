# API-08 Review Record

| Field | Value |
| --- | --- |
| Status | Draft |
| Contract revision | `0.2` |
| Review opened | 2026-07-17 |
| Accountable owner | Unassigned |
| Target accepted version | `1` |

## Deliverable status

| Deliverable | Status | Evidence |
| --- | --- | --- |
| Ownership, lifecycles, and boundary | Drafted | [Index](index.md) |
| Version-0 schemas | Drafted | `conversation.schema.json` |
| Golden fixtures and harness | Drafted | 15 fixtures, 19 tests |
| Scenario/parity trace | Partial | Obligations mapped; concrete walkthroughs open |
| Version-1 immutable contract | Not started | Blocked by decisions, reviews, and cross-API ports |

## Checklist

- [x] Chat messages are totally ordered and idempotent
- [x] Conversation segment span equals its message count
- [x] Exact model-request context snapshot is persisted
- [x] Turn policy bounds per-turn model activations
- [x] Version-0 schemas, fixtures, and semantic harness pass
- [x] 0.2 re-draft in the schema bundle: inline candidate-reply capture
      (`CandidateReplySet`, D12-8) and canonical vs experienced delivery
      evidence (`DeliveryReceipt.evidence_stream`, D10-5)
- [ ] Exact command payload/result/view schemas for every command and query
- [ ] Accountable owner and four reviewers assigned
- [ ] Routing, visibility, and moderation policy defined
- [ ] Streaming presentation and delivery-evidence timing defined with API-09
- [x] Cross-modality anchors relate game and chat streams (no global clock) --
  built with W6. Causation is `EventEnvelope.causation_event_id`, which was frozen
  and never written: a reply now names the event of the message it answers. The
  environment step and render frame have no field on any frozen record, so they are
  a content-addressed anchor tape (`mug.conversation.anchors`) that the episode
  aggregate names beside its trajectory, checked against the run by
  `verify_anchors`. Channel sequence and the server monotonic anchor were already
  on `ChatMessage` and `EventEnvelope`. No global order is written anywhere.
- [ ] NS-02 through NS-07 walkthroughs pass
- [ ] Dependent ADRs accepted; four sign-offs recorded; version-1 bytes frozen

## Open decision log

| ID | Decision needed | Proposed default | Blocks |
| --- | --- | --- | --- |
| A08-O01 | Model activation loop prevention | Per-turn activation budget; a model reply cannot itself re-trigger unboundedly | ['API-12'] |
| A08-O02 | Message ordering authority | Server assigns total order per chat channel; clients never assert order | ['ADR 0010'] |
| A08-O03 | Moderation and visibility enforcement | Channel-membership visibility (API-06) with output escaping and safe rendering; ungated (self-hosted; ADR-0015) | ['API-06'] |

## Required sign-off

| Review | Reviewer | Decision | Date | Focus |
| --- | --- | --- | --- | --- |
| Domain/scientific validity | Unassigned | Pending | — | Conversation semantics, routing, context |
| Runtime/distributed systems | Unassigned | Pending | — | Ordering, idempotency, activation loops |
| Data/replay | Unassigned | Pending | — | History, context snapshots, replay readiness |
| Security/privacy | Unassigned | Pending | — | Visibility, moderation, output escaping |

## What W19 settles, and what it does not (2026-07-27)

**Settles.** `CandidateReplySet` has a producer. A live conversation now presents
`n` candidate replies for one turn, records the participant's choice as an API-18
response, continues the thread from the chosen reply, and keeps the unchosen branch
-- committed to the channel, delivered to nobody, and recorded as a durable
generation with its own private provenance. `ConversationChannel.candidate_set` is
the write; `mug/participant_elicit.py` and the chat mount drive it. D12-8 is
implemented as it was settled, with one departure recorded below.

**One rule carries the whole guarantee.** A candidate is posted through the
*channel* and handed to the *room* only if it is chosen. A message the room never
adopts is in no order, so no delivery, no flush, and no reconnection can reach it.
There is one enforcement point rather than two to keep in step, and a first
implementation's delivery-watermark guard was deleted once mutation testing showed
it guarded nothing.

**Departure from D12-8, deliberate.** The decision settled "sampled by default";
the built default elicits **every** turn, with `sample` as an author knob. Writing
`elicit_preference=` is already the opt-in, and a silent default that drops half of
a study's elicitations is a surprise a reader of the data cannot see. Which turns a
sampling study elicits is derived from the deployment secret and the prompt message,
so the rate is checkable against the record rather than trusted.

**Does not settle.** No adjudication and no multi-annotator agreement inside a
conversation (D12-7 stays as it was: several judgements are recordable, resolution
is deferred). No streaming of candidates as they generate -- a set is presented when
all of it is recorded. No re-elicitation of a turn already answered. And no owner
sign-off: this section is evidence, not review.

**No record, field, or fixture was added to API-08.** The bundle digest is
unchanged. The dimensional and tie surface this needed is API-18 revision 0.3.

## Change log

| Date | Revision | Change |
| --- | --- | --- |
| 2026-07-17 | `0.1` | Opened API-08: chat-message, conversation-segment, context-snapshot, turn-policy, delivery-receipt schemas, total ordering, segment contiguity, context capture, 10 fixtures, 14 tests |
| 2026-07-18 | `0.2 (docs)` | Folded user-surface-review decisions (docs only; schema bundle stays `0.1`): default chat widget, streaming-as-experienced-evidence, inline in-chat preference elicitation, API-20 reference removed |
| 2026-07-19 | `0.2` | Re-drafted the schema bundle to the 0.2 docs: `CandidateReplySet` (inline candidate-reply capture, D12-8 — presented candidates, selected reply, API-18 `prefresponse_` link, selected-must-be-presented semantic rule), `DeliveryReceipt.evidence_stream` (`canonical`/`experienced`, D10-5); conformed to shared-kernel 0.2 (no retired prefixes or `retention_policy` present); 15 fixtures, 19 tests; digests restamped |

## Folded decisions (2026-07-18)

Approved user-surface-review decisions applied to this family's docs
(schema/fixture re-draft landed 2026-07-19):

| ID | Applied as |
| --- | --- |
| D10-5 | Chat totally ordered + idempotent; model replies stream, turn-bounded; streaming deltas are experienced-delivery evidence distinct from the canonical accepted message |
| D10-7 | Platform ships a default chat widget — `Chat(key="talk")` is a working UI with zero UI code; custom presentation is an override |
| D12-8 | Inline in-chat preference: `Chat(elicit_preference=Compare.pairwise(n=2))` presents n candidate replies, the pick is an API-18 preference response, the thread continues with the chosen reply, the unchosen branch is retained as data; candidate generation is turn-bounded (D08-5) |
| F-3 | Illustrative Python uses typed constants (`Compare.pairwise(...)`), never magic strings |
| F-4 / ADR-0015 | API-20 reference removed from A08-O03; visibility/moderation is channel-membership plus safe rendering, ungated (self-hosted) |
