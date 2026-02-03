# Requirements: Interactive Gym v1.13

**Defined:** 2026-02-03
**Core Value:** Both players in a multiplayer game experience local-feeling responsiveness regardless of network latency, enabling valid research data collection without latency-induced behavioral artifacts.

## v1 Requirements

Requirements for v1.13 Matchmaker Hardening. Each maps to roadmap phases.

### P2P RTT Probing

- [ ] **RTT-01**: Matchmaker can establish WebRTC probe connection between candidate participants
- [x] **RTT-02**: Probe measures actual P2P RTT between candidates (specified number of pings)
- [ ] **RTT-03**: Probe connection is closed after measurement completes
- [ ] **RTT-04**: Matchmaker constructor accepts `max_p2p_rtt_ms` threshold parameter
- [ ] **RTT-05**: `find_match()` receives measured RTT between candidates
- [ ] **RTT-06**: Match is rejected if RTT exceeds configured threshold

### Game Creation

- [ ] **GAME-01**: All games created through single path: Matchmaker.find_match() → match → create game
- [ ] **GAME-02**: No other code paths create games
- [ ] **GAME-03**: Game only exists when all matched participants are assigned
- [ ] **GAME-04**: Group reunion flow is bypassed and documented as future matchmaker variant

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Enhanced Matching

- **MATCH-01**: Wait time relaxation (progressively relax criteria as wait time increases)
- **MATCH-02**: Priority queuing for dropout recovery
- **MATCH-03**: Pre-match validation hook (beyond RTT, e.g., custom compatibility checks)

### Group Reunion

- **REUN-01**: Matchmaker variant that reunites previous groups
- **REUN-02**: Configurable reunion timeout before falling back to FIFO

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Skill-based matchmaking (SBMM) | Game-focused pattern, not research validity |
| Global player pools | Cross-experiment contamination |
| Mid-game backfill | Invalidates experimental conditions |
| Persistent P2P connections during matchmaking | User specified: probe then close |

## Traceability

Which phases cover which requirements. Updated by create-roadmap.

| Requirement | Phase | Status |
|-------------|-------|--------|
| RTT-01 | Phase 57 | Complete |
| RTT-02 | Phase 58 | Complete |
| RTT-03 | Phase 57 | Complete |
| RTT-04 | Phase 59 | Pending |
| RTT-05 | Phase 59 | Pending |
| RTT-06 | Phase 59 | Pending |
| GAME-01 | Phase 60 | Pending |
| GAME-02 | Phase 60 | Pending |
| GAME-03 | Phase 60 | Pending |
| GAME-04 | Phase 60 | Pending |

**Coverage:**
- v1 requirements: 10 total
- Mapped to phases: 10 ✓
- Unmapped: 0

---
*Requirements defined: 2026-02-03*
*Last updated: 2026-02-03 after Phase 58 complete*
