# API-01: Study Authoring, Compilation, and Publication

| Field | Value |
| --- | --- |
| Status | Draft |
| Contract revision | `0.2` |
| Accountable owner | Unassigned |
| Last updated | 2026-07-20 |
| Consumers | Researchers, study reviewers/publishers, compiler workers, API-02, API-04, API-10, and API-22 |
| Depends on | [Shared kernel revision 0.2](../shared-kernel/index.md), [API design standard](../api-design-standard.md), and proposed ADRs 0003, 0007, 0008, 0009, 0011, 0012, 0013, and 0015 |
| Implementation phase | Phase 1 compiler/manifests; Phase 2 durable catalog |
| Stability tiers | Public authoring, application command/query, wire, and archival |

## Outcome

API-01 replaces the current mutable experiment-object launch path with a narrow,
content-bound pipeline. Git owns study source; the platform owns compilation and
the immutable published record ([ADR 0013](../../decisions/0013-git-native-study-versioning.md)):

```text
authored Python source in the study's git repository
        │ capture named git state: commit SHA + patch of uncommitted changes
        ▼
normalized AuthoringDocument compiled from that exact source
        │ validate and compile one exact captured state
        ▼
ScientificManifest
  ├── ClientManifest template(s)
  ├── StudyServerManifest (private template)
  └── ProvenanceManifest (records GitProvenance)
        │ verify transitive closure; publish atomically under an
        │ author-supplied version string
        ▼
immutable StudyVersion (stored resolved artifact) + catalog metadata
```

MUG implements no drafts, no revisions, and no definition registry: branching,
diff, review, and collaboration on source are git's job. The platform compiles a
named git state, stores the resolved artifact (never rebuilt on demand), records
`GitProvenance`, and binds every result to the resolved version digest. The
platform retains existing author-facing outcomes, but there is deliberately no
source, callback, serialization, default, file-layout, or runtime behavioral
compatibility with `ExperimentConfig`, `Stager`, `Scene`, or `app.run()`.

## Contract set

| Document | Normative responsibility |
| --- | --- |
| [Current-MUG parity map](current-mug-parity-map.md) | Repository evidence, retained capabilities, and current hazards to eliminate |
| [Authoring and publication](authoring-and-publication.md) | Ownership, public types, commands/queries, git provenance, version strings, compiler jobs, diagnostics, publication transaction, errors, and recovery |
| [Manifests and packaging](manifests-and-packaging.md) | Five representations, manifest partitions, digest graph, study-code packages, capability closure, disclosure, and secret boundary |
| [Command and failure sequences](publication-sequences.md) | Capture/compile/publish acknowledgment, transaction, duplicate, lost-reply, and crash paths |
| [Schema bundle](schemas/index.md) | Exact version-0 persisted and archival shapes |
| [Golden fixtures](fixtures/index.md) | Valid and one-defect invalid contract examples |
| [Conformance plan](conformance.md) | Structural, semantic, privacy, determinism, transaction, and fault tests |
| [Review record](review-record.md) | Evidence, unresolved decisions, sign-offs, and promotion gate |

Where prose and schema shape disagree in revision 0.2, the schema controls the
portable shape and the mismatch is a Draft defect to resolve before version 1.
Domain-owned `TypedObject.data` schemas remain authoritative for their own
content after exact second-stage resolution.

## Ownership boundary

API-01 owns:

- The stable `Study` aggregate: published-version index, version-string
  reservations, and availability dispositions
- `GitProvenance` capture at publish (commit SHA, optional branch/remote,
  dirty flag, stored patch) and its collision-free binding to versions
- The pure validation/compilation contract and immutable result schemas
- Definition-key continuity checks derived from published history
- The scientific root manifest and deliberate client/server/provenance
  projections
- Publication preflight, content uniqueness, version-string uniqueness,
  atomic commit, and catalog queries

It does not own study source storage or source diff (git), deployment/secret
bindings (API-02), treatment and visit materialization (API-04), actor/channel/
environment execution (API-05 through API-08), evidence/artifact storage
semantics (API-10/API-11), domain-specific authoring meanings (their owning
APIs), study-code execution (the owning core runtime APIs), or durable job
mechanics (API-22). API-01's `TypedObject`, code-package,
capability-closure, and deployment-requirement fields are composition,
pinning, and projection wrappers. Their owning API's exact schema remains
authoritative; API-01 cannot create weaker duplicate semantics.

## Public and application interfaces

The API family has four distinct interface classes:

