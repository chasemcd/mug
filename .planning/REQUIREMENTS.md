# Requirements: Interactive Gym v1.18 Loading UX & Cleanup

**Defined:** 2026-02-07
**Core Value:** Both players in a multiplayer game experience local-feeling responsiveness regardless of network latency, enabling valid research data collection without latency-induced behavioral artifacts.

## v1 Requirements

Requirements for v1.18 Loading UX & Cleanup. Each maps to roadmap phases.

### Loading UX

- [x] **LOAD-01**: Participant sees a single loading screen during pre-game setup (no separate Pyodide spinner)
- [x] **LOAD-02**: Loading screen gates advancement on both compatibility check AND Pyodide being ready
- [x] **LOAD-03**: Pyodide loading timeout is configurable via experiment config (default 60s)
- [x] **LOAD-04**: If Pyodide fails to load or times out, participant sees a clear error page (not a hang or blank screen)

### Test Cleanup

- [ ] **CLEAN-01**: Orphaned `flask_server_multi_episode` fixture removed from `tests/conftest.py`
- [ ] **CLEAN-02**: Unused `run_full_episode_flow` import removed from `test_network_disruption.py`
- [ ] **CLEAN-03**: Duplicate `run_full_episode_flow` consolidated into `tests/fixtures/game_helpers.py` (single source of truth)
- [ ] **CLEAN-04**: v1.14 Phases 65-66 marked complete in ROADMAP.md (work was done, roadmap not updated)

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

## Traceability

Which phases cover which requirements. Updated by create-roadmap.

| Requirement | Phase | Status |
|-------------|-------|--------|
| LOAD-01 | Phase 75 | Complete |
| LOAD-02 | Phase 75 | Complete |
| LOAD-03 | Phase 75 | Complete |
| LOAD-04 | Phase 75 | Complete |
| CLEAN-01 | Phase 76 | Pending |
| CLEAN-02 | Phase 76 | Pending |
| CLEAN-03 | Phase 76 | Pending |
| CLEAN-04 | Phase 76 | Pending |

**Coverage:**
- v1 requirements: 8 total
- Mapped to phases: 8
- Unmapped: 0 ✓

---
*Requirements defined: 2026-02-07*
*Last updated: 2026-02-06 after Phase 75 complete (LOAD-01 through LOAD-04 verified)*
