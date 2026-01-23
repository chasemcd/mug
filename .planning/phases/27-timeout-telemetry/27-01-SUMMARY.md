---
phase: 27-timeout-telemetry
plan: 01
subsystem: multiplayer
tags: [focus-loss, timeout, telemetry, webrtc, pyodide]

# Dependency graph
requires:
  - phase: 25-focus-detection
    provides: FocusManager class with background detection
  - phase: 26-resync-partner-ux
    provides: Fast-forward resync on refocus
  - phase: 23-partner-disconnect-handling
    provides: Terminal overlay pattern and sessionPartialInfo structure
provides:
  - focus_loss_config() method for researcher configuration
  - Configurable timeout enforcement that ends game
  - Focus loss telemetry in all metrics exports
  - Custom message support for focus loss termination
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Terminal state flag pattern (focusLossTimeoutTerminal) for overlay states"
    - "Config passthrough via scene metadata (focus_loss_timeout_ms, focus_loss_message)"

key-files:
  created: []
  modified:
    - interactive_gym/scenes/gym_scene.py
    - interactive_gym/server/static/js/pyodide_multiplayer_game.js

key-decisions:
  - "Focus loss timeout defaults to 30 seconds, set to 0 to disable"
  - "Timeout only triggers while backgrounded (checked each worker tick)"
  - "Reuses partner disconnect overlay pattern for consistent UX"
  - "All three export methods include focus loss telemetry for research"

patterns-established:
  - "Focus loss telemetry: backgroundPeriods array with start/end/durationMs"
  - "Terminal overlay states: set terminal flag, mark sessionPartialInfo, show overlay, prevent isDone"

# Metrics
duration: 12min
completed: 2026-01-23
---

# Phase 27 Plan 01: Timeout & Telemetry Summary

**Configurable focus loss timeout with graceful game termination and comprehensive research telemetry export**

## Performance

- **Duration:** 12 min
- **Started:** 2026-01-23
- **Completed:** 2026-01-23
- **Tasks:** 3/3
- **Files modified:** 2

## Accomplishments
- Added `focus_loss_config()` method to GymScene for researcher configuration
- Implemented timeout enforcement in FocusManager with configurable threshold
- Game ends gracefully when timeout exceeded with custom message support
- Focus loss telemetry included in all three metrics export methods

## Task Commits

Each task was committed atomically:

1. **Task 1: Add focus_loss_config() to GymScene** - `181c0d3` (feat)
2. **Task 2: Add timeout enforcement and game end trigger** - `9ae6f26` (feat)
3. **Task 3: Add focus loss telemetry to metrics export** - `fd77029` (feat)

## Files Created/Modified
- `interactive_gym/scenes/gym_scene.py` - Added focus_loss_timeout_ms, focus_loss_message attributes and focus_loss_config() method
- `interactive_gym/server/static/js/pyodide_multiplayer_game.js` - Added FocusManager timeout methods, _handleFocusLossTimeout(), _showFocusLossTimeoutOverlay(), focusLoss telemetry in exports

## Decisions Made
- **Default timeout: 30 seconds** - Balances allowing brief tab switches with detecting abandonment
- **Timeout check location:** In _handleWorkerTick() after fast-forward check, before background skip - ensures timeout triggers even while backgrounded
- **Reuse overlay pattern:** _showFocusLossTimeoutOverlay follows same pattern as _showPartnerDisconnectedOverlay for consistent UX
- **All export methods:** Focus loss telemetry added to _exportMetrics(), exportValidationData(), and exportMultiplayerMetrics() for comprehensive research data

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- v1.5 Focus Loss Handling milestone complete
- All four phases (24-27) successfully implemented:
  - Phase 24: Web Worker timer for throttle-resistant timing
  - Phase 25: Focus detection with background state management
  - Phase 26: Fast-forward resync on refocus
  - Phase 27: Configurable timeout and telemetry export
- Ready for milestone shipping

---
*Phase: 27-timeout-telemetry*
*Completed: 2026-01-23*
