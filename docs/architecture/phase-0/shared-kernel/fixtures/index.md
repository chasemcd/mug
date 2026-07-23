# Shared-Kernel Golden Fixtures

| Field | Value |
| --- | --- |
| Status | Draft |
| Last updated | 2026-07-20 |

The machine-readable [version-0 manifest](v0/manifest.json) maps every instance
to an exact schema fragment and expected result.

## Valid fixtures

- [Full wire command](v0/valid/wire-command.full.json)
- [Accepted commit receipt](v0/valid/command-receipt.accepted.json)
- [Indeterminate external-effect receipt](v0/valid/command-receipt.indeterminate.json)
- [Privacy-safe domain error](v0/valid/domain-error.revision-conflict.json)
- [Artifact reference](v0/valid/artifact-ref.json)
- [Pinned secret reference](v0/valid/secret-ref.pinned.json)
- [Canonicalization vector set](v0/valid/canonicalization-vectors.json)
- [Canonical inline bytes](v0/valid/inline-bytes.json)
- [Canonical capability set](v0/valid/capability-set.json)
- [Public handle](v0/valid/public-handle.json)

## Invalid fixtures

- [Client asserts trusted principal](v0/invalid/wire-command.principal-claim.json)
- [Conflicting expected-absent/revision preconditions](v0/invalid/wire-command.conflicting-preconditions.json)
- [Payload fails its exact domain schema](v0/invalid/wire-command.domain-payload.json)
- [Payload cites the wrong domain-schema digest](v0/invalid/wire-command.domain-schema-digest.json)
- [Command cites a different registered payload schema](v0/invalid/wire-command.command-schema-binding.json)
- [Receipt contains both result and error](v0/invalid/command-receipt.result-and-error.json)
- [Accepted commit has no stream position](v0/invalid/command-receipt.accepted-empty-streams.json)
- [Indeterminate effect requests automatic retry](v0/invalid/command-receipt.indeterminate-same-command.json)
- [Secret reference contains raw value](v0/invalid/secret-ref.inline-value.json)
- [Artifact reference leaks storage URI](v0/invalid/artifact-ref.storage-uri.json)
- [Data handling carries a retired retention-policy reference](v0/invalid/artifact-ref.retention-policy.json)
- [Artifact privacy labels are noncanonical](v0/invalid/artifact-ref.privacy-order.json)
- [Noncanonical identifier](v0/invalid/resource-ref.uuid4.json)
- [Generic reference asserts a separate kind](v0/invalid/resource-ref.kind-claim.json)
- [Unregistered identifier prefix](v0/invalid/resource-ref.unregistered-prefix.json)
- [Noncanonical timestamp](v0/invalid/domain-error.timestamp-offset.json)
- [Uppercase digest](v0/invalid/artifact-ref.uppercase-digest.json)
- [SemVer numeric prerelease has a leading zero](v0/invalid/semver.leading-zero-prerelease.json)
- [W3C trace context uses an all-zero trace ID](v0/invalid/trace-context.zero-trace-id.json)
- [Inline bytes use an impossible base64url length](v0/invalid/inline-bytes.noncanonical-length.json)
- [Inline byte count disagrees with decoded data](v0/invalid/inline-bytes.size-mismatch.json)
- [Inline byte digest disagrees with decoded data](v0/invalid/inline-bytes.digest-mismatch.json)
- [Capability set is not canonically ordered](v0/invalid/capability-set.unsorted.json)
- [Schema reference uses the retired plugin namespace](v0/invalid/schema-ref.plugin-namespace.json)
- [Capability set uses the retired plugin namespace](v0/invalid/capability-set.plugin-namespace.json)

Each invalid case contains one intended defect and declares the expected JSON
Schema keyword and instance pointer. Fixture values are synthetic and must
never resemble or contain usable credentials.
