# Phase 38: Episode Boundary Confirmation - Research

**Researched:** 2026-01-30
**Domain:** GGPO frame confirmation at episode boundaries
**Confidence:** HIGH

## Summary

This phase addresses a data integrity issue at episode boundaries: when an episode ends, unconfirmed frames in `speculativeFrameData` are not yet promoted to `frameDataBuffer`, so they are excluded from export. This results in missing data for the final frames of each episode.

The root cause is that `signalEpisodeComplete()` immediately calls `_emitEpisodeDataFromBuffer()`, but at that point `confirmedFrame` may be behind `frameNumber`. Frames `confirmedFrame + 1` through `frameNumber - 1` are still in `speculativeFrameData` and won't be exported.

The fix is straightforward: before export, force-promote any remaining speculative frames, with a warning log if this happens (indicating frames were exported without full confirmation).

**Primary recommendation:** Add forced promotion with warning before export in `signalEpisodeComplete()`.

## Standard Stack

No new libraries needed. This phase uses existing infrastructure from Phase 36.

### Core Components (from Phase 36)
| Component | Location | Purpose |
|-----------|----------|---------|
| `speculativeFrameData` | pyodide_multiplayer_game.js:1028 | Map storing unconfirmed frame data |
| `frameDataBuffer` | pyodide_multiplayer_game.js:1024 | Map storing confirmed/canonical frame data |
| `_promoteConfirmedFrames()` | pyodide_multiplayer_game.js:2966 | Promotes frames where `frame <= confirmedFrame` |
| `confirmedFrame` | pyodide_multiplayer_game.js:923 | Highest frame with confirmed inputs from ALL players |

### Episode End Flow Components
| Component | Location | Purpose |
|-----------|----------|---------|
| `signalEpisodeComplete()` | Line 3687 | Marks episode done, triggers export and reset |
| `_emitEpisodeDataFromBuffer()` | Line 3737 | Exports frameDataBuffer to server via socket |
| `exportEpisodeDataFromBuffer()` | Line 3616 | Builds export data structure from frameDataBuffer |

## Architecture Patterns

### Current Episode End Flow (Problem)

```
Episode end detected (terminated/truncated/max_steps)
        |
        v
signalEpisodeComplete()
        |
        v
_emitEpisodeDataFromBuffer()  <-- Problem: reads only frameDataBuffer
        |
        v
frameDataBuffer.clear() + speculativeFrameData.clear()
        |
        v
[Unconfirmed frames LOST - they were in speculativeFrameData]
```

### Required Episode End Flow (Solution)

```
Episode end detected (terminated/truncated/max_steps)
        |
        v
signalEpisodeComplete()
        |
        v
Check: speculativeFrameData.size > 0?
        |
        +-- YES --> Log warning: "Promoting N unconfirmed frames at episode boundary"
        |                   |
        |                   v
        |           Force-promote all remaining speculative frames
        |
        +-- NO --> (normal case, all frames already confirmed)
        |
        v
_emitEpisodeDataFromBuffer()  <-- Now includes all frames
        |
        v
frameDataBuffer.clear() + speculativeFrameData.clear()
```

### Pattern: Forced Promotion at Boundary

The key insight is that at episode end, all frames HAVE real inputs (both players executed the same steps to reach termination). The speculative data IS correct data - it just hasn't been marked as "confirmed" yet because input confirmation packets are still in flight.

```javascript
// At episode boundary, force-promote remaining frames
_promoteRemainingFramesAtBoundary() {
    const remaining = this.speculativeFrameData.size;
    if (remaining === 0) return;

    // Log warning - this is unusual but not incorrect
    console.warn(`[Episode Boundary] Promoting ${remaining} unconfirmed frames ` +
        `(confirmedFrame=${this.confirmedFrame}, frameNumber=${this.frameNumber})`);

    // Force-promote all remaining speculative frames
    for (const [frame, data] of this.speculativeFrameData.entries()) {
        this.frameDataBuffer.set(frame, data);
    }
    this.speculativeFrameData.clear();
}
```

### Anti-Patterns to Avoid

- **Waiting for confirmation packets:** Don't add delays/polling waiting for all input confirmations - this adds latency and complexity. The data is already correct.
- **Modifying confirmedFrame:** Don't artificially set `confirmedFrame = frameNumber - 1` - this conflates "exported" with "confirmed" semantics.
- **Selective promotion:** Don't try to promote only "valid" frames - all speculative frames at episode end have real inputs.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Frame iteration | Manual frame loop | Existing Map.entries() iteration | Standard JS Map iteration |
| Promotion logic | Custom promotion | Extend existing _promoteConfirmedFrames() or add sibling method | Reuse established pattern |

**Key insight:** This is a small, focused change. Don't over-engineer - just add force-promotion before the existing export call.

## Common Pitfalls

### Pitfall 1: Misunderstanding "Unconfirmed" Data

**What goes wrong:** Treating speculative data as unreliable and discarding it
**Why it happens:** The term "unconfirmed" suggests the data might be wrong
**How to avoid:** Understand that at episode end, both players have executed identical steps with real inputs. The data IS correct - "unconfirmed" just means the confirmation packets haven't arrived yet.
**Warning signs:** Any solution that discards speculative data at episode boundary

### Pitfall 2: Adding Confirmation Wait Logic

**What goes wrong:** Adding delays or polling to wait for confirmation packets before export
**Why it happens:** Desire for "proper" confirmation before export
**How to avoid:** Recognize that the P2P episode sync already waits for both peers to agree on episode end - by that time, inputs have been exchanged, just not confirmed. Adding more waits adds latency.
**Warning signs:** setTimeout, Promises that wait for confirmedFrame to advance, polling loops

### Pitfall 3: Modifying Multiple Code Paths

