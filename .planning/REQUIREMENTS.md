# Requirements: Interactive Gym v1.16

**Defined:** 2026-02-04
**Core Value:** Both players in a multiplayer game experience local-feeling responsiveness regardless of network latency, enabling valid research data collection without latency-induced behavioral artifacts.

## v1 Requirements

Requirements for v1.16 Pyodide Web Worker. Each maps to roadmap phases.

### Web Worker Infrastructure

- [ ] **WORKER-01**: PyodideWorker class loads Pyodide in dedicated Web Worker
- [ ] **WORKER-02**: Main thread remains responsive during Pyodide initialization (can respond to Socket.IO pings)
- [ ] **WORKER-03**: Worker sends READY event before accepting commands

### Game Integration

- [x] **INTEG-01**: RemoteGame uses PyodideWorker for all Pyodide operations
- [ ] **INTEG-02**: MultiplayerPyodideGame uses PyodideWorker for all Pyodide operations
- [x] **INTEG-03**: step() and reset() operations work via Worker postMessage
- [x] **INTEG-04**: render_state is proxied back to main thread for Phaser rendering

### Validation

- [ ] **VALID-01**: Socket.IO connections remain stable during concurrent Pyodide init (3+ games)
- [ ] **VALID-02**: Multi-participant tests pass with 0.5s stagger delay (down from 5s)
- [ ] **VALID-03**: Game loop step latency unchanged or improved vs direct Pyodide
- [ ] **VALID-04**: No memory leaks across multiple game sessions

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Enhanced Worker Features

- **WORKER-V2-01**: Progress events during loading ("Loading Pyodide...", "Installing packages...")
- **WORKER-V2-02**: Batch API for GGPO rollback (single round-trip for setState + N steps)
- **WORKER-V2-03**: Graceful Worker termination with cleanup
- **WORKER-V2-04**: Request/response correlation with IDs and timeouts
- **WORKER-V2-05**: Backward compatibility config flag for direct Pyodide mode

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| SharedArrayBuffer | Requires COOP/COEP headers, overkill for this use case |
| Comlink library | RPC abstraction doesn't fit async WASM with progress events |
| Multi-Worker support | Single Pyodide instance is sufficient |
| Hot reload | Environment code without Worker restart is complex |
| Zero-stagger (0s) | 0.5s stagger is sufficient; true zero requires more optimization |

## Traceability

Which phases cover which requirements. Updated by create-roadmap.

| Requirement | Phase | Status |
|-------------|-------|--------|
| WORKER-01 | Phase 67 | Complete |
| WORKER-02 | Phase 67 | Complete |
| WORKER-03 | Phase 67 | Complete |
| INTEG-01 | Phase 68 | Complete |
| INTEG-02 | Phase 69 | Pending |
| INTEG-03 | Phase 68 | Complete |
| INTEG-04 | Phase 68 | Complete |
| VALID-01 | Phase 70 | Pending |
| VALID-02 | Phase 70 | Pending |
| VALID-03 | Phase 70 | Pending |
| VALID-04 | Phase 70 | Pending |

**Coverage:**
- v1 requirements: 11 total
- Mapped to phases: 11
- Unmapped: 0 ✓

## Completed Requirements (v1.14)

Requirements completed in previous milestone, preserved for reference.

### Data Parity Fix (v1.14)

- [x] **PARITY-01**: Episode export waits for partner input confirmation before writing
- [x] **PARITY-02**: Configurable confirmation timeout (default reasonable for 200ms+ latency)
- [x] **PARITY-03**: Both players export identical action sequences for every frame
- [x] **PARITY-04**: Both players export identical rewards for every frame
- [x] **PARITY-05**: Both players export identical infos for every frame
- [x] **PARITY-06**: `test_active_input_with_latency[chromium-100]` passes consistently
- [x] **PARITY-07**: `test_active_input_with_packet_loss` passes consistently

### Multi-Participant Infrastructure (v1.14)

- [x] **STRESS-01**: Test infrastructure supports 6 concurrent participants (3 simultaneous games)

---
*Requirements defined: 2026-02-04*
*Last updated: 2026-02-05 for Phase 68 completion*
