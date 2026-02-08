---
phase: 71-documentation-migration
plan: 01
subsystem: documentation
tags: [rst, sphinx, api-migration, documentation]

dependency-graph:
  requires: [70]
  provides: [user-facing-docs-migrated]
  affects: [71-02, 71-03]

tech-stack:
  added: []
  patterns: []

key-files:
  created: []
  modified:
    - docs/content/core_concepts/scenes.rst
    - docs/content/core_concepts/pyodide_mode.rst
    - docs/content/core_concepts/index.rst
    - docs/content/core_concepts/server_mode.rst
    - docs/content/quick_start.rst
    - docs/content/examples/slime_volleyball.rst
    - docs/content/examples/mountain_car.rst
    - docs/content/examples/overcooked_multiplayer.rst
    - docs/content/examples/overcooked_human_ai.rst
    - interactive_gym/examples/cogrid/README.md

decisions:
  - id: "71-01-waitroom-param-removal"
    decision: "Removed waitroom_time_randomization_interval_s from server_mode.rst example"
    reason: "Parameter has no corresponding new builder method; only timeout_redirect_url maps to .waitroom()"

metrics:
  duration: "4 min"
  completed: "2026-02-08"
---

# Phase 71 Plan 01: RST + README Documentation Migration Summary

**One-liner:** Migrated all 9 user-facing RST docs and cogrid README from .pyodide()/.user_experience() to .runtime()/.content()/.waitroom()/.multiplayer()

## What Was Done

### Task 1: Migrate 5 core concept RST files + quick_start.rst (88f512e)
Migrated method names across 5 files:

- **scenes.rst**: Renamed .user_experience() section header and code block to .content(), renamed .pyodide() section header and code block to .runtime(), updated conditional scene content example
- **pyodide_mode.rst**: Updated 8 .pyodide() calls to .runtime() (basic config, external file, packages, custom code, AI policies, restart, complete example), updated 2 .user_experience() calls to .content() (loading screen, complete example)
- **index.rst**: Updated fluent chain example (.user_experience -> .content, .pyodide -> .runtime) and simple single-player example
- **server_mode.rst**: Updated comment "No .pyodide() call" to "No .runtime() call", split .user_experience(waitroom_timeout_redirect_url=...) into .waitroom(timeout_redirect_url=...)
- **quick_start.rst**: Updated .user_experience() to .content(), .pyodide() to .runtime(), updated text reference in troubleshooting

### Task 2: Migrate 4 example RST files + cogrid README (15837ea)
Migrated method names across 5 files:

- **slime_volleyball.rst**: .user_experience() -> .content(), .pyodide() -> .runtime(), comment "No .pyodide() configuration" -> "No .runtime() configuration"
- **mountain_car.rst**: .user_experience() -> .content(), .pyodide() -> .runtime()
- **overcooked_multiplayer.rst**: .user_experience() -> .content() (single location in tutorial scene)
- **overcooked_human_ai.rst**: .user_experience() -> .content() (single location in tutorial scene)
- **cogrid README.md**: Split .pyodide(run_through_pyodide=True, multiplayer=True, ...) into .runtime() + .multiplayer() with proper param separation

## Verification Results

Comprehensive grep sweep confirms:
- Zero `.pyodide(` references across all docs/content/ RST files and cogrid README
- Zero `.user_experience(` references across all docs/content/ RST files and cogrid README
- Zero backtick-quoted `pyodide()` references (as GymScene method) in any target file

## Decisions Made

| ID | Decision | Rationale |
|----|----------|-----------|
| 71-01-waitroom-param-removal | Removed `waitroom_time_randomization_interval_s` from server_mode.rst example when converting to .waitroom() | Parameter has no corresponding new builder method in .waitroom(); only timeout-related params are supported |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Removed unsupported waitroom param from docs**

- **Found during:** Task 1 (server_mode.rst)
- **Issue:** server_mode.rst example had `waitroom_time_randomization_interval_s` in `.user_experience()`, but `.waitroom()` only supports `timeout`, `timeout_redirect_url`, `timeout_scene_id`, `timeout_message`
- **Fix:** Removed the unsupported param from the code example to avoid documenting a non-existent API
- **Files modified:** docs/content/core_concepts/server_mode.rst

## Commits

| Task | Commit | Files |
|------|--------|-------|
| Task 1 | 88f512e | 5 core concept RST files + quick_start.rst |
| Task 2 | 15837ea | 4 example RST files + cogrid README.md |

## Next Phase Readiness

Plan 71-02 (design docs migration) can proceed. The user-facing documentation is now fully migrated. Pre-existing uncommitted changes to design docs (multiplayer-sync-optimization.md, multiplayer_pyodide_implementation.md, server-frame-aligned-stepper.md) were observed in the working tree but were NOT touched by this plan -- they appear to be leftover from Phase 70 work.
