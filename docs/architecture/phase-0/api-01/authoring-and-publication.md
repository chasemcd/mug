# API-01: Study Authoring and Publication

| Field | Value |
| --- | --- |
| Status | Draft |
| Contract revision | `0.2` |
| Owner | Unassigned |
| Consumers | Study authors, reviewers, publishers, compiler workers, API-02 deployment services |
| Last updated | 2026-07-20 |
| Depends on | [API design standard](../api-design-standard.md), [shared kernel](../shared-kernel/index.md), [ADR 0003](../../decisions/0003-immutable-study-versions-and-materialized-plans.md), [ADR 0007](../../decisions/0007-explicit-client-server-provenance-manifests.md), [ADR 0008](../../decisions/0008-shared-identifiers-serialization-and-schema-evolution.md), [ADR 0009](../../decisions/0009-command-receipt-idempotency-and-concurrency.md), [ADR 0011](../../decisions/0011-data-classification-retention-and-secret-references.md), [ADR 0013](../../decisions/0013-git-native-study-versioning.md), [ADR 0015](../../decisions/0015-governance-out-of-scope.md) |
| Supersedes | Revision 0.1's draft/revision/registry model, per ADR 0013 |
| Implementation phase | Phase 1 |
| Stability tier | Public authoring API, application command/query API, archival publication format |

## Goals

API-01 owns the path from git-managed study source to an immutable,
content-bound scientific version. It must:

- Give authors a typed source model for flow, activities, definitions,
  treatments, actors, channels, capture, privacy, and deployment requirements.
- Accept study source only from a named git state: the repository's current
  commit SHA plus a stored patch of any uncommitted working-tree changes.
- Record `GitProvenance` automatically at publish; a clean HEAD is not
  required.
- Bind each published version to a required, author-supplied version string
  that is unique and immutable within the study.
- Preserve stable definition-key identity by validating each candidate against
  the study's published history, not a mutable server-side registry.
- Validate and compile one exact captured source state under one exact
  toolchain.
- Produce explicit client, private-server, and provenance projections and
  compose an exact API-02-owned deployment-requirement object into the
  scientific root.
- Store the compiled, resolved artifact; never rebuild a published version on
  demand.
- Publish atomically and idempotently, with no partial or mutable version.
- Provide stable, safe diagnostics suitable for IDE, CLI, and control-plane
  clients.
- Preserve enough source and compiler provenance in the immutable publication
  artifact to explain and reproduce it while the researcher's institution
  retains those bytes.

## Non-goals

API-01 does not:

- Preserve the existing `ExperimentConfig`, `Stager`, `Scene`, builder, socket,
  callback, or metadata APIs.
- Implement drafts, revisions, branches, merges, source diff, or any other
  source-control feature. Git owns source history.
- Deploy or activate a study. API-02 binds a `StudyVersion` to an immutable
  `DeploymentRevision` and operational resources.
- Materialize participant visit plans or assign treatment. API-04 consumes the
  published protocol.
- Resolve secret values, contact a live model provider, or claim that a hosted
  provider backend is content-addressed.
- Run participant interactions, collect research data, or package replay.
- Accept non-git source. Git is the only publication source (settled
  2026-07-18); there is no uploaded-artifact path.
- Treat arbitrary working-directory state outside the captured commit + patch,
  mutable URLs, imported Python objects, or ambient integration discovery as
  publication inputs.
- Make MUG a general source-control, survey-authoring, or package-management
  system.

## Terminology and aggregate ownership

### `Study`

A stable scientific namespace. It owns:

- `StudyId`
- Open/archive status
- Optimistic `VersionStamp`
- The unique index from scientific-manifest digest to published version
- The unique, append-only index from version string to published version
- Append-only availability dispositions (deprecate/withdraw)

It contains no mutable source, drafts, or definition registry. Between
publications, git is the only source of truth.

### `GitProvenance`

The named git state captured automatically when the author publishes:

- `commit` — the repository HEAD commit SHA (40- or 64-hex)
- `branch` — optional branch name
- `remote` — optional remote URL
- `dirty` — whether the working tree differed from the commit
- `patch` — required exactly when `dirty`: the digest and size of the
  uncommitted-changes patch, with the patch bytes stored by the platform as a
  protected artifact so provenance stays whole

Commit + patch reconstructs the exact source state. A clean HEAD is not
required to publish. The pair is provenance, never identity: dedup identity is
the resolved-content digest.

### Version string

A required, author-supplied handle (for example `"2.1"`, `"pilot-3"`)
recorded with each publication. It is free-form and non-empty, unique within
the study, immutable once used, and the citable name for the version.
Collision rules:

