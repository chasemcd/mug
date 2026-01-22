# Roadmap: Interactive Gym P2P Multiplayer

## Milestones

- **v1.0 P2P Multiplayer** - Phases 1-10 (shipped 2026-01-19)
- **v1.1 Sync Validation** - Phases 11-14 (complete)
- **v1.2 Participant Exclusion** - Phases 15-18 (shipped 2026-01-22)
- **v1.3 P2P Connection Validation** - Phases 19-22 (shipped 2026-01-22)
- **v1.4 Partner Disconnection Handling** - Phase 23 (in progress)

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

### v1.4 Partner Disconnection Handling (In Progress)

**Milestone Goal:** Improve the experience when a partner disconnects mid-game — stay on the same page with a configurable message, ensure data is exported with disconnection metadata.

- [x] **Phase 23: Partner Disconnection Handling** - In-page overlay, data export, disconnection metadata

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

## Progress

**Execution Order:**
Phases execute in numeric order: 23

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

---
*Roadmap created: 2026-01-20*
*Last updated: 2026-01-22 after Phase 23 complete*
