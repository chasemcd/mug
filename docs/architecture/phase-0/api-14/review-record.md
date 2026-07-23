# API-14 Review Record

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
| Version-0 schemas | Drafted | `tools.schema.json` |
| Golden fixtures and harness | Drafted | 13 fixtures, 16 tests |
| Scenario/parity trace | Partial | Obligations mapped; concrete walkthroughs open |
| Version-1 immutable contract | Not started | Blocked by decisions, reviews, and cross-API ports |

## Checklist

- [x] Optional human-approval gate: a mutating call under an author-declared gate executes only after approval
- [x] Executed results name evidence; effects are recorded
- [x] Tool versions are immutable and declare egress allowlists
- [x] Side effects execute at most as declared/approved (no grant system; ADR-0015)
- [x] Version-0 schemas, fixtures, and semantic harness pass
- [x] Folded `0.2` decisions reflected in schemas: author-declared `approval_gate` on tool versions, ungated mutating calls valid, `approvalGate` execution evidence; capability-grant vocabulary removed (ADR-0015)
- [ ] Exact command payload/result/view schemas for every command and query
- [ ] Accountable owner and four reviewers assigned
- [ ] MCP discovery, sandboxing, and execution isolation defined
- [ ] SSRF defenses, side-effect budgets, and emergency stop defined
- [ ] Replay tool-result substitution defined with API-16
- [ ] NS-07/NS-11/NS-12 walkthroughs pass
- [ ] Dependent ADRs accepted; four sign-offs recorded; version-1 bytes frozen

## Open decision log

| ID | Decision needed | Proposed default | Blocks |
| --- | --- | --- | --- |
| A14-O01 | Egress and SSRF policy | Deny-by-default egress allowlist with SSRF defenses; enforced mechanically at execution (no grant layer; ADR-0015) | ['Version 1'] |
| A14-O02 | Idempotency for side effects | Idempotency key with at-most-once external effect; unknown outcome is durable indeterminate | ['ADR 0009'] |
| A14-O03 | Emergency stop | A single control halts tool execution and agent activation immediately | ['API-12'] |

## Required sign-off

| Review | Reviewer | Decision | Date | Focus |
| --- | --- | --- | --- | --- |
| Domain/scientific validity | Unassigned | Pending | — | Tool gating and approval semantics |
| Runtime/distributed systems | Unassigned | Pending | — | Idempotency, unknown outcomes, cancellation |
| Data/replay | Unassigned | Pending | — | Result evidence and replay substitution |
| Security/privacy | Unassigned | Pending | — | Egress, sandboxing, side-effect budgets, emergency stop |

## Change log

| Date | Revision | Change |
| --- | --- | --- |
| 2026-07-17 | `0.1` | Opened API-14: tool-version/call/approval/result, environment-command-mailbox schemas, approval-before-mutation, egress allowlist, execution evidence, 10 fixtures, 14 tests |
| 2026-07-18 | `0.2 (docs)` | Folded user-surface-review decisions (docs only; schema bundle remained `0.1` pending re-draft): native + MCP tools, optional approval gate, replay substitution, API-20 coupling removed |
| 2026-07-19 | `0.2` | Re-drafted the schema bundle to the `0.2` docs: approval gate is optional and author-declared (`approval_gate` on `ToolVersion`; mutating calls without the gate are valid), gated execution names its approval (`approval_required`/`approval_digest` on `ToolResult`, `approvalGate` rule), `required_capabilities` grant vocabulary removed (ADR-0015), authorization language dropped from the bundle title; 13 fixtures, 16 tests; digests restamped |

## Folded decisions (2026-07-18)

Applied from the approved user-surface review (`scratch/phase0-review/DECISIONS.md`):

- **D11-5** — Tools are native Python **and** MCP (`Tool.mcp("search")`), both in
  v0; immutable tool versions with egress allowlists; human approval for
  mutating calls is an optional, author-declared gate; recorded tool results are
  substituted on exact replay (no live calls; API-16).
- **F-4 / ADR-0015** — No governance/grant system: MUG (not the model) gates
  tool effects mechanically, but authorization language and the API-20 coupling
  are removed (Consumers/Depends rows, decision-log blocks).
- **F-3** — Illustrative code uses typed constructors (`Tool.mcp(...)`), never
  magic strings for MUG vocabulary.
