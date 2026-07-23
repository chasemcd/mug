# Shared Kernel Contract

| Field | Value |
| --- | --- |
| Status | Draft |
| Contract | `mug.shared-kernel` |
| Contract revision | `0.2` |
| Owner | Platform architecture (accountable owner unassigned) |
| Consumers | Every MUG authoring API, service, wire client, evidence reader, and exporter |
| Last updated | 2026-07-20 |
| Depends on | ADR 0001; proposed ADRs 0004, 0006, 0008–0011, and 0013–0015 |
| Supersedes | No vNext contract; the existing platform is deliberately not wire-compatible |
| Implementation phase | Phase 1 onward |
| Stability tier | Wire and archival after acceptance; draft until then |

## Purpose

The shared kernel is the small language-neutral vocabulary that prevents each
domain API from inventing its own identifiers, references, command envelope,
receipt, error, clock, privacy label, or version policy. It owns portable value
shapes and cross-cutting invariants, not domain behavior.

This contract is the first Phase 0 API review. It is intentionally numbered
`0` while under review. Draft schemas and fixtures may change. A published
study, deployment, event, artifact, or replay bundle **must not** reference a
version-`0` schema. When review converges, a deterministic promotion creates a
version-`1` release candidate with updated `$id`, embedded version constants,
references, and digests. Reviewers sign the exact promoted schema/fixture bytes;
those accepted bytes are then immutable.

## Normative documents

The words **must**, **must not**, **required**, **should**, and **may** are
normative in these documents:

1. [Identifiers and resource hierarchy](identifiers-and-resource-hierarchy.md)
2. [Shared references](references.md)
3. [Serialization and schema evolution](serialization-and-schema-evolution.md)
4. [Commands, receipts, and errors](commands-receipts-and-errors.md)
5. [Time, ordering, and fencing](time-ordering-and-fencing.md)
6. [Privacy classification and secrets](privacy-retention-and-secrets.md)
7. [Conformance plan](conformance.md)
8. [Review record](review-record.md)

The [schema index](schemas/index.md) links the proposed wire schemas. The
[fixture index](fixtures/index.md) links valid and deliberately invalid golden
examples. Explanatory examples are non-normative when they disagree with a
schema; such disagreement is a contract defect and blocks acceptance.

## Goals

- Give Python, browser, worker, storage, replay, and export code one
  portable contract.
- Keep definition identity, immutable version identity, runtime occurrence
  identity, content identity, credentials, revisions, and ordering distinct.
- Make retries, durable acknowledgment, concurrency, and stale authority
  testable rather than transport-specific.
- Preserve exact evidence for the declared archival support lifetime of a
  published study.
- Prevent client-supplied ownership, arbitrary schema resolution, secret
  material, or unsafe diagnostics from crossing a trust boundary.

## Non-goals

- Domain state machines and payloads; their owning API families define them.
- Database tables, ORM models, provider SDK objects, or transport frameworks.
- Old MUG API, socket-event, Python-pickle, or stored-data compatibility.
- A universal event order across independent game, chat, render, provider, and
  participant-experienced streams.
- Treating possession of an identifier, cursor, artifact reference, or trace
  identifier as runtime authority.

## Ownership boundary

| Shared kernel owns | Domain owner still owns |
| --- | --- |
| Portable `ArtifactRef` shape | API-11 artifact lifecycle, delivery tickets, staging, integrity state, and storage |
| Portable `SecretRef` shape | API-02 secret storage, binding, resolution, and rotation |
| Generic `ResourceRef`, scoped `PublicHandle`, and `TypedObject` shapes | Domain resource types; API-03/API-18 handle scope/lookup; each domain's exact data schemas |
| Command/receipt/error envelopes | Each command's payload, aggregate transition, minimum durability, and result/error-detail schemas |
| Identifier encoding and registry rules | Each API's issuance authority, lifecycle, and safe exposure |
| Stream positions, cursors, and fencing values | API-06/API-10 stream ownership, leases, append policy, and compaction |
| Privacy classification labels | The self-hosting institution's retention, lawful purpose, consent, data rights, and deletion practices (ADR 0015) |
| Schema references and evolution rules | Each owning API's schemas, upcasters, and archival readability support window |

## Core processing boundary

```text
untrusted WireCommandEnvelope
        │ verify runtime identity, resolve target, validate schema and membership
        ▼
trusted server-derived CommandContext
        │ check revision, state, effect validity, lease, and deadline
        ▼
domain transition / durable job / authoritative runtime
        │
        ├── immutable CommandReceipt for a terminal accepted/rejected/indeterminate result
        └── privacy-safe DomainError when no terminal command result was committed
```

A socket acknowledgment, HTTP status, queue acknowledgment, mutable job status,
and domain receipt are different claims. No API may label all of them `success`.

## Global invariants

1. Version-`0` contracts never enter published or retained research evidence.
2. Wire input cannot construct a trusted `CommandContext`.
3. Identifiers are typed references, never runtime-authority credentials or
   order.
4. One idempotency scope/key has one semantic command fingerprint and at most
   one terminal receipt.
5. Wall-clock time and UUID sort order never establish canonical order.
6. Effects recheck runtime identity/membership, lifecycle state, deadline, and
   fencing at application time.
7. Secret material never appears in ordinary JSON contracts.
8. Unknown critical schemas are preserved and rejected, never silently skipped.
9. Archived bytes remain unchanged; upcasting produces a derived representation.
10. Privacy classifications join by choosing the stricter disclosure base and
    taking the normalized union of restrictions; owning schemas may add
    restrictions, institutions may impose handling outside MUG, and no
    reference establishes runtime membership.

## Required reviews

The contract remains Draft until the [review record](review-record.md) has
accountable sign-off from domain/science, runtime/distributed systems,
data/replay, and security/privacy reviewers. Proposed ADRs 0008 through 0011
must be accepted or superseded at the same review.
