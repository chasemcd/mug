# Phase 48: isFocused Column Consistency - Research

**Researched:** 2026-02-02
**Domain:** Data export column consistency for focus state telemetry
**Confidence:** HIGH

## Summary

Phase 48 addresses a known limitation discovered in Phase 47: the isFocused column format is inconsistent between players when focus loss occurs. The player who loses focus exports `isFocused.0` and `isFocused.1` columns (per-player format), while the always-focused player exports only a single `isFocused` column (boolean). This causes column mismatch errors in the data comparison script.

The root cause is clear:
1. **`storeFrameData()` in step()** stores `isFocused` as a single boolean (`this.focusManager ? !this.focusManager.isBackgrounded : true`)
2. **`getFocusStatePerPlayer()`** exists and returns the correct format (`{playerId: boolean, ...}`) but is NOT used in `storeFrameData()` calls
3. **`exportEpisodeDataFromBuffer()`** uses `addAgentData('isFocused', frameData.isFocused)` which expands objects to per-agent columns but treats booleans as scalars

The fix is straightforward: replace the single boolean with `getFocusStatePerPlayer()` in all three `storeFrameData()` call sites.

**Primary recommendation:** Change `isFocused` parameter in all `storeFrameData()` calls to use `this.getFocusStatePerPlayer()` for consistent per-player column export.

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `getFocusStatePerPlayer()` | N/A | Get focus state as `{playerId: boolean}` | Already implemented and used by `phaser_gym_graphics.js` |
| `p2pEpisodeSync.partnerFocused` | N/A | Track partner's focus state | Already updated via P2P focus state messages |
| `FocusManager.isBackgrounded` | N/A | Track local focus state | Already used throughout codebase |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `exportEpisodeDataFromBuffer()` | N/A | Export data with per-agent columns | Automatically handles object->column expansion |
| `_getHumanPlayerIds()` | N/A | Get list of human player IDs | Used by `getFocusStatePerPlayer()` |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `getFocusStatePerPlayer()` | Inline focus state construction | More code duplication, less maintainable |
| Modify export to handle both formats | Use consistent format from source | Handling inconsistency at export is more complex |

**Installation:**
No external dependencies required. This uses existing methods.

## Architecture Patterns

### Current Data Format (Inconsistent)

```
step() -> storeFrameData():
  isFocused: true  // Single boolean - local player focus only

Export when no focus loss:
  isFocused: [true, true, true, ...]  // Single column

Export when focus loss occurs:
  phaser_gym_graphics.js uses getFocusStatePerPlayer():
  isFocused: {0: true, 1: false}  // Object format

  exportEpisodeDataFromBuffer():
  isFocused.0: [true, true, ...]
  isFocused.1: [false, true, ...]  // Expanded to per-agent columns
```

### Required Data Format (Consistent)

```
step() -> storeFrameData():
  isFocused: this.getFocusStatePerPlayer()  // Always object format

Export format (always):
  isFocused.0: [true, true, ...]
  isFocused.1: [true, true, ...]  // Always both columns present
```

### Pattern 1: Consistent Per-Player Focus State

**What:** Store focus state as per-player object, not single boolean.

**When to use:** Every `storeFrameData()` call.

**Example:**
```javascript
// Source: getFocusStatePerPlayer() at line 7539
// Returns: { 0: true, 1: false } where key=playerId, value=isFocused

// Old (inconsistent):
this.storeFrameData(frameNumber, {
    ...otherData,
    isFocused: this.focusManager ? !this.focusManager.isBackgrounded : true
});

// New (consistent):
this.storeFrameData(frameNumber, {
    ...otherData,
    isFocused: this.getFocusStatePerPlayer()
});
```

### Pattern 2: Export Column Expansion

**What:** `addAgentData('isFocused', frameData.isFocused)` in `exportEpisodeDataFromBuffer()` automatically expands objects to per-agent columns.

**When to use:** Automatic - no changes needed to export.

**Example:**
```javascript
// Source: exportEpisodeDataFromBuffer() at line 3725
// addAgentData iterates Object.entries and creates per-agent arrays

const addAgentData = (field, agentData) => {
    if (!agentData) return;
    for (const [agentId, value] of Object.entries(agentData)) {
        if (!data[field][agentId]) {
            data[field][agentId] = [];
        }
        data[field][agentId].push(value);
    }
};

addAgentData('isFocused', frameData.isFocused);
// If isFocused = {0: true, 1: false}:
//   data.isFocused[0].push(true)
//   data.isFocused[1].push(false)
// Resulting columns: isFocused.0, isFocused.1
```

### Anti-Patterns to Avoid

- **Storing single boolean for isFocused:** Results in inconsistent column format between players.
- **Adding columns conditionally based on focus loss:** Would require retroactive column addition.
- **Modifying export to handle both formats:** More complex than fixing at source.

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Getting both players' focus states | Manual lookup of partner focus | `getFocusStatePerPlayer()` | Already handles edge cases (partner ID lookup, defaults) |
| Converting to export columns | Custom column expansion | `addAgentData()` in export | Already iterates object entries correctly |
| Tracking partner focus state | New tracking mechanism | `p2pEpisodeSync.partnerFocused` | Already updated by P2P focus messages |

