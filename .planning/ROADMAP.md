# Roadmap: Interactive Gym P2P Multiplayer

## Milestones

- **v1.0 P2P Multiplayer** - Phases 1-10 (shipped 2026-01-19)
- **v1.1 Sync Validation** - Phases 11-14 (complete)
- **v1.2 Participant Exclusion** - Phases 15-18 (complete)

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

### v1.2 Participant Exclusion (In Progress)

**Milestone Goal:** A configurable, extensible system to exclude participants who don't meet experiment requirements - checked both at entry and continuously during play.

- [x] **Phase 15: Entry Screening Rules** - Pre-game device/browser/ping checks with exclusion messaging
- [x] **Phase 16: Continuous Monitoring** - Real-time ping and tab visibility monitoring during gameplay
- [x] **Phase 17: Multiplayer Exclusion Handling** - Coordinated game termination when one player excluded
- [x] **Phase 18: Custom Exclusion Callbacks** - Researcher-defined arbitrary exclusion logic

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

## Progress

**Execution Order:**
Phases execute in numeric order: 15 -> 16 -> 17 -> 18

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

---
*Roadmap created: 2026-01-20*
*Last updated: 2026-01-22 after Phase 18 complete - v1.2 milestone complete*
