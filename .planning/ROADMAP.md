# Roadmap: Interactive Gym P2P Multiplayer

## Milestones

- ✅ **v1.0 P2P Multiplayer** - Phases 1-10 (shipped 2026-01-19)
- ✅ **v1.1 Sync Validation** - Phases 11-14 (shipped 2026-01-21)
- ✅ **v1.2 Participant Exclusion** - Phases 15-18 (shipped 2026-01-22)
- ✅ **v1.3 P2P Connection Validation** - Phases 19-22 (shipped 2026-01-22)
- ✅ **v1.4 Partner Disconnection Handling** - Phase 23 (shipped 2026-01-22)
- ✅ **v1.5 Focus Loss Handling** - Phases 24-27 (shipped 2026-01-23)
- ⚠️ **v1.6 Input Latency Diagnosis** - Phases 28-31 (partial: 2026-01-24)
- ✅ **v1.7 Admin Console Improvement** - Phases 32-35 (shipped 2026-01-25)
- ✅ **v1.8 Data Export Parity** - Phases 36-39 (shipped 2026-01-30)
- ✅ **v1.9 Data Parity Testing** - Phases 40-44 (shipped 2026-02-01)
- ✅ **v1.10 E2E Test Fix** - Phases 45-47 (shipped 2026-02-02)
- ✅ **v1.11 Data Export Edge Cases** - Phases 48-50 (shipped 2026-02-02) → [archive](milestones/v1.11-ROADMAP.md)
- ✅ **v1.12 Waiting Room Overhaul** - Phases 51-56 (shipped 2026-02-03)
- ✅ **v1.13 Matchmaker Hardening** - Phases 57-60 (shipped 2026-02-03)
- ✅ **v1.14 Data Parity Fix** - Phases 61-66 (shipped 2026-02-04)
- ✅ **v1.16 Pyodide Pre-loading** - Phases 67-70 (shipped 2026-02-06)
- ✅ **v1.17 E2E Test Reliability** - Phases 71-74 (shipped 2026-02-06)
- ✅ **v1.18 Loading UX & Cleanup** - Phases 75-76 (shipped 2026-02-07)
- ✅ **v1.19 P2P Lifecycle Cleanup** - Phases 77-79 (shipped 2026-02-07)
- ✅ **v1.20 Pre-Game Countdown** - Phase 80 (shipped 2026-02-07)
- 🚧 **v1.21 Latency-Aware Matchmaking** - Phases 81-82 (in progress)

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

<details>
<summary>v1.0 P2P Multiplayer (Phases 1-10) - SHIPPED 2026-01-19</summary>

See `.planning/archive/v1.0/` for completed phase details.

Key deliverables:
- WebRTC DataChannel P2P connections
- GGPO-style rollback netcode
- Binary P2P protocol with redundancy
- TURN server fallback
- Symmetric peer architecture

</details>

<details>
<summary>v1.1 Sync Validation (Phases 11-14) - COMPLETE</summary>

**Milestone Goal:** Build a validation system that confirms verified action sequences and state hashes are identical across all peers, enabling debugging of non-deterministic environments and networking issues.

- [x] **Phase 11: Hash Infrastructure** - Deterministic state hashing with confirmed frame tracking
- [x] **Phase 12: P2P Hash Exchange** - Binary hash message protocol over DataChannel
- [x] **Phase 13: Mismatch Detection** - Comparison logic, peer buffering, desync logging
- [x] **Phase 14: Validation Export** - Post-game JSON export with frame-by-frame data

</details>

<details>
<summary>v1.2 Participant Exclusion (Phases 15-18) - SHIPPED 2026-01-22</summary>

**Milestone Goal:** A configurable, extensible system to exclude participants who don't meet experiment requirements - checked both at entry and continuously during play.

- [x] **Phase 15: Entry Screening Rules** - Pre-game device/browser/ping checks with exclusion messaging
- [x] **Phase 16: Continuous Monitoring** - Real-time ping and tab visibility monitoring during gameplay
- [x] **Phase 17: Multiplayer Exclusion Handling** - Coordinated game termination when one player excluded
- [x] **Phase 18: Custom Exclusion Callbacks** - Researcher-defined arbitrary exclusion logic

</details>

<details>
<summary>v1.3 P2P Connection Validation (Phases 19-22) - SHIPPED 2026-01-22</summary>

**Milestone Goal:** Ensure reliable P2P connections throughout experiments with pre-game validation, per-round health checks, reconnection handling, and comprehensive latency/connection telemetry.

- [x] **Phase 19: Waiting Room Validation** - P2P connection validation before experiment starts
- [x] **Phase 20: Mid-Game Reconnection** - Detect drops, pause gameplay, reconnection overlay, configurable timeout
- [x] **Phase 21: Per-Round Health Check** - DataChannel verification before each round begins
- [x] **Phase 22: Latency Telemetry** - Async latency monitoring and stats export

