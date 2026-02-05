---
phase: 69-multiplayer-batch-operations
plan: 03
subsystem: multiplayer
tags: [pyodide, web-worker, batch, migration, shim-removal, ggpo, rollback]

# Dependency graph
requires:
  - phase: 69-multiplayer-batch-operations Plan 02
    provides: All individual this.pyodide.* calls replaced with structured this.worker.* commands
  - phase: 69-multiplayer-batch-operations Plan 01
    provides: batch() Worker command for sequential multi-op execution
provides:
  - performRollback uses worker.batch() for single-round-trip replay (setState + N steps + getState)
  - _performFastForward uses worker.batch() for single-round-trip catch-up (N steps)
  - Zero this.pyodide references in entire JS codebase
  - Clean PyodideWorker.js with no backward-compat shims
  - Clean pyodide_worker.js with no handleRunPython
  - Clean pyodide_remote_game.js with no this.pyodide = this.worker shim
  - INTEG-02 satisfied: MultiplayerPyodideGame uses PyodideWorker for all Pyodide operations
affects:
  - 70-verification (ready for final integration verification)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Worker batch API for multi-step operations (rollback replay, fast-forward catch-up)"
    - "JS-side result processing: iterate batchResults array matching batch operation order"
    - "Type-safe Map/Object conversion for Worker step results during batch processing"

key-files:
  modified:
    - interactive_gym/server/static/js/pyodide_multiplayer_game.js
    - interactive_gym/server/static/js/PyodideWorker.js
    - interactive_gym/server/static/js/pyodide_worker.js
    - interactive_gym/server/static/js/pyodide_remote_game.js

key-decisions:
  - "Batch rollback includes computeHash ops for debug logging parity with original Python"
  - "Hash computation uses SHA-256 (Worker) instead of MD5 (original Python) - consistent with Plan 02 migration"
  - "Batch rollback includes trailing getState for post-replay state capture (future use)"
  - "Null-safe type conversion: check both instanceof Map and typeof object with null guard"

patterns-established:
  - "All Pyodide operations go through structured Worker commands - no arbitrary Python execution"
  - "Batch API is the standard for multi-step operations (rollback, fast-forward)"

# Metrics
duration: 4min
completed: 2026-02-05
---

# Phase 69 Plan 03: Batch Migration + Shim Removal Summary

**Migrated performRollback and _performFastForward to Worker batch API for single-round-trip execution, then removed all 5 Phase 68 backward-compatibility shims leaving zero this.pyodide references**

## Performance

- **Duration:** 4 min
- **Started:** 2026-02-05T04:45:21Z
- **Completed:** 2026-02-05T04:49:33Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- performRollback now executes setState + N*(computeHash+step+computeHash) + getState in a single Worker round-trip instead of building a monolithic Python string
- _performFastForward now executes N step operations in a single Worker round-trip instead of inline Python
- Removed all 5 backward-compatibility shims: runPythonAsync, _wrapResult, toPy (PyodideWorker.js), handleRunPython (pyodide_worker.js), this.pyodide = this.worker (pyodide_remote_game.js)
- Zero this.pyodide references remain in the entire JS codebase
- Net reduction of ~96 lines across all files (44 added, 140 removed)

## Task Commits

Each task was committed atomically:

1. **Task 1: Migrate performRollback to worker.batch()** - `e2bbc6a` (feat)
2. **Task 2: Migrate _performFastForward to batch and remove all shims** - `e30eec5` (feat)

## Files Created/Modified
- `interactive_gym/server/static/js/pyodide_multiplayer_game.js` - performRollback and _performFastForward now use this.worker.batch(); zero this.pyodide references
- `interactive_gym/server/static/js/PyodideWorker.js` - Removed runPythonAsync(), _wrapResult(), toPy() shim methods
- `interactive_gym/server/static/js/pyodide_worker.js` - Removed handleRunPython function and case 'runPython' from switch; updated header comment
- `interactive_gym/server/static/js/pyodide_remote_game.js` - Removed this.pyodide = this.worker backward-compat shim from initialize()

## Decisions Made
- Batch rollback includes computeHash operations before and after each step for debug logging, maintaining parity with the original Python implementation's pre_hash/post_hash logging
- Hash computation now uses SHA-256 (from Worker's computeHash) instead of MD5 (from the original inline Python) -- consistent with the Plan 02 migration that switched all hash operations to SHA-256
- Included a trailing getState in the rollback batch for post-replay state capture availability
- Null-safe type conversion for step results: check `rewards instanceof Map`, then `typeof rewards === 'object' && rewards !== null`, with fallback to `{ human: rewards }`

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Phase 69 (Multiplayer Batch Operations) is complete: all 3 plans executed
- All Pyodide operations now go through the structured Worker API
- No arbitrary Python execution possible from the main thread
- Ready for Phase 70 (verification) or milestone completion

---
*Phase: 69-multiplayer-batch-operations*
*Completed: 2026-02-05*
