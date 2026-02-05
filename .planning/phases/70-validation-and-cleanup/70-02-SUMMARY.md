---
phase: 70-validation-and-cleanup
plan: 02
subsystem: testing, worker
tags: [pyodide-worker, toJs, postMessage, DataCloneError, action-keys, validation]

# Dependency graph
requires:
  - phase: 69-multiplayer-batch-operations
    provides: "Complete Pyodide Worker migration - all game operations run in Worker thread"
  - phase: 68-remotegame-integration
    provides: "RemoteGame uses PyodideWorker for all Pyodide operations"
provides:
  - "Fixed js.window AttributeError in Worker context (interactiveGymGlobals via postMessage)"
  - "Fixed DataCloneError by replacing toJs({depth:2}) with toJs({dict_converter: Object.fromEntries})"
  - "Fixed action key type mismatch (JSON string keys converted back to int for env.step())"
  - "Manual browser verification: 2-player game runs with step latency 3.8-7.6ms"
affects: [all-pyodide-games, multiplayer]

# Tech tracking
tech-stack:
  added: []
  patterns: ["dict_converter: Object.fromEntries for postMessage-safe toJs()", "int(k) key coercion at JSON boundary"]

key-files:
  created:
    - "tests/e2e/test_worker_validation.py"
  modified:
    - "interactive_gym/server/static/js/pyodide_worker.js"
    - "interactive_gym/server/static/js/pyodide_remote_game.js"

key-decisions:
  - "toJs({dict_converter: Object.fromEntries}) without depth limit - unlimited depth ensures all nested PyProxy objects are converted"
  - "Action key int coercion in Worker Python code - fixes JSON string-key → Python int-key mismatch at serialization boundary"
  - "interactiveGymGlobals passed via Worker globals payload instead of js.window - Workers have no window object"

patterns-established:
  - "toJs() for postMessage: always use dict_converter: Object.fromEntries, never use depth limit"
  - "JSON action keys: always coerce string keys to int when env expects int agent IDs"

# Metrics
duration: ~3h
completed: 2026-02-05
---

# Phase 70 Plan 02: Worker Validation and Bug Fixes Summary

**Fixed three critical Worker migration bugs; verified multiplayer game runs end-to-end with 3.8-7.6ms step latency**

## Performance

- **Duration:** ~3h
- **Started:** 2026-02-05
- **Completed:** 2026-02-05
- **Tasks:** Bug investigation and fixes (scope expanded from original latency/memory tests)
- **Files modified:** 3

## Accomplishments

### Bug Fix 1: js.window AttributeError (commit 9e733d5)
- **Root cause:** `pyodide_remote_game.js` injected Python code accessing `js.window.interactiveGymGlobals` — Workers have no `window` object
- **Fix:** Pass `interactive_gym_globals` via the Worker's `initEnv` globals payload instead of accessing `js.window`
- **Files:** `pyodide_remote_game.js` (initialize + reinitialize_environment)

### Bug Fix 2: DataCloneError on postMessage (commit c9477dc)
- **Root cause:** `toJs({ depth: 2 })` produced JS `Map` objects (not structurally cloneable) and left nested PyProxy objects unconverted beyond depth 2
- **Fix:** Changed all three `toJs()` calls to `toJs({ dict_converter: Object.fromEntries })` — converts all Python dicts to plain JS objects at unlimited depth
- **Files:** `pyodide_worker.js` (handleStepInternal, handleResetInternal, handleRenderInternal)

### Bug Fix 3: Action key type mismatch (commit ec0e492)
- **Root cause:** `JSON.stringify()` converts all object keys to strings, but `cogrid_env.py` expects integer agent IDs
- **Fix:** Added dict comprehension after `json.loads()` to convert digit-only string keys back to integers
- **Files:** `pyodide_worker.js` (handleStepInternal)

### Manual Verification
- 2-player Overcooked multiplayer game tested in browser
- Game advances correctly: 500+ frames in 5 seconds
- Step latency: 3.8-7.6ms (well within acceptable range)
- No DataCloneError, no KeyError, no game-stopping errors
- Only pre-existing P2P state hash truncation mismatch (cosmetic, not functional)

## Task Commits

1. **fix(70): pass interactiveGymGlobals via Worker postMessage instead of js.window** - `9e733d5`
2. **fix(70): use dict_converter in toJs() to prevent DataCloneError on postMessage** - `c9477dc`
3. **fix(70): convert JSON string action keys back to int for env.step()** - `ec0e492`

## Files Created/Modified
- `interactive_gym/server/static/js/pyodide_remote_game.js` - Removed js.window references, pass globals via Worker postMessage
- `interactive_gym/server/static/js/pyodide_worker.js` - dict_converter in toJs(), int key coercion for actions
- `tests/e2e/test_worker_validation.py` - Created latency and memory test scaffolding

## Deviations from Plan

**Scope expanded significantly.** Original plan called for latency measurement and memory growth tests. During execution, discovered three critical Worker migration bugs that prevented the game from running at all. Fixed bugs first, then verified game works manually rather than via automated E2E tests (which require the bugs to be fixed first).

## Issues Encountered

- **E2E test infrastructure:** Automated Playwright E2E tests need the three bug fixes to run. Test scaffolding was created but full automated validation deferred.
- **Tab throttling:** Browser tabs in background get throttled, affecting multiplayer timing. Must use separate windows for multiplayer testing.

---
*Phase: 70-validation-and-cleanup*
*Completed: 2026-02-05*