**Key insight:** All infrastructure exists. The only gap is that `storeFrameData()` calls don't use `getFocusStatePerPlayer()`.

## Common Pitfalls

### Pitfall 1: Missing Call Sites

**What goes wrong:** Some `storeFrameData()` calls still use single boolean.
**Why it happens:** Three different call sites in the codebase.
**How to avoid:** Update ALL three call sites:
  - Line 2453: `step()` normal execution
  - Line 4852: `_performRollbackCorrection()` replay
  - Line 5069: `_performFastForward()` per_frame_data
**Warning signs:** Columns match sometimes (when all sites use same format) but not always.

### Pitfall 2: Fast-Forward Focus State Override

**What goes wrong:** Fast-forward code already computes `focusStateForFF` differently.
**Why it happens:** Fast-forward has special semantics: local player was backgrounded during these frames.
**How to avoid:** Fast-forward already correctly computes per-player format:
```javascript
const focusStateForFF = {};
for (const playerId of humanPlayerIds) {
    focusStateForFF[playerId] = String(playerId) !== String(this.myPlayerId);
}
```
This is already correct! Local player = false (was backgrounded), partner = true (sent inputs).
**Warning signs:** Fast-forward isFocused values incorrect for local player.

### Pitfall 3: Rollback Replay Focus State

**What goes wrong:** Rollback replay uses current focus state instead of historical.
**Why it happens:** `getFocusStatePerPlayer()` returns current state, not state at replay frame.
**How to avoid:** This is acceptable behavior - we record the focus state at the time data was recorded, not the historical state at the frame number. Since rollback replay happens in the present, using current focus state is correct.
**Warning signs:** None expected - this is correct behavior.

### Pitfall 4: Single-Player Mode Regression

**What goes wrong:** Single-player exports break because they don't have partner.
**Why it happens:** `_getHumanPlayerIds()` returns only local player in single-player.
**How to avoid:** `getFocusStatePerPlayer()` handles this correctly - it iterates human players, so single-player gets `{localId: true/false}`. Export will have `isFocused.{localId}` column.
**Warning signs:** Single-player exports missing isFocused columns.

## Code Examples

Verified patterns from codebase:

### getFocusStatePerPlayer() Implementation

```javascript
// Source: pyodide_multiplayer_game.js, line 7539-7555
/**
 * Get current focus state for all players.
 * Returns an object mapping player IDs to their focus state (true = focused, false = backgrounded).
 * Used for per-frame data logging in CSV exports.
 * @returns {Object} {playerId: boolean, ...}
 */
getFocusStatePerPlayer() {
    const focusState = {};
    const myFocused = this.focusManager ? !this.focusManager.isBackgrounded : true;
    const partnerFocused = this.p2pEpisodeSync?.partnerFocused ?? true;

    // Get all human player IDs
    const humanPlayerIds = this._getHumanPlayerIds();
    for (const playerId of humanPlayerIds) {
        if (String(playerId) === String(this.myPlayerId)) {
            focusState[playerId] = myFocused;
        } else {
            focusState[playerId] = partnerFocused;
        }
    }

    return focusState;
}
```

### Call Site 1: step() Normal Execution (Line 2453)

```javascript
// Current (line 2459):
isFocused: this.focusManager ? !this.focusManager.isBackgrounded : true

// Fixed:
isFocused: this.getFocusStatePerPlayer()
```

### Call Site 2: Rollback Replay (Line 4852)

```javascript
// Current (line 4858):
isFocused: this.focusManager ? !this.focusManager.isBackgrounded : true

// Fixed:
isFocused: this.getFocusStatePerPlayer()
```

### Call Site 3: Fast-Forward (Line 5069)

```javascript
// Current (lines 5010-5013 and 5075):
const focusStateForFF = {};
for (const playerId of humanPlayerIds) {
    focusStateForFF[playerId] = String(playerId) !== String(this.myPlayerId);
}
// ...
isFocused: focusStateForFF

// This is ALREADY CORRECT - per-player format with correct semantics.
// No change needed here.
```

### Export Column Expansion (Line 3725)

```javascript
// Source: exportEpisodeDataFromBuffer(), line 3725
addAgentData('isFocused', frameData.isFocused);

// addAgentData implementation (lines 3687-3694):
const addAgentData = (field, agentData) => {
    if (!agentData) return;
    for (const [agentId, value] of Object.entries(agentData)) {
        if (!data[field][agentId]) {
            data[field][agentId] = [];
        }
        data[field][agentId].push(value);
    }
};
```

### phaser_gym_graphics.js Usage (Reference)

