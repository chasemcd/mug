# Phase 37: Fast-Forward Data Recording Fix - Research

**Researched:** 2026-01-30
**Domain:** Fast-forward code path integration with dual-buffer data recording architecture
**Confidence:** HIGH

## Summary

Phase 37 fixes a critical gap in the data recording architecture introduced by Phase 36. The fast-forward code path (`_performFastForward()`) correctly calls `storeFrameData()` to write frame data, but it bypasses the confirmation-gated promotion path by directly setting `confirmedFrame` instead of calling `_updateConfirmedFrame()`.

The issue is clear and localized:
- Fast-forward stores data in `speculativeFrameData` (correct per Phase 36)
- Fast-forward directly sets `this.confirmedFrame = this.frameNumber - 1` (line 5025)
- **No call to `_promoteConfirmedFrames()`** after fast-forward completes
- Result: Data stays in speculative buffer, never promoted to `frameDataBuffer`, causing export gaps

The fix is straightforward: after fast-forward updates `confirmedFrame`, call `_promoteConfirmedFrames()` to promote the fast-forwarded frames to the canonical buffer.

**Primary recommendation:** Add `this._promoteConfirmedFrames()` call immediately after the `this.confirmedFrame = this.frameNumber - 1` line in `_performFastForward()`.

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Existing `_promoteConfirmedFrames()` | N/A | Promote speculative to canonical | Already implemented in Phase 36 |
| Existing `storeFrameData()` | N/A | Write to speculative buffer | Already called by fast-forward |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `speculativeFrameData` Map | ES6+ | Unconfirmed frame storage | During fast-forward frame stepping |
| `frameDataBuffer` Map | ES6+ | Confirmed frame storage | After promotion |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Call `_promoteConfirmedFrames()` | Call `_updateConfirmedFrame()` | Overkill - would re-scan input buffer unnecessarily; fast-forward already knows frames are confirmed |
| Single promotion call at end | Promotion after each frame | Unnecessary complexity; batch promotion is efficient |

**Installation:**
No external dependencies required. This is a one-line fix using existing infrastructure.

## Architecture Patterns

### Current Fast-Forward Data Flow (Broken)

```
Tab refocus triggers _performFastForward()
            |
            v
For each frame: step() via Python batch
            |
            v
storeFrameData() -> speculativeFrameData[N] = {...}  [CORRECT]
            |
            v
this.confirmedFrame = this.frameNumber - 1  [BYPASSES _updateConfirmedFrame]
            |
            v
[NO PROMOTION CALL]  <-- BUG: data stays in speculative buffer
            |
            v
Episode ends, export reads only frameDataBuffer
            |
            v
MISSING FRAMES in export (all fast-forwarded frames)
```

### Fixed Fast-Forward Data Flow

```
Tab refocus triggers _performFastForward()
            |
            v
For each frame: step() via Python batch
            |
            v
storeFrameData() -> speculativeFrameData[N] = {...}  [CORRECT]
            |
            v
this.confirmedFrame = this.frameNumber - 1  [confirmedFrame updated]
            |
            v
this._promoteConfirmedFrames()  <-- FIX: promote all fast-forward frames
            |
            v
frameDataBuffer contains all fast-forward frames
            |
            v
Episode ends, export reads frameDataBuffer
            |
            v
COMPLETE DATA (no gaps)
```

### Pattern 1: Post-Confirmation Promotion

**What:** After any operation that advances `confirmedFrame`, call `_promoteConfirmedFrames()`.

**When to use:** Any code path that:
1. Stores frame data via `storeFrameData()`, AND
2. Updates `confirmedFrame` directly (not via `_updateConfirmedFrame()`)

**Example:**
```javascript
// Source: _performFastForward() in pyodide_multiplayer_game.js, line 5025
// Current (broken):
this.confirmedFrame = this.frameNumber - 1;

// Fixed:
this.confirmedFrame = this.frameNumber - 1;
// Promote fast-forward frames to canonical buffer (Phase 37)
this._promoteConfirmedFrames();
```

### Pattern 2: Consistency Check

**What:** Verify that fast-forward follows the same confirmation gating as normal execution.

**When to use:** When auditing data recording paths.

**Audit checklist:**
- [ ] Frame data stored via `storeFrameData()` (writes to speculative buffer)
- [ ] `confirmedFrame` updated to reflect confirmed state
- [ ] `_promoteConfirmedFrames()` called after `confirmedFrame` update
- [ ] No direct writes to `frameDataBuffer`

### Anti-Patterns to Avoid

