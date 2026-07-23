# API-01 Schemas

| Field | Value |
| --- | --- |
| Status | Draft |
| Contract revision | `0.2` |
| Normative dialect | JSON Schema Draft 2020-12 |
| Last updated | 2026-07-20 |

## Draft version 0

- [`mug.api-01.study-authoring` schema bundle](v0/study-authoring.schema.json)

The current RFC 8785 canonical bundle digest is
`96958cdf2ab34fd541208d2adcd17f0d2c7d43ee2c1f5e433d2c87e323e2d58f`.
It identifies only this mutable review snapshot and will change whenever v0 is
edited.

The bundle reuses shared-kernel definitions by exact offline `$ref`; it does not
copy or weaken them. It currently defines:

- Authoring keys, study/flow-node/activity identifiers, and authored
  definitions (no draft, revision, or registry shapes; source identity is
  git-native per ADR 0013)
- `GitProvenance` (commit SHA, optional branch/remote, dirty flag, patch
  record with stored patch digest/size/artifact) and the `VersionString`
  handle
- A closed `FlowNode` union and `FlowSpec`
- Logical `SecretRequirement`, MUG-owned capability requirement/closure,
  `CodePackageRef` for pinned ordinary study code, and `CompilationPolicy`
- `AuthoringDocument`, compiler identity, projection references,
  `ScientificManifest`, `ClientManifest`, `StudyServerManifest`, and
  `ProvenanceManifest` (which records `source_git`), and `ManifestSet`
- `CompilationInputs`/`CompiledStudyCandidate` keyed by git provenance,
  diagnostics/reports, publication results, and `PublishedStudyVersion` with
  its required `version_string` and `git_provenance`
- Fixture-only domain schemas that exercise exact `TypedObject` resolution

All objects are strict and bounded. The dirty-implies-patch rule is a schema
conditional; cross-reference, graph, patch-integrity, client-disclosure,
manifest-closure, diagnostic-count, version-string-reservation, and
publication-version rules that JSON Schema cannot express are mandatory
semantic or transactional validation layers documented in the
[conformance plan](../conformance.md).

Version 0 is a mutable proposal and cannot appear in a published, deployed, or
archival object. Promotion creates a positive version with updated `$id`, exact
schema references and digests, regenerated fixtures, review of the exact bytes,
and an immutable retained directory. Offline readers must package the shared
kernel, this bundle, and every domain schema referenced by a retained manifest.
