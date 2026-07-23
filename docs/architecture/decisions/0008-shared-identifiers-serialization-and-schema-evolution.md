# ADR 0008: Shared Identifiers, Canonical Serialization, and Schema Evolution

| Field | Value |
| --- | --- |
| Status | Accepted |
| Date | 2026-07-17 |
| Accepted | 2026-07-20 (shared-kernel **core-layer** freeze; accountable-owner human sign-off after G5 RFC 8785 cross-language conformance + G7 four-panel review) |
| Last updated | 2026-07-20 |
| Owners | Unassigned |
| Supersedes | None |
| Superseded by | [ADR 0013](0013-git-native-study-versioning.md) in part (definition registry removed) and [ADR 0015](0015-governance-out-of-scope.md) in part (v0 extension/plugin surface retracted) |
| Affects | Shared kernel and all API families |

## Context

MUG must exchange and retain scientific definitions, runtime occurrences,
commands, events, artifacts, and replay evidence across Python, browsers,
workers, core integrations, and future readers. The current platform has no durable
language-neutral identity/schema contract. Labels, Python object attributes,
JSON numbers, timestamps, and dictionary shapes are otherwise easy to interpret
differently across runtimes or change silently.

The platform owes no compatibility to pre-vNext code. Once a vNext study or
evidence contract is published, however, exact meaning and archival readability
must survive its declared support period.

## Decision

Adopt the [shared-kernel identifier](../phase-0/shared-kernel/identifiers-and-resource-hierarchy.md),
[reference](../phase-0/shared-kernel/references.md), and
[serialization/evolution](../phase-0/shared-kernel/serialization-and-schema-evolution.md)
contracts:

- Separate definition identity, immutable version identity, runtime occurrence
  identity, principal/security identity, human keys, content digests,
  credentials, revisions, and ordered positions.
- Encode MUG entity IDs as registered type prefix plus canonical lowercase
  UUIDv7. UUID time bits are never order or authorization.
- Derive a generic resource's kind from its registered typed-ID prefix rather
  than accepting a duplicate caller-controlled kind field. Use mandatory scoped
  random `PublicHandle`s when the typed ID, UUID time, digest, or stable linkage
  could unblind or connect client contexts; a handle is never authorization.
- Give published scientific and operational versions typed occurrence IDs,
  catalog ordinals, and content digests; use SemVer only for protocol/software
  compatibility and `VersionStamp` only for mutable aggregate concurrency.
- Use JSON Schema Draft 2020-12, strict schemas, exact `SchemaRef`
  name/integer-version/digest, and an allowlisted offline registry.
- Reserve schema version `0` for mutable proposals and prohibit it from
  publication, deployment, or archival evidence. Accepted versions start at 1
  and are immutable.
- Use RFC 8785 canonical JSON after schema validation/default resolution for
  digestable JSON, with UTF-8, duplicate-key rejection, safe IEEE-754 numbers,
  fixed microsecond UTC, explicit exact-number types, and typed artifacts for
  large/binary/nonnative values.
- Preserve original archived bytes and stream positions for their declared
  archival support lifetime, including across lossless compaction. Upcasters produce
  lineage-bearing derived representations and never rewrite originals.
- Preserve and fail closed on unknown critical schemas. A projection may skip
  an unknown noncritical observation only when its accepted contract says so.

## Scope and non-goals

This ADR chooses portable identity, JSON, time representation, schema registry,
and evolution rules. It does not select production model-generation libraries,
database keys, an environment snapshot codec, schema-bundle signatures, or the
exact support lifetime of each study; follow-up decisions own those.

## Invariants

- No ID, digest, version, key, revision, sequence, token, or cursor substitutes
  for another class.
- IDs do not grant access and do not establish event order.
- Public handles neither grant access nor expose internal resource kind; their
  equality is scoped to the recorded presentation/audience context.
