# Shared-Kernel Review Record

| Field | Value |
| --- | --- |
| Status | Core layer frozen 2026-07-20 (ADR-0008/0011 accepted); runtime layer Draft |
| Contract revision | `0.2` |
| Review opened | 2026-07-17 |
| Accountable owner | Unassigned |
| Target accepted version | `1` |

This page records evidence and unresolved decisions. A checked drafting item is
not approval. Only named reviewer sign-off can move the contract to Accepted.

## Deliverable status

| Foundation | Status | Evidence |
| --- | --- | --- |
| Shared IDs and resource hierarchy | Drafted | [Identifiers](identifiers-and-resource-hierarchy.md) and proposed ADR 0008 |
| Schema and protocol evolution | Drafted | [Serialization/evolution](serialization-and-schema-evolution.md), version-0 schema, proposed ADR 0008 |
| Commands, receipts, events, and errors | Drafted | [Command contract](commands-receipts-and-errors.md), fixtures, proposed ADR 0009 |
| Authority, clocks, ordering, and fencing | Drafted | [Time/order/fencing](time-ordering-and-fencing.md), proposed ADR 0010 |
| Privacy, secrets, and classification | Drafted | [Privacy classification/secrets](privacy-retention-and-secrets.md), proposed ADR 0011 as narrowed by ADR 0015 |
| Stability tiers | Drafted | [Serialization/evolution](serialization-and-schema-evolution.md) |
| Automated schema/fixture validation | Drafted | [Conformance plan](conformance.md); the full architecture suite (`uv run pytest tests/architecture -q`) reports 636 passing schema, fixture, parser, digest, registry, cross-language canonicalization, and bounded semantic tests |

## Specification checklist

- [x] Scope, non-goals, consumers, and ownership boundary drafted
- [x] Definition/version/occurrence/security/content identity classes drafted
- [x] Registered ID kinds and resource hierarchy drafted
- [x] `SchemaRef`, `TypedObject`, `ArtifactRef`, `SecretRef`, `ResourceRef`,
      `PublicHandle`, `VersionStamp`, `EventCursor`, lease, privacy,
      principal, capability, and trace values drafted
- [x] Wire command versus trusted context boundary drafted
- [x] Idempotency, semantic fingerprint, concurrency, Unit-of-Work, receipt, and
      error semantics drafted
- [x] Wall/monotonic/client/provider clocks, stream/producer ordering, and
      fencing semantics drafted
- [x] Canonical JSON, numeric, binary, timestamp, schema evolution, and unknown
      version behavior drafted
- [x] Privacy inheritance, destination matrix, secret boundary, and negative
      leakage cases drafted
- [x] Initial version-0 JSON Schema and valid/invalid fixture plan drafted
- [x] Automated schema/fixture/parser tests pass (636 current architecture-suite tests)
- [x] Fixture-owned domain schemas prove exact second-stage payload, result,
      and error-detail validation and reject a wrong schema digest
- [ ] Independent Python and browser RFC 8785 vectors pass
- [ ] Python and TypeScript mapping/code-generation decision accepted
- [ ] API-10 event envelope compatibility reviewed
- [ ] API-11 artifact/transaction compatibility reviewed
- [x] 0.2 re-draft executed: ADR-0013/0014/0015 retirements folded in (retired
      kinds dropped from the ID pattern, `RetentionPolicyRef` removed,
      `DataHandlingRef` reduced to privacy labels, API-20 ownership re-owned)
- [x] Removed the retired `plugin.*` branches from the version-0 `SchemaName`
      and `CapabilitySet` patterns, added one-defect rejection fixtures, and
      restamped the shared-kernel digest (ADR-0015)
- [ ] NS-08, NS-10, and NS-12 concrete walkthroughs completed
- [ ] ADRs 0008–0011 accepted
- [ ] Four required review sign-offs recorded
- [ ] Version-1 bytes frozen and version 0 rejected by publication compiler

## Hardening-audit disposition

