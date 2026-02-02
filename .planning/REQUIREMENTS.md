# Requirements: Interactive Gym v1.10 E2E Test Fix

**Defined:** 2026-02-02
**Core Value:** All E2E tests pass in headed mode, validating data parity under network stress conditions.

## v1.10 Requirements

Requirements for v1.10 E2E Test Fix milestone. Each maps to roadmap phases.

### Episode Completion Fix

- [x] **EPFIX-01**: Diagnose why game initializes but frames don't advance in E2E tests
- [x] **EPFIX-02**: Fix root cause so games progress through frames to episode completion
- [x] **EPFIX-03**: Episode completion detected within test timeout (180s)

### Row Count Synchronization

- [ ] **SYNC-01**: Both players export identical frame counts regardless of network latency
- [ ] **SYNC-02**: Synchronized termination frame calculated as minimum of local/remote detection
- [ ] **SYNC-03**: Frame storage stops at synced termination frame
- [ ] **SYNC-04**: Export filters frames to only include up to termination frame

### Test Validation

- [ ] **TEST-01**: `test_infrastructure.py` smoke tests pass
- [ ] **TEST-02**: `test_multiplayer_basic.py` matchmaking and episode tests pass
- [ ] **TEST-03**: `test_latency_injection.py` all latency scenarios pass
- [ ] **TEST-04**: `test_network_disruption.py` packet loss and focus tests pass
- [ ] **TEST-05**: `test_data_comparison.py` parity validation tests pass

### Focus Loss Data Accuracy

- [ ] **FOCUS-01**: Data parity maintained when one client loses focus mid-episode (opens new tab during gameplay)
- [ ] **FOCUS-02**: Data parity maintained when one client loses focus at episode boundary (opens new tab as episode ends)

## v2 Requirements

Deferred to future release.

### Test Infrastructure

- **CI-01**: Headless mode for CI/CD integration (requires WebRTC workaround)
- **CI-02**: GitHub Actions workflow for automated test runs
- **CI-03**: Screenshot/video capture on test failure

### Extended Coverage

- **COV-01**: Multi-episode test scenarios
- **COV-02**: Stress testing with sustained high latency
- **COV-03**: Connection recovery scenarios

## Out of Scope

| Feature | Reason |
|---------|--------|
| Headless automation | WebRTC requires headed mode; defer to v2 |
| Cross-browser testing | Chromium-only sufficient for validation |
| Performance benchmarks | Focus is correctness, not speed |
| New test scenarios | Fix existing tests first |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| EPFIX-01 | Phase 45 | Complete |
| EPFIX-02 | Phase 45 | Complete |
| EPFIX-03 | Phase 45 | Complete |
| SYNC-01 | Phase 46 | Implemented (pending verification) |
| SYNC-02 | Phase 46 | Implemented (pending verification) |
| SYNC-03 | Phase 46 | Implemented (pending verification) |
| SYNC-04 | Phase 46 | Implemented (pending verification) |
| TEST-01 | Phase 46 | Pending |
| TEST-02 | Phase 46 | Pending |
| TEST-03 | Phase 46 | Pending |
| TEST-04 | Phase 46 | Pending |
| TEST-05 | Phase 46 | Pending |
| FOCUS-01 | Phase 47 | Pending |
| FOCUS-02 | Phase 47 | Pending |

**Coverage:**
- v1.10 requirements: 14 total
- Mapped to phases: 14 ✓
- Unmapped: 0

---
*Requirements defined: 2026-02-02*
*Last updated: 2026-02-02 after Phase 45 completion*