- Accepted `(schema name, version)` bytes/digest are never changed or reused.
- Version-0 schemas cannot enter retained research objects.
- Every archived object remains interpretable without arbitrary network fetch.
- Schema validation precedes canonical hashing and domain effects.
- Unknown critical meaning is never silently discarded.
- Python and browser canonicalization produce identical bytes/digests for the
  accepted profile.

## Consequences

### Positive

- Type prefixes expose cross-domain mistakes in fixtures, dynamic clients, and
  logs while UUIDv7 supports decentralized issuance and database locality.
- Exact schemas and digests prevent registry drift.
- Original evidence remains auditable while readers can evolve through explicit
  upcasters.
- Large Gym/PettingZoo values are forced into declared portable codecs instead
  of accidental JSON or pickle behavior.

### Costs and constraints

- MUG must maintain an ID/schema registry, retained reader/upcaster suite,
  versioned fixture corpus, and cross-language RFC 8785 implementation.
- UUIDv7 can reveal approximate issuance time. Blinded/client APIs need scoped
  handles where this could affect privacy or experimental validity, plus
  protected server-side handle bindings and concealment-safe resolution.
- Strict unknown-field behavior requires deliberate closed schemas. Version 0
  has no extension container or plugin negotiation surface (ADR 0015).
- Fixed microsecond UTC may require retaining higher-precision provider values
  in a separate typed source field.

### Failure consequences

- Digest mismatch quarantines data as an integrity failure.
- Unsupported critical schema stops the affected ingest/projection/replay/export
  rather than producing a partial answer disguised as complete.
- A missing schema bundle is a publication/bundle defect and blocks deployment
  or replay validation.

## Security and privacy

Opaque IDs and digests remain classified data when linkable. Type/UUID timing or
content equality must not unblind a participant. Schema resolution is offline
and allowlisted, preventing untrusted `$ref` network access. Strict schemas and
bounded inputs reduce parser/resource attacks. Secret material is outside this
serialization profile and handled by ADR 0011.

## API and schema impact

Every API adopts typed IDs, `SchemaRef`, canonical timestamps/numbers, and
version-0 rejection at publication. API-01/16 packages retained schema bundles;
API-09 negotiates protocol; API-10 preserves exact event schema/bytes; API-11
binds artifact bytes/digests; API-19 records derived upcaster lineage.

## Alternatives considered

### Reuse labels, paths, or auto-increment integers

Rejected because renames, source changes, tenancy, offline issuance, and
cardinality leakage make them unstable or unsafe identity.

### Use content hashes as every identifier

Rejected because equal bytes can be distinct occurrences with different
provenance, privacy classification, and institutional handling; ordinary edits
also should not change a definition's identity.

### One untyped UUID string

Rejected because dynamic/wire code would accept cross-type substitution too
easily. UUIDv4 remains useful for cryptographic/random token material but is not
the MUG entity-ID encoding.

### SemVer every object and infer compatibility

Rejected because scientific versions, mutable revisions, schema shapes, and
software capability have different semantics. Schema compatibility requires an
explicit declaration and tests.

### Permissive JSON with best-effort readers

Rejected because silent coercion or field skipping destroys reproducibility and
makes privacy/security behavior dependent on incidental libraries.

## Validation

- Schema and one-defect fixture harness in the
  [conformance plan](../phase-0/shared-kernel/conformance.md)
- Independent Python/browser UUID, strict-parser, RFC 8785, number, Unicode, and
  timestamp vectors
- Unknown-version, digest-mismatch, retained-upcaster, and offline-bundle tests
- Published-history definition-key continuity, rename, and fork tests
- NS-08, NS-09, NS-12 and all replay/export scenario walks

## Follow-up decisions

- Definition-key continuity against immutable published history — API-01
- Public-handle binding, lifetime, and resolution services — API-03/API-09/API-18
- Runtime validation/code-generation libraries — platform implementation owner
- Deterministic environment/trajectory binary profiles — API-07/API-10/API-16
- Schema-bundle packaging/signing and support lifetime — API-01/API-16
