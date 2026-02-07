# Phase 63: Parity Test Stabilization - Research

**Researched:** 2026-02-03
**Domain:** E2E test reliability under packet loss
**Confidence:** HIGH

## Summary

The parity tests validate that both players export identical data under network stress. Phase 61 added input confirmation waiting (500ms timeout) and Phase 62 validated that tests pass. However, `test_active_input_with_packet_loss` remains flaky (~50% failure rate per context) because 500ms may be insufficient under 15% packet loss when inputs are lost near episode boundaries.

The root cause is understood: When the 500ms confirmation timeout expires without receiving partner inputs for the final frames, `_promoteRemainingAtBoundary()` force-promotes speculative (predicted) data. Both players record what they actually executed, which can differ if predictions were wrong.

**Primary recommendation:** Increase the input confirmation timeout to 1000ms (or higher) specifically for packet loss resilience, or implement input re-request mechanism for missing final-frame inputs.

## Standard Stack

### Core Components Already Implemented

| Component | Location | Purpose | Status |
|-----------|----------|---------|--------|
| `_waitForInputConfirmation()` | Line 3010 in pyodide_multiplayer_game.js | Wait for partner inputs before export | Implemented in Phase 61 |
| `inputConfirmationTimeoutMs` | Lines 1320-1324 | Configurable timeout (default 500ms) | Implemented in Phase 61 |
| `_promoteRemainingAtBoundary()` | Line 3068 | Force-promote unconfirmed frames at episode end | Existing from Phase 38 |
| Input redundancy | Line 5594 | 3 inputs per packet for loss recovery | Existing |

### Test Infrastructure

| Component | Location | Purpose |
|-----------|----------|---------|
| `apply_packet_loss()` | `tests/fixtures/network_helpers.py` | CDP-based 15% packet loss simulation |
| `run_comparison()` | `tests/fixtures/export_helpers.py` | Compare exported CSV files |
| `validate_action_sequences.py` | `scripts/` | Detailed parity checking |

## Architecture Patterns

### Current Episode End Flow

```
1. Episode end detected (max_steps or truncated)
2. _broadcastEpisodeEnd() - notify peer
3. _checkEpisodeSyncAndReset() - both peers agree
4. _waitForInputConfirmation(500ms) - poll for missing inputs
5. If timeout: log warning, proceed anyway
6. signalEpisodeComplete()
7. _promoteRemainingAtBoundary() - promotes ALL remaining speculative frames
8. _emitEpisodeDataFromBuffer() - exports data
```

### Why Timeout Causes Divergence

At step 5, when timeout occurs:
- `confirmedFrame` is still behind `targetFrame` (syncedTerminationFrame - 1)
- `speculativeFrameData` contains frames with **predicted** partner inputs
- At step 7, these frames are force-promoted with potentially incorrect data
- Both players export what they actually executed, but the predicted values differ

### Observed Failure Pattern

From context:
- Divergence at row 395 of 450 (near episode end)
- `actions.1` differs: one player recorded action 2, other recorded action 6
- Propagates to `infos.1.direction` for final 5 rows
- Pattern indicates ~55 frames (~5.5 seconds at 10 FPS) of unconfirmed data

## Root Cause Analysis

### Why 500ms May Be Insufficient

1. **15% packet loss is aggressive**: With redundancy of 3 inputs per packet, the probability that all 3 redundant packets for a given input are lost is ~0.3% per input. However, for final frames near episode boundary, there may be fewer subsequent packets to carry redundant copies.

2. **Episode boundary timing**: When episode ends, no more packets are sent. The final frame's input has limited redundancy opportunities since subsequent packets don't exist.

3. **Packet loss + latency compound**: The test applies 50ms latency + 15% loss. Under compound stress, 500ms may not cover:
   - RTT (100ms = 50ms each way)
   - Packet retransmission at WebRTC level (disabled - `maxRetransmits: 0`)
   - Multiple lost packets requiring redundancy

4. **WebRTC is configured for no retransmits**: See line 239 in `webrtc_manager.js`:
   ```javascript
   maxRetransmits: 0  // No retransmits (GGPO handles loss)
   ```
   This means lost packets rely entirely on application-level redundancy.

### Mathematical Analysis of 500ms Timeout

At 10 FPS with 3-input redundancy:
- 1 input every 100ms
- 3 packets needed to guarantee delivery of 1 input
- Time for 3 packets: 300ms
- With 50ms base latency: 300 + 100 = 400ms expected
- With 15% packet loss: P(all 3 lost) = 0.15^3 = 0.003 per input
- For last 5 frames: P(any input lost) = 1 - (0.997)^5 = 1.5%
- But for the FINAL frame specifically: only 1-2 redundant copies possible before episode ends

