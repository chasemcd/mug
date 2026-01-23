---
phase: 24-web-worker-timer
plan: 01
subsystem: timing
tags: [web-worker, game-loop, browser-throttling, multiplayer]

# Dependency graph
requires:
  - phase: 23-partner-disconnect-handling
    provides: multiplayer game architecture, P2P infrastructure
provides:
  - GameTimerWorker class for unthrottled timing
  - Worker-driven game loop integration
  - Background tab handling for multiplayer games
affects: [25-focus-detection, 26-notification-pause, 27-focus-recovery]

# Tech tracking
tech-stack:
  added: [Web Worker API (native), Blob URL Workers]
  patterns: [dual-loop architecture (Worker timer + RAF render)]

key-files:
  created: []
  modified:
    - interactive_gym/server/static/js/pyodide_multiplayer_game.js
    - interactive_gym/server/static/js/phaser_gym_graphics.js

key-decisions:
  - "Inline Blob Worker instead of separate file (simpler deployment)"
  - "Worker ticks trigger game logic; RAF loop only renders"
  - "Processing guard (isProcessingTick) prevents overlapping async operations"

patterns-established:
  - "GameTimerWorker: Reusable class for throttle-resistant timing"
  - "Tick callback pattern: External code registers callback, clears flag when done"
  - "Cleanup on all termination paths (done, exclusion, disconnect)"

# Metrics
duration: 12min
completed: 2026-01-23
---

# Phase 24 Plan 01: Web Worker Timer Infrastructure Summary

**Inline Blob Worker for game timing that runs unthrottled when tabs are backgrounded, integrated with multiplayer game loop**

## Performance

- **Duration:** 12 min
- **Started:** 2026-01-23
- **Completed:** 2026-01-23
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Created GameTimerWorker class with inline Blob Worker (no separate file)
- Worker runs setInterval exempt from browser throttling (Chrome 88+)
- Integrated with MultiplayerPyodideGame: Worker ticks drive game logic
- Phaser's update() now only renders when Worker timing is active
- Proper cleanup on all game termination paths (normal end, exclusion, disconnect)

## Task Commits

Each task was committed atomically:

1. **Task 1: Create GameTimerWorker class** - `028af80` (feat)
2. **Task 2: Integrate Worker timing with game loop** - `94d84d3` (feat)

## Files Created/Modified

- `interactive_gym/server/static/js/pyodide_multiplayer_game.js`
  - Added GameTimerWorker class (lines 39-155)
  - Added timer properties to constructor (timerWorker, isProcessingTick, tickCallback)
  - Added _initTimerWorker(), _handleWorkerTick(), registerTickCallback(), _destroyTimerWorker()
  - Added cleanup calls on all termination paths

- `interactive_gym/server/static/js/phaser_gym_graphics.js`
  - Register tick callback in create() for multiplayer games
  - Added onWorkerTick() method
  - Modified update() to skip processPyodideGame when Worker timing active

## Decisions Made

1. **Inline Blob Worker** - Created Worker from string via Blob URL instead of separate .js file
   - Simpler deployment (no extra file to serve)
   - Worker code is minimal (just setInterval and postMessage)

2. **Tick callback pattern** - External code registers callback instead of Worker calling game directly
   - Allows Phaser to still orchestrate game step
   - Processing guard (isProcessingTick) cleared by callback, not Worker

3. **Cleanup on all paths** - Timer destroyed on:
   - Normal game completion
   - Partner exclusion
   - Mid-game exclusion
   - Partner disconnection
   - Prevents memory leaks from orphaned Workers

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None - implementation followed research patterns from 24-RESEARCH.md without issues.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Web Worker timer infrastructure complete
- Game logic advances on Worker ticks (unthrottled in background)
- Rendering still uses Phaser RAF (pauses in background - expected and correct)
- Ready for Phase 25: Focus detection to detect when tab is backgrounded

**Note:** To verify background behavior, test by:
1. Run multiplayer game in browser
2. Background the tab for 10+ seconds
3. Foreground the tab
4. Game should have continued advancing frames (no gap)

---
*Phase: 24-web-worker-timer*
*Completed: 2026-01-23*