| Publication input | Outcome |
| --- | --- |
| Same resolved content, same string | Idempotent; resolves to the existing version |
| Same resolved content, new string | Rejected: `publication.content_already_published` names the existing string |
| New resolved content, used string | Rejected: `publication.version_string_reserved` |

### Definition-key continuity

Definitions carry permanent author-chosen keys that live in the committed
source. Longitudinal identity is enforced at publish time by checking the
candidate's `(kind, key)` set against the study's published history: a key
that previously named a different definition kind or incompatible meaning is
`definition.key_incompatible_reuse`. There is no server-side registry,
allocation, rename, or tombstone command; renames and removals are ordinary
source edits whose compatibility is judged against published versions.

### Validation and compilation work

Validation and compilation execute as API-22 durable jobs and use `JobId`.
API-01 owns their job specifications and immutable result schemas; API-22 owns
queueing, status, worker leases, progress, cancellation, and terminal job
state. API-01 does not introduce validation-run or compilation-run IDs.

### `CompiledStudyCandidate`

An immutable, content-bound compilation result artifact built from a named git
state. A valid candidate contains the proposed scientific manifest and its
client, private-server, and provenance projections, plus the exact
`CompilationInputs` (git provenance, source artifact, compiler, schema
registry, build context, platform contract). Deployment requirements are an
API-02-owned typed, content-bound object composed into the scientific
manifest; the version-0 schema carries a fixture placeholder until API-02 is
Accepted. An invalid compilation contains a diagnostic report and no
publishable candidate.

### `StudyVersion`

An immutable publication occurrence identified by `StudyVersionId` and bound
to one scientific-manifest digest, one version string, and one recorded
`GitProvenance`. The resolved artifact bytes are stored; results and evidence
bind to the stored version digest. The occurrence ID is not a content hash.
Publication time, publisher, display ordinal, and warning approvals are
catalog metadata excluded from the scientific-manifest digest.

## Author-facing source API

The public Python API consists of immutable typed specifications evaluated
from plain Python modules in the study repository. The concrete validation
library remains an implementation choice; its incidental behavior must not
become the public contract. The names below describe the composition surface,
not a transfer of domain ownership to API-01: `StudySpec`, `FlowSpec`, and
compilation policy are API-01 concerns, while the other specifications are
imported from their owning APIs and retain those APIs' exact schemas and
semantics.

```python
StudySpec
FlowSpec
ActivitySpec
ContentActivitySpec
InteractionActivitySpec
PreferenceActivitySpec
CompletionActivitySpec
TreatmentSpec
FactorSpec
ConditionSpec
AssignmentPolicySpec
SeatSpec
ChannelSpec
ControllerSpec
CapturePolicySpec
DataPolicySpec
DeploymentRequirementsSpec
```

`DeploymentRequirementsSpec` is owned by API-02; treatment, assignment, and
participant-state types are owned by API-03/API-04; seat/controller,
interaction, environment, and conversation types are owned by API-05 through
API-08; capture and data-policy meanings are owned by API-10. API-01 owns the
closed composition slots, stable references, projection placement, and
whole-study validation across those values. It may not duplicate their fields
into weaker API-01-native alternatives.

The frontend produces an exact `AuthoringDocument`; polymorphic domain specs
inside it are `TypedObject` values. Large code, assets, environment packages,
models, prompt collections, and client components are already-finalized
`ArtifactRef` values; they are not embedded as arbitrary Python objects. Every
definition declaration carries a definition kind, authoring key, and typed
definition reference so an accidental key substitution cannot silently change
identity.

The authoring library may provide ergonomic constructors, but its serialized
document must make every default explicit before compilation. Unknown or
unserializable scientific values are errors, never silently dropped fields.
Local `check()` runs the same pure validation with no platform state.

## Persisted model

Conceptually, the owned records are:

```python
@dataclass(frozen=True)
class GitPatch:
    patch_digest: Digest
    size_bytes: int
    artifact: ArtifactRef | None


@dataclass(frozen=True)
class GitProvenance:
    commit: str
    branch: str | None
    remote: str | None
    dirty: bool
    patch: GitPatch | None


@dataclass(frozen=True)
class CompilationInputs:
    git_provenance: GitProvenance
    source: ArtifactRef
    compiler: CompilerIdentity
    schema_registry_digest: Digest
    build_context_digest: Digest
    target_platform_contract: SchemaRef
    compilation_policy: CompilationPolicy


@dataclass(frozen=True)
class CompiledStudyCandidate:
    input_fingerprint: Digest
    inputs: CompilationInputs
    manifest_set: ManifestArtifact
    validation_report: ArtifactRef
    scientific_manifest_digest: Digest
    release_eligibility: str


@dataclass(frozen=True)
class StudyVersion:
    ref: StudyVersionRef
    version_string: str
    git_provenance: GitProvenance
    candidate: ArtifactRef
    scientific_manifest: ArtifactRef
    client_manifests: tuple[ArtifactRef, ...]
    server_manifest: ArtifactRef
    provenance_manifest: ArtifactRef
    published_at: UtcInstant
    published_by: PrincipalRef
```

These shapes are explanatory projections; the exact persisted and archival
contract is the [API-01 version-0 schema bundle](schemas/v0/study-authoring.schema.json).
Every embedded polymorphic value uses a `TypedObject` with an exact accepted
`SchemaRef` and mandatory second-stage validation under the
[command contract](../shared-kernel/commands-receipts-and-errors.md).

## Git capture

Publication input is the working tree of the author's study repository plus
its authored Python source, compiled directly:

1. The platform resolves the repository's current HEAD commit SHA.
2. If the working tree is dirty, it produces a deterministic patch of the
   uncommitted changes and finalizes the patch bytes as a protected artifact.
3. It normalizes the authored source into an `AuthoringDocument` and finalizes
   that artifact.
4. `GitProvenance` (commit, optional branch/remote, dirty flag, patch record,
   optional `source_path`) is bound into the compilation inputs and recorded on
   the published version.

One repository may hold several studies: a study may declare a repo-relative
root directory, recorded as `source_path` (settled 2026-07-18). The commit and
patch always cover the whole repository; `source_path` scopes which subtree the
authored source is normalized from, not what provenance captures.

Failure to resolve a commit is `git.provenance_unavailable`; failure to
capture a dirty tree's patch is `git.patch_capture_failed`. Neither failure
creates platform state. The stored patch may contain anything in the working
tree; it is protected provenance data and never enters client manifests.

### Fork

Forking accepts an immutable source `StudyVersionRef` and creates a new
`StudyId` bound to a new source location (typically a forked or branched
repository), with recorded lineage to the parent version. It copies design,
never enrollment, participant identity, deployment, secret binding, response,
interaction, or research data. Referenced artifact bytes may be reused only
when API-11 can verify the exact readable artifact and the researcher's
external privacy, storage, and licensing rules permit reuse; otherwise the fork
fails closed or uses separately stored bytes. MUG records lineage but does not
enforce those institutional rules.

## Application commands

All mutations use the shared `WireCommandEnvelope`, trusted `CommandContext`,
typed `CommitReceipt`, exact payload/result schemas, optimistic preconditions,
and server-resolved target and effect-time state.

```python
StudyCommandService.create(
    command: CreateStudy,
    ctx: CommandContext,
) -> CommitReceipt[StudyCreated]

StudyCommandService.archive(
    command: ArchiveStudy,
    ctx: CommandContext,
) -> CommitReceipt[StudyArchived]

StudyCommandService.restore(
    command: RestoreStudy,
    ctx: CommandContext,
) -> CommitReceipt[StudyRestored]

StudyValidationService.request(
    command: RequestStudyValidation,
    ctx: CommandContext,
) -> CommitReceipt[JobCreated]

StudyCompilationService.request(
    command: RequestStudyCompilation,
    ctx: CommandContext,
) -> CommitReceipt[JobCreated]

StudyPublicationService.publish(
    command: PublishStudyVersion,
    ctx: CommandContext,
) -> CommitReceipt[StudyVersionPublished]

StudyForkService.fork_from_version(
    command: ForkStudyVersion,
    ctx: CommandContext,
) -> CommitReceipt[StudyForked]

StudyAvailabilityService.deprecate(
    command: DeprecateStudyVersion,
    ctx: CommandContext,
) -> CommitReceipt[StudyVersionDeprecated]

StudyAvailabilityService.withdraw(
    command: WithdrawStudyVersion,
    ctx: CommandContext,
) -> CommitReceipt[StudyVersionWithdrawn]
```

`RequestStudyValidation` and `RequestStudyCompilation` identify one exact
captured source state (git provenance + finalized source artifact digest);
they never mean "whatever the working tree is when a worker starts." API-22's
`JobService.status(JobId)` and cancellation API own mutable job state.

