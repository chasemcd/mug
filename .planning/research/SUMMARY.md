# Project Research Summary

**Project:** Interactive Gym v1.16 - Pyodide Web Worker
**Domain:** WebAssembly Worker Architecture for Browser-Based Python Game Execution
**Researched:** 2026-02-04
**Confidence:** MEDIUM

## Executive Summary

Moving Pyodide to a Web Worker is the correct solution for preventing Socket.IO disconnects during concurrent game initialization. The research confirms this is an officially supported pattern with well-documented implementation paths. The key architectural decision is to use **raw postMessage with a typed message protocol** rather than abstractions like Comlink, which aligns with existing codebase patterns (GameTimerWorker) and provides the progress event support needed during lengthy Pyodide initialization.

The recommended approach uses **composition over inheritance**: create a `PyodideWorker` class that both `RemoteGame` and `MultiplayerPyodideGame` use. This cleanly separates Worker lifecycle management from game logic. The critical technical challenge is the multiplayer rollback system, which currently executes batched Python operations to avoid event loop yields. The solution is a **batch API** that sends all rollback operations in a single postMessage, with the Worker executing them synchronously and returning all results together.

Key risks are (1) **memory boundary serialization** - PyProxy objects cannot cross the Worker boundary and must be converted to JavaScript first, (2) **initialization race conditions** - the Worker must signal readiness before accepting commands, and (3) **error propagation** - Worker errors must be explicitly forwarded to the main thread. All three have straightforward prevention patterns documented in the research.

## Key Findings

### Recommended Stack

The stack is minimal - native Web Worker APIs without external dependencies. This matches the existing codebase philosophy.

**Core technologies:**
- **Web Worker (native)**: Isolates Pyodide from main thread - fundamental browser API, HIGH confidence
- **postMessage API**: Main-Worker communication - chosen over Comlink for progress event support and codebase consistency
- **Transferable Objects**: Zero-copy transfer for large ArrayBuffers (render state, observations) - optional optimization
- **Separate Worker File**: `/static/js/pyodide_worker.js` - cleaner than inline Blob for Pyodide's complexity

**Rejected alternatives:**
- Comlink: RPC abstraction doesn't fit async WASM with progress events
- SharedArrayBuffer: Requires COOP/COEP headers, overkill for this use case
- Inline Blob Worker: Works for small workers (GameTimerWorker) but unwieldy for Pyodide

### Expected Features

**Must have (table stakes):**
- Non-blocking Pyodide initialization - main thread stays responsive for Socket.IO
- Progress events during loading - user sees "Loading Pyodide...", "Installing packages..."
- Error propagation to main thread - failures surface as UI errors, not silent hangs
- Request/response correlation with IDs - enables timeouts and proper promise resolution

**Should have (competitive):**
- Batch operations for rollback - single round-trip for state restore + N replay steps
- Latency tracking via timestamps - performance monitoring built-in
- Graceful Worker termination with cleanup - prevents memory leaks

**Defer (v2+):**
- SharedArrayBuffer for sub-ms latency (not needed at current frame rates)
- Hot reload of environment code without Worker restart
- Multi-Worker support for parallel environments

### Architecture Approach

The composition pattern keeps Worker management separate from game logic. Both `RemoteGame` (single-player) and `MultiplayerPyodideGame` use a shared `PyodideWorker` instance. The Worker is a singleton per page - Pyodide initialization is expensive (3-8 seconds) and packages stay loaded across scenes.

**Major components:**
1. **pyodide_worker.js** (Worker script) - owns Pyodide instance, handles all Python execution
2. **PyodideWorker** (main thread class) - manages Worker lifecycle, request/response correlation, progress callbacks
3. **Message Protocol** - typed messages with numeric IDs: INIT, STEP, RESET, BATCH, PROGRESS, ERROR

**Key message types:**
```
Main -> Worker: INIT, INSTALL_PACKAGES, SET_GLOBALS, RUN_INIT_CODE, STEP, RESET, BATCH
Worker -> Main: READY, INIT_COMPLETE, STEP_RESULT, RESET_RESULT, BATCH_RESULT, PROGRESS, ERROR
```

### Critical Pitfalls

1. **Worker-Main Thread Memory Boundary** - PyProxy objects CANNOT be sent via postMessage. Always call `.toJs()` before sending, then `.destroy()` to prevent leaks. Test serialization with `JSON.parse(JSON.stringify(data))` before implementation.

2. **Race Conditions During Initialization** - Worker script loads before Pyodide is ready. Must queue messages until `pyodideReady` flag, then send explicit `READY` event to main thread. Main thread must await `READY` before sending commands.

3. **Worker Error Propagation** - Uncaught Worker errors don't bubble to main thread. Wrap all Worker handlers in try/catch, send structured ERROR messages. Add timeouts to all pending requests to detect Worker crashes.

4. **Package Installation Timing** - `micropip.install()` takes 5-30 seconds. Send PROGRESS events during installation. Don't show game UI until ENV_READY received.

