# API-11 Review Record

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
| Version-0 schemas | Drafted | `storage.schema.json` |
| Golden fixtures and harness | Drafted | 10 fixtures, 13 tests |
| Scenario/parity trace | Partial | Obligations mapped; concrete walkthroughs open |
| Version-1 immutable contract | Not started | Blocked by decisions, reviews, and cross-API ports |

## Checklist

- [x] Content-addressed staging; finalized digest equals intended digest
- [x] Unit of Work commits state, idempotency, event, and outbox atomically
- [x] Confirmed outbox records name their events
- [x] Acknowledgment durability is explicit
- [x] Version-0 schemas, fixtures, and semantic harness pass
- [x] Schema bundle re-drafted to the 0.2 docs: fixtures conform to shared-kernel 0.2 (`data_handling` carries privacy labels only; retention-policy metadata rejected on the durability surface; ADR-0015)
- [ ] Exact command payload/result/view schemas for every command and query
- [ ] Accountable owner and four reviewers assigned
- [ ] Repository and outbox SPI signatures finalized
- [ ] Artifact encryption, dedup scope, and garbage collection defined (ungated; deletion is a researcher-side DB operation, self-hosted; ADR-0015)
- [ ] Crash/retry fault injection at the Unit-of-Work and finalize points
- [ ] API-10 event and API-22 job integration reviewed
- [ ] Dependent ADRs accepted; four sign-offs recorded; version-1 bytes frozen

## Open decision log

| ID | Decision needed | Proposed default | Blocks |
| --- | --- | --- | --- |
| A11-O01 | Artifact digest exposure and dedup scope | Trusted/archival ref; the client-facing view may redact digests; no cross-policy dedup; ungated (self-hosted; ADR-0015) | ['Version 1'] |
| A11-O02 | Outbox delivery and confirmation | At-least-once dispatch with idempotent consumers; confirmation is durable | ['API-22'] |
| A11-O03 | Durability profiles | Deployment-pinned named failure model; high-rate ingress weaker | ['API-10'] |

## Required sign-off

| Review | Reviewer | Decision | Date | Focus |
| --- | --- | --- | --- | --- |
| Domain/scientific validity | Unassigned | Pending | — | Transaction/consistency semantics |
| Runtime/distributed systems | Unassigned | Pending | — | Unit-of-Work atomicity, outbox delivery, recovery |
| Data/replay | Unassigned | Pending | — | Artifact integrity, encryption, archival readability |
| Security/privacy | Unassigned | Pending | — | Artifact access, dedup, deletion |

## Change log

| Date | Revision | Change |
| --- | --- | --- |
| 2026-07-17 | `0.1` | Opened API-11: artifact staging/finalization, unit-of-work receipt, outbox record schemas, digest closure and outbox-evidence rules, 9 fixtures, 13 tests |
| 2026-07-18 | `0.2 (docs)` | Folded user-surface-review decisions (docs only; schema bundle stays `0.1`): family preserved as-is; API-20 references removed (ADR-0015); stored compiled StudyVersion artifact noted as a stored object class (ADR-0013) |
| 2026-07-19 | `0.2` | Schema bundle re-drafted to the 0.2 docs: schema surface unchanged (no docs delta touched it); fixtures conform to shared-kernel 0.2 `data_handling` (retention_policy removed from artifact-staging and finalized-artifact fixtures; new invalid fixture proves retention-policy metadata is rejected; ADR-0015); 10 fixtures, 13 tests |

## Folded decisions (2026-07-18)

Approved user-surface-review decisions applied to this family's docs
(schema/fixture re-draft pending; bundle stays `0.1`):

| ID | Applied as |
| --- | --- |
| F-4 / ADR-0015 | Family preserved; API-20 stripped from Consumers, ownership boundary, checklist, and open decisions. Retention/deletion workflows are the researcher's own DB operations in a self-hosted install; the durability surface is ungated |
| F-1 / ADR-0013 | The compiled `StudyVersion` artifact is called out as a stored object class: publication stores the compiled bytes (not rebuild-on-demand) via the same content-addressed staging/finalization path |
