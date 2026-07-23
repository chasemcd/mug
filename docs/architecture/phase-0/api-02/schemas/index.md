# API-02 Schemas

| Field | Value |
| --- | --- |
| Status | Draft |
| Contract revision | `0.2` |
| Normative dialect | JSON Schema Draft 2020-12 |
| Last updated | 2026-07-19 |

The v0 bundle encodes the folded 0.2 surface (D03-1..5, F-4, R-20/R-21): the
two-verb, ungated (self-hosted; ADR-0015) operator surface with its internal
records. The five-op command vocabulary, grant coupling, and capability
closure of the 0.1 draft are gone.

## Draft version 0

- [`mug.api-02.platform-deployment` schema bundle](v0/platform-deployment.schema.json)

The current RFC 8785 canonical bundle digest is
`4fe71236a986f298966abe5ed4a6e9d1b53121a6b22de829eeb9a52826e09825`.
It identifies only this mutable review snapshot and will change whenever v0 is
edited.

The bundle reuses shared-kernel definitions by exact offline `$ref` (`Digest`,
`ArtifactRef`, `SecretRef`, `SemVer`, `CapabilitySet`, `DataHandlingRef`,
`StudyVersionRef`, `DeploymentRevisionRef`, and integer bounds). It defines:

- `DeploymentRequirement` (the typed object API-01 composes) and its data:
  logical secret requirements, execution slots, provider adapters, and region
  policy
- `Deployment` — the aggregate's live/stopped disposition (the only two
  dispositions; no grant or authority fields) pinning its current revision
- `DeploymentRevision` — the internal immutable record `mug deploy` creates:
  study version ref, `requirement_digest`, server/client/execution build
  bindings, provider and secret bindings (`SecretRef` only), region, and
  endpoints (participant or internal; localhost URLs allowed per R-20)
- `ClientDeploymentProjection` — the participant-safe positive-allowlist view
- `SatisfactionReport` — the internal secret/execution/region satisfaction
  proof, surfaced only as a deploy error; a revision ref exists exactly when
  `satisfied` is true
- Fixture-manifest schemas for the conformance harness

All objects are strict and bounded. Secret boundary, provider-binding integrity,
satisfaction closure, projection closure, disposition pinning, and digest
binding that JSON Schema cannot express are mandatory semantic layers
documented in the [conformance plan](../conformance.md).

Version 0 is a mutable proposal and cannot appear in a published, deployed, or
archival object. Promotion creates a positive version with an updated `$id`,
exact references and digests, regenerated fixtures, and review of the exact
bytes.