</details>

<details>
<summary>v1.4 Partner Disconnection Handling (Phase 23) - SHIPPED 2026-01-22</summary>

**Milestone Goal:** Improve the experience when a partner disconnects mid-game — stay on the same page with a configurable message, ensure data is exported with disconnection metadata.

- [x] **Phase 23: Partner Disconnection Handling** - In-page overlay, data export, disconnection metadata

</details>

<details>
<summary>v1.5 Focus Loss Handling (Phases 24-27) - SHIPPED 2026-01-23</summary>

**Milestone Goal:** Prevent desync when a participant tabs away by using Web Workers for timing and gracefully handling the backgrounded state.

- [x] **Phase 24: Web Worker Timer Infrastructure** - Throttle-resistant timing in Web Worker
- [x] **Phase 25: Focus Detection & Background State** - Page Visibility API, idle defaults, input buffering
- [x] **Phase 26: Resync & Partner Experience** - Fast-forward on refocus, no partner interruption
- [x] **Phase 27: Timeout, Messaging & Telemetry** - Configurable timeout, messages, research data

</details>

<details>
<summary>v1.6 Input Latency Diagnosis (Phases 28-31) - PARTIAL 2026-01-24</summary>

**Milestone Goal:** Diagnose reported 1-2 second local input lag with tooling to measure input→execute→render latency at each pipeline stage.

**Delivered:** Pipeline instrumentation. Root cause fix deferred to future milestone.

- [x] **Phase 28: Pipeline Instrumentation** - Timestamp capture at each pipeline stage
- [ ] **Phase 29: Root Cause Diagnosis** - Deferred
- [ ] **Phase 30: Latency Fix** - Deferred
- [ ] **Phase 31: Telemetry Export** - Deferred

</details>

<details>
<summary>v1.7 Admin Console Improvement (Phases 32-35) - SHIPPED 2026-01-25</summary>

**Milestone Goal:** A clean, usable admin console that gives researchers effective experiment monitoring — see what's happening, catch problems, track progress.

- [x] **Phase 32: Dashboard Summary Stats** - Key experiment metrics at a glance
- [x] **Phase 33: Session List with P2P Health** - Session status and problem flagging
- [x] **Phase 34: Session Detail View** - Detailed diagnostic info on click
- [x] **Phase 35: Layout & Polish** - Clean visual hierarchy and prioritization

</details>

<details>
<summary>v1.8 Data Export Parity (Phases 36-39) - SHIPPED 2026-01-30</summary>

**Milestone Goal:** Both players export identical game state data (actions, observations, rewards, infos) regardless of rollbacks, fast-forwards, or latency — ensuring research data validity.

- [x] **Phase 36: Speculative/Canonical Buffer Split** - Core data recording architecture fix
- [x] **Phase 37: Fast-Forward Data Recording Fix** - Tab refocus confirmation-gated recording
- [x] **Phase 38: Episode Boundary Confirmation** - Ensure all frames confirmed before export
- [x] **Phase 39: Verification & Metadata** - Per-frame metadata and validation tooling

</details>

<details>
<summary>v1.9 Data Parity Testing (Phases 40-44) - SHIPPED 2026-02-01</summary>

**Milestone Goal:** Validate v1.8 data export parity under controlled network conditions using Playwright automation against `overcooked_human_human_multiplayer`.

- [x] **Phase 40: Test Infrastructure Foundation** - Playwright fixtures, server lifecycle
- [x] **Phase 41: Latency Injection Tests** - CDP-based latency (100ms, 200ms, jitter)
- [x] **Phase 42: Network Disruption Tests** - Packet loss, tab focus simulation
- [x] **Phase 43: Data Comparison Pipeline** - Export collection and validation
- [x] **Phase 44: Manual Test Protocol** - Documentation for manual verification

</details>

<details>
<summary>v1.10 E2E Test Fix (Phases 45-47) - SHIPPED 2026-02-02</summary>

**Milestone Goal:** Fix E2E test environment so all automated tests pass in headed mode, validating data parity under network stress conditions.

- [x] **Phase 45: Episode Completion Diagnosis & Fix** - Visibility override for Playwright
- [x] **Phase 46: Test Suite Verification** - All test suites passing
- [x] **Phase 47: Focus Loss Data Accuracy Testing** - Focus loss parity tests

</details>

<details>
<summary>v1.11 Data Export Edge Cases (Phases 48-50) - SHIPPED 2026-02-02</summary>

**Milestone Goal:** Fix dual-buffer data recording edge cases so all xfail tests pass and research data exports are identical between both players.

