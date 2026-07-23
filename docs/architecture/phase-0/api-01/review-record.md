# API-01 Review Record

| Field | Value |
| --- | --- |
| Status | Draft |
| Contract revision | `0.2` |
| Review opened | 2026-07-17 |
| Last updated | 2026-07-20 |
| Accountable owner | Unassigned |
| Target accepted version | `1` |
| Governing ADRs | [ADR 0013: Git-Native Study Versioning and Stored Compiled Artifacts](../../decisions/0013-git-native-study-versioning.md); [ADR 0015: Governance Is Out of Scope](../../decisions/0015-governance-out-of-scope.md) |

## F-1 fold record

Revision `0.2` folds foundational decision **F-1** (git-native study
versioning + stored compiled artifact) into this family. Decision source:
`scratch/phase0-review/DECISIONS.md` (F-1, D01-1 through D01-8, D02-1 through
D02-8) and the surface reviews `scratch/phase0-review/01-researcher-authoring.md`
and `scratch/phase0-review/02-publishing-versioning.md`. ADR 0013 is the
governing ADR; it supersedes ADR 0012 in part and refines ADR 0003.

Removed by the fold: `StudyDraft`, `DraftRevision` chains and head optimistic
preconditions, `diff_revisions`, `allocate_definition_id`/`commit_revision`,
draft lifecycle commands, and the mutable `DefinitionRegistry` aggregate with
its registration/rename/tombstone machinery.

Added by the fold: `GitProvenance` (commit SHA, optional branch/remote, dirty
flag, stored patch) recorded automatically at publish with dirty trees
allowed; the hand-typed per-study **version string** (unique, immutable,
citable) alongside the resolved-content dedup digest; definition-key
continuity derived from published history; and the stored compiled artifact
as the published record.

Kept: pure compile to immutable `StudyVersion`, the scientific/client/server/
provenance manifest split and digest graph, secret-requirement slots and
no-inline-secret rules, capability closure, atomic publication with
`(study_id, scientific_manifest_digest)` uniqueness, availability dispositions
(deprecate/withdraw) as append-only catalog facts, and API-22 job-based
validation/compilation.

## F-4 / ADR 0015 correction record

The `0.2 correction` folds foundational decision **F-4** and ADR 0015 into
API-01 without advancing the family revision; `0.3` is reserved for the runtime
parity folds. The correction removes the former API-21 framework surface from
the executable contract: `PluginRequirement`, the authoring `plugins`
collection, the server-binding plugin branch, the `plugin.*` capability
namespace, and package trust classes are gone. Speculative worker/container
package kinds are also removed. `CodePackageRef` remains only as a pinned
ordinary study-code artifact implementing a closed, MUG-owned typed protocol.

The former API-20 coupling is absent: API-10 owns immutable scientific evidence,
API-02 and the shared kernel own minimal secret references, and institutional
infrastructure owns access control and storage lifecycle. API-01/API-02 plus the
security review own study-code package integrity and deployment constraints;
API-11/API-16 own schema-bundle artifact and archival-readability concerns. The
shared-kernel dependency is the current version-0 bundle at
`f675d9ec1f6258719da93a507421689b26babf69d36503c7df90b5039e238d6d`
(provisional until the shared-kernel runtime-layer freeze; see the
shared-kernel review-record).

## Deliverable status

| Deliverable | Status | Evidence |
| --- | --- | --- |
| Current-capability grounding | Drafted | [Parity map](current-mug-parity-map.md) with line-level repository evidence |
| Ownership, lifecycles, commands, and queries | Drafted | [Authoring/publication contract](authoring-and-publication.md) |
| Git capture, version strings, and provenance | Drafted | ADR 0013 fold in the authoring/publication contract and schema bundle |
| Compiler, diagnostics, and failure semantics | Drafted | Pure/durable APIs, work key, diagnostics, error catalog, and fault matrix |
| Normal/failure sequences | Drafted | [Capture, compile, publish, duplicate, and crash sequences](publication-sequences.md) |
| Manifest/privacy/package boundary | Drafted | [Manifest/packaging contract](manifests-and-packaging.md) |
| Version-0 portable schemas | Drafted | [Schema bundle](schemas/index.md) |
| Golden fixtures and automated harness | Drafted | [Fixtures](fixtures/index.md), [conformance](conformance.md); 34 API-01 tests over 10 valid and 18 invalid fixtures pass alongside the shared-kernel suite |
| Scenario and parity trace | Partial | Contract-level mapping exists; concrete API walkthroughs and domain schemas remain open |
| Version-1 immutable contract | Not started | Blocked by decisions, reviews, cross-runtime evidence, and promotion |

## Checklist

