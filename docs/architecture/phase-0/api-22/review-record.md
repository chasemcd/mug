# API-22 Review Record

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
| Version-0 schemas | Drafted | `jobs.schema.json` |
| Golden fixtures and harness | Drafted | 11 fixtures, 16 tests |
| Scenario/parity trace | Partial | Obligations mapped; concrete walkthroughs open |
| Version-1 immutable contract | Not started | Blocked by decisions, reviews, and cross-API ports |

## Checklist

- [x] Jobs are idempotent on a content work key
- [x] Runs hold a fenced lease; stale generations cannot commit
- [x] Succeeded runs and successful results name their evidence
- [x] Cancellation/retry never fabricate a result
- [x] Version-0 schemas, fixtures, and semantic harness pass
- [x] First-class job kinds named in schemas: `compile-at-publish` and
      `simulate-batch` plus export/replay bundle builds (D11-7/ADR-0013;
      re-drafted `0.2`)
- [ ] Exact command payload/result/view schemas for every command and query
- [ ] Accountable owner and four reviewers assigned
- [ ] Compile-at-publish job kind defined with API-01 (ADR-0013)
- [ ] `mug simulate` headless batch job kind defined with API-05/12 (all-agent seats; D11-7)
- [ ] Worker queue, backpressure, and multi-process coordination defined
- [ ] Retry/backoff, poison-job, and cancellation propagation defined
- [ ] API-11 outbox dispatch and API-12 scheduler integration reviewed
- [ ] Crash/lease-expiry fault injection passes
- [ ] Dependent ADRs accepted; four sign-offs recorded; version-1 bytes frozen

## Open decision log

| ID | Decision needed | Proposed default | Blocks |
| --- | --- | --- | --- |
| A22-O01 | Queue substrate and coordination | Relational queue in Phase 1; Redis/streaming durable scaling in Phase 6 | ['Phase 6'] |
| A22-O02 | Retry and poison-job policy | Bounded retries with backoff; poison jobs quarantined, never silently dropped | ['Version 1'] |
| A22-O03 | Lease fencing and heartbeat | Fenced lease with heartbeat; expiry frees the job; stale results rejected | ['ADR 0010'] |

## Required sign-off

| Review | Reviewer | Decision | Date | Focus |
| --- | --- | --- | --- | --- |
| Domain/scientific validity | Unassigned | Pending | — | Job lifecycle and idempotency |
| Runtime/distributed systems | Unassigned | Pending | — | Lease fencing, retry, cancellation, recovery |
| Data/replay | Unassigned | Pending | — | Result durability and archival readability |
| Security/privacy | Unassigned | Pending | — | Payload isolation and abuse limits |

## Change log

| Date | Revision | Change |
| --- | --- | --- |
| 2026-07-17 | `0.1` | Opened API-22: job request/run/result schemas, work-key idempotency, lease fencing, success/result consistency, 8 fixtures, 12 tests |
| 2026-07-18 | `0.2 (docs)` | Folded user-surface-review decisions (docs only; schema bundle remains `0.1` pending re-draft): family preserved; compile-at-publish and `mug simulate` headless batch runs named first-class job kinds |
| 2026-07-19 | `0.2` | Re-drafted the schema bundle to the 0.2 docs: first-class job-kind registry `FirstClassJobKind` (`compile-at-publish`, `simulate-batch`, `export-bundle-build`, `replay-bundle-build`; D11-7/ADR-0013) with the `job_kind` space left open to domain kinds; request/run/result lifecycle unchanged; shared-kernel 0.2 `data_handling` (privacy labels only; retired retention-policy IDs removed from the job-result fixture); 11 fixtures, 16 tests |

## Folded decisions (2026-07-18)

Applied from the approved user-surface review (`scratch/phase0-review/DECISIONS.md`):

- **D11-7** — All-agent runs launch via the headless `mug simulate` batch
  runner (all-agent seats, no human participants; `--render` to debug one run);
  named a first-class API-22 job kind driven by the API-12 scheduler.
- **ADR-0013 (F-1/D02-2)** — Compile-at-publish is a first-class job kind:
  publishing compiles a git commit into the stored immutable `StudyVersion`
  artifact.
- Family otherwise preserved as drafted; no lifecycle changes.
