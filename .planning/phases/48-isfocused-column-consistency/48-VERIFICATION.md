---
phase: 48-isfocused-column-consistency
verified: 2026-02-02T19:15:00Z
status: passed
score: 3/3 must-haves verified
human_verification:
  - test: "Run test_focus_loss_mid_episode_parity in headed mode"
    expected: "Test passes without xfail marker"
    why_human: "E2E test requires headed browser with WebRTC"
  - test: "Run test_export_parity_basic in headed mode"
    expected: "Test passes (no regression)"
    why_human: "E2E test requires headed browser with WebRTC"
---

# Phase 48: isFocused Column Consistency Verification Report

**Phase Goal:** Both players export consistent focus state columns
**Verified:** 2026-02-02T19:15:00Z
**Status:** passed
**Re-verification:** No - initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Both players export isFocused.0 and isFocused.1 columns regardless of focus events | VERIFIED | All 4 storeFrameData calls use getFocusStatePerPlayer() which returns {playerId: boolean} format |
| 2 | isFocused values reflect actual focus state (true when focused, false when backgrounded) | VERIFIED | getFocusStatePerPlayer() uses focusManager.isBackgrounded for local and p2pEpisodeSync.partnerFocused for partner |
| 3 | Column names match between both players' exports | VERIFIED | Both players use same getFocusStatePerPlayer() method with same export addAgentData expansion |

**Score:** 3/3 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| \`pyodide_multiplayer_game.js\` | getFocusStatePerPlayer() used in storeFrameData | VERIFIED | Lines 2365, 2459, 4719, 4858 use getFocusStatePerPlayer(); method defined at line 7539 |
| \`validate_action_sequences.py\` | isFocused columns excluded from comparison | VERIFIED | Lines 48-49 add isFocused.0 and isFocused.1 to COLUMNS_EXCLUDE_FROM_COMPARE |
| \`test_data_comparison.py\` | xfail removed from mid-episode test | VERIFIED | test_focus_loss_mid_episode_parity at line 381 has no xfail marker |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| storeFrameData() calls | getFocusStatePerPlayer() | isFocused parameter | WIRED | 4 call sites verified with grep pattern match |
| getFocusStatePerPlayer() | FocusManager | isBackgrounded property | WIRED | Line 7541: myFocused = !this.focusManager.isBackgrounded |
| getFocusStatePerPlayer() | p2pEpisodeSync | partnerFocused property | WIRED | Line 7542: partnerFocused = this.p2pEpisodeSync?.partnerFocused |
| addAgentData() | isFocused export | Object.entries expansion | WIRED | Line 3725: addAgentData('isFocused', frameData.isFocused) |

### Requirements Coverage

| Requirement | Status | Notes |
|-------------|--------|-------|
| FOCUS-COL-01: Both players export isFocused.0 and isFocused.1 columns regardless of focus events | SATISFIED | getFocusStatePerPlayer() always returns per-player format |
| FOCUS-COL-02: isFocused columns contain accurate values | SATISFIED | Values come from focusManager and p2pEpisodeSync |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| pyodide_multiplayer_game.js | 4545, 4700 | TODO: bot determinism during rollback | Info | Pre-existing, unrelated to Phase 48 |
| test_data_comparison.py | 400-404 | Stale docstring mentioning xfail | Info | Documentation out of sync with code, no functional impact |

### Human Verification Required

The following items require human verification because they involve E2E tests that need headed browsers with WebRTC:

### 1. Test Mid-Episode Focus Loss Parity

**Test:** Run \`pytest tests/e2e/test_data_comparison.py::test_focus_loss_mid_episode_parity -v --headed --timeout=300\`
**Expected:** Test passes without xfail marker
**Why human:** E2E test requires headed browser with WebRTC and real focus loss simulation

### 2. Test Basic Export Parity (Regression Check)

**Test:** Run \`pytest tests/e2e/test_data_comparison.py::test_export_parity_basic -v --headed --timeout=300\`
**Expected:** Test passes (no regression from Phase 48 changes)
**Why human:** E2E test requires headed browser with WebRTC

### Verification Commands Used

\`\`\`bash
# Check old pattern removed (should return 0)
grep -c "isFocused:.*focusManager" interactive_gym/server/static/js/pyodide_multiplayer_game.js
# Result: 0

# Check new pattern added (should return 4)
grep -c "isFocused:.*getFocusStatePerPlayer" interactive_gym/server/static/js/pyodide_multiplayer_game.js
# Result: 4

# Check method exists
grep -n "getFocusStatePerPlayer()" interactive_gym/server/static/js/pyodide_multiplayer_game.js | head -5
# Result: Lines 2365, 2459, 4719, 4858, 7539

# Check xfail markers
grep -B5 "def test_focus_loss_mid_episode_parity" tests/e2e/test_data_comparison.py
# Result: No xfail marker

grep -B2 "def test_focus_loss_episode_boundary_parity" tests/e2e/test_data_comparison.py
# Result: xfail with "Phase 49" in reason
\`\`\`

### Summary

Phase 48 goal is achieved:

1. **Code changes verified:** All 4 storeFrameData call sites now use \`getFocusStatePerPlayer()\` instead of the single boolean pattern
2. **Export format consistent:** Both players will export isFocused.0 and isFocused.1 columns because \`getFocusStatePerPlayer()\` returns \`{playerId: boolean}\` format for all human players
3. **Test markers updated:** \`test_focus_loss_mid_episode_parity\` no longer has xfail marker; \`test_focus_loss_episode_boundary_parity\` retains xfail with Phase 49 scope
4. **Comparison script updated:** isFocused columns excluded from parity comparison due to expected notification latency divergence

The automated structural verification passes. Human verification is recommended to confirm E2E tests pass in headed mode.

---

*Verified: 2026-02-02T19:15:00Z*
*Verifier: Claude (gsd-verifier)*
