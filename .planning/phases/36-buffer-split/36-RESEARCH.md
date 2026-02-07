# Phase 36: Speculative/Canonical Buffer Split - Research

**Researched:** 2026-01-30
**Domain:** GGPO-style data recording architecture for rollback netcode
**Confidence:** HIGH

## Summary

Phase 36 introduces the core architectural change that enables data export parity: separating **speculative** frame data (recorded during step execution with potentially predicted inputs) from **canonical** frame data (promoted only after all inputs are confirmed). This is the foundational pattern that Phases 37-39 build upon.

The existing codebase already has all the necessary infrastructure:
- `confirmedFrame` tracking in `_updateConfirmedFrame()`
- `_hasAllInputsForFrame()` for checking input confirmation
- `frameDataBuffer` for storing per-frame data
- `clearFrameDataFromRollback()` for clearing speculative data on rollback

The gap is that `storeFrameData()` writes directly to `frameDataBuffer` during step execution, before confirmation. The fix adds a `speculativeFrameData` buffer and promotes data to `frameDataBuffer` only when `confirmedFrame` advances.

**Primary recommendation:** Add `speculativeFrameData` Map, modify `storeFrameData()` to write there, add `_promoteConfirmedFrames()` method called from `_updateConfirmedFrame()`.

## Standard Stack

The established libraries/tools for this domain:

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Native JavaScript Map | ES6+ | Frame-indexed data storage | Already used for `frameDataBuffer`, `inputBuffer`, `stateSnapshots` |
| Existing GGPO infrastructure | N/A | Frame confirmation, rollback | Complete implementation in codebase |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `_updateConfirmedFrame()` | N/A | Frame confirmation detection | Called after input processing |
| `clearFrameDataFromRollback()` | N/A | Speculative data invalidation | Called at rollback start |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Dual buffer (speculative + canonical) | Single buffer with confirmation flag | More complex, same effect |
| Promotion in `_updateConfirmedFrame()` | Promotion at export time | Export-time is less efficient, harder to test |

**Installation:**
No external dependencies required. This is a pure JavaScript refactoring of existing patterns.

## Architecture Patterns

### Recommended Data Flow

```
step() execution with predicted inputs
            |
            v
speculativeFrameData[N] = {actions, rewards, ...}
            |
    [frame continues...]
            |
            v
_updateConfirmedFrame() detects confirmedFrame >= N
            |
            v
_promoteConfirmedFrames():
  frameDataBuffer[N] = speculativeFrameData[N]
  delete speculativeFrameData[N]
            |
    [episode ends...]
            |
            v
exportEpisodeDataFromBuffer()
  reads only from frameDataBuffer (canonical only)
```

### Pattern 1: Speculative-Then-Promote

**What:** Store data speculatively during step(), promote to canonical buffer when confirmed.

**When to use:** Normal gameplay frame execution.

**Example:**
```javascript
// In step():
// Source: existing storeFrameData() pattern, modified
this.speculativeFrameData.set(this.frameNumber, {
    actions: finalActions,
    rewards: Object.fromEntries(rewards),
    terminateds: Object.fromEntries(terminateds),
    truncateds: Object.fromEntries(truncateds),
    infos: infos instanceof Map ? Object.fromEntries(infos) : infos,
    isFocused: this.focusManager ? !this.focusManager.isBackgrounded : true,
    timestamp: Date.now()
});

// In _updateConfirmedFrame():
// After confirmedFrame advances, promote frames
this._promoteConfirmedFrames();
```

### Pattern 2: Rollback Clearing

**What:** On rollback, clear invalidated speculative data. Replay will re-store correct data.

**When to use:** When rollback is triggered by late input mismatch.

**Example:**
```javascript
// Source: existing clearFrameDataFromRollback(), extended
clearFrameDataFromRollback(targetFrame) {
    // Clear canonical buffer (existing behavior - safety valve)
    for (const frame of this.frameDataBuffer.keys()) {
        if (frame >= targetFrame) {
            this.frameDataBuffer.delete(frame);
        }
    }
    // Clear speculative buffer (new)
    for (const frame of this.speculativeFrameData.keys()) {
        if (frame >= targetFrame) {
            this.speculativeFrameData.delete(frame);
        }
    }
}
```

### Pattern 3: Buffer Pruning

**What:** Remove old entries from speculative buffer to prevent memory growth.

**When to use:** After promotion, to clean up promoted entries.

**Example:**
```javascript
// In _promoteConfirmedFrames():
_promoteConfirmedFrames() {
    for (const [frame, data] of this.speculativeFrameData.entries()) {
        if (frame <= this.confirmedFrame) {
            // Promote to canonical
            this.frameDataBuffer.set(frame, data);
            // Remove from speculative
            this.speculativeFrameData.delete(frame);
        }
    }
}
```

### Anti-Patterns to Avoid