- [x] Goals, non-goals, consumers, ownership, and API classes drafted
- [x] Functional-parity/no-backward-compatibility boundary grounded in code
- [x] F-1 fold: drafts/revisions/registry removed; git-native model drafted
- [x] `GitProvenance` shape (commit + dirty patch) and capture failures drafted
- [x] Version-string identity, collision rules, and reservation drafted
- [x] Definition-key continuity from published history drafted
- [x] Public authoring and application command/query signatures drafted
- [x] Pure validation/compile and API-22 durable-job split drafted
- [x] Diagnostics, errors, idempotency, concurrency, transaction, and recovery drafted
- [x] Scientific/client/server/provenance manifest and digest graph drafted
- [x] Secret requirement versus deployment secret-binding boundary drafted
- [x] Pinned ordinary study-code packages and closed core-capability closure drafted
- [x] Exact schemas, valid/invalid fixtures, and semantic harness pass
- [x] Publication explicitly rejects proposal-only schema version 0
- [ ] Exact payload/result/view/page/diff schemas exist for every listed
      command and query
- [ ] Accountable owner and four reviewers assigned
- [ ] Hermetic Python frontend/source-package boundary accepted
- [ ] Git capture mechanics (monorepo/patch format/submodules) accepted
- [ ] Package integrity, signature, dependency-lock, deployment-execution, and
      SBOM requirements accepted by API-01/API-02 and the security review
- [ ] Domain-owned authoring schemas for NS-01 through NS-08 drafted
- [ ] API-02 deployment requirement/overlay compatibility reviewed
- [ ] API-04 flow/materialization compatibility reviewed
- [ ] API-10/API-11 evidence/artifact compatibility reviewed (including stored
      patch and resolved-artifact durability)
- [ ] API-11/API-16 schema-bundle artifact and archival compatibility reviewed
- [ ] API-22 job compatibility reviewed
- [ ] Independent browser schema/privacy/canonicalization runner passes
- [ ] Deterministic compile-twice reference studies pass
- [ ] Stateful publication/fork fault injection passes
- [ ] NS-01 through NS-08 concrete API walkthroughs pass
- [ ] Proposed ADRs (including ADRs 0013 and 0015) accepted or superseded
- [x] Shared-kernel 0.2 retirements and closed `mug.*` namespaces consumed at
      digest `19f024dc918b52a5…`
- [ ] Exact version-1 bytes frozen and retained

## Resolved at Draft level

| Question | Revision-0.2 decision |
| --- | --- |
| Backward compatibility | None; retain functional outcomes and port examples |
| Source of truth for study source | Git (ADR 0013); the platform stores no drafts or revisions |
| Publication input | Named git state: HEAD commit + stored patch of uncommitted changes; dirty trees allowed (D02-1) |
| Stored artifact versus rebuild | The compiled, resolved artifact is stored and bound to results; never rebuilt on demand (D02-2) |
| Version identity | Content digest is dedup identity; hand-typed version string is the unique immutable citable handle; git SHA is provenance (D02-3) |
| Version-string format | Free-form, non-empty, no leading/trailing whitespace; no enforced semver |
| Amendments | Always a new immutable version compiled from a new git state (D02-4) |
| Availability | Deprecate/withdraw are append-only dispositions, never deletion (D02-5) |
| Diff | Platform diff compares resolved versions; source diff is git's (D02-6) |
| Definition identity | Derived from published history at publish time, not a mutable registry (D02-7) |
| Fork | New `Study` bound to forked source with lineage; copies design, never data/secrets/enrollment (D02-8) |
| Validation target | Exact captured source state and content-bound context, never an implicit working tree |
| Slow compilation | Pure compiler contract plus API-22 durable job application API |
| Scientific identity | RFC 8785 scientific-root bytes; publication metadata excluded |
| Manifest partitions | Complete scientific root plus deliberately constructed client/server/provenance projections |
| Secrets | Logical `SecretRequirement` in science; `SecretRef` only in the API-02 deployment overlay |
| Participant artifacts | Neutral slots in the compiled client template; runtime-scoped handles are supplied with participant delivery |
| Randomization | Rule compiled; API-04 commits outcomes; compiler never samples |
| Duplicate publication | Unique same-study scientific digest returns one version; a new key receives a separate durable reuse fact/receipt, never the original command's receipt |
| Invalid content | Successful validation/compile outcome with diagnostics, not infrastructure `DomainError` |

## Open decision log

