---
phase: 49-episode-boundary-row-parity
plan: 01
subsystem: testing
tags: [fast-forward, episode-boundary, data-parity, dual-buffer, webrtc]

# Dependency graph
requires:
  - phase: 48-isfocused-column-consistency
    provides: isFocused columns always exported (column parity)
  - phase: 38-episode-boundary
    provides: _promoteRemainingAtBoundary() for episode end data capture
  - phase: 37-fast-forward-fix
    provides: Fast-forward data recording path
provides:
  - Fast-forward respects syncedTerminationFrame boundary
  - _promoteRemainingAtBoundary() filters post-boundary frames
  - Both players export exactly max_steps rows at episode boundary
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "BOUND-02: Cap maxFrame at syncedTerminationFrame in fast-forward"
    - "BOUND-03: Skip frames >= terminationFrame in storeFrameData and promotion"

key-files:
  created: []
  modified:
    - interactive_gym/server/static/js/pyodide_multiplayer_game.js
    - tests/e2e/test_data_comparison.py

key-decisions:
  - "Defense-in-depth: both maxFrame cap and storeFrameData guard for robustness"
  - "Use < comparison (not <=) to exclude termination frame itself"

patterns-established:
  - "BOUND-02/03: Episode boundary guards in async processing paths"

# Metrics
duration: 3min
completed: 2026-02-02
---

# Phase 49 Plan 01: Episode Boundary Row Parity Summary

**Fast-forward and promotion paths now respect syncedTerminationFrame, ensuring both players export identical row counts at episode boundary**

## Performance

- **Duration:** 3 min
- **Started:** 2026-02-02T23:28:35Z
- **Completed:** 2026-02-02T23:31:44Z
- **Tasks:** 3
- **Files modified:** 2

## Accomplishments
- Fast-forward processing capped at syncedTerminationFrame (BOUND-02)
- storeFrameData loop skips frames at or beyond termination frame (BOUND-03)
- _promoteRemainingAtBoundary() filters post-boundary speculative frames
- test_focus_loss_episode_boundary_parity passes without xfail marker

## Task Commits

Each task was committed atomically:

1. **Task 1: Cap fast-forward maxFrame at episode boundary** - `6a95a1a` (fix)
2. **Task 2: Update _promoteRemainingAtBoundary to filter frames** - `48cf0d7` (fix)
3. **Task 3: Remove xfail marker and verify test passes** - `420b9af` (test)

## Files Created/Modified
- `interactive_gym/server/static/js/pyodide_multiplayer_game.js` - Added BOUND-02/03 guards in fast-forward and promotion paths
- `tests/e2e/test_data_comparison.py` - Removed xfail marker and NOTE from test_focus_loss_episode_boundary_parity

## Decisions Made
- Defense-in-depth approach: added boundary check both when computing maxFrame AND when storing frame data
- Use strict less-than comparison (frame >= terminationFrame means skip) to match existing pattern in _processStep()
- Track and log skipped frames in both locations for debugging visibility

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None - implementation followed plan precisely.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Both focus loss parity tests now pass: test_focus_loss_mid_episode_parity and test_focus_loss_episode_boundary_parity
- Phase 49 (Episode Boundary Row Parity) complete
- Ready for Phase 50 (if planned)

---
*Phase: 49-episode-boundary-row-parity*
*Completed: 2026-02-02*
