---
phase: 69-multiplayer-batch-operations
plan: 01
subsystem: infra
tags: [pyodide, web-worker, batch-api, state-management, ggpo]

# Dependency graph
requires:
  - phase: 68-remotegame-integration
    provides: PyodideWorker class and pyodide_worker.js with basic step/reset/runPython protocol
provides:
  - getState/setState Worker commands for env + RNG state capture/restore
  - computeHash Worker command for deterministic SHA-256 state hashing
  - seedRng Worker command for numpy + Python random seeding
  - render Worker command for standalone env.render()
  - batch Worker command for sequential multi-op execution in single round-trip
  - Internal handler variants (handleStepInternal, handleResetInternal, etc.) for batch reuse
affects:
  - 69-multiplayer-batch-operations Plan 02 (multiplayer migration uses these commands)
  - 69-multiplayer-batch-operations Plan 03 (shim removal depends on all callers migrated)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Internal/External handler pattern: *Internal does work and returns, * wraps with postMessage"
    - "Batch command protocol: array of {op, params} executed sequentially, stop-on-error with partialResults"

key-files:
  modified:
    - interactive_gym/server/static/js/pyodide_worker.js
    - interactive_gym/server/static/js/PyodideWorker.js

key-decisions:
  - "Internal/External handler split enables batch reuse without code duplication"
  - "getState returns raw JSON string (caller parses) for minimal transfer overhead"
  - "computeHash normalizes floats to 10 decimal places for deterministic cross-platform hashing"
  - "Batch error includes failedIndex and partialResults for precise error reporting"
  - "handleRunPython and backward-compat shims preserved for Plan 02/03 migration"

patterns-established:
  - "Internal handler pattern: every handler that batch needs has an *Internal variant"
  - "Batch protocol: {operations: [{op, params}]} -> [result1, result2, ...]"

# Metrics
duration: 3min
completed: 2026-02-05
---

# Phase 69 Plan 01: Worker Protocol Extension Summary

**Extended PyodideWorker with 6 new structured commands (getState, setState, computeHash, seedRng, render, batch) for multiplayer GGPO rollback migration**

## Performance

- **Duration:** 3 min
- **Started:** 2026-02-05T04:33:08Z
- **Completed:** 2026-02-05T04:36:02Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Added 6 new Worker-side handlers with Internal variants for batch reuse
- Added 6 new main-thread async methods on PyodideWorker class
- Refactored existing handleStep/handleReset into Internal/External pattern
- Batch command supports all 7 operation types with stop-on-error semantics
- All existing functionality preserved (installPackages, initEnv, step, reset, runPython, toPy, _wrapResult)

## Task Commits

Each task was committed atomically:

1. **Task 1: Add new Worker-side handlers to pyodide_worker.js** - `aed7db1` (feat)
2. **Task 2: Add new main-thread methods to PyodideWorker.js** - `e8dc86f` (feat)

## Files Created/Modified
- `interactive_gym/server/static/js/pyodide_worker.js` - Added handleGetState, handleSetState, handleComputeHash, handleSeedRng, handleRender, handleBatch handlers + Internal variants; refactored handleStep/handleReset to Internal pattern; wired 6 new types into handleMessage switch
- `interactive_gym/server/static/js/PyodideWorker.js` - Added getState(), setState(), computeHash(), seedRng(), render(), batch() public async methods with JSDoc; updated module header with usage examples

## Decisions Made
- Internal/External handler split: each handler that batch needs has an *Internal variant that does the work and returns the result, while the external variant wraps with postMessage. This avoids code duplication in batch.
- getState returns a raw JSON string (not parsed object) to minimize transfer overhead and let the caller decide when/if to parse.
- computeHash uses float normalization (round to 10 decimal places) and sorted JSON for deterministic cross-platform hashing.
- Batch error reporting includes failedIndex (which operation failed) and partialResults (what succeeded before failure).
- All backward-compat shims (handleRunPython, runPythonAsync, toPy, _wrapResult) preserved -- they will be removed in Plan 03 after all callers are migrated in Plan 02.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- All 6 new Worker commands are ready for Plan 02 to use when migrating MultiplayerPyodideGame
- The batch command supports the rollback pattern: setState + N steps + getState + render in single round-trip
- handleRunPython and shims remain for Plan 02 incremental migration
- Plan 03 can remove shims after Plan 02 completes migration

---
*Phase: 69-multiplayer-batch-operations*
*Completed: 2026-02-05*
