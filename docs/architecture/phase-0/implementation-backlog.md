# Phase 0 → Phase 1 Implementation Backlog

| Field | Value |
| --- | --- |
| Status | Proposed |
| Purpose | Backlog gate: dependency-ordered implementation work derived from the accepted-shape contracts |
| Last updated | 2026-07-20 |

This backlog converts the drafted Phase 0 contracts into dependency-ordered
implementation work. Ordering follows the contract dependency graph. Estimates
are indicative, not commitments. This is the backlog-gate deliverable; it is
`Proposed` and firms up as each contract reaches `Accepted`.

## Dependency layers

```text
L0 Shared kernel runtime (ids, refs, canonical JSON, command/receipt, errors, clocks, privacy)
        │
L1 Storage + evidence + jobs      API-11, API-10, API-22
        │
L2 Authoring + platform           API-01, API-02
        │
L3 Identity + visits              API-03, API-04
        │
L4 Interaction fabric             API-05, API-06, API-09
        │
L5 Execution runtimes             API-07 (game), API-08 (chat)
        │
L6 Agents + providers + tools     API-12, API-13, API-14, API-15
        │
L7 Replay + content + prefs       API-16, API-17, API-18
        │
L8 Export                         API-19 (JSONL; API-20 removed, API-21 retracted)
```

## Ordered work items

| Order | Work item | Depends on | Indicative size |
| ---: | --- | --- | --- |
| 1 | Shared-kernel runtime library (Python + TS): typed IDs, `SchemaRef`/`ArtifactRef`/`SecretRef`, RFC 8785 canonicalization, command context/receipt, error taxonomy, clocks/fencing, privacy lattice | — | L |
| 2 | Local relational + object backend, repository/outbox SPI, unit of work, artifact staging/finalization (API-11) | 1 | L |
| 3 | Canonical event ledger, capture policy, canonical/experienced streams, cursors (API-10) | 1, 2 | M |
| 4 | Durable job/worker runtime with fenced leases, work-key idempotency, compile jobs, and the headless `mug simulate` batch runner (API-22) | 1, 2 | M |
| 5 | Study compiler, git provenance (commit + patch), version strings/digests, manifests, atomic publication of immutable stored versions, catalog (API-01) | 1–4 | L |
| 6 | Two-verb deploy/stop, internal deployment revisions, requirement satisfaction, secret pass-at-deploy and minimal secret store, client projection (API-02) | 1, 5 | M |
| 7 | Pseudonymous enrollment, opaque launch tickets, blinded external identity links, stable return links (API-03) | 1, 5, 6 | M |
| 8 | Visit plan materialization, treatment/exposure, advancement, recovery (API-04) | 5, 6, 7 | L |
| 9 | Seats/actors/controllers (API-05); interactions/channels/membership/leases (API-06) | 7, 8 | M |
| 10 | Participant client protocol, realtime commands, uploads (API-09) | 6, 9, 3, 2 | M |
| 11 | Game runtime (server/browser/P2P), rendering, episodes (API-07) | 9, 10, 3 | L |
| 12 | Conversation runtime, ordering, context snapshots, delivery (API-08) | 9, 10, 3 | L |
| 13 | Controller scheduler/executor with staleness/deadline/fallback (API-12) | 11, 12, 3 | M |
| 14 | Provider adapters (fake + compatible + one direct), usage/provenance (API-13) | 13, 6 (secrets) | M |
| 15 | Tools, approval, egress, idempotency, environment mailbox (API-14) | 13 | M |
| 16 | Agent memory scopes, compare-and-swap, provenance (API-15) | 12, 13 | M |
| 17 | Replay capture, bundles, validation, safe player (API-16) | 3, 11, 13, 14 | L |
| 18 | Forms, presentation, accessibility (API-17) | 8, 10 | M |
| 19 | Preference protocols, candidates, assignment, response, quality (API-18) | 16, 17, 3 | M |
| 20 | JSONL dataset query/export/lineage (API-19) | 3, 2, 16, 18 | M |
| — | Governance (API-20): **removed** under F-4/ADR-0015 — no work item; the researcher-owned store and institution provide access control, retention, and deletion | — | — |
| — | Plugins (API-21): **retracted for v0** under D15-1..3 — no work item; core authoring in plain Python is covered by items 5, 11, 13, 15 | — | — |

The security mechanisms that remain in scope are implemented with their owning
families, not as a separate layer: minimal secret storage/reference and
isolation at deploy (API-02, item 6), immutable event capture (API-10, item 3),
and the participant-safe client projection (API-01/02, items 5–6). There is no
governance layer (F-4).

## Phase 1 minimal parity subset

The first release should target the smallest end-to-end slice that proves the
architecture: items 1–11, whose baseline security mechanisms (secret isolation
at deploy, immutable event capture, participant-safe client projection) ride
along with their owning items. That subset delivers
authoring → deployment → enrollment/visit → single- and multi-writer game with
capture sufficient for the later visual-replay layer. It covers the selected
current-parity fixtures without the
agent, conversation, preference, and longitudinal features layered in Phases 3–5.

## Exit conditions carried into Phase 1

- Every item above lists its owning contract; no item begins before its contract
  reaches `Accepted` (or a time-bounded waiver ADR).
- Contract fixtures become the acceptance tests for each item.
- The parity fixtures and NS golden fixtures are ported as integration gates.
