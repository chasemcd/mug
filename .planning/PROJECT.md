# Interactive Gym — P2P Multiplayer

## What This Is

A framework for running browser-based reinforcement learning experiments with human participants. The P2P multiplayer system implements true peer-to-peer connections with GGPO-style rollback netcode, enabling fighting-game-smooth responsiveness for research experiments where both players experience local-feeling input response regardless of network latency.

## Core Value

Both players in a multiplayer game experience local-feeling responsiveness regardless of network latency, enabling valid research data collection without latency-induced behavioral artifacts.

## Current Milestone: v1.21 Latency-Aware Matchmaking

**Goal:** A FIFO matchmaker that pre-filters candidates by server RTT heuristic before proposing matches, then verifies with P2P probe — so only low-latency pairs get matched.

**Target features:**

- [ ] `LatencyFIFOMatchmaker` class: FIFO ordering with server RTT pre-filtering in `find_match()`
- [ ] Configurable `max_server_rtt_ms` threshold for pre-filtering (estimated P2P RTT = sum of server RTTs)
- [ ] Works with existing `max_p2p_rtt_ms` for post-match P2P probe verification
- [ ] Exposed via `scene.matchmaking(matchmaker=LatencyFIFOMatchmaker(...))`

**What done looks like:**
- Researcher configures `LatencyFIFOMatchmaker(max_server_rtt_ms=200, max_p2p_rtt_ms=150)`
- `find_match()` skips candidates where sum of server RTTs exceeds threshold
- Post-match P2P probe verifies actual latency before game creation
- Falls back gracefully when server RTT data is unavailable

## Previous Milestone: v1.20 Pre-Game Countdown (Shipped: 2026-02-07)

**Delivered:** 3-second "Players found!" countdown on waiting room screen after matchmaking, synced game start.

## Previous Milestone: v1.19 P2P Lifecycle Cleanup (Shipped: 2026-02-07)

**Delivered:** P2P connections scoped to GymScenes — torn down on scene exit, with group history preserved for future re-pairing.

## Previous Milestone: v1.18 Loading UX & Cleanup (Shipped: 2026-02-07)

**Delivered:** Single merged loading screen gating on both compatibility check and Pyodide readiness, with configurable timeout and error page. Cleaned up orphaned test fixtures and duplicate helpers.

## Previous Milestone: v1.17 E2E Test Reliability (Shipped: 2026-02-06)

**Delivered:** 100% E2E test pass rate — 24 tests across 8 modules, zero failures. Robust server fixture lifecycle, P2P timeout tuning, GGPO fixes, and documented content parity limitation.

**Key accomplishments:**
- Robust server fixture lifecycle with port-verified teardown (shared helpers)
- P2P ready gate timeout fix (5000ms → 15000ms) for 200ms latency tests
- All 24 E2E tests pass (23 passed + 1 xfail for GGPO architectural limitation)
- Two GGPO fixes: prune guard + boundary ordering
- GGPO content parity limitation documented in backlog with recommended fix approach

## Previous Milestone: v1.16 Pyodide Pre-loading (Shipped: 2026-02-06)

**Delivered:** Pyodide pre-loading during compat check, shared instance reuse, server-side grace period, concurrent game starts with 0.5s stagger.

**Key accomplishments:**
- Pyodide loads during compatibility check screen (before matching)
- Game classes reuse pre-loaded instance (near-instant game startup)
- Server tolerates missed pings during loading (ping_timeout=30, LOADING_CLIENTS grace)
- Stagger delay reduced 5.0s → 0.5s, all multi-participant tests pass

## Previous Milestone: v1.15 E2E Test Reliability (Complete: 2026-02-04)

**Delivered:** Root cause analysis — Pyodide main thread blocking identified as source of Socket.IO disconnects. Fix delivered in v1.16.

## Previous Milestone: v1.14 Data Parity Fix (Shipped: 2026-02-04)

