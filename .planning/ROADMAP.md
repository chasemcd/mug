# Roadmap: Multi-User Gymnasium (MUG)

## Milestones

<details>
<summary>Shipped milestones (v1.0-v1.27)</summary>

- v1.0-v1.21 Feature Branch -- Phases 1-66 (shipped)
- v1.22 GymScene Config Cleanup -- Phases 67-71 (shipped 2026-02-08)
- v1.23 Pre-Merge Cleanup -- Phases 72-78 (shipped 2026-02-08)
- v1.24 Test Fix & Hardening -- Phases 79-82 (shipped 2026-02-09)
- v1.25 Data Export Path Fix -- Phase 83 (shipped 2026-02-09)
- v1.26 Project Rename -- Phases 84-86 (shipped 2026-02-10)
- v1.27 Principled Rollback Management -- Phases 87-88 (shipped 2026-02-11)

</details>

- **v1.28 Configurable Inference** -- Phases 89-92 (in progress)

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

<details>
<summary>v1.27 Principled Rollback Management (Phases 87-88) -- SHIPPED 2026-02-11</summary>

- [x] Phase 87: ConfirmedFrame-Based Resource Management (1/1 plans) -- completed 2026-02-11
- [x] Phase 88: Verification (1/1 plans) -- completed 2026-02-11

</details>

### v1.28 Configurable Inference (In Progress)

**Milestone Goal:** Make client-side ONNX inference flexible and configurable instead of hardcoded to RLlib LSTM format.

- [x] **Phase 89: Declarative Model Config** - Python builder API for ONNX tensor config with transport to JS client -- completed 2026-02-12
- [x] **Phase 90: LSTM State Persistence** - JS runtime captures output hidden states and feeds them back on next inference -- completed 2026-02-12
- [ ] **Phase 91: Custom Inference Escape Hatch** - Inline JS function override for full inference control
- [ ] **Phase 92: Verification** - All existing tests pass with no regressions

## Phase Details

### Phase 89: Declarative Model Config
**Goal**: Users can configure ONNX model tensor names and shapes per policy via Python, and that config arrives in the JS client automatically
**Depends on**: Nothing (first phase of v1.28)
**Requirements**: DECL-01, DECL-02, DECL-03, DECL-04, DECL-05
**Success Criteria** (what must be TRUE):
  1. User can set observation input tensor name (e.g., "obs") per policy using the Python builder API and it is respected during inference
  2. User can set logit output tensor name (e.g., "output") per policy using the Python builder API and it is respected during inference
  3. User can set hidden state input/output tensor name pairs per policy (not locked to "state_in_0"/"state_out_0" convention)
  4. User can set hidden state tensor shapes per policy (not locked to [1, 256])
  5. Declarative model config specified in Python scene config is available in the JS client without manual JSON passing
**Plans:** 2 plans
Plans:
- [x] 89-01-PLAN.md -- ModelConfig dataclass + builder API + validation (Python)
- [x] 89-02-PLAN.md -- JS inference consumes declarative model config

### Phase 90: LSTM State Persistence
**Goal**: Hidden state tensors persist across inference steps so LSTM/GRU policies produce correct sequential behavior
**Depends on**: Phase 89
**Requirements**: STATE-01, STATE-02, STATE-03
**Success Criteria** (what must be TRUE):
  1. After an ONNX inference call, the output state tensors (e.g., state_out) are captured and stored for the next step
  2. On the next inference call, the previously captured state tensors are fed as input state tensors (e.g., state_in) instead of zeros
  3. On the first inference call (no prior state), hidden states are initialized to zero tensors with the shape specified in the declarative config
**Plans:** 1 plan
Plans:
- [x] 90-01-PLAN.md -- Fix hidden state keying to agentID and add legacy output state capture

### Phase 91: Custom Inference Escape Hatch
**Goal**: Users who need non-standard inference logic can provide their own JS function and bypass the declarative path entirely
**Depends on**: Phase 89
**Requirements**: CUST-01, CUST-02, CUST-03
**Success Criteria** (what must be TRUE):
  1. User can provide an inline JS function string via the Python builder API that handles ONNX inference
  2. The custom inference function receives the ONNX session, current observation, and model config as arguments
  3. When a custom inference function is specified for a policy, the declarative inference path is skipped entirely for that policy
**Plans:** 1 plan
Plans:
- [ ] 91-01-PLAN.md -- Custom inference fn on ModelConfig (Python) + JS compilation and invocation

### Phase 92: Verification
**Goal**: All existing tests pass and no regressions were introduced by the inference configurability changes
**Depends on**: Phase 89, Phase 90, Phase 91
**Requirements**: VER-01
**Success Criteria** (what must be TRUE):
  1. All unit tests pass with zero failures
  2. All E2E tests pass with zero failures
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
| 87-88 | v1.27 | 2/2 | Complete | 2026-02-11 |
| 89 | v1.28 | 2/2 | Complete | 2026-02-12 |
| 90 | v1.28 | 1/1 | Complete | 2026-02-12 |
| 91 | v1.28 | 0/? | Not started | - |
| 92 | v1.28 | 0/? | Not started | - |

---
*Roadmap updated: 2026-02-12 — Phase 90 complete*
