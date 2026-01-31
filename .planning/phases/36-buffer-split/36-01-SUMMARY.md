---
phase: 36-buffer-split
plan: 01
status: complete
subsystem: rollback-data-collection
tags: [ggpo, data-export, dual-buffer, speculative, canonical]

dependency-graph:
  requires:
    - 11-hash-infrastructure (frame confirmation tracking)
    - 14-validation-export (frameDataBuffer and export methods)
  provides:
    - REC-01: speculativeFrameData buffer for unconfirmed data
    - REC-02: _promoteConfirmedFrames() for data promotion
    - REC-03: Dual-buffer clearing on rollback and episode reset
  affects:
    - 37-fast-forward-logging (will need to handle speculative data)
    - 38-episode-boundary (will flush speculative data at episode end)
    - 39-export-validation (will validate canonical-only export)

tech-stack:
  added: []
  patterns:
    - Dual-buffer architecture (speculative + canonical)
    - Promotion gate pattern (confirm before promote)
    - Frame-indexed Map storage

key-files:
  created: []
  modified:
    - interactive_gym/server/static/js/pyodide_multiplayer_game.js

decisions:
  - key: speculative-buffer-storage
    choice: "Use separate speculativeFrameData Map"
    why: "Clear separation between unconfirmed and confirmed data"
  - key: promotion-trigger
    choice: "Call _promoteConfirmedFrames() at end of _updateConfirmedFrame()"
    why: "Promotes data only after confirmedFrame advances"
  - key: rollback-clearing
    choice: "Clear both buffers in clearFrameDataFromRollback()"
    why: "Ensures replayed frames store correct data without residual speculative data"

metrics:
  duration: 4m
  completed: 2026-01-30
---

# Phase 36 Plan 01: Speculative/Canonical Buffer Split Summary

Dual-buffer data recording: step() writes to speculativeFrameData, _promoteConfirmedFrames() moves confirmed data to frameDataBuffer for export

## What Was Done

### Task 1: Add speculativeFrameData buffer and modify storeFrameData()
**Commit:** 3527abe

Added `speculativeFrameData` Map in constructor alongside `frameDataBuffer`. Modified `storeFrameData()` to write to the speculative buffer instead of the canonical buffer. This ensures that during step() execution (which may use predicted inputs), data is stored tentatively until inputs are confirmed.

**Key changes:**
- Constructor: `this.speculativeFrameData = new Map();`
- storeFrameData(): `this.speculativeFrameData.set(frameNumber, {...})` instead of `this.frameDataBuffer.set()`

### Task 2: Add _promoteConfirmedFrames() and integrate into _updateConfirmedFrame()
**Commit:** 54b123c

Added `_promoteConfirmedFrames()` method that iterates through speculative buffer and promotes frames where `frame <= confirmedFrame` to the canonical `frameDataBuffer`. Method is called at the end of `_updateConfirmedFrame()` after `confirmedFrame` advances, ensuring promotion happens with the updated confirmation boundary.

**Key changes:**
- New method `_promoteConfirmedFrames()` with promotion logic
- Promotion removes entries from speculative buffer after moving to canonical
- Debug logging: "Promoted N frames to canonical buffer (up to frame M)"

### Task 3: Extend clearFrameDataFromRollback() and episode reset to clear both buffers
**Commit:** 00f2e9d

Extended `clearFrameDataFromRollback()` to clear both canonical and speculative buffers for frames >= targetFrame. Updated episode reset and post-emit cleanup to clear both buffers.

**Key changes:**
- `clearFrameDataFromRollback()`: Clears both `frameDataBuffer` and `speculativeFrameData`
- Episode reset: `this.speculativeFrameData.clear()` added after `this.frameDataBuffer.clear()`
- Post-emit: Same dual clearing after `emitEpisodeData()`

## Data Flow Summary

```
step() with predicted inputs
        |
        v
speculativeFrameData[N] = {actions, rewards, ...}
        |
[input packet arrives]
        |
        v
_updateConfirmedFrame() advances confirmedFrame
        |
        v
_promoteConfirmedFrames():
  frameDataBuffer[N] = speculativeFrameData[N]
  delete speculativeFrameData[N]
        |
[episode ends]
        |
        v
exportEpisodeDataFromBuffer() reads only frameDataBuffer
```

## Deviations from Plan

None - plan executed exactly as written.

## Requirements Satisfied

- **REC-01:** Step execution data stored in speculative buffer
- **REC-02:** Promotion happens only when inputs confirmed
- **REC-03:** Export reads only canonical buffer

## Console Logging

The following debug logs are now available:
- `Promoted N frames to canonical buffer (up to frame M)` - when frames are promoted
- `Cleared frame data buffers from frame X onwards` - on rollback

## Next Phase Readiness

Phase 37 (Fast-Forward Logging) can proceed. The speculative buffer infrastructure is in place for:
- Handling fast-forward replay (frames will be re-stored in speculative buffer)
- Ensuring fast-forward frames follow the same promotion path

---
*Completed: 2026-01-30*