| Class | Initial surface |
| --- | --- |
| Public Python authoring | Frozen `StudySpec`, `FlowSpec`, closed flow-node union, domain-owned typed definitions, `CompilationPolicy`, and composition wrappers for study-code package, secret, and capability requirements |
| Pure build API | `StudyValidator.validate(source, context)`, `StudyCompiler.compile(source, context)`, and `StudyCompiler.diff(left, right)` over resolved versions |
| Application commands | Create/archive/restore study; request validation/compilation of a captured git state; publish under a version string; fork; deprecate/withdraw availability |
| Queries and archival formats | Study/version/diff queries plus exact authoring, diagnostic, manifest-set, and published-version schemas |

Validation and compilation always address an immutable captured source state
(commit + patch + finalized source artifact) and content-bound build context.
Slow or durable work runs as API-22 jobs under `JobId`; API-01 does not invent
a competing job lifecycle.

## Closed flow algebra

Version 0 defines these structural nodes:

| Node | Meaning at authoring time | Materialization owner |
| --- | --- | --- |
| `sequence` | Ordered child definitions | API-04 creates distinct occurrences |
| `activity` | Reference to one stable activity definition | API-04/API-06 start the occurrence/interaction |
| `randomized_select` | Candidate set, count, and exact rule | API-04 commits sampled outcomes before exposure |
| `repeat` | Exact repetition count over one definition | API-04 issues a separate occurrence per repetition |
| `branch` | Versioned condition cases and optional default | API-04 durably records dynamic decisions |
| `terminal` | Typed completion/ineligibility/withdrawal behavior | Owning completion/visit command commits it |

Compiler traversal is pure. It validates references, reachability, cycles,
terminal coverage, and rule shape but never samples participant randomization.
`FlowNodeDefinitionId`, `ActivityDefinitionId`, and
`ActivityOccurrenceId` are intentionally different identity classes.

## Non-negotiable publication boundary

A publishable candidate must bind exact git provenance, source bytes, compiler,
schema registry, build context, packages, artifacts, capabilities, normalized
defaults, and manifest bytes. Publication:

1. Revalidates the entire transitive closure and publication policy.
2. Rejects version 0, mutable references, missing closure, client leakage,
   secrets, integrity mismatches, and unacknowledged warnings.
3. Locks the `Study` aggregate and rechecks state, revision, and publication
   preconditions.
4. Uses unique `(study_id, scientific_manifest_digest)` content identity and
   a unique, immutable per-study version string: same content under its
   existing string is idempotent; same content under a new string is rejected;
   new content under a used string is rejected.
5. Atomically writes the immutable version, stored resolved artifact
   references, git provenance, receipt, canonical publication evidence event,
   and outbox.
6. Returns the existing version for content-identical publication without a
   second version or `study_version.published` event. A different command key
   gets its own durable `publication_resolved_existing` fact and receipt.

Publishing never mutates the source repository. Availability changes are
separate append-only catalog dispositions and never rewrite version bytes.

## Current executable evidence

The version-0 bundle currently has:

- 10 valid examples spanning normalized authoring, all four manifest roles, a
  closed manifest set, a validation report, clean and dirty git provenance,
  and a published version envelope
- 18 one-defect invalid examples spanning inline secret material, optional
  capability disposition, rejection of the retired `plugin.*` capability
  namespace and server binding kind, error suppression, duplicate definition
  keys, flow references/randomization, client disclosure, digest integrity,
  proposal-only publication, mutable executable location,
  dirty-without-patch and clean-with-patch provenance, malformed commit
  digests, patch integrity, missing provenance on a published version, and a
  blank version string
- 34 API-01 contract tests pass alongside the shared-kernel suite

Version 0 remains mutable and unpublishable. These tests are drafting evidence,
not acceptance or a production compiler implementation.

## Acceptance status

API-01 is `Drafted`, not `Accepted`. The [review record](review-record.md) keeps
the exact blockers. The highest-priority remaining work is:

1. Resolve the Python frontend/hermetic source-build boundary and code-signing
   policy. (Repo layout settled 2026-07-18: a repo may hold several studies via
   a repo-relative `source_path`; git is the only publication source.)
2. Compose the exact API-02-owned deployment-requirement object once API-02 is
   Accepted; the version-0 schema carries a fixture placeholder.
3. Complete domain-owned authoring schemas for the north-star scenarios.
4. Define API-11 artifact staging (including stored patch bytes and resolved
   version artifacts) and API-22 job integration precisely enough for
   publication crash tests.
5. Run independent browser/schema/canonicalization and client-disclosure
   checks.
6. Walk NS-01 through NS-08 and the current parity fixtures end to end.
7. Accept or supersede the dependent ADRs (including ADRs 0013 and 0015), assign
   reviewers, promote exact version-1 bytes, and prove the publication
   compiler rejects version 0.
