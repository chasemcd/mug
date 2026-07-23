# Functional-Parity Contract

| Field | Value |
| --- | --- |
| Status | Proposed |
| Last updated | 2026-07-20 |
| Governing decision | [ADR 0001](decisions/0001-functional-parity-not-backward-compatibility.md) |

The replacement platform does not need to run old MUG code. It does need to
retain the useful capabilities of the platform. This document defines that
boundary so that freedom to redesign APIs does not accidentally become freedom
to delete functionality.

## What parity means

Functional parity means that an equivalent experiment can be authored and run
on the new architecture. It does not require the same:

- Python class, function, or fluent-builder API
- Configuration keys or defaults
- Socket event names or payloads
- Browser implementation
- Filesystem or CSV layout
- Deployment procedure
- Automatically inferred behavior
- Incidental behavior, race condition, or existing bug

Unsafe behavior may be replaced by an explicit, safer capability. For example,
arbitrary browser-authored global state need not remain, but declared,
schema-validated participant state must be available.

## Capability inventory

The final Phase 0 review must assign every row a reference scenario and an
automated acceptance owner. The target phase indicates when the replacement is
expected to exist, not when its API must first be designed; all APIs are
reviewed in Phase 0.

### Study flow and participant experience

| Current capability to preserve | Target expression | Target phase |
| --- | --- | --- |
| Ordered participant flow with start, content, interactive, and terminal stages | Compiled `FlowSpec` and materialized `VisitPlan` with typed activity occurrences | 1–2 |
| Per-participant randomized and repeated activities | Versioned randomization rules whose outcomes are persisted in the visit plan | 2 |
| Instructions and arbitrary study content | Safe content activity with versioned assets and explicit client manifest | 1 |
| Basic text, choice, scale, and form collection | Typed form protocol and durable response receipt | 1–2 |
| Completion code and redirect workflows | Idempotent completion claim and configurable terminal action | 2 |
| Participant-specific state across activities | Namespaced, schema-versioned state documents with read/write policy | 2 |
| Static asset directories | Declared, hashed asset collections served through the artifact/asset layer | 1 |
| Custom entry and continuous eligibility checks | Versioned eligibility policies with server-side context and recorded decisions | 2 |
| Device, browser, focus, and latency screening | Client-capability evidence plus versioned eligibility rules | 2 |

### Environment and game execution

| Current capability to preserve | Target expression | Target phase |
| --- | --- | --- |
| Gymnasium single-agent environments | Environment adapter and one-seat game channel | 1 |
| Multi-agent/PettingZoo-style environments | Multi-seat game channel with explicit environment-agent mapping | 1 |
| Browser-side Python execution through Pyodide | Browser execution backend selected explicitly in the compiled manifest | 1 |
| Server-authoritative execution | Server game worker/backend with single-writer environment semantics | 1 |
| Browser/P2P multiplayer with rollback | P2P execution backend with deterministic state contract, rollback, reconciliation, and canonicality status | 1 and 3A |
| Multiple concurrent independent games | Interaction coordinator with isolated environment instances | 1 |
| Multiple episodes, reset transitions, limits, and inter-episode UI | Typed episode lifecycle and reset protocol | 1 |
| Default actions, held inputs, frame skipping, and composite keys | Explicit input and action-cadence specifications | 1 |
| WebRTC direct connection with TURN fallback | Declared P2P transport configuration and operational secret references | 1 and 6 |
| Disconnect, reconnect, focus loss, and partner-loss handling | Explicit connection leases and interaction recovery/termination policies | 1–2 |
| Unity/WebGL activity integration | Versioned external-client activity adapter with episode and score events | 2 or an approved replacement milestone |

### Humans and conventional policies

| Current capability to preserve | Target expression | Target phase |
| --- | --- | --- |
| Keyboard-controlled human actors | Human input controller binding with declared input map | 1 |
| Random policies | Seeded random controller | 1 |
| Browser ONNX inference | Versioned browser model controller and model artifact | 1 |
| Python heuristic policies in browser or server | Versioned deterministic controller artifact for supported backends | 1 |
| Server-loaded custom policies | Versioned server-side Python controller artifacts loaded through the core authoring API | 1 |
| Mixed human and software-controlled environment agents | Seats, actor instances, and per-channel controller bindings | 1 |
| Per-actor policy state | Controller instance lifecycle and snapshot contract where recovery is claimed | 1–3A |