`CreateStudy` is an aggregate-bootstrap command, so its wire target cannot be a
`StudyId` that does not exist yet. Its `CommandContext.runtime_protocol` is
`None`, and the server must resolve a real pre-publication catalog scope
before claiming idempotency or allocating the new `StudyId`. Revision 0.2 has
not selected that target resource type or its `expected_absent` uniqueness
key. An implementation must not work around the gap with a fabricated study
ID, a nullable untyped target, or a process-global catalog singleton; the exact
bootstrap target and scope are an open version-1 decision.

## Queries

```python
StudyQueryService.get(study_id: StudyId) -> StudyView
StudyQueryService.list_versions(study_id: StudyId, cursor: PageToken | None) \
    -> StudyVersionPage
StudyQueryService.get_version(version_id: StudyVersionId) -> StudyVersion
StudyQueryService.get_version_by_string(
    study_id: StudyId,
    version_string: str,
) -> StudyVersion
StudyQueryService.diff_versions(left: StudyVersionId, right: StudyVersionId) \
    -> StudyVersionDiff

StudyValidationQueryService.result(job_id: JobId) -> ValidationOutcome
StudyCompilationQueryService.result(job_id: JobId) -> CompilationOutcome
```

`diff_versions` compares two published **resolved** versions (definitions and
flow); source-level diff is git's job. A resolved diff can expose a behavior
change with zero source diff, such as a dependency bump.

Queries keep the public catalog view, source, private manifest, provenance, and
diagnostics as distinct outputs. MUG v0 evaluates no operator roles or grants;
the deployment perimeter and the researcher's storage controls determine which
of those endpoints and stored bytes are exposed.

## Lifecycle and state machines

### Study

```text
                  archive
create → OPEN ─────────────→ ARCHIVED
           ↑                    │
           └────── restore ─────┘
```

- Open studies may compile and publish.
- Archived studies reject those mutations.
- Archive does not terminate a deployment or active visit; API-02/API-04 own
  those transitions.

### Validation and compilation job

```text
QUEUED → RUNNING → SUCCEEDED_VALID
                 → SUCCEEDED_INVALID
                 → FAILED_TRANSIENT
                 → FAILED_INTERNAL
                 → CANCELLED
```

API-22 owns the generic lifecycle labels; the API-01 result distinguishes
valid from invalid scientific content. `SUCCEEDED_INVALID` is successful tool
execution with diagnostics, not an infrastructure error.

### Study version

```text
valid compiled candidate → PUBLISHED IMMUTABLE
```

A separate availability projection may become deprecated or withdrawn. That
does not mutate or delete the version, its manifests, its stored artifact, or
its archival reader.

## Validation

The pure compiler-facing interface is:

```python
StudyValidator.validate(
    source: CompilationInputs,
    context: ValidationContext,
) -> ValidationReport
```

The validation work key contains:

```text
source artifact digest
git provenance (commit + patch digest when dirty)
validation profile and schema reference
validator/compiler artifact digest
schema-registry digest
```

The exact work key is unique. Repeating it returns the existing API-22 job or
result instead of executing duplicate work.

Validation covers source shape, identity, graph reachability, flow
termination, treatment and randomization definitions, references, execution
capabilities, public/private manifest placement, privacy labels, schema
versions, artifact immutability, definition-key continuity against published
history, and publication constraints.

## Compilation

The pure compiler-facing interface is:

```python
StudyCompiler.compile(
    source: CompilationInputs,
    context: CompilationContext,
) -> CompilationOutcome
```

`CompilationContext` is immutable and contains exact compiler artifact,
compiler contract, schema-registry digest, build-context digest, and target
platform contract. Compilation must not read undeclared working-directory
state beyond the captured commit + patch, perform mutable package resolution,
resolve secrets, call a provider, or discover integrations dynamically.

Compilation:

1. Re-runs authoritative validation; an older report is not trusted as proof.
2. Resolves all defaults and definition references.
3. Verifies every code, environment, model, prompt, tool, component, and asset
   reference is declared, immutable, and content-bound.
4. Produces an immutable scientific manifest plus explicit client,
   private-server, and provenance projections. The provenance projection
   records the `GitProvenance` of the captured source. The accepted
   scientific schema must carry API-01's logical capability closure and one
   exact API-02-owned deployment-requirement object; the version-0 schema
   composes a fixture placeholder for the latter.
5. Verifies no client-forbidden field appears in the client manifest.
6. Verifies no secret value appears in any output. Allowed logical secret slots
   remain unresolved references.
7. In release mode, uses only accepted positive schema versions. Design mode
   may emit version 0 only with an explicit `unpublishable` result class; the
   publication service rejects that closure unconditionally.

