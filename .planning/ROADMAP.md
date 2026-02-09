# Roadmap: Interactive Gym — v1.24 Test Fix & Hardening

## Overview

Fix the rename corruption introduced in v1.23 (bulk `sio` → `socketio` mangled 72 identifiers), restore all 46 tests to passing, harden data export parity validation, and ensure examples and documentation reflect the refactored codebase. Zero new features — correctness and validation only.

## Milestones

- ✅ **v1.0–v1.21** - Phases 1-66 (shipped)
- ✅ **v1.22 GymScene Config Cleanup** - Phases 67-71 (shipped 2026-02-08)
- ✅ **v1.23 Pre-Merge Cleanup** - Phases 72-78 (shipped 2026-02-08)
- 🚧 **v1.24 Test Fix & Hardening** - Phases 79-82 (in progress)

## Phases

**Phase Numbering:**
- Integer phases (79, 80, ...): Planned milestone work
- Decimal phases (e.g., 79.1): Urgent insertions (marked with INSERTED)

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

<details>
<summary>✅ v1.23 Pre-Merge Cleanup (Phases 72-78) — SHIPPED 2026-02-08</summary>

- [x] **Phase 72: Server Python Dead Code Removal** - Remove unused functions, classes, methods from server code
- [x] **Phase 73: Scene & Environment Dead Code Removal** - Remove unused code from scenes/examples
- [x] **Phase 74: Client JavaScript Dead Code Removal** - Remove unused JS functions and dead paths
- [x] **Phase 75: Python Naming Clarity** - Rename unclear Python variables/functions/modules
- [x] **Phase 76: JavaScript Naming Clarity** - Rename unclear JS variables/functions
- [x] **Phase 77: Structural Organization** - Reorganize files, consolidate modules
- [x] **Phase 78: Final Verification** - Full test suite pass after cleanup

</details>

### 🚧 v1.24 Test Fix & Hardening (In Progress)

**Milestone Goal:** Fix refactor-introduced bugs, restore all 46 tests to passing, harden data export validation, and ensure examples and docs reflect the refactored codebase.

- [x] **Phase 79: Rename Corruption Fix** - Restore all 72 corrupted identifiers from bulk `sio` → `socketio` rename ✓ 2026-02-08
- [ ] **Phase 80: Test Suite Restoration** - Get all 46 tests passing with zero exceptions
- [ ] **Phase 81: Data Parity Hardening** - Add export parity validation to all data-producing tests
- [ ] **Phase 82: Examples & Documentation** - Verify examples run end-to-end and docs reflect refactored API

## Phase Details

### Phase 79: Rename Corruption Fix
**Goal**: Restore all corrupted identifiers from v1.23 bulk `sio` → `socketio` rename that mangled words containing "sio"
**Depends on**: Nothing (first phase of v1.24)
**Requirements**: FIX-01, FIX-02, FIX-03, FIX-04
**Success Criteria** (what must be TRUE):
  1. All `Sessocketion` → `Session` occurrences restored in pyodide_game_coordinator.py
  2. All `sessocketion` → `session` occurrences restored in probe_coordinator.py
  3. All `transmissocketion` → `transmission` occurrences restored in server_game_runner.py
  4. All `exclusocketion` → `exclusion` occurrences restored in pyodide_game_coordinator.py
  5. Server starts without import errors or NameError exceptions
**Plans:** 1 plan

Plans:
- [x] 79-01-PLAN.md — Fix all 72 corrupted identifiers across 3 server files ✓

### Phase 80: Test Suite Restoration
**Goal**: Get all 46 existing tests passing with zero exceptions and no loosened criteria
**Depends on**: Phase 79 (code must compile before tests can pass)
**Requirements**: TEST-01, TEST-02, TEST-03, TEST-04, TEST-05, TEST-06, TEST-07
**Success Criteria** (what must be TRUE):
  1. All 2 E2E infrastructure tests pass (server start, context connection)
  2. All 2 E2E multiplayer basic tests pass (connect+complete, matchmaking)
  3. All E2E data comparison tests pass (basic parity, latency parity, active input, focus loss)
  4. All 7 E2E network stress tests pass (latency injection, packet loss, jitter, rollback, fast-forward)
  5. All 5 E2E multi-participant tests pass (simultaneous games, staggered arrival, multi-episode, disconnect, focus timeout)
  6. Scene isolation test passes (partner exit on survey)
  7. All 27 unit tests pass (matchmaker unit + integration)
**Plans**: TBD

Plans:
- [ ] TBD

### Phase 81: Data Parity Hardening
**Goal**: Ensure every test producing episode CSV data validates export parity between both players
**Depends on**: Phase 80 (tests must pass before adding validation)
**Requirements**: DATA-01, DATA-02, DATA-03
**Success Criteria** (what must be TRUE):
  1. Every E2E test that produces episode data calls validate_action_sequences.py --compare
  2. Tests that currently skip parity checks have been updated to include them
  3. No test produces episode CSV data without asserting that both players' exports match
**Plans**: TBD

Plans:
- [ ] TBD

### Phase 82: Examples & Documentation
**Goal**: Verify all examples run end-to-end and documentation reflects post-refactor API names and module paths
**Depends on**: Phase 79 (examples need working code)
**Requirements**: EXAM-01, EXAM-02, DOCS-01, DOCS-02
**Success Criteria** (what must be TRUE):
  1. All example configurations in interactive_gym/examples/ run end-to-end without errors
  2. Example imports and API calls use post-v1.23 renamed modules and methods
  3. All documentation files reference correct module paths after v1.23 reorganization
  4. All documentation files reference correct API method names after v1.22/v1.23 renames
**Plans**: TBD

Plans:
- [ ] TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 79 → 80 → 81 → 82

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 79. Rename Corruption Fix | 1/1 | ✓ Complete | 2026-02-08 |
| 80. Test Suite Restoration | 0/? | Not started | - |
| 81. Data Parity Hardening | 0/? | Not started | - |
| 82. Examples & Documentation | 0/? | Not started | - |