- **Direct `confirmedFrame` update without promotion:** Setting `confirmedFrame` alone leaves data stranded in speculative buffer.
- **Skipping `storeFrameData()` during fast-forward:** Would cause missing frames even if promotion worked.
- **Writing directly to `frameDataBuffer`:** Bypasses the dual-buffer architecture; all writes should go through `storeFrameData()` -> speculative -> promotion.

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Promoting frames after fast-forward | Custom promotion loop | `_promoteConfirmedFrames()` | Already handles all edge cases (iteration, deletion, logging) |
| Determining which frames to promote | Frame range calculation | `frame <= confirmedFrame` check in `_promoteConfirmedFrames()` | Already implemented correctly |
| Logging promotion activity | Custom logging | Existing debug log in `_promoteConfirmedFrames()` | Consistent with normal flow |

**Key insight:** Phase 36 already implemented all the infrastructure. Phase 37 just needs to use it in the fast-forward path.

## Common Pitfalls

### Pitfall 1: Calling `_updateConfirmedFrame()` Instead of Just `_promoteConfirmedFrames()`

**What goes wrong:** Unnecessary work; `_updateConfirmedFrame()` scans input buffer to find confirmed frames.
**Why it happens:** Seems like the "safe" option since normal step() uses it.
**How to avoid:** Fast-forward already knows all processed frames are confirmed (it used real inputs from buffered packets). Just call `_promoteConfirmedFrames()`.
**Warning signs:** Performance degradation during fast-forward; unnecessary hash computation.

### Pitfall 2: Promotion Before `confirmedFrame` Update

**What goes wrong:** `_promoteConfirmedFrames()` promotes frames where `frame <= confirmedFrame`. If called before update, no frames qualify.
**Why it happens:** Incorrect ordering of the fix.
**How to avoid:** The call to `_promoteConfirmedFrames()` must be AFTER `this.confirmedFrame = this.frameNumber - 1`.
**Warning signs:** Promotion log shows 0 frames promoted after fast-forward.

### Pitfall 3: Missing Verification After Fast-Forward

**What goes wrong:** Bug isn't detected until full episode export.
**Why it happens:** Fast-forward appears to work (game state is correct), but data isn't exported.
**How to avoid:** Add verification log or assertion after fast-forward.
**Warning signs:** `speculativeFrameData.size` is large after fast-forward, `frameDataBuffer.size` doesn't increase.

### Pitfall 4: Breaking Existing Rollback Behavior

**What goes wrong:** Rollback during or after fast-forward behaves incorrectly.
**Why it happens:** Not understanding interaction between fast-forward, rollback, and confirmation.
**How to avoid:** Fast-forward sets `rollbackInProgress = true` during execution, preventing interference. After fast-forward, `rollbackInProgress = false` and normal GGPO resumes.
**Warning signs:** Rollbacks triggered during fast-forward; data cleared unexpectedly.

## Code Examples

Verified patterns from existing codebase:

### Current `_performFastForward()` Code (Relevant Section)

```javascript
// Source: pyodide_multiplayer_game.js, lines 5002-5025

// Store per-frame data in the rollback-safe buffer
// Note: isFocused=false for local player during fast-forward
for (const frameData of ffResult.per_frame_data) {
    this.storeFrameData(frameData.frame, {
        actions: frameData.actions,
        rewards: frameData.rewards,
        terminateds: frameData.terminateds,
        truncateds: frameData.truncateds,
        infos: frameData.infos,
        isFocused: focusStateForFF
    });
}
p2pLog.debug(`Stored ${ffResult.per_frame_data.length} fast-forward frames in data buffer`);

framesProcessed = fastForwardFrames.length;

// Update frame number, step count, and tracking
this.frameNumber = this.frameNumber + framesProcessed;
this.step_num += framesProcessed;
this.lastExecutedActions = lastBotActions;

// Update confirmedFrame to match - all fast-forwarded frames used real inputs
// This prevents GGPO from thinking we have many unconfirmed frames
this.confirmedFrame = this.frameNumber - 1;

// [BUG: Missing _promoteConfirmedFrames() call here]
```

### Fixed Code

```javascript
// Source: pyodide_multiplayer_game.js, lines 5023-5026 (modified)

// Update confirmedFrame to match - all fast-forwarded frames used real inputs
// This prevents GGPO from thinking we have many unconfirmed frames
this.confirmedFrame = this.frameNumber - 1;

// Promote fast-forward frames to canonical buffer (Phase 37: EDGE-01)
// Without this, data stays in speculativeFrameData and is missing from export
this._promoteConfirmedFrames();
```

### Existing `_promoteConfirmedFrames()` Implementation

