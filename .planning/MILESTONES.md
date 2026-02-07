# Project Milestones: Interactive Gym P2P Multiplayer

## v1.21 Latency-Aware Matchmaking (In Progress)

**Goal:** A FIFO matchmaker that pre-filters candidates by server RTT heuristic before proposing matches, then verifies with P2P probe.

**Status:** Defining requirements

**Target features:**

- LatencyFIFOMatchmaker class with server RTT pre-filtering in find_match()
- Configurable max_server_rtt_ms threshold (estimated P2P RTT = sum of server RTTs)
- Integration with existing max_p2p_rtt_ms for post-match P2P probe verification
- Graceful fallback when server RTT data unavailable

---

## v1.20 Pre-Game Countdown (Shipped: 2026-02-07)

**Delivered:** 3-second "Players found!" countdown on waiting room screen after matchmaking, synced game start.

**Phases completed:** 80 (1 plan)

**Key accomplishments:**

- Server-side `_start_game_with_countdown()` method with background greenlet
- Client-side `match_found_countdown` socket handler with 3-2-1 countdown display
- Single-player guard skips countdown for non-multiplayer games
- Uses `sio.start_background_task()` to avoid holding `waiting_games_lock` during 3s sleep

---

## v1.19 P2P Lifecycle Cleanup (Shipped: 2026-02-07)

**Delivered:** P2P connections scoped to GymScenes — torn down on scene exit, with group history preserved for future re-pairing.

**Phases completed:** 77-79 (3 plans total)

**Key accomplishments:**

- Client-side P2P connection scoping via cleanupForSceneExit() + sceneExited guards
- GroupReunionMatchmaker for re-pairing previous partners
- E2E scene isolation test validates no stale overlays on post-game scenes

---

## v1.18 Loading UX & Cleanup (Shipped: 2026-02-07)

**Delivered:** Single merged loading screen gating on both compatibility check and Pyodide readiness. Configurable timeout with error page. Cleaned up orphaned test fixtures and duplicate helpers.

**Phases completed:** 75-76 (3 plans total)

**Key accomplishments:**

- Unified loading screen replacing separate screening + Pyodide loaders
- Loading gate requires both compatibility check AND Pyodide before advancing
- Configurable pyodide_load_timeout_s (default 60s) with clear error page on failure
- Full-page loading overlay visible from initial page load
- Removed orphaned flask_server_multi_episode fixture
- Consolidated duplicate run_full_episode_flow into single game_helpers.py source

---

## v1.17 E2E Test Reliability (Shipped: 2026-02-06)

**Delivered:** 100% E2E test pass rate — 24 tests across 8 modules, zero failures. Robust server fixture lifecycle, P2P timeout tuning, GGPO fixes.

**Phases completed:** 71-74 (8 plans total)

**Key accomplishments:**

- Robust server fixture lifecycle with port-verified teardown (shared helpers)
- P2P ready gate timeout fix (5000ms → 15000ms) for 200ms latency tests
- All 24 E2E tests pass (23 passed + 1 xfail for GGPO architectural limitation)
- Two GGPO fixes: prune guard + episode boundary ordering
- GGPO content parity limitation documented in .planning/backlog/GGPO-PARITY.md

---

## v1.16 Pyodide Pre-loading (Shipped: 2026-02-06)

**Delivered:** Pyodide pre-loading during compat check, shared instance reuse, server-side grace period, concurrent game starts with 0.5s stagger.

**Phases completed:** 67-70 (4 phases)

**Key accomplishments:**

- Server-side Pyodide config detection via get_pyodide_config()
- Client preloadPyodide() during compatibility check with progress UI and advancement gating
- RemoteGame.initialize() reuses pre-loaded Pyodide instance (package dedup)
- MultiplayerPyodideGame inherits via super.initialize()
- Server LOADING_CLIENTS grace period (ping_timeout=30, 60s safety timeout)
- Client pyodide_loading_start/complete signals with 50ms yield before blocking
- Stagger delay reduced from 5.0s to 0.5s across all E2E tests
- 14/14 requirements satisfied, 3/3 E2E flows verified

---

## v1.15 E2E Test Reliability (Complete: 2026-02-04)

**Delivered:** Root cause analysis of multi-participant test failures. Identified Pyodide main thread blocking as the source of Socket.IO disconnects.

**Key findings:**

- Pyodide initialization blocks browser main thread during WASM compilation
- Socket.IO ping timeout (8s) exceeded when multiple games start concurrently
- 5-second stagger delay workaround allows sequential Pyodide init
- Permanent fix requires Web Worker architecture (deferred to v1.16)

---

## v1.14 Data Parity Fix (Shipped: 2026-02-04)

**Delivered:** Fixed data parity divergence bug, added multi-participant test infrastructure, and comprehensive lifecycle stress tests.

**Phases completed:** 61-65 (5 phases)

**Key accomplishments:**

- Input confirmation protocol before episode export
- Increased P2P input redundancy (3→10 inputs per packet)
- Multi-participant test infrastructure (6 contexts, 3 concurrent games)
- GameOrchestrator class for test orchestration
- Data export parity validation helpers
- Fixed GAME-01 violation (games pre-created in waitroom)
- Fixed PyodideGameCoordinator eventlet deadlock
- 5 lifecycle stress test functions (STRESS-02 through STRESS-07)

---

## v1.13 Matchmaker Hardening (Shipped: 2026-02-03)

**Delivered:** P2P RTT probing for latency-based match filtering and a single game creation path.

**Phases completed:** 57-60 (4 phases)

**Key accomplishments:**

- P2P probe infrastructure (ProbeCoordinator, ProbeConnection, ProbeManager)
- RTT ping-pong measurement protocol via WebRTC DataChannel
- Matchmaker RTT integration with configurable max_p2p_rtt_ms threshold
- Removed group reunion flow (~230 lines), single game creation path
- Game only exists when all matched participants are assigned

