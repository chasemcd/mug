---
phase: 65-multi-episode-lifecycle-stress-tests
plan: 01
subsystem: testing
tags: [pytest, fixtures, multi-episode, focus-timeout, stress-testing]

# Dependency graph
requires:
  - phase: 64-multi-participant-test-infrastructure
    provides: multi_participant_contexts fixture and GameOrchestrator
provides:
  - flask_server_multi_episode fixture (port 5703, num_episodes=2)
  - flask_server_focus_timeout fixture (port 5704, timeout_ms=10000)
  - Test server configs for STRESS-02 and STRESS-05 scenarios
affects: [65-02-PLAN, 65-03-PLAN, multi-episode-tests, focus-loss-tests]

# Tech tracking
tech-stack:
  added: []
  patterns: [module-scoped-fixtures, test-server-config-variants]

key-files:
  created:
    - interactive_gym/examples/cogrid/overcooked_human_human_multiplayer_multi_episode_test.py
    - interactive_gym/examples/cogrid/overcooked_human_human_multiplayer_focus_timeout_test.py
  modified:
    - tests/conftest.py

key-decisions:
  - "Port 5703 for multi-episode server, 5704 for focus timeout server to avoid conflicts"
  - "Fixture yields include config metadata (num_episodes, focus_timeout_ms) for test introspection"

patterns-established:
  - "Test server config variants: Copy base config and modify specific behavior for test scenario"
  - "Fixture metadata: Include relevant config values in yield dict for test assertions"

# Metrics
duration: 8min
completed: 2026-02-03
---

# Phase 65 Plan 01: Test Server Configs and Fixtures Summary

**Multi-episode (num_episodes=2) and focus timeout (timeout_ms=10000) test server configs with corresponding pytest fixtures on ports 5703 and 5704**

## Performance

- **Duration:** 8 min
- **Started:** 2026-02-03T00:00:00Z
- **Completed:** 2026-02-03T00:08:00Z
- **Tasks:** 3
- **Files created:** 2
- **Files modified:** 1

## Accomplishments
- Multi-episode test server config with num_episodes=2 for back-to-back episode stress testing (STRESS-02)
- Focus timeout test server config with timeout_ms=10000 for focus loss timeout testing (STRESS-05)
- pytest fixtures for both server variants with proper startup/shutdown lifecycle

## Task Commits

Each task was committed atomically:

1. **Task 1: Create multi-episode test server config** - `26a079c` (feat)
2. **Task 2: Create focus timeout test server config** - `d287c7c` (feat)
3. **Task 3: Add pytest fixtures for new server configs** - `36fdfcc` (feat)

## Files Created/Modified
- `interactive_gym/examples/cogrid/overcooked_human_human_multiplayer_multi_episode_test.py` - Server config with num_episodes=2 on port 5703
- `interactive_gym/examples/cogrid/overcooked_human_human_multiplayer_focus_timeout_test.py` - Server config with focus_loss_config(timeout_ms=10000) on port 5704
- `tests/conftest.py` - Added flask_server_multi_episode and flask_server_focus_timeout fixtures

## Decisions Made
- Port 5703 for multi-episode server, 5704 for focus timeout server (avoid conflicts with standard test port 5702)
- Fixtures yield metadata dicts including config values (num_episodes, focus_timeout_ms) for test assertions
- Both configs maintain all other settings identical to standard test config (no RTT limit, 2000ms input confirmation)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Test server configs ready for STRESS-02 (multi-episode) and STRESS-05 (focus timeout) tests
- Fixtures available for use in subsequent test implementation plans
- All configs import and start without errors

---
*Phase: 65-multi-episode-lifecycle-stress-tests*
*Completed: 2026-02-03*
