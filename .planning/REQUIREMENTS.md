# Requirements: Interactive Gym v1.20 Pre-Game Countdown

**Defined:** 2026-02-07
**Core Value:** Both players in a multiplayer game experience local-feeling responsiveness regardless of network latency, enabling valid research data collection without latency-induced behavioral artifacts.

## v1 Requirements

Requirements for v1.20 Pre-Game Countdown. Each maps to roadmap phases.

### Countdown

- [x] **CD-01**: 3-second countdown overlay on waiting room screen after match formed
- [x] **CD-02**: "Players found!" message with 3-2-1 countdown visible to all matched players
- [x] **CD-03**: Game start remains synced across all players after countdown completes

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
| Configurable countdown duration | Hardcoded 3s for v1.20; configurability is future work |
| Configurable countdown message | Hardcoded "Players found!" for v1.20 |
| Countdown for single-player | Not needed; countdown is multiplayer-only |
| Countdown skip option | Not needed for research experiments |

## Traceability

Which phases cover which requirements. Updated by create-roadmap.

| Requirement | Phase | Status |
|-------------|-------|--------|
| CD-01 | Phase 80 | Complete |
| CD-02 | Phase 80 | Complete |
| CD-03 | Phase 80 | Complete |

**Coverage:**
- v1 requirements: 3 total
- Mapped to phases: 3
- Unmapped: 0 ✓

---
*Requirements defined: 2026-02-07*
*Last updated: 2026-02-07 after Phase 80 completion*
