# Roadmap: Interactive Gym — v1.23 Pre-Merge Cleanup

## Overview

Clean the entire codebase before merging `feature/p2p-multiplayer` to `main`. Three passes: remove dead code (server → scenes → client JS), improve naming (Python → JS), reorganize structure, then verify everything. Zero functionality changes throughout.

## Milestones

- ✅ **v1.0–v1.21** - Phases 1-66 (shipped)
- ✅ **v1.22 GymScene Config Cleanup** - Phases 67-71 (shipped 2026-02-08)
- ✅ **v1.23 Pre-Merge Cleanup** - Phases 72-78 (shipped 2026-02-08)

## Phases

**Phase Numbering:**
- Integer phases (72, 73, ...): Planned milestone work
- Decimal phases (e.g., 72.1): Urgent insertions (marked with INSERTED)

<details>
<summary>✅ v1.0–v1.21 (Phases 1-66) — SHIPPED</summary>

See previous milestone records.

</details>

<details>
<summary>✅ v1.22 GymScene Config Cleanup (Phases 67-71) — SHIPPED 2026-02-08</summary>

- [x] **Phase 67: API Method Consolidation** - Refactor GymScene builder methods
- [x] **Phase 68: Clean Break** - Remove all old method names
- [x] **Phase 69: Example Configs Migration** - Update all example configs
- [x] **Phase 70: Verification & Test Pass** - Verify zero functionality change
- [x] **Phase 71: Documentation Migration** - Update all docs to new API

</details>

### ✅ v1.23 Pre-Merge Cleanup (COMPLETE)

**Milestone Goal:** Make the entire codebase clean, readable, and coherent before merging to `main`. Zero functionality changes.

- [x] **Phase 72: Server Python Dead Code Removal** - Remove unused functions, classes, methods, and vestigial logic from server code ✓ 2026-02-07
- [x] **Phase 73: Scene & Environment Dead Code Removal** - Remove unused code from scenes, examples, and environment code ✓ 2026-02-08
- [x] **Phase 74: Client JavaScript Dead Code Removal** - Remove unused JS functions, classes, and dead code paths ✓ 2026-02-08
- [x] **Phase 75: Python Naming Clarity** - Rename unclear Python variable, function, and module names ✓ 2026-02-08
- [x] **Phase 76: JavaScript Naming Clarity** - Rename unclear JS variable and function names ✓ 2026-02-08
- [x] **Phase 77: Structural Organization** - Reorganize files, consolidate modules, move misplaced code ✓ 2026-02-08
- [x] **Phase 78: Final Verification** - Full test suite pass and behavioral verification ✓ 2026-02-08

## Phase Details

### Phase 72: Server Python Dead Code Removal
**Goal**: Remove all unused functions, classes, methods, and vestigial logic from server Python code (`server/`, `configurations/`, `utils/`)
**Depends on**: Nothing (first phase of v1.23)
**Requirements**: DEAD-01, DEAD-04 (server portion)
**Research needed**: Unlikely — grep for unused definitions, review call graphs
**Success Criteria** (what must be TRUE):
  1. No unused Python functions/classes/methods remain in `server/`, `configurations/`, or `utils/`
  2. No vestigial logic (unreachable code, obsolete feature flags, dead branches) remains in server code
  3. All tests pass after removal
**Plans**: 2 plans
Plans:
- [x] 72-01-PLAN.md — Delete dead files, remove dead classes (RemoteGame, RenderedEnvRGB), update type annotations
- [x] 72-02-PLAN.md — Remove dead methods, dead functions, vestigial logic, and backward compat aliases

### Phase 73: Scene & Environment Dead Code Removal
**Goal**: Remove all unused Python functions, classes, methods, and vestigial logic from scenes and example code
**Depends on**: Phase 72
**Requirements**: DEAD-02, DEAD-04 (scene portion)
**Research needed**: Unlikely — grep for unused definitions, review call graphs
**Success Criteria** (what must be TRUE):
  1. No unused Python functions/classes/methods remain in `scenes/` or `examples/`
  2. No vestigial logic (unreachable code, dead branches) remains in scene/environment code
  3. All tests pass after removal
**Plans**: 2 plans
Plans:
- [x] 73-01-PLAN.md — Delete constructors/ directory, remove dead static scene classes and dead GymScene methods
- [x] 73-02-PLAN.md — Fix broken footsies import, remove dead scene variables, delete empty pyodide_overcooked/ directory

