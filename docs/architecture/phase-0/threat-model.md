# Phase 0 Threat Model and Data-Flow Inventory

| Field | Value |
| --- | --- |
| Status | Proposed |
| Purpose | Gate 0H: threat model covering every external boundary, plus the data-flow and privacy inventory |
| Last updated | 2026-07-20 |

This document consolidates the security and privacy decisions distributed across
the API families into one threat model. It is the gate-0H deliverable. It is
`Proposed`, not `Accepted`: acceptance requires the four named security sign-offs
recorded in each family review record and in the shared-kernel review record.

## Trust boundaries

The platform crosses these boundaries; each is a distinct trust zone.

| # | Boundary | Untrusted input | Owning controls |
| --- | --- | --- | --- |
| B1 | Browser ↔ server | Client-supplied identity, ownership, intent payloads | API-09 (server derives identity from launch), shared-kernel wire command vs command context |
| B2 | Peer ↔ peer (P2P) | Remote replica inputs and monotonic ticks | API-07 finality/reconciliation, shared-kernel fencing |
| B3 | Server ↔ worker | Job payloads, lease claims | API-22 fenced leases, API-11 unit of work |
| B4 | Server ↔ model provider | Prompts out, generations in, hidden backend | API-13 secret-by-key, safe output handling, exposure evidence |
| B5 | Server ↔ tool / MCP | Tool arguments out, results and side effects in | API-14 approval, egress allowlist, SSRF defense, idempotency |
| B6 | Server ↔ object store | Artifact bytes, keys | API-11 content addressing and integrity verification; researcher-owned storage |
| B7 | Server ↔ database | Query/txn | API-11 unit of work, optimistic concurrency; researcher-owned store |
| B8 | Server ↔ author study code | The researcher's own envs/policies/renderers/tools from the study repo | API-01 git provenance + content digest pins exactly what ran; no third-party plugin framework in v0 (API-21 retracted) |
| B9 | Server ↔ recruitment / external identity | External subject IDs, PII | API-03 blinded `ExternalIdentityLink`, stored apart, `pii` classification |
| B10 | Researcher/operator ↔ platform | Operator commands | Ungated by design (F-4): MUG is self-hosted and the researcher owns the deployment; immutable event capture (API-10) preserves evidence integrity |

## Primary threats and mitigations

| Threat | Boundary | Mitigation (owning family) |
| --- | --- | --- |
| Client forges identity or ownership | B1 | Identity derived from authenticated launch, never client fields (API-09); opaque launch ticket (API-03) |
| Secret material reaches a browser or event | B1/B4/B6 | Secrets never in client projections, events, keys, or logs; `SecretRef`/binding only, resolved server-side (API-02/13/shared kernel) |
| Blinded condition leaked to a participant | B1 | Positive-allowlist client projections; blinded display handles; no raw identity in candidates (API-02/17/18) |
| Slow/malicious provider stalls a frame | B4 | Async scheduler; decisions never block the environment lock (API-12); provider latency isolated (API-13) |
| Stale/cancelled decision mutates state or memory | B4/B5 | Effect-time generation/deadline recheck; stale decisions discarded (API-12); compare-and-swap memory (API-15) |
| Duplicate external side effect | B5 | Idempotency keys; possibly-executed effect becomes durable indeterminate, never auto-retried (API-14, shared-kernel) |
| SSRF / unbounded egress from a tool | B5 | Deny-by-default egress allowlist and SSRF defense (API-14) |
| Author study code misbehaves | B8 | Self-hosted trust model: study code is the researcher's own, pinned by git provenance and content digest (API-01) so exactly what ran is recorded; no third-party plugin distribution exists in v0 |
| PII linkage across contexts | B9 | Pseudonymous enrollment; external identity only in the blinded `ExternalIdentityLink`, stored apart (API-03) |
| Tampered replay bundle or hidden external call | B6 | Integrity validation detects modified artifacts; exact replay makes zero external calls (API-16) |
| Evidence rewrite by an operator | B10 | Canonical events are immutable and append-only (API-10); termination/quarantine append new facts, never edit prior ones; operator access itself is ungated (self-hosted, F-4) |
| Re-identification via export | B6/B10 | Complete lineage; redaction produces a new lineage object (API-19); export is ungated — access control is the self-hosting institution's responsibility |

## Data classification and allowed flows

Privacy classification is the shared-kernel lattice: one base disclosure label
(`public` or `research`) plus optional `sensitive` and `pii` restrictions.
`secret` is deliberately outside research-data classification.

| Class | May appear in | Must never appear in |
| --- | --- | --- |
| `public` | Client manifest/projection (when approved), exports | — |
| `research` | Server manifests, events, artifacts, declared exports | Participant-facing surfaces unless the compiled study requires the data |
| `research+sensitive` | Server manifests, encrypted artifacts, restricted/redacted exports | Unrelated client projections, ordinary logs |
| `research+pii` | The blinded external-identity link, stored apart (API-03) | Enrollment records, events, client surfaces, ordinary exports |
| `secret` | Minimal secret store (API-02/shared kernel), server-side resolution (API-02/13) | Client manifests, events, object keys, logs, exports |

## Data-flow inventory (representative)

1. **Launch:** external reference → API-03 blinded `ExternalIdentityLink`
   (pii, stored apart) → pseudonymous enrollment → opaque launch ticket →
   browser (no principal, no pii).
2. **Participation:** browser intent (B1) → API-09 (identity derived) → API-06
   channel → API-07/08 execution → API-10 canonical event + API-11 unit of work.
3. **Agent turn:** API-12 request → API-13 provider (secret resolved server-side,
   B4) → normalized generation + usage exposure → API-10 evidence.
4. **Tool call:** API-12 → API-14 approval → egress (B5, allowlisted) →
   idempotent result → API-10 evidence.
5. **Export:** API-10/11 evidence → API-19 JSONL export with lineage →
   self-hosting researcher (B10, ungated), redaction as a new lineage object.

## Residual risks and follow-ups

- Cryptographic launch-ticket format and replay defense (A03-O02) — pending.
- MCP sandbox, supply-chain, and signature policy (API-14) — pending.
- Key rotation and backup/restore — Phase 6; organizational access control is
  the self-hosting institution's, not MUG's (F-4).
- Independent browser-side disclosure/canonicalization runner — pending across
  API-01/02/09/18.

Acceptance of this threat model is gated on the security sign-offs in the family
review records; those remain `Pending`.
