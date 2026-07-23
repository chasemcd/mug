# API-14: Tools, Approval, and Environment Commands

| Field | Value |
| --- | --- |
| Status | Draft |
| Contract revision | `0.2` |
| Accountable owner | Unassigned |
| Last updated | 2026-07-19 |
| Consumers | API-12 (scheduler), API-13 (agents), API-07 (environment commands), API-16 (replay substitution) |
| Depends on | [Shared kernel 0.1](../shared-kernel/index.md), [API-12 0.1](../api-12/index.md), proposed ADRs 0005, 0011 (security half), 0015 |
| Implementation phase | Phase 4 |
| Stability tiers | Application command/query, archival |

## Outcome

API-14 governs agent tool use: **native Python tools and MCP tools** — both
first-class in v0 — as immutable tool versions with egress allowlists, an
**optional human-approval gate** before mutating side effects, idempotent
execution, and environment-command mailboxes. MUG — not the model — gates tool
effects mechanically; there is **no governance/grant system** (ADR-0015). On
exact replay, recorded tool results are substituted and no live call is made
(API-16).

```python
tools = [Tool.mcp("search"), grab_tool]   # MCP + native Python; immutable tool versions
```

## Ownership boundary

API-14 owns `ToolVersion`, `ToolCall`, `ToolApproval`, `ToolResult`, and
`EnvironmentCommandMailbox`. Scheduling is API-12; provider calls are API-13;
replay substitution is API-16. There is no governance/grant layer around tool
use (ADR-0015) — gating is mechanical and in-family.

## Non-negotiable tool boundary

1. Tool versions are immutable and declare an egress allowlist.
2. Human approval is an optional, author-declared gate; a mutating call under
   that gate executes only after approval — MUG enforces this mechanically, the
   model never self-authorizes.
3. Executed results name their evidence; effects are recorded (none/mutating).
4. Side effects execute at most as declared/approved; stale decisions cannot
   commit them. No grant system exists (ADR-0015).
5. On exact replay, recorded tool results are substituted from the decision
   tape; no live tool call occurs (API-16).

## Current executable evidence

- 7 valid and 6 one-defect invalid examples; 16 API-14 tests including
  approval-gate and executed-result evidence.

## Acceptance status

`Drafted`, not `Accepted`. See the [review record](review-record.md).
