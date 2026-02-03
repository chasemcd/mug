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
- 🚧 **v1.14 Data Parity Fix** - Phases 61-66 (in progress)

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

### 🚧 v1.14 Data Parity Fix (In Progress)

**Milestone Goal:** Fix the rare data parity divergence bug and add comprehensive multi-participant E2E stress tests. Data parity must be EXACT — both players export identical data for every frame under all network conditions.

- [x] **Phase 61: Input Confirmation Protocol** - Wait for partner input confirmation before export
- [ ] **Phase 62: Data Parity Validation** - Ensure identical exports for actions/rewards/infos
- [ ] **Phase 63: Parity Test Stabilization** - E2E tests pass consistently (10+ runs)
- [ ] **Phase 64: Multi-Participant Test Infrastructure** - Support 6 concurrent participants
- [ ] **Phase 65: Multi-Episode and Lifecycle Stress Tests** - Comprehensive lifecycle coverage
- [ ] **Phase 66: Server Recovery Validation** - Prove server recovers from chaos correctly

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
- [ ] 62-01-PLAN.md — Run parity tests to validate Phase 61 fix

### Phase 63: Parity Test Stabilization
**Goal**: E2E parity tests pass consistently with no tolerance or xfail markers
**Depends on**: Phase 62
**Requirements**: PARITY-06, PARITY-07
**Success Criteria** (what must be TRUE):
  1. `test_active_input_with_latency[chromium-100]` passes 10 consecutive runs
  2. `test_active_input_with_packet_loss` passes 10 consecutive runs
  3. No tolerance or xfail markers needed for parity tests
**Research flag:** Unlikely (running existing tests)
**Plans**: TBD

Plans:
- [ ] 63-01: TBD

### Phase 64: Multi-Participant Test Infrastructure
**Goal**: Build test infrastructure supporting 6 concurrent participants (3 simultaneous games)
**Depends on**: Phase 63
**Requirements**: STRESS-01
**Success Criteria** (what must be TRUE):
  1. Test fixture can launch 6 browser contexts simultaneously
  2. Test fixture can orchestrate 3 concurrent games
  3. Infrastructure handles staggered participant arrival
**Research flag:** Likely (Playwright concurrent context management, resource limits)
**Plans**: TBD

Plans:
- [ ] 64-01: TBD

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
**Research flag:** Unlikely (builds on Phase 64 infrastructure)
**Plans**: TBD

Plans:
- [ ] 65-01: TBD

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
**Plans**: TBD

Plans:
- [ ] 66-01: TBD

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
| 62. Data Parity Validation | v1.14 | 0/1 | Not started | - |
| 63. Parity Test Stabilization | v1.14 | 0/TBD | Not started | - |
| 64. Multi-Participant Test Infrastructure | v1.14 | 0/TBD | Not started | - |
| 65. Multi-Episode Lifecycle Stress | v1.14 | 0/TBD | Not started | - |
| 66. Server Recovery Validation | v1.14 | 0/TBD | Not started | - |

---
*Roadmap created: 2026-01-20*
*Last updated: 2026-02-03 after Phase 62 planning*
