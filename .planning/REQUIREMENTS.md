# Requirements: Interactive Gym v1.4 Partner Disconnection Handling

**Defined:** 2026-01-22
**Core Value:** Both players in a multiplayer game experience local-feeling responsiveness regardless of network latency, enabling valid research data collection without latency-induced behavioral artifacts.

## v1.4 Requirements

Requirements for v1.4 Partner Disconnection Handling milestone. Each maps to roadmap phases.

### UI Handling

- [x] **UI-01**: Participant stays on same page when partner disconnects (no redirect)
- [x] **UI-02**: Game container and HUD hidden when partner disconnection detected
- [x] **UI-03**: Disconnection message displayed on same page after partner disconnects
- [x] **UI-04**: Page remains displayed indefinitely (participant closes when done)

### Data Export

- [x] **DATA-01**: All gameplay data collected before disconnection is exported to server
- [x] **DATA-02**: Session marked as partial in exported data when partner disconnects
- [x] **DATA-03**: Disconnection reason included in session metadata
- [x] **DATA-04**: Disconnected player ID included in session metadata

### Configuration

- [x] **CFG-01**: Researchers can set custom partner disconnect message via GymScene config
- [x] **CFG-02**: Default message provided when no custom message configured

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
| UI-01 | 23 | Complete |
| UI-02 | 23 | Complete |
| UI-03 | 23 | Complete |
| UI-04 | 23 | Complete |
| DATA-01 | 23 | Complete |
| DATA-02 | 23 | Complete |
| DATA-03 | 23 | Complete |
| DATA-04 | 23 | Complete |
| CFG-01 | 23 | Complete |
| CFG-02 | 23 | Complete |

**Coverage:**
- v1.4 requirements: 10 total
- Mapped to phases: 10
- Unmapped: 0

---
*Requirements defined: 2026-01-22*
*Last updated: 2026-01-22 after Phase 23 complete*
