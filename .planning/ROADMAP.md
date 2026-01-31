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
- 🚧 **v1.9 Data Parity Testing** - Phases 40-44 (in progress)

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

### v1.7 Admin Console Improvement (Complete)

**Milestone Goal:** A clean, usable admin console that gives researchers effective experiment monitoring — see what's happening, catch problems, track progress.

- [x] **Phase 32: Dashboard Summary Stats** - Key experiment metrics at a glance
- [x] **Phase 33: Session List with P2P Health** - Session status and problem flagging
- [x] **Phase 34: Session Detail View** - Detailed diagnostic info on click
- [x] **Phase 35: Layout & Polish** - Clean visual hierarchy and prioritization

### v1.8 Data Export Parity (Complete)

**Milestone Goal:** Both players export identical game state data (actions, observations, rewards, infos) regardless of rollbacks, fast-forwards, or latency — ensuring research data validity.

- [x] **Phase 36: Speculative/Canonical Buffer Split** - Core data recording architecture fix
- [x] **Phase 37: Fast-Forward Data Recording Fix** - Tab refocus confirmation-gated recording
- [x] **Phase 38: Episode Boundary Confirmation** - Ensure all frames confirmed before export
- [x] **Phase 39: Verification & Metadata** - Per-frame metadata and validation tooling

## Phase Details

### Phase 11: Hash Infrastructure
**Goal:** Deterministic state hashing with float normalization, confirmed frame tracking
**Depends on:** v1.0 complete (existing P2P infrastructure)
**Requirements:** HASH-01, HASH-02, HASH-03, HASH-04
**Success Criteria** (what must be TRUE):
  1. State hash computed only after all inputs confirmed for a frame
  2. Floats normalized to 10 decimal places before serialization
  3. SHA-256 hash produces identical results across browsers
  4. confirmedHashHistory tracks frame-to-hash mapping
**Research flag:** Unlikely (standard patterns)
**Plans:** 1 plan
Plans:
- [x] 11-01-PLAN.md - SHA-256 hashing, float normalization, confirmedHashHistory, rollback invalidation

### Phase 12: P2P Hash Exchange
**Goal:** Binary hash message protocol over DataChannel
**Depends on:** Phase 11
**Requirements:** EXCH-01, EXCH-02, EXCH-03, EXCH-04
**Success Criteria** (what must be TRUE):
  1. Hashes exchanged via P2P DataChannel (not SocketIO)
  2. Hash exchange doesn't block frame advancement
  3. Hash history cleared when rollback invalidates frames
  4. Binary message format (13 bytes) works correctly
**Research flag:** Unlikely (extension of existing protocol)
**Plans:** 1 plan
Plans:
- [x] 12-01-PLAN.md - P2P_MSG_STATE_HASH protocol, encode/decode, exchange queue, rollback invalidation

### Phase 13: Mismatch Detection
**Goal:** Comparison logic, peer buffering, desync event logging
**Depends on:** Phase 12
**Requirements:** DETECT-01, DETECT-02, DETECT-03, DETECT-04, DETECT-05
**Success Criteria** (what must be TRUE):
  1. Exact frame number identified when mismatch occurs
  2. Peer hashes buffered until local confirmation catches up
  3. Desync events logged with frame, both hashes, timestamp
  4. verifiedFrame tracks highest mutually-verified frame
  5. Full state dump captured on mismatch
**Research flag:** Unlikely (architecture documented, patterns from prior phases)
**Plans:** 1 plan
Plans:
- [x] 13-01-PLAN.md - verifiedFrame tracking, desyncEvents logging, comparison logic, rollback integration

### Phase 14: Validation Export
**Goal:** Post-game JSON export with frame-by-frame validation data
**Depends on:** Phase 13
**Requirements:** EXPORT-01, EXPORT-02, EXPORT-03, EXPORT-04
**Success Criteria** (what must be TRUE):
  1. JSON export available after game ends
  2. Export contains only confirmed-frame data (no predictions)
  3. Desync events included in export
  4. Verified action sequences exported per player
**Research flag:** Unlikely (straightforward JSON export)
**Plans:** 1 plan
Plans:
- [x] 14-01-PLAN.md - exportValidationData method, confirmed hash export, verified actions, desync events