**Delivered:** Fixed data parity divergence bug, added multi-participant test infrastructure, and comprehensive lifecycle stress tests.

**Key accomplishments:**
- Input confirmation protocol before episode export
- Increased P2P input redundancy (3→10 inputs per packet)
- Multi-participant test infrastructure (6 contexts, 3 concurrent games)
- GameOrchestrator class for test orchestration
- Data export parity validation helpers
- Fixed GAME-01 violation (games pre-created in waitroom)
- Fixed PyodideGameCoordinator eventlet deadlock
- 5 lifecycle stress test functions (STRESS-02 through STRESS-07)

**Known limitation:** P2P validation timeouts under concurrent load (deferred to v1.15)

## Previous Milestone: v1.13 Matchmaker Hardening (Shipped: 2026-02-03)

**Delivered:** P2P RTT probing for latency-based match filtering and a single game creation path.

**Key accomplishments:**
- P2P probe infrastructure (ProbeCoordinator, ProbeConnection, ProbeManager)
- RTT ping-pong measurement protocol via WebRTC DataChannel
- Matchmaker RTT integration with configurable max_p2p_rtt_ms threshold
- Removed group reunion flow (~230 lines), single game creation path
- Game only exists when all matched participants are assigned

## Previous Milestone: v1.12 Waiting Room Overhaul (Shipped: 2026-02-03)

**Delivered:** Fixed waiting room bugs and built pluggable Matchmaker abstraction for custom participant pairing logic.

**Key accomplishments:**
- Diagnostic logging and state validation for stale game routing
- Comprehensive cleanup on all exit paths (idempotent)
- Session lifecycle state machine (WAITING → MATCHED → VALIDATING → PLAYING → ENDED)
- Participant state tracker (single source of truth for routing)
- Matchmaker base class with FIFOMatchmaker default
- Match assignment logging (JSONL + admin dashboard)

## Previous Milestone: v1.11 Data Export Edge Cases (Shipped: 2026-02-02)

**Delivered:** Fixed dual-buffer data recording edge cases so all E2E stress tests pass and research data exports are identical between both players.

**Key accomplishments:**
- Fixed isFocused column consistency (both players always export isFocused.0 and isFocused.1)
- Fixed episode boundary row parity (both players export exactly max_steps rows)
- All 17 E2E tests pass with no xfail markers
- Validated data parity under latency (100ms, 200ms), packet loss (15%), and focus loss

## Previous Milestone: v1.10 E2E Test Fix (Shipped: 2026-02-02)

**Delivered:** All E2E tests pass in headed mode with data parity validation under network stress.

**Key accomplishments:**
- Fixed Playwright visibility override (FocusManager was blocking frames when document.hidden=true)
- 15 tests passing (12 passed + 3 xpassed)
- Identified 5 edge cases in dual-buffer data recording (marked xfail for v1.11)
- Focus loss data parity tests in place (reveal edge cases for fixing)

## Previous Milestone: v1.9 Data Parity Testing (Shipped: 2026-02-01)

**Delivered:** Playwright E2E test infrastructure with network condition simulation and data comparison pipeline.

**Key accomplishments:**
- Playwright test fixtures (flask_server, player_contexts)
- CDP-based latency injection tests (100ms, 200ms, jitter)
- Packet loss and tab focus simulation tests
- Export collection and comparison helpers
- Manual test protocol documentation

## Previous Milestone: v1.8 Data Export Parity (Shipped: 2026-01-31)

**Delivered:** Both players export identical game state data regardless of rollbacks, fast-forwards, or latency.

**Key accomplishments:**
- Dual-buffer architecture (speculative → canonical frame data)
- Fast-forward frames properly promoted to canonical buffer
- Episode boundary confirmation ensures complete data export
- `wasSpeculative` per-frame metadata for research analysis
- `rollbackEvents` array in export for rollback history
- Offline `--compare` mode in validation script

## Previous Milestone: v1.7 Admin Console Improvement (Shipped: 2026-01-25)