- [x] **Phase 48: isFocused Column Consistency** - Both players export isFocused.0/isFocused.1
- [x] **Phase 49: Episode Boundary Row Parity** - Both players export exactly max_steps rows
- [x] **Phase 50: Stress Test Verification** - All 17 E2E tests pass

See [milestones/v1.11-ROADMAP.md](milestones/v1.11-ROADMAP.md) for full details.

</details>

<details>
<summary>v1.12 Waiting Room Overhaul (Phases 51-56) - SHIPPED 2026-02-03</summary>

**Milestone Goal:** Fix waiting room bugs and build a pluggable Matchmaker abstraction for custom participant pairing logic.

- [x] **Phase 51: Diagnostic Logging & State Validation** - Logging and state validation
- [x] **Phase 52: Comprehensive Cleanup** - Idempotent cleanup on all exit paths
- [x] **Phase 53: Session Lifecycle** - Session state machine (WAITING → MATCHED → VALIDATING → PLAYING → ENDED)
- [x] **Phase 54: ParticipantStateTracker** - Single source of truth for participant state
- [x] **Phase 55: Matchmaker Base Class** - FIFOMatchmaker with pluggable API
- [x] **Phase 56: Custom Attributes & Assignment Logging** - JSONL logging, RTT exposure

</details>

<details>
<summary>v1.13 Matchmaker Hardening (Phases 57-60) - SHIPPED 2026-02-03</summary>

**Milestone Goal:** Make matchmaking safer and smarter with P2P RTT probing and a single game creation path.

- [x] **Phase 57: P2P Probe Infrastructure** - ProbeCoordinator, ProbeConnection, ProbeManager
- [x] **Phase 58: RTT Measurement** - Ping-pong protocol over DataChannel
- [x] **Phase 59: Matchmaker RTT Integration** - max_p2p_rtt_ms threshold, rejection handling
- [x] **Phase 60: Single Game Creation Path** - Remove group reunion, single entry point

</details>

<details>
<summary>v1.14 Data Parity Fix (Phases 61-66) - SHIPPED 2026-02-04</summary>

**Milestone Goal:** Fix the rare data parity divergence bug and add comprehensive multi-participant E2E stress tests. Data parity must be EXACT — both players export identical data for every frame under all network conditions.

- [x] **Phase 61: Input Confirmation Protocol** - Wait for partner input confirmation before export
- [x] **Phase 62: Data Parity Validation** - Ensure identical exports for actions/rewards/infos
- [x] **Phase 63: Parity Test Stabilization** - E2E tests pass consistently (10+ runs)
- [x] **Phase 64: Multi-Participant Test Infrastructure** - Support 6 concurrent participants
- [x] **Phase 65: Multi-Episode and Lifecycle Stress Tests** - Comprehensive lifecycle coverage
- [x] **Phase 66: Server Recovery Validation** - Prove server recovers from chaos correctly

</details>

### v1.16 Pyodide Pre-loading (Shipped 2026-02-06)

**Milestone Goal:** Pre-load Pyodide during the compatibility check screen so game startup never blocks the main thread, eliminating Socket.IO disconnects at scale (50+ concurrent game pairs).

- [x] **Phase 67: Pyodide Pre-load Infrastructure** - Detect Pyodide scenes, load during compat check, progress UI, advancement gate
- [x] **Phase 68: Shared Instance Integration** - Game classes reuse pre-loaded Pyodide instance
- [x] **Phase 69: Server-Side Init Grace** - Server tolerates missed pings during Pyodide loading
- [x] **Phase 70: Validation & Test Stabilization** - Remove stagger, prove concurrent starts work

<details>
<summary>v1.17 E2E Test Reliability (Phases 71-74) - SHIPPED 2026-02-06</summary>

**Milestone Goal:** Achieve 100% pass rate for all E2E tests with zero flakiness -- every test passes 10+ consecutive runs.

- [x] **Phase 71: Test Infrastructure Fix** - Reliable server lifecycle and navigation between test suites
- [x] **Phase 72: Latency Test Diagnosis** - Root cause and fix for 200ms latency test timeout
- [x] **Phase 73: Network & Regression Validation** - All test suites pass (network disruption, data comparison, multiplayer, multi-participant, focus loss)
- [x] **Phase 74: Stability Certification** - Full suite stable, GGPO parity limitation documented

</details>

<details>
<summary>v1.18 Loading UX & Cleanup (Phases 75-76) - SHIPPED 2026-02-07</summary>

**Milestone Goal:** Fix the double-loading screen UX and clean up accumulated tech debt from rapid milestone delivery.

- [x] **Phase 75: Merged Loading Screen** - Single loading screen gating on both compat check and Pyodide readiness
- [x] **Phase 76: Test & Roadmap Cleanup** - Remove orphaned fixtures, consolidate helpers, update roadmap

