---
phase: 73-production-bug-fixes
plan: 01
subsystem: p2p-multiplayer
tags: [ggpo, rollback, dual-buffer, data-parity, state-sync, cogrid]

dependency_graph:
  requires: [72-test-infrastructure-fixes, 71-test-audit, 69-multiplayer-batch-operations, 36-buffer-split]
  provides: [rollback-promotion-guards, cogrid-state-sync, numpy-state-serialization]
  affects: [74-stability-validation]

tech_stack:
  added: []
  patterns:
    - "Promotion guard pattern: all promotion paths check pendingRollbackFrame/rollbackInProgress before promoting"
    - "Post-reset state sync revalidation: re-run validateStateSync after first reset for environments that need reset before get_state works"
    - "NumpyEncoder pattern: custom JSON encoder for numpy types in environment state serialization"

files:
  key_files:
    created: []
    modified:
      - interactive_gym/server/static/js/pyodide_multiplayer_game.js
      - interactive_gym/server/static/js/pyodide_worker.js

decisions:
  - id: "73-01-D1"
    decision: "Guard _promoteConfirmedFrames and _updateConfirmedFrame against pending rollback/rollbackInProgress"
    rationale: "Universal safety net -- no promotion path can ever promote uncorrected speculative data regardless of calling code path"
  - id: "73-01-D2"
    decision: "Execute pending rollbacks inside _waitForInputConfirmation polling loop before promoting"
    rationale: "Episode-end input confirmation was the primary bug location -- late-arriving inputs set pendingRollbackFrame but rollback never executed before promotion"
  - id: "73-01-D3"
    decision: "Re-validate state sync after first reset instead of only during initialize"
    rationale: "Cogrid environments populate env_agents during reset(), not __init__(). Pre-reset get_state() fails, causing stateSyncSupported=false, which disables all rollback execution permanently"
  - id: "73-01-D4"
    decision: "Add NumpyEncoder for state serialization in pyodide_worker.js"
    rationale: "Cogrid get_state() returns dicts containing numpy arrays (bit_generator.state). json.dumps fails without custom encoder"
  - id: "73-01-D5"
    decision: "Log warning (not error) in signalEpisodeComplete when pendingRollbackFrame still set"
    rationale: "Safety net only -- actual rollback should have been executed by _waitForInputConfirmation; warning enables debugging if it ever fires"

metrics:
  duration: "~4 hours (debugging and root cause analysis)"
  completed: "2026-02-05"
  tasks_completed: 2
  tasks_total: 2
  commits: 2
---

# Phase 73 Plan 01: Fix Rollback/Promotion Race Condition Summary

**One-liner:** Fixed dual-buffer promotion race by guarding all promotion paths against pending rollbacks, and enabled cogrid state sync by re-validating after first reset.

## What Was Done

### Task 1: Fix rollback/promotion race condition in dual-buffer system (commit 7bcf37f)

Applied four coordinated fixes to `pyodide_multiplayer_game.js`:

**Fix A: Guard `_promoteConfirmedFrames()` against pending rollback**
- Added guard at function entry: `if (this.pendingRollbackFrame !== null || this.rollbackInProgress) { return; }`
- Universal safety net preventing any promotion of uncorrected speculative data

**Fix B: Guard `_updateConfirmedFrame()` during rollback**
- Added guard at function entry: `if (this.rollbackInProgress) { return; }`
- Prevents mid-rollback confirmation advancement that could trigger promotion

**Fix C: Execute pending rollback in `_waitForInputConfirmation()` before promoting**
- Added rollback execution in the "already confirmed" fast path
- Added rollback execution inside the polling loop after `_processQueuedInputs()`
- Added rollback execution after timeout before proceeding
- This was the primary bug location: late-arriving inputs set `pendingRollbackFrame` but rollback never executed before promotion at episode end

**Fix D: Warning in `signalEpisodeComplete()` for uncorrected pending rollback**
- Added `console.warn` if `pendingRollbackFrame` is still set before `_promoteRemainingAtBoundary()`
- Safety net for debugging; actual rollback should have been handled by Fix C

### Task 1 (amendment): Enable rollback state sync for cogrid environments (commit c68ac0e)

During testing, discovered that Fixes A-D alone did not resolve the issue because rollbacks were never actually executing. Root cause chain:

1. `validateStateSync()` called during `initialize()` before `reset()`
2. Cogrid `env.get_state()` fails with `AttributeError: 'NoneType' object has no attribute 'get_state'` because `env_agents` populated during `reset()`, not `__init__()`
3. `stateSyncSupported` set to `false` permanently
4. `performRollback()` returns early at line 4466 without executing snapshot load or replay
5. Mispredicted frames stay in `speculativeFrameData` with wrong predicted actions
6. Promotion promotes uncorrected data even with guards (guards only protect against pending rollbacks, but if rollback never executes, data is never corrected)

**Fix in `pyodide_multiplayer_game.js`:**
```javascript
// After worker.reset() in reset() method:
if (!this.stateSyncSupported && this.num_episodes === 0) {
    await this.validateStateSync();
}
```

**Fix in `pyodide_worker.js`:**
- Added `_NumpyEncoder` class in `handleGetStateInternal` for numpy array/integer/float/bool serialization
- Added `import numpy as np` and numpy type handling in `handleComputeHashInternal` normalizer

