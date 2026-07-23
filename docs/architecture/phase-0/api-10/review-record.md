# API-10 Review Record

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
| Version-0 schemas | Drafted | `evidence.schema.json` |
| Golden fixtures and harness | Drafted | 17 fixtures, 23 tests |
| Scenario/parity trace | Partial | Obligations mapped; concrete walkthroughs open |
| Version-1 immutable contract | Not started | Blocked by decisions, reviews, and cross-API ports |

## Checklist

- [x] Immutable schema-versioned event envelope with producer epoch/sequence/digest
- [x] Producer positions monotonic within an epoch; causation explicit
- [x] Canonical and experienced streams are distinct profiles
- [x] Capture policy declares per-stream capture profile; no retention
      declarations anywhere (retention is the researcher's own DB concern,
      ADR-0015)
- [x] Secret is never a research-data privacy label
- [x] Version-0 schemas, fixtures, and semantic harness pass
- [x] `0.2` schema/fixture re-draft encoding the folded decisions:
      `CaptureStreamRule` drops its `retention` reference (ADR-0015; the shared
      kernel retired `RetentionPolicyRef`), `data_handling` is privacy labels
      only, and invalid fixtures prove retention declarations are rejected on
      both the envelope and the capture policy; capture semantics themselves
      unchanged (D08-6, D05-6)
- [x] RP-9 scope decision recorded: the experienced stream captures frames as
      rendered with delivered/speculative/corrected/skipped delivery kinds,
      alongside post-rollback canonical truth
- [x] Fold RP-9's full-fidelity scope into the 0.3 contract, exact capture
      schemas, semantic/completeness rules, and fixtures: the experienced stream
      classifies every rendered frame as `delivered`/`speculative`/`corrected`/
      `skipped`, each `ExperiencedFrame` is joinable to its canonical frame via
      `canonical_event_id` (a `corrected` frame additionally records the
      speculative `supersedes_experienced_position` it replaced), and a
      dual-stream `CapturePolicy` captures both streams under the
      `experiencedRequiresCanonical` and `correctedRequiresCanonical` semantic
      rules
