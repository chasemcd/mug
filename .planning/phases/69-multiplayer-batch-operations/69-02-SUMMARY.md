---
phase: 69-multiplayer-batch-operations
plan: 02
subsystem: multiplayer
tags: [pyodide, web-worker, migration, multiplayer, ggpo]

# Dependency graph
requires:
  - phase: 69-multiplayer-batch-operations Plan 01
    provides: getState/setState/computeHash/seedRng/render/batch Worker commands
provides:
  - All individual this.pyodide.* calls replaced with structured this.worker.* commands
  - stepWithActions uses Worker step() with _convertToMap()
  - State management (save/load snapshot) uses Worker getState/setState
  - Hash operations use Worker computeHash()
affects:
  - 69-multiplayer-batch-operations Plan 03 (shim removal - performRollback + _performFastForward migration)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Worker command migration: replace inline Python with structured Worker API calls"
    - "_convertToMap() for Worker plain-object to Map conversion"
    - "_processRenderState() for RGB array detection and render_state structuring"

key-files:
  modified:
    - interactive_gym/server/static/js/pyodide_multiplayer_game.js

key-decisions:
  - "validateStateSync uses getState() probe instead of Python hasattr check - simpler and no arbitrary Python"
  - "Server-auth reset path: reset() + setState() + render() sequence replaces monolithic Python block"
  - "loadStateSnapshot drops verification step (before/after state comparison) - setState is a tested Worker command"
  - "applyServerState wraps env_state in {env_state: ...} for setState compatibility"
  - "computeHash() now uses SHA-256 (Worker) instead of MD5 (old inline Python) - both peers use same algorithm"

patterns-established:
  - "All individual Pyodide operations use structured Worker commands"
  - "Only batch operations (rollback, fast-forward) still use runPythonAsync"

# Metrics
duration: 5min
completed: 2026-02-05
---

# Phase 69 Plan 02: Multiplayer Call Site Migration Summary

**Migrated all 18 individual this.pyodide.runPythonAsync() calls to structured this.worker.* commands, removing ~307 lines of inline Python code**

## Performance

- **Duration:** 5 min
- **Started:** 2026-02-05T04:38:33Z
- **Completed:** 2026-02-05T04:43:25Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments
- Replaced 18 individual this.pyodide.runPythonAsync/toPy call sites with structured Worker commands
- stepWithActions() now uses this.worker.step() with _convertToMap() for downstream Map compatibility
- reset() server-authoritative path uses this.worker.reset() + setState() + render() sequence
- reset() P2P path uses this.worker.reset() with _convertToMap() and _processRenderState()
- saveStateSnapshot() uses this.worker.getState() (captures env + RNG state)
- loadStateSnapshot() uses this.worker.setState() (restores env + RNG state)
- computeQuickStateHash() and _computeHashFromState() use this.worker.computeHash()
- seedPythonEnvironment() uses this.worker.seedRng()
- validateStateSync() uses getState() probe instead of Python hasattr check
- Net reduction of 307 lines (374 deleted, 67 added) - inline Python code eliminated

## Task Commits

Each task was committed atomically:

1. **Task 1: Migrate individual call sites to structured Worker commands** - `71c0c00` (feat)

## Files Created/Modified
- `interactive_gym/server/static/js/pyodide_multiplayer_game.js` - Replaced 18 this.pyodide.runPythonAsync() and this.pyodide.toPy() calls with structured this.worker.getState/setState/computeHash/seedRng/render/step/reset commands; only performRollback() and _performFastForward() still use this.pyodide for batch operations (Plan 03 scope)

## Decisions Made
- **validateStateSync approach:** Replaced Python hasattr() check with a practical getState() probe. If it succeeds, the env has get_state/set_state. Simpler, no arbitrary Python execution needed.
- **Server-auth reset sequence:** Uses reset() + setState() + render() as three separate Worker calls instead of a monolithic Python block. The obs from reset() is used (Worker handles normalization), render from after setState shows correct state.
- **loadStateSnapshot simplification:** Dropped the verification step (before/after state comparison with JSON round-trip). setState is a tested Worker command; the debug logging was informational only.
- **Hash algorithm change:** computeHash() now uses SHA-256 (via Worker) instead of the old inline MD5. Both peers use the same Worker command, so hashes remain comparable. The episode sync hash check and debug hashes all use the same algorithm now.
- **setState wrapper:** applyServerState and _applyP2PState wrap env_state in `{env_state: ...}` JSON for setState compatibility. The Worker's handleSetState handles missing np_rng_state/py_rng_state gracefully.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Only performRollback() and _performFastForward() still reference this.pyodide (2 call sites)
- Plan 03 will migrate these batch operations to this.worker.batch() and remove all backward-compat shims
- The toPy shim has zero callers remaining (all removed in this plan)
- runPythonAsync shim has only 2 callers remaining (performRollback + _performFastForward)

---
*Phase: 69-multiplayer-batch-operations*
*Completed: 2026-02-05*