**The final frame is the vulnerability** - it has limited redundancy since no packets are sent after episode end.

## Options Analysis

### Option 1: Increase Timeout to 1000ms (or 1500ms)

**Approach:** Simply increase `inputConfirmationTimeoutMs` to allow more time for redundant packets.

**Pros:**
- Simplest implementation (single config change)
- Matches existing pattern
- No new code needed

**Cons:**
- Adds 500-1000ms to every episode end (UX impact)
- May still fail under severe packet loss
- Doesn't address the fundamental issue of final-frame vulnerability

**Implementation:**
```python
# In gym_scene.py or test configuration
input_confirmation_timeout_ms=1000  # or 1500
```

**Confidence:** MEDIUM - may still fail occasionally

### Option 2: Implement Input Re-request at Episode Boundary

**Approach:** When timeout starts, actively request missing inputs using existing `INPUT_REQUEST`/`INPUT_RESPONSE` protocol.

**Pros:**
- More robust under severe packet loss
- Actively recovers missing data
- Uses existing P2P message types (Phase 26)

**Cons:**
- More complex implementation
- Requires both peers to respond to requests during episode end
- Round-trip latency added

**Implementation outline:**
```javascript
async _waitForInputConfirmation(timeoutMs) {
    // ... existing polling logic ...

    // After first timeout check, request missing inputs
    if (performance.now() - startTime > timeoutMs / 2) {
        const missingFrames = this._findMissingInputFrames(targetFrame, humanPlayerIds);
        if (missingFrames.length > 0) {
            this._requestMissingInputs(missingFrames);
        }
    }
    // ... continue polling ...
}
```

**Confidence:** HIGH - active recovery is more reliable

### Option 3: Send Additional Redundant Packets at Episode End

**Approach:** When episode end is detected, send extra input packets with higher redundancy specifically for final frames.

**Pros:**
- Proactive rather than reactive
- No round-trip needed
- Final frames get extra protection

**Cons:**
- Requires coordination - both peers must send extra packets
- May send unnecessary data

**Implementation outline:**
```javascript
_broadcastEpisodeEnd() {
    // Send episode end notification
    // ...

    // Send extra redundant input packets for last N frames
    const finalFrameInputs = this.recentInputs.slice(-10);  // Last 10 frames
    for (let i = 0; i < 3; i++) {  // Send 3 times
        this._sendRedundantInputPacket(finalFrameInputs);
    }
}
```

**Confidence:** MEDIUM - depends on timing

### Option 4: Retry-based Confirmation with Exponential Backoff

**Approach:** If initial confirmation fails, retry with progressively longer timeouts.

**Pros:**
- Adapts to network conditions
- Fails fast in good conditions, waits longer when needed

**Cons:**
- More complex logic
- Total timeout may exceed user expectations

**Confidence:** MEDIUM

## Recommended Approach

**Primary: Option 1 (Increase timeout) + Option 2 (Input re-request)**

For Phase 63, focus on stabilization with minimal risk:

1. **Increase timeout to 1000ms** for test reliability
2. **Add optional input re-request** at episode boundary

This two-pronged approach provides:
- Immediate fix via longer timeout (low risk)
- More robust fix via active re-request (higher value)

### Test-Specific Configuration

Consider a separate configuration for test environments:

```python
# In test fixtures or conftest.py
scene.input_confirmation_timeout_ms = 1500  # Higher for tests
```

Or a dedicated test mode:

```javascript
if (this.testMode) {
    this.inputConfirmationTimeoutMs = 1500;
}
```

## Don't Hand-Roll

Problems that have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Missing input detection | Custom gap detection | `_hasAllInputsForFrame()` | Already tracks per-player per-frame |
| Input re-request | New protocol | `INPUT_REQUEST`/`INPUT_RESPONSE` | Phase 26 already implemented this |
| Packet redundancy | Custom buffering | `P2PInputSender.redundancyCount` | Already parameterized |
| CDP packet loss | Custom network simulation | `apply_packet_loss()` | Existing test fixture |

## Common Pitfalls

### Pitfall 1: Changing Only One Side

**What goes wrong:** Fixing timeout on one side doesn't help if the other side exports before receiving confirmation.

**Why it happens:** Both peers independently run `_checkEpisodeSyncAndReset()` and may timeout at different times.

**How to avoid:** Both peers must use the same timeout configuration. The scene metadata already syncs this (`input_confirmation_timeout_ms`).

**Warning signs:** Divergence occurs when one file has real data and one has predicted data.

### Pitfall 2: Re-request During Episode End Race

**What goes wrong:** If input re-request is sent during episode end, the peer may already be resetting and ignore the request.

**Why it happens:** Episode end sync happens before confirmation wait, so peer may be cleaning up state.

**How to avoid:** Input re-request should be sent BEFORE episode end is signaled, or the handler must check for pending requests.