- [ ] Exact command payload/result/view schemas for every command and query
- [ ] Accountable owner and four reviewers assigned
- [ ] Stream append, cursor, and compaction semantics defined with API-11
- [ ] Backpressure, buffering, and degraded-capture behavior defined
- [ ] Cursor expiry after researcher-side removal defined (removal itself is the researcher's own DB operation; ungated, self-hosted; ADR-0015)
- [ ] All north-star scenarios traced for evidence completeness
- [ ] Dependent ADRs accepted; four sign-offs recorded; version-1 bytes frozen

## Open decision log

| ID | Decision needed | Proposed default | Blocks |
| --- | --- | --- | --- |
| A10-O01 | Append durability profiles | Deployment-pinned named durability; high-rate ingress declares weaker receipts | ['API-11'] |
| A10-O02 | Compaction vs removal | Ordinary compaction preserves bytes/positions; removal is a researcher-side DB operation outside the platform (self-hosted; ADR-0015), and only such removal expires cursors | ['API-11'] |
| A10-O03 | Metrics vs canonical evidence | Operational telemetry is separate from canonical evidence and never analysis input | ['ADR 0006'] |

## Settled runtime-parity input for revision 0.3

RP-9 chooses the full experienced-stream profile: retain canonical
post-rollback truth and the participant-experienced frames as rendered, labeled
`delivered`, `speculative`, `corrected`, or `skipped`. The scope choice is
settled. **Folded into the 0.3 bundle on 2026-07-20** (see "Folded
runtime-parity decisions in revision 0.3" below): exact experienced/canonical
linkage, corrected-supersession lineage, dual-stream capture, and the
`experiencedRequiresCanonical` / `correctedRequiresCanonical` semantic checks are
now proven by the schema bundle, semantic harness, and fixtures. Degraded-
completeness behavior and privacy/size policy remain out of this fold.

## Folded runtime-parity decisions in revision 0.3

| Decision | Settled input |
| --- | --- |
| RP-9 | Both streams are captured: the canonical post-rollback truth and the experienced stream of frames exactly as rendered, classified by `ExperiencedFrame.delivery_kind` ∈ {`delivered`, `speculative`, `corrected`, `skipped`}. Every experienced frame joins to the canonical stream through `canonical_event_id`; a `corrected` frame also records the `supersedes_experienced_position` of the speculative frame it replaced and must carry the canonical linkage (`correctedRequiresCanonical`). A `CapturePolicy` declares dual-stream capture, and capturing the experienced stream requires capturing the canonical stream (`experiencedRequiresCanonical`). |

## Required sign-off

| Review | Reviewer | Decision | Date | Focus |
| --- | --- | --- | --- | --- |
| Domain/scientific validity | Unassigned | Pending | — | Occurrence identity, canonical/experienced meaning |
| Runtime/distributed systems | Unassigned | Pending | — | Append durability, ordering, backpressure |
| Data/replay | Unassigned | Pending | — | Schemas, cursors, archival readability |
| Security/privacy | Unassigned | Pending | — | Privacy classification and redaction |

## Change log

| Date | Revision | Change |
| --- | --- | --- |
| 2026-07-17 | `0.1` | Opened API-10: event-envelope, capture-policy, experienced-frame schemas, canonical/experienced separation, producer monotonicity, 9 fixtures, 14 tests |
| 2026-07-18 | `0.2 (docs)` | Folded user-surface-review decisions (docs only; schema bundle stays `0.1`): API-10 framed as the sole home of immutable capture for reproducibility, not an audit trail; API-20 references removed (ADR-0015) |
| 2026-07-19 | `0.2` | Re-drafted the schema bundle to the `0.2` docs: `CaptureStreamRule` drops `retention` (retention/deletion are researcher-side DB operations, ADR-0015; shared kernel `RetentionPolicyRef` retired), fixtures cleaned of `retention_policy` inside `data_handling` (shared kernel 0.2 closed `DataHandlingRef` to privacy labels only) and of retired `retpolicy_`/`retpolicyver_` identifiers; envelope, experienced-frame, and canonical/experienced capture semantics unchanged (D08-6, D05-6); two new invalid fixtures prove retention declarations are rejected; 11 fixtures (4 valid, 7 invalid), 15 tests; bundle digests restamped |
| 2026-07-20 | `0.3 input (docs)` | Recorded settled RP-9 full experienced-stream scope; exact contract/schema/fixture fold remains pending |
| 2026-07-20 | `0.3` | Folded RP-9 into exact bytes: `ExperiencedFrame` gains `supersedes_experienced_position` (the speculative frame a `corrected` frame replaces), keeping the four-value `delivery_kind` enum and the `canonical_event_id` canonical linkage; new `correctedRequiresCanonical` and `experiencedRequiresCanonical` semantic rules; new fixtures cover every delivery kind, a dual-stream `CapturePolicy`, a corrected frame missing its canonical linkage, and experienced-without-canonical capture; 17 fixtures (8 valid, 9 invalid), 23 tests; bundle digest restamped to `f8d8da4c…` |

## Folded decisions (2026-07-18/19)

Approved user-surface-review decisions applied to this family's docs
(schema/fixture re-draft landed at `0.2` on 2026-07-19):

| ID | Applied as |
| --- | --- |
| F-4 / ADR-0015 | Governance out of scope: API-10 is explicitly not an admin audit trail; it is the sole home of immutable event capture for reproducibility. API-20 removed from Consumers and open decisions; retention/deletion are the researcher's own DB operations in a self-hosted install |
| D08-6 | Every action/message is a normalized recorded event — an invisible guarantee enabling replay/export with no author effort; capture semantics unchanged |
| D05-6 | Capture guarantees unchanged for participants: durable receipt still means "your response was saved"; offline tolerance is an authoring knob elsewhere, not a capture change |
