# ADR 0007: Explicit Client, Private Server, and Provenance Manifests

| Field | Value |
| --- | --- |
| Status | Accepted |
| Accepted | 2026-07-20 (ratification; client / server / provenance manifests folded in API-01; per-family freeze separate) |
| Date | 2026-07-16 |
| Owners | Unassigned |
| Affects | API-01, API-02, API-07 through API-10, API-12 through API-22 |

## Context

Automatically serializing public object attributes cannot reliably distinguish
browser-required configuration from prompts, blinded treatments, provider
settings, secrets, or scientific provenance. It may also silently omit values
that cannot be serialized.

## Decision

Study compilation produces three explicit versioned manifests:

- `ClientManifest`: the minimal participant/browser-authorized configuration
- `ServerManifest`: private scientific runtime configuration, prompts, tool
  policy, requested provider/model settings, private conditions, and logical
  `SecretRequirement`s
- `ProvenanceManifest`: content digests, versions, and content whose capture
  policy explicitly permits retention

Fields are placed deliberately through typed schemas. Compilation fails on
unknown or unserializable scientific configuration. API-01 never receives
secret material or `SecretRef`: it compiles logical `SecretRequirement`s. An
API-02 deployment-private overlay later binds those slots to
`SecretRef`s and is content-bound by `DeploymentRevision` (secret storage is a
minimal API-02/shared-kernel security mechanism; see ADR-0015). Secret material is
forbidden in every ordinary manifest; secret references are forbidden in the
client, scientific, server-template, and provenance bodies.

## Invariants

- Browser payloads contain no secret, private condition, hidden model identity,
  or unapproved prompt/tool content.
- The delivered client-manifest body contains no internal retention-policy or
  protected artifact identity; those remain in its authorized server-side
  artifact envelope.
- Every scientific input is represented or compilation fails.
- Manifest versions and digests are pinned to the study version/deployment.
- Operational secret rebinding does not alter scientific content silently.
- Actual secret binding cannot occur until an immutable deployment revision is
  created by the owning deployment API (API-02).

## Alternatives considered

### Filter one broad serialized dictionary at runtime

Rejected because deny-list filtering fails as new fields are added and cannot
provide a complete scientific manifest.

### Put everything except credentials in the browser payload

Rejected because prompts, private treatment information, tool policy, and model
identity may themselves be sensitive or blinding-critical.

## Validation

Golden client manifests for every acceptance scenario undergo schema validation
and secret/private-field scanning. Invalid or unserializable scientific fields
fail compilation rather than disappearing.
