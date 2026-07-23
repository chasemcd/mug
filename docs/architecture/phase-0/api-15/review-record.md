# API-15 Review Record

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
| Version-0 schemas | Drafted | `memory.schema.json` |
| Golden fixtures and harness | Drafted | 11 fixtures, 15 tests |
| Scenario/parity trace | Partial | Obligations mapped; concrete walkthroughs open |
| Version-1 immutable contract | Not started | Blocked by decisions, reviews, and cross-API ports |

## Checklist

- [x] Reads are immutable snapshots at a base version
- [x] Writes are compare-and-swap against the exact read base
- [x] A commit advances the version by exactly one
- [x] Treatment mode isolates memory across actors and conditions
- [x] Version-0 schemas, fixtures, and semantic harness pass
- [ ] Exact command payload/result/view schemas for every command and query
- [ ] Accountable owner and four reviewers assigned
- [ ] Search, summarization, and eviction semantics defined
- [x] Typed `MemoryScope`/`MemoryMode` vocabularies reflected in schemas (F-3; `MemoryScopeName`/`MemoryModeName` named definitions in the 0.2 bundle)
- [ ] Stale-decision rejection fault injection passes
- [ ] NS-03 through NS-08 and NS-11 walkthroughs pass
- [ ] Dependent ADRs accepted; four sign-offs recorded; version-1 bytes frozen

## Open decision log

| ID | Decision needed | Proposed default | Blocks |
| --- | --- | --- | --- |
| A15-O01 | Stale-decision memory rejection | A decision whose base version moved cannot commit; it fails closed | ['API-12'] |
| A15-O02 | Longitudinal memory retention/deletion | Ungated: the researcher handles retention/deletion against their own store (self-hosted; ADR-0015), reconciled with immutable provenance | ['ADR 0015'] |
| A15-O03 | Treatment ablation | Ablated mode presents empty memory without leaking that ablation occurred | ['Version 1'] |

## Required sign-off

| Review | Reviewer | Decision | Date | Focus |
| --- | --- | --- | --- | --- |
| Domain/scientific validity | Unassigned | Pending | — | Memory scope and treatment semantics |
| Runtime/distributed systems | Unassigned | Pending | — | Compare-and-swap, staleness, conflict, recovery |
| Data/replay | Unassigned | Pending | — | Provenance, retention, archival readability |
| Security/privacy | Unassigned | Pending | — | Cross-actor/treatment isolation |

## Change log

| Date | Revision | Change |
| --- | --- | --- |
| 2026-07-17 | `0.1` | Opened API-15: memory scope/read/proposal/commit schemas, compare-and-swap, monotonic version, provenance, treatment modes, 9 fixtures, 14 tests |
| 2026-07-18 | `0.2 (docs)` | Folded user-surface-review decisions (docs only; schema bundle remains `0.1` pending re-draft): memory as experimental treatment with typed scope/mode vocabularies; API-20 retention/deletion coupling removed |
| 2026-07-19 | `0.2` | Re-drafted the schema bundle to the 0.2 docs: `MemoryScope`/`MemoryMode` closed vocabularies hoisted to named definitions (`MemoryScopeName`, `MemoryModeName`) referenced by every record (F-3, D11-6); record shapes, CAS/provenance/monotonic-version rules unchanged from 0.1 (already conforming); no retention/`data_handling` coupling (F-4/ADR-0015, shared-kernel 0.2); 11 fixtures, 15 tests |

## Folded decisions (2026-07-18)

Applied from the approved user-surface review (`scratch/phase0-review/DECISIONS.md`):

- **D11-6** — Memory is an experimental treatment:
  `Memory(scope=MemoryScope.EPISODIC, mode=MemoryMode.ISOLATED)`; treatment mode
  (shared/isolated/ablated) makes memory an isolated experimental variable.
- **F-3** — `MemoryScope` and `MemoryMode` are typed closed vocabularies; no
  magic strings in illustrative code or schemas.
- **F-4 / ADR-0015** — Retention/deletion are not an API-20 workflow: ungated,
  researcher-owned store (self-hosted); API-20 removed from Consumers/Depends.