**Delivered:** A clean, usable admin console that gives researchers effective experiment monitoring — see what's happening, catch problems, track progress.

**Key accomplishments:**
- Dashboard overview with completion rate and average duration stats
- Session list showing state, P2P health indicators, and connection type
- Session detail panel with termination reasons and player health
- Problems indicator for quick access to errors/warnings
- Clean layout with sessions as the primary focus

## Previous Milestone: v1.6 Input Latency Diagnosis (Partial: 2026-01-24)

**Delivered:** Pipeline instrumentation for latency diagnosis. Root cause fix deferred.

**Key accomplishments:**
- Diagnostic instrumentation for input→execute→render pipeline timing
- Latency measurement at each stage (queue time, step time, render time)
- Console logging format for latency breakdown per frame
- Instrumentation in both multiplayer and single-player code paths

**Deferred to future:** Root cause identification and fix for reported 1-2s delay (tooling now exists for diagnosis).

## Previous Milestone: v1.5 Focus Loss Handling (Shipped: 2026-01-23)

**Delivered:** Resilient focus loss handling with Web Worker timing, graceful backgrounded state, and fast-forward resync on refocus.

**Key accomplishments:**
- Web Worker-based timing to maintain clock accuracy when tab is backgrounded
- Page Visibility API detection of focus loss
- Backgrounded player's actions default to idle/no-op
- Partner inputs continue flowing via WebRTC, queued for resync on refocus
- On refocus: fast-forward simulation using queued inputs
- Focused partner experiences no interruption (sees other player go idle)
- Configurable timeout before ending game (default 30s)
- Focus loss events in session metadata for research analysis

## Previous Milestone: v1.4 Partner Disconnection Handling (Shipped: 2026-01-22)

**Delivered:** Improved partner disconnect experience with in-page overlay instead of redirect, data export before termination, and configurable messaging.

**Key accomplishments:**
- No redirect on partner disconnect — stay on same page with overlay
- Clean UI update — hide game container, show disconnection message
- Data export before termination
- Session metadata with disconnection reason and disconnected player ID
- Configurable partner disconnect message via GymScene config

## Previous Milestone: v1.3 P2P Connection Validation (Shipped: 2026-01-22)

**Delivered:** Reliable P2P connections throughout experiments with pre-game validation, per-round health checks, reconnection handling, and comprehensive latency/connection telemetry.

**Key accomplishments:**
- Waiting room P2P validation before experiment starts
- Per-round DataChannel health check
- Mid-game reconnection with gameplay pause and ICE restart
- Connection event logging (disconnections, reconnection attempts, pause durations)
- Async periodic P2P latency monitoring
- Latency stats export (min, median, mean, max)
- Fast connection loss detection (500ms grace period)

## Previous Milestone: v1.2 Participant Exclusion (Shipped: 2026-01-22)

**Delivered:** A configurable, extensible system to exclude participants who don't meet experiment requirements — checked both at entry and continuously during play.

**Key accomplishments:**
- Entry screening with browser/device detection via ua-parser-js
- Continuous monitoring with frame-throttled checking and warning system
- Custom callback support for arbitrary server-side exclusion logic
- Multiplayer exclusion handling (end game for both, distinct partner notification)

## Previous State (v1.0)

**Shipped:** 2026-01-19

**Tech stack:**
- Pyodide runs Python/Gymnasium in browser via WebAssembly
- WebRTC DataChannels provide near-UDP performance between peers
- Flask/SocketIO handles signaling and fallback
- 3,913 LOC in pyodide_multiplayer_game.js
- 759 LOC in webrtc_manager.js

**Architecture:**
- Symmetric peers (no "host" concept)
- Binary P2P protocol with redundant input packets
- TURN server fallback for NAT-blocked connections
- GGPO-style input queuing with synchronous rollback

## Requirements

### Validated

