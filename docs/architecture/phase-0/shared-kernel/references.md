# Shared References

| Field | Value |
| --- | --- |
| Status | Draft |
| Contract revision | `0.2` |
| Owner | Shared kernel; referenced resources remain domain-owned |
| Last updated | 2026-07-20 |
| Schema | [`mug.shared-kernel`, version 0](schemas/v0/shared-kernel.schema.json) |

This page defines the meaning of shared portable values. The JSON Schema owns
their exact wire shape. Examples use deliberately synthetic identifiers and
digests.

## `Digest`

```json
{
  "algorithm": "sha-256",
  "hex": "3cf2d09da21a0f4d93d9f58c696223049c5b521c6b0a74f62b64f8bb96ae2682"
}
```

Version 0 supports SHA-256 only. Hex is exactly 64 lowercase characters. Each
field that uses a digest defines its byte domain; shape equality does not make
digests from different domains interchangeable.

Initial domains are:

| Field | Bytes covered |
| --- | --- |
| Artifact digest | Finalized bytes after declared content encoding and before transparent storage encryption |
| Schema digest | RFC 8785 canonical JSON bytes of the immutable schema document |
| Manifest digest | RFC 8785 canonical JSON bytes of the manifest body, excluding publication metadata and its own digest field |
| Command fingerprint | Schema-normalized semantic command content defined in the command specification |
| Environment state hash | Bytes produced by the named environment state-hash profile |

A digest is an integrity/equality claim, not an occurrence ID, signature,
runtime credential, or proof that bytes remain available. Equal sensitive or
low-entropy content can leak information; digest exposure and physical
deduplication must stay inside the declared classification boundary.

## `SchemaRef`

```json
{
  "name": "mug.preference.response-submit",
  "version": 1,
  "digest": {
    "algorithm": "sha-256",
    "hex": "e7a04ccf3744d580fb921f97b5c1600c4a9f73a1b54d7f5dc622e25c74681b3"
  }
}
```

- Active v0 schema names start `mug.`.
- Version `0` is a mutable proposal and is forbidden in published/deployed or
  archival objects. Accepted versions are positive integers and immutable.
- The digest is required in publication, archival, and evidence contracts. It
  is also carried on the wire initially so registry drift cannot change meaning.
- Resolution uses the deployment's allowlisted local registry. A client,
  fixture, event, or bundle must never cause arbitrary URL fetching.
- The exact registry entry selects the schema and any declared upcaster. An
  integer comparison does not imply compatibility.

Both `SchemaName` and `CapabilitySet` are closed to `mug.*` names in v0.
`plugin.<registered-plugin-id>.*` is rejected structurally. ADR 0015 retracted
plugins for v0; core integrations use MUG-owned contract names and ordinary
study code rather than a plugin namespace.

## `StudyVersionRef`

```json
{
  "study_id": "study_01981c4e-7b64-7e81-8a72-a2537d5f6c91",
  "study_version_id": "studyver_01981c50-1baa-72db-a85b-e06372a27ebf",
  "version_number": 3,
  "manifest_digest": {
    "algorithm": "sha-256",
    "hex": "3cf2d09da21a0f4d93d9f58c696223049c5b521c6b0a74f62b64f8bb96ae2682"
  }
}
```

The version ID is identity. `version_number` is a catalog-assigned display
ordinal, not SemVer, order of scientific quality, or compatibility. The digest
binds the reference to one manifest. Publishing the same manifest under the
same study is idempotent and returns the existing version. A scientific fork
uses a distinct `StudyId` and explicit lineage rather than creating a second
same-study version with identical content.

## `DeploymentRevisionRef`

A deployment is a stable launch/operations resource; a deployment revision is
one immutable operational manifest. A visit pins both its scientific version
and operational revision.

```json
{
  "deployment_id": "deploy_01981c54-747c-79bc-a18c-eb80ade8275b",
  "deployment_revision_id": "deployrev_01981c55-12cf-75dc-9ca9-f3a41f95fb02",
  "revision_number": 4,
  "study_version": {
    "study_id": "study_01981c4e-7b64-7e81-8a72-a2537d5f6c91",
    "study_version_id": "studyver_01981c50-1baa-72db-a85b-e06372a27ebf",
    "version_number": 3,
    "manifest_digest": {
      "algorithm": "sha-256",
      "hex": "3cf2d09da21a0f4d93d9f58c696223049c5b521c6b0a74f62b64f8bb96ae2682"
    }
  },
  "manifest_digest": {
    "algorithm": "sha-256",
    "hex": "ad4b11f4affbcb2ad7dcc42644a494930e41ec2967ab9ab6c091c7aa884ba99e"
  }
}
```