```javascript
// Source: pyodide_multiplayer_game.js, lines 2966-2982

/**
 * Promote confirmed frame data from speculative to canonical buffer.
 * Only frames where frame <= confirmedFrame are promoted.
 * This ensures only data with confirmed inputs is exported.
 */
_promoteConfirmedFrames() {
    const promoted = [];
    for (const [frame, data] of this.speculativeFrameData.entries()) {
        if (frame <= this.confirmedFrame) {
            // Promote to canonical buffer
            this.frameDataBuffer.set(frame, data);
            promoted.push(frame);
        }
    }
    // Remove promoted entries from speculative buffer
    for (const frame of promoted) {
        this.speculativeFrameData.delete(frame);
    }
    if (promoted.length > 0) {
        p2pLog.debug(`Promoted ${promoted.length} frames to canonical buffer (up to frame ${this.confirmedFrame})`);
    }
}
```

### Verification Example

```javascript
// Browser console verification after fast-forward:

// Before fix:
// window.pyodideGame.speculativeFrameData.size  // Large (all fast-forward frames)
// window.pyodideGame.frameDataBuffer.size       // Small (no fast-forward frames)

// After fix:
// window.pyodideGame.speculativeFrameData.size  // 0 or small
// window.pyodideGame.frameDataBuffer.size       // Includes fast-forward frames

// Also check console for:
// "Promoted N frames to canonical buffer (up to frame M)"
// where N = number of fast-forwarded frames
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Direct `frameDataBuffer` writes | `speculativeFrameData` -> promotion | Phase 36 | Confirmation gating |
| No promotion in fast-forward | Add `_promoteConfirmedFrames()` call | Phase 37 (this phase) | Fix export gaps |

**Deprecated/outdated:**
- Fast-forward without promotion call (the current broken state)

## Open Questions

Things that couldn't be fully resolved:

1. **Partial fast-forward limit scenario**
   - What we know: Fast-forward has a `MAX_FRAMES = 1000` limit. If hit, remaining frames catch up normally.
   - What's unclear: Does promotion handle this correctly? (Yes - promotion is per-frame, so partial fast-forward works fine)
   - Recommendation: No additional work needed; existing design handles this.

2. **Fast-forward during episode boundary**
   - What we know: If episode ends while backgrounded, fast-forward processes those frames.
   - What's unclear: Does episode end logic handle this correctly?
   - Recommendation: Defer to Phase 38 (Episode Boundary Handling) which addresses this.

## Sources

### Primary (HIGH confidence)
- `pyodide_multiplayer_game.js` lines 4820-5082 - `_performFastForward()` implementation
- `pyodide_multiplayer_game.js` lines 2966-2982 - `_promoteConfirmedFrames()` implementation
- `pyodide_multiplayer_game.js` lines 5023-5025 - Direct `confirmedFrame` update in fast-forward
- `.planning/phases/36-buffer-split/36-RESEARCH.md` - Phase 36 dual-buffer architecture
- `.planning/phases/36-buffer-split/36-01-SUMMARY.md` - Phase 36 implementation details

### Secondary (HIGH confidence)
- Phase 26 decisions (from STATE.md) - Fast-forward safety limits and async handling
- Git history (commits 3527abe, 54b123c, 00f2e9d) - Phase 36 implementation

### Tertiary (N/A)
- No external sources needed; this is a codebase-specific fix using existing infrastructure

## Metadata

**Confidence breakdown:**
- Root cause identification: HIGH - Code path is clear, bug is obvious (missing promotion call)
- Fix approach: HIGH - Single-line fix using existing infrastructure
- Side effects: HIGH - No new code paths; just connecting existing components

**Research date:** 2026-01-30
**Valid until:** Until Phase 36 architecture changes (stable)

## Implementation Summary

### Files to Modify

| File | Changes |
|------|---------|
| `interactive_gym/server/static/js/pyodide_multiplayer_game.js` | Add `_promoteConfirmedFrames()` call after `confirmedFrame` update in `_performFastForward()` |

### Task Sequence

1. **Add promotion call in `_performFastForward()`** - Single line: `this._promoteConfirmedFrames()` after `this.confirmedFrame = this.frameNumber - 1`

### Exact Change Location

```
File: pyodide_multiplayer_game.js
Line: 5025 (after this.confirmedFrame = this.frameNumber - 1;)
Insert: this._promoteConfirmedFrames();
```

### Success Verification

- [ ] After fast-forward completes, `speculativeFrameData.size` is 0 (all frames promoted)
- [ ] After fast-forward completes, `frameDataBuffer` contains fast-forward frames
- [ ] Console shows "Promoted N frames to canonical buffer" where N = fast-forward frame count
- [ ] Tab refocus scenario: No frame gaps in export
- [ ] Requirement EDGE-01 satisfied

---
*Phase: 37-fast-forward-fix*
*Researched: 2026-01-30*
