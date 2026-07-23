# ADR 0003: Immutable Study Versions and Materialized Visit Plans

| Field | Value |
| --- | --- |
| Status | Accepted |
| Accepted | 2026-07-20 (ratification; immutable versions + materialized visit plans folded in API-01/API-04; per-family freeze separate) |
| Date | 2026-07-16 |
| Owners | Unassigned |
| Refined by | [ADR 0013](0013-git-native-study-versioning.md) (2026-07-18): how a version comes to exist is now git-native publication; version immutability and materialized plans stand |
| Affects | API-01 through API-04, API-10, API-16, API-18 |

## Context

Rebuilding authored flow objects during restoration can rerun randomization and
change a participant's scene order or condition. Longitudinal research also
requires exact knowledge of the scientific protocol used in each visit.

## Decision

A published `StudyVersion` is an immutable, content-bound scientific protocol.
Its typed version ID is immutable-version identity; a separate canonical
manifest digest binds that identity to exact content. It pins every scientifically
meaningful flow, environment/controller artifact requirement, client behavior,
prompt, tool policy, model-selection rule, capture policy, and schema.

A stable deployment identity has immutable `DeploymentRevision`s that bind one
study version to exact deployable builds, adapters, endpoints, region, and
secret references. A visit pins both IDs. An infrastructure-only change may
create a deployment revision without a new study version only when it cannot
affect scientific semantics or participant experience; otherwise both versions
change.

Hosted-provider configuration pins the requested provider/model selector,
adapter, parameters, and fallback rule. The resolved model and response are
recorded as exposure because MUG cannot content-address a vendor's hidden
serving implementation.

Before a visit begins, MUG atomically records assignment and a materialized
`VisitPlan` containing stable activity occurrence IDs, randomization results,
known branches, repetition, parameters, roles, and versions.

Recovery loads the plan. It never recreates random outcomes implicitly.
Protocol-defined dynamic branch decisions are appended durably before
progression.

## Invariants

- An active visit never silently moves to the latest study version.
- An active visit never silently moves to a later deployment revision.
- Assignment and known plan outcomes exist before exposure.
- Visit-plan mutation occurs only through a versioned, recorded protocol rule.
- Longitudinal version transitions are explicit and may require renewed consent.

## Alternatives considered

### Store only a random seed and rebuild

Rejected because code, traversal, RNG consumption, dependencies, and branching
can change. Persisted outcomes are stronger evidence than an assumed replay.

### Store only the current activity index

Rejected because an index has no stable meaning if the rebuilt sequence differs.

## Validation

NS-08 restarts at every activity boundary and verifies the same plan, assignment,
occurrence IDs, and version. Changing the authoring definition produces a new
version rather than mutating an active visit.