5. **NumPy Array Conversion** - NumPy dtypes don't always map cleanly to JS TypedArrays. Use Python-side `safe_serialize()` function to convert all NumPy types to plain Python lists/floats before returning.

## Implications for Roadmap

Based on research, suggested phase structure:

### Phase 1: Core Worker Infrastructure
**Rationale:** Foundation must exist before any game integration. Isolated, testable.
**Delivers:** `pyodide_worker.js` and `PyodideWorker` class with init, runPython, step, reset operations
**Addresses:** Non-blocking initialization, progress events, error propagation
**Avoids:** Pitfalls 2 (race conditions) and 3 (error propagation) by implementing ready-check and error forwarding from the start
**Estimated complexity:** Medium - new file, established patterns

### Phase 2: RemoteGame Integration
**Rationale:** Single-player is simpler - no GGPO/batch concerns. Validates Worker correctness before multiplayer.
**Delivers:** Updated `RemoteGame` using `PyodideWorker`, fallback mode for debugging
**Uses:** All stack elements, full message protocol
**Implements:** Main thread manager with request correlation
**Avoids:** Pitfall 1 (memory boundary) by ensuring all state serialization works
**Estimated complexity:** Medium - refactoring existing code

### Phase 3: Multiplayer Batch Operations
**Rationale:** GGPO rollback is the complex case. Requires batch API that doesn't exist yet.
**Delivers:** `batch()` operation, `MultiplayerPyodideGame` integration, rollback working with Worker
**Uses:** Batch message type, atomicity guarantees
**Implements:** Rollback as single round-trip: setState + N steps + getState
**Avoids:** Race conditions during replay by ensuring no event loop yields in Worker execution
**Estimated complexity:** High - new batch API, complex state management

### Phase 4: Validation and Cleanup
**Rationale:** Full system test, then remove scaffolding
**Delivers:** Verified zero-stagger concurrent initialization, performance validation, documentation
**Tests:** 3 concurrent games without Socket.IO disconnects, rollback parity, memory leak checks
**Cleanup:** Remove fallback code if stable, update deployment docs

### Phase Ordering Rationale

- **Phase 1 before 2**: Worker must exist before game classes can use it
- **Phase 2 before 3**: Single-player validates Worker correctness without GGPO complexity
- **Phase 3 needs batch API**: Rollback performance depends on single round-trip pattern
- **Phase 4 last**: Integration testing requires all components working together

The research identified that multiplayer's `performRollback()` already batches Python execution to avoid event loop yields - this pattern must be preserved in the Worker architecture via the batch API.

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 3 (Batch Operations):** GGPO state buffer location needs decision - research recommends Worker-authoritative but needs implementation exploration
- **Phase 4 (Validation):** Playwright Worker testing capabilities are documented but not hands-on verified

Phases with standard patterns (skip research-phase):
- **Phase 1 (Core Infrastructure):** Web Worker patterns well-documented, existing GameTimerWorker provides template
- **Phase 2 (RemoteGame):** Straightforward refactoring, no novel patterns

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Native Web Worker APIs, no exotic dependencies, matches existing codebase |
| Features | HIGH | Based on MDN docs and existing pyodide_multiplayer_game.js patterns |
| Architecture | MEDIUM | Composition pattern is sound; batch API needs implementation validation |
| Pitfalls | MEDIUM-HIGH | Memory boundary and error propagation well-documented; GGPO integration needs testing |

**Overall confidence:** MEDIUM

The core Web Worker patterns are solid, but MEDIUM overall because:
1. Web search was unavailable - Pyodide version/API may have changed since training data
2. Batch API for rollback is architecturally sound but unproven
3. Playwright Worker testing capabilities inferred from docs, not validated

### Gaps to Address

- **Pyodide Version Verification**: Research assumed v0.26.x based on training data. Verify current version and any API changes at https://pyodide.org/en/stable/usage/webworker.html before Phase 1
- **Batch API Design**: The batch operation needs detailed specification during Phase 3 planning. Current research provides concept but not full protocol
- **GGPO State Authority**: Research recommends Worker-authoritative state, but this changes the current architecture significantly. Validate during Phase 3
- **Performance Baselines**: Capture current timing metrics (Pyodide init time, step latency) before Worker migration to measure improvement

## Sources

### Primary (HIGH confidence)
- Existing codebase: `pyodide_multiplayer_game.js` - GameTimerWorker pattern, rollback implementation
- Existing codebase: `pyodide_remote_game.js` - RemoteGame API contract
- MDN Web Workers API - postMessage, Transferable objects, Worker lifecycle

### Secondary (MEDIUM confidence)
- Pyodide documentation (training data) - Web Worker usage patterns
- Phase 24 Research - Web Worker timer infrastructure patterns

### Tertiary (LOW confidence)
- Comlink comparison - library may have updated since training data
- Playwright Worker testing - capabilities inferred, not hands-on tested

---
*Research completed: 2026-02-04*
*Ready for roadmap: yes*
