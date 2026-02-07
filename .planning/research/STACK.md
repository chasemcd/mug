# Stack Research: Rollback Netcode Data Consistency

**Domain:** GGPO-style rollback netcode data consistency for P2P multiplayer
**Researched:** 2026-01-30
**Confidence:** HIGH (verified against GGPO documentation, NetplayJS, and existing codebase)

## Executive Summary

The core problem is ensuring both players export **identical** game data (actions, observations, rewards, infos) when using rollback netcode. The existing codebase already implements the correct pattern but has a gap: the `frameDataBuffer` can contain data from **predicted frames that are later invalidated by rollback**.

**Key insight from GGPO implementations:** Data should only be recorded/exported for **confirmed frames** where all players' inputs have been received and validated. The codebase tracks `confirmedFrame` but the data export mechanism doesn't strictly enforce this boundary.

## Recommended Patterns for Canonical State

### Core Concepts

| Concept | Definition | Codebase Implementation |
|---------|------------|------------------------|
| **Confirmed Frame** | A frame where ALL players' inputs have been received and validated | `this.confirmedFrame` tracks the highest consecutive frame with all inputs |
| **Speculative Frame** | A frame simulated using predicted inputs (may be wrong) | Frames > `confirmedFrame` that use `getPredictedAction()` |
| **Rollback Window** | Frames between `confirmedFrame` and `this.frameNumber` | Dynamic; typically 0-15 frames depending on latency |
| **Input Delay** | Intentional delay before inputs are applied to reduce rollback frequency | Not currently implemented; could reduce rollback frequency |
| **Canonical State** | The authoritative state at a confirmed frame | State snapshots at frames <= `confirmedFrame` |

### Data Structures

| Structure | Purpose | Implementation Notes |
|-----------|---------|---------------------|
| **Confirmed Frame Index** | Tracks highest frame where all inputs received | Already exists: `this.confirmedFrame`. Updated via `updateConfirmedFrame()` |
| **Input Buffer (per player)** | Stores received inputs indexed by frame | Already exists: `this.inputBuffer` as `Map<frameNumber, Map<playerId, input>>` |
| **State Snapshot Ring Buffer** | Enables rollback to any recent frame | Already exists: `this.stateSnapshots` with configurable interval |
| **Frame Data Buffer** | Stores per-frame data (actions, rewards, obs) | Already exists: `this.frameDataBuffer`. **Gap: not strictly bounded by confirmedFrame** |
| **Confirmed Hash History** | SHA-256 hashes of confirmed frames for desync detection | Already exists: `this.confirmedHashHistory` |

### Current Codebase Analysis

The existing implementation in `pyodide_multiplayer_game.js` has:

**Correctly Implemented:**
- Input buffering with frame indexing
- Rollback detection via `misprediction` check in `processP2PInput()`
- State snapshots with save/load for rollback
- Confirmed frame tracking
- Confirmed hash computation and exchange
- Rollback replay that clears and rebuilds `frameDataBuffer`

**Gap Identified (DATA-PARITY issue):**
```javascript
// Current: storeFrameData() is called in step() BEFORE confirmedFrame is updated
// This means speculative frames are stored before confirmation
this.storeFrameData(this.frameNumber, frameData);

// The rollback DOES clear this via clearFrameDataFromRollback()
// BUT: if no rollback happens (prediction was correct), the data
// was recorded at the time of prediction, not confirmation
```

**The actual issue:** When both players' predictions are correct (common case), neither player rolls back. But if they recorded data at slightly different frames due to network timing, they could have different data. The data should only be finalized when `confirmedFrame` advances past that frame.

## Data Collection Strategy

### When to Record Data (Correct Approach)

**Pattern 1: Deferred Recording (Recommended)**

Only export data for frames that have been confirmed. This is the fighting game standard.

```javascript
// In exportEpisodeData() or equivalent
exportCanonicalData() {
    const exportData = [];
    for (const [frame, data] of this.frameDataBuffer.entries()) {
        // Only export frames that are fully confirmed
        if (frame <= this.confirmedFrame) {
            exportData.push(data);
        }
    }
    return exportData;
}
```

**Pattern 2: Dual Buffer (Alternative)**

Maintain separate buffers for speculative and confirmed data:

