# API-19: Dataset Query, Export, Lineage, and External Annotation

| Field | Value |
| --- | --- |
| Status | Draft |
| Contract revision | `0.2` |
| Accountable owner | Unassigned |
| Last updated | 2026-07-19 |
| Consumers | Researchers/analysts, API-10/11 (evidence/artifacts), API-16 (bundles), API-18 (preferences) |
| Depends on | [Shared kernel 0.1](../shared-kernel/index.md), [API-10 0.1](../api-10/index.md), [API-11 0.1](../api-11/index.md), proposed ADRs 0004, 0006, 0013, 0015 |
| Implementation phase | Phase 1 onward |
| Stability tiers | Application command/query, archival |

## Outcome

API-19 defines dataset export with complete lineage: normalized event,
trajectory, preference, and conversation datasets in **one format — JSONL** —
each bound to an exact row schema and an immutable lineage record. Dataset kinds
are a **typed closed vocabulary** (`Dataset.EVENTS` / `Dataset.TRAJECTORIES` /
`Dataset.PREFERENCES` / `Dataset.CONVERSATIONS` — F-3). Every export carries a
lineage manifest back to the study version and its git provenance (ADR-0013). A
redacted or aggregated derivative is a **new lineage-bearing export object**,
never a rewrite of source evidence. Export is **ungated** (ADR-0015).

```python
ds = study.export(Dataset.TRAJECTORIES)   # JSONL — the single export format
ds.schema    # exact row schema
ds.lineage   # manifest back to study version + git provenance (ADR-0013)
```

## Ownership boundary

API-19 owns `ExportRequest`, `ExportBundle`, `LineageRecord`, and
`DatasetSchemaBinding`. Evidence and artifacts are API-10/11; replay bundles are
API-16. Export is ungated; access control is the researcher's own, against their
self-hosted store (ADR-0015).

## Non-negotiable export boundary

1. JSONL is the single export format; nested/variable data is nested JSON —
   there is no format menu (no Parquet/CSV/derived formats).
2. Every export bundle carries a lineage record naming its sources — a manifest
   back to the study version and its git provenance (ADR-0013); any row traces
   to the recorded evidence that produced it.
3. A redacted or aggregated export is a new lineage-bearing object; source
   evidence is never rewritten.
4. Every dataset kind — a typed `Dataset` vocabulary, never a magic string —
   binds an exact row schema.
5. Export is ungated (ADR-0015): no grant or authorization layer sits in front
   of it.

## Current executable evidence

- 5 valid and 10 one-defect invalid examples; 18 API-19 tests including
  lineage-source presence and the derived-export source rule.

## Acceptance status

`Drafted`, not `Accepted`. See the [review record](review-record.md).
