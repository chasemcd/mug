# Roadmap: Multi-User Gymnasium (MUG)

## Milestones

<details>
<summary>Shipped milestones (v1.0-v1.26)</summary>

- v1.0-v1.21 Feature Branch -- Phases 1-66 (shipped)
- v1.22 GymScene Config Cleanup -- Phases 67-71 (shipped 2026-02-08)
- v1.23 Pre-Merge Cleanup -- Phases 72-78 (shipped 2026-02-08)
- v1.24 Test Fix & Hardening -- Phases 79-82 (shipped 2026-02-09)
- v1.25 Data Export Path Fix -- Phase 83 (shipped 2026-02-09)
- v1.26 Project Rename -- Phases 84-86 (shipped 2026-02-10)

</details>

- **v1.27 Principled Rollback Management** -- Phases 87-88 (in progress)

## Phases

<details>
<summary>v1.0-v1.21 Feature Branch (Phases 1-66) -- SHIPPED</summary>

- [x] Phases 1-66: P2P Multiplayer development (see milestones/ for details)

</details>

<details>
<summary>v1.22 GymScene Config Cleanup (Phases 67-71) -- SHIPPED 2026-02-08</summary>

- [x] Phase 67: API method consolidation (14 -> 10 builder methods)
- [x] Phase 68: Clean break (9 old method names removed)
- [x] Phase 69: Example configs migration (5 examples updated)
- [x] Phase 70: Verification & test pass
- [x] Phase 71: Documentation migration (15 doc files)

</details>

<details>
<summary>v1.23 Pre-Merge Cleanup (Phases 72-78) -- SHIPPED 2026-02-08</summary>

- [x] Phase 72: Server Python dead code removal
- [x] Phase 73: Scene/environment dead code
- [x] Phase 74: Client JS dead code
- [x] Phase 75: Python naming clarity
- [x] Phase 76: JS naming clarity
- [x] Phase 77: Structural organization
- [x] Phase 78: Final verification

</details>

<details>
<summary>v1.24 Test Fix & Hardening (Phases 79-82) -- SHIPPED 2026-02-09</summary>

- [x] Phase 79: Rename corruption fix
- [x] Phase 80: Test suite restoration
- [x] Phase 81: Data parity hardening
- [x] Phase 82: Examples & documentation

</details>

<details>
<summary>v1.25 Data Export Path Fix (Phase 83) -- SHIPPED 2026-02-09</summary>

- [x] Phase 83: Export path consolidation

</details>

<details>
<summary>v1.26 Project Rename (Phases 84-86) -- SHIPPED 2026-02-10</summary>

- [x] Phase 84: Package & Code Rename (2/2 plans) -- completed 2026-02-10
- [x] Phase 85: Documentation & Frontend (3/3 plans) -- completed 2026-02-10
- [x] Phase 86: Final Verification (2/2 plans) -- completed 2026-02-10

</details>

### v1.27 Principled Rollback Management (In Progress)

**Milestone Goal:** Replace arbitrary hardcoded limits in the GGPO rollback system with principled, confirmedFrame-based resource management.

- [x] **Phase 87: ConfirmedFrame-Based Resource Management** (1/1 plans) -- completed 2026-02-11
- [ ] **Phase 88: Verification** - Confirm all tests pass and rollback correctness is preserved

## Phase Details

### Phase 87: ConfirmedFrame-Based Resource Management
**Goal**: Snapshot and input buffer pruning adapts to network conditions via confirmedFrame instead of arbitrary hardcoded limits
**Depends on**: Nothing (first phase of v1.27)
**Requirements**: SNAP-01, SNAP-02, SNAP-03, IBUF-01, IBUF-02, IBUF-03, CONF-01, CONF-02
**Success Criteria** (what must be TRUE):
  1. Snapshots before the anchor snapshot (highest snapshot <= confirmedFrame) are automatically deleted during pruning
  2. No hardcoded maxSnapshots cap exists -- snapshot count grows and shrinks based on unconfirmed input window
  3. The anchor snapshot at or before confirmedFrame is never deleted (always available as rollback recovery point)
  4. Input buffer entries at or before confirmedFrame are pruned instead of using a hardcoded frame offset
  5. snapshotInterval is configurable via GymScene.multiplayer() in Python and read by the JS constructor with a default of 5
**Plans**: 1 plan
- [x] 87-01-PLAN.md -- Config plumbing + confirmedFrame-based snapshot and input buffer pruning

### Phase 88: Verification
**Goal**: All existing tests pass and rollback correctness is preserved after the pruning changes
**Depends on**: Phase 87
**Requirements**: VER-01, VER-02
**Success Criteria** (what must be TRUE):
  1. All 52 existing tests pass (27 unit + 25 E2E) with zero failures
  2. Multiplayer E2E tests that exercise rollback scenarios complete successfully with correct game state
**Plans**: TBD

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1-66 | v1.0-v1.21 | - | Complete | - |
| 67-71 | v1.22 | 10/10 | Complete | 2026-02-08 |
| 72-78 | v1.23 | 13/13 | Complete | 2026-02-08 |
| 79-82 | v1.24 | 6/6 | Complete | 2026-02-09 |
| 83 | v1.25 | 1/1 | Complete | 2026-02-09 |
| 84-86 | v1.26 | 7/7 | Complete | 2026-02-10 |
| 87 | v1.27 | 1/1 | Complete | 2026-02-11 |
| 88 | v1.27 | 0/TBD | Not started | - |

---
*Roadmap created: 2026-02-11 for v1.27 Principled Rollback Management*