```javascript
class CanonicalDataBuffer {
    constructor() {
        this.speculativeBuffer = new Map();  // Current predictions
        this.canonicalBuffer = new Map();    // Confirmed data only
    }

    // Called during step() - stores speculatively
    storeSpeculative(frame, data) {
        this.speculativeBuffer.set(frame, data);
    }

    // Called when confirmedFrame advances - promotes to canonical
    promoteToCanonical(confirmedFrame) {
        for (const [frame, data] of this.speculativeBuffer.entries()) {
            if (frame <= confirmedFrame) {
                this.canonicalBuffer.set(frame, data);
                this.speculativeBuffer.delete(frame);
            }
        }
    }

    // Called on rollback - clears invalidated speculative data
    clearFromFrame(targetFrame) {
        for (const frame of this.speculativeBuffer.keys()) {
            if (frame >= targetFrame) {
                this.speculativeBuffer.delete(frame);
            }
        }
    }

    // For export - only canonical data
    getCanonicalData() {
        return Array.from(this.canonicalBuffer.entries())
            .sort((a, b) => a[0] - b[0])
            .map(([frame, data]) => data);
    }
}
```

**Pattern 3: Frame Confirmation Callback (NetplayJS approach)**

The NetplayJS `RollbackHistory` class tracks `isPrediction: boolean` per input. When all inputs for a frame become confirmed, the frame is "synced."

```javascript
// Track prediction status per frame
allInputsSynced(frameNumber) {
    const frameInputs = this.inputBuffer.get(frameNumber);
    if (!frameInputs) return false;

    for (const [playerId, inputRecord] of frameInputs.entries()) {
        if (inputRecord.isPrediction) return false;
    }
    return true;
}
```

### Recommended Implementation for Interactive-Gym

Given the existing architecture, **Pattern 1 (Deferred Recording)** is the simplest fix:

```javascript
// Modify exportEpisodeFromBuffer() in the existing codebase
_exportEpisodeFromBuffer() {
    const episodeData = {
        // ... existing fields ...
        frames: []
    };

    // CRITICAL: Only export frames up to confirmedFrame
    const exportableFrames = Array.from(this.frameDataBuffer.entries())
        .filter(([frame, _]) => frame <= this.confirmedFrame)
        .sort((a, b) => a[0] - b[0]);

    for (const [frameNum, frameData] of exportableFrames) {
        episodeData.frames.push({
            frame: frameNum,
            ...frameData
        });
    }

    return episodeData;
}
```

## Key Patterns from GGPO/Fighting Games

### How GGPO Handles Replay Data

1. **Input-Only Recording:** GGPO records only inputs, not full game state. Given determinism, inputs are sufficient to replay.

2. **Confirmed Input Marking:** Each input is either "confirmed" (received from peer) or "predicted" (guessed). The `ggpo_synchronize_inputs()` function returns inputs with their source.

3. **Save State Timing:** `save_game_state` callback is called at confirmed frames, not speculative frames. This ensures snapshots are authoritative.

4. **Replay Recording:** The Universal Fighting Engine (UFE) offers "Record Post-Rollback Frames" toggle to see what happened after corrections, separate from what player saw.

### Data Parity Guarantee

For research validity, both players MUST export identical data. This requires:

1. **Deterministic Frame Numbering:** Both players must agree on which frame is which.
2. **Confirmed Data Only:** Only export data for frames where both players' inputs are known.
3. **Hash Verification:** Compare hashes of confirmed frames to detect any divergence.

The codebase already has hash comparison via `confirmedHashHistory`. The gap is ensuring `frameDataBuffer` export respects the same boundary.

## Existing Libraries/References

