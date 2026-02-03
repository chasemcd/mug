# Interactive Gym — P2P Multiplayer

## What This Is

A framework for running browser-based reinforcement learning experiments with human participants. The P2P multiplayer system implements true peer-to-peer connections with GGPO-style rollback netcode, enabling fighting-game-smooth responsiveness for research experiments where both players experience local-feeling input response regardless of network latency.

## Core Value

Both players in a multiplayer game experience local-feeling responsiveness regardless of network latency, enabling valid research data collection without latency-induced behavioral artifacts.

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

(Planning next milestone)

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

- [ ] Rollback visual smoothing (tween objects after corrections)
- [ ] N-player support with hybrid topology (mesh for small N, relay for large N)
- [ ] Adaptive input delay based on RTT
- [ ] Input latency root cause fix (v1.6 tooling exists for diagnosis)

### Out of Scope

- Ping-based matchmaking — deferred to future milestone
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
- ~~**[RESOLVED]** Data export parity issues — fixed in v1.8 with dual-buffer architecture~~

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

---
*Last updated: 2026-02-02 after v1.11 milestone complete*
