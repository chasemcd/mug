# Requirements: Interactive Gym v1.7 Admin Console Improvement

**Defined:** 2026-01-24
**Core Value:** A clean, usable admin console that gives researchers effective experiment monitoring — see what's happening, catch problems, track progress.

## v1.7 Requirements

Requirements for v1.7 Admin Console Improvement milestone. Each maps to roadmap phases.

### Dashboard Overview

- [x] **DASH-01**: Dashboard shows completion rate (X of Y participants completed successfully)
- [x] **DASH-02**: Dashboard shows average session duration
- [x] **DASH-03**: Summary stats visually prominent at top of page

### Session List

- [x] **LIST-01**: Session list shows current episode/round for each active game
- [x] **LIST-02**: Session list shows connection type per session (P2P direct / TURN relay / SocketIO fallback)
- [x] **LIST-03**: Session list shows current latency between peers
- [x] **LIST-04**: Session list shows connection status indicator (healthy / degraded / reconnecting)
- [x] **LIST-05**: Sessions with issues visually distinguished from healthy sessions

### Session Details

- [ ] **DETAIL-01**: Clicking a session opens detailed view
- [ ] **DETAIL-02**: Session detail shows exclusion reason if participant was excluded
- [ ] **DETAIL-03**: Session detail shows disconnection reason if session ended abnormally
- [ ] **DETAIL-04**: Session detail surfaces console errors from that participant

### Layout & Hierarchy

- [ ] **LAYOUT-01**: Clear visual hierarchy: summary at top → session list in middle → details on click
- [ ] **LAYOUT-02**: Information prioritized by importance (stats > active sessions > history)

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Alerts & Notifications

- **ALERT-01**: Real-time alerts when sessions have issues
- **ALERT-02**: Configurable alert thresholds (e.g., latency > 200ms)
- **ALERT-03**: Sound/visual notification for critical issues

### Historical Analysis

- **HIST-01**: View past sessions with same detail level as live
- **HIST-02**: Filter/search sessions by date, status, errors
- **HIST-03**: Export session summaries to CSV

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Participant management (ban, message) | Admin console is monitoring-focused, not intervention |
| Experiment configuration via admin UI | Experiments configured in Python code, not live |
| Real-time intervention (pause/resume games) | Would require significant game state management |
| Multi-admin access control | Single researcher use case, keep auth simple |

## Traceability

Which phases cover which requirements. Updated by create-roadmap.

| Requirement | Phase | Status |
|-------------|-------|--------|
| DASH-01 | Phase 32 | Complete |
| DASH-02 | Phase 32 | Complete |
| DASH-03 | Phase 32 | Complete |
| LIST-01 | Phase 33 | Complete |
| LIST-02 | Phase 33 | Complete |
| LIST-03 | Phase 33 | Complete |
| LIST-04 | Phase 33 | Complete |
| LIST-05 | Phase 33 | Complete |
| DETAIL-01 | Phase 34 | Pending |
| DETAIL-02 | Phase 34 | Pending |
| DETAIL-03 | Phase 34 | Pending |
| DETAIL-04 | Phase 34 | Pending |
| LAYOUT-01 | Phase 35 | Pending |
| LAYOUT-02 | Phase 35 | Pending |

**Coverage:**
- v1.7 requirements: 14 total
- Mapped to phases: 14 ✓
- Unmapped: 0

---
*Requirements defined: 2026-01-24*
*Last updated: 2026-01-25 after Phase 33 complete*
