---
phase: 25-focus-detection
plan: 01
subsystem: multiplayer
tags: [page-visibility-api, focus-detection, input-buffering, telemetry]

# Dependency graph
requires:
  - phase: 24-web-worker-timer
    provides: Worker-based timing immune to browser throttling
provides:
  - FocusManager class with Page Visibility API integration
  - Background period tracking with timestamps
  - Partner input buffering when tab is backgrounded
  - getTelemetry() method for session export
affects: [26-fast-forward-resume, 27-telemetry-export]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "FocusManager class for visibility detection"
    - "Input buffering for graceful background operation"

key-files:
  created: []
  modified:
    - interactive_gym/server/static/js/pyodide_multiplayer_game.js

key-decisions:
  - "Worker keeps ticking when backgrounded (for elapsed time), but frames don't advance"
  - "Partner inputs buffered in FocusManager.backgroundInputBuffer for Phase 26 fast-forward"
  - "Periodic logging every ~50 ticks (5s at 10 FPS) during background state"

patterns-established:
  - "FocusManager pattern: visibility detection + state tracking + input buffering"
  - "Integration pattern: check focusManager.isBackgrounded in tick and input handlers"

# Metrics
duration: 3min
completed: 2026-01-23
---

# Phase 25 Plan 01: Focus Detection & Background State Summary

**FocusManager class with Page Visibility API detects tab backgrounding, tracks duration/periods, and buffers partner inputs for Phase 26 fast-forward**

## Performance

- **Duration:** 3 min
- **Started:** 2026-01-23T05:23:35Z
- **Completed:** 2026-01-23T05:26:27Z
- **Tasks:** 3
- **Files modified:** 1

## Accomplishments

- FocusManager class with Page Visibility API listener for immediate tab background detection
- Background period tracking with start/end/duration timestamps for telemetry
- Partner input buffering when tab is backgrounded (inputs stored in backgroundInputBuffer)
- Integration with _handleWorkerTick (skip frame processing) and _handleInputPacket (buffer inputs)
- getTelemetry() method ready for Phase 27 export

## Task Commits

Each task was committed atomically:

1. **Task 1: Create FocusManager class with visibility detection** - `3cb81fb` (feat)
2. **Task 2: Integrate FocusManager with multiplayer game loop** - `e988d7d` (feat)
3. **Task 3: Verify background behavior with console logging** - `a7d278c` (feat)

## Files Created/Modified

- `interactive_gym/server/static/js/pyodide_multiplayer_game.js` - Added FocusManager class (lines 170-284), integrated with constructor, _handleWorkerTick, _handleInputPacket, _destroyTimerWorker, and clearGGPOState

## Decisions Made

- **Worker ticks continue during background:** Worker keeps timing so we track elapsed time, but _handleWorkerTick returns early without advancing frames. Partner will continue playing; we catch up on refocus via Phase 26 fast-forward.
- **Input buffering in FocusManager:** Partner inputs buffered in backgroundInputBuffer array rather than pendingInputPackets. This separates normal input processing from background-recovery flow.
- **Periodic logging cadence:** Every ~50 ticks (approximately 5 seconds at 10 FPS) during background state to avoid log spam while providing visibility.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- FocusManager.drainBufferedInputs() ready for Phase 26 fast-forward implementation
- FocusManager.getTelemetry() ready for Phase 27 telemetry export
- Background periods tracked with timestamps for data quality analysis

---
*Phase: 25-focus-detection*
*Completed: 2026-01-23*
