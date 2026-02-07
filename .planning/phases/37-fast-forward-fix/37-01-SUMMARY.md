---
phase: 37-fast-forward-fix
plan: 01
status: complete
subsystem: fast-forward-data-recording
tags: [ggpo, data-export, fast-forward, dual-buffer, canonical]

dependency-graph:
  requires:
    - 36-buffer-split (speculativeFrameData and _promoteConfirmedFrames() infrastructure)
    - 26-resync-partner-ux (_performFastForward() implementation)
  provides:
    - EDGE-01: Fast-forward frames promoted to canonical buffer
  affects:
    - 38-episode-boundary (fast-forward at episode end now exports correctly)
    - 39-export-validation (no more fast-forward frame gaps)

tech-stack:
  added: []
  patterns:
    - Post-confirmation promotion pattern (same as _updateConfirmedFrame())

key-files:
  created: []
  modified:
    - interactive_gym/server/static/js/pyodide_multiplayer_game.js

decisions:
  - key: promotion-location
    choice: "Call _promoteConfirmedFrames() immediately after confirmedFrame update"
    why: "Fast-forward already knows all frames are confirmed (used real inputs), just needs promotion"
  - key: avoid-updateConfirmedFrame
    choice: "Direct promotion call instead of _updateConfirmedFrame()"
    why: "_updateConfirmedFrame() would re-scan input buffer unnecessarily; fast-forward already confirmed all frames"

metrics:
  duration: <1m
  completed: 2026-01-31
---

# Phase 37 Plan 01: Fast-Forward Data Recording Fix Summary

Fast-forward frames now promoted to canonical buffer via _promoteConfirmedFrames() call after confirmedFrame update

## What Was Done

### Task 1: Add _promoteConfirmedFrames() call after confirmedFrame update in _performFastForward()
**Commit:** 8a82825

Added `this._promoteConfirmedFrames()` call in `_performFastForward()` immediately after the line that updates `confirmedFrame`. This ensures fast-forward frames stored in `speculativeFrameData` are promoted to `frameDataBuffer` for export.

**Key changes:**
- Added call at line 5029: `this._promoteConfirmedFrames();`
- Comment explains Phase 37 / EDGE-01 purpose
- Fast-forward now follows same promotion path as normal execution

**Code change:**
```javascript
// Update confirmedFrame to match - all fast-forwarded frames used real inputs
// This prevents GGPO from thinking we have many unconfirmed frames
this.confirmedFrame = this.frameNumber - 1;

// Promote fast-forward frames to canonical buffer (Phase 37: EDGE-01)
// Without this, data stays in speculativeFrameData and is missing from export
this._promoteConfirmedFrames();

// Update HUD to reflect fast-forwarded state
```

## Data Flow Summary (Fixed)

```
Tab refocus triggers _performFastForward()
        |
        v
For each frame: batch step() via Python
        |
        v
storeFrameData() -> speculativeFrameData[N] = {...}
        |
        v
this.confirmedFrame = this.frameNumber - 1
        |
        v
this._promoteConfirmedFrames()  <-- NEW: Phase 37 fix
        |
        v
frameDataBuffer contains all fast-forward frames
        |
        v
Episode ends, exportEpisodeDataFromBuffer() reads frameDataBuffer
        |
        v
COMPLETE DATA (no gaps from fast-forward)
```

## Deviations from Plan

None - plan executed exactly as written.

## Requirements Satisfied

- **EDGE-01:** Fast-forward uses same confirmation-gated recording path as normal execution

## Verification

Grep confirms three occurrences of `_promoteConfirmedFrames`:
1. Line 2958: Called in `_updateConfirmedFrame()` (Phase 36)
2. Line 2966: Method definition (Phase 36)
3. Line 5029: Called in `_performFastForward()` (Phase 37 - this fix)

## Runtime Verification (Manual)

To verify fix works:
1. Start multiplayer game
2. Tab away, wait for fast-forward frames to accumulate
3. Tab back, observe console for "Promoted N frames to canonical buffer"
4. Check `window.pyodideGame.speculativeFrameData.size` is 0 after fast-forward
5. Check `window.pyodideGame.frameDataBuffer.size` includes fast-forward frames
6. Complete episode, verify export contains all frames (no gaps)

## Next Phase Readiness

Phase 38 (Episode Boundary Handling) can proceed. Fast-forward frames are now properly promoted, but edge cases around episode boundaries during fast-forward still need handling.

---
*Completed: 2026-01-31*