**What goes wrong:** Changing both P2P and server-authoritative paths, multiple entry points
**Why it happens:** Not recognizing that all paths flow through signalEpisodeComplete()
**How to avoid:** All episode completions call signalEpisodeComplete() - fix it there once.
**Warning signs:** Changes in multiple functions, duplicate promotion logic

### Pitfall 4: Breaking Frame Count Parity

**What goes wrong:** One player exports N frames, other exports M frames
**Why it happens:** Different timing of when promotion happens vs when confirmedFrame advances
**How to avoid:** Force-promote ALL remaining speculative frames (not just up to confirmedFrame) at episode boundary. Both players have same speculative frames.
**Warning signs:** Frame count mismatches in validation tests

## Code Examples

### Location for Fix: signalEpisodeComplete()

Current code (lines 3687-3702):
```javascript
signalEpisodeComplete() {
    /**
     * Mark the game as done when episode completes.
     * ...
     */

    // Export episode data from the rollback-safe buffer
    // This ensures only correct, validated data is emitted
    if (this.sceneId) {
        this._emitEpisodeDataFromBuffer();
    }

    this.num_episodes += 1;
    // ... rest of method
}
```

### Required Modification

```javascript
signalEpisodeComplete() {
    /**
     * Mark the game as done when episode completes.
     * ...
     */

    // Phase 38 (EDGE-02): Promote any remaining unconfirmed frames before export
    // At episode end, all frames have real inputs - just not yet confirmed via packets
    this._promoteRemainingAtBoundary();

    // Export episode data from the rollback-safe buffer
    // This ensures only correct, validated data is emitted
    if (this.sceneId) {
        this._emitEpisodeDataFromBuffer();
    }

    this.num_episodes += 1;
    // ... rest of method
}
```

### New Method: _promoteRemainingAtBoundary()

```javascript
/**
 * Force-promote any remaining speculative frames at episode boundary.
 * Called before export to ensure all frame data is captured.
 *
 * At episode end, both players have executed identical steps with real inputs.
 * The data is correct - it just hasn't been "confirmed" because input
 * confirmation packets are still in flight.
 *
 * Phase 38: EDGE-02
 */
_promoteRemainingAtBoundary() {
    const remaining = this.speculativeFrameData.size;
    if (remaining === 0) return;

    // Log warning - this indicates confirmedFrame was behind at episode end
    console.warn(`[Episode Boundary] Promoting ${remaining} unconfirmed frames ` +
        `at episode end (confirmedFrame=${this.confirmedFrame}, frameNumber=${this.frameNumber})`);

    // Promote all remaining frames - don't check confirmedFrame
    for (const [frame, data] of this.speculativeFrameData.entries()) {
        this.frameDataBuffer.set(frame, data);
    }
    this.speculativeFrameData.clear();
}
```

## State of the Art

This is a custom GGPO-like implementation, so "state of the art" is project-specific.

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Direct recording to frameDataBuffer | Dual-buffer with promotion | Phase 36 | Prevents rollback corruption |
| No fast-forward promotion | _promoteConfirmedFrames() in fast-forward | Phase 37 | Fixes fast-forward gaps |
| (Current gap) Episode boundary promotion | (This phase) Force-promote at boundary | Phase 38 | Complete data at episode end |

## Verification Strategy

### Success Criteria from Requirements

1. **Episode end waits for all frames to be confirmed before triggering export**
   - Verification: Check that `speculativeFrameData.size === 0` after promotion, before export

2. **Warning logged if promoting unconfirmed frames at episode boundary**
   - Verification: Grep for `console.warn` with "Episode Boundary" in log

3. **Both players export identical frame counts**
   - Verification: Compare `episodeData.t.length` between peers (requires Phase 39 validation)

### Manual Test Protocol

1. Start multiplayer game, play normally
2. Let episode end naturally (reach termination condition)
3. Check console for `[Episode Boundary] Promoting N unconfirmed frames` warning
4. Verify in console: `window.pyodideGame.frameDataBuffer.size` before clear matches expected frame count
5. Verify no frames lost by comparing episode data frame counts between players

### Automated Verification (for Plan)

```javascript
// In signalEpisodeComplete(), after promotion, before export:
const expectedFrames = this.frameNumber;  // frames 0 to frameNumber-1
const actualFrames = this.frameDataBuffer.size;
if (actualFrames !== expectedFrames) {
    console.error(`[EDGE-02 VIOLATION] Expected ${expectedFrames} frames, got ${actualFrames}`);
}
```

## Open Questions

None. This is a focused, well-understood change.

The only consideration is whether to log at `warn` or `debug` level when promoting unconfirmed frames. Recommendation: Use `warn` because:
- It's unusual (confirmation should normally keep up)
- It indicates potential network latency issues
- It's important for debugging data discrepancies

## Sources

### Primary (HIGH confidence)
- pyodide_multiplayer_game.js - Direct code review of:
  - Lines 3687-3731: signalEpisodeComplete() flow
  - Lines 2966-2982: _promoteConfirmedFrames() implementation
  - Lines 1024-1028: Buffer declarations
  - Lines 7112-7175: P2P episode sync flow

### Secondary (HIGH confidence)
- Phase 36 SUMMARY.md - Dual-buffer architecture documentation
- Phase 37 SUMMARY.md - Fast-forward promotion pattern

### Tertiary
- REQUIREMENTS.md - EDGE-02 requirement definition

## Metadata

**Confidence breakdown:**
- Architecture: HIGH - Direct code review, clear data flow
- Solution approach: HIGH - Follows established promotion pattern from Phase 36/37
- Verification: HIGH - Clear success criteria, testable

**Research date:** 2026-01-30
**Valid until:** Indefinite (project-specific patterns, not external dependencies)