</details>

<details>
<summary>v1.19 P2P Lifecycle Cleanup (Phases 77-79) - SHIPPED 2026-02-07</summary>

**Milestone Goal:** P2P connections are scoped to GymScenes — torn down on scene exit, with group history preserved for future re-pairing.

- [x] **Phase 77: P2P Connection Scoping** - Close P2P/WebRTC on GymScene exit, suppress partner-disconnected overlay on non-game scenes
- [x] **Phase 78: Group History Tracking** - Server tracks group membership across scenes, matchmakers can query for re-pairing
- [x] **Phase 79: Post-Game Scene Isolation Test** - E2E test: two players complete Overcooked, proceed to survey, one exits; remaining player stays on survey without partner-disconnected overlay

</details>

### v1.20 Pre-Game Countdown (Shipped 2026-02-07)

**Milestone Goal:** After matchmaking, show a brief countdown on the waiting room screen before transitioning to the gym scene, so players know a match was found and can prepare.

- [x] **Phase 80: Pre-Game Countdown** - 3-second "Players found! 3... 2... 1..." countdown on waiting room after match, synced game start

### 🚧 v1.21 Latency-Aware Matchmaking (In Progress)

**Milestone Goal:** A FIFO matchmaker that pre-filters candidates by server RTT heuristic before proposing matches, then verifies with P2P probe — so only low-latency pairs get matched.

- [x] **Phase 81: LatencyFIFOMatchmaker Core** - Server RTT pre-filtering with configurable threshold and graceful fallback
- [ ] **Phase 82: Scene API & P2P Probe Integration** - Wire into scene.matchmaking(), verify P2P probe coordination

## Phase Details

### Phase 61: Input Confirmation Protocol
**Goal**: Implement protocol to wait for partner input confirmation before episode export
**Depends on**: Phase 60 (v1.13 complete)
**Requirements**: PARITY-01, PARITY-02
**Success Criteria** (what must be TRUE):
  1. Episode export does not begin until partner inputs are confirmed for final frame
  2. Confirmation timeout is configurable (default handles 200ms+ latency)
  3. Timeout triggers graceful handling (not crash or data loss)
**Research flag:** Complete (61-RESEARCH.md)
**Plans:** 1 plan

Plans:
- [x] 61-01-PLAN.md — Add confirmation timeout config and wait logic before episode export

### Phase 62: Data Parity Validation
**Goal**: Ensure both players export identical data for every frame
**Depends on**: Phase 61
**Requirements**: PARITY-03, PARITY-04, PARITY-05
**Success Criteria** (what must be TRUE):
  1. Both players' exports contain identical action columns for every frame
  2. Both players' exports contain identical reward columns for every frame
  3. Both players' exports contain identical info columns for every frame
**Research flag:** Unlikely (verification of Phase 61 fix)
**Plans:** 1 plan

Plans:
- [x] 62-01-PLAN.md — Run parity tests to validate Phase 61 fix

### Phase 63: Parity Test Stabilization
**Goal**: E2E parity tests pass consistently with no tolerance or xfail markers
**Depends on**: Phase 62
**Requirements**: PARITY-06, PARITY-07
**Success Criteria** (what must be TRUE):
  1. `test_active_input_with_latency[chromium-100]` passes 10 consecutive runs
  2. `test_active_input_with_packet_loss` passes 10 consecutive runs
  3. No tolerance or xfail markers needed for parity tests
**Research flag:** Complete (63-RESEARCH.md)
**Plans:** 1 plan

Plans:
- [x] 63-01-PLAN.md — Increase timeout, clean up test docstrings, increase redundancy, verify 10 consecutive passes

### Phase 64: Multi-Participant Test Infrastructure
**Goal**: Build test infrastructure supporting 6 concurrent participants (3 simultaneous games)
**Depends on**: Phase 63
**Requirements**: STRESS-01
**Success Criteria** (what must be TRUE):
  1. Test fixture can launch 6 browser contexts simultaneously
  2. Test fixture can orchestrate 3 concurrent games
  3. Infrastructure handles staggered participant arrival
**Research flag:** Complete (64-RESEARCH.md)
**Plans:** 1 plan

Plans:
- [x] 64-01-PLAN.md — Add multi_participant_contexts fixture, GameOrchestrator class, and validation tests

### Phase 65: Multi-Episode and Lifecycle Stress Tests
**Goal**: Comprehensive stress test coverage for all participant lifecycle scenarios
**Depends on**: Phase 64
**Requirements**: STRESS-02, STRESS-03, STRESS-04, STRESS-05, STRESS-06, STRESS-07
**Success Criteria** (what must be TRUE):
  1. Participant can complete 2+ episodes back-to-back without state corruption
  2. Mid-game disconnect test passes (partner sees message, data exported)
  3. Waiting room disconnect test passes (other participants not affected)
  4. Focus loss test passes (game ends gracefully after timeout)
  5. Mixed lifecycle test passes (combinations of above scenarios)
  6. All completed games pass exact parity validation
