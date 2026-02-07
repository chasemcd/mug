# Phase 49: Episode Boundary Row Parity - Research

**Researched:** 2026-02-02
**Domain:** JavaScript game loop, episode synchronization, dual-buffer data recording
**Confidence:** HIGH

## Summary

Phase 49 addresses the row count mismatch that occurs when one player is backgrounded at episode boundaries. The core issue is that fast-forward processing in `_performFastForward()` does not respect the `syncedTerminationFrame` boundary, causing the backgrounded player to record frames beyond `max_steps`.

The root cause is well-understood from Phase 47 testing: when Player 1 backgrounds near frame 440 (of max_steps=450), Player 2 continues to frame 450 and broadcasts episode end. Player 1's fast-forward processes all buffered inputs up to `maxFrame` without checking if those frames exceed the episode boundary, resulting in 512 rows vs 450 rows.

**Primary recommendation:** Modify `_performFastForward()` to check `syncedTerminationFrame` when building the fast-forward frame list and cap processing at the episode boundary.

## Standard Stack

This phase modifies existing code without introducing new libraries.

### Core
| File | Purpose | Modification Needed |
|------|---------|---------------------|
| `pyodide_multiplayer_game.js` | Main game loop and data recording | Modify `_performFastForward()` and `storeFrameData()` calls |

### Supporting Concepts
| Concept | Purpose | Relevance |
|---------|---------|-----------|
| `p2pEpisodeSync` | Episode coordination state | Contains `syncedTerminationFrame` |
| `speculativeFrameData` | Unconfirmed frame buffer | Fast-forward writes here |
| `frameDataBuffer` | Confirmed frame buffer | Export reads from here |

## Architecture Patterns

### Current Data Flow (Problem)

```
Player 1 backgrounds at frame 440
        |
        v
Player 2 continues: frames 440-450, detects episode end
        |
        v
Player 2 broadcasts: {frameNumber: 450}
        |
        v
Player 1 receives episode end, sets syncedTerminationFrame = 450
        |
        v
Player 1 refocuses, _performFastForward() runs
        |
        v
PROBLEM: maxFrame from buffered inputs = 512 (partner's currentFrame)
         Fast-forward processes ALL frames 440-512
        |
        v
storeFrameData() called for frames 450-511 (beyond boundary!)
        |
        v
Export includes frames 0-511 (512 rows vs 450 expected)
```

### Required Data Flow (Fix)

```
Player 1 refocuses, _performFastForward() runs
        |
        v
Check syncedTerminationFrame BEFORE building frame list
        |
        v
Cap maxFrame at min(maxFrame, syncedTerminationFrame)
        |
        v
Fast-forward processes only frames 440-449
        |
        v
Export includes frames 0-449 (450 rows - correct)
```

### Pattern: Frame Boundary Guard

The existing pattern in `_processStep()` (line 2449-2450) should be applied to fast-forward:

```javascript
// Existing pattern in _processStep():
const shouldStoreFrame = !sync.localEpisodeEndDetected &&
    (sync.syncedTerminationFrame === null || this.frameNumber < sync.syncedTerminationFrame);
```

This same guard should be applied in two places during fast-forward:
1. When building the frame list (cap maxFrame)
2. When storing per-frame data (filter post-boundary frames)

### Pattern: Export Boundary Filter

The `_emitEpisodeDataFromBuffer()` already filters by `syncedTerminationFrame` (line 3669-3674):

```javascript
const terminationFrame = this.p2pEpisodeSync?.syncedTerminationFrame;
if (terminationFrame !== null && terminationFrame !== undefined) {
    sortedFrames = sortedFrames.filter(frame => frame < terminationFrame);
}
```

This provides a safety net, but preventing extra frames from being stored is cleaner.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Episode boundary detection | Custom boundary tracking | Existing `syncedTerminationFrame` | Already computed and synced between peers |
| Frame filtering | New filtering logic | Existing patterns from `_processStep()` | Proven correct in normal execution path |

**Key insight:** The fix reuses existing episode boundary infrastructure. The issue is not missing infrastructure but missing application of that infrastructure in the fast-forward path.

## Common Pitfalls

### Pitfall 1: Checking Boundary Too Late

**What goes wrong:** Checking `syncedTerminationFrame` after storing data means frames are already in the buffer.

**Why it happens:** The existing fast-forward code stores data first, then updates frameNumber.

**How to avoid:** Check boundary BEFORE building the `fastForwardFrames` array:
```javascript
// In _performFastForward(), after computing maxFrame:
const sync = this.p2pEpisodeSync;
if (sync.syncedTerminationFrame !== null && sync.syncedTerminationFrame !== undefined) {
    maxFrame = Math.min(maxFrame, sync.syncedTerminationFrame);
}
```

**Warning signs:** Export row count exceeds max_steps; test_focus_loss_episode_boundary_parity fails with row mismatch.

### Pitfall 2: Not Handling Boundary Received During Fast-Forward

**What goes wrong:** Episode end packet arrives while fast-forward is in progress, boundary is set mid-processing.

**Why it happens:** Fast-forward is async; episode end packets are processed in parallel.

**How to avoid:** Capture `syncedTerminationFrame` at start of fast-forward and use that snapshot throughout. The `rollbackInProgress` guard already prevents most issues, but defensive coding is safer.

**Warning signs:** Inconsistent row counts under high latency.

### Pitfall 3: Off-by-One Errors

**What goes wrong:** Recording frame 450 when max_steps=450 means frames 0-450 = 451 rows.

**Why it happens:** Frame numbers are 0-indexed; max_steps=450 means frames 0-449.

**How to avoid:** Use strict less-than: `frame < syncedTerminationFrame` (not `<=`).

