# Requirements: Interactive Gym v1.9 Data Parity Testing

**Defined:** 2026-01-31
**Core Value:** Validate that both players export identical game state data under controlled network conditions, ensuring v1.8 data export parity works in practice.

## v1.9 Requirements

Requirements for v1.9 Data Parity Testing milestone. Each maps to roadmap phases.

### Test Infrastructure

- [x] **INFRA-01**: Playwright test suite can launch two browser contexts for multiplayer game
- [x] **INFRA-02**: Test lifecycle manages Flask server startup and teardown

### Network Condition Tests

- [x] **NET-01**: Test applies fixed latency (100ms, 200ms) via Chrome DevTools Protocol (500ms causes WebRTC signaling timeouts)
- [x] **NET-02**: Test simulates packet loss to trigger rollback scenarios
- [x] **NET-03**: Test triggers tab unfocus/refocus to exercise fast-forward path
- [x] **NET-04**: Test applies asymmetric latency (different delays for each player)
- [x] **NET-05**: Test applies jitter (variable latency) during gameplay

### Data Comparison

- [x] **CMP-01**: Test collects export files from both players after episode ends
- [x] **CMP-02**: Test invokes `validate_action_sequences.py --compare` on collected exports
- [x] **CMP-03**: Test reports pass/fail based on comparison result (exit code)

### Documentation

- [ ] **DOC-01**: Manual test protocol documents step-by-step researcher verification process

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Test Infrastructure

- **INFRA-03**: Headless mode for CI/CD integration
- **INFRA-04**: Screenshot capture on test failure

### Data Comparison

- **CMP-04**: In-browser comparison before server export
- **CMP-05**: Detailed divergence reports (columns, frames)

### Documentation

- **DOC-02**: Setup instructions for running test suite
- **DOC-03**: CI integration guide (GitHub Actions)
- **DOC-04**: Test case documentation with expected outcomes

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Automated CI pipeline | Manual test runs sufficient for v1.9 |
| Performance benchmarking | Focus is parity validation, not latency measurement |
| Mobile browser testing | Desktop Chrome/Firefox only |
| Cross-browser matrix | Playwright on Chromium sufficient for validation |

## Traceability

Which phases cover which requirements. Updated by create-roadmap.

| Requirement | Phase | Status |
|-------------|-------|--------|
| INFRA-01 | Phase 40 | Complete |
| INFRA-02 | Phase 40 | Complete |
| NET-01 | Phase 41 | Complete |
| NET-04 | Phase 41 | Complete |
| NET-05 | Phase 41 | Complete |
| NET-02 | Phase 42 | Complete |
| NET-03 | Phase 42 | Complete |
| CMP-01 | Phase 43 | Complete |
| CMP-02 | Phase 43 | Complete |
| CMP-03 | Phase 43 | Complete |
| DOC-01 | Phase 44 | Pending |

**Coverage:**
- v1.9 requirements: 11 total
- Mapped to phases: 11 ✓
- Unmapped: 0

---
*Requirements defined: 2026-01-31*
*Last updated: 2026-01-31 after Phase 43 execution*
