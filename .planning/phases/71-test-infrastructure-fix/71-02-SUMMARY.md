---
phase: 71-test-infrastructure-fix
plan: 02
subsystem: testing
tags: [pytest, module-isolation, fixture-scope, flask-server, focus-loss]

# Dependency graph
requires:
  - phase: 71-test-infrastructure-fix
    plan: 01
    provides: "Robust server fixture lifecycle with port verification and shared teardown helpers"
provides:
  - "Isolated test module for test_focus_loss_episode_boundary_parity with fresh flask_server instance"
  - "Gap closure: 5th test no longer runs on exhausted server state"
affects: [72-latency-diagnosis, 73-network-regression-validation, 74-stability-certification]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Module isolation for server state exhaustion: move test to own module to get fresh module-scoped fixture"

key-files:
  created:
    - "tests/e2e/test_focus_loss_data_parity.py"
  modified:
    - "tests/e2e/test_data_comparison.py"

key-decisions:
  - "Extract test to own module rather than changing fixture scope or adding server state cleanup"
  - "Copy clean_data_dir fixture to new module (function-scoped, not shared via conftest)"
  - "Do not remove any imports from test_data_comparison.py (remaining tests still use them all)"

patterns-established:
  - "Module isolation: when a module-scoped fixture exhausts server state, move long-tail tests to their own module"

# Metrics
duration: 4min
completed: 2026-02-06
---

# Phase 71 Plan 02: Gap Closure - Isolate Focus Loss Boundary Test Summary

**Extracted test_focus_loss_episode_boundary_parity to its own module, eliminating server state exhaustion failure by giving it a fresh flask_server instance**

## Performance

- **Duration:** 4 min
- **Started:** 2026-02-06T18:41:42Z
- **Completed:** 2026-02-06T18:45:55Z
- **Tasks:** 2 (1 code change + 1 verification)
- **Files modified:** 2

## Accomplishments

- Extracted `test_focus_loss_episode_boundary_parity` from `test_data_comparison.py` into its own module `test_focus_loss_data_parity.py`
- All 5 tests pass back-to-back: 4 data comparison tests + 1 focus loss boundary test (132s total)
- Server state exhaustion gap fully closed: the 5th test gets a fresh `flask_server` in its new module
- No Page.goto timeouts during back-to-back module execution
- All ports (5702-5706) clean after test completion

## Task Commits

Each task was committed atomically:

1. **Task 1: Extract test_focus_loss_episode_boundary_parity to its own module** - `646d6ef` (refactor)
2. **Task 2: Verify the extracted test passes after other test suites** - No commit (verification-only task, no code changes)

**Plan metadata:** (see final commit)

## Files Created/Modified

- `tests/e2e/test_focus_loss_data_parity.py` - New module containing `test_focus_loss_episode_boundary_parity` with its own `clean_data_dir` fixture and all required imports
- `tests/e2e/test_data_comparison.py` - Removed `test_focus_loss_episode_boundary_parity` function (lines 504-613); retains 4 remaining tests unchanged

## Decisions Made

1. **Module isolation over fixture scope change:** Extracting the test to its own module is the simplest fix -- it leverages the existing module-scoped `flask_server` fixture to get a fresh server instance without changing any fixture scopes or adding server state cleanup logic.

2. **Copy clean_data_dir to new module:** The `clean_data_dir` fixture is function-scoped and defined locally in `test_data_comparison.py`. The new module needs its own copy since it is not shared via conftest.py.

3. **Preserve all imports in test_data_comparison.py:** The remaining 4 tests still use `set_tab_visibility`, `wait_for_focus_manager_state`, `run_full_episode_flow_until_gameplay`, `apply_latency`, `start_random_actions`, and `stop_random_actions`. No imports were removed.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None - all 5 tests passed on the first run with no issues.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Phase 71 gap closure complete: all server fixture infrastructure issues resolved
- test_focus_loss_episode_boundary_parity passes reliably in its own module (fresh server)
- All 4 data comparison tests continue to pass (no regression)
- Ready for Phase 72 (Latency Diagnosis) to investigate test_episode_completion_under_fixed_latency[chromium-200] timeout

---
*Phase: 71-test-infrastructure-fix*
*Completed: 2026-02-06*