### Phase 15: Entry Screening Rules
**Goal:** Pre-game screening with device, browser, and ping checks
**Depends on:** v1.1 complete (existing P2P infrastructure)
**Requirements:** ENTRY-01, ENTRY-02, ENTRY-03, ENTRY-04
**Success Criteria** (what must be TRUE):
  1. Researcher can configure device type exclusion (mobile/desktop/both) in Python config
  2. Researcher can configure browser requirements (require/block specific browsers)
  3. Participant blocked at entry if ping exceeds configured threshold
  4. Participant sees rule-specific message explaining why excluded
**Research flag:** Unlikely (jsPsych browser-check as reference, ua-parser-js documented)
**Plans:** 1 plan
Plans:
- [x] 15-01-PLAN.md - GymScene.entry_screening() config, ua-parser-js detection, exclusion UI

### Phase 16: Continuous Monitoring
**Goal:** Real-time ping and tab visibility monitoring during gameplay
**Depends on:** Phase 15
**Requirements:** MONITOR-01, MONITOR-02, MONITOR-03, MONITOR-04
**Success Criteria** (what must be TRUE):
  1. Participant ping monitored continuously during gameplay
  2. Participant excluded mid-game if ping exceeds threshold for sustained period
  3. Tab switch detected when participant leaves experiment window
  4. Tab visibility triggers configurable warning or exclusion
**Research flag:** Likely (power-saving mode pitfall P10 needs careful handling)
**Plans:** 1 plan
Plans:
- [x] 16-01-PLAN.md - GymScene.continuous_monitoring() config, ContinuousMonitor class, game loop integration

### Phase 17: Multiplayer Exclusion Handling
**Goal:** Coordinated game termination when one player excluded
**Depends on:** Phase 16
**Requirements:** MULTI-01, MULTI-02, MULTI-03
**Success Criteria** (what must be TRUE):
  1. Non-excluded player sees clear partner notification message
  2. Game terminates cleanly for both players when one is excluded
  3. Valid game data up to exclusion point is preserved and marked as partial session
**Research flag:** Likely (no existing patterns for real-time multiplayer exclusion)
**Plans:** 1 plan
Plans:
- [x] 17-01-PLAN.md - Server handler, partner notification, partial session marking

### Phase 18: Custom Exclusion Callbacks
**Goal:** Researcher-defined arbitrary exclusion logic via Python callbacks
**Depends on:** Phase 17
**Requirements:** EXT-01, EXT-02, EXT-03
**Success Criteria** (what must be TRUE):
  1. Researcher can define custom exclusion rules via Python callback functions
  2. Callbacks receive full participant context (ping, browser, focus state, etc.)
  3. Callbacks return exclusion decision with optional message
**Research flag:** Unlikely (standard callback patterns)
**Plans:** 1 plan
Plans:
- [x] 18-01-PLAN.md - GymScene.exclusion_callbacks() config, server-side callback execution, client-server integration

### Phase 19: Waiting Room Validation
**Goal:** P2P connection validated before experiment starts
**Depends on:** v1.2 complete (existing exclusion infrastructure)
**Requirements:** WAIT-01, WAIT-02, WAIT-03
**Success Criteria** (what must be TRUE):
  1. P2P connection established and validated before proceeding to experiment
  2. Failed P2P pairs automatically returned to matchmaking pool
  3. Participants see clear status messaging during P2P validation attempt
**Research flag:** Unlikely (WebRTC connection state APIs well-documented)
**Plans:** 1 plan
Plans:
- [x] 19-01-PLAN.md - P2P validation protocol, server coordination, re-pool on failure, status UI

### Phase 20: Mid-Game Reconnection
**Goal:** Handle P2P drops with pause, overlay, and configurable recovery
**Depends on:** Phase 19
**Requirements:** RECON-01, RECON-02, RECON-03, RECON-04, RECON-05, RECON-06, LOG-01, LOG-02, LOG-03
**Success Criteria** (what must be TRUE):
  1. DataChannel drop detected immediately by both clients
  2. Gameplay pauses for both players when connection drops
  3. Both players see reconnecting overlay during recovery attempts
  4. Gameplay resumes seamlessly if reconnection succeeds
  5. Game ends cleanly if reconnection times out (configurable)
  6. Disconnection and reconnection events logged with timestamps
