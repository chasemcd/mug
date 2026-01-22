# Requirements: Interactive Gym v1.3 P2P Connection Validation

**Defined:** 2026-01-21
**Core Value:** Both players in a multiplayer game experience local-feeling responsiveness regardless of network latency, enabling valid research data collection without latency-induced behavioral artifacts.

## v1.3 Requirements

Requirements for v1.3 P2P Connection Validation milestone. Each maps to roadmap phases.

### Waiting Room Validation

- [x] **WAIT-01**: P2P connection must be validated before experiment starts
- [x] **WAIT-02**: Failed P2P pairs re-enter matchmaking pool to find new partners
- [x] **WAIT-03**: Participants see clear status messaging during P2P validation

### Per-Round Health

- [ ] **ROUND-01**: DataChannel connection verified before each round begins
- [ ] **ROUND-02**: Round start blocked until P2P connection confirmed healthy

### Mid-Game Reconnection

- [x] **RECON-01**: System detects when P2P DataChannel connection drops
- [x] **RECON-02**: Gameplay pauses immediately for both clients on connection drop
- [x] **RECON-03**: Both players see reconnecting overlay during reconnection attempts
- [x] **RECON-04**: Reconnection timeout is configurable by researcher
- [x] **RECON-05**: Gameplay resumes if reconnection succeeds within timeout
- [x] **RECON-06**: Game ends cleanly for both players if reconnection times out

### Connection Logging

- [x] **LOG-01**: Disconnection events logged with timestamp and detecting peer
- [x] **LOG-02**: Reconnection attempts logged with duration and outcome
- [x] **LOG-03**: Total pause duration per session recorded in data export

### Latency Monitoring

- [ ] **LAT-01**: P2P latency measured periodically during gameplay (non-blocking)
- [ ] **LAT-02**: Latency stats exported: min, median, mean, max

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Latency

- **LAT-03**: Configurable latency threshold with exclusion (not just logging)

### Reconnection

- **RECON-07**: Automatic reconnection retry count limit before giving up

### Waiting Room

- **WAIT-04**: Connection quality pre-check (latency threshold) before matchmaking completes

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Latency-based exclusion | v1.3 focuses on data collection; exclusion deferred to v2 |
| Adaptive input delay based on RTT | Deferred to future milestone |
| N-player reconnection handling | Current scope is 2-player only |

## Traceability

Which phases cover which requirements.

| Requirement | Phase | Status |
|-------------|-------|--------|
| WAIT-01 | Phase 19 | Complete |
| WAIT-02 | Phase 19 | Complete |
| WAIT-03 | Phase 19 | Complete |
| ROUND-01 | Phase 21 | Pending |
| ROUND-02 | Phase 21 | Pending |
| RECON-01 | Phase 20 | Complete |
| RECON-02 | Phase 20 | Complete |
| RECON-03 | Phase 20 | Complete |
| RECON-04 | Phase 20 | Complete |
| RECON-05 | Phase 20 | Complete |
| RECON-06 | Phase 20 | Complete |
| LOG-01 | Phase 20 | Complete |
| LOG-02 | Phase 20 | Complete |
| LOG-03 | Phase 20 | Complete |
| LAT-01 | Phase 22 | Pending |
| LAT-02 | Phase 22 | Pending |

**Coverage:**
- v1.3 requirements: 16 total
- Mapped to phases: 16 ✓
- Unmapped: 0

---
*Requirements defined: 2026-01-21*
*Last updated: 2026-01-21 after roadmap created*