---

## v1.12 Waiting Room Overhaul (Shipped: 2026-02-03)

**Delivered:** Fixed waiting room bugs and built pluggable Matchmaker abstraction for custom participant pairing logic.

**Phases completed:** 51-56 (6 phases)

**Key accomplishments:**

- Diagnostic logging and state validation for stale game routing
- Comprehensive cleanup on all exit paths (idempotent)
- Session lifecycle state machine (WAITING → MATCHED → VALIDATING → PLAYING → ENDED)
- Participant state tracker (single source of truth for routing)
- Matchmaker base class with FIFOMatchmaker default
- Match assignment logging (JSONL + admin dashboard)

---

## v1.11 Data Export Edge Cases (Shipped: 2026-02-02)

**Delivered:** Fixed dual-buffer data recording edge cases so all E2E stress tests pass and research data exports are identical between both players.

**Phases completed:** 48-50 (3 plans total)

**Key accomplishments:**

- Fixed isFocused column consistency — both players always export isFocused.0 and isFocused.1 columns
- Fixed episode boundary row parity — fast-forward respects syncedTerminationFrame, both players export exactly max_steps rows
- All 17 E2E stress tests pass with no xfail markers
- Validated data parity under network latency (100ms, 200ms), packet loss (15%), and focus loss (mid-episode and boundary)

**Stats:**

- 17 files created/modified
- +1,527/-92 lines
- 3 phases, 3 plans
- 1 day (2026-02-02)

**Git range:** `fix(48-01)` → `docs(50)` (11 commits)

**What's next:** Production-ready data export parity. Consider v2.0 features (CI/CD integration, headless mode).

---

## v1.10 E2E Test Fix (Shipped: 2026-02-02)

**Delivered:** All E2E tests pass in headed mode with data parity validation under network stress conditions.

**Phases completed:** 45-47 (3 plans total)

**Key accomplishments:**

- Fixed Playwright visibility override (FocusManager was blocking frames when document.hidden=true)
- 15 tests passing (12 passed + 3 xpassed)
- Identified 5 edge cases in dual-buffer data recording (fixed in v1.11)
- Focus loss data parity tests in place

---

## v1.9 Data Parity Testing (Shipped: 2026-02-01)

**Delivered:** Playwright E2E test infrastructure with network condition simulation and data comparison pipeline.

**Phases completed:** 40-44 (6 plans total)

**Key accomplishments:**

- Playwright test fixtures (flask_server, player_contexts)
- CDP-based latency injection tests (100ms, 200ms, jitter)
- Packet loss and tab focus simulation tests
- Export collection and comparison helpers
- Manual test protocol documentation

---

## v1.8 Data Export Parity (Shipped: 2026-01-30)

**Delivered:** Both players export identical game state data regardless of rollbacks, fast-forwards, or latency.

**Phases completed:** 36-39 (4 plans total)

**Key accomplishments:**

- Dual-buffer architecture (speculative → canonical frame data)
- Fast-forward frames properly promoted to canonical buffer
- Episode boundary confirmation ensures complete data export
- wasSpeculative per-frame metadata and rollbackEvents array in export

---

## v1.7 Admin Console Improvement (Shipped: 2026-01-25)

**Delivered:** A clean, usable admin console for effective experiment monitoring.

**Phases completed:** 32-35 (4 plans total)

---

## v1.6 Input Latency Diagnosis (Partial: 2026-01-24)

**Delivered:** Pipeline instrumentation for latency diagnosis. Root cause fix deferred.

**Phases completed:** 28 (1 plan)

---

## v1.5 Focus Loss Handling (Shipped: 2026-01-23)

**Delivered:** Resilient focus loss handling with Web Worker timing and fast-forward resync.

**Phases completed:** 24-27 (4 plans total)

---

## v1.4 Partner Disconnection Handling (Shipped: 2026-01-22)

**Delivered:** Improved partner disconnect experience with in-page overlay.

**Phases completed:** 23 (1 plan)

---

## v1.3 P2P Connection Validation (Shipped: 2026-01-22)

**Delivered:** Reliable P2P connections with pre-game validation and reconnection handling.

**Phases completed:** 19-22 (5 plans total)

---

## v1.2 Participant Exclusion (Shipped: 2026-01-22)

**Delivered:** Configurable participant exclusion system.

**Phases completed:** 15-18 (4 plans total)

---

## v1.1 Sync Validation (Shipped: 2026-01-21)

**Delivered:** Validation system for action sequences and state hashes.

**Phases completed:** 11-14 (4 plans total)

---

## v1.0 P2P Multiplayer (Shipped: 2026-01-19)

**Delivered:** True peer-to-peer multiplayer with GGPO-style rollback netcode, replacing the pseudo-P2P "host client" architecture to achieve fighting-game-smooth responsiveness for research experiments.

**Phases completed:** 1-6 (11 plans total)

**Key accomplishments:**

- WebRTC DataChannel P2P connections with server-mediated SDP/ICE signaling
- Binary P2P protocol with redundant input sending (3 inputs per packet) for packet loss recovery
- Symmetric peer architecture — both peers run identical simulations with mutual state verification
- TURN server fallback via Open Relay Project when direct P2P fails
- GGPO-style synchronous input processing with batched rollback replay
- Research metrics export API for connection type, rollback events, and sync status

**Stats:**

- 12 files created/modified
- +2,454 net lines of JavaScript
- 6 phases, 11 plans
- 4 days from start to ship (2026-01-16 → 2026-01-19)

**Git range:** `feat(01-01)` → `feat(06-01)` (76 commits)

**What's next:** TBD — rollback visual smoothing, additional environment support

---
