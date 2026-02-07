---
phase: 71-test-infrastructure-fix
plan: 01
subsystem: testing
tags: [pytest, subprocess, port-management, fixture-teardown, process-lifecycle]

# Dependency graph
requires:
  - phase: 40-test-infrastructure
    provides: "Original server fixtures in tests/conftest.py"
provides:
  - "Robust server fixture lifecycle with port verification (_is_port_free, _ensure_port_available, _teardown_server, _wait_for_port_free)"
  - "DRY shared teardown helpers used by all 5 server fixtures"
  - "Pre-startup port cleanup to handle stale processes from crashed test runs"
  - "Process group isolation via start_new_session=True"
affects: [72-latency-diagnosis, 73-network-regression-validation, 74-stability-certification]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Port-verified teardown: poll _is_port_free() after process kill instead of sleep-based delays"
    - "Pre-startup cleanup: _ensure_port_available() with lsof before Popen"
    - "Process group isolation: start_new_session=True + os.killpg for child process cleanup"
    - "stdout=DEVNULL: prevent pipe buffer deadlock on long-running server subprocesses"

key-files:
  created: []
  modified:
    - "tests/conftest.py"

key-decisions:
  - "Use socket.bind() for port checks (not connect-based, which succeeds during TIME_WAIT)"
  - "lsof for stale PID discovery as last-resort cleanup in _ensure_port_available"
  - "stdout=DEVNULL for all fixtures (stderr kept as PIPE for crash diagnostics only)"
  - "flask_server_multi_episode: read stderr before teardown, write empty bytes for stdout debug file"

patterns-established:
  - "Port-verified teardown: _teardown_server(process, port) replaces inline terminate/kill/sleep"
  - "Pre-startup cleanup: _ensure_port_available(port) before every Popen call"
  - "Shared helpers at module top: _is_port_free, _ensure_port_available, _wait_for_port_free, _teardown_server"

# Metrics
duration: 8min
completed: 2026-02-06
---

# Phase 71 Plan 01: Test Infrastructure Fix Summary

**Robust server fixture teardown with port-availability verification and shared helpers, eliminating Page.goto timeouts at module boundaries**

## Performance

- **Duration:** 8 min
- **Started:** 2026-02-06T18:16:53Z
- **Completed:** 2026-02-06T18:25:24Z
- **Tasks:** 2 (1 code change + 1 verification)
- **Files modified:** 1

## Accomplishments

- All 5 server fixtures refactored to use shared `_teardown_server()` and `_ensure_port_available()` helpers (DRY)
- Port-verified teardown replaces hope-based `time.sleep(3)` hacks and bare `terminate()` calls
- Between-module test execution (test_data_comparison -> test_multiplayer_basic) succeeds with no Page.goto timeouts
- All Popen calls use `start_new_session=True` and `stdout=subprocess.DEVNULL`
- No stale processes remain on ports 5702-5706 after test completion

## Task Commits

Each task was committed atomically:

1. **Task 1: Add shared teardown helpers and refactor all server fixtures** - `2e61920` (feat)
2. **Task 2: Verify back-to-back test suite execution** - No commit (verification-only task, no code changes)

**Plan metadata:** (see final commit)

## Files Created/Modified

- `tests/conftest.py` - Added 4 shared helpers (_is_port_free, _ensure_port_available, _wait_for_port_free, _teardown_server) and refactored all 5 server fixtures to use them

## Decisions Made

1. **socket.bind() over connect-based port checks:** `_is_port_free()` uses `socket.bind()` with `SO_REUSEADDR` because connect-based checks can succeed during TCP TIME_WAIT, giving false negatives.

2. **lsof for stale PID discovery:** `_ensure_port_available()` uses `lsof -ti :{port}` to find and kill stale processes. Wrapped in try/except for FileNotFoundError (lsof missing on some systems) and TimeoutExpired.

3. **stdout=DEVNULL for all fixtures:** Prevents pipe buffer deadlock when server runs for extended periods (module-scoped fixtures serve multiple tests). stderr kept as PIPE for crash diagnostics in the retry loop.

4. **flask_server_multi_episode stderr handling:** Since stdout is now DEVNULL, the teardown reads stderr before calling `_teardown_server` (which kills the process), writes empty bytes to the stdout debug file, and writes stderr to the stderr debug file.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

### test_focus_loss_episode_boundary_parity still fails when run after 4 other tests in same module

- **What:** Running the full `test_data_comparison.py` module (5 tests), the 5th test `test_focus_loss_episode_boundary_parity` fails with `Page.goto: Timeout 30000ms exceeded` on port 5702.
- **Root cause:** The module-scoped `flask_server` fixture (port 5702) is NOT torn down between tests within the same module. After serving 4 full game sessions, the server becomes unresponsive (likely eventlet/socketio state accumulation). This is a server state issue, NOT a port teardown issue.
- **Evidence:**
  - The test passes in isolation (32.57s)
  - Between-module transitions work correctly (4 data_comparison tests -> 2 multiplayer_basic tests, all 6 pass)
  - Port 5702 is properly freed between modules by `_teardown_server`
- **Phase 71 scope:** This issue is outside Phase 71's scope (infrastructure/teardown only). The server state accumulation issue would require a different fix (e.g., making the fixture function-scoped for this test, or adding server state cleanup between tests).

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Infrastructure fix complete: all 5 fixtures now have robust startup/teardown
- Between-module port handoff verified working (test_data_comparison -> test_multiplayer_basic)
- Ready for Phase 72 (Latency Diagnosis) which can run test_latency_injection with confidence
- **Known remaining issue:** test_focus_loss_episode_boundary_parity fails within its module when preceded by 4 other tests -- this is a server state issue, not infrastructure. May need to be addressed in Phase 72 or 73 if it blocks validation.

---
*Phase: 71-test-infrastructure-fix*
*Completed: 2026-02-06*