Changing a pinned client build, runtime image, endpoint topology, secret-slot
binding, or other semantic operational input creates a deployment revision.
Activating or suspending the same immutable revision changes the deployment
aggregate state and `VersionStamp`; it does not create another revision.

## `VersionStamp`

```json
{
  "revision": 8,
  "etag": "sha256:7fdf5d353a83b3a1c0414b2a175d49d1e612db83bb376edc6ee1d826203bc45e"
}
```

New aggregates have revision `1` after creation. Each committed aggregate
mutation increments it exactly once; revisions are never reused or decremented.
The ETag covers the schema-defined canonical current projection, not row bytes.
HTTP adapters may quote it in an `ETag` header. A mutable aggregate revision is
unrelated to a study ordinal, schema version, deployment revision, or event
stream sequence.

## `ResourceRef` and `PrincipalRef`

```json
{
  "id": "episode_01981c73-bb4c-7141-88cc-f53a011446cd"
}
```

`ResourceRef` is for generic envelopes, lineage, and evidence correlation. Its kind is derived
from the registered ID prefix; it is not repeated as a second caller-controlled
field that could disagree. Domain APIs should prefer typed references.

```json
{
  "kind": "participant",
  "id": "participant_01981c70-5a35-76eb-94c8-5072f2c0c868"
}
```

`PrincipalRef.kind` is one of `participant`, `researcher`, `service`, or
`system`. It represents a server-resolved runtime subject, not a claim a
browser may insert into a trusted context.

Neither reference grants existence disclosure or runtime membership. The
owning API resolves the resource against canonical identity, audience, and
membership state and returns a concealment-safe error where necessary.

## `PublicHandle`

Where a typed ID, UUID issuance time, digest, definition kind, or stable linkage
could reveal a blinded condition or connect contexts, the client receives a
scoped `PublicHandle` instead:

```json
"handle_7Gg3L2M1qPv9sXr4Nk8BzQ"
```

The value is `handle_` plus the canonical 22-character unpadded base64url
encoding of exactly 16 CSPRNG bytes; its final character is one of `A`, `Q`,
`g`, or `w`. It contains no resource type or scientific identity and is not a
bearer credential. The server resolves it only after verifying runtime identity
and the current binding, inside its recorded audience, purpose, and lifetime scope.
Equality has meaning only within that scope.

The shared kernel owns the encoding and non-authorizing semantics. The exact
binding/issuance APIs are deliberately domain-owned: API-03 for participant
pseudonyms, API-09 for client transport presentation, and API-18 for
blinded preference candidates and presentation artifacts.

## `ArtifactRef`

```json
{
  "artifact_id": "artifact_01981c61-bdc2-7bad-9ef1-c53633e9c613",
  "digest": {
    "algorithm": "sha-256",
    "hex": "9acbbcf3f70f3581b4cfe0954dc23bb3dbc063cd459aca06f99d488b80848429"
  },
  "size_bytes": 120391,
  "media_type": "application/vnd.apache.arrow.file",
  "content_encoding": "zstd",
  "content_schema": {
    "name": "mug.trajectory.chunk",
    "version": 1,
    "digest": {
      "algorithm": "sha-256",
      "hex": "712c38c3e806a34e70cffcb36d7d8b5cbb9b9e8bc467a516bab05ee2b47f224c"
    }
  },
  "data_handling": {
    "privacy_labels": ["research", "sensitive"]
  }
}
```

- `content_encoding` is `identity` when unencoded.
- Digest and size cover exactly the finalized encoded bytes.
- `content_schema` is omitted for unstructured content.
- Storage URI, bucket, path, filename, signed URL, encryption key, owner,
  mutable availability/integrity status, and deletion status are forbidden.
- Artifact identity is separate from content identity; equal bytes can have
  distinct provenance and privacy classification.
