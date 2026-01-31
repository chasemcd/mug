# Feature Research: Rollback Netcode Data Consistency

**Domain:** Rollback netcode authoritative history and data recording for P2P multiplayer
**Researched:** 2026-01-30
**Confidence:** HIGH (codebase analysis + established rollback netcode patterns)

## Executive Summary

This research addresses data divergence in P2P rollback netcode systems where both players must export IDENTICAL game data (actions, rewards, infos) for research purposes. The core challenge: rollbacks and fast-forwards cause each peer to execute frames multiple times with potentially different inputs, creating divergent local histories.

**Key insight:** In GGPO-style rollback netcode, there is no single "authoritative" peer in true P2P. Instead, **authoritative history emerges from input confirmation** - a frame becomes "confirmed" when ALL players' inputs for that frame have been received by ALL peers. Only confirmed frames should be recorded for export.

## Frame State Lifecycle

### States

| State | Definition | When Reached |
|-------|------------|--------------|
| **FUTURE** | Frame not yet simulated | Default state for frames > currentFrame |
| **SPECULATIVE** | Frame executed but using at least one predicted input | When `getInputsForFrame()` returns any prediction |
| **CONFIRMED** | All players' inputs received for this frame by this peer | When `inputBuffer.get(frame)` contains entries for ALL human players |
| **VERIFIED** | Confirmed AND peer hash matches (optional) | When local and remote hashes for frame agree (Phase 11-14 infrastructure) |
| **RECORDED** | Frame data exported to final dataset | When frame transitions to CONFIRMED and data is moved from speculative buffer to export buffer |

### State Transitions

```
                              +------------------+
                              |      FUTURE      |
                              +--------+---------+
                                       |
                     (frame simulated) | step() executes
                                       v
                    +------------------+-----------------+
                    |                                    |
        (missing inputs)                      (all inputs present)
                    v                                    v
           +--------+--------+                +---------+---------+
           |   SPECULATIVE   |                |     CONFIRMED     |
           +--------+--------+                +---------+---------+
                    |                                    |
                    |  (late input arrives)              |  (peer hash received)
                    |  storeRemoteInput()                |  _compareFrameHashes()
                    |                                    v
                    |                         +---------+---------+
                    |                         |     VERIFIED      |
                    |                         +---------+---------+
                    |                                    |
                    +---------->-----------<-------------+
                                       |
                    (ready for export) | _updateConfirmedFrame()
                                       v
                              +--------+---------+
                              |     RECORDED     |
                              +------------------+

    ROLLBACK EVENT:
    If late input differs from prediction:
    SPECULATIVE -> (rollback) -> clear frames >= targetFrame -> replay with confirmed inputs
```

### Rollback Impact on State

