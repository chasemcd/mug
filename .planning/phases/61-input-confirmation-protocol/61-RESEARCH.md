# Phase 61 Research: Input Confirmation Protocol

**Researched:** 2026-02-03
**Domain:** GGPO input confirmation at episode boundaries
**Confidence:** HIGH

## Summary

The root cause of the data parity bug is well understood: `_promoteRemainingAtBoundary()` force-promotes speculative frame data at episode end regardless of whether all inputs have been confirmed. Under packet loss with active inputs, rollback replay may use **predicted** actions if confirmed inputs have not arrived yet. Both players record what they actually executed, which can differ.

The fix is to **wait for input confirmation** before calling `signalEpisodeComplete()`. This requires adding a confirmation wait step in the episode end synchronization flow (`_checkEpisodeSyncAndReset()`), with a configurable timeout for graceful degradation under extreme network conditions.

**Primary recommendation:** Add confirmation waiting logic between episode end sync and `signalEpisodeComplete()`, with configurable timeout (default 500ms for 200ms+ RTT scenarios).

## Current Implementation

### Episode Boundary Handling

The current episode end flow is:

```
1. Episode end detected (terminated/truncated/max_steps)
2. _broadcastEpisodeEnd() - notify peer, wait for peer's episode end
3. _checkEpisodeSyncAndReset() - both peers agree on episode end
4. signalEpisodeComplete() called immediately
5. _promoteRemainingAtBoundary() - force-promotes ALL speculative frames
6. _emitEpisodeDataFromBuffer() - exports data
```

**Problem location:** Step 4 calls `signalEpisodeComplete()` immediately after both peers agree on episode end. But at this point, `confirmedFrame` may still be behind `frameNumber` because:
- Input packets sent by peer have not arrived yet (in-flight)
- Under packet loss, some input packets were lost entirely
- The speculative buffer still contains frames with **predicted** partner inputs

**Key code (`_checkEpisodeSyncAndReset()` at line 7257):**
```javascript
_checkEpisodeSyncAndReset() {
    const sync = this.p2pEpisodeSync;

    // Both peers must agree before we can reset
    if (!sync.localEpisodeEndDetected || !sync.remoteEpisodeEndReceived) {
        return;  // Still waiting for sync
    }

    // Clear sync state for next episode
    this._clearEpisodeSyncState();

    // Now safe to signal episode complete (which triggers shouldReset)
    this.episodeComplete = true;
    this.signalEpisodeComplete();  // <-- PROBLEM: No confirmation wait
}
```

### Input Confirmation Protocol

Inputs are exchanged via P2P DataChannel using `P2P_MSG_INPUT` packets. The confirmation mechanism works as follows:

1. **Local input stored:** `storeLocalInput()` stores player's input in `inputBuffer` for the target frame
2. **Input sent to peer:** P2P packet sent via WebRTC DataChannel (unreliable delivery)
3. **Remote input received:** `_handleInputPacket()` queues packet, `_processQueuedInputs()` calls `storeRemoteInput()`
4. **Confirmation tracked:** `_updateConfirmedFrame()` scans `inputBuffer` to find highest frame where ALL players have inputs

**Key tracking variables:**
- `confirmedFrame` (line 923): Highest frame with confirmed inputs from ALL players
- `predictedFrames` (line 940): Set of frames where prediction was used
- `inputBuffer` (line 927): Map of frame -> Map of playerId -> action

**Confirmation detection (`_hasAllInputsForFrame()` at line 2907):**
```javascript
_hasAllInputsForFrame(frame, playerIds) {
    const frameInputs = this.inputBuffer.get(frame);
    if (!frameInputs) return false;

    for (const playerId of playerIds) {
        if (!frameInputs.has(String(playerId))) {
            return false;
        }
    }
    return true;
}
```

### Dual-Buffer System

The dual-buffer architecture (Phase 36) prevents rollback data corruption:

1. **Speculative buffer (`speculativeFrameData`):** Stores frame data during step execution
2. **Canonical buffer (`frameDataBuffer`):** Stores confirmed frame data for export

**Normal promotion flow:**
- Data stored in `speculativeFrameData` during `step()`
- `_updateConfirmedFrame()` advances `confirmedFrame` when all inputs received
- `_promoteConfirmedFrames()` moves frames where `frame <= confirmedFrame` to canonical buffer

**Episode boundary flow (current, problematic):**
- `_promoteRemainingAtBoundary()` force-promotes ALL remaining speculative frames
- This includes frames with **predicted** (unconfirmed) partner inputs
- If prediction was wrong (packet loss), exported data differs from what partner exported