The compilation work key contains:

```text
source artifact digest + git provenance
+ compiler artifact digest + compiler contract + schema-registry digest
+ build-context digest + target-platform contract
```

Identical work keys must produce byte-identical canonical output and the same
scientific-manifest digest. Different output is
`compiler.nondeterministic_output`; the compiler build and both candidates are
quarantined from publication.

Hosted-model source pins the logical selector, configuration, fallback rule,
and required MUG capabilities. API-02 owns the concrete provider adapter,
endpoint, region/residency setting, and `SecretRef` binding. Actual
provider-resolved model identity is recorded later as deployment/interaction
exposure.

## Diagnostic contract

```python
Diagnostic(
    fingerprint=...,
    code=...,
    severity="error" | "warning" | "info",
    stage="source" | "identity" | "flow" | "capability" |
          "privacy" | "manifest" | "publication",
    safe_message=...,
    primary_location=SourceLocation(...) | None,
    related_locations=(...),
    definition=ResourceRef(...) | None,
    suppressible=...,
)
```

Diagnostics have deterministic fingerprints and ordering for identical input
and toolchain. Client-safe or public views never include secret values, raw
protected source, provider errors, or private object names. Restricted snippets
may be placed in a separately stored researcher artifact outside those views.

- Errors are non-waivable and make the candidate invalid.
- Warnings follow a versioned publication policy.
- Warning acknowledgment binds to diagnostic fingerprint, candidate digest,
  acknowledging principal, and policy version—not message text or array
  position. The principal is publication provenance, not a role or grant.
- Candidate changes invalidate acknowledgments that no longer match.
- Informational diagnostics never silently alter compiled output.

Scientific invalidity is a `ValidationReport`/`CompilationOutcome`, not a
`DomainError`. Invalid command context, missing or unreadable required input,
worker crash, dependency outage, or unsupported compiler is an error.

## Publication

`PublishStudyVersion` carries:

```python
PublishStudyVersion(
    study_id: StudyId,
    version_string: str,
    note: str | None,
    candidate: ArtifactRef,
    compilation_job_id: JobId,
    expected_study_revision: int,
    warning_acknowledgments: tuple[DiagnosticAcknowledgment, ...],
)
```

The author types the version string; the git commit and patch were captured
when the candidate's source state was compiled and travel inside the
candidate. There is no draft-head precondition: the candidate names its exact
source, and the only optimistic precondition is the study aggregate revision.

### Preflight

Before publication commits, API-01 verifies:

- Candidate status is valid and belongs to the target study.
- Candidate, manifest, and artifact digests verify, including the stored
  patch artifact when the source was dirty.
- Git provenance, source artifact, compiler, schemas, and build context match
  the candidate.
- Compiler/schema versions remain permitted for publication.
- Referenced artifacts are committed, readable, and integrity-verified by
  API-11.
- Client, server, and provenance projections agree with the scientific root,
  including its logical capability closure and composed deployment
  requirements.
- No mutable reference, version-0 schema, or secret value is present.
- Errors are absent and required warnings have valid acknowledgments.
- The version string is well-formed and either unused or bound to this exact
  content digest.
- Definition keys are compatible with the study's published history.
- Study is open and expected study revision still matches.
- The command target and effect-time study state still permit publication.

Any race-sensitive check is repeated under the publication transaction.

### Atomic commit

The relational Unit of Work:

1. Locks the `Study` aggregate.
2. Rechecks state, revision, artifact status, and content digest.
3. Checks unique `(study_id, scientific_manifest_digest)` and the
   version-string reservation.
4. Allocates the next display version number.
5. Issues `StudyVersionId`.
6. Inserts the immutable version header, version-string binding, git
   provenance, manifest/artifact links, and stored-artifact references.
7. Updates the study digest and version-string indexes.
8. Commits aggregate revision, canonical publication evidence event,
   idempotency result/receipt, and outbox entries atomically.

No partial version or manifest subset is visible. Artifact bytes are already
finalized and verified before the transaction references them.

If step 3 finds byte-equal existing content under the same version string, the
transaction skips steps 4 through 7: it allocates no version/ordinal and does
not revise the `Study`. Instead it atomically commits the caller's terminal
receipt, canonical publication-resolution evidence event, and outbox entry
referencing the existing version. Byte-equal content under a **new** string, or
new content under a **used** string, terminates with the version-string
collision errors below and no catalog effect. A digest match with unequal
canonical bytes is quarantined as an integrity incident.

### Publication idempotency and concurrency

