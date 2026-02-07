---
phase: 75-merged-loading-screen
verified: 2026-02-07T03:00:00Z
status: passed
score: 4/4 must-haves verified
gaps: []
---

# Phase 75: Merged Loading Screen Verification Report

**Phase Goal:** Participants see a single loading screen that gates on both compatibility check and Pyodide readiness
**Verified:** 2026-02-07T03:00:00Z
**Status:** passed
**Re-verification:** No -- initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Participant sees exactly one loading screen during pre-game setup (no separate Pyodide spinner) | VERIFIED | index.html has single `#loadingScreen` div (line 287). Zero matches for `screeningLoader`, `pyodideLoader` in both HTML and JS. CSS targets `#loadingScreen` (line 236). Old `showPyodideProgress`/`hidePyodideProgress` functions deleted from index.js. |
| 2 | Loading screen does not advance until both compatibility check passes AND Pyodide is ready | VERIFIED | `checkLoadingGate()` (index.js line 225) requires both `loadingGate.screeningComplete` AND `loadingGate.pyodideComplete` (line 241) before resolving gate. Called from 7 locations: screening completion paths (lines 721, 728, 736), Pyodide completion paths (lines 292, 326, 336), and timeout path (line 679). |
| 3 | Pyodide loading timeout is configurable via experiment config (defaults to 60s) | VERIFIED | `ExperimentConfig.pyodide_load_timeout_s = 60` (experiment_config.py line 46), included in `get_pyodide_config()` both early-return (line 237) and normal (line 253) paths. `RemoteConfig.pyodide_load_timeout_s = 60` (remote_config.py line 93), included in `get_pyodide_config()` (line 445). Server emits via `experiment_config` event (app.py line 377). Client reads `data.pyodide_config.pyodide_load_timeout_s` with `|| 60` fallback (index.js line 670). Server-side grace uses `getattr(CONFIG, 'pyodide_load_timeout_s', LOADING_TIMEOUT_S)` (app.py line 156). |
| 4 | If Pyodide fails or times out, participant sees a clear error page instead of hanging | VERIFIED | Timeout path (index.js line 671-681): `setTimeout` fires after configurable seconds, sets `pyodideSuccess = false`, calls `checkLoadingGate()`. Error path in `preloadPyodide` catch (lines 331-338): sets `pyodideSuccess = false`, calls `checkLoadingGate()`. `checkLoadingGate()` (line 264-267) detects `!pyodideSuccess` and calls `showExclusionMessage('Failed to load the Python runtime...')`. `showExclusionMessage()` (line 568) is a substantive function that hides interactive elements and displays error text. |

**Score:** 4/4 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `interactive_gym/configurations/experiment_config.py` | `pyodide_load_timeout_s` attribute and inclusion in `get_pyodide_config()` | VERIFIED | Line 46: `self.pyodide_load_timeout_s: int = 60`. Lines 237, 253: included in return dict. 300 lines total. |
| `interactive_gym/configurations/remote_config.py` | `pyodide_load_timeout_s` attribute and inclusion in `get_pyodide_config()` | VERIFIED | Line 93: `self.pyodide_load_timeout_s: int = 60`. Line 445: included in return dict. 501 lines total. |
| `interactive_gym/server/app.py` | Dynamic `LOADING_TIMEOUT_S` from config | VERIFIED | Line 156: `getattr(CONFIG, 'pyodide_load_timeout_s', LOADING_TIMEOUT_S)` inside `is_client_in_loading_grace()`. Hardcoded fallback preserved at line 143. |
| `interactive_gym/server/static/templates/index.html` | Single unified loading screen element | VERIFIED | Line 287: single `#loadingScreen` div. Lines 236-263: CSS for `#loadingScreen`, `.screening-spinner`, `#loadingStatus`. Zero references to old IDs. 342 lines total. |
| `interactive_gym/server/static/js/index.js` | Loading gate logic, unified loading screen, timeout, error handling | VERIFIED | Lines 209-218: `loadingGate` object. Lines 225-278: `checkLoadingGate()` function. Lines 287-340: updated `preloadPyodide()`. Lines 650-738: refactored `experiment_config` handler. 34 references to `loadingGate`. 1806 lines total. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `experiment_config.py` / `remote_config.py` | `app.py` | `get_pyodide_config()` dict consumed by experiment_config emission | WIRED | app.py line 377: `CONFIG.get_pyodide_config()` added to experiment_config_data. Line 379: emitted to client. |
| `app.py` (server) | `index.js` (client) | `experiment_config` socket event carries `pyodide_config` with `pyodide_load_timeout_s` | WIRED | Client handler (line 651) processes `data.pyodide_config`. Line 670: reads `pyodide_load_timeout_s`. |
| `experiment_config` handler | `loadingGate` object | Handler creates gate signals, starts preload and screening | WIRED | Handler shows loading screen (line 662), starts preloadPyodide (line 666), starts timeout (line 671), runs screening (line 707), all paths call `checkLoadingGate()`. |
| `preloadPyodide()` | `checkLoadingGate()` | preloadPyodide sets `loadingGate.pyodideComplete` and calls `checkLoadingGate` | WIRED | Non-Pyodide path (lines 290-292), success path (lines 324-326), error path (lines 334-336) all set gate flags and call `checkLoadingGate()`. |
| `checkLoadingGate()` | `showExclusionMessage()` or `processPendingScene()` | Gate resolves to error page or scene dispatch | WIRED | Screening failure: line 259 calls `showExclusionMessage()`. Pyodide failure: line 266 calls `showExclusionMessage()`. Both pass: line 273 calls `processPendingScene()` or line 276 requests current scene. |
| `app.py` `is_client_in_loading_grace()` | CONFIG timeout | Uses config-based timeout with fallback | WIRED | Line 156: `getattr(CONFIG, 'pyodide_load_timeout_s', LOADING_TIMEOUT_S)`. |