**Research flag:** Likely (WebRTC reconnection patterns vary, state machine complexity)
**Plans:** 2 plans
Plans:
- [x] 20-01-PLAN.md - Connection drop detection, bilateral pause coordination, server-side state tracking
- [x] 20-02-PLAN.md - Reconnecting overlay UI, ICE restart recovery, resume handling, config API, data export

### Phase 21: Per-Round Health Check
**Goal:** Verify DataChannel before each round
**Depends on:** Phase 20
**Requirements:** ROUND-01, ROUND-02
**Success Criteria** (what must be TRUE):
  1. DataChannel connection verified before each round begins
  2. Round start blocked until P2P connection confirmed healthy
**Research flag:** Unlikely (builds on Phase 20 infrastructure)
**Plans:** 1 plan
Plans:
- [x] 21-01-PLAN.md — Per-round health check with connection blocking before episode sync

### Phase 22: Latency Telemetry
**Goal:** Async latency monitoring and stats export
**Depends on:** Phase 21
**Requirements:** LAT-01, LAT-02
**Success Criteria** (what must be TRUE):
  1. P2P latency measured periodically during gameplay (non-blocking)
  2. Latency stats (min, median, mean, max) exported in session data
**Research flag:** Unlikely (WebRTC getStats() well-documented)
**Plans:** 1 plan
Plans:
- [x] 22-01-PLAN.md — LatencyTelemetry class, async RTT sampling, stats export integration

### Phase 23: Partner Disconnection Handling
**Goal:** When a partner disconnects mid-game, stay on the same page (no redirect), hide game UI, show a configurable message, export all collected data with disconnection metadata including the disconnected player's ID.
**Depends on:** v1.3 complete (existing reconnection infrastructure)
**Requirements:** UI-01, UI-02, UI-03, UI-04, DATA-01, DATA-02, DATA-03, DATA-04, CFG-01, CFG-02
**Success Criteria** (what must be TRUE):
  1. Partner disconnect triggers in-page overlay instead of redirect to `/partner-disconnected`
  2. Game container and HUD are hidden when overlay appears
  3. Default message shown when no custom message configured
  4. Custom message from `GymScene.partner_disconnect_message()` displayed when configured
  5. Page stays displayed indefinitely (no auto-redirect, no Continue button)
  6. `emitMultiplayerMetrics()` called before overlay display to export collected data
  7. `sessionPartialInfo` populated with `isPartial: true` and `terminationReason: 'partner_disconnected'`
  8. `sessionPartialInfo` includes `disconnectedPlayerId` with the partner's player ID
**Research flag:** Unlikely (builds on existing overlay patterns from Phases 17, 20)
**Plans:** 1 plan
Plans:
- [x] 23-01-PLAN.md — In-page overlay, config API, data export with disconnectedPlayerId

### Phase 24: Web Worker Timer Infrastructure
**Goal:** Move timing-critical code to Web Worker for throttle-resistant operation
**Depends on:** v1.4 complete (existing P2P infrastructure)
**Requirements:** WORK-01, WORK-02
**Success Criteria** (what must be TRUE):
  1. Game timing runs in a Web Worker, not main thread
  2. When tab is backgrounded, Worker timer continues at accurate intervals (not throttled)
  3. Main thread communicates with Worker via postMessage for game state updates
**Research flag:** Likely (Web Worker timing patterns, main thread/Worker communication)
**Plans:** 1 plan
Plans:
- [x] 24-01-PLAN.md — GameTimerWorker class, Worker-driven game loop, decoupled rendering

### Phase 25: Focus Detection & Background State
**Goal:** Detect when participant tabs away and track background duration
**Depends on:** Phase 24
**Requirements:** FOCUS-01, FOCUS-02, BG-01, BG-02
**Success Criteria** (what must be TRUE):
  1. Tab visibility changes are detected immediately via Page Visibility API
  2. Duration of each background period is tracked with start/end timestamps
  3. When backgrounded, player's actions default to idle/no-op (no random inputs)
  4. Partner inputs received via WebRTC are buffered while player is backgrounded