- Same idempotency scope/key/fingerprint returns the original immutable
  receipt.
- Scientific-manifest digest is unique within a study; version strings are
  unique within a study and bind 1:1 to a digest.
- A different command key for the same digest and string resolves to the
  existing `StudyVersion`; it never creates another scientific version or
  `study_version.published` event. It commits its own terminal receipt and
  `study_version.publication_resolved_existing` evidence event so the new
  command has a valid durable stream position without impersonating the
  original command/receipt.
- Equal digests with unequal canonical bytes are an integrity incident.
- Concurrent different candidates serialize on the study lock and receive
  distinct display ordinals in commit order.
- A failed transaction consumes no visible display ordinal, version, or
  version-string reservation.
- Publication does not mutate the source repository or candidate content.

## Deployment and institutional access boundary

MUG v0 defines no operator grants, roles, or permission checks for authoring,
compilation, publication, catalog changes, or queries. The self-hosted
deployment and the researcher's institution control access to the service,
repository, database, object store, private manifests, diagnostics, and stored
patches outside this API. IDs and authoring keys are identifiers, not storage
credentials. API-11 still verifies that every artifact required by compilation
or publication is committed, readable, and unchanged at the effect boundary.

An institution may require independent review or two-person publication in its
external workflow without changing the immutable candidate or making that
workflow a MUG policy subsystem.

## Ordering, concurrency, and transaction invariants

- The `Study` aggregate has one optimistic revision; there are no draft or
  registry aggregates.
- Version-string reservations and digest uniqueness are enforced inside the
  publication transaction, never by a pre-check alone.
- No automatic merge, key-rename inference, assignment recomputation, or
  warning reapproval occurs after conflict.
- Queries never mutate "last viewed," diagnostics, source, or publication
  state.
- Duplicate delivery creates no duplicate job, version, version-string
  binding, or canonical event.

## Timeout, cancellation, reconnect, and recovery

- Create/archive/publish/fork final commits are short transactional commands.
  Cancellation after commit cannot roll them back.
- Validation and compilation are API-22 jobs. Cancellation is best effort and
  never mutates the captured source artifacts.
- Compiler worker loss returns the same job to its declared retry policy.
- A worker never publishes; only the publication service can commit a version.
- Lost reply after a commit is recovered using the original idempotency key.
- A source, patch, or result artifact uploaded without a committed reference
  is an orphan governed by API-11 cleanup.
- Study archive during a job does not corrupt the job result, but subsequent
  publication rejects while archived.
- Artifact loss or integrity failure after compilation prevents publication;
  the service never substitutes another artifact silently.
- Restoring an archived study does not make a stale candidate current; all
  publication preconditions still apply.

## Error codes and safe diagnostics

### Study, capture, and continuity

```text
study.not_open
study.revision_conflict
git.provenance_unavailable
git.patch_capture_failed
definition.key_incompatible_reuse
```

### Validation, compilation, publication, and fork

```text
validation.profile_unsupported
compiler.version_unsupported
compiler.dependency_unavailable
compiler.internal_failure
compiler.nondeterministic_output
publication.candidate_invalid
publication.candidate_integrity_failed
publication.candidate_not_from_study
publication.compiler_not_allowed
publication.schema_not_allowed
publication.warning_unacknowledged
publication.artifact_unavailable
publication.unpinned_content
publication.secret_detected
publication.digest_integrity_failure
publication.version_string_required
publication.version_string_reserved
publication.content_already_published
fork.source_not_published
fork.source_unavailable
fork.artifact_not_shareable
```

Invalid flow, missing definition reference, unsupported capability, unsafe
manifest placement, or invalid privacy/data-flow declaration normally appears
as a compiler diagnostic. The command-level errors above describe inability to
execute the requested lifecycle transition safely.

Public errors follow the shared error contract. They do not expose source,
prompts, private condition names, secret slots, filesystem/provider errors, or
unrelated private artifact contents.

## Privacy, storage ownership, and projection boundaries

- Compiler inputs and outputs are private research-design data by default.
- Source may contain prompts, blinded conditions, tool configuration,
  preregistration material, copyrighted assets, and security-sensitive
  topology. Source, client manifest, private server manifest, provenance, and
  diagnostics remain distinct storage and projection objects.
- The stored patch may contain anything in the author's working tree. It is
  server-side protected provenance, never client-deliverable, and inherits the
  source's classification.
- `StudyVersion` contains logical `SecretRequirement` slots only where
  permitted; neither `SecretRef` nor secret value is accepted by authoring,
  compilation, diagnostics, artifacts, or publication.