### P2P Message Types

Relevant message types for input exchange:

| Type | Constant | Purpose |
|------|----------|---------|
| `P2P_MSG_INPUT` | Binary 0x01 | Input packet with redundant inputs |
| `P2P_MSG_EPISODE_END` | Binary 0x05 | Episode end notification |
| `P2P_MSG_INPUT_REQUEST` | Binary 0x09 | Request missing inputs (fast-forward) |
| `P2P_MSG_INPUT_RESPONSE` | Binary 0x0A | Response with requested inputs |

The `INPUT_REQUEST`/`INPUT_RESPONSE` mechanism already exists for fast-forward recovery (Phase 26). This could potentially be reused for confirmation recovery, but the simpler approach is to wait for in-flight packets.

## Root Cause Analysis

**Scenario causing divergence:**

1. Player A and B both at frame 449 (max_steps=450)
2. Player A presses action 3, sends to B
3. Player B presses action 2, sends to A
4. Both execute frame 449 and detect episode end (max_steps reached)
5. **Packet loss:** A's action 3 packet lost, B's action 2 packet lost
6. Both broadcast episode end and sync
7. `_checkEpisodeSyncAndReset()` triggers `signalEpisodeComplete()` immediately
8. `_promoteRemainingAtBoundary()` promotes frame 449:
   - Player A: used predicted action for B (e.g., action 0)
   - Player B: used predicted action for A (e.g., action 0)
9. Both export, but frame 449 has different actions

**Why waiting helps:**

Input packets are sent with redundancy (multiple recent inputs per packet). Even if one packet is lost, subsequent packets contain the same inputs. A short wait (e.g., 500ms) allows retransmitted/redundant inputs to arrive.

## Proposed Approach

### Strategy: Wait for Confirmation Before Export

Add a confirmation wait phase between episode end sync and `signalEpisodeComplete()`:

```
1. Episode end detected
2. _broadcastEpisodeEnd()
3. _checkEpisodeSyncAndReset() - both peers agree
4. NEW: _waitForInputConfirmation() - wait until confirmedFrame >= syncedTerminationFrame - 1
5. If timeout: log warning, proceed anyway (graceful degradation)
6. signalEpisodeComplete()
7. _promoteRemainingAtBoundary() - now only promotes CONFIRMED frames (or logs if forced)
8. _emitEpisodeDataFromBuffer()
```

### Implementation Details

**1. Add confirmation wait method:**

```javascript
async _waitForInputConfirmation(timeoutMs = 500) {
    const targetFrame = (this.p2pEpisodeSync.syncedTerminationFrame ?? this.frameNumber) - 1;
    const humanPlayerIds = this._getHumanPlayerIds();

    const startTime = performance.now();

    while (performance.now() - startTime < timeoutMs) {
        // Check if all frames up to target are confirmed
        if (this._hasAllInputsForFrame(targetFrame, humanPlayerIds)) {
            // Update confirmedFrame to trigger promotion
            await this._updateConfirmedFrame();
            return true;  // All inputs confirmed
        }

        // Process any pending inputs that arrived
        this._processQueuedInputs();

        // Small delay to allow event loop to process incoming packets
        await new Promise(resolve => setTimeout(resolve, 10));
    }

    // Timeout - log warning but proceed
    console.warn(`[Input Confirmation] Timeout after ${timeoutMs}ms. ` +
        `confirmedFrame=${this.confirmedFrame}, target=${targetFrame}`);
    return false;
}
```

**2. Modify `_checkEpisodeSyncAndReset()`:**

```javascript
async _checkEpisodeSyncAndReset() {
    const sync = this.p2pEpisodeSync;

    if (!sync.localEpisodeEndDetected || !sync.remoteEpisodeEndReceived) {
        return;
    }

    // NEW: Wait for input confirmation before completing episode
    const confirmed = await this._waitForInputConfirmation(this.confirmationTimeoutMs);
    if (!confirmed) {
        // Timeout occurred - data may diverge, logged in _waitForInputConfirmation
    }

    this._clearEpisodeSyncState();
    this.episodeComplete = true;
    this.signalEpisodeComplete();
}
```

**3. Add configurable timeout:**

```javascript
// In constructor, add:
this.confirmationTimeoutMs = config.confirmation_timeout_ms ?? 500;  // Default 500ms
```

**4. Expose configuration in Python:**

```python
# In gym_scene.py or remote_config.py
confirmation_timeout_ms: int = 500  # Phase 61: PARITY-02
```

### Timeout Considerations

