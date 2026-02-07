# Requirements: Interactive Gym v1.19 P2P Lifecycle Cleanup

**Defined:** 2026-02-07
**Core Value:** Both players in a multiplayer game experience local-feeling responsiveness regardless of network latency, enabling valid research data collection without latency-induced behavioral artifacts.

## v1 Requirements

Requirements for v1.19 P2P Lifecycle Cleanup. Each maps to roadmap phases.

### P2P Lifecycle

- [x] **P2P-01**: P2P/WebRTC connections are closed when a GymScene exits (via scene transition or advance_scene)
- [x] **P2P-02**: Partner-disconnected overlay is not shown on non-GymScene scenes (surveys, instructions, end screens)
- [ ] **P2P-03**: Server tracks group membership (which participants were paired together) across scene transitions
- [ ] **P2P-04**: Custom matchmakers can query group history to re-pair previous partners in future GymScenes

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### GGPO Parity

- **GGPO-01**: Fix content divergence under packet loss + active inputs (increase snapshot coverage + eager rollback)

### CI Integration

- **CI-01**: E2E tests run in CI/CD pipeline (headless mode or headed with Xvfb)
- **CI-02**: Test results reported in PR checks

### Full Off-Main-Thread

- **WORKER-01**: Move per-frame `runPythonAsync()` to a Web Worker
- **WORKER-02**: Batch rollback operations in single Worker round-trip

### Enhanced Matching (from v1.13)

- **MATCH-01**: Wait time relaxation (progressively relax criteria as wait time increases)
- **MATCH-02**: Priority queuing for dropout recovery
- **MATCH-03**: Pre-match validation hook (beyond RTT, e.g., custom compatibility checks)

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Pyodide Web Worker migration | Pre-loading solves disconnect issue; Worker deferred until per-frame blocking is a problem |
| New E2E test coverage | Existing suite is stable; new tests are a separate milestone |
| CI/CD pipeline setup | Test suite is CI-ready but pipeline configuration is separate work |
| GGPO parity fix | Documented in backlog; requires dedicated milestone for snapshot/rollback changes |
| P2P reconnection changes | Current reconnection logic stays as-is for this milestone |

## Traceability

Which phases cover which requirements. Updated by create-roadmap.

| Requirement | Phase | Status |
|-------------|-------|--------|
| P2P-01 | Phase 77 | Complete |
| P2P-02 | Phase 77 | Complete |
| P2P-03 | Phase 78 | Pending |
| P2P-04 | Phase 78 | Pending |

**Coverage:**
- v1 requirements: 4 total
- Mapped to phases: 4
- Unmapped: 0 ✓

---
*Requirements defined: 2026-02-07*
*Last updated: 2026-02-07 after Phase 77 complete*
