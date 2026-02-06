# Requirements: Interactive Gym v1.16 Pyodide Pre-loading

**Defined:** 2026-02-06
**Core Value:** Both players in a multiplayer game experience local-feeling responsiveness regardless of network latency, enabling valid research data collection without latency-induced behavioral artifacts.

## v1 Requirements

Requirements for v1.16 Pyodide Pre-loading. Each maps to roadmap phases.

### Early Pyodide Initialization

- [ ] **INIT-01**: System detects Pyodide-requiring scenes from experiment config during compatibility check
- [ ] **INIT-02**: System starts `loadPyodide()` and package installation during compatibility check screen
- [ ] **INIT-03**: Participant sees loading progress indicator during Pyodide initialization
- [ ] **INIT-04**: Participant cannot advance past compatibility check until Pyodide is fully loaded

### Shared Pyodide Instance

- [ ] **SHARED-01**: `RemoteGame.initialize()` reuses pre-loaded Pyodide instance (skips `loadPyodide()` if already loaded)
- [ ] **SHARED-02**: `MultiplayerPyodideGame` reuses pre-loaded Pyodide instance (skips `loadPyodide()` if already loaded)

### Server-Side Init Grace

- [ ] **GRACE-01**: Server tolerates missed pings during Pyodide loading phase (does not disconnect client)
- [ ] **GRACE-02**: Client signals loading state to server so server knows to extend grace
- [ ] **GRACE-03**: Normal ping checking resumes after client signals loading complete

### Testing / Validation

- [ ] **TEST-01**: Stagger delay removed from multi-participant E2E tests
- [ ] **TEST-02**: All E2E tests pass with 0.5s stagger (near-simultaneous game starts)
- [ ] **TEST-03**: Socket.IO connections remain stable during concurrent game starts (no false disconnects)
- [ ] **TEST-04**: No performance regression for game loop execution (per-frame timing unchanged)
- [ ] **TEST-05**: All existing E2E tests pass (no regressions from pre-loading changes)

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Backward Compatibility

- **COMPAT-01**: Load Pyodide on demand if pre-load didn't happen (fallback path)

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
| Web Worker for per-frame Python execution | Pre-loading solves disconnect issue; per-frame blocking (10-100ms) is within tolerance |
| SharedArrayBuffer for sub-ms latency | Not needed at current frame rates |
| Hot reload of environment code | Over-engineering for research use case |
| Multi-Worker support | One Pyodide instance per page is sufficient |

## Traceability

Which phases cover which requirements. Updated by create-roadmap.

| Requirement | Phase | Status |
|-------------|-------|--------|
| INIT-01 | — | Pending |
| INIT-02 | — | Pending |
| INIT-03 | — | Pending |
| INIT-04 | — | Pending |
| SHARED-01 | — | Pending |
| SHARED-02 | — | Pending |
| GRACE-01 | — | Pending |
| GRACE-02 | — | Pending |
| GRACE-03 | — | Pending |
| TEST-01 | — | Pending |
| TEST-02 | — | Pending |
| TEST-03 | — | Pending |
| TEST-04 | — | Pending |
| TEST-05 | — | Pending |

**Coverage:**
- v1 requirements: 14 total
- Mapped to phases: 0
- Unmapped: 14 (awaiting roadmap creation)

---
*Requirements defined: 2026-02-06*
*Last updated: 2026-02-06 after initial definition*