- The client manifest is a deliberate allowlisted projection, not a filtered
  copy of private source.
- Diagnostic locations inherit the source's classification; protected snippets
  or structured private parameters live only in a separately stored researcher
  artifact, not the portable report.
- Fork validation checks lineage and artifact integrity. Licensing, retention,
  deletion, and institutional data-processing decisions remain external to MUG.
- Archiving or withdrawing a version does not erase retained evidence or the
  stored resolved artifact; the researcher's institution controls deletion from
  its stores.

## Events, artifacts, provenance, and observability

### Canonical API-01 events

```text
study.created
study.archived
study.restored
study_validation.requested
study_compilation.requested
study_version.published
study_version.publication_resolved_existing
study_version.deprecated
study_version.withdrawn
study.forked_from
```

API-22 emits generic job lifecycle evidence. API-01 job result artifacts state
whether validation/compilation was valid, invalid, cancelled, transiently
failed, or internally failed. Mutation events carry IDs, digests, version
strings, and safe metadata, not full private source, patches, or diagnostics.

Duplicate command delivery produces no second canonical event. Resolving a
content-identical publication to an existing version produces no second
`study_version.published` event, but a new accepted command key commits the
explicit resolution event and its own receipt. The resolution event changes no
study/version content or display ordinal.

### Required publication provenance

- Git provenance: commit SHA, dirty flag, and stored patch digest/artifact
- Source artifact digest and exact compiler artifact and contract
- Schema-registry and build-context digests
- Scientific/client/server/provenance manifest digests and the scientific
  root's logical capability closure plus its composed deployment requirements
- Every referenced artifact digest and content schema
- Version string, warning policy, and acknowledgments as publication metadata
- Publisher attribution plus publication command, receipt, and canonical event
  references
- Fork lineage, if applicable

Operational compiler logs and traces correlate through job/command IDs but are
not canonical scientific evidence and must not contain source or secrets by
default.

## Capability validation and unsupported behavior

Compilation uses a pinned compiler, offline schema registry, immutable artifact
closure, and a closed set of MUG-owned platform capabilities. Runtime discovery
cannot change a candidate or published version. Unsupported combinations fail
with diagnostics before publication.

The accepted compiler output composes declarative API-02-owned
`DeploymentRequirements`; it does not select a mutable production worker,
provider endpoint, or secret. API-01's `CapabilityRequirement` records a
logical capability, criticality, and—for optional observational capture—the
omission/completeness facts. It does not name a provider. API-02 must later
prove that one immutable deployment revision satisfies every requirement. It
may not silently degrade a scientific requirement.

## Scenario mapping

This section records future acceptance obligations. It does not claim that the
current minimal version-0 fixture or semantic harness can compile these domain
protocols today; each scenario becomes executable only after its owning APIs
publish exact schemas and API-01 composes them.

- NS-01 and NS-02 require immutable trajectory/output preference protocols and
  candidate schemas in the published version.
- NS-03 through NS-07 require explicit actor, channel, controller, provider,
  context, and compound-output definitions that compile without browser-private
  leakage.
- NS-08 exercises longitudinal version identity across hand-typed version
  strings, persisted protocol transition, and exact recovery under an
  intentionally different later study version.
- NS-09 requires the P2P execution/capture requirements to be explicit in the
  manifests rather than inferred at runtime.
- NS-12 verifies private source, secret references, institutional storage,
  export, and fork boundaries.
- Functional-parity fixtures must be rewritten through the authoring API for
  browser, P2P, server, conventional policy, rendering, forms, Unity/external
  client, and administration capabilities.

## Contract tests and golden fixtures

At minimum:

1. Publish from a clean HEAD records commit provenance with no patch.
2. Publish from a dirty tree records commit + stored patch; commit + patch
   reconstructs the compiled source exactly.
3. Publication without a resolvable commit or capturable patch fails with no
   catalog effect.
4. Identical publish retry returns the original receipt.
5. Same content republished under its existing string resolves to the
   existing version with a reuse fact, not a second version.
6. Same content under a new string is rejected naming the existing string.
7. New content under a used string is rejected as reserved.
8. A version string, once bound, never rebinds to a different digest.
9. Duplicate validation/compilation work keys return one API-22 job/result.
10. Invalid source produces deterministic diagnostics, not infrastructure
    failure.
11. Identical compiler inputs produce byte-identical candidates.
12. Nondeterministic compiler output quarantines the compiler/candidates.
13. Version-0 schema, mutable artifact, client-private field, or secret value
    blocks publication.