**Default timeout: 500ms**
- Handles 200ms+ RTT with margin for packet loss retransmission
- Input packets use redundancy (3 most recent inputs per packet)
- At 10 FPS with 3 inputs/packet, ~300ms of inputs in each packet

**Graceful degradation:**
- Timeout logs warning but proceeds with export
- `_promoteRemainingAtBoundary()` already logs when promoting unconfirmed frames
- No crash or data loss, just potential divergence (same as current behavior)

## Key Files to Modify

| File | Changes |
|------|---------|
| `interactive_gym/server/static/js/pyodide_multiplayer_game.js` | Add `_waitForInputConfirmation()`, modify `_checkEpisodeSyncAndReset()` to be async, add `confirmationTimeoutMs` config |
| `interactive_gym/configurations/remote_config.py` | Add `confirmation_timeout_ms` parameter |
| `interactive_gym/scenes/gym_scene.py` | Expose `confirmation_timeout_ms` in scene config |

### Specific Code Locations

| Function | Line | Change |
|----------|------|--------|
| `_checkEpisodeSyncAndReset()` | 7257 | Make async, add confirmation wait before `signalEpisodeComplete()` |
| `_handleEpisodeEnd()` | 7192 | Ensure it calls updated `_checkEpisodeSyncAndReset()` |
| Constructor | ~900 | Add `this.confirmationTimeoutMs` |
| `_broadcastEpisodeEnd()` | 7243 | Timeout callback needs to handle async |

### Async Considerations

Making `_checkEpisodeSyncAndReset()` async requires updating callers:
- `_handleEpisodeEnd()` (line 7202): Called from message handler, can be async
- `_broadcastEpisodeEnd()` timeout callback (line 7244): Needs to handle promise

## Alternative Approaches Considered

### 1. Re-request lost packets (PARITY-V2-01)

Use existing `INPUT_REQUEST`/`INPUT_RESPONSE` mechanism to explicitly request missing inputs.

**Pros:** More robust under severe packet loss
**Cons:** More complex, adds round-trip latency, requires tracking which inputs are missing
**Decision:** Deferred to v2. Simple waiting handles common cases.

### 2. Block until all inputs confirmed (no timeout)

Wait indefinitely for confirmation.

**Pros:** Guarantees exact parity
**Cons:** Could hang indefinitely if packets truly lost, bad UX
**Decision:** Rejected. Timeout provides graceful degradation.

### 3. Modify promotion to skip unconfirmed frames

Only promote frames where inputs are confirmed.

**Pros:** Never exports predicted data
**Cons:** Missing data is worse than divergent data for research validity
**Decision:** Rejected. Better to have data with divergence flag than missing data.

## Open Questions

1. **Should confirmation wait happen only for P2P mode?**
   - Server-authoritative mode has different sync mechanism
   - Recommendation: Only apply to P2P mode (`!this.serverAuthoritative`)

2. **Should timeout be per-frame or total?**
   - Currently proposed: Total timeout for all remaining frames
   - Alternative: Per-frame timeout (more granular but more complex)
   - Recommendation: Total timeout is simpler and sufficient

3. **Should we add packet loss telemetry?**
   - Useful for diagnosing issues in research deployments
   - Recommendation: Deferred to PARITY-V2-02, not needed for basic fix

## RESEARCH COMPLETE

**Phase:** 61 - Input Confirmation Protocol
**Confidence:** HIGH

### Key Findings

- Root cause confirmed: `_promoteRemainingAtBoundary()` promotes predicted (unconfirmed) data
- Fix is straightforward: Wait for input confirmation before `signalEpisodeComplete()`
- Existing infrastructure (`inputBuffer`, `confirmedFrame`, `_hasAllInputsForFrame()`) supports the fix
- Configurable timeout provides graceful degradation
- No new P2P message types needed

### File Created

`.planning/phases/61-input-confirmation-protocol/61-RESEARCH.md`

### Confidence Assessment

| Area | Level | Reason |
|------|-------|--------|
| Root Cause | HIGH | Direct code analysis, documented in tests |
| Architecture | HIGH | Well-understood dual-buffer system from Phase 36-38 |
| Solution Approach | HIGH | Uses existing confirmation tracking, no new concepts |
| Timeout Strategy | MEDIUM | 500ms default is reasonable but may need tuning |

### Ready for Planning

Research complete. Key implementation points:
1. Add `_waitForInputConfirmation(timeoutMs)` async method
2. Make `_checkEpisodeSyncAndReset()` async, add wait before `signalEpisodeComplete()`
3. Add `confirmationTimeoutMs` config (default 500ms)
4. Expose timeout in Python config
