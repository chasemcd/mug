# ADR 0012: Deterministic Study Compilation and Atomic Publication

| Field | Value |
| --- | --- |
| Status | Accepted |
| Accepted | 2026-07-20 as amended by ADR-0013 (git-native versioning) and ADR-0015 (governance removed): the deterministic-compile + atomic-publication substance stands; the draft / revision / definition-registry machinery referenced in the body is removed and is not part of the accepted decision |
| Date | 2026-07-17 |
| Owners | Unassigned |
| Superseded by | [ADR 0013](0013-git-native-study-versioning.md) in part (2026-07-18): the draft/revision/registry machinery (boundary 2, `DraftRevision`, `DefinitionRegistry`) is removed; deterministic compilation and atomic publication stand |
| Affects | API-01, API-02, API-04, API-10, API-11, API-20 through API-22 |

## Context

The current platform launches mutable Python configuration objects directly.
Validation and requirement discovery can mutate those objects; broad attribute
serialization can expose private configuration or silently drop unsupported
values; file/code/package identity depends on process state; and there is no
immutable compile/publication transaction. Rebuilding a flow can also rerun
randomization and change participant meaning.

The target platform needs ergonomic Python authoring without treating a live
Python object graph, callback identity, working directory, provider client, or
secret as a scientific archival format.

## Decision

API-01 uses four explicit boundaries:

1. Researchers construct frozen typed specifications. A frontend lowers them to
   a strict normalized `AuthoringDocument` under a declared build context.
2. Every committed source change creates an immutable `DraftRevision` bound to
   exact source bytes and a study-owned definition-registry snapshot.
3. A pure compiler validates one exact revision and content-bound context,
   resolves every default/reference/package/capability, and emits an acyclic
   manifest set: one complete `ScientificManifest` plus deliberately constructed
   client, private-server, and provenance projections.
4. The catalog publishes only a fully verified candidate in one transaction.
   Unique `(study_id, scientific_manifest_digest)` content identity makes
   content-identical publication resolve to one immutable `StudyVersion`.

Long-running validation and compilation use API-22 jobs, but their semantic
result remains pure and keyed by every source/toolchain input. If equal work
keys yield different canonical output, the compiler build is quarantined and
neither result is publishable.

Definition identity is managed by a study-owned registry. Rename preserves the
typed definition ID and permanently reserves the old key; tombstone preserves
history; fork creates a new `StudyId`, fresh definition IDs, and explicit
lineage. Flow rules compile without sampling. API-04 materializes and commits
randomization, branch, and repetition outcomes before exposure.

The scientific digest covers RFC 8785 canonical root-manifest bytes. It excludes
version ID, display ordinal, publication time/publisher, receipt/signature, and
warning acknowledgments. Child projections never point back to the root, so the
digest graph is acyclic.

## Scope and non-goals

This decision defines source/revision identity, compiler determinism, manifest
partitioning, and publication atomicity. It does not choose the Python modeling
library, build sandbox, package signature, storage vendor, or deployment
topology. It does not preserve any legacy authoring/runtime API. Functional
outcomes are retained through new typed contracts and ported fixtures.

## Invariants

- Validation, compilation, diff, and requirement discovery do not mutate source
  or sample participant decisions.
- Compilation addresses an immutable revision, exact registry snapshot, and
  complete content-bound context; it never means “current draft.”
- Unknown/unserializable scientific content is an error, not an omitted field.
- Published content contains only accepted positive schema versions and
  immutable offline-resolvable references.
- No secret material or `SecretRef` enters an API-01 source or manifest.
- Client projection is a positive allowlist and contains only the selected
  audience's authorized material.
- Publication is all-or-nothing with version, definition bindings, receipt,
  event, audit fact, and outbox.
- A published version and its manifest bytes are never mutated or deleted by an
  availability transition.
- Equal same-study scientific content creates at most one version and one
  publication event.

## Failure and operational consequences

Invalid scientific content is a successful compiler outcome with stable safe
diagnostics. Infrastructure failure remains a job/domain failure and cannot be
misreported as scientific invalidity. A crash before publication commit exposes
no version; a crash after commit returns the original receipt on retry. Missing
or unreadable candidate artifacts reject publication before any catalog effect.
Version numbers are allocated only inside the committing transaction.

Compilation may be more expensive because it packages and verifies the full
closure and may run deterministic double-build checks. That cost is paid before
recruitment to avoid scientifically ambiguous runtime behavior.

## Security and privacy effects

Python source evaluation is a privileged build action, never a server runtime
deserialization primitive. Hosted evaluation requires a separately accepted
isolated/hermetic build policy. Executable content becomes an immutable package
with entry point, ABI, dependency lock, capabilities, and trust class. Client
and provenance negative scans supplement schema destination metadata.

API-01 declares logical secret slots only. API-02/API-20 bind `SecretRef`s in a
deployment-private overlay, allowing credential rotation without rewriting a
scientific version while still requiring a deployment revision and audit.

## API, schema, and migration effects

- Add `StudyDraftId`, `DraftRevisionId`, and `FlowNodeDefinitionId` to the shared
  identifier registry.
- Add exact API-01 authoring, flow, registry, diagnostic, package, manifest-set,
  and publication schemas plus semantic validators.
- API-02 consumes the scientific capability/deployment requirements and binds a
  verified deployment overlay.
- API-04 consumes the compiled flow and stable definition IDs, then creates
  occurrence IDs and materialized outcomes.
- There is no legacy migration/adapter requirement. Existing studies are ported
  and compiled as parity fixtures.

## Alternatives considered

### Serialize one mutable object and filter fields

Rejected because omission and deny-list filtering cannot prove scientific
completeness or prevent new private fields from reaching a client.

### Use source paths, keys, or content hashes as every identity

Rejected because rename/edit/fork/occurrence semantics differ. Typed occurrence,
definition, version, and content identities remain distinct.

### Publish directly from a validation-successful draft head

Rejected because the head can race and prior validation does not bind current
source, registry, toolchain, artifact availability, or publication policy.

### Resolve randomization and secrets during compilation

Rejected because participant outcomes belong to durable visit materialization,
and secret binding belongs to an immutable deployment revision.

## Required acceptance tests

- Cross-runtime schema, typed-object, canonicalization, and privacy fixtures
- Compile-twice deterministic reference studies under perturbed ambient state
- Pure validation/compile proof with randomized flows
- Registry concurrent rename/tombstone/edit and fork fault cases
- Client projection adversarial disclosure tests for every domain schema
- Manifest transitive closure, digest tampering, missing artifact, and version-0
  rejection cases
- Concurrent identical/different publication and crash-before/after-commit tests
- NS-01 through NS-08 plus current static/form/game/P2P/server/external-client
  parity walkthroughs

## Follow-up decisions

- API-01 owner: Python frontend, hermetic source package, diff taxonomy, and
  historical-revision confirmation
- API-11 owner: finalized manifest-set handoff and artifact retention/readability
- API-20/API-21 owners: package trust/signature/SBOM, client destination
  metadata, and secret-binding policy
- API-22 owner: compilation work uniqueness, cancellation, lease, and result
  retention
