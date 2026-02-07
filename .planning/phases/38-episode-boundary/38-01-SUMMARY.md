---
phase: 38-episode-boundary
plan: 01
subsystem: p2p
tags: [ggpo, data-export, episode-boundary, frame-confirmation]

# Dependency graph
requires:
  - phase: 36-buffer-split
    provides: Dual-buffer architecture with speculativeFrameData and frameDataBuffer
  - phase: 37-fast-forward-fix
    provides: _promoteConfirmedFrames() call pattern in fast-forward path
provides:
  - _promoteRemainingAtBoundary() method for forced frame promotion at episode end
  - Complete data export guarantee at episode boundaries
affects: [39-validation-comparison]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Forced promotion at episode boundary with warning logging"

key-files:
  created: []
  modified:
    - interactive_gym/server/static/js/pyodide_multiplayer_game.js

key-decisions:
  - "Use console.warn for boundary promotion (unusual condition worth attention)"
  - "Promote ALL remaining frames (no confirmedFrame check at boundary)"
  - "Call promotion outside if-block to run regardless of sceneId"

patterns-established:
  - "_promoteRemainingAtBoundary(): Force-promote speculative frames at episode boundary"

# Metrics
duration: 8min
completed: 2026-01-30
---

# Phase 38 Plan 01: Episode Boundary Confirmation Summary

**Forced promotion of unconfirmed speculative frames at episode end ensures complete data export with warning logging when confirmedFrame lags behind frameNumber**

## Performance

- **Duration:** 8 min
- **Started:** 2026-01-30T15:00:00Z
- **Completed:** 2026-01-30T15:08:00Z
- **Tasks:** 3
- **Files modified:** 1

## Accomplishments

- Added `_promoteRemainingAtBoundary()` method to force-promote all speculative frames at episode boundary
- Integrated boundary promotion call in `signalEpisodeComplete()` before data export
- Verified correct call order: promotion happens before `_emitEpisodeDataFromBuffer()`

## Task Commits

Each task was committed atomically:

1. **Task 1: Add _promoteRemainingAtBoundary() method** - `1891c63` (feat)
2. **Task 2: Call _promoteRemainingAtBoundary() before export in signalEpisodeComplete()** - `142cd96` (feat)
3. **Task 3: Verify implementation with grep checks** - (verification only, no commit)

## Files Created/Modified

- `interactive_gym/server/static/js/pyodide_multiplayer_game.js` - Added _promoteRemainingAtBoundary() method (lines 2994-3007) and call in signalEpisodeComplete() (line 3725)

## Decisions Made

1. **Warning level for boundary promotion:** Used `console.warn` instead of `p2pLog.debug` because:
   - This is an unusual condition (confirmation should normally keep up)
   - It indicates potential network latency issues
   - It's important for debugging data discrepancies

2. **Promote all remaining frames:** Unlike `_promoteConfirmedFrames()` which checks `frame <= confirmedFrame`, this method promotes ALL speculative frames because at episode end both players have executed identical steps with real inputs.

3. **Call outside if-block:** The `_promoteRemainingAtBoundary()` call is placed before the `if (this.sceneId)` block to ensure promotion always happens, regardless of whether sceneId exists for export.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Episode boundary confirmation complete
- Ready for Phase 39 validation comparison
- Both players now guaranteed to export identical frame counts after episode end
- Warning logging enables debugging of network latency issues

---
*Phase: 38-episode-boundary*
*Completed: 2026-01-30*