**Research flag:** Complete (65-RESEARCH.md)
**Plans:** 2 plans

Plans:
- [x] 65-01-PLAN.md — Create test server configs (multi-episode + focus-timeout) and pytest fixtures
- [x] 65-02-PLAN.md — Create lifecycle stress tests (STRESS-02 through STRESS-07)

### Phase 66: Server Recovery Validation
**Goal**: Prove server handles chaos gracefully and recovers correctly for new participants
**Depends on**: Phase 65
**Requirements**: RECOVERY-01, RECOVERY-02, RECOVERY-03, RECOVERY-04, RECOVERY-05, RECOVERY-06
**Success Criteria** (what must be TRUE):
  1. After concurrent completions, disconnections, and focus loss events, server state is clean
  2. New participant pair entering after chaos completes experiment successfully
  3. New pair's exported data passes exact parity validation
  4. No stale state affects new participants
**Research flag:** Unlikely (integration test of previous phases)
**Plans:** 1 plan

Plans:
- [x] 66-01-PLAN.md — Server recovery validation after chaos scenarios

### Phase 67: Pyodide Pre-load Infrastructure
**Goal**: Build the pre-loading mechanism that initializes Pyodide during the compatibility check screen
**Depends on**: Phase 66 (v1.14 complete)
**Requirements**: INIT-01, INIT-02, INIT-03, INIT-04
**Success Criteria** (what must be TRUE):
  1. System detects Pyodide-requiring scenes from experiment config before matching
  2. Pyodide loads during compatibility check screen (not during game start)
  3. Participant sees progress indicator during Pyodide initialization
  4. Participant cannot proceed until Pyodide is ready
**Research flag:** Complete (67-RESEARCH.md)
**Plans:** 1 plan

Plans:
- [x] 67-01-PLAN.md — Server-side Pyodide config detection + client-side preload with progress UI and advancement gating

### Phase 68: Shared Instance Integration
**Goal**: Game classes reuse pre-loaded Pyodide instance instead of loading their own
**Depends on**: Phase 67
**Requirements**: SHARED-01, SHARED-02
**Success Criteria** (what must be TRUE):
  1. RemoteGame.initialize() skips loadPyodide() when Pyodide is pre-loaded
  2. MultiplayerPyodideGame skips loadPyodide() when Pyodide is pre-loaded
  3. Game startup time is near-instant (no WASM compilation at game time)
**Research flag:** Unlikely — straightforward refactoring to check for existing Pyodide instance
**Plans:** 1 plan

Plans:
- [x] 68-01-PLAN.md — Modify RemoteGame.initialize() to reuse pre-loaded Pyodide and add multiplayer observability logging

### Phase 69: Server-Side Init Grace
**Goal**: Server tolerates missed pings during Pyodide loading so no false disconnects
**Depends on**: Phase 68
**Requirements**: GRACE-01, GRACE-02, GRACE-03
**Success Criteria** (what must be TRUE):
  1. Server does not disconnect clients during Pyodide loading phase
  2. Client signals loading state to server
  3. Normal ping checking resumes after loading completes
**Research flag:** Complete (69-RESEARCH.md)
**Plans:** 1 plan (complete)

Plans:
- [x] 69-01-PLAN.md — Increase ping_timeout, add LOADING_CLIENTS tracking, client loading signals, disconnect handler grace check

### Phase 70: Validation & Test Stabilization
**Goal**: Prove concurrent game starts work without stagger delays
**Depends on**: Phase 69
**Requirements**: TEST-01, TEST-02, TEST-03, TEST-04, TEST-05
**Success Criteria** (what must be TRUE):
  1. Stagger delay removed from multi-participant tests
  2. All E2E tests pass with near-simultaneous game starts (0.5s stagger)
  3. Socket.IO connections remain stable during concurrent starts
  4. No performance regression for game loop execution
  5. All existing E2E pass (no regressions)
**Research flag:** Unlikely — integration test of previous phases
**Plans:** 1 plan

Plans:
- [x] 70-01-PLAN.md — Reduce stagger delay from 5.0s to 0.5s and verify full E2E test suite passes