### Matchmaking and multiplayer operations

| Current capability to preserve | Target expression | Target phase |
| --- | --- | --- |
| Waiting rooms and automatic grouping | Durable interaction membership plus ephemeral matchmaking queues | 1–2 |
| FIFO and latency-aware matchmaking | Versioned matchmaking policies operating on measured eligibility evidence | 2 |
| Countdown and synchronized start | Interaction readiness barrier and server-issued start event | 1 |
| Connection probing and P2P validation | Transport capability probe with recorded result and fallback policy | 1 |
| Re-pooling after failed validation | Idempotent match lifecycle and retry policy | 1–2 |
| Mid-game exclusion and partner termination behavior | Explicit participant, interaction, and evidence finalization policies | 2 |

### Rendering and UI

| Current capability to preserve | Target expression | Target phase |
| --- | --- | --- |
| Surface rectangles, circles, lines, polygons, text, images, arcs, and ellipses | Versioned logical rendering API | 1 |
| Stable object identity, updates, removal, depth, and persistence | Renderer object model and delta protocol | 1 |
| Relative and pixel coordinates | Declared coordinate system | 1 |
| Images, sprite atlases, animation, and asset preloading | Content-addressed asset manifest and renderer support | 1 |
| HUD and page text updates | Typed presentation events separate from private environment state | 1 |
| Tweening and client animation | Versioned client renderer behavior with experienced-stream evidence where required | 1 and 3A |

### Data, evidence, and operations

| Current capability to preserve | Target expression | Target phase |
| --- | --- | --- |
| Collection of actions, rewards, observations, terminations, and `info` metrics | Cross-runtime canonical episode ledger and capture profile | 1 |
| Static/form responses | Typed response records with idempotent durable receipts | 1–2 |
| Scene/experiment metadata export | Immutable study/provenance manifests and queryable lineage | 1 |
| Researcher-defined metrics | Declared event or metric schemas, not arbitrary unversioned columns | 1 |
| P2P action/hash comparison and rollback diagnostics | Canonical reconciliation report plus separate experienced/diagnostic events | 1 and 3A |
| Export for analysis | Schema-bound JSONL exporters with lineage (the single export format, D13-1); old layout is not required | 1 onward |
| Live operator visibility | Ungated read-only operational projections over durable state and live presence | 2 and 6 |
| Session/interaction history and terminal reasons | Durable visit and interaction lifecycle projections | 2 |
| Browser and server diagnostics | Privacy-classified operational logging and trace correlation | 1 and 6 |

## Required reference fixtures

Phase 0 must specify replacement acceptance fixtures for at least:

1. A single human running a browser/Pyodide Gymnasium environment.
2. A human and browser-side ONNX or deterministic policy sharing an
   environment.
3. A human and heuristic policy in both browser and server execution.
4. Two humans completing a rollback-enabled P2P game under latency, packet
   loss, and focus loss.
5. Two humans completing a server-authoritative game with reconnect behavior.
6. Multiple concurrent matches with waiting-room and eligibility behavior.
7. A static/form flow with randomization, repeated activities, participant
   state, completion, and redirect.
8. A Surface-rendering conformance scene covering every logical primitive,
   assets, deltas, removal, depth, and animation.
9. A Unity/external-client activity or an explicitly accepted successor
   capability.
10. A trusted deployment operator observing live and completed interactions
    while apart-stored external identity and secret material remain absent from
    the operational projection.

These fixtures validate capabilities through the new APIs. They do not execute
old experiment scripts.

## Phase 0 parity gate

The parity gate passes only when:

- Every capability is accepted, deliberately replaced, or explicitly removed
  by an ADR approved by the product owner.
- Every retained capability maps to a planned API family and implementation
  phase.
- Every retained capability has at least one acceptance scenario.
- The acceptance definition tests outcomes rather than old internal structure.
- Known correctness and security bugs are not enshrined as required behavior.