14. Warning acknowledgment cannot be reused for changed content.
15. Definition-key reuse incompatible with published history fails at publish.
16. Artifact loss between compile and publish creates no version.
17. Two concurrent identical publications produce one version.
18. Two concurrent different publications receive distinct commit-ordered
    display ordinals; version-string collisions serialize on the study lock.
19. Crash before publication commit leaves no visible version or string
    reservation.
20. Crash after commit/before reply returns the original receipt.
21. Resolved-version diff detects a behavior change with zero source diff.
22. Fork creates a fresh study with complete lineage and no data, deployment,
    or secret copying; fork crash leaves no partial destination study.
23. Archive during compilation allows the result but blocks publication.
24. Withdrawal preserves immutable bytes, the stored artifact, and archival
    lookup.
25. Safe diagnostic/error fixtures contain no protected source, patch
    contents, or secrets.

## Non-negotiable invariants

1. Compilation/publication always name an exact captured git state (commit +
   patch + source digest).
2. Every published version records `GitProvenance`; dirty publication stores
   the patch bytes.
3. The stored resolved artifact is the published version; versions are never
   rebuilt on demand.
4. A version string is unique and immutable within a study and maps 1:1 to
   one resolved-content digest.
5. Definition-key continuity is derived from published history; incompatible
   reuse fails at publish time.
6. Forks use new study IDs and recorded lineage.
7. Validation/compilation bind source, git state, compiler, schema, build, and
   platform-contract inputs exactly.
8. Identical compilation work input has exactly one canonical output digest.
9. Invalid scientific content is a report, not a fabricated runtime failure.
10. Published versions contain only immutable references and accepted schemas.
11. No secret value enters source, patches, publication artifacts, or
    diagnostics.
12. Publication creates one immutable version per study/manifest digest.
13. Publication atomically commits version, string binding, provenance,
    canonical evidence event, idempotency receipt, and outbox.
14. Availability/deprecation never mutates scientific bytes.
15. Warning approval is explicit and content-bound.
16. Between publications, the platform holds no mutable pre-publication study
    state; git is the only source of truth.
17. Display ordinal, aggregate revision, version string, schema version, job
    state, and event sequence are distinct.

## Alternatives rejected

### Keep an in-platform draft/revision/registry subsystem

Rejected by ADR 0013: it duplicates git with weaker tooling, adds mutable
aggregate state and precondition races, and serves no approved user journey.

### Publish directly from a mutable Python object

Rejected because working memory, imports, defaults, and files can change between
validation and publication and cannot form durable provenance. The captured
commit + patch + finalized source artifact is the durable input.

### Record commit + lockfile and rebuild on demand

Rejected because reproducibility would depend on future toolchain availability
and behavior. Publication stores resolved immutable outcomes (ADR 0013).

### Require a clean committed HEAD to publish

Rejected because it adds friction without adding evidence; commit + stored
patch reproduces the exact source state either way.

### Derive the version handle from the digest or an ordinal

Rejected because authors and papers need a name they control; content
addressing still deduplicates underneath the hand-typed string.

### Use authoring keys or source paths as identity

Rejected because rename/refactor would silently create a new scientific entity
or rewrite historical identity; continuity is checked against published
history instead.

### Let compilation resolve production secrets/providers

Rejected because it leaks deployment-specific provider binding into scientific source and
makes identical source compile differently across deployments.

## Unresolved questions and required decisions

- Exact authoring validation implementation and Python package surface
- Monorepo versus one-repo-per-study source layout and the exact git capture
  mechanics (patch format, submodules, LFS)
- Version-string character/length constraints beyond non-empty/trimmed
- Initial definition-kind registry of kinds and which definitions have
  independent version types outside `StudyVersion`
- Maximum inline source-document size and artifact threshold
- Warning policy and content-bound acknowledgment rules; any two-person review
  remains external to MUG
- Exact study archive/restore and version deprecation/withdrawal command
  semantics
- Supported fork artifact-sharing/licensing policies
- Execution and isolation requirements for ordinary study-code packages under
  their owning core runtime protocols
- Exact API-02-owned deployment-requirement object binding once API-02 is
  Accepted
- Aggregate-bootstrap target, uniqueness key, and idempotency scope for
  `CreateStudy` before a `StudyId` exists
- Deregistering the retired `studydraft_`/`draftrev_` prefixes from the
  shared-kernel identifier registry (shared-kernel follow-up)

This specification cannot become Accepted until all dependencies above are
Accepted, every command/query and archival shape is exact, and its schema,
error, event, job, privacy, scenario, and fault fixtures pass review.
