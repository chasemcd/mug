---
phase: 75-merged-loading-screen
plan: 02
subsystem: ui, client
tags: [pyodide, loading-screen, loading-gate, timeout, javascript]

# Dependency graph
requires:
  - phase: 75-merged-loading-screen/75-01
    provides: Unified #loadingScreen HTML element, pyodide_load_timeout_s in config classes
  - phase: 67-pyodide-preload-infrastructure
    provides: preloadPyodide() function, pyodide_config socket event payload
  - phase: 69-server-init-grace
    provides: Server-side loading grace period, pyodide_loading_start/complete socket events
provides:
  - loadingGate object coordinating dual screening + Pyodide signals
  - checkLoadingGate() function for event-driven gate resolution
  - Configurable client-side Pyodide timeout from server config
  - Error page via showExclusionMessage() on Pyodide failure/timeout
  - Reconnect guard preventing loading screen re-display
affects:
  - 76 (test cleanup may reference loading gate behavior)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Dual-signal loading gate: loadingGate object with checkLoadingGate() called from both completion paths"
    - "Reconnect guard via gateResolved flag prevents re-entry on socket reconnection"

key-files:
  created: []
  modified:
    - interactive_gym/server/static/js/index.js

key-decisions:
  - "loadingGate object uses gateResolved boolean to prevent re-entry on reconnect"
  - "checkLoadingGate() updates #loadingStatus text based on which signal is still pending"
  - "Pyodide timeout uses setTimeout with configurable duration from pyodide_load_timeout_s"
  - "Timeout path emits pyodide_loading_complete with error+reason to clear server grace state"
  - "Per-scene Pyodide safety nets (advance button gate, start button gate) preserved unchanged"
  - "showPyodideProgress/hidePyodideProgress removed as they referenced deleted #pyodideLoader element"

patterns-established:
  - "Event-driven loading gate: both signals call checkLoadingGate(), gate resolves when both complete"
  - "Status text progression: Checking compatibility -> Loading Python runtime -> Installing packages"

# Metrics
duration: 3min
completed: 2026-02-07
---

# Phase 75 Plan 02: Client-Side Loading Gate with Timeout and Error Handling Summary

**Dual-signal loadingGate in index.js coordinating screening + Pyodide with configurable timeout and showExclusionMessage() error page**

## Performance

- **Duration:** 3 min
- **Started:** 2026-02-07T02:24:02Z
- **Completed:** 2026-02-07T02:27:30Z
- **Tasks:** 2/2
- **Files modified:** 1

## Accomplishments
- Added `loadingGate` object and `checkLoadingGate()` function for dual-signal gate coordination
- Refactored `experiment_config` handler to show unified `#loadingScreen` and delegate resolution to `checkLoadingGate()`
- Added configurable Pyodide timeout using `pyodide_load_timeout_s` from server config (default 60s)
- Integrated `preloadPyodide()` with loading gate signals on all paths (success, error, non-Pyodide early return)
- Removed `showPyodideProgress()`/`hidePyodideProgress()` functions (referenced deleted `#pyodideLoader`)
- Added reconnect guard (`gateResolved`) preventing loading screen re-display
- E2E smoke test (2 multiplayer basic tests) passes confirming full flow works

## Task Commits

Each task was committed atomically:

1. **Task 1: Add loading gate and refactor experiment_config handler** - `f7c007f` (feat)
2. **Task 2: Smoke test with manual server start** - verification only, no code changes (E2E tests pass)

## Files Created/Modified
- `interactive_gym/server/static/js/index.js` - Added loadingGate object, checkLoadingGate() function, refactored experiment_config handler, modified preloadPyodide() integration, removed old Pyodide progress functions

## Decisions Made
- **Reconnect guard:** `gateResolved` boolean prevents `experiment_config` handler from re-showing loading screen on socket reconnect after gate has resolved
- **Status text updates:** `checkLoadingGate()` updates `#loadingStatus` text based on which signal is still pending (compatibility check vs Python runtime loading)
- **Timeout notification:** When Pyodide times out, emits `pyodide_loading_complete` with `{ error: true, reason: 'timeout' }` to clear server-side LOADING_CLIENTS grace state
- **Safety nets preserved:** Per-scene Pyodide gating in `startStaticScene()`, `advanceButton` click handler, and `enableStartRefreshInterval()` kept as no-cost safety nets
- **No separate commit for Task 2:** Verification-only task with no code changes; E2E test results documented in summary

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Phase 75 (Merged Loading Screen) is complete: both Plan 01 (server config + unified HTML) and Plan 02 (client-side JS loading gate) are done
- LOAD-01 through LOAD-04 requirements all satisfied:
  - LOAD-01: Single `#loadingScreen` element, no `#screeningLoader` or `#pyodideLoader`
  - LOAD-02: `checkLoadingGate()` requires both `screeningComplete` AND `pyodideComplete`
  - LOAD-03: `setTimeout` uses `pyodide_load_timeout_s` from config (default 60s)
  - LOAD-04: Timeout and error paths call `showExclusionMessage()` with clear error text
- Phase 76 (cleanup/testing) can proceed

---
*Phase: 75-merged-loading-screen*
*Completed: 2026-02-07*
