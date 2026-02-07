---
phase: 75-merged-loading-screen
plan: 01
subsystem: ui, config
tags: [pyodide, loading-screen, experiment-config, html]

# Dependency graph
requires:
  - phase: 69-server-init-grace
    provides: LOADING_CLIENTS and is_client_in_loading_grace() server-side grace period
  - phase: 67-pyodide-preload-infrastructure
    provides: get_pyodide_config() in ExperimentConfig and RemoteConfig, #pyodideLoader HTML element
provides:
  - pyodide_load_timeout_s configurable attribute on ExperimentConfig and RemoteConfig
  - Dynamic server-side loading grace timeout from config (not hardcoded)
  - Single unified #loadingScreen HTML element replacing #screeningLoader and #pyodideLoader
affects:
  - 75-02 (client-side JS wiring of loadingGate and timeout logic)
  - 76 (test cleanup may reference changed HTML element IDs)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Config-driven server timeouts via getattr(CONFIG, 'pyodide_load_timeout_s', LOADING_TIMEOUT_S)"

key-files:
  created: []
  modified:
    - interactive_gym/configurations/experiment_config.py
    - interactive_gym/configurations/remote_config.py
    - interactive_gym/server/app.py
    - interactive_gym/server/static/templates/index.html

key-decisions:
  - "pyodide_load_timeout_s included in both early-return and normal paths of ExperimentConfig.get_pyodide_config()"
  - "Server-side is_client_in_loading_grace() reads from CONFIG with LOADING_TIMEOUT_S as fallback"
  - "CSS selectors updated from #screeningLoader/#screeningStatus to #loadingScreen/#loadingStatus"

patterns-established:
  - "Config-driven timeout: server reads pyodide_load_timeout_s from CONFIG via getattr with hardcoded fallback"

# Metrics
duration: 2min
completed: 2026-02-07
---

# Phase 75 Plan 01: Server Config & Unified HTML Loading Element Summary

**Configurable pyodide_load_timeout_s on both config classes, dynamic server grace timeout, and single #loadingScreen HTML element replacing dual loaders**

## Performance

- **Duration:** 2 min
- **Started:** 2026-02-07T02:20:35Z
- **Completed:** 2026-02-07T02:22:19Z
- **Tasks:** 2/2
- **Files modified:** 4

## Accomplishments
- Added `pyodide_load_timeout_s` (default 60) to both ExperimentConfig and RemoteConfig, included in `get_pyodide_config()` return dicts
- Server-side `is_client_in_loading_grace()` now reads timeout dynamically from CONFIG instead of hardcoded constant
- Replaced separate `#screeningLoader` and `#pyodideLoader` HTML divs with single unified `#loadingScreen` element
- Updated CSS selectors to match new element IDs while reusing existing `.screening-spinner` class

## Task Commits

Each task was committed atomically:

1. **Task 1: Add pyodide_load_timeout_s to config classes and server** - `8726973` (feat)
2. **Task 2: Unify HTML loading elements into single #loadingScreen** - `5e7695d` (feat)

## Files Created/Modified
- `interactive_gym/configurations/experiment_config.py` - Added `pyodide_load_timeout_s` attribute and included in `get_pyodide_config()` (both early-return and normal paths)
- `interactive_gym/configurations/remote_config.py` - Added `pyodide_load_timeout_s` attribute and included in `get_pyodide_config()`
- `interactive_gym/server/app.py` - `is_client_in_loading_grace()` reads timeout from `CONFIG.pyodide_load_timeout_s` with `LOADING_TIMEOUT_S` fallback
- `interactive_gym/server/static/templates/index.html` - Replaced `#screeningLoader` + `#pyodideLoader` with single `#loadingScreen`, updated CSS selectors

## Decisions Made
- **Early-return path fix:** ExperimentConfig.get_pyodide_config() has an early return when `self.stager is None` -- `pyodide_load_timeout_s` added to both paths to ensure the field is always present
- **Fallback pattern:** `getattr(CONFIG, 'pyodide_load_timeout_s', LOADING_TIMEOUT_S)` preserves the module-level constant as a safe fallback while preferring config
- **CSS update:** Renamed `#screeningLoader` to `#loadingScreen` and `#screeningStatus` to `#loadingStatus` in both CSS and HTML for consistency

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed missing pyodide_load_timeout_s in ExperimentConfig early-return path**
- **Found during:** Task 1 (verification step)
- **Issue:** `ExperimentConfig.get_pyodide_config()` has an early return when `self.stager is None` that did not include the new field, causing the verification assertion to fail
- **Fix:** Added `"pyodide_load_timeout_s": self.pyodide_load_timeout_s` to the early-return dict
- **Files modified:** interactive_gym/configurations/experiment_config.py
- **Verification:** `ExperimentConfig().get_pyodide_config()` returns dict with `pyodide_load_timeout_s` key
- **Committed in:** 8726973 (Task 1 commit)

**2. [Rule 1 - Bug] Updated CSS selectors to match renamed HTML elements**
- **Found during:** Task 2
- **Issue:** Plan only specified HTML div replacement but CSS still targeted `#screeningLoader` and `#screeningStatus` which no longer exist
- **Fix:** Updated CSS selectors from `#screeningLoader` to `#loadingScreen` and `#screeningStatus` to `#loadingStatus`
- **Files modified:** interactive_gym/server/static/templates/index.html
- **Verification:** All old IDs return 0 matches, new IDs properly styled
- **Committed in:** 5e7695d (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (2 bugs)
**Impact on plan:** Both fixes necessary for correctness. No scope creep.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- HTML `#loadingScreen` element ready for Plan 02 to wire up with client-side JavaScript
- `pyodide_load_timeout_s` field available in `experiment_config` socket event payload for client-side timeout logic
- Plan 02 will implement the `loadingGate` pattern, timeout handling, and error display using these foundations

---
*Phase: 75-merged-loading-screen*
*Completed: 2026-02-07*
