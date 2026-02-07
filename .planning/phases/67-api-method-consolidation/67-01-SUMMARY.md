---
phase: 67-api-method-consolidation
plan: 01
subsystem: api
tags: [builder-pattern, method-chaining, gym-scene, pyodide, multiplayer]

# Dependency graph
requires:
  - phase: none
    provides: existing GymScene with 14 builder methods
provides:
  - "runtime() builder method (6 browser execution params)"
  - "multiplayer() builder method (26 multiplayer params from 8 old methods)"
affects:
  - 67-02 (content/waitroom/assets methods)
  - 68 (old method removal)
  - 69 (example migration)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Consolidated builder methods coexisting with old methods during migration"
    - "NotProvided sentinel for optional param detection"
    - "Auto-enable side effect pattern (continuous_monitoring_enabled)"

key-files:
  created: []
  modified:
    - interactive_gym/scenes/gym_scene.py

key-decisions:
  - "runtime() contains only 6 browser execution params (no sync/multiplayer params)"
  - "multiplayer() merges all 8 old multiplayer methods into one with 26 params"
  - "Old methods left completely untouched for backward compatibility (removal is Phase 68)"
  - "multiplayer param maps to self.pyodide_multiplayer (not self.multiplayer) to preserve attribute names"

patterns-established:
  - "New methods added alongside old ones: both work simultaneously"
  - "Parameter-to-attribute mapping preserves all existing internal attribute names"

# Metrics
duration: 4min
completed: 2026-02-07
---

# Phase 67 Plan 01: Add runtime() and multiplayer() Builder Methods Summary

**Added runtime() with 6 browser params and multiplayer() with 26 params merging 8 old methods, all coexisting alongside unchanged old methods**

## Performance

- **Duration:** 4 min
- **Started:** 2026-02-07T22:39:17Z
- **Completed:** 2026-02-07T22:45:31Z
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments
- Added `runtime()` method with 6 browser execution params (run_through_pyodide, environment_initialization_code, environment_initialization_code_filepath, on_game_step_code, packages_to_install, restart_pyodide)
- Added `multiplayer()` method consolidating params from pyodide sync (7), matchmaking (3), player_grouping (2), continuous_monitoring (6+1), exclusion_callbacks (2), reconnection_config (1), partner_disconnect_message_config (2), focus_loss_config (3)
- All validation logic preserved exactly from source methods
- Auto-enable continuous_monitoring when monitoring params provided
- All 8 old methods remain untouched and fully functional

## Task Commits

Each task was committed atomically:

1. **Task 1: Add runtime() method** - `895aa3a` (feat)
2. **Task 2: Add multiplayer() method** - `4461194` (feat)

## Files Created/Modified
- `interactive_gym/scenes/gym_scene.py` - Added runtime() and multiplayer() builder methods

## Decisions Made
- Copied validation logic verbatim from old methods to ensure identical behavior
- Used `_monitoring_param_provided` flag to track auto-enable logic cleanly
- Preserved all 4 non-obvious parameter-to-attribute mappings (multiplayer->pyodide_multiplayer, max_rtt->matchmaking_max_rtt, matchmaker->_matchmaker, continuous_callback->continuous_exclusion_callback)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Plan 67-02 (content/waitroom/assets methods) can proceed immediately
- All old methods intact for Phase 68 removal
- All 27 existing unit tests still pass

---
*Phase: 67-api-method-consolidation*
*Completed: 2026-02-07*
