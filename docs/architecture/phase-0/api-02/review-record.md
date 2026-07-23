# API-02 Review Record

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
| Ownership, lifecycles, and boundary | Drafted | [Index](index.md), [deployment-and-secrets](deployment-and-secrets.md) |
| Requirement composition and satisfaction | Drafted | Satisfaction relation and closure test |
| Secret boundary and client projection | Drafted | `SecretRef`-only bindings, positive-allowlist projection, closure test |
| Verbs, concurrency, recovery | Drafted | Two-verb surface (`deploy`/`stop`) and failure section; ports pending API-11/API-22 |
| Version-0 portable schemas | Drafted | [Schema bundle](schemas/v0/platform-deployment.schema.json) at the 0.2 two-verb surface (live/stopped `Deployment`, internal revision/report, no grant coupling) |
| Golden fixtures and automated harness | Drafted | 20 fixtures (8 valid, 12 invalid), 26 tests; API-02 and Phase 0 corpus suites pass |
| Scenario and parity trace | Partial | NS-08/NS-12 obligations mapped; concrete walkthroughs open |
| Version-1 immutable contract | Not started | Blocked by decisions, reviews, cross-API ports, and promotion |

## Checklist

- [x] Goals, non-goals, consumers, ownership, and API classes drafted
- [x] Deployment/revision lifecycle and immutability drafted
- [x] `DeploymentRequirement` schema owned here; composition boundary with API-01 drafted
- [x] Satisfaction relation (capability/secret/execution) defined and tested
- [x] Secret boundary: `SecretRef`-only bindings, no secret material, provider-binding integrity
- [x] Participant-safe client projection with disclosure allowlist and revision closure
- [x] Initial exact schemas, valid/invalid fixtures, and semantic harness pass
- [ ] Exact payload/result/view schemas for `deploy` and `stop`
- [x] Schema bundle re-drafted from the five-op 0.1 surface to the two-verb 0.2 surface
- [ ] Accountable owner and four reviewers assigned
- [ ] API-11 artifact-staging and API-22 build-job ports defined for fault tests
- [ ] API-01 composes the accepted `DeploymentRequirement` (closes A01-O14)
- [ ] API-03/API-04 visit-pinning compatibility reviewed
- [ ] API-09 client-projection delivery compatibility reviewed
- [ ] Independent browser schema/disclosure runner passes
- [ ] Stateful revision/rotation/recovery fault injection passes
- [ ] NS-08 and NS-12 concrete walkthroughs pass
- [ ] Dependent ADRs (0003, 0007, 0011) accepted or superseded
- [ ] Exact version-1 bytes frozen and retained

## Resolved at Draft level

| Question | Revision-0.1 decision |
| --- | --- |
| Requirement ownership | API-02 owns `DeploymentRequirement`; API-01 composes and pins it |
| Science vs operations split | Semantics-affecting change needs a new study version; infra/secret change needs only a new revision |
| Secret representation | Logical `SecretRequirement` (API-01) → operational `SecretBinding` holding a `SecretRef`; never secret material |
| Secret resolution modes | `pinned` fixes a `binding_revision`; `deployment-current` follows operator rotation |
| Client safety | Positive-allowlist projection; secrets/builds/operator endpoints structurally excluded |
| Satisfaction proof | Revision creatable only when capability/secret/execution closure holds and `requirement_digest` matches |

## Open decision log