*Existing capabilities:*
- ✓ Scene-based experiment flow (StartScene → GymScene → EndScene) — existing
- ✓ Single-player Pyodide game execution in browser — existing
- ✓ Server-side experiment orchestration via Flask/SocketIO — existing
- ✓ Phaser.js game rendering — existing
- ✓ Data collection and CSV export — existing
- ✓ Lobby/waitroom system for player matching — existing
- ✓ Session persistence and reconnection support — existing
- ✓ Deterministic Gymnasium environments — existing

*Shipped in v1.0:*
- ✓ WebRTC DataChannel P2P connections — v1.0
- ✓ SocketIO signaling for SDP/ICE — v1.0
- ✓ TURN server fallback — v1.0
- ✓ Connection type detection for research analytics — v1.0
- ✓ Symmetric peer architecture (no "host") — v1.0
- ✓ P2P input exchange over DataChannel — v1.0
- ✓ Redundant input sending for packet loss — v1.0
- ✓ 2-player P2P support — v1.0
- ✓ Legacy host-based sync code removed — v1.0
- ✓ GGPO-style synchronous input processing — v1.0

*Shipped in v1.2:*
- ✓ Entry screening with browser/device detection — v1.2
- ✓ Continuous monitoring during experiment — v1.2
- ✓ Custom callback support for exclusion logic — v1.2
- ✓ Multiplayer exclusion handling — v1.2

*Shipped in v1.3:*
- ✓ Waiting room P2P validation before experiment starts — v1.3
- ✓ Failed P2P pairs re-enter matchmaking pool — v1.3
- ✓ Per-round DataChannel health check — v1.3
- ✓ Mid-game reconnection with gameplay pause — v1.3
- ✓ Reconnecting overlay for both clients during reconnection — v1.3
- ✓ Configurable reconnection timeout before ending game — v1.3
- ✓ Connection event logging (disconnections, reconnection attempts, pause durations) — v1.3
- ✓ Async periodic P2P latency monitoring — v1.3
- ✓ Latency stats export (min, median, mean, max) — v1.3

*Shipped in v1.4:*
- ✓ No redirect on partner disconnect (in-page overlay) — v1.4
- ✓ Clean UI update on disconnect (hide game, show message) — v1.4
- ✓ Data export before termination — v1.4
- ✓ Session metadata with disconnection reason and disconnected player ID — v1.4
- ✓ Configurable partner disconnect message via GymScene config — v1.4

### Active

*v1.21 Latency-Aware Matchmaking:*
- [ ] LatencyFIFOMatchmaker class with server RTT pre-filtering in find_match()
- [ ] Configurable max_server_rtt_ms threshold for estimated P2P RTT filtering
- [ ] Integration with existing max_p2p_rtt_ms for post-match P2P probe verification
- [ ] Graceful fallback when server RTT data unavailable

*Shipped in v1.20:*
- ✓ 3-second countdown overlay on waiting room screen after match formed — v1.20
- ✓ "Players found!" message with 3-2-1 countdown visible to all matched players — v1.20
- ✓ Game start remains synced across all players after countdown completes — v1.20

*Shipped in v1.19:*
- ✓ P2P connections closed on GymScene exit — v1.19
- ✓ No partner-disconnected overlay on non-GymScene scenes — v1.19
- ✓ Group membership tracked across scene transitions — v1.19
- ✓ Group history queryable by custom matchmakers — v1.19

*Shipped in v1.18:*
- ✓ Single merged loading screen (compat check + Pyodide) — v1.18
- ✓ Configurable Pyodide loading timeout with error page — v1.18
- ✓ Orphaned test fixtures and duplicate helpers removed — v1.18
- ✓ Roadmap reflects actual v1.14 completion state — v1.18

*Shipped in v1.17:*
- ✓ All E2E tests pass with zero failures (24 tests, 23 pass + 1 xfail) — v1.17
- ✓ Server startup/teardown reliable between test suites — v1.17
- ✓ Test timeouts appropriate for each scenario — v1.17
- ✓ Network disruption tests validated and passing — v1.17

