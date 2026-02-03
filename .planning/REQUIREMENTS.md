# Requirements: Interactive Gym v1.14

**Defined:** 2026-02-03
**Core Value:** Both players in a multiplayer game experience local-feeling responsiveness regardless of network latency, enabling valid research data collection without latency-induced behavioral artifacts.

## v1 Requirements

Requirements for v1.14 Data Parity Fix. Each maps to roadmap phases.

### Data Parity Fix

- [x] **PARITY-01**: Episode export waits for partner input confirmation before writing
- [x] **PARITY-02**: Configurable confirmation timeout (default reasonable for 200ms+ latency)
- [ ] **PARITY-03**: Both players export identical action sequences for every frame
- [ ] **PARITY-04**: Both players export identical rewards for every frame
- [ ] **PARITY-05**: Both players export identical infos for every frame
- [ ] **PARITY-06**: `test_active_input_with_latency[chromium-100]` passes consistently (10+ runs)
- [ ] **PARITY-07**: `test_active_input_with_packet_loss` passes consistently (10+ runs)

### Multi-Participant Stress Tests

- [ ] **STRESS-01**: Test infrastructure supports 6 concurrent participants (3 simultaneous games)
- [ ] **STRESS-02**: Multi-episode test: participants complete 2+ episodes back-to-back
- [ ] **STRESS-03**: Mid-game disconnection test: participant disconnects during gameplay
- [ ] **STRESS-04**: Waiting room disconnection test: participant disconnects while waiting
- [ ] **STRESS-05**: Focus loss test: tab goes to background during gameplay
- [ ] **STRESS-06**: Mixed lifecycle test: combines disconnect + completion + focus loss scenarios
- [ ] **STRESS-07**: All completed games' exports validated for exact parity

### Server Recovery Test

- [ ] **RECOVERY-01**: Test runs concurrent episodes to completion
- [ ] **RECOVERY-02**: Test has participants leave mid-game
- [ ] **RECOVERY-03**: Test has participants leave during waiting room
- [ ] **RECOVERY-04**: Test has participants leave due to focus loss timeout
- [ ] **RECOVERY-05**: After all chaos events, new participant pair can enter and complete experiment
- [ ] **RECOVERY-06**: New pair's data exports pass exact parity validation

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Enhanced Matching (from v1.13)

- **MATCH-01**: Wait time relaxation (progressively relax criteria as wait time increases)
- **MATCH-02**: Priority queuing for dropout recovery
- **MATCH-03**: Pre-match validation hook (beyond RTT, e.g., custom compatibility checks)

### Group Reunion (from v1.13)

- **REUN-01**: Matchmaker variant that reunites previous groups
- **REUN-02**: Configurable reunion timeout before falling back to FIFO

### Data Parity Enhancements

- **PARITY-V2-01**: Re-request lost packets if confirmation timeout (more robust than wait-only)
- **PARITY-V2-02**: Packet loss telemetry in export metadata

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Skill-based matchmaking (SBMM) | Game-focused pattern, not research validity |
| Global player pools | Cross-experiment contamination |
| Mid-game backfill | Invalidates experimental conditions |
| Tolerance in parity validation | Data must be EXACT for research validity |
| Load testing (100+ participants) | Research experiments typically <20 concurrent |

## Traceability

Which phases cover which requirements. Updated by create-roadmap.

| Requirement | Phase | Status |
|-------------|-------|--------|
| PARITY-01 | Phase 61 | Complete |
| PARITY-02 | Phase 61 | Complete |
| PARITY-03 | Phase 62 | Pending |
| PARITY-04 | Phase 62 | Pending |
| PARITY-05 | Phase 62 | Pending |
| PARITY-06 | Phase 63 | Pending |
| PARITY-07 | Phase 63 | Pending |
| STRESS-01 | Phase 64 | Pending |
| STRESS-02 | Phase 65 | Pending |
| STRESS-03 | Phase 65 | Pending |
| STRESS-04 | Phase 65 | Pending |
| STRESS-05 | Phase 65 | Pending |
| STRESS-06 | Phase 65 | Pending |
| STRESS-07 | Phase 65 | Pending |
| RECOVERY-01 | Phase 66 | Pending |
| RECOVERY-02 | Phase 66 | Pending |
| RECOVERY-03 | Phase 66 | Pending |
| RECOVERY-04 | Phase 66 | Pending |
| RECOVERY-05 | Phase 66 | Pending |
| RECOVERY-06 | Phase 66 | Pending |

**Coverage:**
- v1 requirements: 20 total
- Mapped to phases: 20 ✓
- Unmapped: 0

## Completed Requirements (v1.13)

Requirements completed in previous milestone, preserved for reference.

### P2P RTT Probing (v1.13)

- [x] **RTT-01**: Matchmaker can establish WebRTC probe connection between candidate participants
- [x] **RTT-02**: Probe measures actual P2P RTT between candidates (specified number of pings)
- [x] **RTT-03**: Probe connection is closed after measurement completes
- [x] **RTT-04**: Matchmaker constructor accepts `max_p2p_rtt_ms` threshold parameter
- [x] **RTT-05**: `find_match()` receives measured RTT between candidates
- [x] **RTT-06**: Match is rejected if RTT exceeds configured threshold

### Game Creation (v1.13)

- [x] **GAME-01**: All games created through single path: Matchmaker.find_match() → match → create game
- [x] **GAME-02**: No other code paths create games
- [x] **GAME-03**: Game only exists when all matched participants are assigned
- [x] **GAME-04**: Group reunion flow is bypassed and documented as future matchmaker variant

---
*Requirements defined: 2026-02-03*
*Last updated: 2026-02-03 after Phase 61 complete*
