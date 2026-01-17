# Phase 3: GGPO P2P Integration - Research

**Researched:** 2026-01-17
**Domain:** GGPO Rollback Netcode, P2P Input Exchange, Symmetric Peer Architecture
**Confidence:** HIGH

## Summary

This phase connects the existing GGPO rollback implementation to the P2P transport layer established in Phases 1-2. The current codebase already has:

1. **Complete GGPO rollback netcode** in `pyodide_multiplayer_game.js` (2600+ lines):
   - `storeRemoteInput()` - stores remote player inputs by frame
   - `storeLocalInput()` - schedules local inputs with INPUT_DELAY
   - `getInputsForFrame()` - returns confirmed inputs or predictions
   - `performRollback()` / `loadStateSnapshot()` - rollback and replay
   - State hash verification via `computeQuickStateHash()`

2. **P2P transport layer** from Phases 1-2:
   - `WebRTCManager` class for DataChannel management
   - Binary protocol: `encodeInputPacket()` / `decodeInputPacket()`
   - `P2PInputSender` with redundant input sending
   - `_handleInputPacket()` that already calls `storeRemoteInput()`

3. **Dual-path input sending** (lines 1107-1119):
   - SocketIO: `socket.emit('pyodide_player_action', ...)` - server relays to other clients
   - P2P: `p2pInputSender.recordAndSend()` - direct peer delivery

**The core integration is already in place.** Phase 3's primary work is:
1. Switching to P2P-first input delivery (SocketIO becomes fallback, not primary)
2. Removing asymmetric "host" logic that conflicts with symmetric peer requirements
3. Implementing SocketIO fallback when P2P degrades mid-game
4. Ensuring state hash verification works with P2P-only input path

**Primary recommendation:** Minimize changes. The existing architecture already supports P2P input exchange; the main work is policy changes (P2P-first vs dual-send) and removing host-dependent features.

## Current Input Flow Analysis

### How Inputs Currently Flow

```
LOCAL PLAYER SENDS:
step() method (lines 1098-1119):
  1. Get local action from allActionsDict
  2. Schedule for target frame: targetFrame = frameNumber + INPUT_DELAY
  3. Store locally: storeLocalInput(myCurrentAction, this.frameNumber)
  4. Send to SERVER: socket.emit('pyodide_player_action', {...})
  5. ALSO send P2P: if (this.p2pConnected) p2pInputSender.recordAndSend()

REMOTE PLAYER RECEIVES (SERVER PATH):
socket.on('pyodide_other_player_action', ...) (lines 483-513):
  1. Extract {player_id, action, frame_number}
  2. Store: storeRemoteInput(player_id, action, frame_number)
  3. Updates lastConfirmedActions for prediction

REMOTE PLAYER RECEIVES (P2P PATH):
_handleInputPacket() (lines 2586-2609):
  1. Decode binary packet: decodeInputPacket(buffer)
  2. For each input in packet: storeRemoteInput(playerId, action, frame)
  3. Update connection health monitor
```

### storeRemoteInput() Behavior (lines 1902-1969)

This is the critical integration point. Both SocketIO and P2P paths converge here.

```javascript
storeRemoteInput(playerId, action, frameNumber):
  1. Ensure input buffer exists for frame
  2. DEDUPE: if already have input for this player at this frame, ignore
  3. Store: frameInputs.set(playerIdStr, action)
  4. Update lastConfirmedActions[playerId] = action
  5. CHECK FOR LATE INPUT:
     - If frameNumber < this.frameNumber (already simulated past it)
     - AND this.predictedFrames.has(frameNumber) (used prediction)
     - COMPARE prediction vs actual:
       - Look up what we used in actionSequence
       - If different: set this.pendingRollbackFrame
```

**Key insight:** The deduplication in `storeRemoteInput()` handles the dual-path scenario gracefully. If the same input arrives via both SocketIO and P2P, the second one is silently ignored. This makes the transition to P2P-first low-risk.

### Rollback Trigger Flow

```
storeRemoteInput() detects late input that differs from prediction
  -> sets this.pendingRollbackFrame

step() (lines 1222-1234):
  if (this.pendingRollbackFrame !== null):
    -> performRollback(rollbackFrame, playerIds)

performRollback() (lines 2213-2360):
  1. Find best snapshot: findBestSnapshot(targetFrame)
  2. Load snapshot: loadStateSnapshot(snapshotFrame)
  3. Replay frames from snapshotFrame to currentFrame
     - getInputsForFrame(frame, playerIds, trackPredictions=false)
     - stepWithActions() for each frame
```