### Task 2: Verify fix with E2E tests

**Previously-failing tests (target: 3/3 pass):**

| Test | Result | Notes |
|------|--------|-------|
| `test_active_input_parity` | PASSED | 0 divergences (previously 98) |
| `test_active_input_with_latency[100]` | FAILED | Pre-existing episode boundary issue (see below) |
| `test_active_input_with_packet_loss` | PASSED | 0 divergences (previously 18) |

**Regression tests (target: 5/5 pass):**

| Test | Result |
|------|--------|
| `test_export_parity_basic` | PASSED |
| `test_export_parity_with_latency` | PASSED |
| `test_focus_loss_mid_episode_parity` | PASSED |
| `test_episode_completion_under_fixed_latency[100]` | PASSED |
| `test_packet_loss_triggers_rollback` | PASSED |

**Score: 7/8 tests pass (2/3 target + 5/5 regression)**

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] State sync revalidation after first reset**

- **Found during:** Task 2 (test verification)
- **Issue:** `validateStateSync()` runs during `initialize()` before `reset()`. Cogrid environments fail `get_state()` pre-reset because `env_agents` is None. This permanently disables rollback execution (`stateSyncSupported=false`), making all four promotion guards ineffective since rollbacks never actually correct data.
- **Fix:** Added post-first-reset revalidation: `if (!this.stateSyncSupported && this.num_episodes === 0) { await this.validateStateSync(); }`
- **Files modified:** `interactive_gym/server/static/js/pyodide_multiplayer_game.js`
- **Commit:** c68ac0e

**2. [Rule 2 - Missing Critical] NumpyEncoder for state serialization**

- **Found during:** Task 2 (test verification)
- **Issue:** Cogrid `get_state()` returns dicts containing numpy arrays (`bit_generator.state`), numpy integers, and numpy floats. `json.dumps()` in `handleGetStateInternal` fails with `TypeError: Object of type ndarray is not JSON serializable`.
- **Fix:** Added `_NumpyEncoder` class that converts numpy arrays to lists, numpy integers/floats to Python native types. Added numpy type handling in `handleComputeHashInternal` normalizer.
- **Files modified:** `interactive_gym/server/static/js/pyodide_worker.js`
- **Commit:** c68ac0e

## Known Issues

### Pre-existing: Latency test episode boundary divergence

`test_active_input_with_latency[100]` fails with `t` column and action divergences at the episode boundary (rows 455+, where max_steps=450).

**Root cause:** `this.step_num += replayLog.length` at line 4686 of `performRollback()` double-counts steps during rollback replay. This inflates `step_num`, causing premature `step_num >= max_steps` episode termination on the peer that experiences more rollbacks. The two peers terminate at different rows (466 vs 460) instead of the same row.

**Why not fixed here:** Removing the line causes episodes to never terminate (709 vs 722 rows). The `step_num` vs `frameNumber` relationship during rollback needs deeper investigation into how episode termination should be computed in a GGPO rollback system. This is a separate architectural issue from the rollback/promotion race condition.

**Improvement from this fix:** Before: 243+ divergences across all frames. After: ~20 divergences only at the episode boundary. The core data parity within the episode body is now correct.

## Decisions Made

| ID | Decision | Rationale |
|----|----------|-----------|
| 73-01-D1 | Guard promotion functions against pending rollback | Universal safety net for all promotion code paths |
| 73-01-D2 | Execute pending rollbacks in _waitForInputConfirmation | Primary bug fix: episode-end promotion without rollback correction |
| 73-01-D3 | Re-validate state sync after first reset | Cogrid env_agents populated during reset(), not __init__() |
| 73-01-D4 | NumpyEncoder for state serialization | Cogrid state contains numpy types that break json.dumps |
| 73-01-D5 | Warning (not error) in signalEpisodeComplete | Safety net for debugging; actual rollback handled elsewhere |

## Commits

| Hash | Type | Description |
|------|------|-------------|
| 7bcf37f | fix | Fix rollback/promotion race condition in dual-buffer system |
| c68ac0e | fix | Enable rollback state sync for cogrid environments |

## Files Modified

| File | Changes |
|------|---------|
| `interactive_gym/server/static/js/pyodide_multiplayer_game.js` | +60 lines: promotion guards (A,B), _waitForInputConfirmation rollback execution (C), signalEpisodeComplete warning (D), post-reset state sync revalidation |
| `interactive_gym/server/static/js/pyodide_worker.js` | +24 lines: NumpyEncoder class, numpy type handling in hash normalizer |

## Next Phase Readiness

**Phase 74 (Stability Validation) can proceed with the following notes:**

1. **7/8 target tests pass** -- the latency test failure is a pre-existing episode boundary issue separate from the rollback/promotion race condition
2. **The `step_num` double-counting during rollback** needs investigation in Phase 74 or a future phase. It affects only the latency test scenario where rollback frequency is high enough to cause measurable `step_num` inflation.
3. **All promotion paths are now guarded** -- future code that calls `_promoteConfirmedFrames()` or `_updateConfirmedFrame()` will be protected by the guards added in this plan.
4. **State sync revalidation pattern** should be considered for any future environments where `get_state()` requires `reset()` to have been called first.
