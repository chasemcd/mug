# API-19 Review Record

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
| Version-0 schemas | Drafted | `export.schema.json` |
| Golden fixtures and harness | Drafted | 15 fixtures, 18 tests |
| Scenario/parity trace | Partial | Obligations mapped; concrete walkthroughs open |
| Version-1 immutable contract | Not started | Blocked by decisions, reviews, and cross-API ports |

## Checklist

- [x] Every export bundle carries a lineage record naming sources
- [x] Redacted/aggregated exports are new lineage-bearing objects
- [x] Every dataset kind binds an exact row schema
- [x] Exports retain complete lineage
- [x] Version-0 schemas, fixtures, and semantic harness pass
- [ ] Exact command payload/result/view schemas for every command and query
- [ ] Accountable owner and four reviewers assigned
- [x] JSONL single-format binding and typed `Dataset` vocabulary reflected in schemas (F-3; re-drafted `0.2`)
- [ ] Lineage manifest to study version + git provenance defined with API-01 (ADR-0013)
- [ ] Query language, filters, and pagination defined
- [ ] Reward-model and external-annotation exporters defined with API-18
- [ ] Redaction/derivation policy defined (export is ungated; ADR-0015)
- [ ] NS-01/NS-02/NS-08/NS-12 walkthroughs pass
- [ ] Dependent ADRs accepted; four sign-offs recorded; version-1 bytes frozen

## Open decision log

| ID | Decision needed | Proposed default | Blocks |
| --- | --- | --- | --- |
| A19-O01 | Redaction and derived exports | Export is ungated (ADR-0015); redaction produces a new lineage-bearing export object with its own policy, never a rewrite of source evidence | ['Version 1'] |
| A19-O02 | Row schema stability | Exported row schemas are versioned and content-addressed | ['Version 1'] |
| A19-O03 | External annotation integration | Behind a MUG-owned contract; results re-imported as lineage-bearing artifacts (no plugin system in v0 — API-21 retracted; ADR-0015) | ['Version 1'] |
| A19-O04 | Live vs batch export | Settled 2026-07-18: export is a **batch, re-runnable snapshot** — running mid-study exports everything recorded so far, consistent as of the snapshot; no streaming/follow mode in v0 | — |

## Required sign-off

| Review | Reviewer | Decision | Date | Focus |
| --- | --- | --- | --- | --- |
| Domain/scientific validity | Unassigned | Pending | — | Dataset semantics and lineage completeness |
| Runtime/distributed systems | Unassigned | Pending | — | Query execution, pagination, incremental export |
| Data/replay | Unassigned | Pending | — | Row schemas, JSONL archival readability |
| Security/privacy | Unassigned | Pending | — | Redaction and re-identification defense (export ungated; ADR-0015) |

## Change log

| Date | Revision | Change |
| --- | --- | --- |
| 2026-07-17 | `0.1` | Opened API-19: export request/bundle, lineage-record, dataset-schema-binding schemas, complete-lineage rule, redaction-as-new-object, 9 fixtures, 12 tests |
| 2026-07-18 | `0.2 (docs)` | Folded user-surface-review decisions (docs only; schema bundle remains `0.1` pending re-draft): JSONL single format, typed `Dataset` vocabulary, lineage to study version + git provenance, redaction-as-new-object, export ungated |
| 2026-07-19 | `0.2` | Re-drafted the schema bundle to the 0.2 docs: closed 4-kind `Dataset` vocabulary (F-3; `normalized` retired), format field removed with the artifact pinned to `application/x-ndjson` (D13-1), lineage record extended to study version + git provenance with dirty-patch conditional (D13-2/ADR-0013), batch re-runnable snapshot encoded as `snapshot_at` + deterministic `bundle_digest` + input refs on the bundle (R-11/A19-O04), derived-export source rule for redacted/aggregated lineage (D13-3), shared-kernel 0.2 `data_handling` (privacy labels only; no retention policy — ADR-0015/NS-12); 15 fixtures, 18 tests |

## Folded decisions (2026-07-18)

Applied from the approved user-surface review (`scratch/phase0-review/DECISIONS.md`):

- **D13-1** — JSONL is the single export format; Parquet/CSV/derived-format
  language removed; nested/variable data is nested JSON; every dataset kind is
  a typed `Dataset` constant (`Dataset.TRAJECTORIES` etc.) bound to an exact
  row schema.
- **D13-2** — Every export carries a complete lineage manifest back to the
  study version and its git provenance (ADR-0013).
- **D13-3** — Redaction/aggregation produces a new derived export object with
  its own lineage; source evidence is never rewritten.
- **F-4 / ADR-0015** — Export is ungated: API-20 authority coupling removed
  from Consumers, checklist, decision log, and sign-off focus; access control
  belongs to the researcher's self-hosted store. API-21 reference retired (no
  plugin system in v0, retracted).
- **F-3** — `Dataset` is a typed closed vocabulary; no magic strings in
  illustrative code.
