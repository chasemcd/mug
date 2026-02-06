# Requirements: Interactive Gym v1.16 Pyodide Pre-loading

**Defined:** 2026-02-06
**Core Value:** Both players in a multiplayer game experience local-feeling responsiveness regardless of network latency, enabling valid research data collection without latency-induced behavioral artifacts.

## v1 Requirements

Requirements for v1.16 Pyodide Pre-loading. Each maps to roadmap phases.

### Early Pyodide Initialization

- [x] **INIT-01**: System detects Pyodide-requiring scenes from experiment config during compatibility check
- [x] **INIT-02**: System starts `loadPyodide()` and package installation during compatibility check screen
- [x] **INIT-03**: Participant sees loading progress indicator during Pyodide initialization
- [x] **INIT-04**: Participant cannot advance past compatibility check until Pyodide is fully loaded

### Shared Pyodide Instance

- [x] **SHARED-01**: `RemoteGame.initialize()` reuses pre-loaded Pyodide instance (skips `loadPyodide()` if already loaded)
- [x] **SHARED-02**: `MultiplayerPyodideGame` reuses pre-loaded Pyodide instance (skips `loadPyodide()` if already loaded)

### Server-Side Init Grace

- [x] **GRACE-01**: Server tolerates missed pings during Pyodide loading phase (does not disconnect client)
- [x] **GRACE-02**: Client signals loading state to server so server knows to extend grace
- [x] **GRACE-03**: Normal ping checking resumes after client signals loading complete

### Testing / Validation

- [x] **TEST-01**: Stagger delay removed from multi-participant E2E tests
- [x] **TEST-02**: All E2E tests pass with 0.5s stagger (near-simultaneous game starts)
- [x] **TEST-03**: Socket.IO connections remain stable during concurrent game starts (no false disconnects)
- [x] **TEST-04**: No performance regression for game loop execution (per-frame timing unchanged)
- [x] **TEST-05**: All existing E2E tests pass (no regressions from pre-loading changes)

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
| INIT-01 | Phase 67 | Complete |
| INIT-02 | Phase 67 | Complete |
| INIT-03 | Phase 67 | Complete |
| INIT-04 | Phase 67 | Complete |
| SHARED-01 | Phase 68 | Complete |
| SHARED-02 | Phase 68 | Complete |
| GRACE-01 | Phase 69 | Complete |
| GRACE-02 | Phase 69 | Complete |
| GRACE-03 | Phase 69 | Complete |
| TEST-01 | Phase 70 | Complete |
| TEST-02 | Phase 70 | Complete |
| TEST-03 | Phase 70 | Complete |
| TEST-04 | Phase 70 | Complete |
| TEST-05 | Phase 70 | Complete |

**Coverage:**
- v1 requirements: 14 total
- Mapped to phases: 14
- Unmapped: 0 ✓

---
*Requirements defined: 2026-02-06*
*Last updated: 2026-02-06 after Phase 68 execution complete*
