---
phase: 49-episode-boundary-row-parity
verified: 2026-02-02T23:34:31Z
status: passed
score: 3/3 must-haves verified
---

# Phase 49: Episode Boundary Row Parity Verification Report

**Phase Goal:** Both players export identical row counts at episode boundaries
**Verified:** 2026-02-02T23:34:31Z
**Status:** passed
**Re-verification:** No - initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Both players export exactly the same number of rows (0 tolerance) | VERIFIED | test_focus_loss_episode_boundary_parity no longer has xfail marker; BOUND-02/03 guards cap frames at syncedTerminationFrame |
| 2 | Fast-forward processing stops at episode boundary, not after | VERIFIED | Line 4929-4936: `maxFrame = sync.syncedTerminationFrame` caps processing before frame list is built |
| 3 | _promoteRemainingAtBoundary() only promotes frames within episode boundary | VERIFIED | Lines 3006-3031: Frame filter `frame >= terminationFrame` skips post-boundary frames |

**Score:** 3/3 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `interactive_gym/server/static/js/pyodide_multiplayer_game.js` | Episode boundary guards in fast-forward path, contains "syncedTerminationFrame" | VERIFIED | 8008 lines; BOUND-02 at line 4929, BOUND-03 at lines 3006 and 5093 |
| `tests/e2e/test_data_comparison.py` | xfail marker removed from test_focus_loss_episode_boundary_parity | VERIFIED | 614 lines; no xfail markers in file; test at line 506 has only @pytest.mark.timeout(300) |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `_performFastForward()` | `syncedTerminationFrame` | maxFrame cap before building frame list | WIRED | Line 4932-4934: `if (maxFrame > sync.syncedTerminationFrame) { maxFrame = sync.syncedTerminationFrame; }` |
| `_promoteRemainingAtBoundary()` | `syncedTerminationFrame` | frame filter during promotion | WIRED | Line 3019: `if (terminationFrame !== null && terminationFrame !== undefined && frame >= terminationFrame)` |
| `storeFrameData` loop (fast-forward) | `syncedTerminationFrame` | defensive frame filter | WIRED | Line 5098-5102: Second guard in storeFrameData loop provides defense-in-depth |

### Requirements Coverage

| Requirement | Status | Blocking Issue |
|-------------|--------|----------------|
| BOUND-01: Both players export exactly same row count | SATISFIED | N/A |
| BOUND-02: Fast-forward stops at episode boundary | SATISFIED | N/A |
| BOUND-03: _promoteRemainingAtBoundary() handles backgrounded player | SATISFIED | N/A |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| pyodide_multiplayer_game.js | 4561, 4716 | TODO comments | Info | Pre-existing; not related to Phase 49; about bot RNG determinism |

No blocking anti-patterns found in Phase 49 changes.

### Human Verification Required

### 1. Focus Loss at Episode Boundary Test

**Test:** Run `python -m pytest tests/e2e/test_data_comparison.py::test_focus_loss_episode_boundary_parity -v --headed --timeout=300`
**Expected:** Test passes without xfail (PASSED, not XPASS or FAILED)
**Why human:** Test requires headed browser mode; WebRTC needs real browser

### 2. Row Count Equality

**Test:** After running test_focus_loss_episode_boundary_parity, compare row counts in exported CSV files
**Expected:** Both players export exactly max_steps (450) rows
**Why human:** Visual inspection of exported data confirms parity

### Gaps Summary

No gaps found. All three truths from the PLAN's must_haves are verified:

1. **Row count parity:** BOUND-02 caps `maxFrame` at `syncedTerminationFrame` before fast-forward processing, ensuring both players stop at the same frame. BOUND-03 provides defense-in-depth by filtering frames in both the `storeFrameData` loop and `_promoteRemainingAtBoundary()`.

2. **Fast-forward boundary:** Line 4929-4936 checks `syncedTerminationFrame` immediately after computing `maxFrame` from buffered inputs, BEFORE the `framesToProcess` calculation and frame list construction.

3. **Promotion filtering:** `_promoteRemainingAtBoundary()` now iterates through speculative frames and skips any where `frame >= terminationFrame`, with logging for skipped frames.

## Commit Verification

| Task | Commit | Message | Verified |
|------|--------|---------|----------|
| Task 1 | 6a95a1a | fix(49-01): cap fast-forward at episode boundary | Yes - BOUND-02 at line 4929 |
| Task 2 | 48cf0d7 | fix(49-01): filter post-boundary frames in _promoteRemainingAtBoundary | Yes - BOUND-03 at line 3006 |
| Task 3 | 420b9af | test(49-01): remove xfail from test_focus_loss_episode_boundary_parity | Yes - No xfail markers in test file |

---

_Verified: 2026-02-02T23:34:31Z_
_Verifier: Claude (gsd-verifier)_
