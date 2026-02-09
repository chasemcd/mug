# Roadmap: Interactive Gym

## Overview

Interactive Gym enables researchers to configure and deploy multiplayer browser experiments with minimal code. This roadmap tracks milestone-based development across the refactor/p2pcleanup branch.

## Milestones

- ✅ **v1.0–v1.21** - Phases 1-66 (shipped)
- ✅ **v1.22 GymScene Config Cleanup** - Phases 67-71 (shipped 2026-02-08)
- ✅ **v1.23 Pre-Merge Cleanup** - Phases 72-78 (shipped 2026-02-08)
- ✅ **v1.24 Test Fix & Hardening** - Phases 79-82 (shipped 2026-02-09)
- [ ] **v1.25 Data Export Path Fix** - Phase 83 (in progress)

## Phases

<details>
<summary>v1.0-v1.21 (Phases 1-66) -- SHIPPED</summary>

See previous milestone records.

</details>

<details>
<summary>v1.22 GymScene Config Cleanup (Phases 67-71) -- SHIPPED 2026-02-08</summary>

- [x] **Phase 67: API Method Consolidation** - Refactor GymScene builder methods
- [x] **Phase 68: Clean Break** - Remove all old method names
- [x] **Phase 69: Example Configs Migration** - Update all example configs
- [x] **Phase 70: Verification & Test Pass** - Verify zero functionality change
- [x] **Phase 71: Documentation Migration** - Update all docs to new API

</details>

<details>
<summary>v1.23 Pre-Merge Cleanup (Phases 72-78) -- SHIPPED 2026-02-08</summary>

- [x] **Phase 72: Server Python Dead Code Removal** - Remove unused functions, classes, methods from server code
- [x] **Phase 73: Scene & Environment Dead Code Removal** - Remove unused code from scenes/examples
- [x] **Phase 74: Client JavaScript Dead Code Removal** - Remove unused JS functions and dead paths
- [x] **Phase 75: Python Naming Clarity** - Rename unclear Python variables/functions/modules
- [x] **Phase 76: JavaScript Naming Clarity** - Rename unclear JS variables/functions
- [x] **Phase 77: Structural Organization** - Reorganize files, consolidate modules
- [x] **Phase 78: Final Verification** - Full test suite pass after cleanup

</details>

<details>
<summary>v1.24 Test Fix & Hardening (Phases 79-82) -- SHIPPED 2026-02-09</summary>

- [x] **Phase 79: Rename Corruption Fix** - Restore all 72 corrupted identifiers
- [x] **Phase 80: Test Suite Restoration** - Get all 52 tests passing
- [x] **Phase 81: Data Parity Hardening** - Add export parity validation to all data-producing tests
- [x] **Phase 82: Examples & Documentation** - Verify examples and update docs

</details>

### v1.25 Data Export Path Fix (In Progress)

**Milestone Goal:** Ensure all exported data (scene metadata, match logs) lands under `data/<experiment-id>/` -- not scattered in `data/`.

- [ ] **Phase 83: Export Path Consolidation** - Fix scene metadata and match log paths to use experiment_id prefix

## Phase Details

### Phase 83: Export Path Consolidation
**Goal**: All exported experiment data lands under a single `data/{experiment_id}/` directory
**Depends on**: Phase 82 (v1.24 complete)
**Requirements**: DEXP-01, DEXP-02, DEXP-03, DEXP-04
**Success Criteria** (what must be TRUE):
  1. Scene metadata CSVs are written to `data/{experiment_id}/{scene_id}/` instead of `data/{scene_id}/`
  2. Match log files are written to `data/{experiment_id}/match_logs/` instead of `data/match_logs/`
  3. All 52 existing tests pass with the updated export paths
  4. Running an experiment produces zero data files outside `data/{experiment_id}/`
**Plans**: 1 plan

Plans:
- [ ] 83-01-PLAN.md -- Fix scene metadata and match log export paths to use experiment_id prefix

## Progress

**Execution Order:** Phase 83

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1-66 | v1.0-v1.21 | - | Complete | - |
| 67-71 | v1.22 | - | Complete | 2026-02-08 |
| 72-78 | v1.23 | - | Complete | 2026-02-08 |
| 79-82 | v1.24 | - | Complete | 2026-02-09 |
| 83. Export Path Consolidation | v1.25 | 0/? | Not started | - |