```javascript
// Source: phaser_gym_graphics.js, lines 481 and 531
// Single-player mode already uses getFocusStatePerPlayer():
isFocused: this.pyodide_remote_game.getFocusStatePerPlayer?.() || {}

// This is the correct pattern that multiplayer should match.
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Single boolean `isFocused` | Per-player object `{playerId: boolean}` | Phase 48 | Consistent columns |
| Conditional column presence | Always export both columns | Phase 48 | Data parity |

**Deprecated/outdated:**
- `isFocused: this.focusManager ? !this.focusManager.isBackgrounded : true` in storeFrameData calls
- Single boolean format for isFocused field

## Open Questions

Things that couldn't be fully resolved:

1. **Historical Focus State During Rollback Replay**
   - What we know: Rollback replay uses current focus state, not historical state at frame time.
   - What's unclear: Should we store historical focus state for replay accuracy?
   - Recommendation: Current behavior is acceptable. Focus state at frame N matters for understanding when data was "truly" recorded, which is now (during replay), not the original frame time.

2. **Comparison Script isFocused Handling**
   - What we know: Currently isFocused columns are not excluded from comparison.
   - What's unclear: Should isFocused columns be compared for parity?
   - Recommendation: Yes, compare them. If both players use `getFocusStatePerPlayer()`, both will have same columns. The values may differ (each player knows their own focus state), but columns should match.

## Sources

### Primary (HIGH confidence)
- `pyodide_multiplayer_game.js` lines 7539-7555 - `getFocusStatePerPlayer()` implementation
- `pyodide_multiplayer_game.js` lines 2453-2460 - `step()` storeFrameData call
- `pyodide_multiplayer_game.js` lines 4852-4859 - Rollback replay storeFrameData call
- `pyodide_multiplayer_game.js` lines 5069-5076 - Fast-forward storeFrameData call
- `pyodide_multiplayer_game.js` lines 3687-3725 - Export column expansion
- `phaser_gym_graphics.js` lines 481, 531 - Reference correct usage pattern

### Secondary (HIGH confidence)
- `.planning/phases/47-focus-loss-testing/47-01-SUMMARY.md` - Discovery of limitation
- `.planning/STATE.md` - Known limitations documentation
- `tests/e2e/test_data_comparison.py` - xfail marker documentation

### Tertiary (N/A)
- No external sources needed; this is a codebase-specific fix

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Uses existing `getFocusStatePerPlayer()` method
- Architecture: HIGH - Clear pattern already used by phaser_gym_graphics.js
- Pitfalls: HIGH - Limited call sites, clear fix

**Research date:** 2026-02-02
**Valid until:** Until data recording architecture changes (stable)

## Implementation Summary

### Files to Modify

| File | Changes |
|------|---------|
| `interactive_gym/server/static/js/pyodide_multiplayer_game.js` | Update 2 `storeFrameData()` calls to use `getFocusStatePerPlayer()` |

### Call Sites to Update

1. **Line 2459** (step() normal execution):
   - Change: `isFocused: this.focusManager ? !this.focusManager.isBackgrounded : true`
   - To: `isFocused: this.getFocusStatePerPlayer()`

2. **Line 4858** (rollback replay):
   - Change: `isFocused: this.focusManager ? !this.focusManager.isBackgrounded : true`
   - To: `isFocused: this.getFocusStatePerPlayer()`

3. **Line 5075** (fast-forward): **NO CHANGE NEEDED**
   - Already uses per-player format via `focusStateForFF`
   - Has correct semantics (local=false, partner=true during fast-forward)

### Success Verification

- [ ] Both players export `isFocused.0` and `isFocused.1` columns regardless of focus events
- [ ] Column names match between both players' exports
- [ ] `test_focus_loss_mid_episode_parity` passes without xfail marker (column mismatch fixed)
- [ ] Values reflect actual focus state: true when focused, false when backgrounded
- [ ] Single-player mode still works (exports single player's isFocused column)

### Test Verification Approach

1. **Remove xfail marker** from `test_focus_loss_mid_episode_parity` in `tests/e2e/test_data_comparison.py`
2. **Run the test**: `pytest tests/e2e/test_data_comparison.py::test_focus_loss_mid_episode_parity -v`
3. **Verify column parity**: Both exports should have same column names
4. **Verify values**: isFocused.0 and isFocused.1 should reflect correct focus states

### Edge Cases to Handle

| Case | Expected Behavior | How Handled |
|------|-------------------|-------------|
| No focus loss | Both isFocused.X columns = true for all frames | `getFocusStatePerPlayer()` returns both players focused |
| Mid-episode focus loss | Local player column shows false during background | FocusManager.isBackgrounded tracked |
| Partner loses focus | Partner column shows false when notified | p2pEpisodeSync.partnerFocused updated via P2P |
| Fast-forward after refocus | Local=false, Partner=true for FF frames | Already correct (focusStateForFF) |
| Rollback replay | Uses current focus state | `getFocusStatePerPlayer()` called at replay time |
| Episode boundary | Normal handling, no special case | Frame data stored before boundary promotion |

---
*Phase: 48-isfocused-column-consistency*
*Researched: 2026-02-02*