**Research flag:** Unlikely (Page Visibility API well-documented, builds on existing exclusion patterns)
**Plans:** 1 plan
Plans:
- [x] 25-01-PLAN.md — FocusManager class with visibility detection, background tracking, input buffering

### Phase 26: Resync & Partner Experience
**Goal:** Fast-forward on refocus while keeping focused partner uninterrupted
**Depends on:** Phase 25
**Requirements:** BG-03, PARTNER-01, PARTNER-02
**Success Criteria** (what must be TRUE):
  1. When backgrounded player refocuses, simulation fast-forwards using queued inputs
  2. Focused partner's game loop never pauses or stutters when other player tabs away
  3. Focused partner sees backgrounded player go idle (their inputs stop affecting game)
**Research flag:** Likely (fast-forward resync patterns, GGPO integration with background state)
**Plans:** 1 plan
Plans:
- [x] 26-01-PLAN.md — Fast-forward resync on refocus, partner experience verification

### Phase 27: Timeout, Messaging & Telemetry
**Goal:** Configurable timeout with graceful game ending and research data capture
**Depends on:** Phase 26
**Requirements:** TIMEOUT-01, TIMEOUT-02, TIMEOUT-03, TELEM-01, TELEM-02
**Success Criteria** (what must be TRUE):
  1. Focus loss timeout is configurable (default 30s)
  2. When timeout exceeded, game ends for both players
  3. Custom message displayed when game ends due to focus loss timeout
  4. Focus loss events recorded in session metadata
  5. Duration of each focus loss period included in exported data
**Research flag:** Unlikely (builds on existing timeout/messaging patterns from v1.3/v1.4)
**Plans:** 1 plan
Plans:
- [x] 27-01-PLAN.md — Config API, timeout enforcement, telemetry export

### Phase 28: Pipeline Instrumentation
**Goal:** Add timestamps at each stage of the input→execute→render pipeline
**Depends on:** v1.5 complete (existing timing infrastructure)
**Requirements:** DIAG-01, DIAG-02, DIAG-03, DIAG-04, DIAG-05, DIAG-06, DIAG-07
**Success Criteria** (what must be TRUE):
  1. Keypress events record timestamp via performance.now()
  2. Input queue entry/exit timestamps captured
  3. Pyodide env.step() call and return timestamps captured
  4. Render begin/complete timestamps captured
  5. Per-input latency breakdown computed and logged to console
**Research flag:** Unlikely (performance.now() API well-documented)
**Plans:** 1 plan
Plans:
- [x] 28-01-PLAN.md — Pipeline instrumentation with per-stage timestamps

### Phase 29: Root Cause Diagnosis
**Goal:** Use instrumentation data to identify where the 1-2 second delay occurs
**Depends on:** Phase 28
**Requirements:** (diagnostic work — uses DIAG-* outputs to inform FIX-*)
**Success Criteria** (what must be TRUE):
  1. Latency data collected from Overcooked gameplay sessions
  2. Pipeline stage causing delay identified with supporting data
  3. Root cause documented with evidence and proposed fix
**Research flag:** Likely (may need to investigate Pyodide performance, browser quirks)
**Plans:** TBD
Plans:
- [ ] 29-01-PLAN.md — Data collection, analysis, root cause identification

### Phase 30: Latency Fix
**Goal:** Implement fix for identified root cause to achieve <100ms local input response
**Depends on:** Phase 29
**Requirements:** FIX-01, FIX-02, FIX-03
**Success Criteria** (what must be TRUE):
  1. Local input latency consistently under 100ms (keypress to render)
  2. Fix verified working in single-player mode
  3. Fix verified working in multiplayer mode
  4. Fix verified specifically in Overcooked environment
**Research flag:** Unknown (depends on what root cause is found)
**Plans:** TBD
Plans:
- [ ] 30-01-PLAN.md — Implement fix for identified root cause

