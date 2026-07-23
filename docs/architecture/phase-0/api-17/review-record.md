# API-17 Review Record

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
| Version-0 schemas | Drafted | `content.schema.json` |
| Golden fixtures and harness | Drafted | 23 fixtures, 26 tests |
| Scenario/parity trace | Partial | Obligations mapped; concrete walkthroughs open |
| Version-1 immutable contract | Not started | Blocked by decisions, reviews, and cross-API ports |

## Checklist

- [x] Form field keys are unique
- [x] Progression-gating responses require a durable receipt
- [x] Components declare an accessibility profile with an enforced WCAG floor
- [x] Accessibility and technical-problem paths are first-class
- [x] Version-0 schemas, fixtures, and semantic harness pass
- [x] RP-8 readiness decision recorded: trusted custom-page code gains a typed
      `mug.gate` operation to block/unblock advance or interaction join
- [x] Fold RP-8 into the 0.3 component/bridge contract, exact wire schemas,
      semantic rules, accessibility behavior, and fixtures: `GateControl` typed
      readiness content component (gate target advance/join, gate action
      block/unblock, interaction/flow anchor, accessibility profile) pinning the
      inert API-09 `mug.api-09.gate-op` bundle it emits; the two RP-8 open
      sub-items (state→env-args resolution, read-only participant handle) remain
      open
- [ ] Exact command payload/result/view schemas for every command and query
- [ ] Accountable owner and four reviewers assigned
- [x] Typed field-type set (likert/choice/text/number/slider/rating) reflected in schemas (F-3)
- [ ] Answer schema, validation, and revision semantics defined
- [ ] Remaining realtime component command contract beyond the settled
      `mug.gate` policy, coordinated with API-09
- [ ] Technical-problem and accessibility acceptance plan completed
- [ ] NS-01/NS-02/NS-10 walkthroughs pass
- [ ] Dependent ADRs accepted; four sign-offs recorded; version-1 bytes frozen

## Open decision log

| ID | Decision needed | Proposed default | Blocks |
| --- | --- | --- | --- |
| A17-O01 | Answer payload schema and validation | Domain-owned typed answer schema resolved and validated before receipt | ['API-01'] |
| A17-O02 | Receipt-before-progression enforcement | Client cannot advance until a durable response receipt is acknowledged | ['API-09'] |
| A17-O03 | Accessibility acceptance testing | Automated and manual WCAG-AA checks in the conformance plan | ['Version 1'] |
| A17-O04 | Content body sourcing | Settled 2026-07-19: repo file or inline, Markdown or HTML (`Content.file/markdown/html`), compiled into the immutable version as a content-addressed `PresentationArtifact`; never bound at deploy. Author HTML (with CSS/JS) is explicit trusted study code; model/participant output never implicitly executable | — |
| A17-O05 | Custom-page response capture | Settled 2026-07-19: typed `window.mug` bridge only (`mug.response.set/get`, `mug.state.get/set`, `mug.advance()`) plus auto-collection of named form controls; `mugGlobals` retired. Responses are schema-bound, idempotent, durable-receipt-gated (D12-2), and addressable downstream via `activity.field(...)` | ['API-09'] |

## Settled runtime-parity input for revision 0.3

RP-8 adds the typed `mug.gate` readiness operation to the trusted custom-page
bridge. It replaces start/advance-button polling hacks by letting page code
block or release advance/join explicitly. **Folded in revision 0.3** on the
API-17 (content/UI) side as the `GateControl` typed readiness content component
that surfaces the gate and drives the API-09 `GateOp`; API-09 owns the op itself
(`mug.api-09.gate-op`, pinned here as an inert foreign ref). The two RP-8
sub-items — the state→env-args resolution path and the read-only participant
handle — were **not** adopted and remain open.

## Folded runtime-parity decisions in revision 0.3

| Decision | Settled input |
| --- | --- |
| RP-8 | API-17 owns the content/UI side of the readiness gate: a first-class `GateControl` content component (start/advance control) declaring its gate target (advance vs join), gate action (block/unblock), and the interaction/flow anchor it gates, carrying an accessibility profile like any shipped component, and pinning the inert API-09 `mug.api-09.gate-op` bundle (`a687a135…`) it emits. API-09 owns `GateOp`. RP-8's state→env-args resolution path and read-only participant handle were not adopted and stay open. |

## Required sign-off

| Review | Reviewer | Decision | Date | Focus |
| --- | --- | --- | --- | --- |
| Domain/scientific validity | Unassigned | Pending | — | Form/presentation semantics and revision |
| Runtime/distributed systems | Unassigned | Pending | — | Receipt-before-progression, refresh safety |
| Data/replay | Unassigned | Pending | — | Answer schemas and export lineage |
| Security/privacy | Unassigned | Pending | — | Accessibility, safe rendering, technical paths |

## Change log

| Date | Revision | Change |
| --- | --- | --- |
| 2026-07-17 | `0.1` | Opened API-17: form-spec/response, presentation-component, accessibility-profile schemas, unique fields, receipt-before-progression, WCAG floor, 9 fixtures, 13 tests |
| 2026-07-18 | `0.2 (docs)` | Folded user-surface-review decisions (docs only; schema bundle remains `0.1` pending re-draft): typed field-type closed set (core + slider/rating), durable gating receipt, WCAG floor for shipped components, consent as ordinary content+form activity |
| 2026-07-19 | `0.2` | Re-drafted the schema bundle to the 0.2 docs: typed field-type closed set (likert/choice/text/number/slider/rating) with labels/options/scale (F-3, D12-1); new `ContentSpec`/`ContentBody` encoding R-12 content bodies — source (file/inline), format (markdown/html), content digest for file bodies — and the origin/executable trust boundary (author HTML explicit trusted study code; model/participant content inline-only, never executable) per A17-O04; `response_required` gating on content (A17-O05, D12-2); retired 0.1 field kinds `single-choice`/`multi-choice`; 8 valid + 10 invalid fixtures, 21 tests; bundle digests restamped |
| 2026-07-20 | `0.3 input (docs)` | Recorded settled RP-8 `mug.gate` readiness operation; exact API-09/17 contract/schema/fixture fold remains pending |
| 2026-07-20 | `0.3` | Folded RP-8 (content/UI side) into exact bytes: `GateControl` typed readiness content component (`gate_target` advance/join, `gate_action` block/unblock, interaction/flow `anchor`, accessibility profile) with a `gateAnchorMismatch` semantic anchor/target-coherence rule; pins the inert API-09 `mug.api-09.gate-op` bundle (`a687a135…`) it emits without adding it to the family bundle; the two RP-8 sub-items stay open. Bundle digest `63d88932…`; 23 fixtures, 26 tests; family bundle self-pins restamped |

## Folded decisions (2026-07-18)

Applied from the approved user-surface review (`scratch/phase0-review/DECISIONS.md`):

- **D12-1** — Forms are a declarative typed activity with default accessible
  widgets; the field-type closed set is core (likert/choice/text/number) plus
  slider and rating — `Field.likert(...)`, `Field.choice(...)`,
  `Field.text(...)` etc. (ranking/matrix/upload deferred).
- **D12-2** — A progression-gating response requires a durable receipt before
  the flow advances.
- **D12-6** — Shipped components carry an enforced WCAG accessibility floor
  (AA ⇒ keyboard navigation + screen-reader support), distinct from the
  deferred game-input a11y work.
- **ADR-0014 (F-2/D04-3)** — Consent is a content+form flow activity recorded
  like any response; no special consent record or wave mechanism.
- **F-3** — Typed field constructors are MUG vocabulary; author-defined keys,
  labels, and options remain plain strings.