*Shipped in v1.16:*
- ✓ Early Pyodide init during compatibility check — v1.16
- ✓ Shared Pyodide instance reused by game classes — v1.16
- ✓ Loading progress indicator and advancement gate — v1.16
- ✓ Server-side ping grace during Pyodide loading — v1.16
- ✓ Stagger delay reduced to 0.5s, concurrent starts work — v1.16

*Shipped in v1.15:*
- ✓ Root cause identified (Pyodide blocks main thread → Socket.IO disconnect) — v1.15

*Shipped in v1.14:*
- ✓ Wait for input confirmation before episode export — v1.14
- ✓ Ensure both players export identical action sequences — v1.14
- ✓ Multi-participant test infrastructure (6 contexts, 3 concurrent games) — v1.14
- ✓ Data export parity validation helpers — v1.14
- ✓ GameOrchestrator for multi-participant test orchestration — v1.14

*Shipped in v1.13:*
- ✓ P2P RTT probe helper for measuring actual latency between candidates — v1.13
- ✓ WebRTC probe connection during matchmaking consideration — v1.13
- ✓ Configurable max_p2p_rtt_ms threshold for match decisions — v1.13
- ✓ Single game creation path (matchmaker → match → game) — v1.13
- ✓ Remove group reunion flow (documented as future matchmaker variant) — v1.13

*Shipped in v1.12:*
- ✓ Diagnostic logging for stale game routing — v1.12
- ✓ State validation before GameManager routing — v1.12
- ✓ Idempotent cleanup on all exit paths — v1.12
- ✓ Session lifecycle state machine — v1.12
- ✓ Participant state tracker — v1.12
- ✓ Matchmaker base class with FIFOMatchmaker — v1.12
- ✓ Match assignment logging (JSONL + admin) — v1.12

*Shipped in v1.11:*
- ✓ isFocused column consistency (both players export isFocused.0/isFocused.1) — v1.11
- ✓ Episode boundary row parity (both players export exactly max_steps rows) — v1.11
- ✓ Dual-buffer stress handling (all stress tests pass without xfail) — v1.11
- ✓ Research data exports identical between both players — v1.11

*Shipped in v1.8:*
- ✓ Identical frame counts between both players' exports — v1.8
- ✓ Identical actions recorded per frame across both players — v1.8
- ✓ Identical rewards and infos per frame — v1.8
- ✓ Correct data collection during/after rollbacks — v1.8
- ✓ Correct data collection during/after fast-forward — v1.8
- ✓ Correct data collection under high latency — v1.8
- ✓ `wasSpeculative` per-frame metadata — v1.8
- ✓ `rollbackEvents` in export — v1.8
- ✓ Offline `--compare` validation mode — v1.8

*Shipped in v1.7:*
- ✓ Dashboard overview with key experiment stats — v1.7
- ✓ Session list with state and P2P health indicators — v1.7
- ✓ Live session state visibility — v1.7
- ✓ P2P/connection metrics surfaced in UI — v1.7
- ✓ Error and exclusion details visible — v1.7
- ✓ Clean, prioritized layout — v1.7

*Shipped in v1.6 (partial):*
- ✓ Diagnostic instrumentation for input→execute→render pipeline — v1.6
- ✓ Latency measurement at each pipeline stage — v1.6
- ✓ Console logging for latency breakdown — v1.6

*Shipped in v1.5:*
- ✓ Web Worker-based timing for background tab resilience — v1.5
- ✓ Page Visibility API focus loss detection — v1.5
- ✓ Backgrounded player actions default to idle/no-op — v1.5
- ✓ Partner input queuing and resync on refocus — v1.5
- ✓ Configurable focus loss timeout (default 30s) — v1.5
- ✓ Configurable focus loss timeout message — v1.5
- ✓ Focus loss events in session metadata — v1.5

### Deferred