### Phase 31: Telemetry Export
**Goal:** Export latency metrics for research analysis
**Depends on:** Phase 30
**Requirements:** TELEM-01, TELEM-02, TELEM-03, TELEM-04
**Success Criteria** (what must be TRUE):
  1. Session data export includes input latency metrics
  2. Min/max/mean/median latency stats computed per session
  3. Latency outliers (>100ms) flagged and counted in export
  4. Per-stage latency breakdown available in exported data
**Research flag:** Unlikely (extends existing telemetry patterns from v1.3/v1.5)
**Plans:** TBD
Plans:
- [ ] 31-01-PLAN.md — Latency stats computation and export integration

### Phase 32: Dashboard Summary Stats
**Goal:** Researchers see key experiment metrics at a glance
**Depends on:** v1.6 complete (existing admin infrastructure)
**Requirements:** DASH-01, DASH-02, DASH-03
**Success Criteria** (what must be TRUE):
  1. Dashboard displays "X of Y participants completed successfully" (completion rate)
  2. Dashboard displays average session duration
  3. Summary stats appear prominently at top of admin page
**Research flag:** Unlikely (standard dashboard patterns)
**Plans:** 1 plan
Plans:
- [x] 32-01-PLAN.md — Completion rate aggregation, avg duration computation, summary stat cards

### Phase 33: Session List with P2P Health
**Goal:** Session list shows what's happening and flags problems
**Depends on:** Phase 32
**Requirements:** LIST-01, LIST-02, LIST-03, LIST-04, LIST-05
**Success Criteria** (what must be TRUE):
  1. Each active session shows current episode/round number
  2. Each session shows connection type (P2P direct / TURN relay / SocketIO fallback)
  3. Each session shows current peer latency
  4. Sessions display health indicator (healthy / degraded / reconnecting)
  5. Problem sessions are visually distinguished from healthy ones
**Research flag:** Unlikely (extends existing session list)
**Plans:** 1 plan
Plans:
- [x] 33-01-PLAN.md — P2P health reporting, aggregator storage, session list UI with health indicators

### Phase 34: Session Detail View
**Goal:** Clicking a session reveals detailed diagnostic info
**Depends on:** Phase 33
**Requirements:** DETAIL-01, DETAIL-02, DETAIL-03, DETAIL-04
**Success Criteria** (what must be TRUE):
  1. Clicking a session opens detailed view
  2. Detail view shows exclusion reason (if participant was excluded)
  3. Detail view shows disconnection reason (if session ended abnormally)
  4. Detail view surfaces console errors from that session
**Research flag:** Unlikely (builds on existing session data)
**Plans:** 1 plan
Plans:
- [x] 34-01-PLAN.md — Session detail panel with termination reason and console error filtering

### Phase 35: Layout & Polish
**Goal:** Clean, prioritized information hierarchy
**Depends on:** Phase 34
**Requirements:** LAYOUT-01, LAYOUT-02
**Success Criteria** (what must be TRUE):
  1. Clear visual hierarchy: summary at top → session list in middle → details on click
  2. Information prioritized by importance (stats > active sessions > history)
**Research flag:** Unlikely (UI polish)
**Plans:** 1 plan
Plans:
- [x] 35-01-PLAN.md — Layout restructure with active sessions primary, problems indicator

### Phase 36: Speculative/Canonical Buffer Split
**Goal:** Separate speculative frame data from confirmed frame data
**Depends on:** v1.7 complete (existing data collection infrastructure)
**Requirements:** REC-01, REC-02, REC-03
**Success Criteria** (what must be TRUE):
  1. Frame data written to speculativeFrameData buffer during step()
  2. Data promoted to confirmed buffer only when all inputs for that frame are received
  3. Export methods read from confirmed buffer, never speculative
**Research flag:** Unlikely (well-documented pattern from GGPO/NetplayJS)
**Plans:** 1 plan
Plans:
- [x] 36-01-PLAN.md — speculativeFrameData buffer, storeFrameData() modification, _promoteConfirmedFrames()

### Phase 37: Fast-Forward Data Recording Fix
**Goal:** Fast-forward uses same confirmation-gated recording path as normal execution
**Depends on:** Phase 36
**Requirements:** EDGE-01
**Success Criteria** (what must be TRUE):
  1. Fast-forward (tab refocus) writes to speculative buffer like normal execution
  2. _promoteConfirmedFrames() called after fast-forward completes
  3. No frame gaps in export after tab refocus scenario
