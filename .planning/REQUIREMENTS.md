# Requirements: Interactive Gym v1.17 E2E Test Reliability

**Defined:** 2026-02-06
**Core Value:** Both players in a multiplayer game experience local-feeling responsiveness regardless of network latency, enabling valid research data collection without latency-induced behavioral artifacts.

## v1 Requirements

Requirements for v1.17 E2E Test Reliability. Each maps to roadmap phases.

### Test Infrastructure

- [x] **INFRA-01**: Server startup/teardown between test suites completes reliably (no stale processes or port conflicts)
- [x] **INFRA-02**: Page.goto navigation succeeds consistently (no 30s timeout failures between tests)
- [x] **INFRA-03**: Test fixtures properly clean up browser contexts, server processes, and temporary files

### Test Performance

- [x] **PERF-01**: Root cause identified for `test_episode_completion_under_fixed_latency[chromium-200]` timeout
- [x] **PERF-02**: 200ms latency test completes within its timeout after root cause fix

### Network Condition Tests

- [x] **NET-01**: All latency injection tests pass (100ms fixed, 200ms fixed, asymmetric, jitter, active input)
- [x] **NET-02**: All network disruption tests pass (packet loss, reconnection scenarios)

### Regression Suite

- [x] **REG-01**: All data comparison tests pass consistently (5/5)
- [x] **REG-02**: All multiplayer basic tests pass
- [x] **REG-03**: All multi-participant tests pass with 0.5s stagger
- [x] **REG-04**: All focus loss tests pass

### Stability Validation

- [x] **STAB-01**: Full E2E test suite passes with zero failures (24 tests, 23 passed + 1 xfail for documented GGPO limitation)
- [x] **STAB-02**: No tolerance hacks or known-flaky annotations in test suite (one xfail for genuine GGPO architectural limitation — see .planning/backlog/GGPO-PARITY.md)

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

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
| New test coverage (v1.14 Phases 65-66) | Separate milestone — v1.17 fixes existing tests, not new ones |
| Headless mode support | WebRTC requires headed Chromium; headless is a CI concern |
| Test parallelization | Current sequential execution is fine for reliability |
| Web Worker for per-frame Python | Pre-loading solves disconnect issue; deferred to future |

## Traceability

Which phases cover which requirements. Updated by create-roadmap.

| Requirement | Phase | Status |
|-------------|-------|--------|
| INFRA-01 | Phase 71 | Complete |
| INFRA-02 | Phase 71 | Complete |
| INFRA-03 | Phase 71 | Complete |
| PERF-01 | Phase 72 | Complete |
| PERF-02 | Phase 72 | Complete |
| NET-01 | Phase 73 | Complete |
| NET-02 | Phase 73 | Complete |
| REG-01 | Phase 73 | Complete |
| REG-02 | Phase 73 | Complete |
| REG-03 | Phase 73 | Complete |
| REG-04 | Phase 73 | Complete |
| STAB-01 | Phase 74 | Complete |
| STAB-02 | Phase 74 | Complete |

**Coverage:**
- v1 requirements: 13 total
- Mapped to phases: 13
- Unmapped: 0

---
*Requirements defined: 2026-02-06*
*Last updated: 2026-02-06 after Phase 74 complete (STAB-01/STAB-02 with documented GGPO xfail)*
