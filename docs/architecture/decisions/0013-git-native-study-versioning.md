# ADR 0013: Git-Native Study Versioning and Stored Compiled Artifacts

| Field | Value |
| --- | --- |
| Status | Accepted |
| Accepted | 2026-07-20 (git-native versioning + stored compiled artifact folded in API-01; the non-git-author publication path is an explicit v0 limitation and stored-artifact retention defers to API-11) |
| Date | 2026-07-18 |
| Owners | Unassigned |
| Supersedes | ADR 0012 in part (draft/revision/registry machinery); refines ADR 0003 (how a version comes to exist) |
| Superseded by | None |
| Affects | API-01, API-02, API-04, API-10, API-11, API-22 |

## Context

ADR 0012 gave API-01 an in-platform source-control subsystem: `StudyDraft`,
`DraftRevision` chains, optimistic head preconditions, revision diffs, and a
mutable study-owned `DefinitionRegistry`. Researchers already keep study source
in git, which does branching, diff, review, and collaboration better than any
re-implementation. The platform-side machinery duplicated git while adding
aggregate state, precondition races, and API surface that no approved user
journey needs (review decision F-1, D02-1 through D02-8).

## Decision

Git is the system of record for study source. MUG never stores drafts or
revisions; it compiles a **named git state** into an immutable, resolved,
access-partitioned `StudyVersion` and **stores the compiled artifact**.

- The named git state is the repository's current commit SHA **plus a patch of
  any uncommitted working-tree changes**, both recorded by the platform at
  publish time. A clean HEAD is not required; the patch bytes are stored by the
  platform (not referenced) so provenance stays whole. Exact source is
  reproducible as commit + patch.
- The author supplies a hand-typed **version string** with each publication. It
  is free-form, non-empty, unique within the study, immutable once used, and is
  the citable handle for the version. It is recorded alongside the
  resolved-content digest (dedup identity, per ADR 0012) and the git provenance.
  Collision rules: same content + same string is idempotent and returns the
  existing version; same content + a new string is rejected; new content + a
  reused string is rejected.
- The resolved `StudyVersion` bytes — scientific manifest plus client, private
  server, and provenance projections (ADR 0007) — are stored and bound to every
  result. Versions are never rebuilt on demand from commit + lockfile.
- Definition-key identity (longitudinal continuity of author-chosen keys) is
  derived by validating a candidate version's keys against the study's published
  history at publish time, not by a mutable registry aggregate.
- The platform's `diff` compares two published **resolved** versions
  (definitions and flow). Source-level diff is git's job.
- Fork creates a new `Study` bound to forked source with a recorded lineage
  link; it copies design, never data, enrollments, secrets, or deployments.

Removed from API-01: `StudyDraft`, `DraftRevision`, revision heads and
optimistic head preconditions, `diff_revisions`, `allocate_definition_id` /
`commit_revision`, and the mutable `DefinitionRegistry` aggregate.

Retained from ADR 0012: pure deterministic compilation keyed by exact inputs,
the acyclic manifest set, all-or-nothing publication in one transaction,
content-digest identity, no secret material or `SecretRef` in any API-01 source
or manifest, and availability transitions (deprecate/withdraw) that never mutate
or delete published bytes.

## Scope and non-goals

This decision defines source identity, version naming, and artifact storage for
publication. It does not change compiler determinism, manifest partitioning, or
publication atomicity (ADR 0012), and it does not change version immutability or
materialized visit plans (ADR 0003). It does not accept non-git source (an
uploaded-artifact path is deferred, not in scope for v0) and does not constrain
the version string to any scheme such as semver.

## Invariants

- Every published `StudyVersion` records its source as a commit SHA plus stored
  patch bytes; that pair reconstructs the exact source state.
- A version string, once bound within a study, is permanently reserved and maps
  1:1 to one resolved-content digest.
- Republishing identical content under its existing string returns the existing
  version and creates no new version or publication event.
- Result and evidence rows bind to the stored resolved version digest, never to
  a rebuild recipe.