- [ ] Pyodide Web Worker (move per-frame runPythonAsync off main thread) — pre-loading solves the disconnect issue; Web Worker deferred until per-frame blocking becomes a problem
- [ ] Rollback visual smoothing (tween objects after corrections)
- [ ] N-player support with hybrid topology (mesh for small N, relay for large N)
- [ ] Adaptive input delay based on RTT
- [ ] Input latency root cause fix (v1.6 tooling exists for diagnosis)

### Out of Scope

- ~~Ping-based matchmaking — deferred to future milestone~~ → Delivering in v1.21
- Server-authoritative mode removal — keeping as parallel option
- Mobile/native clients — browser-only for now
- Spectator mode — not needed for research use case

## Context

**Current codebase:**
- P2P multiplayer fully functional for 2-player games
- Tested with SlimeVolleyball and Overcooked environments
- Research metrics export API captures connection type, rollback events, sync status
- v1.3 added latency telemetry and fast disconnect detection (500ms grace)

**Known issues:**
- Episode start sync can timeout on slow connections (mitigated with retry mechanism)
- Rollback visual corrections cause brief teleporting (smoothing not yet implemented)
- **[CRITICAL]** Users report 1-2 second local input lag in Overcooked (investigating in v1.6)
- **[BUG]** Partner disconnected overlay shown on non-GymScene scenes (surveys, instructions) when former partner disconnects. Fixing in v1.19.
- ~~**[RESOLVED]** Double loading spinner on page open — fixed in v1.18 with unified loading gate~~
- **[KNOWN]** GGPO content parity divergence under packet loss + active inputs (~40-50% failure rate). Documented in `.planning/backlog/GGPO-PARITY.md`. xfail marker on `test_active_input_with_packet_loss`.
- ~~**[RESOLVED]** Data parity divergence under packet loss — input confirmation protocol added in v1.14~~
- ~~**[RESOLVED]** Data export parity issues — fixed in v1.8 with dual-buffer architecture~~
- ~~**[RESOLVED]** New participants sometimes routed to stale games — fixed in v1.12 with state validation and comprehensive cleanup~~

## Constraints

- **Tech stack**: Must work with existing Flask/SocketIO/Pyodide stack
- **Browser compatibility**: WebRTC DataChannels must work in modern Chrome/Firefox/Safari
- **Determinism**: Environments must remain fully deterministic for replay to work
- **Research validity**: Data collection must capture actual player inputs and game states accurately

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Native WebRTC API (no wrapper libraries) | Full control, no external dependencies | ✓ Good |
| Deterministic initiator (lower player ID) | Prevents race conditions in role assignment | ✓ Good |
| DataChannel unreliable/unordered | GGPO handles packet loss via prediction and rollback | ✓ Good |
| Binary protocol with redundancy | Compact format, handles up to 2 consecutive packet losses | ✓ Good |
| Symmetric state sync (both peers broadcast) | Mutual verification, no single point of authority | ✓ Good |
| P2P-first with SocketIO fallback | Minimizes server bandwidth when P2P healthy | ✓ Good |
| GGPO-style input queuing | Prevents race conditions during rollback replay | ✓ Good |
| Open Relay Project for TURN | Free 20GB/month tier sufficient for research | ✓ Good |

| Dual-buffer data recording | Separates speculative from confirmed frame data for export parity | ✓ Good |
| Playwright MCP for testing | Browser automation with network condition control | ✓ Good |
| isFocused exclusion from parity | Focus state has notification latency, column consistency is sufficient | ✓ Good |
| BOUND-02/03 guards | Defense-in-depth at episode boundaries in async paths | ✓ Good |
| Pre-load over Web Worker for v1.16 | Per-frame Python (10-100ms) doesn't cause disconnects; only loadPyodide() does. Pre-loading is simpler and preserves synchronous rollback performance. Web Worker deferred. | ✓ Good |

---
*Last updated: 2026-02-07 after v1.21 Latency-Aware Matchmaking milestone started*