## Host vs Symmetric Peer Analysis

### Current "Host" Usage

The codebase has two different "host" concepts:

**1. Server-Side Host (pyodide_game_coordinator.py)**
```python
# Line 204-206: First player becomes host
if game.host_player_id is None:
    game.host_player_id = player_id
```

**2. Client-Side isHost Flag (pyodide_multiplayer_game.js)**
```javascript
// Line 443: Received from server
this.isHost = data.is_host;

// Line 1212-1216: Used for P2P state sync broadcasts
if (!this.serverAuthoritative && this.isHost) {
    if (this.frameNumber - this.lastP2PSyncFrame >= this.p2pSyncInterval) {
        await this.broadcastP2PStateSync();
    }
}
```

### Analysis: What "Host" Actually Controls

| Feature | Uses isHost | Symmetric Safe? |
|---------|-------------|-----------------|
| P2P state hash broadcast | Yes (line 1212) | NO - only host broadcasts |
| Data logging (historical) | No longer used | N/A |
| GGPO rollback | NO | YES - both peers rollback independently |
| Input buffer | NO | YES - identical on both peers |
| State snapshots | NO | YES - saved locally on each peer |
| Server-authoritative sync | NO | YES - server is authoritative, not host |

**Conclusion:** The `isHost` flag is ONLY used for P2P state sync in non-server-authoritative mode. For symmetric peers, BOTH clients should broadcast their state hash periodically (or use a different sync mechanism).

### Required Changes for Symmetric Peers

1. **Remove host-dependent P2P sync broadcasting** - Either:
   - Both peers broadcast state hashes (with timestamp/frame-based deduplication)
   - OR neither broadcasts (rely on server-authoritative mode)

2. **Verify symmetric behavior:**
   - `storeRemoteInput()` - already symmetric (same on both peers)
   - `getInputsForFrame()` - already symmetric (same prediction logic)
   - `performRollback()` - already symmetric (each peer rolls back independently)
   - State snapshots - already symmetric (saved locally)

## P2P-First vs Dual-Path Strategy

### Current: Dual-Path (Send via Both)

```javascript
// Lines 1107-1119 in step()
socket.emit('pyodide_player_action', {...});  // Always sent

if (this.p2pConnected && this.p2pInputSender) {
    this.p2pInputSender.recordAndSend(myCurrentAction, targetFrame);  // Also sent if P2P up
}
```

**Pros:**
- Redundancy if P2P fails silently
- Server always has input history
- Trivial to implement (already done)

**Cons:**
- Server bandwidth used even when P2P works
- P2P is secondary, not proving it works as primary

### Target: P2P-First with SocketIO Fallback

```javascript
// Proposed change
if (this.p2pConnected && this.p2pInputSender) {
    // Primary: send via P2P
    const sent = this.p2pInputSender.recordAndSend(myCurrentAction, targetFrame);
    if (!sent) {
        // P2P send failed (buffer congested, channel closed)
        this._sendViaSocketIO(myCurrentAction, targetFrame);
    }
} else {
    // No P2P connection: use SocketIO
    this._sendViaSocketIO(myCurrentAction, targetFrame);
}
```

**For Phase 3, recommend:** Keep dual-path initially, add metrics to prove P2P is working, then remove SocketIO send in later phase. This de-risks the transition.

## SocketIO Fallback Implementation

### Fallback Trigger Conditions

When should we switch from P2P to SocketIO?

| Condition | Detection Method | Threshold |
|-----------|------------------|-----------|
| DataChannel closed | `onDataChannelClose` callback | Immediate |
| Connection failed | `onConnectionFailed` callback | Immediate |
| High RTT | `connectionHealth.rttTracker.getAverageRTT()` | > 300ms sustained |
| High packet loss | Gap detection in `connectionHealth` | > 20% frames missing |
| Buffer congestion | `dataChannel.bufferedAmount` | > 32KB sustained |

### Fallback Mechanism (Already Partially Exists)