### Requirements Coverage

| Requirement | Status | Blocking Issue |
|-------------|--------|----------------|
| LOAD-01: Single loading screen | SATISFIED | None -- single `#loadingScreen` element, zero old loader references |
| LOAD-02: Gates on both compat check AND Pyodide | SATISFIED | None -- `checkLoadingGate()` requires both complete before resolution |
| LOAD-03: Configurable timeout (default 60s) | SATISFIED | None -- `pyodide_load_timeout_s` in both config classes, flows to client and server |
| LOAD-04: Clear error page on failure/timeout | SATISFIED | None -- timeout and error paths call `showExclusionMessage()` with user-friendly text |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| None | -- | -- | -- | No TODO, FIXME, placeholder, stub, or empty implementation patterns found in modified files |

### Human Verification Required

### 1. Visual Loading Screen Appearance

**Test:** Open the experiment in a browser with a Pyodide-requiring scene. Observe the loading screen that appears.
**Expected:** A single spinner with status text ("Checking compatibility..." then "Loading Python runtime..." then "Installing packages...") appears. No flash of a second loader. Screen hides when both checks pass.
**Why human:** Visual rendering, spinner animation, and text transitions cannot be verified through static code analysis.

### 2. Timeout Error Display

**Test:** Configure `pyodide_load_timeout_s = 5` on the experiment config. Block CDN access to Pyodide (e.g., via browser DevTools Network blocking). Connect to the experiment.
**Expected:** After 5 seconds, the loading screen is replaced with an error page reading "Failed to load the Python runtime. Please refresh the page or try a different browser."
**Why human:** Requires real browser environment with network manipulation to trigger timeout path.

### 3. Non-Pyodide Experiment Not Affected

**Test:** Run an experiment with no Pyodide scenes. Observe behavior.
**Expected:** Loading screen appears briefly (during screening only), then disappears. No Pyodide-related delays or errors.
**Why human:** Requires running actual server with non-Pyodide configuration.

### 4. Reconnect After Loading Does Not Re-show Loading Screen

**Test:** Complete the loading screen, then simulate a socket reconnection (e.g., disconnect/reconnect network briefly).
**Expected:** Loading screen does NOT re-appear. `gateResolved` guard prevents the `experiment_config` handler from re-showing it.
**Why human:** Requires real socket reconnection behavior which cannot be verified statically.

### Gaps Summary

No gaps found. All four observable truths are verified through code-level evidence:

1. **Single loading screen:** HTML contains exactly one `#loadingScreen` element; all references to old `#screeningLoader` and `#pyodideLoader` have been removed from HTML, CSS, and JavaScript.

2. **Dual-gate advancement:** The `checkLoadingGate()` function enforces both `screeningComplete` AND `pyodideComplete` before resolving. It is called from all completion paths (screening pass/fail, Pyodide success/error/non-Pyodide, timeout).

3. **Configurable timeout:** The `pyodide_load_timeout_s` attribute exists on both config classes with a default of 60, flows through the server `experiment_config` socket event to the client, and is used in both client-side `setTimeout` and server-side `is_client_in_loading_grace()`.

4. **Error page on failure:** Both timeout and error paths set `pyodideSuccess = false` and call `checkLoadingGate()`, which calls `showExclusionMessage()` with a clear user-facing error message.

E2E smoke tests were reported as passing in the 75-02-SUMMARY (2 multiplayer basic tests), confirming the full flow works end-to-end.

---

_Verified: 2026-02-07T03:00:00Z_
_Verifier: Claude (gsd-verifier)_
