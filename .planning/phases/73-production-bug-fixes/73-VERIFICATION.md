---
phase: 73-production-bug-fixes
verified: 2026-02-05T16:30:00Z
status: gaps_found
score: 4/5 must-haves verified
gaps:
  - truth: "Active input with 100ms latency passes with zero divergences (test_active_input_with_latency[100])"
    status: failed
    reason: "Test fails due to pre-existing step_num double-counting during rollback at episode boundary. SUMMARY reports ~20 divergences at episode boundary rows (455+) instead of 0. The rollback/promotion race fix reduced divergences from 243+ to ~20, but did not eliminate them."
    artifacts:
      - path: "interactive_gym/server/static/js/pyodide_multiplayer_game.js"
        issue: "performRollback() line ~4686 has step_num += replayLog.length which inflates step_num under high rollback frequency, causing peers to terminate at different rows"
    missing:
      - "Fix for step_num vs frameNumber accounting during rollback replay"
      - "Episode termination logic that does not depend on step_num inflation"
human_verification:
  - test: "Run test_active_input_parity E2E test"
    expected: "PASSED with 0 divergences"
    why_human: "E2E tests require live Playwright browser automation against running server; cannot verify programmatically in code review"
  - test: "Run test_active_input_with_packet_loss E2E test"
    expected: "PASSED with 0 divergences"
    why_human: "E2E tests require live Playwright browser automation against running server"
  - test: "Run test_active_input_with_latency[100] E2E test"
    expected: "Currently FAILS with ~20 divergences at episode boundary (pre-existing issue)"
    why_human: "Need to confirm divergence count and verify they are only at boundary"
  - test: "Run full regression suite (5 tests)"
    expected: "All 5 pass"
    why_human: "E2E tests require running environment"
---

# Phase 73: Production Bug Fixes Verification Report

**Phase Goal:** Fix rollback/promotion race condition in dual-buffer data recording that causes active input data parity divergences
**Verified:** 2026-02-05T16:30:00Z
**Status:** gaps_found
**Re-verification:** No -- initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Active input parity test passes with zero divergences (test_active_input_parity) | VERIFIED | All four fixes (A-D) present in source; SUMMARY reports PASSED with 0 divergences (was 98). Cannot re-run E2E test but code structure confirms race condition is addressed. |
| 2 | Active input with 100ms latency passes with zero divergences (test_active_input_with_latency[100]) | FAILED | SUMMARY reports FAILED with ~20 divergences at episode boundary (rows 455+, max_steps=450). step_num double-counting in performRollback() causes premature termination under high rollback frequency. Reduced from 243+ divergences but not zero. |
| 3 | Active input with packet loss passes with zero divergences (test_active_input_with_packet_loss) | VERIFIED | All four fixes present; SUMMARY reports PASSED with 0 divergences (was 18). |
| 4 | All previously-passing parity tests continue to pass (idle, latency, focus loss) | VERIFIED | No test modifications or xfail markers added. SUMMARY reports 5/5 regression tests pass. |
| 5 | Rollback mechanism still functions correctly (test_packet_loss_triggers_rollback passes) | VERIFIED | Rollback mechanism enhanced, not degraded. stateSyncSupported revalidation ensures rollbacks actually execute for cogrid environments. |

