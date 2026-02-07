---
phase: 40-test-infrastructure
plan: 01
subsystem: testing
tags: [pytest, playwright, e2e, browser-automation, fixtures]

# Dependency graph
requires: []
provides:
  - Flask server lifecycle fixture (start/stop subprocess)
  - Dual browser context fixture for multiplayer testing
  - Smoke test validating infrastructure
affects: [41-latency-injection, 42-network-disruption, 43-data-comparison]

# Tech tracking
tech-stack:
  added: [pytest>=8.0, playwright>=1.49, pytest-playwright>=0.6, pytest-timeout>=2.3]
  patterns: [module-scoped fixtures for expensive resources, function-scoped fixtures for test isolation]

key-files:
  created:
    - tests/conftest.py
    - tests/__init__.py
    - tests/e2e/__init__.py
    - tests/e2e/test_infrastructure.py
  modified:
    - setup.py

key-decisions:
  - "Test deps in setup.py extras_require (not pyproject.toml project section - package uses legacy setup.py)"
  - "flask_server fixture uses HTTP polling (not requests) to avoid extra dependencies"
  - "Server fixture scope=module (expensive), player_contexts scope=function (isolation)"

patterns-established:
  - "Fixture hierarchy: module-scoped for expensive resources, function-scoped for test isolation"
  - "Server health check: HTTPConnection polling with 30 retries at 1s intervals"
  - "Multiplayer testing: two isolated browser contexts via browser.new_context()"

# Metrics
duration: 3min
completed: 2026-01-31
---

# Phase 40 Plan 01: Test Infrastructure Foundation Summary

**Playwright + pytest infrastructure with Flask server lifecycle management and dual browser contexts for multiplayer E2E testing**

## Performance

- **Duration:** 3 min 16 sec
- **Started:** 2026-01-31T07:54:05Z
- **Completed:** 2026-01-31T07:57:21Z
- **Tasks:** 3/3
- **Files modified:** 5

## Accomplishments

- Test dependencies defined in setup.py `extras_require["test"]`
- Flask server fixture starts subprocess, polls for readiness, terminates on cleanup
- Dual browser context fixture provides isolated sessions for two players
- Smoke test validates infrastructure works end-to-end

## Task Commits

Each task was committed atomically:

1. **Task 1: Add test dependencies to setup.py** - `28a224a` (chore)
2. **Task 2: Create test directory structure and conftest fixtures** - `221a5e3` (feat)
3. **Task 3: Create smoke test validating fixtures work** - `a388fe0` (test)

## Files Created/Modified

- `setup.py` - Added test extras_require with pytest, playwright, pytest-playwright, pytest-timeout
- `tests/__init__.py` - Package marker
- `tests/conftest.py` - Shared fixtures: flask_server (module-scoped), player_contexts (function-scoped)
- `tests/e2e/__init__.py` - E2E test package marker
- `tests/e2e/test_infrastructure.py` - Smoke test verifying server starts and browsers connect

## Decisions Made

1. **Test dependencies in setup.py, not pyproject.toml** - Package uses legacy setup.py with `extras_require`. Adding `[project.optional-dependencies]` requires `[project]` with version field, which would duplicate setup.py metadata.

2. **HTTP health check with http.client** - Used `http.client.HTTPConnection` instead of requests to avoid extra test dependency.

3. **Module-scoped flask_server fixture** - Server startup is expensive (~2-3s), so starts once per test module, not per test.

4. **Function-scoped player_contexts fixture** - Fresh browser contexts for each test ensures test isolation.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- **NumPy version incompatibility** - Initial test run failed due to NumPy 2.x incompatibility with pandas compiled for NumPy 1.x. Downgraded numpy to <2 to resolve. This is an environment issue, not a test infrastructure problem - the fixture correctly detected and reported the server crash.

## User Setup Required

After installing the package with test dependencies, users must install Playwright browsers:
```bash
pip install -e ".[test]"
playwright install chromium
```

## Next Phase Readiness

- Test infrastructure is ready for Phase 41 (Latency Injection Tests)
- `flask_server` fixture provides running server for game automation
- `player_contexts` fixture provides two browsers for multiplayer scenarios
- Smoke test confirms infrastructure works end-to-end

---
*Phase: 40-test-infrastructure*
*Completed: 2026-01-31*