| ID | Decision needed | Proposed default | Blocks |
| --- | --- | --- | --- |
| A02-O01 | ~~Deployment availability state machine and authority~~ | **Closed by D03-5 / ADR-0015:** two dispositions only (live/stopped); ungated (self-hosted) | — |
| A02-O02 | Secret rotation: when a new revision is mandatory | New revision only when bound secret identity or `binding_revision` changes exposure; rotation is redeploy | Version 1 |
| A02-O03 | Endpoint identity, TLS/protocol capability, and health/probe contract | Deployment-pinned endpoint set with declared protocol capabilities; probe owned by API-09 | API-09 review |
| A02-O04 | Region/residency enforcement point | Compiler declares policy (API-01); API-02 enforces at deploy; no audit layer (ADR-0015) | Version 1 |
| A02-O05 | ~~Multi-tenant deployment scope and RBAC~~ | **Closed by F-4 / ADR-0015:** no roles/RBAC; the self-hosting institution owns access control | — |
| A02-O06 | Build artifact provenance/signature/SBOM for server/client/execution builds | Require digest+lock now; signature/trust deferred (no plugin framework in v0) | Live executable deployments |
| A02-O07 | External secret managers (Vault/AWS) by reference vs pass-the-value only | Settled 2026-07-18: pass-the-value (D03-3) is the only v0 path; external by-reference is post-v0 | — |
| A02-O08 | `mug run` (publish+deploy in one) for local dev; `deploy.toml` for repeatable deploys | Revised 2026-07-19 (R-21): `mug run` **retired** — `mug deploy` publishes implicitly, and bare `mug deploy study` is the localhost dev preview (working tree, no version minted, preview-marked data). `deploy.toml` remains open | — |
| A02-O11 | Publish/deploy bundling | Settled 2026-07-19 (R-21): deploy publishes — an unused `study@version` triggers compile+publish of the current git state under that string before deploying; byte-identical re-deploys idempotent; changed content under a used string errors (D02-3). `mug simulate` auto-publishes identically; `mug export` never publishes. `study.publish()` remains the explicit/CI form | — |
| A02-O09 | Rotation default | Settled 2026-07-18: `Resolution.CURRENT` (follow-current) is the default; `Resolution.PINNED` is the advanced opt-in | — |
| A02-O10 | Process topology / deployment profile | Settled 2026-07-19, simplified same day (R-20, supersedes the interim R-19 platform/operator-API model): **one typical run path** — `mug deploy` runs on the hosting machine itself (laptop for dev, lab box for collection), starts the local server process if needed, records the revision in the machine's local store, serves. No remote deployment protocol/operator API/artifact push; code reaches the host via git; `--at` is the presented public URL, not a target; publication idempotence (ADR-0013) makes publish-on-the-host reproduce identical versions. MUG provisions no infrastructure | — |

## Required sign-off

| Review | Reviewer | Decision | Date | Focus |
| --- | --- | --- | --- | --- |
| Domain/scientific validity | Unassigned | Pending | — | Science/operations split, immutability, requirement satisfaction |
| Runtime/distributed systems | Unassigned | Pending | — | Revision concurrency, idempotency, rotation, recovery, visit pinning |
| Data/replay | Unassigned | Pending | — | Schemas, digests, archival readability, projection closure |
| Security/privacy | Unassigned | Pending | — | Secret boundary, client disclosure, region/residency, external processors |

## Change log

| Date | Revision | Change |
| --- | --- | --- |
| 2026-07-17 | `0.1` | Opened concrete API-02 review: deployment/revision ownership, `DeploymentRequirement` schema owned here, satisfaction relation, secret boundary, participant projection, exact v0 schemas, 11 fixtures, and 16 passing tests |
| 2026-07-18 | `0.2 (docs)` | Folded approved user-surface-review decisions (docs only; schema bundle stays 0.1): two-verb operator surface, one-call deploy, pass-at-deploy secrets, ungated deployment (ADR-0015) |
| 2026-07-19 | `0.2` | Schema bundle re-drafted to the two-verb surface: live/stopped `Deployment` aggregate added, grant coupling and capability closure removed, `SatisfactionReport` gains `region_gaps` and drops its revision ref when unsatisfied, `Resolution.CURRENT`-default secret refs, localhost endpoints (R-20), shared-kernel 0.2 `data_handling`; fixtures regenerated (20) and tests rewritten on the shared harness (26) |

## Folded decisions (2026-07-18)

Approved user-surface-review decisions applied to the API-02 docs (schema
bundle unchanged at 0.1; re-draft pending):

- **D03-1** — deploy is one call (`mug deploy study@version --at URL --secret key=$VAL`); revision/satisfaction/promotion machinery is internal, never an operator step.
- **D03-2** — one person, one role; no author/operator split enforced by MUG (superseded in part by F-4: no grant system at all).
- **D03-3** — secrets passed at deploy time (value/env); API-02 stores them and holds references only; no pre-register step, no hand-managed `SecretRef`.
- **D03-4** — four guarantees always on and invisible: immutable deploy record, needs-met check, secret isolation, in-flight visit pinning. The durable `DeploymentRevision` record remains as the internal pinning mechanism.
- **D03-5** — two verbs total: `deploy` and `stop`; no suspend/resume/retire vocabulary; neither verb deletes data.
- **F-4 / ADR-0015** — governance out of scope: removed all API-20 authority coupling; deployment is ungated in a self-hosted install; minimal secret storage stays in API-02 as a security mechanism.
