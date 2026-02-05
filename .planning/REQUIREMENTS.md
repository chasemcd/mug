# Requirements: Interactive Gym v1.17

**Defined:** 2026-02-05
**Core Value:** Both players in a multiplayer game experience local-feeling responsiveness regardless of network latency, enabling valid research data collection without latency-induced behavioral artifacts.

## v1 Requirements

Requirements for v1.17 E2E Test Reliability. Each maps to roadmap phases.

### Test Audit

- [ ] **AUDIT-01**: Full E2E test suite executed and all failures cataloged
- [ ] **AUDIT-02**: Each failure root-caused as test infrastructure, fixture issue, or production bug

### Test Infrastructure

- [ ] **INFRA-01**: Test fixtures updated for Worker-based Pyodide (setup, teardown, timeouts)
- [ ] **INFRA-02**: Playwright selectors/locators updated for any Worker migration UI changes
- [ ] **INFRA-03**: Test waits and timeouts adjusted for Worker async patterns

### Production Bug Fixes

- [ ] **PROD-01**: Production code bugs revealed by E2E tests are fixed (postMessage, serialization, Worker lifecycle)
- [ ] **PROD-02**: Pre-existing functionality regressions from Worker migration are fixed

### Stability Validation

- [ ] **STAB-01**: All multi-participant tests pass (STRESS-01 through STRESS-07)
- [ ] **STAB-02**: All single-participant tests pass
- [ ] **STAB-03**: Zero xfail markers in test suite
- [ ] **STAB-04**: Zero skip markers in test suite
- [ ] **STAB-05**: Full test suite passes 3 consecutive runs with zero flakiness

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Performance & CI

- **PERF-01**: Performance benchmarking of Worker step latency vs pre-Worker baseline
- **CI-01**: E2E tests integrated into CI pipeline

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| New E2E test creation | v1.17 fixes existing tests, not writing new ones |
| Test parallelization | Optimization — not needed for reliability goal |
| Visual regression testing | Not part of current test suite |
| Mobile browser testing | Browser-only testing scope (Chrome/Chromium) |

## Traceability

Which phases cover which requirements. Updated by create-roadmap.

| Requirement | Phase | Status |
|-------------|-------|--------|
| AUDIT-01 | - | Pending |
| AUDIT-02 | - | Pending |
| INFRA-01 | - | Pending |
| INFRA-02 | - | Pending |
| INFRA-03 | - | Pending |
| PROD-01 | - | Pending |
| PROD-02 | - | Pending |
| STAB-01 | - | Pending |
| STAB-02 | - | Pending |
| STAB-03 | - | Pending |
| STAB-04 | - | Pending |
| STAB-05 | - | Pending |

**Coverage:**
- v1 requirements: 12 total
- Mapped to phases: 0
- Unmapped: 12 ⚠️

---
*Requirements defined: 2026-02-05*
*Last updated: 2026-02-05 after initial definition*