| ID | Decision needed | Proposed default | Blocks |
| --- | --- | --- | --- |
| A01-O01 | Python authoring frontend execution/isolation | Trusted local CLI initially; hosted source evaluation only in an isolated, hermetic build job | Phase 1 implementation |
| A01-O02 | Source package and build-context schema | Content-addressed source archive from commit + patch + declared entry point + lock + allowed roots; no ambient CWD/env/network | Version 1 |
| A01-O03 | Package integrity/signature/SBOM/license contract | Require exact digest/lock now; API-01 owns package format, integrity, SBOM, and license declarations, API-02 owns deployment-execution constraints, and the security review selects any signature requirement | Live executable studies |
| A01-O04 | Exact domain definition-kind registry of kinds | Initial core kinds in v0; additions require owning API and typed ID/prefix review | Version 1 |
| A01-O05 | Flow algebra adequacy | Current closed six-node union; prove NS/parity studies before freeze | Version 1 |
| A01-O06 | Version diff classification | Structured scientific/experience/privacy/evidence/capability/provenance change taxonomy | API-02 and review UX |
| A01-O07 | Warning acknowledgment policy | Errors are never waivable; warnings require an explicit content-bound acknowledgment. Any second-person review is an institutional process outside MUG | Version 1 |
| A01-O08 | Git capture mechanics | One repo per study by default; patch = deterministic unified diff of tracked + declared untracked roots; submodule/LFS handling explicit | Version 1 |
| A01-O09 | Catalog availability operation | Author-callable deprecate/withdraw; self-hosted operators ungated | Version 1 |
| A01-O10 | Manifest-set artifact commit handoff | Finalize/verify through API-11 before API-01 publication Unit of Work | Stateful tests |
| A01-O11 | Schema bundle embedding/signature | Offline-complete immutable artifact; exact container/signature pending API-11 artifact and API-16 archival/replay review | Version 1 |
| A01-O12 | Client-disclosure schema metadata | Domain schema declares permitted destination/field projection; compiler also scans synthetic adversarial values | Security review |
| A01-O13 | Study aggregate-bootstrap command target | Introduce or reuse a real catalog-scope `ResourceRef`; bind `expected_absent`, fingerprint, and idempotency before allocating `StudyId` | Exact command schemas |
| A01-O14 | API-02 deployment-requirement composition | API-02 owns the typed requirement and satisfaction proof; API-01 composes its exact accepted `TypedObject`/reference into authoring and scientific roots. API-01 keeps its fixture placeholder until API-02 is Accepted, then binds the real schema | Version 1 and API-02 acceptance |
| A01-O15 | Version-string constraints | Non-empty, trimmed, ≤128 chars; no further scheme (no enforced semver) | Version 1 |
| A01-O16 | Non-git source path | Settled 2026-07-18: **git only** — no uploaded-artifact path, in v0 or planned | — |
| A01-O17 | Monorepo layout | Settled 2026-07-18: a repo may hold several studies via a repo-relative study root; optional `source_path` added to `GitProvenance` (schema restamped) | — |
| A01-O18 | Version-string format | Settled 2026-07-18: free-form unique non-empty string ≤128 (as already encoded in `VersionString`) | — |

## Required sign-off

| Review | Reviewer | Decision | Date | Focus |
| --- | --- | --- | --- | --- |
| Domain/scientific validity | Unassigned | Pending | — | Flow, identity, version strings/diff, treatment/blinding |
| Runtime/distributed systems | Unassigned | Pending | — | Jobs, idempotency, transaction, failure/recovery |
| Data/replay | Unassigned | Pending | — | Manifest closure, stored artifacts, git provenance, archival readability |
| Security/privacy | Unassigned | Pending | — | Source-execution boundary, client projection, secrets, patch handling, package integrity, deployment containment |

## Change log

| Date | Revision | Change |
| --- | --- | --- |
| 2026-07-20 | `0.2 correction` | Folded ADR 0015 into API-01: removed the retracted API-21 framework and API-20 coupling, retained pinned ordinary study-code packages against closed MUG-owned protocols, re-homed package security to API-01/API-02/security review and schema-bundle/archive concerns to API-11/API-16, added two one-defect rejection fixtures, and restamped the bundle `8e338707…` → `96958cdf…` against shared-kernel dependency `19f024dc…`; 34 tests pass over 10 valid and 18 invalid fixtures; `0.3` remains reserved for runtime-parity folds |
| 2026-07-19 | `0.2` | Shared-kernel 0.2 conformance: removed `retention_policy` members from every fixture `data_handling` block (kernel `DataHandlingRef` now carries `privacy_labels` only; `RetentionPolicyRef` retired); dropped the now-unsatisfiable `wave` definition kind (the `wavedef_` prefix left `RegisteredMugId`) and the retired `retpolicy_`/`retpolicyver_` prefixes from the client-disclosure scanner; restamped the bundle digest closure (`28364993…` → `8e338707…`); suite still 31 passing tests |
| 2026-07-18 | `0.2` | Folded F-1/ADR 0013 (git-native versioning + stored compiled artifact): removed drafts, revisions, head preconditions, revision diffs, and the definition registry; added `GitProvenance` (commit + dirty patch), the hand-typed unique version string with collision rules, published-history definition-key continuity, and the stored resolved artifact; removed API-20 from the consumers row (governance retracted by F-4); regenerated schemas, fixtures, and the digest closure; API-01 suite now 31 passing tests over 10 valid and 16 invalid fixtures |
| 2026-07-17 | `0.1` | Composed the A01-O14 deployment requirement into the authoring and scientific roots as a required `TypedObject`; reshaped client projections into `projection_key`/`selector`/`manifest` records and provenance outputs into role-scoped retention records; moved `audience_class` off the client body onto the projection selector; regenerated the digest closure and kept the API-01 suite at 23 passing tests |
| 2026-07-17 | `0.1` | Opened concrete API-01 review with repository grounding, detailed APIs/lifecycles, manifest/package boundary, exact v0 schemas, 18 fixtures, and 23 passing API-01 tests |