**Research flag:** Complete (root cause identified in research phase)
**Plans:** 1 plan
Plans:
- [x] 37-01-PLAN.md — Add _promoteConfirmedFrames() call in _performFastForward()

### Phase 38: Episode Boundary Confirmation
**Goal:** All frames confirmed before export triggered
**Depends on:** Phase 37
**Requirements:** EDGE-02
**Success Criteria** (what must be TRUE):
  1. Episode end waits for all frames to be confirmed before triggering export
  2. Warning logged if promoting unconfirmed frames at episode boundary
  3. Both players export identical frame counts
**Research flag:** Unlikely (focused change at episode boundary)
**Plans:** 1 plan
Plans:
- [x] 38-01-PLAN.md — Force-promote at episode end, warning logging

### Phase 39: Verification & Metadata
**Goal:** Per-frame metadata and offline validation tooling
**Depends on:** Phase 38
**Requirements:** REC-04, EDGE-03, VERIFY-01
**Success Criteria** (what must be TRUE):
  1. Each frame includes `wasSpeculative` metadata indicating if it was ever predicted
  2. Export includes rollback event metadata (frame ranges, count per frame)
  3. Offline validation script compares two player exports and reports divergences
**Research flag:** Unlikely (additive metadata, no core logic changes)
**Plans:** 1 plan
Plans:
- [x] 39-01-PLAN.md — wasSpeculative field, rollback metadata, export comparison script

</details>

### v1.9 Data Parity Testing (In Progress)

**Milestone Goal:** Validate v1.8 data export parity under controlled network conditions using Playwright automation against `overcooked_human_human_multiplayer`.

### Phase 40: Test Infrastructure Foundation
**Goal:** Playwright can automate multiplayer game sessions
**Depends on:** v1.8 complete (existing data export infrastructure)
**Requirements:** INFRA-01, INFRA-02
**Success Criteria** (what must be TRUE):
  1. Two browser contexts can connect to the same game session
  2. Both contexts can progress through matchmaking to gameplay
  3. Flask server starts/stops cleanly as part of test lifecycle
  4. Test can capture game completion state
**Research flag:** Likely (Playwright MCP integration, multiplayer automation patterns)
**Plans:** 2 plans

Plans:
- [x] 40-01-PLAN.md — Test infrastructure setup (pytest, fixtures, server lifecycle)
- [x] 40-02-PLAN.md — Game automation helpers and multiplayer test

### Phase 41: Latency Injection Tests
**Goal:** Test data parity under various latency conditions
**Depends on:** Phase 40
**Requirements:** NET-01, NET-04, NET-05
**Success Criteria** (what must be TRUE):
  1. Test can apply fixed latency (100ms, 200ms, 500ms) via CDP
  2. Test can apply asymmetric latency (different for each player)
  3. Test can apply jitter (variable latency) during gameplay
  4. Tests run to episode completion under each latency condition
**Research flag:** Likely (Chrome DevTools Protocol latency injection)
**Plans:** 1 plan

Plans:
- [x] 41-01-PLAN.md — CDP latency injection, asymmetric/jitter scenarios

### Phase 42: Network Disruption Tests
**Goal:** Test data parity under packet loss and tab focus scenarios
**Depends on:** Phase 41
**Requirements:** NET-02, NET-03
**Success Criteria** (what must be TRUE):
  1. Test can simulate packet loss to trigger rollback scenarios
  2. Test can trigger tab unfocus/refocus to exercise fast-forward path
  3. Both tests complete full episode after disruption
  4. Rollback and fast-forward events are observable in exports
**Research flag:** Likely (WebRTC packet loss simulation, Playwright tab control)
**Plans:** 1 plan

Plans:
- [x] 42-01-PLAN.md — Packet loss simulation, tab focus automation

### Phase 43: Data Comparison Pipeline
**Goal:** Automated validation of export parity between players
**Depends on:** Phase 42
**Requirements:** CMP-01, CMP-02, CMP-03
**Success Criteria** (what must be TRUE):
  1. Test collects export files from both players after episode
  2. Test invokes `validate_action_sequences.py --compare` on exports
  3. Test reports pass/fail based on validation script exit code
  4. Failed comparisons produce actionable diagnostic output
