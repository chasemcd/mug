# Roadmap: Interactive Gym

## Overview

Interactive Gym enables researchers to configure and deploy multiplayer browser experiments with minimal code. This roadmap tracks milestone-based development across the refactor/p2pcleanup branch.

## Milestones

- ✅ **v1.0–v1.21** - Phases 1-66 (shipped)
- ✅ **v1.22 GymScene Config Cleanup** - Phases 67-71 (shipped 2026-02-08)
- ✅ **v1.23 Pre-Merge Cleanup** - Phases 72-78 (shipped 2026-02-08)
- ✅ **v1.24 Test Fix & Hardening** - Phases 79-82 (shipped 2026-02-09)

## Phases

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

<details>
<summary>✅ v1.24 Test Fix & Hardening (Phases 79-82) — SHIPPED 2026-02-09</summary>

- [x] **Phase 79: Rename Corruption Fix** - Restore all 72 corrupted identifiers ✓ 2026-02-08
- [x] **Phase 80: Test Suite Restoration** - Get all 52 tests passing ✓ 2026-02-09
- [x] **Phase 81: Data Parity Hardening** - Add export parity validation to all data-producing tests ✓ 2026-02-09
- [x] **Phase 82: Examples & Documentation** - Verify examples and update docs ✓ 2026-02-09

</details>

## Progress

All milestones through v1.24 shipped. 82 phases complete across 4 milestones.

| Milestone | Phases | Status | Shipped |
|-----------|--------|--------|---------|
| v1.0–v1.21 | 1-66 | ✓ Complete | - |
| v1.22 GymScene Config Cleanup | 67-71 | ✓ Complete | 2026-02-08 |
| v1.23 Pre-Merge Cleanup | 72-78 | ✓ Complete | 2026-02-08 |
| v1.24 Test Fix & Hardening | 79-82 | ✓ Complete | 2026-02-09 |
