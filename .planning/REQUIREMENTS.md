# Requirements: Interactive Gym v1.6 Input Latency Diagnosis & Fix

**Defined:** 2026-01-23
**Core Value:** Both players in a multiplayer game experience local-feeling responsiveness regardless of network latency, enabling valid research data collection without latency-induced behavioral artifacts.

## v1.6 Requirements

Requirements for v1.6 Input Latency Diagnosis & Fix milestone. Each maps to roadmap phases.

### Diagnosis Infrastructure

- [ ] **DIAG-01**: Timestamp captured at keypress event (performance.now())
- [ ] **DIAG-02**: Timestamp captured when action enters input queue
- [ ] **DIAG-03**: Timestamp captured when Pyodide env.step() called
- [ ] **DIAG-04**: Timestamp captured when env.step() returns
- [ ] **DIAG-05**: Timestamp captured when render update begins
- [ ] **DIAG-06**: Timestamp captured when render update completes
- [ ] **DIAG-07**: Per-input latency breakdown computed (queue time, step time, render time)

### Root Cause Fix

- [ ] **FIX-01**: Local input latency consistently under 100ms (keypress to render)
- [ ] **FIX-02**: Fix validated in both single-player and multiplayer modes
- [ ] **FIX-03**: Fix validated specifically in Overcooked environment

### Validation & Telemetry

- [ ] **TELEM-01**: Input latency metrics included in session data export
- [ ] **TELEM-02**: Min/max/mean/median latency stats computed per session
- [ ] **TELEM-03**: Latency outliers (>100ms) flagged and counted
- [ ] **TELEM-04**: Latency breakdown by pipeline stage available for research analysis

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

(None for v1.6)

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Network latency optimization | This milestone is about local lag, not P2P latency |
| Visual rollback smoothing | Separate issue, deferred to future milestone |
| Real-time latency HUD | Telemetry is for export, not live display |
| Adaptive input delay | Deferred to future milestone |

## Traceability

Which phases cover which requirements. Updated by create-roadmap.

| Requirement | Phase | Status |
|-------------|-------|--------|
| DIAG-01 | Phase 28 | Pending |
| DIAG-02 | Phase 28 | Pending |
| DIAG-03 | Phase 28 | Pending |
| DIAG-04 | Phase 28 | Pending |
| DIAG-05 | Phase 28 | Pending |
| DIAG-06 | Phase 28 | Pending |
| DIAG-07 | Phase 28 | Pending |
| FIX-01 | Phase 30 | Pending |
| FIX-02 | Phase 30 | Pending |
| FIX-03 | Phase 30 | Pending |
| TELEM-01 | Phase 31 | Pending |
| TELEM-02 | Phase 31 | Pending |
| TELEM-03 | Phase 31 | Pending |
| TELEM-04 | Phase 31 | Pending |

**Coverage:**
- v1.6 requirements: 14 total
- Mapped to phases: 14
- Unmapped: 0 ✓

---
*Requirements defined: 2026-01-23*
*Last updated: 2026-01-23 after roadmap creation*
