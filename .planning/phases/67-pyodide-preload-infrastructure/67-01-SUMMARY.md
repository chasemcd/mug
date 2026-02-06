---
phase: 67-pyodide-preload-infrastructure
plan: 01
subsystem: pyodide-preload
tags: [pyodide, preload, experiment-config, client-ui, advancement-gating]

dependency-graph:
  requires: []
  provides:
    - "ExperimentConfig.get_pyodide_config() scans stager scenes for Pyodide requirements"
    - "RemoteConfig.get_pyodide_config() returns own pyodide settings"
    - "RemoteConfig.get_entry_screening_config() returns safe defaults"
    - "pyodide_config included in experiment_config socket event"
    - "preloadPyodide() function loads Pyodide during compat check screen"
    - "window.pyodideInstance stores pre-loaded Pyodide for Phase 68"
    - "Advance button gated on Pyodide readiness"
  affects:
    - "Phase 68: Shared Instance Integration (game classes reuse window.pyodideInstance)"
    - "Phase 69: Server-side init grace (may need ping tolerance during preload)"

tech-stack:
  added: []
  patterns:
    - "Fire-and-forget async preload concurrent with entry screening"
    - "window.pyodidePreloadStatus state machine (idle/loading/ready/error)"
    - "Polling-based advancement gating (500ms interval)"

key-files:
  created: []
  modified:
    - interactive_gym/configurations/experiment_config.py
    - interactive_gym/configurations/remote_config.py
    - interactive_gym/server/app.py
    - interactive_gym/server/static/templates/index.html
    - interactive_gym/server/static/js/index.js

decisions:
  - id: PYODIDE-SCAN
    decision: "Scan GENERIC_STAGER scenes via unpack() to detect Pyodide need"
    rationale: "unpack() already handles SceneWrapper recursion; scanning at experiment level (not per-scene) detects need before any scene activates"
  - id: PYODIDE-FIRE-FORGET
    decision: "preloadPyodide() called without await in experiment_config handler"
    rationale: "Runs concurrently with entry screening; no need to block screening on Pyodide load"
  - id: PYODIDE-GRACEFUL-FALLBACK
    decision: "Preload failure sets status to 'error' but does NOT block advancement"
    rationale: "Existing game-time loading (RemoteGame.initialize()) will attempt its own load; preload is optimization not requirement"
  - id: PYODIDE-DOUBLE-LOAD
    decision: "Phase 67 intentionally does NOT modify RemoteGame/MultiplayerPyodideGame"
    rationale: "Phase 68 will wire game classes to reuse window.pyodideInstance; until then, double loadPyodide() is expected and documented"

metrics:
  duration: "~2 minutes"
  completed: "2026-02-06"
---

# Phase 67 Plan 01: Pyodide Pre-load Infrastructure Summary

**One-liner:** Server detects Pyodide-requiring scenes from experiment config and client preloads Pyodide during compat check with progress UI and advancement gating.

## What Was Done

### Task 1: Server-side Pyodide config detection and emission
- Added `ExperimentConfig.get_pyodide_config()` that scans stager scenes via `unpack()` to find `run_through_pyodide=True` scenes and collects the union of all `packages_to_install`
- Added `RemoteConfig.get_pyodide_config()` returning `{needs_pyodide: self.run_through_pyodide, packages_to_install: self.packages_to_install}`
- Added `RemoteConfig.get_entry_screening_config()` returning safe defaults to prevent crashes when called from app.py
- Modified `app.py` `register_subject` handler to include `pyodide_config` in the `experiment_config` socket event (with `hasattr` safety check)

### Task 2: Client-side Pyodide preload, progress UI, and advancement gating
- Added `#pyodideLoader` element to `index.html` (spinner + status text, same styling as `#screeningLoader`)
- Added `preloadPyodide()` async function to `index.js` that loads Pyodide core + micropip + experiment packages, storing results on `window.pyodideInstance`, `window.pyodideMicropip`, `window.pyodideInstalledPackages`
- Added `showPyodideProgress()` and `hidePyodideProgress()` helper functions
- Added global `window.pyodidePreloadStatus` state variable (`idle`/`loading`/`ready`/`error`)
- Called `preloadPyodide()` (fire-and-forget) in `experiment_config` handler, concurrent with entry screening
- Gated advance button click handler: returns early if `pyodidePreloadStatus === 'loading'`
- Added polling in `startStaticScene`: disables advance button while loading, polls at 500ms to re-enable

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 1 | 575e4a2 | Server-side Pyodide config detection and emission |
| 2 | 404aec8 | Client-side Pyodide preload, progress UI, and advancement gating |

## Deviations from Plan

None - plan executed exactly as written.

## Verification Results

1. `ExperimentConfig().get_pyodide_config()` returns `{'needs_pyodide': False, 'packages_to_install': []}` (no stager)
2. `RemoteConfig()` with `run_through_pyodide=True` and packages returns correct config
3. `RemoteConfig().get_entry_screening_config()` returns safe defaults
4. `pyodide_config` present in app.py experiment_config emission
5. No changes to Phase 68 files (pyodide_remote_game.js, pyodide_multiplayer_game.js)
6. No import errors in app.py

## Success Criteria Status

- [x] INIT-01: ExperimentConfig.get_pyodide_config() scans stager scenes, detects run_through_pyodide=True, collects packages. RemoteConfig returns own settings. app.py includes pyodide_config in experiment_config event.
- [x] INIT-02: Client preloadPyodide() starts loadPyodide() + micropip.install() immediately on experiment_config receipt. Runs concurrently with entry screening. Stores result on window.pyodideInstance.
- [x] INIT-03: #pyodideLoader shows spinner + status text. Three stages: "Loading Python runtime...", "Installing packages...", then hidden on ready.
- [x] INIT-04: Advance button disabled while loading. Click handler returns early if loading. Polls at 500ms to re-enable. Error state does NOT block advancement.

## Next Phase Readiness

Phase 68 (Shared Instance Integration) can now proceed:
- `window.pyodideInstance` will contain the pre-loaded Pyodide instance
- `window.pyodideMicropip` will contain the micropip reference
- `window.pyodideInstalledPackages` will contain the list of installed packages
- `window.pyodidePreloadStatus` will be `'ready'` when loading completes
- Phase 68 needs to modify `RemoteGame.initialize()` and `MultiplayerPyodideGame` to check for and reuse these globals
