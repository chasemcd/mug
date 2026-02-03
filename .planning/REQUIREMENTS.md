# Requirements: Interactive Gym v1.11 Data Export Edge Cases

**Defined:** 2026-02-02
**Core Value:** Both players export identical research data regardless of network conditions, focus loss, or stress scenarios.

## v1.11 Requirements

Requirements for v1.11 Data Export Edge Cases milestone. Each maps to roadmap phases.

### isFocused Column Consistency

- [x] **FOCUS-COL-01**: Both players export isFocused.0 and isFocused.1 columns regardless of whether focus loss occurred
- [x] **FOCUS-COL-02**: isFocused columns contain accurate values (true when focused, false when backgrounded)

### Episode Boundary Row Parity

- [x] **BOUND-01**: Both players export exactly the same number of rows (0 row tolerance)
- [x] **BOUND-02**: Fast-forward processing stops at episode boundary, not after
- [x] **BOUND-03**: `_promoteRemainingAtBoundary()` handles backgrounded player correctly

### Dual-Buffer Stress Handling

- [x] **STRESS-01**: `test_active_input_with_latency[100]` passes without xfail marker
- [x] **STRESS-02**: `test_active_input_with_latency[200]` passes without xfail marker
- [x] **STRESS-03**: `test_active_input_with_packet_loss` passes without xfail marker
- [x] **STRESS-04**: `test_focus_loss_mid_episode_parity` passes without xfail marker
- [x] **STRESS-05**: `test_focus_loss_episode_boundary_parity` passes without xfail marker

### Verification

- [x] **VERIFY-01**: All E2E tests pass with no xfail markers remaining
- [x] **VERIFY-02**: Research data exports from both players are byte-identical (ignoring timestamps)

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
| Row tolerance relaxation | v1.11 targets exact parity (0 tolerance) |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| FOCUS-COL-01 | Phase 48 | Complete |
| FOCUS-COL-02 | Phase 48 | Complete |
| BOUND-01 | Phase 49 | Complete |
| BOUND-02 | Phase 49 | Complete |
| BOUND-03 | Phase 49 | Complete |
| STRESS-01 | Phase 50 | Complete |
| STRESS-02 | Phase 50 | Complete |
| STRESS-03 | Phase 50 | Complete |
| STRESS-04 | Phase 50 | Complete |
| STRESS-05 | Phase 50 | Complete |
| VERIFY-01 | Phase 50 | Complete |
| VERIFY-02 | Phase 50 | Complete |

**Coverage:**
- v1.11 requirements: 12 total
- Mapped to phases: 12 ✓
- Unmapped: 0

---
*Requirements defined: 2026-02-02*
*Last updated: 2026-02-02 after Phase 50 complete (v1.11 milestone complete)*
