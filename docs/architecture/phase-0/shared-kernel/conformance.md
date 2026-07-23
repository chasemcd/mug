# Shared-Kernel Conformance Plan

| Field | Value |
| --- | --- |
| Status | Draft |
| Contract revision | `0.2` |
| Owner | Platform architecture and contract-test maintainers |
| Last updated | 2026-07-20 |
| Applies to | Python, browser/TypeScript, services, workers, core integrations, evidence readers, and exporters |

## Conformance layers

An implementation is not conforming merely because its JSON validates.

| Layer | Proves |
| --- | --- |
| Schema document checks | Draft 2020-12 validity, unique immutable IDs, bounded strict shapes, offline `$ref` resolution |
| Golden fixture checks | Valid examples pass; each one-defect negative fails at the expected keyword/path |
| Parser/canonicalization vectors | Duplicate/nonfinite input rejection and identical RFC 8785 bytes/digests |
| Language mapping checks | Python and browser types preserve exact identities, omissions, numbers, and unions |
| Semantic value checks | Registry-derived ID kinds, canonical privacy joins, sorted capabilities, decoded binary integrity, and exact referenced-schema validation |
| State-machine/transaction tests | Idempotency, revision, receipt durability, Unit-of-Work, lease, sequence, crash behavior |
| Privacy tests | Forbidden fields/content cannot enter client, evidence, log, error, bundle, or export paths |
| Integrated scenarios | Independently designed domain APIs compose under north-star success/failure paths |

## Fixture format

[`fixtures/v0/manifest.json`](fixtures/v0/manifest.json) is the machine-readable
index. Each case declares:

- Stable case ID
- Relative instance path
- Exact schema `$id` plus `$defs` fragment
- Validation layer (`schema` by default, `typed_object` for second-stage
  domain-schema validation, or `semantic` for a shared invariant JSON Schema
  cannot express)
- Expected `valid` or `invalid`
- For invalid input, the intended schema/semantic keyword and instance JSON
  Pointer

Every invalid fixture contains one intended defect. The harness must match the
layer, keyword, and pointer, including nested validator contexts, rather than
unstable library error prose. A `typed_object` or `semantic` case must first
pass its structural JSON Schema, then fail the named exact-schema or shared
semantic validator. The harness rejects duplicate case IDs, path traversal,
missing files, and unlisted fixture files.

Draft fixtures live under `v0`. When the proposal converges, deterministic
promotion creates a `v1` release candidate with updated embedded versions,
schema IDs, references, and digests. The exact promoted bytes must pass the
suite and receive review sign-off before becoming immutable. A later change to
an accepted contract gets a new version directory; tests continue running all
retained versions.

## Automated harness

The Phase 0 harness will use Python `jsonschema` Draft 2020-12 with the
`referencing` registry and explicit format checking. All schemas are loaded into
an offline immutable registry; validation must never retrieve a network URL.

The loader must reject duplicate object names and Python's otherwise accepted
`NaN`, `Infinity`, and `-Infinity`. It separately checks canonical JSON because
JSON Schema validates parsed values, not source bytes.

Required test groups:

```text
schema documents declare exact Draft 2020-12 and unique absolute $id
Draft202012Validator.check_schema succeeds
all local $ref values resolve without network retrieval
fixture manifests validate and list every fixture exactly once
valid cases have zero validation errors
invalid cases fail for their declared keyword and pointer
canonicalization vectors produce exact UTF-8 bytes and SHA-256
Python and browser runners produce the same results
```

`all local $ref values` means every recursively discovered `$ref` in every
schema document, not only references named by the fixture manifest.

## Semantic validators

JSON Schema establishes portable structure but does not by itself prove every
shared-kernel invariant. Conforming runtimes and the reusable contract suite
must also check:

- `ResourceRef.id` has a registered prefix and a domain operation receives the
  exact typed resource kind it declares.
- Every `TypedObject.schema` resolves by exact name, version, and digest from
  the offline allowlist, and `data` validates against that resolved schema
  before canonicalization, fingerprinting, persistence, or effects.
- `PrivacyClassification` has exactly one base (`public` or `research`), uses
  canonical label order, and inheritance selects the stricter base plus the
  normalized union of `sensitive`/`pii` restrictions.
- `CapabilitySet` is sorted by canonical capability name and contains no
  duplicates.
- `InlineBytes` decodes as unpadded base64url, satisfies the owning API's decoded
  size limit, and matches its declared digest where one is present.
- W3C trace and span identifiers are nonzero and tracing metadata never grants
  authority or carries protected baggage.
- A `PublicHandle` is resolved only inside its declared audience, purpose, and
  lifetime scope and is never treated as authentication.

Shape fixtures may exercise some of these rules. The fixture manifest must not
claim full semantic conformance until independent semantic validators run in
both Python and the browser where the value crosses that boundary.

The test dependency and harness are intentionally part of Phase 0 contract
evidence, not a production runtime-library choice. Runtime validation/code
generation remains a separate accepted ADR decision.

## Required golden cases

The initial schema fixture set covers shared shapes. Stateful fixtures below
are added as the owning API contracts become concrete.