### Phase 71: Test Infrastructure Fix
**Goal**: Server startup and teardown between test suites completes cleanly, eliminating Page.goto timeout failures
**Depends on**: Phase 70 (v1.16 complete)
**Requirements**: INFRA-01, INFRA-02, INFRA-03
**Success Criteria** (what must be TRUE):
  1. Running two test suites back-to-back (e.g., test_data_comparison then test_focus_loss) succeeds with no Page.goto timeouts
  2. No stale server processes remain after a test suite completes (verified by port check)
  3. Browser contexts, server processes, and temporary files are fully cleaned up between tests
  4. `test_focus_loss_episode_boundary_parity` passes when run after other test suites (not just in isolation)
**Research flag:** Complete (71-RESEARCH.md)
**Plans:** 2 plans

Plans:
- [x] 71-01-PLAN.md — Robust server teardown with port-availability polling, process group kill, and pre-startup cleanup
- [x] 71-02-PLAN.md — Move test_focus_loss_episode_boundary_parity to own module (gap closure for server state exhaustion)

### Phase 72: Latency Test Diagnosis
**Goal**: Identify and fix the root cause of the 200ms latency test timeout so it completes reliably
**Depends on**: Phase 71
**Requirements**: PERF-01, PERF-02
**Success Criteria** (what must be TRUE):
  1. Root cause of `test_episode_completion_under_fixed_latency[chromium-200]` timeout is documented (in plan or summary)
  2. The 200ms latency test completes within its timeout (currently 300s) on 5 consecutive runs
  3. The 100ms latency variant continues to pass (no regression)
**Research flag:** Definite -- root cause is unknown, need investigation before any fix
**Plans:** 2 plans

Plans:
- [x] 72-01-PLAN.md — Instrument test with timing diagnostics and console capture to identify stall point and root cause
- [x] 72-02-PLAN.md — Apply root cause fix and verify 5 consecutive passes with no 100ms regression

### Phase 73: Network & Regression Validation
**Goal**: Every test suite in the E2E suite passes -- network disruption, data comparison, multiplayer, multi-participant, and focus loss
**Depends on**: Phase 72
**Requirements**: NET-01, NET-02, REG-01, REG-02, REG-03, REG-04
**Success Criteria** (what must be TRUE):
  1. All latency injection tests pass in a single run (100ms, 200ms, asymmetric, jitter, active input)
  2. All network disruption tests pass in a single run (packet loss, reconnection)
  3. All 5 data comparison tests pass in a single run
  4. All multiplayer basic tests pass in a single run
  5. All multi-participant tests pass with 0.5s stagger in a single run
  6. All focus loss tests pass in a single run
**Research flag:** Unlikely -- validation of prior fixes; any new failures get diagnosed and fixed inline
**Plans:** 2 plans

Plans:
- [x] 73-01-PLAN.md — Run latency injection + network disruption tests, diagnose and fix any failures (NET-01, NET-02)
- [x] 73-02-PLAN.md — Run data comparison + multiplayer basic + multi-participant + focus loss tests (REG-01 through REG-04)

### Phase 74: Stability Certification
**Goal**: The full E2E test suite is proven stable -- 10 consecutive passes, zero flaky markers
**Depends on**: Phase 73
**Requirements**: STAB-01, STAB-02
**Success Criteria** (what must be TRUE):
  1. Full E2E test suite passes 10 consecutive runs with zero failures
  2. No xfail markers exist in any E2E test file
  3. No tolerance hacks or known-flaky annotations exist in any E2E test file
  4. Any failure during the 10-run sequence triggers root cause investigation (not retry-and-hope)
**Research flag:** Unlikely -- pure execution and validation
**Plans:** 2 plans

Plans:
- [x] 74-01-PLAN.md — Audit E2E test suite for STAB-02 compliance (xfail, tolerance hacks, flaky markers)
- [x] 74-02-PLAN.md — Execute full-suite stability certification with GGPO bug investigation

### Phase 75: Merged Loading Screen
**Goal**: Participants see a single loading screen that gates on both compatibility check and Pyodide readiness
**Depends on**: Phase 74 (v1.17 complete)
**Requirements**: LOAD-01, LOAD-02, LOAD-03, LOAD-04
**Success Criteria** (what must be TRUE):
  1. Participant sees exactly one loading screen during pre-game setup (no separate Pyodide spinner)
  2. Loading screen does not advance until both compatibility check passes AND Pyodide is ready
  3. Pyodide loading timeout is configurable via experiment config (defaults to 60s)
  4. If Pyodide fails or times out, participant sees a clear error page instead of hanging
**Research flag:** Complete (75-RESEARCH.md)
**Plans:** 2 plans

Plans:
- [x] 75-01-PLAN.md — Add pyodide_load_timeout_s to config classes, dynamic server timeout, unified HTML loading element
- [x] 75-02-PLAN.md — Refactor client-side JS with loadingGate, timeout, error handling, and unified loading screen