```javascript
// Current: send via both (lines 1107-1119)
// If P2P fails, SocketIO still works

// For explicit fallback:
_onP2PConnectionLost() {
    console.warn('[P2P] Connection lost, switching to SocketIO-only');
    this.p2pConnected = false;

    // Clear P2P state
    this._stopPingInterval();
    this.p2pInputSender = null;

    // SocketIO path continues working automatically
    // No explicit "switch" needed - p2pConnected check fails, SocketIO always sent
}
```

### Fallback for Mid-Game P2P Loss

The current dual-path architecture makes this trivial:
- If P2P drops mid-game, `p2pConnected` becomes false
- SocketIO path continues (was always active)
- Remote peer receives inputs via SocketIO relay
- No rollback needed (just increased latency)

**Key insight:** The requirement "SocketIO fallback activates if P2P connection fails during gameplay" is already satisfied by the dual-path approach. The "activation" is simply `p2pConnected` becoming false.

## State Hash Verification with P2P

### Current Server-Authoritative Path

```javascript
// Line 594-662: socket.on('server_authoritative_state', ...)
// Server broadcasts state periodically
// Client computes hash, compares, applies corrections
```

### Current P2P Hash Sync Path

```javascript
// Line 515-590: socket.on('p2p_state_sync', ...)
// Only in non-serverAuthoritative mode
// Host broadcasts, non-host compares

// Line 1212-1216: Host broadcasts
if (!this.serverAuthoritative && this.isHost) {
    await this.broadcastP2PStateSync();
}
```

### Symmetric P2P Hash Sync

For symmetric peers without a host, options:

**Option A: Both Broadcast (Simple)**
```javascript
// Both peers broadcast state hash every N frames
// Each peer compares received hash against local
// If mismatch: log warning, trigger resync mechanism
```

**Option B: Deterministic Broadcaster (Frame-Based)**
```javascript
// At frame N: if (N % syncInterval == 0 && shouldBroadcast(N))
// Use frame number to determine who broadcasts
// E.g., even frames = player 0, odd frames = player 1
```

**Option C: Request-Response**
```javascript
// Either peer can request: "give me your hash for frame N"
// Response includes hash and optionally full state for correction
```

**Recommendation:** Start with Option A (both broadcast). Simpler, symmetric by design, and hash comparison is cheap.

## Standard Stack

### Core (Already Implemented)
| Component | Location | Purpose |
|-----------|----------|---------|
| GGPO Rollback | `pyodide_multiplayer_game.js` | Prediction, rollback, replay |
| WebRTCManager | `webrtc_manager.js` | DataChannel lifecycle |
| Binary Protocol | `encodeInputPacket/decodeInputPacket` | Compact input serialization |
| P2PInputSender | `pyodide_multiplayer_game.js` | Redundant input sending |

### Supporting
| Component | Purpose | Already Exists |
|-----------|---------|----------------|
| RTTTracker | Latency measurement | Yes (line 135) |
| ConnectionHealthMonitor | Connection quality | Yes (line 185) |
| State Snapshots | Rollback state | Yes (line 2079) |

## Architecture Patterns

### Pattern 1: Deduplication at Store (Already Implemented)

The `storeRemoteInput()` function (lines 1902-1969) already handles duplicates:

```javascript
// If we already have an input for this player at this frame, ignore
if (frameInputs.has(playerIdStr)) {
    return;  // Duplicate ignored
}
```

This enables dual-path sending safely.

### Pattern 2: Late Input Detection (Already Implemented)

```javascript
// storeRemoteInput() lines 1937-1966
if (frameNumber < this.frameNumber && this.predictedFrames.has(frameNumber)) {
    // Compare used vs received
    const actionRecord = this.actionSequence.find(r => r.frame === frameNumber);
    if (usedAction !== action) {
        this.pendingRollbackFrame = Math.min(...);
    }
}
```

### Pattern 3: Symmetric Input Buffer

Both peers maintain identical structures:
- `inputBuffer`: Map<frameNumber, Map<playerId, action>>
- `stateSnapshots`: Map<frameNumber, envStateJson>
- `predictedFrames`: Set<frameNumber>

No "authoritative" peer - each applies the same logic.

### Anti-Patterns to Avoid

