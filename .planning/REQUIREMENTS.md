# Requirements: Interactive Gym v1.12 — Waiting Room Overhaul

**Defined:** 2026-02-02
**Core Value:** Both players in a multiplayer game experience local-feeling responsiveness regardless of network latency, enabling valid research data collection without latency-induced behavioral artifacts.

## v1 Requirements

Requirements for v1.12 release. Each maps to roadmap phases.

### Bug Fixes

- [x] **BUG-01**: Stale game manager cleanup prevents old games from capturing new participants
- [x] **BUG-02**: Participant routing never sends players to games in progress
- [x] **BUG-03**: Game lifecycle cleanup runs on all exit paths (normal and abnormal termination)
- [x] **BUG-04**: Client receives error event when waiting room state is invalid

### Session Lifecycle

- [ ] **SESS-01**: Session has explicit states (WAITING → MATCHED → VALIDATING → PLAYING → ENDED)
- [ ] **SESS-02**: Session object is destroyed (not reused) when game ends
- [x] **SESS-03**: Cleanup methods are idempotent (safe to call multiple times)

### Matchmaker API

- [ ] **MATCH-01**: Matchmaker abstract base class with `find_match()` method
- [ ] **MATCH-02**: `find_match()` receives arriving participant, waiting list, and group size
- [ ] **MATCH-03**: `find_match()` returns list of matched participants or None to continue waiting
- [ ] **MATCH-04**: FIFOMatchmaker default implementation (current behavior)
- [ ] **MATCH-05**: Matchmaker configurable per-scene via experiment config

### Data & Observability

- [ ] **DATA-01**: Assignment logging records match decisions (who matched with whom, timestamp)
- [ ] **DATA-02**: RTT to server exposed in ParticipantData for matchmaker use

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Matchmaker API

- **MATCH-06**: `on_timeout()` hook for custom timeout behavior
- **MATCH-07**: `on_dropout()` hook for handling waiting room disconnects
- **MATCH-08**: Custom attribute matching (pass arbitrary key-value pairs)
- **MATCH-09**: Prior partners list exposed for blocking repeat matches

### Session Lifecycle

- **SESS-04**: State machine library integration (`python-statemachine`)
- **SESS-05**: Participant state tracker as single source of truth

### Data & Observability

- **DATA-03**: Historical performance access (prior games, scores, partners)

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Skill-based matchmaking (SBMM/MMR) | Game industry pattern; research needs explicit criteria control |
| Global player pools | Cross-experiment contamination; each experiment needs isolation |
| Mid-game backfill | Invalidates experimental conditions |
| Complex rule DSLs | Over-engineered; researchers already know Python |
| N-player support (>2) | Deferred to future milestone (currently 2-player only) |

## Traceability

Which phases cover which requirements. Updated by create-roadmap.

| Requirement | Phase | Status |
|-------------|-------|--------|
| BUG-01 | Phase 52 | Complete |
| BUG-02 | Phase 52 | Complete |
| BUG-03 | Phase 52 | Complete |
| BUG-04 | Phase 51 | Complete |
| SESS-01 | Phase 53 | Pending |
| SESS-02 | Phase 53 | Pending |
| SESS-03 | Phase 52 | Complete |
| MATCH-01 | Phase 55 | Pending |
| MATCH-02 | Phase 55 | Pending |
| MATCH-03 | Phase 55 | Pending |
| MATCH-04 | Phase 55 | Pending |
| MATCH-05 | Phase 55 | Pending |
| DATA-01 | Phase 56 | Pending |
| DATA-02 | Phase 56 | Pending |

**Coverage:**
- v1 requirements: 14 total
- Mapped to phases: 14 ✓
- Unmapped: 0

---
*Requirements defined: 2026-02-02*
*Last updated: 2026-02-02 after phase 52 complete*
