# Phase 0 Integrated North-Star Walkthrough

| Field | Value |
| --- | --- |
| Status | Proposed |
| Purpose | Gate 0I: walk every acceptance scenario through the drafted API families with no undefined API, unowned state, unversioned payload, ambiguous authority, or unhandled failure |
| Last updated | 2026-07-18 |

This document traces each [acceptance scenario](acceptance-scenarios.md) NS-01
through NS-12 across the drafted API-family contracts. It is the gate-0I
deliverable. It is `Proposed`, not `Accepted`: acceptance requires golden
end-to-end fixtures per scenario and the four sign-offs per family, which remain
open. Each per-family contract is `Drafted` and test-backed; this document shows
they compose.

## Scenario traces

| Scenario | End-to-end path across families |
| --- | --- |
| **NS-01 Preference over trajectories** | API-01 compiles the study + preference protocol → API-04 materializes the preference activity → API-16 supplies immutable trajectory candidates → API-18 blinds/orders candidates → API-17 presents → API-11 durably records the response → API-19 exports with lineage |
| **NS-02 Preference over LLM outputs** | API-13 normalized generations / API-08 chat messages become API-18 candidates → API-18 blinds provider/model identity → API-17 presents → API-19 exports reward-model shape with lineage |
| **NS-03 One human + one LLM chat** | API-05 seats (human, LLM) + controller bindings → API-06 chat channel + membership → API-08 turn/activation policy → API-12 schedules the LLM decision → API-13 provider call (secret by key) → API-08 delivery + context snapshot |
| **NS-04 Multiple humans + one LLM** | API-06 channel membership/visibility → API-08 total ordering + activation budget → API-12/13 single agent → API-10 evidence per message |
| **NS-05 Multiple humans + multiple LLMs** | API-05 multiple software actors with independent bindings → API-13 per-agent model/prompt/tools → API-08 per-agent visibility/activation → API-12 independent schedulers |
| **NS-06 Humans play while chatting** | API-06 one interaction with independent game + chat channels → API-07 game transitions (per-producer order) + API-08 chat (total order) → API-10 causally linked, independently ordered streams |
| **NS-07 LLM plays and chats** | API-12 admits slow decisions without blocking frames; in P2P, one fenced designated peer produces each bot seat's recorded result → API-07 applies the validated action and reuses it during rollback → API-08 independently publishes optional messages → API-16 performs zero-provider replay from the decision tape |
| **NS-08 Durable longitudinal recovery** | API-03 enrollment + stable return link (consent is an ordinary flow activity; multi-part flow, no waves) → API-04 pins study version + deployment revision and materializes the plan → server restart → API-04 reloads the plan, never re-samples; API-02 revision pinned across redeploy |
| **NS-09 P2P rollback, evidence, replay** | API-06 freezes a generation-fenced three-peer full-mesh membership → API-07 records speculative → confirmed → verified frame evidence, RNG-complete logical snapshots, and the minimum end-frame-exclusive barrier → disagreement remains disputed while lower-ID-defers controls live repair only → API-10 preserves each producer claim → API-16 replays verified canonical actions or declares confirmed-only/disputed/visual fallback honestly |
| **NS-10 Preference submission failure/recovery** | API-17 response requires a durable receipt → API-11 unit of work + idempotency → a refresh cannot duplicate or lose the accepted response (shared-kernel idempotency) |
| **NS-11 Tool side effect, timeout, replay** | API-12 deadline/staleness → API-14 approval + idempotent execution; a possibly-executed effect is a durable indeterminate outcome → API-16 substitutes the recorded result, makes no external call |
| **NS-12 Privacy, export, researcher-owned store** | API-03 pseudonymity + blinded `ExternalIdentityLink` stored apart → API-19 ungated JSONL export with complete lineage → withdrawal/deletion handled by the researcher against their own store (F-4; not a MUG feature); secrets stay server-side by reference (API-02/shared kernel) |

## Authority trace (one writer per transition)

| Transition | Sole authority |
| --- | --- |
| Study publication | API-01 study aggregate lock |
| Deployment revision | API-02 deployment aggregate |
| Visit plan materialization / advancement | API-04 visit aggregate |
| Environment step | API-07 single writer per instance/replica |
| Chat message order | API-08 server total order per channel |
| Decision acceptance | API-12 effect-time generation/deadline recheck |
| Tool side effect | API-14 approval + idempotency |
| Memory commit | API-15 compare-and-swap |
| Durable commit | API-11 unit of work (state + idempotency + event + outbox) |
| Secret resolution | API-02/shared kernel server-side secret store (never the client) |
| Immutable event capture | API-10 append-only canonical ledger (no rewrite path exists) |

## Failure trace (every command has a defined outcome)

- Duplicate command → same receipt (shared-kernel idempotency; API-11 outbox).
- Crash before commit → no partial state or receipt; crash after commit → original
  receipt on retry (API-11/API-01/API-04).
- Provider/tool timeout → fallback policy (API-12); possibly-executed external
  effect → durable indeterminate, never auto-retried (API-14, shared-kernel).
- Stale decision → discarded (API-12); stale memory write → rejected (API-15).
- Connection loss → lease expiry, non-authoritative (API-06); reconnect resumes
  from a durable cursor (API-09).
- Modified replay artifact → detected; determinism unavailable → visual fallback
  declared (API-16).

## Open items before acceptance

1. Golden end-to-end fixtures for each NS scenario (currently per-family slices).
2. The four named review sign-offs per family and for the shared kernel.
3. Acceptance of the proposed ADRs (0002–0015) and the shared-kernel version-1
   freeze.
4. Independent browser-side schema/canonicalization/disclosure runner.

With those closed, this walkthrough becomes the gate-0I acceptance record. Until
then it demonstrates compositional coverage, not final acceptance.