- **Host-only rollback:** Both peers must rollback independently when predictions are wrong
- **Host-only state verification:** Symmetric peers should both verify
- **Blocking on input arrival:** GGPO predicts; never block the game loop
- **Clearing P2P state on episode reset:** WebRTC connection should persist across episodes

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Input deduplication | Custom tracking | Existing `storeRemoteInput()` check | Already handles duplicates |
| Rollback logic | New rollback system | Existing `performRollback()` | 200+ lines, battle-tested |
| State serialization | Custom format | Existing `get_state()` / `set_state()` | Env already implements |
| Connection health | Manual tracking | Existing `ConnectionHealthMonitor` | Already integrated |

**Key insight:** Phase 3 is primarily a wiring and policy change, not new feature development. The components exist; the task is connecting them correctly.

## Common Pitfalls

### Pitfall 1: Breaking Host-Dependent Features

**What goes wrong:** Removing `isHost` flag breaks P2P state sync
**Why it happens:** State sync broadcast logic depends on `isHost`
**How to avoid:** Replace host-dependent broadcast with symmetric alternative
**Warning signs:** State hashes only computed on one peer

### Pitfall 2: Rollback During Replay

**What goes wrong:** Nested rollbacks, infinite loop
**Why it happens:** Receiving late input during replay triggers new rollback
**How to avoid:** The existing `trackPredictions=false` parameter in `getInputsForFrame()` during replay already prevents this
**Warning signs:** Rollback count increasing during replay

### Pitfall 3: Input Buffer Pruning Before Rollback

**What goes wrong:** Rollback fails because needed inputs were deleted
**Why it happens:** Pruning runs before pending rollback is processed
**How to avoid:** Already handled - `pruneInputBuffer()` called AFTER rollback check in `step()`
**Warning signs:** "No valid snapshot found for rollback"

### Pitfall 4: P2P Reconnection After Close

**What goes wrong:** Stale callbacks, zombie connections
**Why it happens:** WebRTC connection closed but not fully cleaned up
**How to avoid:** Full cleanup in `onDataChannelClose`, set all P2P state to null
**Warning signs:** Multiple DataChannel open logs, duplicate inputs

### Pitfall 5: Desync from Different RNG States

**What goes wrong:** State hashes don't match even with same inputs
**Why it happens:** RNG state not included in state sync, bots produce different actions
**How to avoid:** The existing `saveStateSnapshot()` already saves numpy/Python RNG state
**Warning signs:** Hashes diverge gradually, action counts match

## Code Examples

### Symmetric P2P State Hash Broadcast

Replace host-only broadcast with symmetric version:

```javascript
// New: Both peers broadcast their state hash
async broadcastSymmetricStateSync() {
    try {
        const stateHash = await this.computeQuickStateHash();

        // Send via P2P DataChannel directly (not SocketIO)
        if (this.p2pConnected && this.webrtcManager?.isReady()) {
            const syncPacket = encodeStateSync(
                this.myPlayerId,
                this.frameNumber,
                stateHash
            );
            this.webrtcManager.send(syncPacket);
        }

        this.lastP2PSyncFrame = this.frameNumber;
    } catch (e) {
        console.warn(`[P2P Sync] Failed to broadcast state hash: ${e}`);
    }
}

// New message type for state sync (add to binary protocol)
const P2P_MSG_STATE_SYNC = 0x05;

function encodeStateSync(playerId, frame, hash) {
    // hash is 16 char hex string = 8 bytes as binary
    const buffer = new ArrayBuffer(1 + 2 + 4 + 8);  // 15 bytes
    const view = new DataView(buffer);

    view.setUint8(0, P2P_MSG_STATE_SYNC);
    view.setUint16(1, playerId, false);
    view.setUint32(3, frame, false);

    // Encode hash as 8 bytes (first 16 hex chars)
    for (let i = 0; i < 8; i++) {
        view.setUint8(7 + i, parseInt(hash.substring(i * 2, i * 2 + 2), 16));
    }

    return buffer;
}
```

### P2P-First Input Sending (Future Change)

```javascript
// In step() - change from dual-path to P2P-first
sendInput(action, targetFrame) {
    const p2pSent = this.p2pConnected &&
                    this.p2pInputSender?.recordAndSend(action, targetFrame);

    if (!p2pSent) {
        // Fallback to SocketIO
        socket.emit('pyodide_player_action', {
            game_id: this.gameId,
            player_id: this.myPlayerId,
            action: action,
            frame_number: targetFrame,
            timestamp: Date.now(),
            sync_epoch: this.syncEpoch
        });
    }

    return p2pSent;
}
```