**Score:** 4/5 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `interactive_gym/server/static/js/pyodide_multiplayer_game.js` | Fixed dual-buffer promotion logic with rollback guards | VERIFIED (exists, substantive, wired) | 7844 lines. Contains all 4 planned fixes + 1 auto-discovered fix (state sync revalidation). File is the core multiplayer game engine, deeply wired into the application. |
| `interactive_gym/server/static/js/pyodide_worker.js` | NumpyEncoder for state serialization (auto-discovered) | VERIFIED (exists, substantive, wired) | 605 lines. NumpyEncoder class at line 330, numpy handling in hash normalizer at lines 460-467. Used by handleGetStateInternal and handleComputeHashInternal. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `_promoteConfirmedFrames()` | `pendingRollbackFrame` | guard check at function entry | VERIFIED | Line 2850: `if (this.pendingRollbackFrame !== null \|\| this.rollbackInProgress) { return; }` -- exact pattern from plan |
| `_waitForInputConfirmation()` | `performRollback()` | execute pending rollback before promoting | VERIFIED | Lines 2898-2901 (fast path), 2921-2925 (poll loop), 2941-2945 (timeout) -- three rollback execution points covering all paths |
| `_updateConfirmedFrame()` | `rollbackInProgress` | guard check prevents mid-rollback confirmation advancement | VERIFIED | Line 2800: `if (this.rollbackInProgress) { return; }` -- exact pattern from plan |
| `signalEpisodeComplete()` | `pendingRollbackFrame` | warning before boundary promotion | VERIFIED | Lines 3673-3675: `console.warn` if pendingRollbackFrame still set before `_promoteRemainingAtBoundary()` |
| `validateStateSync()` | `reset()` | re-validate after first reset | VERIFIED | Line 1934: `if (!this.stateSyncSupported && this.num_episodes === 0) { await this.validateStateSync(); }` |
| `performRollback()` | `stateSyncSupported` | early return if not supported | VERIFIED | Line 4391: `if (!this.stateSyncSupported) { return false; }` -- state sync revalidation makes this path work for cogrid |
| `performRollback()` | `rollbackInProgress` | set/unset flag | VERIFIED | Set at line 4397, unset in `finally` block at line 4709 -- properly protected against exceptions |
| `storeRemoteInput()` | `pendingRollbackFrame` | misprediction detection triggers rollback | VERIFIED | Lines 4144-4147 (misprediction) and 4152-4155 (no record fallback) correctly set `pendingRollbackFrame` |
| `NumpyEncoder` | `handleGetStateInternal` | custom JSON encoder | VERIFIED | Line 359: `cls=_NumpyEncoder` passed to `json.dumps` |
| `numpy types` | `handleComputeHashInternal` normalizer | type handling in hash function | VERIFIED | Lines 460-467: `hasattr(obj, 'tolist')`, `np.integer`, `np.floating`, `np.bool_` handling |

### Requirements Coverage

| Requirement | Status | Blocking Issue |
|-------------|--------|----------------|
| PROD-01: Production code bugs revealed by E2E tests are fixed | MOSTLY SATISFIED | 2/3 target tests pass. The latency test failure is a pre-existing step_num accounting issue, not a new production bug from the Worker migration. |
| PROD-02: Pre-existing functionality regressions from Worker migration are fixed | SATISFIED | State sync revalidation (cogrid get_state pre-reset failure) and NumpyEncoder (numpy serialization in Worker) both fix Worker-migration-specific issues. All 5 regression tests pass. |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| pyodide_multiplayer_game.js | 4379 | `TODO: For full determinism, bot actions should be re-computed with correct RNG state.` | Info | Pre-existing, not introduced by this phase. Bot action determinism during rollback is a known limitation. |
| pyodide_multiplayer_game.js | 4534 | `TODO: Ideally re-compute with correct RNG state for full determinism` | Info | Pre-existing, same issue as above. |

No new anti-patterns introduced by Phase 73.

### Human Verification Required

### 1. E2E Test Suite Execution

**Test:** Run `python -m pytest tests/e2e/test_data_comparison.py::test_active_input_parity tests/e2e/test_network_disruption.py::test_active_input_with_packet_loss -xvs`
**Expected:** Both tests PASS with 0 divergences
**Why human:** E2E tests require Playwright browser automation against a live Flask server with Pyodide initialization

### 2. Latency Test Verification

**Test:** Run `python -m pytest tests/e2e/test_latency_injection.py::test_active_input_with_latency[100] -xvs`
**Expected:** FAILS with divergences only at episode boundary rows (455+), not within episode body
**Why human:** Need to inspect actual divergence output to confirm they are boundary-only

### 3. Regression Suite

**Test:** Run the 5 regression tests: test_export_parity_basic, test_export_parity_with_latency, test_focus_loss_mid_episode_parity, test_episode_completion_under_fixed_latency[100], test_packet_loss_triggers_rollback
**Expected:** All 5 PASS
**Why human:** E2E tests require live environment

### Gaps Summary

One must-have truth failed: `test_active_input_with_latency[100]` does not pass with zero divergences. The SUMMARY documents this as a pre-existing episode boundary issue caused by `step_num += replayLog.length` in `performRollback()` (line ~4686), which double-counts steps during rollback replay. Under high rollback frequency (100ms latency causes many rollbacks), this inflates `step_num` enough to cause premature episode termination on the peer with more rollbacks.

This is a meaningful gap but is arguably outside the scope of the rollback/promotion race condition fix, which was the stated phase goal. The core race condition (speculative data promoted before rollback correction) is fully fixed -- all four planned guards are in place plus the auto-discovered state sync revalidation. The remaining issue is a separate step_num accounting bug in the rollback replay mechanism itself.

**Impact assessment:**
- 2/3 previously-failing target tests now pass (was 0/3)
- 5/5 regression tests continue to pass
- The one remaining failure is reduced from 243+ divergences to ~20, and only at episode boundary
- The root cause (step_num inflation) is well-understood and documented for future work

---

_Verified: 2026-02-05T16:30:00Z_
_Verifier: Claude (gsd-verifier)_
