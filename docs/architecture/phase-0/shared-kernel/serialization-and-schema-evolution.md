# Serialization and Schema Evolution

| Field | Value |
| --- | --- |
| Status | Draft |
| Contract revision | `0.2` |
| Owner | Shared kernel and schema registry |
| Last updated | 2026-07-20 |
| Decision | Proposed ADR 0008 |

## Version domains

MUG keeps four version systems separate:

| Domain | Representation | Meaning |
| --- | --- | --- |
| Published scientific/operational resource | Typed UUIDv7 ID + ordinal + manifest digest | One immutable realization |
| Persisted or wire JSON schema | Registered name + integer version + schema digest | Exact data shape and meaning |
| Runtime protocol and software compatibility | SemVer 2.0 | Negotiated client/runtime compatibility range |
| Mutable aggregate state | `VersionStamp` | Optimistic concurrency |

SemVer must not be used as a study's scientific identity. An aggregate revision
must not be used as an event sequence or immutable deployment revision.

Note: `VersionStamp.etag` deliberately uses the HTTP-style `sha256:` prefix,
while `Digest.algorithm` uses `sha-256`; they name the same hash in different
namespaces.

## Normative schema language

JSON Schema Draft 2020-12 is the normative language for JSON wire, manifest,
event, receipt, and fixture documents. Every document schema must:

- Declare the exact Draft 2020-12 `$schema`
- Have a globally unique absolute `$id`
- Use a registered `SchemaRef`
- Be strict by default with `additionalProperties: false` or, when composing,
  `unevaluatedProperties: false`
- Bound collection counts, nesting, and string sizes at every untrusted boundary
- Use disjoint discriminators for unions
- Declare whether each nullable value is meaningful; omission and `null` are
  not interchangeable

Version 0 defines no open `extensions` container or plugin-provided schema
surface (ADR 0015). Unknown fields are not an extension mechanism. Schema
resolution is offline/allowlisted; `$ref` never authorizes network fetch. If a
typed extension protocol is accepted post-v0, it will require its own versioned
contract rather than weakening existing closed schemas.

Each standalone JSON document carries a top-level `schema` field. Envelopes and
payloads have separate references when different APIs own them. Provider SDK
objects, Python pickles, JavaScript class instances, and database row layouts
are not archival schemas.

## Version allocation and immutability

- Version `0` is reserved for mutable Phase 0 proposals and test fixtures. It
  must fail publication/deployment validation.
- Accepted versions start at `1`, increase monotonically per schema name, and
  are immutable byte-for-byte.
- Any validation- or meaning-affecting change receives a new integer version.
- Compatibility metadata is explicit. It is never inferred because one integer
  is larger than another.
- Editorial documentation may change without changing schema bytes. A corrected
  example becomes a new fixture revision; a changed accepted wire shape becomes
  a new schema version.

The registry entry binds `(name, version)` to an exact digest, local schema
document, criticality, owning API, supported readers, and registered upcasters.

## Reader and upcaster behavior

At ingestion, exact schema validation happens before canonicalization,
fingerprinting, defaults, or domain effects. At read time:

1. Resolve the exact local schema by name, version, and digest.
2. Verify the original bytes and schema reference.
3. Validate with the original schema.
4. If needed, run an explicitly registered deterministic upcaster chain.
5. Retain the original bytes/digest and record the derived representation's
   schema, code version, and lineage.

Upcasting never rewrites archived events, artifacts, manifests, receipts, or
bundles. A downcaster may be offered only when its information loss is explicit
and it is not used to claim exact replay.

Unknown behavior is fail-closed:

| Condition | Required behavior |
| --- | --- |
| Unknown wire protocol or command schema | Reject before idempotency execution or domain mutation |
| Known schema name/version with digest mismatch | Integrity error; quarantine the bytes |
| Unknown critical persisted schema | Preserve bytes; stop the affected projection/replay/export |
| Unknown noncritical observational schema | Preserve and diagnose; skip only if that projection's accepted contract allows it |
| Declared built-in integration contract outside its supported range | Compilation/deployment fails closed |
| Accepted reader reaches end of support window | Archive/migrate with verified tooling before support is removed |

Published study and replay bundles embed or content-address the complete schema
bundle needed to interpret retained evidence. A registry service going offline
must not make an otherwise complete bundle unreadable.

## Canonical JSON profile

Digestable JSON uses RFC 8785 JSON Canonicalization Scheme after exact schema
validation, plus these MUG input constraints:

1. UTF-8 without a BOM.
2. Duplicate member names, comments, trailing commas, NaN, and infinities are
   rejected by the parser.