**Warning signs:** Re-requests sent but no responses received.

### Pitfall 3: Timeout Too Short for TURN Relay

**What goes wrong:** TURN relay adds significant latency (50-100ms additional RTT).

**Why it happens:** TURN routes through server, doubling effective latency.

**How to avoid:** Use 1000ms+ timeout which handles TURN scenarios.

**Warning signs:** Failures correlate with TURN connection type (check `p2pMetrics.connectionType`).

### Pitfall 4: Test Flakiness Due to Timing Variance

**What goes wrong:** Test passes sometimes, fails sometimes with same configuration.

**Why it happens:** Packet loss is probabilistic; sometimes final frames get through, sometimes not.

**How to avoid:** Run test 10+ times to validate stability. Use deterministic seed for packet loss simulation if possible.

**Warning signs:** Pass rate is ~50% rather than 0% or 100%.

## Code Examples

### Checking Current Timeout Configuration

```javascript
// In browser console after game starts
console.log(window.game.inputConfirmationTimeoutMs);  // Should be 500 by default
```

### Finding Unconfirmed Frames

```javascript
_findMissingInputFrames(targetFrame, humanPlayerIds) {
    const missing = [];
    for (let frame = this.confirmedFrame + 1; frame <= targetFrame; frame++) {
        if (!this._hasAllInputsForFrame(frame, humanPlayerIds)) {
            missing.push(frame);
        }
    }
    return missing;
}
```

### Sending Input Re-request (Existing Protocol)

```javascript
// From Phase 26 fast-forward implementation
_sendInputRequest(startFrame, count) {
    const packet = new ArrayBuffer(7);
    const view = new DataView(packet);
    view.setUint8(0, P2P_MSG_INPUT_REQUEST);
    view.setUint16(1, startFrame, true);
    view.setUint16(3, count, true);
    view.setUint16(5, this.frameNumber, true);
    this.webrtcManager.send(packet);
}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| No confirmation wait | 500ms confirmation wait | Phase 61 (2026-02-03) | Fixed most parity issues |
| Fixed 500ms timeout | Configurable timeout | Phase 61 | Allows tuning per-environment |
| Force-promote all speculative | Wait then force-promote | Phase 61 | Reduced divergence rate |

**Still needed:**
- Longer timeout for severe packet loss scenarios
- Active re-request for truly lost packets

## Open Questions

1. **Should timeout be configurable per-test or globally?**
   - Current: Global via `input_confirmation_timeout_ms`
   - Recommendation: Keep global, but tests can override via scene config

2. **Is 1000ms acceptable UX for production?**
   - Consider: 500ms base + 500ms only on timeout
   - Or: Shorter initial wait, longer retry with re-request

3. **Should re-request be mandatory or optional?**
   - Conservative: Optional, enabled for tests
   - Aggressive: Always on, minimal overhead

## Success Criteria for Phase 63

Per context requirements:

1. `test_active_input_with_latency[chromium-100]` passes 10 consecutive runs
2. `test_active_input_with_packet_loss` passes 10 consecutive runs
3. No tolerance or xfail markers needed for parity tests

**Test strategy:**
```bash
# Run test 10 times
for i in {1..10}; do
    pytest tests/e2e/test_network_disruption.py::test_active_input_with_packet_loss -v
done

# Or use pytest-repeat
pytest tests/e2e/test_network_disruption.py::test_active_input_with_packet_loss --count=10 -v
```

## Sources

### Primary (HIGH confidence)
- `interactive_gym/server/static/js/pyodide_multiplayer_game.js` - Lines 3010-3056 (`_waitForInputConfirmation`), 7323-7358 (`_checkEpisodeSyncAndReset`)
- `interactive_gym/server/static/js/webrtc_manager.js` - Line 239 (maxRetransmits: 0)
- `.planning/phases/61-input-confirmation-protocol/61-RESEARCH.md` - Root cause analysis

### Secondary (MEDIUM confidence)
- `.planning/phases/62-data-parity-validation/62-VERIFICATION.md` - Test execution evidence
- `.planning/phases/61-input-confirmation-protocol/61-01-SUMMARY.md` - Implementation decisions

### Test Evidence
- Context states `test_active_input_with_packet_loss` has ~50% failure rate
- Divergence pattern: near episode boundary, final 5 frames

## Metadata

**Confidence breakdown:**
- Root cause: HIGH - well documented in Phase 61, code analysis confirms
- Timeout increase: HIGH - simple parameter change, predictable effect
- Input re-request: MEDIUM - uses existing protocol, but integration at episode end is new
- Test stability: MEDIUM - depends on network simulation consistency

**Research date:** 2026-02-03
**Valid until:** 30 days (stable domain, implementation-focused)