### Phase 76: Test & Roadmap Cleanup
**Goal**: Remove dead test code and update roadmap to reflect actual completion state
**Depends on**: Nothing (independent of Phase 75)
**Requirements**: CLEAN-01, CLEAN-02, CLEAN-03, CLEAN-04
**Success Criteria** (what must be TRUE):
  1. `flask_server_multi_episode` fixture no longer exists in conftest.py
  2. `test_network_disruption.py` has no unused imports
  3. `run_full_episode_flow` exists in exactly one location (`game_helpers.py`) and all consumers import from there
  4. ROADMAP.md shows v1.14 Phases 65-66 as complete
**Research flag:** Unlikely — straightforward deletions and edits
**Plans:** 1 plan

Plans:
- [x] 76-01-PLAN.md — Remove orphaned fixtures, consolidate helpers, update roadmap

### Phase 77: P2P Connection Scoping
**Goal**: P2P/WebRTC connections are scoped to GymScenes — torn down on exit, no stale overlays on other scenes
**Depends on**: Phase 76 (v1.18 complete)
**Requirements**: P2P-01, P2P-02
**Success Criteria** (what must be TRUE):
  1. When a participant advances past a GymScene, all WebRTC connections are closed (no lingering DataChannels or PeerConnections)
  2. When a participant is on a non-GymScene scene (survey, instructions, end screen), no "partner disconnected" overlay appears even if their former partner disconnects
  3. Existing GymScene gameplay is unaffected (P2P connections still work during active game)
**Research flag:** Complete (77-RESEARCH.md)
**Plans:** 1 plan

Plans:
- [x] 77-01-PLAN.md — Add cleanupForSceneExit() and sceneExited guards to scope P2P connections to GymScene lifetime

### Phase 78: Group History Tracking
**Goal**: Matchmakers can query group history to re-pair previous partners across GymScenes
**Depends on**: Phase 77
**Requirements**: P2P-03, P2P-04
**Success Criteria** (what must be TRUE):
  1. Server records which participants were paired together after each GymScene completes
  2. Group history persists across scene transitions (available in later scenes)
  3. A custom matchmaker can query group history and use it to re-pair previous partners in future GymScenes
  4. Group history does not interfere with fresh matching (new participants unaffected)
**Research flag:** Complete (78-RESEARCH.md)
**Plans:** 1 plan

Plans:
- [x] 78-01-PLAN.md — Add GroupHistory dataclass, extend MatchCandidate, implement GroupReunionMatchmaker, wire group history into GameManager

### Phase 79: Post-Game Scene Isolation Test
**Goal**: E2E test validates that after two players complete Overcooked and advance to the survey scene, one player exiting does not trigger a partner-disconnected overlay on the remaining player
**Depends on**: Phase 78
**Success Criteria** (what must be TRUE):
  1. Two Playwright-controlled players complete an Overcooked game together and advance to the survey scene
  2. When one player closes their browser/tab on the survey scene, the remaining player does NOT see a partner-disconnected overlay
  3. The remaining player's survey scene remains functional (not interrupted)
**Research flag:** Unlikely — builds on existing E2E infrastructure
**Plans:** 1 plan

Plans:
- [x] 79-01-PLAN.md — Create multi-scene test server config, server fixture, and E2E test validating post-game scene isolation

### Phase 80: Pre-Game Countdown
**Goal**: After matchmaking forms a match, show a 3-second "Players found!" countdown on the waiting room screen before transitioning to the game
**Depends on**: Phase 79 (v1.19 complete)
**Requirements**: CD-01, CD-02, CD-03
**Success Criteria** (what must be TRUE):
  1. After matchmaker forms a match, all matched players see "Players found!" with a 3-2-1 countdown on the waiting room screen
  2. Countdown is visible simultaneously to all matched players (server-triggered)
  3. Game scene transition and gameplay start only after countdown completes, synced across all players
  4. Existing single-player and non-multiplayer flows are unaffected (no regression)
**Research flag:** Unlikely — straightforward client/server event flow using existing waiting_room and start_game patterns
**Plans:** 1 plan

Plans:
- [x] 80-01-PLAN.md — Server-side countdown delay + client-side countdown display on waiting room screen

### Phase 81: LatencyFIFOMatchmaker Core
**Goal**: A matchmaker class that skips candidates whose estimated P2P RTT (sum of server RTTs) exceeds a configurable threshold
**Depends on**: Phase 80 (v1.20 complete)
**Requirements**: MATCH-01, MATCH-02, MATCH-04
**Success Criteria** (what must be TRUE):
  1. `LatencyFIFOMatchmaker(max_server_rtt_ms=200)` can be instantiated with a configurable threshold
  2. `find_match()` skips waiting candidates where sum of server RTTs exceeds `max_server_rtt_ms`
  3. When no candidate passes the RTT filter, arriving participant waits (returns None)
  4. When a candidate's RTT data is unavailable (None), they are NOT excluded (graceful fallback)