When rollback occurs:
1. Frames from `targetFrame` to `currentFrame` transition back to FUTURE
2. `frameDataBuffer` entries for those frames are CLEARED (`clearFrameDataFromRollback()`)
3. Frames are re-executed with correct inputs
4. Re-executed frames may be SPECULATIVE (if still missing other player's inputs) or CONFIRMED

**Critical:** A frame may be rolled back and re-executed multiple times before becoming CONFIRMED. Only the final confirmed execution should be recorded.

## Confirmation Protocol

### Input Confirmation in P2P (Two Players)

In true P2P with GGPO-style rollback, input confirmation happens independently on each peer:

**Peer A's view:**
- Frame N is CONFIRMED when:
  - Peer A has stored their own input for frame N (`storeLocalInput`)
  - Peer A has received Peer B's input for frame N (`storeRemoteInput`)

**Peer B's view:**
- Frame N is CONFIRMED when:
  - Peer B has stored their own input for frame N (`storeLocalInput`)
  - Peer B has received Peer A's input for frame N (`storeRemoteInput`)

**Key insight:** Both peers will eventually reach the same CONFIRMED state for frame N because:
1. Each peer's local input is sent to the other via P2P DataChannel
2. Each peer stores both their local input and received remote inputs in `inputBuffer`
3. When both inputs exist in `inputBuffer.get(N)`, frame N is CONFIRMED

### Current Implementation Analysis

The existing codebase (`pyodide_multiplayer_game.js`) has the infrastructure:

```javascript
// Lines 2901-2911: Check if all players have inputs for a frame
_hasAllInputsForFrame(frameNumber, playerIds) {
    const frameInputs = this.inputBuffer.get(frameNumber);
    if (!frameInputs) return false;

    for (const playerId of playerIds) {
        if (!frameInputs.has(String(playerId))) {
            return false;
        }
    }
    return true;
}

// Lines 2918-2951: Update confirmedFrame tracking
async _updateConfirmedFrame() {
    const humanPlayerIds = this._getHumanPlayerIds();
    // Find highest consecutive confirmed frame
    for (let frame = startFrame; frame < this.frameNumber; frame++) {
        if (this._hasAllInputsForFrame(frame, humanPlayerIds)) {
            this.confirmedFrame = frame;
            // ... compute and store hash
        } else {
            break;  // Gap in confirmation
        }
    }
}
```

**Current gap:** Frame data is stored in `frameDataBuffer` immediately on step completion (line 2441-2449), regardless of confirmation status. Export (`exportEpisodeDataFromBuffer`) doesn't filter by confirmation state.

## Data Recording Rules

### Table Stakes (Must Have)

| Rule | Why Required | Implementation Notes |
|------|--------------|---------------------|
| **Record only CONFIRMED frames** | Speculative frames may use wrong inputs; will be corrected on rollback | Check `confirmedFrame >= frameNumber` before writing to export buffer |
| **Clear speculative data on rollback** | Rollback invalidates all data from targetFrame onward | Existing: `clearFrameDataFromRollback(targetFrame)` - already implemented |
| **Re-record during replay** | Replay produces correct data after rollback | Existing: `storeFrameData()` called during replay (lines 4747-4756) |
| **Buffer until confirmation** | Can't export speculative data as final | New: separate `speculativeDataBuffer` from `confirmedDataBuffer` |
| **Export from confirmed buffer only** | Ensures both peers export identical data | Modify `exportEpisodeDataFromBuffer()` to read from confirmed buffer |
| **Include confirmation metadata** | Research needs to know which frames were speculative | Add `wasSpeculative: bool` and `rollbackCount: number` per frame |

### Differentiator Rules (Research Value-Add)

| Rule | Why Valuable | Implementation Notes |
|------|--------------|---------------------|
| **Track rollback events per frame** | Understand prediction accuracy | Existing: `sessionMetrics.rollbacks.events` |
| **Include input delay metrics** | Correlate delay with rollback frequency | Add `inputDelayAtRecord` field |
| **Mark focus state per frame** | Filter out backgrounded frames if needed | Existing: `isFocused` field per frame |
| **Hash verification status** | Know which frames were cryptographically verified | Add `peerHashMatch: bool` from Phase 11-14 |

## Edge Cases

### Scenario: Rollback

| Step | Correct Behavior | Common Mistake |
|------|------------------|----------------|
| 1. Late input arrives | Trigger `pendingRollbackFrame` | Recording data before checking for rollback |
| 2. Clear speculative data | `clearFrameDataFromRollback(targetFrame)` | Only clearing some data structures |
| 3. Load snapshot | `loadStateSnapshot(snapshotFrame)` | Forgetting to restore RNG state |
| 4. Replay frames | Execute with confirmed inputs, re-store frame data | Not re-storing data during replay |
| 5. Resume normal execution | Continue from `currentFrame` | Leaving `rollbackInProgress` flag set |

### Scenario: Fast-Forward (Tab Refocus)

| Step | Correct Behavior | Common Mistake |
|------|------------------|----------------|
| 1. Detect refocus | `FocusManager._onForegrounded()` | Not detecting visibility change |
| 2. Request missing inputs | `_requestMissingInputs()` if gaps exist | Processing immediately without inputs |
| 3. Fast-forward execution | Execute batched frames without rendering | Rendering each frame (slow, causes freeze) |
| 4. Mark focus state | `isFocused: false` for backgrounded frames | Recording all frames as focused |
| 5. Data recording | Same as rollback - store with correct inputs | Using predicted inputs without verification |

### Scenario: Packet Loss (Missing Inputs)

| Step | Correct Behavior | Common Mistake |
|------|------------------|----------------|
| 1. Input not received | Use prediction (`getPredictedAction`) | Blocking/waiting for input |
| 2. Mark as speculative | Add frame to `predictedFrames` set | Treating predicted frame as confirmed |
| 3. Continue simulation | Execute with prediction, don't record as final | Recording speculative data as final |
| 4. Input arrives late | Trigger rollback if prediction was wrong | Ignoring late input |
| 5. After correction | Frame becomes CONFIRMED, record correct data | Keeping wrong data in export buffer |

### Scenario: Episode End During Speculation

| Step | Correct Behavior | Common Mistake |
|------|------------------|----------------|
| 1. Terminal state detected | Set `episodeComplete = true` | Immediately exporting data |
| 2. Wait for peer sync | Exchange `p2p_episode_ready` messages | Exporting before peer reaches same state |
| 3. Confirm final frames | Wait for all inputs up to terminal frame | Exporting with predicted final frames |
| 4. Export confirmed data | Only export frames where `frame <= confirmedFrame` | Exporting all frames including speculative |

## Feature Dependencies

For data parity to work correctly, these must be true:

1. **Deterministic simulation**: Given same inputs, both peers produce identical state
   - Verified via state hash comparison (Phase 11-14)
   - Requires seeded RNG, deterministic environment

2. **Reliable input delivery**: All inputs eventually reach both peers
   - P2P DataChannel with redundant sending (3 inputs per packet)
   - SocketIO fallback path
   - Input request mechanism for missing inputs

3. **Synchronized episode boundaries**: Both peers agree when episode ends
   - `p2pEpisodeSync` mechanism
   - Wait for peer before exporting

4. **Consistent frame numbering**: Both peers use same frame counter
   - Shared `syncEpoch` prevents stale frame matching
   - Frame counter resets together on episode start

5. **Rollback capability**: Environment supports `get_state()` / `set_state()`
   - Required for snapshot/restore
   - `stateSyncSupported` flag gates rollback features

## Recommended Data Structure

### Dual-Buffer Approach

```javascript
// Speculative buffer - data from current execution (may be wrong)
this.speculativeDataBuffer = new Map();  // frameNumber -> frameData

// Confirmed buffer - data promoted after confirmation (correct)
this.confirmedDataBuffer = new Map();    // frameNumber -> frameData

// On step completion:
storeFrameData(frameNumber, data) {
    this.speculativeDataBuffer.set(frameNumber, data);
    this._promoteConfirmedFrames();
}

// On rollback:
clearFrameDataFromRollback(targetFrame) {
    for (const frame of this.speculativeDataBuffer.keys()) {
        if (frame >= targetFrame) {
            this.speculativeDataBuffer.delete(frame);
        }
    }
    // Note: DO NOT clear confirmedDataBuffer - those frames are already confirmed
    // But in rare cases (server correction), we may need to invalidate confirmed data too
}

// Promote confirmed frames:
_promoteConfirmedFrames() {
    const humanPlayerIds = this._getHumanPlayerIds();
    for (const [frame, data] of this.speculativeDataBuffer) {
        if (frame <= this.confirmedFrame && this._hasAllInputsForFrame(frame, humanPlayerIds)) {
            // Frame is confirmed - move to confirmed buffer
            this.confirmedDataBuffer.set(frame, {
                ...data,
                wasSpeculative: this.predictedFrames.has(frame),
                confirmedAt: Date.now()
            });
            this.speculativeDataBuffer.delete(frame);
        }
    }
}

// Export only confirmed data:
exportEpisodeDataFromBuffer() {
    // Only read from confirmedDataBuffer
    const sortedFrames = Array.from(this.confirmedDataBuffer.keys()).sort((a, b) => a - b);
    // ... build export format from confirmed frames only
}
```

### Frame Data Schema (Extended)

```javascript
{
    // Core data (existing)
    actions: { playerId: action },
    rewards: { playerId: reward },
    terminateds: { playerId: bool },
    truncateds: { playerId: bool },
    infos: { playerId: info },
    isFocused: bool,
    timestamp: number,

    // Confirmation metadata (new)
    wasSpeculative: bool,           // Was this frame ever predicted?
    confirmedAt: number,            // Timestamp when frame became confirmed
    rollbacksBeforeConfirm: number, // How many times was this frame rolled back?
    inputDelayFrames: number,       // INPUT_DELAY setting when recorded

    // Verification metadata (from Phase 11-14)
    localHash: string,              // State hash after this frame
    peerHashMatch: bool,            // Did peer's hash match?
    hashVerifiedAt: number          // Timestamp of hash verification
}
```

## Anti-Features (Do NOT Build)

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| **Server-authoritative data source** | P2P architecture has no server running the game; adds complexity | Each peer exports from own confirmed buffer; verify with hash comparison |
| **Waiting for confirmation before stepping** | Transforms rollback into lockstep; kills responsiveness | Predict and continue; rollback on mismatch |
| **Real-time data streaming to server** | Network overhead; doesn't solve divergence | Batch export at episode end |
| **Discarding all rollback data** | Loses research value of understanding rollback patterns | Record rollback metadata, discard wrong values |
| **Single global "authoritative" export** | No single authority in P2P | Both peers export; verify equivalence offline |

## Implementation Priority

### Phase 1: Core Confirmation Tracking (Required)

1. Add `confirmedFrame` tracking (already exists)
2. Add `_hasAllInputsForFrame()` check (already exists)
3. Split data buffers: speculative vs confirmed
4. Modify export to read from confirmed buffer only

### Phase 2: Rollback-Safe Data Recording (Required)

1. Clear speculative buffer on rollback (partially exists)
2. Re-store data during replay (exists)
3. Promote to confirmed buffer after replay completes
4. Ensure episode-end waits for final frame confirmation

### Phase 3: Research Metadata (Recommended)

1. Track `wasSpeculative` per frame
2. Record rollback events with frame ranges
3. Add hash verification status (leverages Phase 11-14)
4. Export confirmation timing metrics

### Phase 4: Verification (Optional)

1. Cross-peer hash comparison at export time
2. Offline validation tool to compare two exports
3. Alert on divergence detection

## Sources

### Primary (HIGH Confidence - Codebase Analysis)
- `/Users/chasemcd/Repositories/interactive-gym/interactive_gym/server/static/js/pyodide_multiplayer_game.js` - Current GGPO implementation (7000+ lines)
- `/Users/chasemcd/Repositories/interactive-gym/.planning/phases/03-ggpo-p2p-integration/03-RESEARCH.md` - Phase 3 research on GGPO integration

### Secondary (HIGH Confidence - Established Patterns)
- [GGPO Developer Guide](https://github.com/pond3r/ggpo/blob/master/doc/DeveloperGuide.md) - Rollback netcode reference
- [Rollback Networking in INVERSUS](https://www.gamedeveloper.com/design/rollback-networking-in-inversus) - Symmetric P2P patterns, deterministic replay
- [SnapNet: Netcode Architectures Part 2: Rollback](https://www.snapnet.dev/blog/netcode-architectures-part-2-rollback/) - Confirmed vs speculative frames

### Tertiary (MEDIUM Confidence - Community Patterns)
- [Gaffer on Games: Deterministic Lockstep](https://gafferongames.com/post/deterministic_lockstep/) - Input acknowledgment protocol
- [2XKO Netcode Article](https://2xko.riotgames.com/en-us/news/dev/how-2xko-handles-online-play/) - Spectator data from confirmed frames
- [BestoNet](https://github.com/BestoGames/BestoNet) - Confirmed frame input buffer for spectators

## Confidence Assessment

| Area | Confidence | Rationale |
|------|------------|-----------|
| Frame state definitions | HIGH | Based on established GGPO patterns + existing codebase |
| Confirmation protocol | HIGH | Directly analyzed from `pyodide_multiplayer_game.js` |
| Dual-buffer approach | HIGH | Standard pattern from INVERSUS and other rollback implementations |
| Rollback edge cases | HIGH | Already implemented in codebase, just needs data recording fix |
| Fast-forward edge cases | HIGH | Implementation exists in codebase (Phase 26) |
| Verification/hash comparison | MEDIUM | Phase 11-14 infrastructure exists but export integration untested |
| Research metadata schema | MEDIUM | Custom requirements; standard patterns provide guidance |