| ID | Case | Expected evidence | Scenario/failure trace |
| --- | --- | --- | --- |
| SK-01 | Full valid wire command | Exact parse; no trusted principal in input | All commands |
| SK-02 | Wire command asserts trusted principal/actor context | Schema rejection; no idempotency record | NS-04, NS-05 |
| SK-03 | Unsupported/unknown command schema | Safe error; no mutation | Failure matrix unknown schema |
| SK-04 | Valid commit receipt | Accepted result, revision, positions, named durability | NS-10 |
| SK-05 | Receipt contains both result and error | Schema rejection | Receipt invariant |
| SK-06 | Secret reference carries value/path/token | Schema rejection | NS-12 |
| SK-07 | Artifact reference contains storage URI | Schema rejection | API-11 boundary |
| SK-08 | Noncanonical ID/digest/time | Pattern rejection | Encoding invariant |
| SK-09 | Duplicate JSON key, NaN, infinity, unsafe integer | Parser/schema rejection | Serialization invariant |
| SK-10 | Canonical JSON vector | Same Python/browser bytes and digest | API-01/API-10 |
| SK-11 | Transactional preference success | Aggregate, idempotency, receipt, canonical event, outbox atomic | NS-10 |
| SK-12 | Identical retry after lost reply | Byte-equivalent receipt; no second effect/event | NS-08, NS-10 |
| SK-13 | Conflicting idempotency reuse | `command.idempotency_conflict`; no disclosure/mutation | NS-10 |
| SK-14 | Two concurrent duplicate commands | One effect; existing status/receipt for the other | Failure matrix |
| SK-15 | Crash before/after relational commit | Safe execute or original receipt, respectively | NS-08, NS-10 |
| SK-16 | Revision/state/uniqueness conflict | Terminal safe rejection; no recomputation | NS-01, NS-10 |
| SK-17 | Lease takeover and delayed old socket/worker | Old generation fenced at effect time | NS-04, NS-07 |
| SK-18 | Lease-store loss | New namespace epoch invalidates every old token | Failure matrix |
| SK-19 | Producer exact duplicate/equivocation/gap | Deduplicate, conflict, or gap without canonical misorder | NS-09 |
| SK-20 | Concurrent chat acceptance/delivery | Canonical channel order and separate experienced timing | NS-04, NS-06 |
| SK-21 | Runtime input then crash | Declared loss/completeness; no false commit claim | NS-09 |
| SK-22 | Artifact finalize and transaction crash points | No dangling committed ref; safe orphan cleanup | NS-01, NS-02 |
| SK-23 | Committed artifact later unavailable | Historical receipt intact; capability withdrawn/incident appended | NS-01, NS-12 |
| SK-24 | Provider result after generation/deadline | Provenance retained; all effects/memory discarded | NS-03, NS-07 |
| SK-25 | Declared fallback | Separate decision and actual exposure | NS-07 |
| SK-26 | External tool unknown outcome | Durable indeterminate result; no automatic retry | NS-11 |
| SK-27 | Database unavailable before commit | No accepted commit receipt; same command retryable | NS-10 |
| SK-28 | Forbidden versus nonexistent protected resource | Observationally equivalent public errors | NS-05, NS-12 |
| SK-29 | Receipt lookup after reconnect | Audience-valid original receipt without reapplying effect | NS-08, NS-10 |
| SK-30 | Error redaction injection | No credential, prompt, SQL, tool body, PII, or raw input | NS-12 |
| SK-31 | Schema reference uses `plugin.*` | Pattern rejection; no v0 plugin schema is reachable | ADR-0015 |
| SK-32 | Capability set uses `plugin.*` | Pattern rejection; closed v0 capability namespace | ADR-0015 |

## Python mapping rules

- Generate or hand-maintain frozen typed values with distinct nominal ID types;
  do not expose every ID as an interchangeable `str` in application signatures.
- Preserve unknown archived bytes outside typed projections; do not coerce an
  unsupported object into a permissive dictionary.
- Disable implicit timezone conversion, float NaN, enum coercion, and arbitrary
  extra fields.
- `SecretLease`, live handles, provider clients, repositories, and transactions
  are deliberately nonserializable.
- Domain defaults are materialized before hashing; library annotation defaults
  must not silently change canonical data.

## Browser/TypeScript mapping rules

- Brand identifier types so `VisitId`, `EventId`, and `ArtifactId` cannot be
  assigned interchangeably in checked code.
- Validate untrusted server/integration input at the boundary; static types alone do
  not validate JSON.
- Reject unsafe integers and nonfinite numbers before constructing a command.
- Preserve Unicode and omission/null distinctions exactly.
- Generate request/idempotency material with a cryptographically secure source.
- Never expose server-only `CommandContext`, `SecretRef`, private manifests, or
  full protected artifact references in the browser package.

## Stateful fault injection

Every implementation of the shared semantics must inject failure at:

1. Before idempotency claim
2. After claim, before mutation
3. During aggregate/event/outbox Unit of Work
4. After commit, before reply
5. During artifact upload, finalization, verification, and reference commit
6. During lease renewal/takeover and after lease-store state loss
7. Before, during, and after provider/tool cancellation/deadline
8. During reconnect, duplicate delivery, producer gaps, and P2P disagreement

Tests assert both visible result and absence of forbidden second effects.

## Acceptance gate

Version 1 cannot be accepted until:

- Every version-0 schema and fixture passes the automated harness.
- Every semantic validator above has positive, boundary, and negative vectors.
- Independent Python and browser canonicalization runners pass the same vectors.
- Proposed ADRs 0008–0011 are accepted or superseded.
- Domain/science, runtime, data/replay, and security/privacy reviewers sign the
  [review record](review-record.md).
- API-01, API-02, API-09, API-10, and API-11 owners confirm that the shared
  boundary does not duplicate or omit their state.
- NS-08, NS-10, and NS-12 have concrete command/receipt/failure walkthroughs.