- **Writing directly to frameDataBuffer during step():** This conflates speculative and confirmed data. Always write to speculative first.
- **Promoting all speculative data at episode end without logging:** If there's unconfirmed data at episode end, log a warning (indicates sync issue).
- **Deleting speculative data before promotion:** Ensure promotion happens before cleanup.

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Frame confirmation detection | Custom tracking | `_hasAllInputsForFrame()` | Already handles multi-player input checking |
| Confirmed frame tracking | Manual counter | `this.confirmedFrame` | Already maintained by `_updateConfirmedFrame()` |
| Speculative data invalidation | Custom rollback handler | Extend `clearFrameDataFromRollback()` | Rollback already calls this |
| Data export | New export method | `exportEpisodeDataFromBuffer()` | Already reads from frameDataBuffer |

**Key insight:** The codebase already has frame confirmation infrastructure (Phase 11-14). Phase 36 extends it to gate data recording.

## Common Pitfalls

### Pitfall 1: Missing Promotion Call

**What goes wrong:** Data never moves from speculative to canonical buffer.
**Why it happens:** `_promoteConfirmedFrames()` not called or called before confirmation advances.
**How to avoid:** Call `_promoteConfirmedFrames()` at the end of `_updateConfirmedFrame()`, after `this.confirmedFrame` is updated.
**Warning signs:** `frameDataBuffer` empty or much smaller than expected at export time.

### Pitfall 2: Double-Storing on Rollback Replay

**What goes wrong:** Frame data stored twice (once in original step, once in replay).
**Why it happens:** Rollback replay calls `storeFrameData()` but original speculative data wasn't cleared.
**How to avoid:** `clearFrameDataFromRollback()` must clear speculative buffer before replay. Existing code already calls this.
**Warning signs:** Duplicate frame numbers in buffer, or data from wrong execution.

### Pitfall 3: Promotion of Incorrect Data

**What goes wrong:** Promoted data has predicted (wrong) inputs instead of confirmed inputs.
**Why it happens:** Promotion happens before rollback correction, or speculative data not updated after replay.
**How to avoid:** Promotion only happens when `frame <= confirmedFrame`, which means all inputs are received. Rollback replay re-stores corrected data, overwriting speculative entry before promotion.
**Warning signs:** Exported actions don't match `actionSequence` or peer exports differ.

### Pitfall 4: Memory Growth from Unconfirmed Frames

**What goes wrong:** Speculative buffer grows unbounded under high latency.
**Why it happens:** Frames advance but confirmedFrame lags; speculative entries accumulate.
**How to avoid:** Add pruning for very old speculative entries (e.g., older than maxSnapshots window). Log warning if pruning unconfirmed data.
**Warning signs:** speculativeFrameData.size >> 100 (more than ~10 seconds of data at 10 FPS).

## Code Examples

Verified patterns from existing codebase:

### Data Structure Initialization

```javascript
// Source: constructor in PyodideMultiplayerGame
// Location: pyodide_multiplayer_game.js, around line 1024

// EXISTING: Canonical buffer (will now hold only confirmed data)
this.frameDataBuffer = new Map();

// NEW: Speculative buffer for unconfirmed frames
this.speculativeFrameData = new Map();
```

### Modified storeFrameData()

```javascript
// Source: existing storeFrameData(), modified to target speculative buffer
// Location: pyodide_multiplayer_game.js, around line 3547

/**
 * Store frame data in the speculative buffer.
 * Data will be promoted to canonical buffer when confirmedFrame advances.
 * On rollback, speculative data is cleared and re-stored during replay.
 */
storeFrameData(frameNumber, data) {
    this.speculativeFrameData.set(frameNumber, {
        actions: data.actions,
        rewards: data.rewards,
        terminateds: data.terminateds,
        truncateds: data.truncateds,
        infos: data.infos,
        isFocused: data.isFocused,
        timestamp: Date.now()
    });
}
```

### Promotion Method

```javascript
// NEW: Promote confirmed frames from speculative to canonical buffer
// Should be called at the end of _updateConfirmedFrame()

/**
 * Promote confirmed frame data from speculative to canonical buffer.
 * Only frames where confirmedFrame >= frame are promoted.
 * This ensures only data with confirmed inputs is exported.
 */
_promoteConfirmedFrames() {
    const promoted = [];
    for (const [frame, data] of this.speculativeFrameData.entries()) {
        if (frame <= this.confirmedFrame) {
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

### Integration Point in _updateConfirmedFrame()

```javascript
// Source: existing _updateConfirmedFrame(), extended
// Location: pyodide_multiplayer_game.js, around line 2918

async _updateConfirmedFrame() {
    const humanPlayerIds = this._getHumanPlayerIds();
    if (humanPlayerIds.length === 0) return;

    let startFrame = this.confirmedFrame + 1;

    // ... existing logic for finding highest confirmed frame ...

    for (let frame = startFrame; frame < this.frameNumber; frame++) {
        if (this._hasAllInputsForFrame(frame, humanPlayerIds)) {
            this.confirmedFrame = frame;
            this.predictedFrames.delete(frame);
            await this._computeAndStoreConfirmedHash(frame);
        } else {
            break;
        }
    }

    // NEW: Promote confirmed frames to canonical buffer
    this._promoteConfirmedFrames();
}
```

### Modified clearFrameDataFromRollback()

```javascript
// Source: existing clearFrameDataFromRollback(), extended
// Location: pyodide_multiplayer_game.js, around line 3563