### Connection Health Check for Fallback

```javascript
checkP2PHealth() {
    if (!this.connectionHealth) return { shouldFallback: false };

    const health = this.connectionHealth.getHealthStatus();

    // Criteria for falling back to SocketIO
    const shouldFallback =
        health.status === 'critical' ||
        (health.latency && health.latency > 300) ||
        health.gapCount > this.frameNumber * 0.2;  // >20% frame gaps

    return { shouldFallback, health };
}
```

## Integration Summary

### What Already Works

| Feature | Status | Notes |
|---------|--------|-------|
| P2P input sending | WORKING | `p2pInputSender.recordAndSend()` called in step() |
| P2P input receiving | WORKING | `_handleInputPacket()` calls `storeRemoteInput()` |
| SocketIO parallel path | WORKING | Always sends via server relay |
| GGPO rollback | WORKING | Triggers when late P2P input differs from prediction |
| State snapshots | WORKING | Saved every 5 frames |
| Deduplication | WORKING | `storeRemoteInput()` ignores duplicates |

### What Needs Phase 3 Work

| Change | Effort | Priority |
|--------|--------|----------|
| Remove host-dependent P2P sync | Small | HIGH |
| Add symmetric hash verification | Medium | HIGH |
| Add P2P health monitoring | Small | MEDIUM |
| Add explicit fallback trigger | Small | MEDIUM |
| Add P2P-specific metrics/logging | Small | MEDIUM |

### Files to Modify

| File | Changes |
|------|---------|
| `pyodide_multiplayer_game.js` | Remove isHost check for P2P sync, add symmetric broadcast |

### Success Verification

The success criteria from the phase description:

1. **Two players can complete a full game session with inputs exchanged exclusively via P2P DataChannel**
   - Already possible: P2P path exists, just need to disable SocketIO send for testing
   - Verify: Watch browser console for `[P2P]` logs, not `pyodide_other_player_action`

2. **Neither peer acts as "host" -- both run symmetric simulations**
   - Already true for GGPO: both peers rollback independently
   - Need to fix: P2P state sync currently host-only

3. **Rollback and replay work correctly when remote inputs arrive late**
   - Already working: `storeRemoteInput()` detects late inputs, triggers rollback
   - Verify: Artificially delay P2P packets, watch for `[GGPO] Rolling back` logs

4. **State hash verification detects desyncs**
   - Already working in server-authoritative mode
   - Need to enable for P2P-only mode with symmetric verification

5. **SocketIO fallback activates if P2P connection fails during gameplay**
   - Already works: dual-path means SocketIO is always active
   - Need to add: explicit fallback detection and logging

## Open Questions

1. **Keep dual-path or switch to P2P-first?**
   - Current: Both paths always active
   - Option: P2P-first with fallback
   - Recommendation: Keep dual-path for Phase 3, switch in Phase 4

2. **Server still running in P2P mode?**
   - Server receives inputs but doesn't step environment
   - Could add "P2P-only" mode where server is pure relay
   - Recommendation: Defer to Phase 4

3. **What happens if peers have different frame numbers?**
   - Each peer runs at local FPS
   - Frame drift could cause confusion in state sync
   - Recommendation: Use frame number in state sync, compare only matching frames

## Sources

### Primary (HIGH confidence)
- Existing codebase analysis: `pyodide_multiplayer_game.js` (2677 lines)
- Phase 1 Research: WebRTC foundation patterns
- Phase 2 Research: Binary protocol, redundant sending

### Secondary (MEDIUM confidence)
- [GGPO Developer Guide](https://github.com/pond3r/ggpo/blob/master/doc/DeveloperGuide.md) - Rollback architecture reference
- [INVERSUS Rollback Networking](https://blog.hypersect.com/rollback-networking-in-inversus/) - Symmetric peer patterns

## Metadata

**Confidence breakdown:**
- Input flow analysis: HIGH - Direct code analysis
- GGPO integration: HIGH - Existing code works
- Symmetric peer changes: HIGH - Clear what needs to change
- Fallback mechanism: MEDIUM - Design clear, implementation details need testing
- State hash sync: MEDIUM - Multiple valid approaches

**Research date:** 2026-01-17
**Valid until:** 30 days (implementation phase, may discover edge cases)
