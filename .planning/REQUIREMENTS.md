# Requirements: Interactive Gym v1.4 Partner Disconnection Handling

**Defined:** 2026-01-22
**Core Value:** Both players in a multiplayer game experience local-feeling responsiveness regardless of network latency, enabling valid research data collection without latency-induced behavioral artifacts.

## v1.4 Requirements

Requirements for v1.4 Partner Disconnection Handling milestone. Each maps to roadmap phases.

### UI Handling

- [ ] **UI-01**: Participant stays on same page when partner disconnects (no redirect)
- [ ] **UI-02**: Game container and HUD hidden when partner disconnection detected
- [ ] **UI-03**: Disconnection message displayed on same page after partner disconnects
- [ ] **UI-04**: Page remains displayed indefinitely (participant closes when done)

### Data Export

- [ ] **DATA-01**: All gameplay data collected before disconnection is exported to server
- [ ] **DATA-02**: Session marked as partial in exported data when partner disconnects
- [ ] **DATA-03**: Disconnection reason included in session metadata
- [ ] **DATA-04**: Disconnected player ID included in session metadata

### Configuration

- [ ] **CFG-01**: Researchers can set custom partner disconnect message via GymScene config
- [ ] **CFG-02**: Default message provided when no custom message configured

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

(None for v1.4)

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Auto-advance to next scene after disconnect | User specified staying on page indefinitely |
| Continue button after disconnect | User specified page stays indefinitely |
| Reconnection attempts after partner leaves | Partner leaving is terminal (different from connection drop) |

## Traceability

Which phases cover which requirements. Updated by create-roadmap.

| Requirement | Phase | Status |
|-------------|-------|--------|
| UI-01 | 23 | Pending |
| UI-02 | 23 | Pending |
| UI-03 | 23 | Pending |
| UI-04 | 23 | Pending |
| DATA-01 | 23 | Pending |
| DATA-02 | 23 | Pending |
| DATA-03 | 23 | Pending |
| DATA-04 | 23 | Pending |
| CFG-01 | 23 | Pending |
| CFG-02 | 23 | Pending |

**Coverage:**
- v1.4 requirements: 10 total
- Mapped to phases: 10
- Unmapped: 0

---
*Requirements defined: 2026-01-22*
*Last updated: 2026-01-22 after initial definition*
