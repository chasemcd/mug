---
phase: 96-scene-transition-focus-loss
plan: 01
subsystem: ui
tags: [javascript, messagechannel, background-tabs, event-driven, scene-transitions]

# Dependency graph
requires:
  - phase: 24-web-worker-timer
    provides: "GameTimerWorker for background-tab-safe game loop timing"
  - phase: 26-fast-forward
    provides: "_performFastForward batch stepping after tab refocus"
provides:
  - "onGameDone callback for event-driven game completion notification"
  - "_startDoneCountdown with MessageChannel watchdog for background-tab-safe countdown"
  - "Fast-forward episode end detection from terminated/truncated environment flags"
affects: [96-02, scene-transitions, background-tabs, csv-export]

# Tech tracking
tech-stack:
  added: []
  patterns: ["MessageChannel watchdog for background-tab-safe timing", "Event callback + setInterval fallback pattern"]

key-files:
  created: []
  modified:
    - "mug/server/static/js/pyodide_multiplayer_game.js"
    - "mug/server/static/js/index.js"

key-decisions:
  - "Used onGameDone callback pattern instead of custom events for simplicity and direct invocation"
  - "MessageChannel watchdog with setTimeout(200) polling instead of tight busy-wait"
  - "Kept setInterval as fallback for RemoteGame (single-player) compatibility"
  - "Check both individual agent terminated/truncated values AND Gymnasium __all__ key"

patterns-established:
  - "onGameDone callback: game instance fires callback on completion, host sets it after creation"
  - "MessageChannel watchdog: use MessageChannel + setTimeout hybrid for background-tab-safe delayed actions"

# Metrics
duration: 3min
completed: 2026-02-16
---

# Phase 96 Plan 01: Event-Driven Scene Advancement Summary

**onGameDone callback + MessageChannel watchdog replaces throttled setInterval polling for reliable scene transitions in background tabs; fast-forward now detects terminated/truncated episode end flags**

## Performance

- **Duration:** 3 min
- **Started:** 2026-02-16T18:43:07Z
- **Completed:** 2026-02-16T18:45:46Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- MultiplayerPyodideGame now fires `onGameDone` callback immediately when `signalEpisodeComplete()` sets state="done", bypassing throttled setInterval polling
- Scene advancement countdown extracted into `_startDoneCountdown()` with MessageChannel watchdog that forces `advance_scene` even in fully-throttled background tabs
- Fast-forward episode end detection now checks both `max_steps` AND `terminated/truncated` environment flags (individual agent values + Gymnasium `__all__` key)
- All 39 unit tests pass with zero regressions

## Task Commits

Each task was committed atomically:

1. **Task 1: Add onGameDone callback and complete fast-forward episode detection** - `f973da0` (feat)
2. **Task 2: Replace throttled polling with event-driven scene advancement** - `0224a42` (feat)

**Plan metadata:** (pending final commit)

## Files Created/Modified
- `mug/server/static/js/pyodide_multiplayer_game.js` - Added onGameDone callback property in constructor, invocation in signalEpisodeComplete, and enhanced fast-forward episode end detection with terminated/truncated flag checking
- `mug/server/static/js/index.js` - Rewrote enableCheckPyodideDone to set onGameDone callback, extracted _startDoneCountdown with MessageChannel watchdog, added cleanup in terminateGymScene

## Decisions Made
- **onGameDone callback pattern:** Direct callback invocation (not CustomEvent) for simplicity -- the game instance and index.js are tightly coupled, so a callback is the most straightforward notification mechanism
- **MessageChannel watchdog:** Uses `setTimeout(200)` between MessageChannel posts to avoid CPU waste while still checking ~5x/second -- sufficient for a 3-second countdown
- **Fallback polling retained:** `setInterval(100)` kept as fallback for `RemoteGame` (single-player Pyodide) instances that don't have the `onGameDone` callback
- **Gymnasium __all__ key handling:** Check both individual agent terminated/truncated values AND the `__all__` key for maximum compatibility with different Gymnasium environment implementations

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Added cleanup in terminateGymScene**
- **Found during:** Task 2 (index.js rewrite)
- **Issue:** Plan didn't specify cleanup of onGameDone callback and _startDoneCountdown._started flag when scene terminates, which could cause stale callbacks or double-firing on next scene
- **Fix:** Added cleanup in terminateGymScene to null out pyodideRemoteGame.onGameDone and reset _startDoneCountdown._started
- **Files modified:** mug/server/static/js/index.js
- **Verification:** grep confirms cleanup code present in terminateGymScene
- **Committed in:** 0224a42 (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 missing critical)
**Impact on plan:** Essential for correctness across scene transitions. No scope creep.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Event-driven notification and background-tab-safe countdown are in place
- Plan 02 can now implement focus-loss timeout handling, CSV focus flag, and E2E test fixes
- The onGameDone callback + MessageChannel watchdog patterns are established for reuse

## Self-Check: PASSED

All files verified present, both commit hashes confirmed in git log.

---
*Phase: 96-scene-transition-focus-loss*
*Completed: 2026-02-16*
