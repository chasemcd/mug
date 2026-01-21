# Architecture: Sync Validation Integration with GGPO Rollback

**Domain:** P2P multiplayer sync validation for v1.1
**Researched:** 2026-01-20
**Confidence:** HIGH (based on existing codebase analysis, GGPO patterns, and industry best practices)

## Executive Summary

Sync validation in GGPO-style rollback netcode requires careful integration with the input confirmation flow. The key architectural principle: **compute hashes only on confirmed frames** (frames where all players' inputs have been received), and **exchange hashes after rollback completion** (not during). This ensures hash comparisons are deterministic and meaningful.

The existing `pyodide_multiplayer_game.js` already has partial sync validation infrastructure (state hashes, periodic broadcasting via SocketIO), but it operates on potentially-predicted frames and doesn't integrate tightly with the GGPO confirmation flow. The v1.1 enhancement should compute hashes **at confirmation time** and exchange them **over the P2P DataChannel** as a lightweight binary message.

---

## Current Architecture Analysis

### Existing State Hash Infrastructure

The codebase already implements several hash-related features:

| Component | Location | Current Behavior |
|-----------|----------|------------------|
| `computeQuickStateHash()` | Line ~1900 | MD5 hash of `env.get_state()` JSON |
| `stateHashHistory` | Line 506-508 | Map of frameNumber to hash (max 60 entries) |
| `recordStateHashForFrame()` | Line ~1860 | Records hash for a frame (currently disabled) |
| `p2p_state_sync` SocketIO | Line 719-787 | Periodic hash broadcast via server |
| `confirmedFrame` | Line 434, 522 | Tracks last frame with all inputs confirmed |

**Current Gap:** Hash computation happens on potentially-predicted frames, and hash exchange goes through SocketIO (server relay) rather than P2P DataChannel.

### GGPO Input Confirmation Flow

The existing input confirmation flow in `step()`:

```
1. _processQueuedInputs()        // Drain network buffers synchronously
2. processDelayedInputs()        // Handle debug-delayed inputs
3. Check pendingRollbackFrame    // If set, execute rollback BEFORE stepping
4. performRollback() if needed   // Restore snapshot, replay with confirmed inputs
5. getInputsForFrame()           // Get confirmed OR predicted inputs
6. stepWithActions()             // Execute frame
7. frameNumber++                 // Advance frame counter
```

**Key insight:** A frame is "confirmed" when `getInputsForFrame()` returns only confirmed inputs (no predictions). Currently tracked via `predictedFrames` Set, but no explicit `confirmedFrame` advancement during normal stepping.

---

## Recommended Architecture: Hash-on-Confirm

### Core Principle

**Hash computation should only occur on frames where ALL players' inputs are confirmed.**

```
Frame state lifecycle:
  PREDICTED → CONFIRMED → HASHED → EXCHANGED → VERIFIED

Only transition to HASHED when:
  - Frame has exited PREDICTED state (not in predictedFrames)
  - All players' inputs are in inputBuffer for that frame
  - Frame has been stepped (post-step state is what gets hashed)
```

### Integration Points in Frame Processing Pipeline

```javascript
// Modified step() flow with sync validation

async step() {
    // 1. Process queued inputs (existing)
    this._processQueuedInputs();

    // 2. Check for and execute rollback (existing)
    if (this.pendingRollbackFrame !== null) {
        await this.performRollback(...);
        // IMPORTANT: After rollback, recalculate confirmed frame
        this._updateConfirmedFrame();
    }

    // 3. Get inputs for current frame (existing)
    const inputs = this.getInputsForFrame(this.frameNumber, playerIds);

    // 4. Step environment (existing)
    await this.stepWithActions(finalActions);

    // 5. Save snapshot (existing, every snapshotInterval frames)
    if (this.frameNumber % this.snapshotInterval === 0) {
        await this.saveStateSnapshot(this.frameNumber);
    }

    // 6. NEW: Check if previous frames are now fully confirmed
    this._processNewlyConfirmedFrames();

    // 7. Advance frame (existing)
    this.frameNumber++;

    // 8. NEW: Exchange hashes for confirmed frames (batched)
    this._exchangePendingHashes();
}
```

### When State is "Final" for a Frame

A frame's state is final for hashing when:

1. **Frame has been stepped** - We have post-step state
2. **No rollback will touch it** - All players' inputs are confirmed
3. **Snapshot exists** (if applicable) - State can be reproduced

The mathematical condition:

```
Frame N is hashable IFF:
  - N < currentFrame (already stepped)
  - inputBuffer.has(N) && allPlayersHaveInput(N) (all inputs confirmed)
  - N not in pendingRollbackFrame..currentFrame range (won't be replayed)
```

### Confirmed Frame Advancement Logic

```javascript
_updateConfirmedFrame() {
    // Find the highest frame where ALL players have confirmed inputs
    // and we've already stepped past it

    const humanPlayerIds = this._getHumanPlayerIds();

    for (let frame = this.confirmedFrame + 1; frame < this.frameNumber; frame++) {
        if (this.hasAllInputsForFrame(frame, humanPlayerIds)) {
            // This frame is now confirmed
            this.confirmedFrame = frame;

            // Remove from predictedFrames if it was there
            this.predictedFrames.delete(frame);

            // Queue for hash computation
            this._queueFrameForHashing(frame);
        } else {
            // Gap in confirmation - stop here
            break;
        }
    }
}
```

---

## Hash Exchange Protocol

### New Binary Message Type

Add to P2P protocol (currently has INPUT=0x01, PING=0x02, PONG=0x03, KEEPALIVE=0x04, EPISODE_END=0x05, EPISODE_READY=0x06):

```javascript
const P2P_MSG_STATE_HASH = 0x07;

// Format: 13 bytes
//   Byte 0: Message type (0x07)
//   Bytes 1-4: Frame number (uint32)
//   Bytes 5-12: Hash value (8 bytes, first 16 hex chars of MD5)

function encodeStateHash(frameNumber, hash) {
    const buffer = new ArrayBuffer(13);
    const view = new DataView(buffer);
    view.setUint8(0, P2P_MSG_STATE_HASH);
    view.setUint32(1, frameNumber, false);  // big-endian
    // Write 8 bytes of hash (16 hex chars = 8 bytes)
    for (let i = 0; i < 8; i++) {
        const hexPair = hash.substring(i * 2, i * 2 + 2);
        view.setUint8(5 + i, parseInt(hexPair, 16));
    }
    return buffer;
}
```

### Exchange Timing

Hashes should be exchanged:

1. **After frame confirmation** - Not after every step, only when confirmedFrame advances
2. **Batched if multiple frames confirm** - Avoid flooding peer with individual messages
3. **With priority lower than inputs** - Input delivery is time-critical, hashes are not
4. **Separate from rollback** - Never send hashes during `performRollback()`

```javascript
_exchangePendingHashes() {
    // Skip if rollback in progress (hash would be from mid-replay state)
    if (this.rollbackInProgress) {
        return;
    }

    // Drain pending hash queue
    while (this.pendingHashExchange.length > 0) {
        const { frame, hash } = this.pendingHashExchange.shift();

        // Send via P2P if available, otherwise queue for later
        if (this.webrtcManager?.isReady()) {
            const packet = encodeStateHash(frame, hash);
            this.webrtcManager.send(packet);
        } else {
            // Fallback: use SocketIO (existing p2p_state_sync path)
            this._sendHashViaSocketIO(frame, hash);
        }
    }
}
```

---

## Mismatch Detection and Rollback Interaction

### Detection Flow

```
Peer A sends hash for frame N → Peer B receives
Peer B checks:
  1. Do we have a hash for frame N? (confirmedHashHistory)
     - If no: Buffer peer's hash until we confirm frame N
  2. Do hashes match?
     - If yes: Frame N is mutually verified, update verifiedFrame
     - If no: DESYNC DETECTED

On desync:
  - Log event with both hashes and frame number
  - If frame N < currentFrame: We've already diverged
  - Decision: Request resync OR continue and report
```

### Critical: Never Rollback During Hash Comparison

The existing `performRollback()` sets `rollbackInProgress = true` as a guard. Hash comparison must respect this:

```javascript
async _handleReceivedHash(frame, peerHash) {
    // DO NOT process hashes during rollback - state is in flux
    if (this.rollbackInProgress) {
        this.pendingHashComparisons.push({ frame, peerHash });
        return;
    }

    // Get our hash for this frame
    const ourHash = this.confirmedHashHistory.get(frame);

    if (!ourHash) {
        // We haven't confirmed this frame yet - buffer for later
        this.pendingPeerHashes.set(frame, peerHash);
        return;
    }

    // Compare
    if (ourHash === peerHash) {
        this._markFrameVerified(frame);
    } else {
        this._handleDesync(frame, ourHash, peerHash);
    }
}
```

### Desync Handling Options

When mismatch detected, ordered from least to most disruptive:

1. **Log and continue** - For research, just record the desync
2. **Request state from peer** - Lower player ID defers to higher (existing pattern)
3. **Pause game** - Wait for state resync before continuing
4. **Disconnect** - If desync is unrecoverable

For v1.1, recommend option 1 (log) with option 2 as configurable fallback.

---

## Data Structures

### New State Tracking

```javascript
// Add to MultiplayerPyodideGame constructor

// Confirmed hash history: hashes for frames where all inputs are verified
this.confirmedHashHistory = new Map();  // frameNumber -> hash
this.confirmedHashHistoryMaxSize = 120;  // Keep ~4 seconds at 30fps

// Pending hash exchange: frames that need hash sent to peer
this.pendingHashExchange = [];  // [{frame, hash}, ...]

// Pending peer hashes: peer's hashes we received before confirming that frame
this.pendingPeerHashes = new Map();  // frameNumber -> peerHash

// Verified frame: highest frame where both peers agree on hash
this.verifiedFrame = -1;

// Desync tracking
this.desyncEvents = [];  // [{frame, ourHash, peerHash, timestamp}, ...]
```

### Hash History Management

```javascript
_recordConfirmedHash(frame) {
    // Compute hash for this confirmed frame
    const hash = await this.computeQuickStateHash();

    // Store in confirmed history
    this.confirmedHashHistory.set(frame, hash);

    // Queue for exchange
    this.pendingHashExchange.push({ frame, hash });

    // Check if peer already sent their hash for this frame
    const peerHash = this.pendingPeerHashes.get(frame);
    if (peerHash) {
        this.pendingPeerHashes.delete(frame);
        this._compareHashes(frame, hash, peerHash);
    }

    // Prune old entries
    this._pruneHashHistory();
}
```

---

## Timing Considerations

### Hash Computation Cost

`computeQuickStateHash()` involves:
1. `env.get_state()` - Python call, ~1-5ms typical
2. `JSON.stringify()` - Serialization, depends on state size
3. MD5 hash - Fast, <1ms

**Total: 2-10ms per hash computation**

### When to Compute (Performance Trade-off)

| Strategy | Frequency | CPU Cost | Detection Latency |
|----------|-----------|----------|-------------------|
| Every frame | 30/sec | High (~150-300ms/sec) | Immediate |
| On confirm | Variable | Medium | Low (input delay + RTT) |
| Periodic | Every N frames | Low | N frames |
| On snapshot | Every 5 frames | Low | 5 frames |

**Recommendation:** Compute on confirmation (matches input delay + RTT naturally) OR piggyback on snapshot interval for minimal overhead.

### Integration with Snapshot Interval

Since snapshots are already computed every `snapshotInterval` (5) frames, hash computation can piggyback:

```javascript
// In step(), after snapshot save
if (this.frameNumber % this.snapshotInterval === 0) {
    await this.saveStateSnapshot(this.frameNumber);

    // Also compute and store hash (state is already in memory)
    await this._recordConfirmedHashIfReady(this.frameNumber);
}
```

---

## Edge Cases and Pitfalls

### 1. Rollback Invalidates Hashes

When rollback occurs for frame N:
- All hashes for frames >= N are invalid
- Must recompute after replay completes
- Don't compare peer hashes against pre-rollback values

```javascript
async performRollback(targetFrame, playerIds) {
    // ... existing rollback code ...

    // Invalidate hashes from rollback point onward
    for (const frame of this.confirmedHashHistory.keys()) {
        if (frame >= targetFrame) {
            this.confirmedHashHistory.delete(frame);
        }
    }

    // Also clear any pending comparisons for these frames
    for (const frame of this.pendingPeerHashes.keys()) {
        if (frame >= targetFrame) {
            this.pendingPeerHashes.delete(frame);
        }
    }

    // Verified frame cannot be beyond rollback point
    this.verifiedFrame = Math.min(this.verifiedFrame, targetFrame - 1);
}
```

### 2. Asymmetric Confirmation Timing

Peers may confirm frames at different times due to:
- Different network latency
- Different local processing time
- Packet loss causing retransmission

**Solution:** Buffer peer hashes until local confirmation catches up.

### 3. Hash Computation During Async Operations

`computeQuickStateHash()` is async (Python call). Must ensure:
- State doesn't change during computation
- No race with rollback starting

**Solution:** Call from synchronous context within step(), never concurrently.

### 4. Episode Reset Clears Everything

On episode reset, must clear:
- confirmedHashHistory
- pendingHashExchange
- pendingPeerHashes
- verifiedFrame

This is already partially handled in `clearGGPOState()`.

---

## Implementation Phases

### Phase A: Hash-on-Confirm Infrastructure (Foundation)

1. Add `confirmedHashHistory` and related data structures
2. Implement `_updateConfirmedFrame()` to track confirmation
3. Implement `_recordConfirmedHash()` for hash computation
4. Add hash invalidation to `performRollback()`

**Verification:** Log confirmed frames and hashes, compare manually between peers.

### Phase B: P2P Hash Exchange (Transport)

1. Add P2P_MSG_STATE_HASH message type
2. Implement `encodeStateHash()` / `decodeStateHash()`
3. Add `_exchangePendingHashes()` to step loop
4. Add `_handleReceivedHash()` message handler

**Verification:** Both peers exchange hashes, log shows symmetric values.

### Phase C: Mismatch Detection (Detection)

1. Implement hash comparison logic
2. Add buffering for out-of-order peer hashes
3. Track `verifiedFrame` as highest mutually-verified frame
4. Log desync events with full context

**Verification:** Deliberately cause desync (different action), observe detection.

### Phase D: Response Mechanism (Response)

1. Add desync response configuration (log-only, resync, disconnect)
2. Implement state request/response for resync
3. Add UI indication of sync status (optional)
4. Integrate desync events into session metrics

**Verification:** Desync triggers configured response, game recovers or reports.

---

## Component Interaction Diagram

```
+------------------+     +------------------+
|  Step Loop       |     |  Message Handler |
|                  |     |                  |
| 1. processInputs |     | onDataChannel    |
| 2. rollback?     |     |   message        |
| 3. getInputs     |     |                  |
| 4. step          |     |                  |
| 5. snapshot?     |     |                  |
| 6. updateConfirm |<----|---[input arrives]|
| 7. frameNumber++ |     |                  |
| 8. exchangeHash--|---->|---[hash arrives]-+
+------------------+     +-----|------------+
        |                      |
        v                      v
+------------------+     +------------------+
| confirmedHash    |     | pendingPeerHash  |
| History          |     | Buffer           |
+------------------+     +------------------+
        |                      |
        +----------+-----------+
                   |
                   v
           +---------------+
           | _compareHashes|
           | - match: OK   |
           | - mismatch:   |
           |   DESYNC      |
           +---------------+
                   |
                   v
           +---------------+
           | verifiedFrame |
           | desyncEvents  |
           +---------------+
```

---

## Success Criteria

Sync validation integration is complete when:

- [ ] Hashes computed only on confirmed frames (not predicted)
- [ ] Hash exchange uses P2P DataChannel (not SocketIO)
- [ ] Rollback invalidates affected hashes correctly
- [ ] Peer hash buffering handles async confirmation
- [ ] Desync detection logs frame, both hashes, and timestamp
- [ ] verifiedFrame tracks highest mutually-verified frame
- [ ] Session metrics include desync count and details
- [ ] No performance regression (< 10% step time increase)
- [ ] Works correctly with existing rollback flow

---

## Sources

**HIGH confidence (direct code analysis):**
- `pyodide_multiplayer_game.js` - Existing GGPO implementation, hash infrastructure
- `webrtc_manager.js` - P2P DataChannel protocol

**MEDIUM confidence (industry patterns):**
- [GGPO Developer Guide](https://github.com/pond3r/ggpo/blob/master/doc/DeveloperGuide.md) - Sync test methodology
- [Coherence Documentation](https://docs.coherence.io/manual/advanced-topics/competitive-games/determinism-prediction-rollback) - AckFrame concept
- [SnapNet Rollback Article](https://www.snapnet.dev/blog/netcode-architectures-part-2-rollback/) - Rollback architecture patterns

**LOW confidence (general patterns):**
- [Gaffer On Games - Deterministic Lockstep](https://gafferongames.com/post/deterministic_lockstep/) - Checksum timing
- [Factorio Wiki - Desynchronization](https://wiki.factorio.com/Desynchronization) - Desync detection approaches

---

*Architecture analysis for v1.1 Sync Validation: 2026-01-20*