| Finding | Draft disposition | Remaining acceptance evidence |
| --- | --- | --- |
| Longitudinal resources were nested under immutable versions | `StudyVersion`, `Deployment`, and `Enrollment` are parallel study-owned lifecycles; each visit pins both immutable versions | API-01/API-03/API-04 walkthrough |
| Generic references could disagree about kind | `ResourceRef` now contains one registered typed ID; its prefix is the sole kind discriminator | Generated Python/TypeScript nominal types |
| Domain payload/result/details were unbound objects | `TypedObject` carries exact name/version/digest and requires second-stage allowlisted validation before fingerprints or effects | Each domain API registers its exact schemas |
| Foreign monotonic ticks were treated as portable | Coordinator retains the authoritative deadline/lease clock; remote work receives a bounded local budget and effect-time recheck | API-12/API-14/API-22 fault tests |
| Privacy had no deterministic ordering | Canonical label-set lattice has one `public`/`research` base plus `sensitive`/`pii` restrictions and a defined join | Label-lattice vectors in the shared suite |
| Malformed input could lack a valid request ID | `DomainError.request_id` is optional until structurally validated; server `error_id` and support reference remain required | API-09 malformed-byte fixtures |
| Study identity and content identity conflicted | Study versions are immutable and content-bound; identical publication is idempotent | API-01 publication state machine |
| Idempotency ignored pinned versions | Runtime scopes include study version and deployment revision; the base context now permits pre-publication/platform commands without inventing versions and binds their exact domain target/input in the fingerprint | API-01/API-02 stateful duplicate/restart tests |
| Compaction could erase retained evidence | Ordinary compaction preserves original bytes, positions, and cursor meaning; only institution-executed deletion expires cursors | API-10 compaction tests |
| Blinded handles were underspecified | Fixed 128-bit canonical `PublicHandle` plus mandatory scope and non-authorizing semantics | API-03/API-18 binding lifecycle |

These findings are resolved at the Draft contract level, not accepted runtime
behavior. The unchecked checklist and sign-off gates remain deliberate blockers.

## Required review sign-off

| Review | Reviewer | Decision | Date | Notes |
| --- | --- | --- | --- | --- |
| Domain/scientific validity | Agent panel (G7) | Sign-off (core) | 2026-07-20 | 3 MAJOR: float vectors added; receipt anchor (D1) + artifact-unblinding (D2) dispositioned; core layer clean |
| Runtime/distributed systems | Agent panel (G7) | Deferred (runtime layer) | 2026-07-20 | BLOCK items (LeaseRef/EventCursor/StreamPosition/Duration fixtures, NS-10/12) are runtime-layer per D3 — out of core-freeze scope |
| Data/replay | Agent panel (G7) | Sign-off (core) | 2026-07-20 | BLOCK (local `json.dumps` canonicalizer) fixed + guard added; float/`-0`/collapse + key-order divergence vectors added |
| Security/privacy | Agent panel (G7) | Sign-off (core) | 2026-07-20 | No leakage/impersonation hole found; `PrivacyLabel` footgun removed; Receipt/ArtifactRef destination-matrix rules added |
| Accountable owner (human, PG-1) | Chase M. | Signed off (core) | 2026-07-20 | Real-human-review complete; ADR-0008/0011 accepted, core layer recorded frozen |

## Core-layer promotion status (2026-07-20)

The kernel is promoted in **two freeze events** (decision D3, narrow freeze):

- **Core layer — freeze target NOW:** identifiers and resource hierarchy;
  canonical JSON / serialization / numeric profile / schema evolution;
  `TypedObject`, `SchemaRef`, `ArtifactRef`, `SecretRef`, `PublicHandle`,
  `VersionStamp`; the privacy classification lattice + `DataHandlingRef`; the
  wire-command envelope + the `DomainError` taxonomy. **ADRs: 0008 + 0011.**
- **Runtime layer — freeze WITH API-06/12:** command/receipt/idempotency
  (**ADR-0009**) and clocks/ordering/fencing — `LeaseRef`, `EventCursor`,
  `StreamPosition`, `Duration` (**ADR-0010**). Deferred here: D1 (self-contained
  receipt: embed pinned versions + `semantic_fingerprint`), and the runtime
  review-panel items — indeterminate-receipt `stream_positions`/`error.code`
  constraints, fencing rule-4 epoch+generation wording, idempotency-scope
  discriminator reconciliation, the four value-type shape fixtures, and the
  NS-10/12 walkthroughs.

