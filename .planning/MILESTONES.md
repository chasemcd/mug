# Project Milestones: Interactive Gym P2P Multiplayer

## v1.16 Pyodide Pre-loading (In Progress)

**Goal:** Pre-load Pyodide during the compatibility check screen so game startup never blocks the main thread, eliminating Socket.IO disconnects at scale (50+ concurrent game pairs).

**Status:** Planning

**Approach:** Move Pyodide loading to the compatibility check screen (before matching). By the time a game starts, Pyodide is already compiled — game startup is instant and non-blocking. This is simpler than the originally planned Web Worker approach and preserves the synchronous rollback path.

**Target features:**

- Early Pyodide init during compatibility check (detect Pyodide scenes from config)
- Shared Pyodide instance reused by RemoteGame (skip loadPyodide if pre-loaded)
- Loading progress indicator and gate before participant advancement
- Server-side ping grace during Pyodide loading phase
- Remove stagger delay from multi-participant tests

**Key insight:**

- Only `loadPyodide()` causes disconnects (5-15s main thread blocking)
- Per-frame `runPythonAsync()` is fine (10-100ms, well within 8s ping timeout)
- Pre-loading eliminates concurrent init at game start without rewriting the game loop
- Web Worker for per-frame execution deferred to future milestone

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
