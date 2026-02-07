# Roadmap: Interactive Gym — GymScene Config Cleanup

## Overview

Refactor the GymScene chaining API from 14 accumulated builder methods into fewer, intuitively grouped methods. This is a pure API surface cleanup — rename, split, merge methods with zero functionality change. Phases progress from core method consolidation → old name removal → example migration → full verification.

## Phases

**Phase Numbering:**
- Integer phases (67, 68, 69, 70): Planned milestone work
- Decimal phases (e.g., 67.1): Urgent insertions (marked with INSERTED)

- [x] **Phase 67: API Method Consolidation** - Refactor GymScene builder methods: rename, split, and merge per new API design
- [ ] **Phase 68: Clean Break** - Remove all old method names — no aliases, no shims
- [ ] **Phase 69: Example Configs Migration** - Update all example configs to use new API
- [ ] **Phase 70: Verification & Test Pass** - Verify zero functionality change across full test suite

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
- [ ] 68-01-PLAN.md — Remove 9 old methods, slim rendering() asset params

### Phase 69: Example Configs Migration
**Goal**: Update all 5 example configs to use the new API methods
**Depends on**: Phase 68
**Requirements**: EXMP-01, EXMP-02, EXMP-03, EXMP-04, EXMP-05
**Research needed**: Unlikely — mechanical find-and-replace in example files
**Success Criteria** (what must be TRUE):
  1. All 5 example configs exclusively use new method names
  2. Each example can be imported/loaded without errors
  3. No references to old method names remain in any example file
**Plans**: TBD

### Phase 70: Verification & Test Pass
**Goal**: Verify zero functionality change — all tests pass, no params lost, chaining works
**Depends on**: Phase 69
**Requirements**: VERF-01, VERF-02, VERF-03
**Research needed**: Unlikely — run existing tests and verify param coverage
**Success Criteria** (what must be TRUE):
  1. Full test suite passes with zero failures
  2. Every parameter from old API is accessible through new API (no params lost)
  3. All new builder methods return `self` for method chaining
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 67 → 68 → 69 → 70

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 67. API Method Consolidation | 2/2 | ✓ Complete | 2026-02-07 |
| 68. Clean Break | 0/1 | Not started | - |
| 69. Example Configs Migration | 0/TBD | Not started | - |
| 70. Verification & Test Pass | 0/TBD | Not started | - |