**Gate status for the core layer:**

| Gate | State |
| --- | --- |
| G1 spec completeness | Met (core surfaces) |
| G2 schema + fixtures | Met (638-test corpus; kernel bundle `f675d9ec…`) |
| G3 scenario traces | Kernel obligations covered by shape+semantic+lattice fixtures; full cross-family NS traces per-wave (PG-4) |
| G5 cross-language conformance | **Met** — `_contract_harness.canonical_bytes` is conforming RFC 8785 (`rfc8785`); 41 vectors pass in Python **and** Chromium (`canonicalize.js`), incl. integral-float collapse, `-0`, exponent edges, and the UTF-16-vs-code-point key-order divergence. SK-O04 implementation selection: `rfc8785` (Python) + reference `canonicalize` (JS); final library pin recorded at freeze |
| G6 ADR acceptance | **Met** — ADR-0008 + ADR-0011 Accepted 2026-07-20 (core layer); ADR-0009/0010 *decisions* Accepted 2026-07-20, runtime-layer byte-freeze deferred to API-06/12 |
| G7 review | **Met** — agent panels complete (2 sign-off, 2 block → data/replay resolved, runtime deferred) + accountable-owner human sign-off 2026-07-20 |
| G8 freeze | **Met (core layer)** — core bytes recorded frozen; reject-v0 rule stands (version 0 fails publication/deployment validation); core digest checkpoint `f675d9ec1f6258719da93a507421689b26babf69d36503c7df90b5039e238d6d` (provisional; whole-bundle immutable v1 digest finalized at the runtime-layer freeze) |

The accountable-owner (human) sign-off is **recorded 2026-07-20**: ADR-0008 and
ADR-0011 are Accepted and the core layer is recorded frozen. The core `$defs` are
change-controlled from here; the whole-bundle immutable v1 digest is finalized
when the runtime layer freezes with API-06/12, with `f675d9ec…` as the
provisional core checkpoint until then.

## Open decision log

| ID | Decision needed | Proposed default | Blocks |
| --- | --- | --- | --- |
| SK-O01 | Definition-key continuity across rename and fork | Validate author-chosen keys against published history; forks receive explicit lineage and no mutable registry | API-01 acceptance |
| SK-O02 | UUIDv7 generation library, same-millisecond behavior, and offline issuance | Server-issued canonical IDs; scoped source IDs for approved replicas | Version 1 |
| SK-O03 | Exact accepted ID-prefix registry | Current draft table | Version 1 |
| SK-O04 | Python/browser RFC 8785 implementations | Select only after cross-language vectors | Version 1 |
| SK-O05 | Runtime validation/type generation library | JSON Schema remains normative; implementation library cannot change meaning | Phase 1 backlog |
| SK-O06 | Deterministic environment snapshot and trajectory codecs | Separate binary-codec ADR | API-07/API-16 acceptance |
| SK-O07 | Inline binary maximum | At most 4 KiB; domain may be lower | Version 1 |
| SK-O08 | Artifact digest exposure and physical dedup scope | Trusted/archival ref; client delivery ticket may redact; no cross-classification dedup | API-11 |
| SK-O09 | Credential rotation and deployment revision | Pin the logical binding; record the actual binding revision as exposure/provenance | API-02 |
| SK-O10 | Institution-executed event removal and cursor expiry | Ordinary compaction preserves original bytes and logical positions; only institution-executed deletion expires a cursor and requires an explicit snapshot/restart route | API-10 |
| SK-O11 | Schema bundle embedding/signing | Bundle must be offline-complete; exact packaging/signature pending | API-01/API-16 |
| SK-O12 | ETag projection/hash profile | Canonical audience-scoped projection, exact fields domain-owned | Domain APIs |
| SK-O13 | Journaled durability profiles | Deployment-pinned named failure model | API-07/API-10/API-11 |
| SK-O14 | Lifetime of ephemeral input idempotency | Capture-profile-specific bounded window | API-07/API-09 |
| SK-O15 | Client handle scope, lookup, rotation, and expiry policy | Shared `PublicHandle` encoding is fixed; API-03/API-18 must define audience, purpose, lifetime, and non-linkability policy | API-03/API-18 |

