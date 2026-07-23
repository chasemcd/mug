# API-22: Durable Background Jobs and Workers

| Field | Value |
| --- | --- |
| Status | Draft |
| Contract revision | `0.2` |
| Accountable owner | Unassigned |
| Last updated | 2026-07-19 |
| Consumers | API-01 (compile), API-02 (builds), API-11 (outbox dispatch), API-12/13 (async), API-16/19 (bundles/exports) |
| Depends on | [Shared kernel 0.1](../shared-kernel/index.md), proposed ADRs 0009, 0010, 0013 |
| Implementation phase | Phase 1; durable scaling Phase 6 |
| Stability tiers | SPI, application command/query |

## Outcome

API-22 is the single durable-job lifecycle the platform reuses instead of each
domain inventing its own. Work is idempotent on a content work key, runs under a
fenced lease, and produces exactly one durable result per work key.

## First-class job kinds (v0)

| Kind | Kind key | Driver |
| --- | --- | --- |
| **Compile-at-publish** — compiling a git commit into the stored, immutable `StudyVersion` artifact | `compile-at-publish` | API-01; ADR-0013 |
| **`mug simulate` headless batch runs** — N all-agent runs (no human seats), scheduler-driven, data captured like any run | `simulate-batch` | API-05/12; D11-7 |
| Export bundle builds | `export-bundle-build` | API-19 |
| Replay bundle construction | `replay-bundle-build` | API-16 |

The first-class kind keys are registered in the schema bundle
(`FirstClassJobKind`); the `job_kind` space itself stays open because domains
supply their own kinds and payload schemas.

## Ownership boundary

API-22 owns `JobRequest`, `JobRun`, and `JobResult` plus the worker lease and
retry contract. Domains supply job kinds and payload schemas; they do not invent
competing job lifecycles.

## Non-negotiable job boundary

1. A job is idempotent on its `work_key`; a duplicate request resolves to the
   existing result.
2. A run holds a fenced lease; a stale generation cannot commit a result.
3. A succeeded run names a result digest; a successful result names its artifact.
4. Cancellation and retry are explicit and never fabricate a result.

## Current executable evidence

- 5 valid and 6 one-defect invalid examples; 16 API-22 tests including work-key
  idempotency, success/result consistency, and the first-class job-kind
  registry.

## Acceptance status

`Drafted`, not `Accepted`. See the [review record](review-record.md).