**Research flag:** Unlikely — straightforward subclass of existing Matchmaker, server RTT already available on MatchCandidate
**Plans:** 1 plan

Plans:
- [x] 81-01-PLAN.md — Implement LatencyFIFOMatchmaker class with server RTT pre-filtering and unit tests

### Phase 82: Scene API & P2P Probe Integration
**Goal**: Researcher can use LatencyFIFOMatchmaker via scene config, with post-match P2P probe verification
**Depends on**: Phase 81
**Requirements**: MATCH-03, MATCH-05
**Success Criteria** (what must be TRUE):
  1. `scene.matchmaking(matchmaker=LatencyFIFOMatchmaker(max_server_rtt_ms=200, max_p2p_rtt_ms=150))` works
  2. After RTT pre-filter match, P2P probe still runs if `max_p2p_rtt_ms` is set
  3. Rejected P2P probe returns participants to waitroom (existing behavior preserved)
**Research flag:** Unlikely — existing scene.matchmaking() API and P2P probe flow already support custom matchmakers with max_p2p_rtt_ms
**Plans:** TBD

Plans:
- [ ] 82-01: TBD

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1-10 | v1.0 | — | Complete | 2026-01-19 |
| 11-14 | v1.1 | — | Complete | 2026-01-21 |
| 15-18 | v1.2 | — | Complete | 2026-01-22 |
| 19-22 | v1.3 | — | Complete | 2026-01-22 |
| 23 | v1.4 | — | Complete | 2026-01-22 |
| 24-27 | v1.5 | — | Complete | 2026-01-23 |
| 28 | v1.6 | — | Complete | 2026-01-24 |
| 29-31 | v1.6 | — | Deferred | — |
| 32-35 | v1.7 | — | Complete | 2026-01-25 |
| 36-39 | v1.8 | — | Complete | 2026-01-30 |
| 40-44 | v1.9 | — | Complete | 2026-02-01 |
| 45-47 | v1.10 | — | Complete | 2026-02-02 |
| 48-50 | v1.11 | — | Complete | 2026-02-02 |
| 51-56 | v1.12 | — | Complete | 2026-02-03 |
| 57-60 | v1.13 | — | Complete | 2026-02-03 |
| 61. Input Confirmation Protocol | v1.14 | 1/1 | Complete | 2026-02-03 |
| 62. Data Parity Validation | v1.14 | 1/1 | Complete | 2026-02-03 |
| 63. Parity Test Stabilization | v1.14 | 1/1 | Complete | 2026-02-03 |
| 64. Multi-Participant Test Infrastructure | v1.14 | 1/1 | Complete | 2026-02-03 |
| 65. Multi-Episode Lifecycle Stress | v1.14 | 2/2 | Complete | 2026-02-04 |
| 66. Server Recovery Validation | v1.14 | 1/1 | Complete | 2026-02-04 |
| 67. Pyodide Pre-load Infrastructure | v1.16 | 1/1 | Complete | 2026-02-06 |
| 68. Shared Instance Integration | v1.16 | 1/1 | Complete | 2026-02-06 |
| 69. Server-Side Init Grace | v1.16 | 1/1 | Complete | 2026-02-06 |
| 70. Validation & Test Stabilization | v1.16 | 1/1 | Complete | 2026-02-06 |
| 71. Test Infrastructure Fix | v1.17 | 2/2 | Complete | 2026-02-06 |
| 72. Latency Test Diagnosis | v1.17 | 2/2 | Complete | 2026-02-06 |
| 73. Network & Regression Validation | v1.17 | 2/2 | Complete | 2026-02-06 |
| 74. Stability Certification | v1.17 | 2/2 | Complete | 2026-02-06 |
| 75. Merged Loading Screen | v1.18 | 2/2 | Complete | 2026-02-06 |
| 76. Test & Roadmap Cleanup | v1.18 | 1/1 | Complete | 2026-02-07 |
| 77. P2P Connection Scoping | v1.19 | 1/1 | Complete | 2026-02-07 |
| 78. Group History Tracking | v1.19 | 1/1 | Complete | 2026-02-07 |
| 79. Post-Game Scene Isolation Test | v1.19 | 1/1 | Complete | 2026-02-07 |
| 80. Pre-Game Countdown | v1.20 | 1/1 | Complete | 2026-02-07 |
| 81. LatencyFIFOMatchmaker Core | v1.21 | 1/1 | Complete | 2026-02-07 |
| 82. Scene API & P2P Probe Integration | v1.21 | 0/1 | Not started | - |

---
*Roadmap created: 2026-01-20*
*Last updated: 2026-02-07 after Phase 81 execution*