## Acceptance-scenario trace

| Scenario | Shared-kernel obligations |
| --- | --- |
| NS-01/NS-02 | Typed occurrence/artifact/schema IDs, immutable content refs, privacy/blinding, artifact commit receipt |
| NS-03–NS-05 | Actor-safe command context, channel ordering, effect-time membership/fencing, protected content/error boundaries |
| NS-06/NS-07 | Independent modality coordinates, async deadline/stale decision, receipt durability, fallback provenance |
| NS-08 | Pinned immutable versions, stable receipts, revision/plan state, protected external identity |
| NS-09 | Producer epochs/sequences/digests, replica authority, reconciliation, partial/disputed evidence |
| NS-10 | Idempotency fingerprint/scope, byte-equivalent receipt, conflict, atomic progression |
| NS-11 | Authority fence, unknown external outcome, no duplicate effect, causation and stale-memory prevention |
| NS-12 | Data handling labels, secret boundary, export lineage, institution-owned unlink/deletion |

## Change log

| Date | Revision | Change |
| --- | --- | --- |
| 2026-07-25 | `0.2` | Evidence only; the core-layer freeze holds and the bundle digest is still `f675d9ec…`. Added the `EventCursor` fixtures the [contract freeze](../contract-freeze.md) measured as missing: a valid cursor at `after_sequence` 0 (the position before the first event, the one value that separates a cursor from a `StreamPosition`), and two rejections -- a negative sequence and a version-4 stream id. `EventCursor` is a runtime-layer type whose byte-freeze stays deferred to the API-06/12 freeze; this records that the contract and the record model agree about it now |
| 2026-07-20 | `core-freeze-ready` | Ran the core-layer promotion gates. G5: migrated `canonical_bytes` to conforming RFC 8785 (`rfc8785`; 0 corpus digest deltas), amended the numeric profile (finite floats permitted), built 41 cross-language vectors passing in Python + Chromium. G7: four adversarial review panels (2 sign-off, 2 block). Folded the resolvable findings: removed the unreferenced `PrivacyLabel` enum (bundle `19f024dc…` → `f675d9ec…`), migrated the two remaining local `json.dumps` canonicalizers + added a frozen-anchor guard, added float/`-0`/collapse + key-order-divergence vectors, added the Receipt + `ArtifactRef`-archival destination-matrix rules. Deferred the runtime-layer findings (D1 + fencing/ordering/idempotency) to the API-06/12 freeze (D3). 638 tests. Core layer pending human sign-off + ADR-0008/0011 acceptance |
| 2026-07-20 | `0.2 correction` | Completed the ADR-0015 plugin retraction in executable shared-kernel bytes: `SchemaName` and `CapabilitySet` now accept only `mug.*`; added two one-defect invalid fixtures; restamped bundle digest `f6ea55c7…` → `19f024dc…`; 50 tests |
| 2026-07-19 | `0.2` | Registered the `group` prefix (`GroupId`, runtime occurrence, API-06) in the ID registry and version-0 pattern for the R-18 shared Group object; kernel digest cascade restamped |
| 2026-07-19 | `0.2` | Executed the ADR-0013/0014/0015 re-draft: dropped the retired kinds (`studydraft`, `draftrev`, `account`, `authsession`, `wavedef`, `retpolicy`, `retpolicyver`) from the version-0 ID pattern and moved them to the reserved (retired) prefix list; removed `RetentionPolicyRef` and the `account` principal branch; reduced `DataHandlingRef` to `privacy_labels` only; re-owned the former API-20 registry cells (`service`/`system` to the shared kernel/runtime, `researcher` to API-03, `secret` to API-02); regenerated the schema digest cascade and fixtures |
| 2026-07-17 | `0.1` | Hardened the draft after architecture/schema audits; added exact typed-object and shared semantic validation and expanded the Python suite to 47 tests |
| 2026-07-17 | `0.1` | Opened first concrete shared-kernel review with proposed schemas and fixture plan |