### Phase 74: Client JavaScript Dead Code Removal
**Goal**: Remove all unused JS functions, classes, and dead code paths from client-side JavaScript
**Depends on**: Phase 73
**Requirements**: DEAD-03, DEAD-04 (JS portion)
**Research needed**: Unlikely — grep for unused functions, trace call graphs in JS modules
**Success Criteria** (what must be TRUE):
  1. No unused JS functions/classes remain in `server/static/js/`
  2. No dead code paths or obsolete feature logic remains in client code
  3. All tests pass after removal
**Plans**: 2 plans
Plans:
- [x] 74-01-PLAN.md — Delete dead JS files (latency.js, socket_handlers.js, game_events.js) and remove dead functions from unity_utils.js
- [x] 74-02-PLAN.md — Remove dead exports from ui_utils.js, phaser_gym_graphics.js, webrtc_manager.js and commented-out code from index.js

### Phase 75: Python Naming Clarity
**Goal**: Rename unclear Python variable, function, and module names across the codebase to reflect their purpose
**Depends on**: Phase 74
**Requirements**: NAME-01, NAME-03
**Research needed**: Unlikely — review code for unclear names, apply renames
**Success Criteria** (what must be TRUE):
  1. All unclear Python variable/function names have been renamed to reflect their purpose
  2. File/module names reflect their contents
  3. All tests pass with new names
**Plans**: 2 plans
Plans:
- [x] 75-01-PLAN.md — Rename `sio` to `socketio` across all Python files, fix cryptic variables (`vv`, `ch`, `gm`)
- [x] 75-02-PLAN.md — Rename `server/utils.py` to `server/thread_utils.py`, `scenes/utils.py` to `scenes/sentinels.py`, rename `Available` to `AvailableSlot`

### Phase 76: JavaScript Naming Clarity
**Goal**: Rename unclear JS variable and function names to reflect their purpose
**Depends on**: Phase 75
**Requirements**: NAME-02
**Research needed**: Unlikely — review JS code for unclear names, apply renames
**Success Criteria** (what must be TRUE):
  1. All unclear JS variable/function names have been renamed to reflect their purpose
  2. All tests pass with new names
**Plans**: 2 plans
Plans:
- [x] 76-01-PLAN.md — Expand WebRTC abbreviations (`pc`, `dc`) and rename cryptic `pgg` import alias
- [x] 76-02-PLAN.md — Rename generic `data` parameters in all socket handlers in index.js to context-specific names

### Phase 77: Structural Organization
**Goal**: Reorganize files into logical locations, consolidate unnecessarily split modules, move misplaced code
**Depends on**: Phase 76
**Requirements**: STRUCT-01, STRUCT-02, STRUCT-03
**Research needed**: Likely — need to analyze module boundaries, identify misplaced code, plan reorganization
**Research topics**: Module dependency analysis, import graph, identifying consolidation candidates
**Success Criteria** (what must be TRUE):
  1. Files are in logical locations in the directory tree
  2. Unnecessarily split modules are consolidated where it reduces complexity
  3. Misplaced functions/classes are in the modules where they logically belong
  4. All tests pass after reorganization
**Plans**: 2 plans
Plans:
- [x] 77-01-PLAN.md — Move NotProvided sentinel from scenes/sentinels.py to utils/sentinels.py, update all imports
- [x] 77-02-PLAN.md — Consolidate game state types and callbacks into remote_game.py, rename thread_utils.py to thread_safe_collections.py

### Phase 78: Final Verification
**Goal**: Full verification that zero functionality changes were introduced across all cleanup phases
**Depends on**: Phase 77
**Requirements**: VERIF-01, VERIF-02
**Research needed**: Unlikely — run tests, compare behavior
**Success Criteria** (what must be TRUE):
  1. Full test suite passes with zero failures
  2. No functionality changes introduced (behavior identical before and after all cleanup)
**Plans**: 1 plan
Plans:
- [x] 78-01-PLAN.md — Run full test suite, verify all phase artifacts and cross-phase integration

## Progress

**Execution Order:**
Phases execute in numeric order: 72 → 73 → 74 → 75 → 76 → 77 → 78

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 72. Server Python Dead Code Removal | 2/2 | ✓ Complete | 2026-02-07 |
| 73. Scene & Environment Dead Code Removal | 2/2 | ✓ Complete | 2026-02-08 |
| 74. Client JavaScript Dead Code Removal | 2/2 | ✓ Complete | 2026-02-08 |
| 75. Python Naming Clarity | 2/2 | ✓ Complete | 2026-02-08 |
| 76. JavaScript Naming Clarity | 2/2 | ✓ Complete | 2026-02-08 |
| 77. Structural Organization | 2/2 | ✓ Complete | 2026-02-08 |
| 78. Final Verification | 0/1 | Not started | - |
