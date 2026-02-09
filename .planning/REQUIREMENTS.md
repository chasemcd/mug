# Requirements: Interactive Gym — v1.24 Test Fix & Hardening

**Defined:** 2026-02-08
**Core Value:** Researchers can configure and deploy multiplayer browser experiments with minimal code — a chained scene config and a Python environment are all that's needed.

## v1 Requirements

Requirements for v1.24 milestone. Each maps to roadmap phases.

### Rename Fix

- [ ] **FIX-01**: All corrupted `Sessocketion` → `Session` identifiers restored in `pyodide_game_coordinator.py`
- [ ] **FIX-02**: All corrupted `sessocketion` → `session` identifiers restored in `probe_coordinator.py`
- [ ] **FIX-03**: All corrupted `transmissocketion` → `transmission` identifiers restored in `server_game_runner.py`
- [ ] **FIX-04**: All corrupted `exclusocketion` → `exclusion` identifiers restored in `pyodide_game_coordinator.py`

### Test Restoration

- [ ] **TEST-01**: All E2E infrastructure tests pass (server starts, contexts connect)
- [ ] **TEST-02**: All E2E multiplayer basic tests pass (connect+complete, matchmaking)
- [ ] **TEST-03**: All E2E data comparison tests pass (basic parity, latency parity, active input, focus loss)
- [ ] **TEST-04**: All E2E network stress tests pass (latency injection, packet loss, jitter, rollback, fast-forward)
- [ ] **TEST-05**: All E2E multi-participant tests pass (simultaneous games, staggered arrival, multi-episode, disconnect, focus timeout)
- [ ] **TEST-06**: All E2E scene isolation tests pass (partner exit on survey)
- [ ] **TEST-07**: All unit tests pass (matchmaker unit + integration — 27 tests)

### Data Parity

- [ ] **DATA-01**: Every test producing episode CSV data runs export parity validation (validate_action_sequences.py --compare)
- [ ] **DATA-02**: Tests that currently skip parity checks are updated to include them
- [ ] **DATA-03**: No test produces episode data without asserting on it

### Examples

- [ ] **EXAM-01**: All example configurations in `interactive_gym/examples/` run end-to-end without errors
- [ ] **EXAM-02**: Example imports and API calls reflect v1.23 renamed modules and methods

### Documentation

- [ ] **DOCS-01**: All documentation files reference correct module paths after v1.23 reorganization
- [ ] **DOCS-02**: All documentation files reference correct API method names after v1.22/v1.23 renames

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Additional Testing

- **TEST-08**: Add new tests for code paths that have zero coverage
- **TEST-09**: Performance benchmarks for latency-sensitive operations

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| New features or capabilities | This milestone is fix + harden only |
| New test infrastructure or frameworks | Use existing pytest + Playwright setup |
| Performance optimization | Focus is correctness, not speed |
| Loosening test criteria | Fix the code, not the tests |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| FIX-01 | Phase 79 | Pending |
| FIX-02 | Phase 79 | Pending |
| FIX-03 | Phase 79 | Pending |
| FIX-04 | Phase 79 | Pending |
| TEST-01 | Phase 80 | Pending |
| TEST-02 | Phase 80 | Pending |
| TEST-03 | Phase 80 | Pending |
| TEST-04 | Phase 80 | Pending |
| TEST-05 | Phase 80 | Pending |
| TEST-06 | Phase 80 | Pending |
| TEST-07 | Phase 80 | Pending |
| DATA-01 | Phase 81 | Pending |
| DATA-02 | Phase 81 | Pending |
| DATA-03 | Phase 81 | Pending |
| EXAM-01 | Phase 82 | Pending |
| EXAM-02 | Phase 82 | Pending |
| DOCS-01 | Phase 82 | Pending |
| DOCS-02 | Phase 82 | Pending |

**Coverage:**
- v1 requirements: 18 total
- Mapped to phases: 18
- Unmapped: 0 ✓

---
*Requirements defined: 2026-02-08*
*Last updated: 2026-02-08 after roadmap creation*