- A full reference is not a client delivery ticket. API-11 issues a scoped,
  expiring delivery ticket after resolving audience/membership and may redact
  the digest where equality itself is sensitive.
- A derived artifact may add labels or otherwise require stricter handling than
  its source. The label-lattice join determines its effective classification;
  the institution may impose additional handling outside MUG.

## `DataHandlingRef`

`DataHandlingRef` carries canonical `privacy_labels` and nothing else. The
label set contains exactly one base disclosure label (`public` or `research`)
plus independent `sensitive` and `pii` restriction labels where applicable.
Persisted data must declare or inherit labels. `secret` is deliberately not a
privacy label.

There is no retention-policy reference: retention and deletion are owned by
the self-hosting institution and applied to its own store (ADR 0015). MUG
records labels so the institution can classify what it retains; it does not
model retention as a platform object.

## `SecretRef`

Study/server manifests declare a logical slot and purpose; a private deployment
revision binds it to a secret without exposing a provider name, environment
variable, vault path, account, or material value.

```json
{
  "binding_id": "secret_01981c66-2f5c-7658-b3da-76dcdf5b0486",
  "resolution": "pinned",
  "binding_revision": 7
}
```

`resolution` is `deployment-current` or `pinned`; the latter requires a positive
`binding_revision`. A `SecretRef` is permitted only in declared private
server/deployment configuration. It is forbidden in client/provenance
manifests, events, research artifacts, replay bundles, exports, traces, logs,
fixtures containing real values, and participant-safe errors.

Resolution returns a nonserializable, short-lived server-side `SecretLease`,
not JSON. The actual binding revision used is recorded as protected
exposure/provenance without secret material. Credential rotation does not
change scientific model identity.

## `EventCursor` and `StreamPosition`

```json
{
  "stream_id": "stream_01981c6a-7dc4-7392-bd86-81fb2712ef92",
  "after_sequence": 123
}
```

An event cursor points immediately after the last consumed canonical event.
Zero means before the first event; the next read after `123` begins at `124`.
It has no runtime-authority semantics. Lossless compaction may relocate or re-index
retained events, but it preserves original bytes, stream IDs, sequences, and
cursor meaning for their declared archival support lifetime. A hot-store miss must be
resolved from retained archival storage rather than reported as loss.

`event.cursor_expired` is permitted only after the operating institution has
deleted the underlying original evidence from its store, or for an explicitly ephemeral
non-archival stream whose accepted contract declared a bounded lifetime. A
snapshot/resumption route may help a live client continue, but it never claims
to replace deleted original evidence or restore an exact replay capability.

```json
{
  "stream_id": "stream_01981c6a-7dc4-7392-bd86-81fb2712ef92",
  "sequence": 124
}
```

`StreamPosition` identifies an accepted position. Multi-stream cursor arrays
must be unique and sorted by stream ID in canonical documents. `PageToken`,
signed `ResumeToken`, and per-subscription `DeliveryCursor` are distinct types.

## `LeaseRef` and `LeaseToken`

Persistable evidence may carry a non-secret verified reference:

```json
{
  "lease_id": "lease_01981c80-bdc2-7bad-9ef1-c53633e9c616",
  "namespace_epoch_id": "leaseepoch_01981c81-bdc2-7bad-9ef1-c53633e9c617",
  "generation": 17
}
```

The raw `LeaseToken` is an opaque bearer credential accepted only at the wire
boundary. It is verified into a trusted fencing claim, then removed. Tokens are
never placed in events, receipts, traces, logs, diagnostics, or artifacts.

## `CapabilitySet`

Capabilities are a lexicographically sorted, duplicate-free array of registered
lowercase strings:

```json
[
  "mug.game.server-authoritative.v1",
  "mug.model.structured-output.v1",
  "mug.replay.seekable.v1"
]
```

Absence means unsupported. Negotiation chooses an explicitly compatible set;
it never silently degrades a published scientific requirement.

## `TraceContext`

The portable shape carries W3C `traceparent` and optional `tracestate` only.
Arbitrary baggage is forbidden. Trace values are operational correlation, not
canonical evidence or participant identity, and must not contain raw content,
external identity, MUG resource IDs, idempotency keys, or secrets.