**Research flag:** Unlikely (file collection and script invocation)
**Plans:** TBD

Plans:
- [ ] 43-01-PLAN.md — Export collection, validation invocation, result reporting

### Phase 44: Manual Test Protocol
**Goal:** Researchers can manually verify data parity
**Depends on:** Phase 43
**Requirements:** DOC-01
**Success Criteria** (what must be TRUE):
  1. Step-by-step protocol document exists
  2. Protocol covers each network condition scenario
  3. Protocol includes how to compare exports manually
  4. Protocol includes expected outcomes for each test
**Research flag:** Unlikely (documentation)
**Plans:** 1 plan

Plans:
- [ ] 44-01-PLAN.md — Manual test protocol documentation

## Progress

**Execution Order:**
Phases execute in numeric order: 40 → 41 → 42 → 43 → 44

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 11. Hash Infrastructure | v1.1 | 1/1 | Complete | 2026-01-21 |
| 12. P2P Hash Exchange | v1.1 | 1/1 | Complete | 2026-01-21 |
| 13. Mismatch Detection | v1.1 | 1/1 | Complete | 2026-01-21 |
| 14. Validation Export | v1.1 | 1/1 | Complete | 2026-01-21 |
| 15. Entry Screening Rules | v1.2 | 1/1 | Complete | 2026-01-21 |
| 16. Continuous Monitoring | v1.2 | 1/1 | Complete | 2026-01-21 |
| 17. Multiplayer Exclusion | v1.2 | 1/1 | Complete | 2026-01-21 |
| 18. Custom Callbacks | v1.2 | 1/1 | Complete | 2026-01-22 |
| 19. Waiting Room Validation | v1.3 | 1/1 | Complete | 2026-01-22 |
| 20. Mid-Game Reconnection | v1.3 | 2/2 | Complete | 2026-01-22 |
| 21. Per-Round Health Check | v1.3 | 1/1 | Complete | 2026-01-22 |
| 22. Latency Telemetry | v1.3 | 1/1 | Complete | 2026-01-22 |
| 23. Partner Disconnection | v1.4 | 1/1 | Complete | 2026-01-22 |
| 24. Web Worker Timer | v1.5 | 1/1 | Complete | 2026-01-23 |
| 25. Focus Detection | v1.5 | 1/1 | Complete | 2026-01-23 |
| 26. Resync & Partner UX | v1.5 | 1/1 | Complete | 2026-01-23 |
| 27. Timeout & Telemetry | v1.5 | 1/1 | Complete | 2026-01-23 |
| 28. Pipeline Instrumentation | v1.6 | 1/1 | Complete | 2026-01-24 |
| 29-31. Deferred | v1.6 | — | Deferred | — |
| 32. Dashboard Summary | v1.7 | 1/1 | Complete | 2026-01-25 |
| 33. Session List | v1.7 | 1/1 | Complete | 2026-01-25 |
| 34. Session Detail | v1.7 | 1/1 | Complete | 2026-01-25 |
| 35. Layout & Polish | v1.7 | 1/1 | Complete | 2026-01-25 |
| 36. Buffer Split | v1.8 | 1/1 | Complete | 2026-01-30 |
| 37. Fast-Forward Fix | v1.8 | 1/1 | Complete | 2026-01-30 |
| 38. Episode Boundary | v1.8 | 1/1 | Complete | 2026-01-30 |
| 39. Verification & Metadata | v1.8 | 1/1 | Complete | 2026-01-30 |
| 40. Test Infrastructure | v1.9 | 2/2 | Complete | 2026-01-31 |
| 41. Latency Injection | v1.9 | 1/1 | Complete | 2026-01-31 |
| 42. Network Disruption | v1.9 | 1/1 | Complete | 2026-01-31 |
| 43. Data Comparison | v1.9 | 0/1 | Not started | - |
| 44. Manual Protocol | v1.9 | 0/1 | Not started | - |

---
*Roadmap created: 2026-01-20*
*Last updated: 2026-01-31 after Phase 42 execution*
