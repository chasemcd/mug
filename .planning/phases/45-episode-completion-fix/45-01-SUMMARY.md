---
phase: 45-episode-completion-fix
plan: 01
subsystem: testing
tags: [playwright, e2e, focus-management, visibility-api]

# Dependency graph
requires:
  - phase: 40-test-infrastructure
    provides: E2E test fixtures and game automation helpers
  - phase: 25-focus-detection
    provides: FocusManager class and visibility handling
provides:
  - Working E2E test visibility override enabling frame advancement
  - Fixed test flows removing obsolete tutorial scene calls
  - set_tab_visibility integration in shared game helper
affects: [46-remaining-test-fixes, 47-test-suite-validation]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Visibility override pattern: call set_tab_visibility after wait_for_game_object"

key-files:
  created: []
  modified:
    - tests/fixtures/game_helpers.py
    - tests/e2e/test_multiplayer_basic.py
    - tests/e2e/test_latency_injection.py
    - tests/e2e/test_data_comparison.py
    - tests/e2e/test_network_disruption.py

key-decisions:
  - "Visibility override placed after wait_for_game_object (FocusManager must exist)"
  - "Removed complete_tutorial_and_advance calls (tutorial scene removed in 607b60a)"
  - "Override added to both shared helper and individual test flows for completeness"

patterns-established:
  - "Visibility override pattern: In Playwright E2E tests, always call set_tab_visibility(page, True) after wait_for_game_object() to prevent FocusManager from blocking frame processing"

# Metrics
duration: 32min
completed: 2026-02-02
---

# Phase 45 Plan 01: Episode Completion Fix Summary

**Fixed E2E test frame advancement by overriding document.hidden for Playwright, enabling games to progress through frames and complete episodes within timeout**

## Performance

- **Duration:** ~32 min (including checkpoint verification)
- **Started:** 2026-02-02T18:58:32Z
- **Completed:** 2026-02-02T19:16:11Z
- **Tasks:** 2 (1 auto task + 1 checkpoint)
- **Files modified:** 5

## Accomplishments

- Diagnosed root cause: Playwright sets `document.hidden = true`, causing FocusManager to skip all frame processing
- Added `set_tab_visibility(page, True)` override to shared `run_full_episode_flow_until_gameplay()` helper
- Fixed all 4 E2E test files by removing obsolete `complete_tutorial_and_advance()` calls and adding visibility override
- Verified fix with `test_two_players_connect_and_complete_episode` passing in 31.53s

## Task Commits

Each task was committed atomically:

1. **Task 1: Add visibility override to shared helper and fix test flows** - `03ca482` (fix)
2. **Task 2: Checkpoint verification** - (no commit - user verification only)

**Plan metadata:** (this commit)

## Files Created/Modified

- `tests/fixtures/game_helpers.py` - Added set_tab_visibility import and calls after wait_for_game_object in run_full_episode_flow_until_gameplay()
- `tests/e2e/test_multiplayer_basic.py` - Removed complete_tutorial_and_advance calls, added visibility override
- `tests/e2e/test_latency_injection.py` - Removed complete_tutorial_and_advance calls, added visibility override
- `tests/e2e/test_data_comparison.py` - Removed complete_tutorial_and_advance calls, added visibility override
- `tests/e2e/test_network_disruption.py` - Removed complete_tutorial_and_advance calls, added visibility override

## Decisions Made

1. **Visibility override placement:** Override must come AFTER `wait_for_game_object()` because FocusManager doesn't exist until game initializes
2. **Removed tutorial calls:** The `complete_tutorial_and_advance()` helper was calling code for a tutorial scene that was removed in commit 607b60a - these calls were causing test failures
3. **Shared helper vs individual tests:** Added override to both the shared `run_full_episode_flow_until_gameplay()` helper AND individual test flows to ensure all code paths are covered

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None - the fix worked as expected on first verification.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- E2E tests now advance frames and complete episodes
- Phase 46 can proceed to fix any remaining test failures
- Phase 47 can validate full test suite passes

**Test verification result:** `test_two_players_connect_and_complete_episode` passed in 31.53s (previously timed out)

---
*Phase: 45-episode-completion-fix*
*Completed: 2026-02-02*