- Definition-key reuse that is incompatible with the study's published history
  fails at publish time.
- The platform holds no mutable pre-publication study state; between
  publications, git is the only source of truth.

## Consequences

### Positive

- A whole stateful subsystem (drafts, revisions, registry, head preconditions)
  is deleted from API-01 with its concurrency and migration burden.
- Authors keep their existing git workflow, including publishing mid-iteration
  from a dirty tree.
- Reproducibility survives toolchain rot: a stored artifact replays years later
  even if `mug`, plugins, or dependencies have moved on.
- Papers cite a stable, author-chosen version string instead of an opaque
  ordinal or digest.

### Costs and constraints

- Resolved artifacts must be stored durably per version; storage is the price of
  rebuild-free reproducibility.
- Publishing from a dirty tree records work absent from git history; the stored
  patch is then the only record of that delta.
- Authors without git have no publication path in v0.

### Failure consequences

- A publication that cannot capture commit + patch, or whose version string
  collides, fails before any catalog effect (per ADR 0012 atomicity).
- Loss of stored artifact bytes is loss of the scientific record for that
  version; artifact retention/readability obligations move to API-11.

## Security and privacy

The stored patch may contain anything in the working tree; it is provenance
data, server-side only, and never enters the client manifest. Secret handling is
unchanged: API-01 compiles logical `SecretRequirement`s only (ADR 0007), and no
secret material or `SecretRef` may appear in source, patch-derived manifests, or
the stored artifact.

## API and schema impact

- API-01 drops `StudyDraftId`, `DraftRevisionId`, draft/revision/registry
  schemas, and their commands and preconditions from the shared identifier
  registry and contract set.
- API-01 adds a git provenance shape (commit SHA + patch artifact reference) and
  a per-study version-string binding with the collision rules above.
- API-02 and API-04 consume published versions exactly as before; visit pinning
  (ADR 0003) is unchanged.
- API-22 still runs compilation as durable jobs keyed by exact inputs.

## Alternatives considered

### Keep the in-platform draft/revision/registry subsystem

Rejected because it duplicates git with weaker tooling, adds mutable aggregate
state and precondition races, and serves no approved user journey.

### Record commit + lockfile and rebuild on demand

Rejected because reproducibility would depend on future availability and
behavior of toolchains, packages, and plugins; a stored artifact is stronger
evidence (F-1 tradeoff, D02-2).

### Require a clean committed HEAD to publish

Rejected because it adds friction without adding evidence: commit + stored
patch reproduces the exact source state either way.

### Derive the version handle from the digest or an ordinal

Rejected because authors and papers need a name they control; content
addressing still deduplicates underneath the hand-typed string.

## Validation

- Publish from clean and dirty trees; verify commit + patch reconstructs the
  compiled input exactly.
- Version-string collision matrix: identical content/same string idempotent,
  identical content/new string rejected, new content/reused string rejected.
- Definition-key continuity checks against published history, including
  incompatible reuse and fork with fresh lineage.
- Resolved-version diff detects a behavior change with zero source diff (for
  example a dependency bump).
- Replay of a stored version with the current toolchain removed or upgraded.

## Follow-up decisions

- Monorepo versus one-repo-per-study source layout — API-01 owner
- Version-string character/length constraints, if any — API-01 owner
- Uploaded-artifact source path for non-git authors (post-v0) — API-01 owner
- Stored-artifact retention and readability guarantees — API-11 owner

### Resolved 2026-07-20 (accountable-owner)

- **Source layout:** BOTH one-repo-per-study and a monorepo with a
  subdirectory per study are allowed; the published version pins the commit +
  subpath (exact subpath binding is API-01 detail).
- **Version-string constraints:** already settled — free-form, non-empty,
  unique and immutable within the study; no enforced semver (DECISIONS
  surface-02).
- Non-git-author uploaded-artifact path (post-v0) and stored-artifact retention
  (API-11) remain routed to their family gates.
