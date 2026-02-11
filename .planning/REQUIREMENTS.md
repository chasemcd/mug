# Requirements: Multi-User Gymnasium (MUG)

**Defined:** 2026-02-11
**Core Value:** Researchers can configure and deploy multiplayer browser experiments with minimal code

## v1.27 Requirements

Requirements for principled rollback resource management -- replacing arbitrary hardcoded limits with confirmedFrame-based pruning.

### Snapshot Management

- [ ] **SNAP-01**: Snapshot pruning is tied to `confirmedFrame` -- all snapshots before the anchor snapshot (highest snapshot <= `confirmedFrame`) are deleted
- [ ] **SNAP-02**: `maxSnapshots` parameter is removed -- snapshot count adapts to network conditions (more snapshots when inputs are unconfirmed, fewer when confirmed)
- [ ] **SNAP-03**: The anchor snapshot (one snapshot at or before `confirmedFrame`) is always retained as a rollback recovery point

### Input Buffer Management

- [ ] **IBUF-01**: Input buffer pruning is tied to `confirmedFrame` -- entries at or before `confirmedFrame` are pruned (replacing hardcoded `frameNumber - 60` threshold)
- [ ] **IBUF-02**: The hardcoded `pruneThreshold` of `frameNumber - 60` is removed
- [ ] **IBUF-03**: `inputBufferMaxSize` (120) is removed or made a safety-only cap, not the primary pruning mechanism

### Configuration

- [ ] **CONF-01**: `snapshot_interval` parameter added to `GymScene.multiplayer()` builder method (default: 5)
- [ ] **CONF-02**: JS constructor reads `config.snapshot_interval` with fallback to 5

### Verification

- [ ] **VER-01**: All 52 existing tests pass after changes (27 unit + 25 E2E)
- [ ] **VER-02**: Rollback correctness preserved -- multiplayer E2E tests with rollback scenarios still pass

## Out of Scope

| Feature | Reason |
|---------|--------|
| Adaptive snapshotInterval based on network | Over-engineering; fixed interval with config override is sufficient |
| Delta-compressed snapshots | Separate optimization concern, different milestone |
| Snapshot format changes | Current JSON serialization works; performance optimization is separate |
| New rollback tests | Testing existing rollback behavior, not adding new test scenarios |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| SNAP-01 | Phase 87 | Pending |
| SNAP-02 | Phase 87 | Pending |
| SNAP-03 | Phase 87 | Pending |
| IBUF-01 | Phase 87 | Pending |
| IBUF-02 | Phase 87 | Pending |
| IBUF-03 | Phase 87 | Pending |
| CONF-01 | Phase 87 | Pending |
| CONF-02 | Phase 87 | Pending |
| VER-01 | Phase 88 | Pending |
| VER-02 | Phase 88 | Pending |

**Coverage:**
- v1.27 requirements: 10 total
- Mapped to phases: 10
- Unmapped: 0

---
*Requirements defined: 2026-02-11*
*Last updated: 2026-02-11 -- roadmap created, traceability complete*
