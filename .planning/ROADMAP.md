# Roadmap: Interactive Gym — GymScene Config Cleanup

## Overview

Refactor the GymScene chaining API from 14 accumulated builder methods into fewer, intuitively grouped methods. This is a pure API surface cleanup — rename, split, merge methods with zero functionality change. Phases progress from core method consolidation → old name removal → example migration → full verification.

## Phases

**Phase Numbering:**
- Integer phases (67, 68, 69, 70): Planned milestone work
- Decimal phases (e.g., 67.1): Urgent insertions (marked with INSERTED)

- [x] **Phase 67: API Method Consolidation** - Refactor GymScene builder methods: rename, split, and merge per new API design
- [x] **Phase 68: Clean Break** - Remove all old method names — no aliases, no shims
- [x] **Phase 69: Example Configs Migration** - Update all example configs to use new API
- [x] **Phase 70: Verification & Test Pass** - Verify zero functionality change across full test suite
- [ ] **Phase 71: Documentation Migration** - Update all docs to use new API method names (gap closure)

## Phase Details

### Phase 67: API Method Consolidation
**Goal**: Refactor GymScene builder methods — rename `pyodide()` to `runtime()`, create `multiplayer()` from sync params + 7 merged methods, split `user_experience()` into `content()` + `waitroom()`, split `rendering()` into `rendering()` + `assets()`
**Depends on**: Nothing (first phase)
**Requirements**: APIC-01, APIC-02, APIC-03, APIC-04, APIC-05, APIC-06
**Research needed**: Unlikely — straightforward method restructuring on existing code
**Success Criteria** (what must be TRUE):
  1. `runtime()` method exists with only browser execution params (code, packages, restart flag)
  2. `multiplayer()` method exists containing sync/rollback params AND matchmaking/monitoring/resilience params
  3. `content()` and `waitroom()` methods exist replacing `user_experience()`
  4. `rendering()` retains display params; new `assets()` method holds preload/animation params
  5. `policies()` and `gameplay()` remain unchanged
**Plans:** 2 plans
Plans:
- [x] 67-01-PLAN.md — Add runtime() and multiplayer() builder methods
- [x] 67-02-PLAN.md — Add content(), waitroom(), and assets() builder methods

### Phase 68: Clean Break
**Goal**: Remove all old method names entirely — no deprecation aliases, no redirect methods
**Depends on**: Phase 67
**Requirements**: CLNB-01, CLNB-02
**Research needed**: Unlikely — deletion of old names, grep to confirm no remnants
**Success Criteria** (what must be TRUE):
  1. Calling any old method name (`pyodide`, `user_experience`, `player_grouping`, `continuous_monitoring`, `exclusion_callbacks`, `reconnection_config`, `partner_disconnect_message_config`, `focus_loss_config`, `player_pairing`) raises AttributeError
  2. No deprecation aliases or redirect methods exist in the codebase
  3. All internal references within GymScene class use new method names
**Plans:** 1 plan
Plans:
- [x] 68-01-PLAN.md — Remove 9 old methods, slim rendering() asset params

### Phase 69: Example Configs Migration
**Goal**: Update all 5 example configs to use the new API methods
**Depends on**: Phase 68
**Requirements**: EXMP-01, EXMP-02, EXMP-03, EXMP-04, EXMP-05
**Research needed**: Unlikely — mechanical find-and-replace in example files
**Success Criteria** (what must be TRUE):
  1. All 5 example configs exclusively use new method names
  2. Each example can be imported/loaded without errors
  3. No references to old method names remain in any example file
**Plans:** 2 plans
Plans:
- [x] 69-01-PLAN.md — Migrate cogrid scenes.py to new API methods
- [x] 69-02-PLAN.md — Migrate slime volleyball, mountain car, and overcooked multiplayer examples

### Phase 70: Verification & Test Pass
**Goal**: Verify zero functionality change — all tests pass, no params lost, chaining works
**Depends on**: Phase 69
**Requirements**: VERF-01, VERF-02, VERF-03
**Research needed**: Unlikely — run existing tests and verify param coverage
**Success Criteria** (what must be TRUE):
  1. Full test suite passes with zero failures
  2. Every parameter from old API is accessible through new API (no params lost)
  3. All new builder methods return `self` for method chaining
**Plans:** 2 plans
Plans:
- [x] 70-01-PLAN.md — Migrate remaining unmigrated files (test configs + controllable scenes)
- [x] 70-02-PLAN.md — Full test suite, parameter coverage audit, and chaining verification

### Phase 71: Documentation Migration
**Goal**: Update all documentation files to use new API method names — replace references to removed methods (`.pyodide()`, `.user_experience()`, `.continuous_monitoring()`, `.exclusion_callbacks()`, `.focus_loss_config()`, etc.) with their new equivalents
**Depends on**: Phase 70
**Requirements**: DOCS-01, DOCS-02
**Research needed**: Unlikely — mechanical find-and-replace in doc files
**Gap Closure**: Closes documentation tech debt from v1.22 milestone audit
**Success Criteria** (what must be TRUE):
  1. Zero references to removed GymScene method names in any documentation file (docs/, README.md files)
  2. All code examples in documentation use the new API methods and are accurate
  3. No documentation references to methods that would raise AttributeError
**Plans:** 3 plans
Plans:
- [ ] 71-01-PLAN.md — Migrate 9 RST files + cogrid README to new API method names
- [ ] 71-02-PLAN.md — Migrate 5 MD design docs + delete stale HTML export
- [ ] 71-03-PLAN.md — Final verification sweep across all documentation

## Progress

**Execution Order:**
Phases execute in numeric order: 67 → 68 → 69 → 70 → 71

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 67. API Method Consolidation | 2/2 | ✓ Complete | 2026-02-07 |
| 68. Clean Break | 1/1 | ✓ Complete | 2026-02-07 |
| 69. Example Configs Migration | 2/2 | ✓ Complete | 2026-02-07 |
| 70. Verification & Test Pass | 2/2 | ✓ Complete | 2026-02-08 |
| 71. Documentation Migration | 0/3 | Planned | — |
