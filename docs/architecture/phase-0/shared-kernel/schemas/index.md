# Shared-Kernel Schemas

| Field | Value |
| --- | --- |
| Status | Draft |
| Normative dialect | JSON Schema Draft 2020-12 |
| Last updated | 2026-07-20 |

## Draft version 0

- [`mug.shared-kernel` schema bundle](v0/shared-kernel.schema.json)

The current canonical bundle digest is
`f675d9ec1f6258719da93a507421689b26babf69d36503c7df90b5039e238d6d`.
The v0 `SchemaName` and `CapabilitySet` namespaces are closed to `mug.*`;
`plugin.*` is rejected.

The bundle contains `$defs` for every initial shared value and envelope. The
fixture manifest selects an exact `$id` plus fragment. Version 0 is mutable
during review and is forbidden from published/deployed/archival documents.

The bundle also contains four explicitly fixture-only domain schemas. They let
the conformance harness prove that `TypedObject` processing resolves the exact
name/version/digest and validates `data` in a second stage; production domain
schemas remain owned and packaged by their API families.

At acceptance, a deterministic promotion writes a `v1` release candidate,
updates embedded IDs/version constants/references, computes its digest, and
regenerates fixture references. Reviewers approve those exact promoted bytes;
they then become immutable. All retained accepted versions remain in
conformance tests.

Schema `$id` values are identifiers, not fetch instructions. Validators resolve
them from an allowlisted offline registry.