/**
 * Clear frame data buffer entries from rollback target onwards.
 * Clears both speculative and canonical buffers to ensure
 * replayed frames are stored with correct data.
 */
clearFrameDataFromRollback(targetFrame) {
    // Clear canonical buffer (existing - safety valve)
    for (const frame of this.frameDataBuffer.keys()) {
        if (frame >= targetFrame) {
            this.frameDataBuffer.delete(frame);
        }
    }
    // Clear speculative buffer (new)
    for (const frame of this.speculativeFrameData.keys()) {
        if (frame >= targetFrame) {
            this.speculativeFrameData.delete(frame);
        }
    }
    p2pLog.debug(`Cleared frame data buffers from frame ${targetFrame} onwards`);
}
```

### Episode Reset Cleanup

```javascript
// Source: existing clearGGPOState() or similar reset method
// Location: pyodide_multiplayer_game.js, episode reset section

// On new episode, clear both buffers
clearEpisodeData() {
    this.frameDataBuffer.clear();
    this.speculativeFrameData.clear();
}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Store data directly during step() | Store speculatively, promote on confirmation | This phase | Guarantees parity |
| Single buffer with rollback correction | Dual buffer with promotion gate | This phase | Cleaner separation |

**Deprecated/outdated:**
- Direct writes to `frameDataBuffer` in `step()` — now writes to speculative buffer
- No confirmation gating — now gated by `confirmedFrame`

## Open Questions

Things that couldn't be fully resolved:

1. **Maximum speculative buffer size**
   - What we know: Under normal network conditions, speculative buffer should have < 20 entries (2 seconds at 10 FPS)
   - What's unclear: Should we add explicit size limit or let it grow?
   - Recommendation: Add warning log if size exceeds 50 entries, but don't hard limit (data loss worse than memory)

2. **Handling very late confirmations**
   - What we know: If confirmedFrame lags significantly, speculative buffer grows
   - What's unclear: At what point should we treat unconfirmed frames as "lost"?
   - Recommendation: For Phase 36, just promote what we have at episode end with warning. Phase 38 will add episode boundary handling.

## Sources

### Primary (HIGH confidence)
- `pyodide_multiplayer_game.js` — existing GGPO implementation, frame confirmation tracking
- `.planning/research/ARCHITECTURE.md` — detailed two-buffer architecture design
- `.planning/research/SUMMARY.md` — v1.8 research executive summary
- `.planning/research/STACK.md` — canonical state patterns

### Secondary (HIGH confidence)
- [GGPO Developer Guide](https://github.com/pond3r/ggpo/blob/master/doc/DeveloperGuide.md) — confirmed frame concepts
- [NetplayJS](https://github.com/rameshvarun/netplayjs) — `isPrediction` flag pattern

### Tertiary (MEDIUM confidence)
- [SnapNet: Rollback Netcode](https://www.snapnet.dev/blog/netcode-architectures-part-2-rollback/) — confirmed vs speculative frame distinction

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — uses existing JavaScript Map patterns
- Architecture: HIGH — well-documented dual-buffer pattern from GGPO/NetplayJS
- Pitfalls: HIGH — derived from codebase analysis of existing rollback flow

**Research date:** 2026-01-30
**Valid until:** 60 days (stable pattern, unlikely to change)

## Implementation Summary

### Files to Modify

| File | Changes |
|------|---------|
| `pyodide_multiplayer_game.js` | Add `speculativeFrameData`, modify `storeFrameData()`, add `_promoteConfirmedFrames()`, extend `clearFrameDataFromRollback()`, update episode reset |

### Task Sequence

1. **Add speculativeFrameData buffer** — Initialize in constructor alongside `frameDataBuffer`
2. **Modify storeFrameData()** — Write to `speculativeFrameData` instead of `frameDataBuffer`
3. **Add _promoteConfirmedFrames()** — New method to move confirmed data to canonical buffer
4. **Integrate promotion in _updateConfirmedFrame()** — Call after confirmedFrame advances
5. **Extend clearFrameDataFromRollback()** — Clear both buffers on rollback
6. **Update episode reset** — Clear both buffers on new episode

### Success Verification

- [ ] After normal frame execution, data is in `speculativeFrameData` (not `frameDataBuffer`)
- [ ] After `_updateConfirmedFrame()` advances `confirmedFrame`, data is in `frameDataBuffer`
- [ ] After rollback, both buffers are cleared for frames >= target
- [ ] After replay, data is re-stored in speculative buffer
- [ ] At episode export, `frameDataBuffer` contains only confirmed-frame data
- [ ] Console logs show promotion activity: "Promoted N frames to canonical buffer"

---
*Phase: 36-buffer-split*
*Completed: 2026-01-30*