3. Object member order is semantically irrelevant; array order is significant
   unless the field defines set semantics and a canonical sort.
4. Optional fields are omitted. `null` appears only where the schema gives it a
   distinct domain meaning.
5. Human text preserves exact Unicode scalar values; no implicit Unicode
   normalization is allowed.
6. Machine identifiers, keys, enum values, media types, and schema names use
   constrained ASCII.
7. Defaults are resolved by the owning schema/normalizer before a semantic
   digest. JSON Schema's `default` annotation does not itself mutate input.
8. A digest domain includes the applicable schema reference or is embedded in a
   parent whose schema reference is already bound.

`json.dumps(sort_keys=True)` is not a conforming substitute for RFC 8785. Phase
0 acceptance requires one real Python implementation and one browser
implementation to pass identical canonical byte and digest vectors.

## Numeric profile

Ordinary JSON numbers are finite interoperable IEEE-754 binary64 values.
Integers are limited to `[-9007199254740991, 9007199254740991]`. Schemas must
distinguish `integer` and `number`; negative zero is forbidden where its sign is
meaningful.

Digested content MAY carry finite non-integral binary64 numbers. Their canonical
form is the RFC 8785 / ECMAScript `Number`-to-`String` serialization (shortest
round-tripping decimal), identical across conforming Python and browser
implementations, so a float value has exactly one canonical digest.
Integral-valued numbers share a single canonical form regardless of source
spelling (`1`, `1.0`, and `1e0` all canonicalize to `1`); schemas still declare
`integer` where integer semantics are intended. Values needing precision beyond
binary64 (exact decimals, `uint64`, bit patterns) continue to use the typed
string form below and never a raw JSON number.

Exact values outside that profile use a schema-specific string representation:

```json
{"kind": "uint64", "decimal": "18446744073709551615"}
```

```json
{"kind": "decimal", "decimal": "0.1000"}
```

There is no generic permissive exact-number union. Each domain chooses safe JSON
numbers, an exact integer/decimal schema, or a typed artifact. Large arrays,
non-finite values, exact float bit patterns, tensors, observations, and dense
trajectories belong in a binary artifact that records codec/profile, dtype,
endianness, shape, missing values, and special-value policy.

Random seeds carry an algorithm and hexadecimal seed material, not an unsafe
JSON integer:

```json
{"algorithm": "pcg64dxsm", "seed_hex": "f1c8bb28d56f87156e53b45ac421a9bf"}
```

## Time and duration encoding

Canonical persisted UTC instants use fixed-width RFC 3339 UTC with exactly six
fractional digits:

```text
2026-07-17T14:03:12.123456Z
```

Offsets, lowercase `z`, omitted fractions, and leap-second `:60` are rejected.
Client/provider source values with another representation may be retained as
explicitly untrusted source evidence; they do not replace canonical server
instants.

Portable durations use safe nonnegative integer microseconds:

```json
{"microseconds": 187423}
```

Nanosecond precision or larger exact ranges use a separately typed decimal
string. Monotonic clock readings are coordinator-local and are not ordinary
wire timestamps.

## Binary profile

Binary content normally becomes an artifact. Inline bytes are permitted only
where the owning schema sets a small bound no greater than 4 KiB; they use
unpadded base64url and include decoded size and digest. Large numeric arrays,
trajectory chunks, snapshots, media, provider bodies, and replay content must
not be encoded as JSON number or base64 arrays.

The Phase 0 binary-codec ADR still must select deterministic profiles for
environment state/snapshots and trajectory chunks. Arrow IPC/Parquet are
candidates for analysis artifacts; their use does not by itself define a
deterministic replay state codec.

## Protocol negotiation

The initial wire handshake exchanges:

- Protocol SemVer range
- Exact supported command-envelope versions
- Capability set
- Maximum message/upload limits
- Client build identity pinned by the deployment revision

The server selects one explicitly supported protocol/capability set or rejects
the connection. It never accepts a nearest version or silently removes a
scientifically required capability. Once selected, every message still carries
or is framed under an exact schema reference.

## Stability tiers

| Tier | After acceptance |
| --- | --- |
| Internal | May change with all in-repository callers; no archival promise |
| Core integration | Versioned with explicit supported ranges and conformance suite |
| Public authoring | Changes require a documented source migration; old MUG source need not run |
| Wire | Negotiated exact contracts; no silent meaning changes |
| Archival | Readable/upcastable for the declared published-study support period; original bytes immutable |

No backward compatibility with the pre-vNext platform is required. This does
not waive compatibility obligations created when vNext contracts, studies, or
evidence are published.
