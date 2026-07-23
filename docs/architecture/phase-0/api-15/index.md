# API-15: Experimental Agent Memory

| Field | Value |
| --- | --- |
| Status | Draft |
| Contract revision | `0.2` |
| Accountable owner | Unassigned |
| Last updated | 2026-07-19 |
| Consumers | API-12/13 (agents), API-08 (conversation), API-10 (provenance) |
| Depends on | [Shared kernel 0.1](../shared-kernel/index.md), [API-12 0.1](../api-12/index.md), proposed ADRs 0009, 0011 (security half), 0015 |
| Implementation phase | Phase 4 |
| Stability tiers | Application command/query, archival |

## Outcome

API-15 makes agent memory an **experimental treatment**: working, episodic, and
longitudinal scopes with explicit treatment modes, both declared as **typed
closed vocabularies** (F-3). Reads are immutable snapshots; writes are
compare-and-swap carrying provenance. A stale or rejected decision can never
commit memory, and treatment isolation holds across actors and conditions.

```python
memory = Memory(scope=MemoryScope.EPISODIC, mode=MemoryMode.ISOLATED)
```

`MemoryScope` (`WORKING` / `EPISODIC` / `LONGITUDINAL`) and `MemoryMode`
(`SHARED` / `ISOLATED` / `ABLATED`) are closed, typed sets — never bare strings.

## Ownership boundary

API-15 owns `MemoryScope`, `MemoryRead`, `MemoryProposal`, and `MemoryCommit`.
Decisions come from API-12/13; durable conversation history is API-08. Retention
and deletion of memory data are ungated and handled by the researcher against
their own store (self-hosted; ADR-0015).

## Non-negotiable memory boundary

1. Reads are immutable snapshots at a base version.
2. Writes are compare-and-swap against the exact read base, carrying provenance.
3. A commit advances the version by exactly one; a stale base cannot commit.
4. Treatment mode (`MemoryMode.SHARED` / `ISOLATED` / `ABLATED`) isolates memory
   across actors and conditions — memory is an isolable experimental variable.

## Current executable evidence

- 5 valid and 6 one-defect invalid examples; 15 API-15 tests including monotonic
  version advance and commit-matches-proposal-base. The `MemoryScope`/`MemoryMode`
  closed vocabularies are named schema definitions (`MemoryScopeName`,
  `MemoryModeName`) referenced by every record (F-3).

## Acceptance status

`Drafted`, not `Accepted`. See the [review record](review-record.md).
