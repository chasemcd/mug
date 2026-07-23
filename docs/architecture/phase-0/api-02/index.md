# API-02: Platform Composition and Deployment

| Field | Value |
| --- | --- |
| Status | Draft |
| Contract revision | `0.2` |
| Accountable owner | Unassigned |
| Last updated | 2026-07-19 |
| Consumers | Operators/deployers, API-01 (requirement composition), API-03/API-04 (visit pinning), API-09 (client delivery), API-22 (build jobs) |
| Depends on | [Shared kernel revision 0.1](../shared-kernel/index.md), [API-01 revision 0.1](../api-01/index.md), and proposed ADRs 0003, 0007, 0011, 0013, 0015 |
| Implementation phase | Phase 1 one-call deploy binding; Phase 2 durable revision history, rotation, and recovery |
| Stability tiers | Application command/query, wire (client projection), and archival |

## Outcome

API-02 turns an immutable scientific `StudyVersion` into a live study without
touching study semantics. The operator surface is exactly **two verbs** (D03-5):

```bash
mug deploy study@version --at URL --secret key=$VAL   # bring up, rewire, rotate, bring back
mug stop  study                                       # take down (no new participants)
```

`deploy` is **one call** (D03-1): it records an immutable `DeploymentRevision`,
verifies the study's declared needs are met, stores any passed secrets **by
reference**, and goes live — or fails with a plain diagnostic before anything is
live. Deployment is **ungated (self-hosted; ADR-0015)**: there is no
author/operator role split enforced by MUG and no grant check.

```text
StudyVersion (API-01, immutable science — git-native provenance, ADR-0013)
        │  declares deployment_requirements: DeploymentRequirement
        ▼
mug deploy  ──►  DeploymentRevision (internal, immutable pinning record)
  ├── server/client/execution build artifacts
  ├── region + participant endpoints
  └── secret bindings (SecretRef, never secret material)
        │  needs-met check (refused before live if unsatisfied)
        ▼
live study ──► ClientDeploymentProjection (participant-safe)
```

The `DeploymentRevision` record **remains** as the internal mechanism that
in-flight visits pin (D03-4): a visit is bound to the version + wiring it
started on, so `stop` or a redeploy never interrupts or corrupts a running
session. The record is not an operator-facing object — the five-op
create/revision/promote/suspend/retire ceremony is gone; the durable record
stays.

A scientifically equivalent infrastructure, endpoint, or secret change is just
another `mug deploy` and produces a new internal revision without a new study
version. Any change that can affect study semantics or participant experience
requires a new study version first; API-02 never launders such a change through
a redeploy.

## Contract set

| Document | Normative responsibility |
| --- | --- |
| [Deployment and secrets](deployment-and-secrets.md) | Ownership, lifecycles, requirement satisfaction, secret boundary, client projection, verbs, and recovery |
| [Schema bundle](schemas/v0/platform-deployment.schema.json) | Exact version-0 persisted, wire, and archival shapes for the two-verb surface |
| [Golden fixtures](fixtures/v0/manifest.json) | Valid and one-defect invalid contract examples |
| [Conformance plan](conformance.md) | Structural, semantic, satisfaction-closure, secret-boundary, and disclosure tests |
| [Review record](review-record.md) | Evidence, unresolved decisions, sign-offs, and promotion gate |

The prose and the schema bundle agree at revision 0.2: the bundle encodes the
two-verb, ungated surface (no grant coupling, no capability closure, no
five-op vocabulary) and the fixtures exercise it end to end.

## Ownership boundary

API-02 owns:

- The stable `Deployment` aggregate and its immutable linear `DeploymentRevision`
  history for one study (internal; created by `mug deploy`, never hand-managed).
- `DeploymentRequirement` (the typed requirement API-01 composes) and the
  deployment-side **satisfaction** proof against a pinned study version.
- Build/execution artifact bindings, region, and endpoints for a revision.
- **Minimal secret storage** (D03-3, F-4): secrets are passed at deploy time
  (value or env var); API-02 stores them and holds only references
  (`SecretBinding` → shared-kernel `SecretRef`). Secret material never enters
  the compiled study, the deployment record, logs, exports, or the client.
- The participant-safe `ClientDeploymentProjection` delivered through API-09.

It does not own: study science, manifests, or capability closure (API-01);
identity, enrollment, or visit materialization (API-03/API-04); artifact bytes
and staging (API-11); or build-job mechanics (API-22). API-02 composes those
contracts; it never redefines them. Authorization, roles, audit, and retention
are out of MUG's scope entirely (ADR-0015) — the self-hosting institution owns
access control around its own install.

## Non-negotiable deployment boundary

1. Each `mug deploy` records an immutable `DeploymentRevision` pinning exactly
   one `StudyVersion` by ref and `requirement_digest` (D03-4).
2. A deploy goes live only if it **satisfies** the pinned requirement: every
   non-optional secret requirement is bound and every execution slot has a
   build binding. An unsatisfied deploy fails with a plain diagnostic before
   going live — never a partially live study.
3. Secret material and `SecretRef` never enter a `ClientDeploymentProjection`,
   a browser payload, an object key, or an ordinary log. The projection carries
   only participant-facing endpoints, region, protocol capabilities, and the
   non-secret deployment revision reference.
4. A visit pins one study version and one deployment revision; `mug stop`,
   redeploy, or server restart never rebinds an in-flight visit's pinned
   revision (NS-08).
5. Secret rotation is just `mug deploy` with a new value; under
   `Resolution.CURRENT` the referenced binding advances, under
   `Resolution.PINNED` a `binding_revision` is fixed (F-3 typed constants).
   Neither rewrites a prior revision's bytes.

## Current executable evidence

- 8 valid examples: a composed `DeploymentRequirement`, a satisfying
  `DeploymentRevision` (`Resolution.CURRENT` default), a localhost dev-machine
  revision (R-20 default `--at`, `Resolution.PINNED` opt-in), a participant
  `ClientDeploymentProjection`, satisfied and unsatisfied `SatisfactionReport`s,
  and live and stopped `Deployment` dispositions pinning the same revision.
- 12 one-defect invalid examples: inline secret material, 0.1 grant coupling in
  a requirement, `capability_grants` on a revision, dangling provider secret
  key, duplicate secret binding, a `binding_revision` on an unpinned secret
  ref, an internal endpoint in a client projection, a secret ref leaked into a
  client projection, an inconsistent satisfaction verdict, 0.1
  `capability_gaps` on a report, a retired five-op disposition, and a
  deployment whose current revision belongs to another deployment.
- 26 API-02 contract tests, including satisfaction closure, client-projection
  closure, and disposition/revision pinning over exact canonical bytes; the
  integrated Phase 0 corpus checks pass alongside them.

Version 0 remains mutable and unpublishable.

## Acceptance status

API-02 is `Drafted`, not `Accepted`. The [review record](review-record.md)
holds the exact blockers. Highest-priority remaining work: promote the
`DeploymentRequirement` schema
to Accepted so API-01 can replace its fixture placeholder (open decision
A01-O14); define the API-11/API-22 artifact-staging and build-job ports needed
for revision crash tests; and walk NS-08 and NS-12 end to end.
