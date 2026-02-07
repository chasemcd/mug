---
phase: 68-shared-instance-integration
plan: 01
subsystem: pyodide-shared-instance
tags: [pyodide, shared-instance, preload-reuse, package-dedup]

dependency-graph:
  requires:
    - "Phase 67: window.pyodideInstance, window.pyodideMicropip, window.pyodideInstalledPackages, window.pyodidePreloadStatus"
  provides:
    - "RemoteGame.initialize() reuses pre-loaded Pyodide instance when available"
    - "Package installation deduplicated against preload-installed packages"
    - "MultiplayerPyodideGame inherits shared instance behavior via super.initialize()"
  affects:
    - "Phase 69: Server-side init grace (game startup now near-instant when preloaded)"
    - "Phase 70: Validation & test stabilization (concurrent starts viable)"

tech-stack:
  added: []
  patterns:
    - "Conditional reuse of window globals for singleton Pyodide instance"
    - "Package dedup via array filter against installed_packages"

key-files:
  created: []
  modified:
    - interactive_gym/server/static/js/pyodide_remote_game.js
    - interactive_gym/server/static/js/pyodide_multiplayer_game.js

decisions:
  - id: SHARED-REUSE
    decision: "Check window.pyodidePreloadStatus === 'ready' AND window.pyodideInstance truthy before reuse"
    rationale: "Both conditions prevent reuse of partially loaded or failed instances; status check alone insufficient if instance was garbage collected"
  - id: SHARED-FALLBACK
    decision: "Else branch runs original loadPyodide() path unchanged"
    rationale: "Preserves backward compatibility for non-Pyodide experiments, preload failures, and direct RemoteGame usage without preload"
  - id: SHARED-DEDUP
    decision: "Filter packages_to_install against this.installed_packages before calling micropip.install()"
    rationale: "Preload may have installed some but not all packages; game scene may need additional packages beyond what was preloaded"
  - id: SHARED-NO-MULTIPLAYER-CHANGE
    decision: "MultiplayerPyodideGame.initialize() only gets a log line, no structural changes"
    rationale: "super.initialize() already inherits all RemoteGame changes; adding structural code would duplicate logic"

metrics:
  duration: "~2 minutes"
  completed: "2026-02-06"
---

# Phase 68 Plan 01: Shared Pyodide Instance Integration Summary

**One-liner:** RemoteGame.initialize() reuses pre-loaded window.pyodideInstance with package dedup, falling back to fresh loadPyodide() when preload unavailable.

## What Was Done

### Task 1: Modify RemoteGame.initialize() to reuse pre-loaded Pyodide
- Added conditional check at start of `initialize()`: if `window.pyodidePreloadStatus === 'ready'` AND `window.pyodideInstance` is truthy, reuse the pre-loaded instance
- Reuse path sets `this.pyodide = window.pyodideInstance`, `this.micropip = window.pyodideMicropip`, copies `window.pyodideInstalledPackages` into `this.installed_packages`
- Fallback path preserves original `loadPyodide()` + `loadPackage("micropip")` + `pyimport("micropip")` flow
- Package installation deduplicated: filters `config.packages_to_install` against `this.installed_packages`, only installs packages not already present
- `reinitialize_environment()` left untouched (already has its own dedup logic)

### Task 2: Add console logging to MultiplayerPyodideGame.initialize()
- Added `console.log` line before `await super.initialize()` that logs which initialization path will be used
- Conditional message: `'(will reuse pre-loaded Pyodide)'` or `'(will load Pyodide fresh)'` based on `window.pyodidePreloadStatus`
- No other changes to the multiplayer game file

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 1 | a8351d7 | Modify RemoteGame.initialize() to reuse pre-loaded Pyodide |
| 2 | dc52234 | Add preload path logging to MultiplayerPyodideGame.initialize() |

## Deviations from Plan

None - plan executed exactly as written.

## Verification Results

1. `window.pyodidePreloadStatus === 'ready'` check exists in RemoteGame.initialize() (line 50)
2. Fallback `loadPyodide()` path preserved, appears exactly once in file (line 57)
3. Package dedup filters already-installed packages before calling micropip.install()
4. MultiplayerPyodideGame inherits shared instance via `await super.initialize()` (unchanged at line 1742)
5. `reinitialize_environment()` untouched (existing dedup logic preserved)
6. Console logging present in both RemoteGame and MultiplayerPyodideGame

## Success Criteria Status

- [x] SHARED-01: RemoteGame.initialize() checks window.pyodidePreloadStatus and reuses window.pyodideInstance when 'ready'
- [x] SHARED-02: MultiplayerPyodideGame.initialize() calls super.initialize() which inherits the reuse behavior
- [x] Fallback: When preload didn't happen (status != 'ready'), the original loadPyodide() path executes
- [x] Package dedup: Packages installed during preload are not reinstalled at game time
- [x] No changes to existing game loop, step(), reset(), or reinitialize_environment() methods

## Next Phase Readiness

Phase 69 (Server-side Init Grace) can proceed:
- Game startup is now near-instant when Pyodide was pre-loaded during compat check
- The 5-15 second loadPyodide() delay is eliminated for the preloaded path
- Server-side ping tolerance during loading may still be needed for the fallback (non-preloaded) path