| Library | Relevance | JS Applicability |
|---------|-----------|------------------|
| [GGPO](https://www.ggpo.net/) | Original rollback SDK; defines the canonical patterns | C/C++ only, but patterns transfer directly |
| [NetplayJS](https://github.com/rameshvarun/netplayjs) | TypeScript GGPO implementation for browser games | **Directly applicable.** `RollbackHistory` class shows data structures. |
| [Telegraph](https://github.com/thomasboyt/telegraph) | TypeScript port of GGPO using PeerJS/WebRTC | **Directly applicable.** Requires deterministic game + serializable state. |
| [GGRS](https://github.com/gschup/ggrs) | Rust reimplementation of GGPO | Patterns transfer; has browser demos via WASM |
| [Backroll](https://github.com/HouraiTeahouse/backroll-rs) | Pure Rust GGPO implementation | Patterns transfer |
| [netcode-rollback](https://github.com/Corrade/netcode-rollback) | Unity P2P rollback implementation | Documents "confirmed tick" vs "speculative" concepts clearly |

### Key Implementation References

- **NetplayJS RollbackHistory:** Shows how to track `isPrediction` flag per input
- **GGPO DeveloperGuide:** Documents `save_game_state`/`load_game_state` callback contracts
- **SnapNet Rollback Architecture:** Explains input delay configuration and rollback window sizing

## Specific Recommendations for Interactive-Gym

### Immediate Fix (Low Effort)

Modify `_exportEpisodeFromBuffer()` to filter by `confirmedFrame`:

```javascript
// Only export confirmed frames
const exportableFrames = Array.from(this.frameDataBuffer.entries())
    .filter(([frame, _]) => frame <= this.confirmedFrame);
```

### Robust Solution (Medium Effort)

1. **Add confirmation callback:** When `updateConfirmedFrame()` advances, call a new method `promoteFrameDataToCanonical(frame)`.

2. **Separate canonical buffer:** Store confirmed data separately from speculative data.

3. **Final validation:** At episode end, verify `confirmedFrame` covers all frames before export. If not, wait or truncate.

### Edge Case: Episode Ends During Rollback

If episode ends (terminal state reached) while frames are still unconfirmed:
- Option A: Wait for inputs to arrive (may block)
- Option B: Truncate data to `confirmedFrame` (loses some frames)
- Option C: Mark final frames as "unconfirmed" in export metadata

Recommendation: **Option B** with logging. Research data should be authoritative; losing 1-2 frames at episode end is acceptable.

## Alternatives Considered

### Server-Authoritative State

**Pattern:** One player acts as authoritative server; other player reconciles.

**Why not:**
- Breaks P2P symmetry
- Adds latency for "client" player
- More complex than fixing confirmed frame boundary

### Lockstep Netcode

**Pattern:** Wait for all inputs before simulating each frame.

**Why not:**
- Already using rollback for responsiveness
- Would require architecture rewrite
- Input delay is worse UX than rollback

### Checksumming Every Frame

**Pattern:** Compare full state checksums every frame.

**Why not:**
- Already doing this for confirmed frames (`confirmedHashHistory`)
- Every frame would be expensive
- Desync detection doesn't prevent data divergence

## Confidence Assessment

| Finding | Confidence | Basis |
|---------|------------|-------|
| Confirmed frame boundary is correct approach | HIGH | GGPO docs, NetplayJS, fighting game implementations |
| Existing `confirmedFrame` tracking is correct | HIGH | Code review; matches GGPO pattern |
| Data export needs to respect confirmedFrame | HIGH | Logical deduction from confirmed frame semantics |
| Dual buffer pattern would work | MEDIUM | Common pattern but adds complexity |
| Episode-end edge cases matter | MEDIUM | May not occur often in practice |

## Sources

- [GGPO Official Site](https://www.ggpo.net/) - Canonical rollback patterns
- [GGPO GitHub Documentation](https://github.com/pond3r/ggpo/blob/master/doc/DeveloperGuide.md) - Save/load callback contracts
- [NetplayJS GitHub](https://github.com/rameshvarun/netplayjs) - TypeScript rollback implementation
- [Telegraph GitHub](https://github.com/thomasboyt/telegraph) - TypeScript GGPO port for browser
- [SnapNet Rollback Architecture](https://www.snapnet.dev/blog/netcode-architectures-part-2-rollback/) - Input delay and rollback window explanation
- [netcode-rollback GitHub](https://github.com/Corrade/netcode-rollback) - Confirmed vs speculative state documentation
- [INVERSUS Rollback Networking](https://www.gamedeveloper.com/design/rollback-networking-in-inversus) - Deterministic replay recording
- [Universal Fighting Engine Docs](http://www.ufe3d.com/doku.php/global:network) - Post-rollback frame recording option
- Existing codebase: `/Users/chasemcd/Repositories/interactive-gym/interactive_gym/server/static/js/pyodide_multiplayer_game.js`