**Warning signs:** Row count is consistently 1 more than max_steps.

### Pitfall 4: Forgetting the storeFrameData Loop

**What goes wrong:** Capping maxFrame but not filtering the per_frame_data storage loop.

**Why it happens:** Python batch returns all frames; JavaScript iterates without checking boundary.

**How to avoid:** Either:
1. Cap maxFrame BEFORE Python batch (cleaner - fewer frames processed)
2. Add boundary check in the storeFrameData loop (defensive)

Recommendation: Do both for robustness.

## Code Examples

### Fix Location 1: Cap maxFrame at Episode Boundary

```javascript
// Source: _performFastForward() around line 4915
// AFTER: determining framesToProcess
// BEFORE: building fastForwardFrames array

// Phase 49 (BOUND-02): Cap fast-forward at episode boundary
const sync = this.p2pEpisodeSync;
if (sync.syncedTerminationFrame !== null && sync.syncedTerminationFrame !== undefined) {
    if (maxFrame > sync.syncedTerminationFrame) {
        p2pLog.debug(`Fast-forward capped at episode boundary: ${maxFrame} -> ${sync.syncedTerminationFrame}`);
        maxFrame = sync.syncedTerminationFrame;
    }
}
```

### Fix Location 2: Guard storeFrameData in Fast-Forward Loop

```javascript
// Source: _performFastForward() around line 5068-5077
// Modify the per_frame_data storage loop

// Phase 49 (BOUND-03): Skip frames at or beyond episode boundary
const terminationFrame = this.p2pEpisodeSync?.syncedTerminationFrame;
for (const frameData of ffResult.per_frame_data) {
    // Skip frames at or beyond episode boundary
    if (terminationFrame !== null && terminationFrame !== undefined) {
        if (frameData.frame >= terminationFrame) {
            p2pLog.debug(`Fast-forward: skipping post-boundary frame ${frameData.frame}`);
            continue;
        }
    }
    this.storeFrameData(frameData.frame, {
        actions: frameData.actions,
        rewards: frameData.rewards,
        terminateds: frameData.terminateds,
        truncateds: frameData.truncateds,
        infos: frameData.infos,
        isFocused: focusStateForFF
    });
}
```

### Verification: Update _promoteRemainingAtBoundary

The `_promoteRemainingAtBoundary()` method (lines 3002-3015) already promotes all speculative frames without checking boundaries. However, since we're now preventing extra frames from being stored, this should be fine. But we could add defensive filtering:

```javascript
// Source: _promoteRemainingAtBoundary() around line 3002
_promoteRemainingAtBoundary() {
    const remaining = this.speculativeFrameData.size;
    if (remaining === 0) return;

    // Phase 49 (BOUND-03): Only promote frames within episode boundary
    const terminationFrame = this.p2pEpisodeSync?.syncedTerminationFrame;

    console.warn(`[Episode Boundary] Promoting ${remaining} unconfirmed frames ` +
        `at episode end (confirmedFrame=${this.confirmedFrame}, frameNumber=${this.frameNumber})`);

    let promoted = 0;
    for (const [frame, data] of this.speculativeFrameData.entries()) {
        // Skip frames beyond episode boundary
        if (terminationFrame !== null && terminationFrame !== undefined && frame >= terminationFrame) {
            p2pLog.debug(`[Episode Boundary] Skipping post-boundary frame ${frame}`);
            continue;
        }
        this.frameDataBuffer.set(frame, { ...data, wasSpeculative: true });
        promoted++;
    }
    this.speculativeFrameData.clear();

    if (promoted > 0) {
        p2pLog.debug(`[Episode Boundary] Actually promoted ${promoted} frames`);
    }
}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| No fast-forward | Fast-forward on refocus | Phase 26 (v1.5) | Players catch up after tab switch |
| Fast-forward without boundary | Fast-forward with boundary check | Phase 49 (this phase) | Correct row counts at episode end |

**Deprecated/outdated:**
- None - this is a bug fix, not an approach change.

## Open Questions

1. **Edge case: Episode end detected DURING fast-forward**
   - What we know: `rollbackInProgress` guard prevents most concurrent operations
   - What's unclear: Can episode end packet arrive and be processed while fast-forward is running?
   - Recommendation: Capture `syncedTerminationFrame` at start of fast-forward and use snapshot

2. **Edge case: Both players backgrounded at boundary**
   - What we know: Extremely rare edge case
   - What's unclear: How sync negotiation works if both detect late
   - Recommendation: Test manually; likely works due to two-way sync

## Sources

### Primary (HIGH confidence)
- `pyodide_multiplayer_game.js` lines 4884-5150 (`_performFastForward()`)
- `pyodide_multiplayer_game.js` lines 2444-2460 (frame boundary guard in `_processStep()`)
- `pyodide_multiplayer_game.js` lines 7286-7320 (`_updateSyncedTerminationFrame()`)
- `pyodide_multiplayer_game.js` lines 3002-3016 (`_promoteRemainingAtBoundary()`)
- Phase 47 test findings (row count mismatch: 512 vs 450)

### Secondary (MEDIUM confidence)
- Phase 38 summary (episode boundary promotion rationale)
- Phase 36 summary (dual-buffer architecture)
- Phase 37 summary (fast-forward data recording fix)

## Metadata

**Confidence breakdown:**
- Fast-forward boundary fix: HIGH - clear code path, well-understood issue
- storeFrameData guard: HIGH - follows existing pattern from _processStep()
- _promoteRemainingAtBoundary update: MEDIUM - defensive; may not be strictly necessary

**Research date:** 2026-02-02
**Valid until:** 30 days (stable infrastructure, well-understood codebase)
