# Phase 2: P2P Transport Layer - Research

**Researched:** 2026-01-16
**Domain:** P2P Input Serialization, Redundant Sending, RTT Measurement
**Confidence:** HIGH

## Summary

This phase builds the message protocol for P2P game input exchange over the WebRTC DataChannel established in Phase 1. The existing GGPO implementation in `pyodide_multiplayer_game.js` already has sophisticated rollback netcode (input buffers, prediction, state snapshots, replay); Phase 2 adds the transport layer that sends/receives inputs directly between peers instead of via the SocketIO server relay.

The primary work involves:
1. Defining a compact binary message format for input packets with frame metadata
2. Implementing redundant input sending (last 3-5 inputs per packet) to handle packet loss without retransmission
3. Adding ping/pong keepalive messages for RTT measurement
4. Modifying `_handleP2PMessage` to deserialize inputs and store them in the existing GGPO input buffer
5. Adding `sendP2PInput()` method called alongside the existing `socket.emit('pyodide_player_action', ...)` call

**Primary recommendation:** Use binary serialization via ArrayBuffer/DataView for input packets (compact, fast) with JSON fallback for test/debug messages. Include the last 3 confirmed inputs in each packet for redundancy against 5% packet loss scenarios.

## Current Input Flow Analysis

### Existing Server-Relay Path (to be replaced in Phase 3)

The current flow in `pyodide_multiplayer_game.js`:

```
step() method:
  1. Get local action from allActionsDict
  2. Store in local input buffer: storeLocalInput(action, frameNumber)
  3. Send to server: socket.emit('pyodide_player_action', {...})
  4. Build finalActions from getInputsForFrame() - uses predictions if remote not arrived
  5. Step environment with finalActions

On receiving 'pyodide_other_player_action':
  1. Extract {player_id, action, frame_number}
  2. Store in buffer: storeRemoteInput(player_id, action, frame_number)
  3. Check for late input -> trigger rollback if prediction was wrong
```

### Key Integration Points

| Location | Current Code | Phase 2 Change |
|----------|--------------|----------------|
| Line 811 | `socket.emit('pyodide_player_action', ...)` | Add parallel `sendP2PInput()` call |
| Line 2167 | `onDataChannelMessage` callback | Parse input messages, call `storeRemoteInput()` |
| Line 2204 | `_handleP2PMessage()` | Add input message type handler |

### Frame Number and Target Frame

The existing code uses **target frame** semantics:
- Local input at frame N is scheduled for frame N + INPUT_DELAY
- `frame_number` in the message is the **target execution frame**, not the capture frame

This is correct for GGPO and must be preserved in the P2P protocol.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| ArrayBuffer/DataView | Browser-native | Binary message serialization | Zero dependencies, fast, compact |
| TextEncoder/TextDecoder | Browser-native | UTF-8 string encoding | Built-in, used for debug/test messages |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| msgpack | Existing in codebase | Complex object serialization | Only if JSON fallback needed for debugging |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Binary ArrayBuffer | JSON.stringify | 3-4x larger packets, slower parsing, but easier debugging |
| Custom binary format | Protocol Buffers | Protobuf overkill for 3 integers; adds build complexity |

**Installation:**
```bash
# No new dependencies - all browser-native APIs
```

## Architecture Patterns

### Recommended Message Type Structure
```
Message Types:
  0x01 = Input packet (primary game data)
  0x02 = Ping (RTT measurement request)
  0x03 = Pong (RTT measurement response)
  0x04 = Keepalive (connection health check)
  0xFF = Debug/test message (JSON-encoded)
```

### Pattern 1: Binary Input Packet Format
**What:** Compact binary encoding for game inputs with redundancy
**When to use:** Every frame for P2P input transmission
**Why:** Minimizes packet size, maximizes throughput

```javascript
// Input Packet Structure (variable length)
// Header: 9 bytes fixed
//   Byte 0:      Message type (0x01 = input)
//   Bytes 1-2:   Player ID (uint16)
//   Bytes 3-6:   Current frame number (uint32, target frame)
//   Byte 7:      Input count (1-5, current + N-1 redundant)
//   Byte 8:      Reserved/flags
// Body: 5 bytes per input
//   Bytes 0-3:   Frame number (uint32)
//   Byte 4:      Action value (uint8 - assumes action space < 256)

// Total typical size: 9 + (5 * 4) = 29 bytes for 4 inputs
// Compare to JSON: {"t":"i","p":0,"f":150,"i":[{...}]} = 50-80 bytes

function encodeInputPacket(playerId, currentFrame, inputs) {
    // inputs = [{frame, action}, ...] - most recent last
    const inputCount = Math.min(inputs.length, 5);
    const buffer = new ArrayBuffer(9 + inputCount * 5);
    const view = new DataView(buffer);

    view.setUint8(0, 0x01);                    // Message type
    view.setUint16(1, playerId);               // Player ID
    view.setUint32(3, currentFrame);           // Current frame (target)
    view.setUint8(7, inputCount);              // Number of inputs
    view.setUint8(8, 0);                       // Reserved

    // Write inputs from oldest to newest
    for (let i = 0; i < inputCount; i++) {
        const offset = 9 + i * 5;
        view.setUint32(offset, inputs[i].frame);
        view.setUint8(offset + 4, inputs[i].action);
    }

    return buffer;
}

function decodeInputPacket(buffer) {
    const view = new DataView(buffer);

    const type = view.getUint8(0);
    if (type !== 0x01) return null;

    const playerId = view.getUint16(1);
    const currentFrame = view.getUint32(3);
    const inputCount = view.getUint8(7);

    const inputs = [];
    for (let i = 0; i < inputCount; i++) {
        const offset = 9 + i * 5;
        inputs.push({
            frame: view.getUint32(offset),
            action: view.getUint8(offset + 4)
        });
    }

    return { playerId, currentFrame, inputs };
}
```

### Pattern 2: Redundant Input Sending
**What:** Include last N inputs in each packet to survive packet loss
**When to use:** Always - packet loss is common with UDP-like DataChannels
**Why:** Eliminates need for retransmission; lost packets don't create gaps

```javascript
// Source: INVERSUS rollback netcode pattern
// https://blog.hypersect.com/rollback-networking-in-inversus/

class P2PInputSender {
    constructor(webrtcManager, myPlayerId, redundancyCount = 3) {
        this.webrtcManager = webrtcManager;
        this.myPlayerId = myPlayerId;
        this.redundancyCount = redundancyCount;

        // Track last N inputs sent for redundancy
        // [{frame, action}, ...] - most recent at end
        this.recentInputs = [];
        this.maxRecentInputs = 10;  // Keep a larger buffer
    }

    recordAndSend(action, targetFrame) {
        // Record this input
        this.recentInputs.push({ frame: targetFrame, action: action });

        // Trim to max size
        if (this.recentInputs.length > this.maxRecentInputs) {
            this.recentInputs.shift();
        }

        // Build redundant input set (current + last N-1)
        const inputsToSend = this.recentInputs.slice(-this.redundancyCount);

        // Encode and send
        const packet = encodeInputPacket(
            this.myPlayerId,
            targetFrame,
            inputsToSend
        );

        this.webrtcManager.send(packet);
    }
}
```

### Pattern 3: Ping/Pong RTT Measurement
**What:** Periodic ping messages to measure round-trip time
**When to use:** Every 500ms or so during gameplay
**Why:** RTT informs adaptive systems, detects connection degradation

```javascript
// Ping packet: 9 bytes
//   Byte 0:      Message type (0x02 = ping)
//   Bytes 1-8:   Timestamp (float64, ms since epoch)

// Pong packet: 9 bytes
//   Byte 0:      Message type (0x03 = pong)
//   Bytes 1-8:   Original timestamp (echo back)

function encodePing() {
    const buffer = new ArrayBuffer(9);
    const view = new DataView(buffer);
    view.setUint8(0, 0x02);
    view.setFloat64(1, performance.now());
    return buffer;
}

function encodePong(originalTimestamp) {
    const buffer = new ArrayBuffer(9);
    const view = new DataView(buffer);
    view.setUint8(0, 0x03);
    view.setFloat64(1, originalTimestamp);
    return buffer;
}

class RTTTracker {
    constructor() {
        this.rttSamples = [];
        this.maxSamples = 10;
        this.lastPingTime = 0;
        this.pingInterval = 500;  // ms
    }

    shouldPing() {
        return performance.now() - this.lastPingTime >= this.pingInterval;
    }

    recordRTT(sentTime) {
        const rtt = performance.now() - sentTime;
        this.rttSamples.push(rtt);
        if (this.rttSamples.length > this.maxSamples) {
            this.rttSamples.shift();
        }
    }

    getAverageRTT() {
        if (this.rttSamples.length === 0) return null;
        return this.rttSamples.reduce((a, b) => a + b) / this.rttSamples.length;
    }

    getLatency() {
        const rtt = this.getAverageRTT();
        return rtt ? rtt / 2 : null;
    }
}
```

### Pattern 4: Connection Health Monitoring
**What:** Track packet loss rate and latency degradation
**When to use:** Continuously during gameplay
**Why:** Enables fallback decisions, user feedback, research logging

```javascript
class ConnectionHealthMonitor {
    constructor() {
        this.expectedPackets = 0;
        this.receivedPackets = 0;
        this.lastReceivedFrame = -1;
        this.gapCount = 0;  // Count of frame gaps (indicates loss)

        // Latency tracking
        this.rttTracker = new RTTTracker();

        // Health thresholds
        this.warningLatencyMs = 100;
        this.criticalLatencyMs = 200;
        this.warningLossRate = 0.05;  // 5%
    }

    recordReceivedInput(frame) {
        this.receivedPackets++;

        if (this.lastReceivedFrame >= 0 && frame > this.lastReceivedFrame + 1) {
            // Gap detected - but redundancy may have filled it
            this.gapCount++;
        }
        this.lastReceivedFrame = Math.max(this.lastReceivedFrame, frame);
    }

    getHealthStatus() {
        const latency = this.rttTracker.getLatency();
        const approxLossRate = this.expectedPackets > 0
            ? 1 - (this.receivedPackets / this.expectedPackets)
            : 0;

        return {
            rtt: this.rttTracker.getAverageRTT(),
            latency: latency,
            estimatedPacketLoss: approxLossRate,
            status: this.determineStatus(latency, approxLossRate)
        };
    }

    determineStatus(latency, lossRate) {
        if (latency > this.criticalLatencyMs || lossRate > 0.10) {
            return 'critical';
        }
        if (latency > this.warningLatencyMs || lossRate > this.warningLossRate) {
            return 'warning';
        }
        return 'good';
    }
}
```

### Anti-Patterns to Avoid
- **Sending only current input:** Packet loss creates irrecoverable gaps; always include redundant inputs
- **Using JSON for input packets:** 3-4x overhead for small fixed-structure data
- **Blocking on missing inputs:** GGPO predicts; don't wait for retransmission
- **Ping flooding:** 500ms interval is sufficient; more frequent wastes bandwidth
- **Ignoring bufferedAmount:** Check before sending to avoid buffer overflow

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Binary serialization | Custom byte packing library | DataView API | Browser-native, well-tested, zero deps |
| RTT measurement | WebRTC getStats() parsing | Simple ping/pong | getStats() is complex and overkill for RTT |
| Packet checksums | Manual CRC calculation | Skip checksums | DTLS already provides integrity; redundant |
| Compression | Custom delta encoding | Send raw inputs | Inputs are tiny (1 byte); compression overhead not worth it |

**Key insight:** The input data is so small (5 bytes per input) that optimization efforts should focus on redundancy and reliability, not compression. The existing GGPO rollback handles late/missing inputs gracefully.

## Common Pitfalls

### Pitfall 1: Sending Before DataChannel Open
**What goes wrong:** Input messages silently dropped, player appears frozen
**Why it happens:** Calling send() before `readyState === 'open'`
**How to avoid:** Check `webrtcManager.isReady()` before sending; queue or fallback to SocketIO if not ready
**Warning signs:** First few frames of inputs don't arrive at peer
**Example fix:**
```javascript
sendP2PInput(action, targetFrame) {
    if (!this.webrtcManager?.isReady()) {
        // Fallback to SocketIO - server relay still works
        return false;
    }
    // ... encode and send via DataChannel
    return true;
}
```

### Pitfall 2: Byte Order Mismatch
**What goes wrong:** Frame numbers corrupted, actions misread
**Why it happens:** Different endianness assumptions between encode/decode
**How to avoid:** Always use DataView (defaults to big-endian) or explicitly specify `littleEndian` parameter
**Warning signs:** Frame numbers are nonsensical, action values wrong
**Example fix:**
```javascript
// Consistent endianness - use default (big-endian) or explicit
view.setUint32(offset, value, false);  // false = big-endian (explicit)
view.getUint32(offset, false);         // Must match!
```

### Pitfall 3: Buffer Overflow from High Send Rate
**What goes wrong:** Packets queued, latency spikes, eventually drops
**Why it happens:** Sending faster than network can transmit; `bufferedAmount` grows
**How to avoid:** Check `bufferedAmount` before sending, skip non-critical packets if congested
**Warning signs:** `bufferedAmount` grows continuously, sudden latency spike
**Example fix:**
```javascript
send(data) {
    if (this.dataChannel.bufferedAmount > 16384) {  // 16KB threshold
        console.warn('[P2P] Buffer congested, skipping packet');
        return false;
    }
    this.dataChannel.send(data);
    return true;
}
```

### Pitfall 4: Storing Redundant Inputs Multiple Times
**What goes wrong:** Same input stored multiple times, action counts wrong, desync
**Why it happens:** Redundant inputs in packets stored without checking if already present
**How to avoid:** `storeRemoteInput()` already checks for duplicates - trust existing logic
**Warning signs:** Action counts don't match between peers
**Example fix:**
```javascript
// Existing storeRemoteInput() has this check:
if (frameInputs.has(playerIdStr)) {
    // Already have confirmed input, ignore duplicate
    return;
}
```

### Pitfall 5: Clock Drift in Ping Timestamps
**What goes wrong:** RTT measurements become increasingly inaccurate
**Why it happens:** Using `Date.now()` which can be adjusted; clocks differ between machines
**How to avoid:** Use `performance.now()` for local timing; don't compare clocks between peers
**Warning signs:** RTT values drift over time or become negative
**Example fix:**
```javascript
// Use performance.now() for high-resolution local timing
const sentTime = performance.now();
// ...
const rtt = performance.now() - sentTime;  // Both are local measurements
```

## Code Examples

### Complete Message Handler Integration
```javascript
// Add to pyodide_multiplayer_game.js _handleP2PMessage()

_handleP2PMessage(data) {
    // Handle both string and ArrayBuffer data
    if (data instanceof ArrayBuffer) {
        this._handleBinaryMessage(data);
        return;
    }

    // Existing JSON handling for test messages
    if (typeof data === 'string') {
        try {
            const message = JSON.parse(data);
            this._handleJsonMessage(message);
        } catch (e) {
            console.error('[P2P] Failed to parse JSON message:', e);
        }
        return;
    }

    console.warn('[P2P] Unknown message type:', typeof data);
}

_handleBinaryMessage(buffer) {
    const view = new DataView(buffer);
    const messageType = view.getUint8(0);

    switch (messageType) {
        case 0x01:  // Input packet
            this._handleInputPacket(buffer);
            break;
        case 0x02:  // Ping
            this._handlePing(buffer);
            break;
        case 0x03:  // Pong
            this._handlePong(buffer);
            break;
        case 0x04:  // Keepalive
            this._handleKeepalive();
            break;
        default:
            console.warn('[P2P] Unknown binary message type:', messageType);
    }
}

_handleInputPacket(buffer) {
    const packet = decodeInputPacket(buffer);
    if (!packet) return;

    // Store all inputs from packet (redundancy handles loss)
    for (const input of packet.inputs) {
        this.storeRemoteInput(
            packet.playerId,
            input.action,
            input.frame
        );
    }

    // Update health monitor
    this.connectionHealth?.recordReceivedInput(packet.currentFrame);
}

_handlePing(buffer) {
    const view = new DataView(buffer);
    const timestamp = view.getFloat64(1);

    // Echo back as pong
    const pong = encodePong(timestamp);
    this.webrtcManager.send(pong);
}

_handlePong(buffer) {
    const view = new DataView(buffer);
    const sentTime = view.getFloat64(1);

    this.connectionHealth?.rttTracker.recordRTT(sentTime);

    const rtt = performance.now() - sentTime;
    if (this.frameNumber % 60 === 0) {
        console.log(`[P2P] RTT: ${rtt.toFixed(1)}ms`);
    }
}
```

### P2P Input Sender Integration
```javascript
// Add to step() method, after the socket.emit() call

// Existing: Send via server relay
socket.emit('pyodide_player_action', {
    game_id: this.gameId,
    player_id: this.myPlayerId,
    action: myCurrentAction,
    frame_number: targetFrame,
    timestamp: Date.now(),
    sync_epoch: this.syncEpoch
});

// NEW: Also send via P2P DataChannel
if (this.p2pConnected && this.p2pInputSender) {
    this.p2pInputSender.recordAndSend(myCurrentAction, targetFrame);
}
```

### Initialization Code
```javascript
// Add to _initP2PConnection() after setting callbacks

this.webrtcManager.onDataChannelOpen = () => {
    console.log('[MultiplayerPyodide] P2P DataChannel OPEN');
    this.p2pConnected = true;

    // Initialize P2P input sending
    this.p2pInputSender = new P2PInputSender(
        this.webrtcManager,
        this.myPlayerId,
        3  // redundancy count
    );

    // Initialize connection health monitoring
    this.connectionHealth = new ConnectionHealthMonitor();

    // Start ping interval
    this._startPingInterval();

    // Send a test message
    this._sendP2PTestMessage();
};

_startPingInterval() {
    this.pingIntervalId = setInterval(() => {
        if (this.webrtcManager?.isReady()) {
            const ping = encodePing();
            this.webrtcManager.send(ping);
            this.connectionHealth?.rttTracker.lastPingTime = performance.now();
        }
    }, 500);  // Every 500ms
}

// Clean up in clearGGPOState or destroy
if (this.pingIntervalId) {
    clearInterval(this.pingIntervalId);
    this.pingIntervalId = null;
}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| JSON serialization | Binary ArrayBuffer | Always better for games | 3-4x smaller packets |
| TCP-style reliability | UDP with redundancy | GGPO (2009+) | No retransmission delay |
| Single input per packet | N redundant inputs | Standard practice | Handles 5-10% packet loss gracefully |

**Deprecated/outdated:**
- Reliable ordered DataChannel for game inputs: Causes head-of-line blocking
- Waiting for ACK before sending next input: Defeats purpose of low-latency

## Open Questions

1. **Optimal redundancy count**
   - What we know: 3-5 inputs is common in fighting games
   - What's unclear: Optimal for this specific game/network profile
   - Recommendation: Start with 3, configurable via `this.redundancyCount`

2. **Fallback trigger threshold**
   - What we know: Should fall back to SocketIO if P2P fails
   - What's unclear: Exact criteria (RTT threshold? Loss rate? Timeout?)
   - Recommendation: Defer to Phase 3; for now, always send via both channels

3. **Input queue growth under high latency**
   - What we know: Redundant inputs could queue up if latency spikes
   - What's unclear: Whether to rate-limit or let GGPO rollback handle it
   - Recommendation: Monitor `bufferedAmount`, log warnings but don't block

## Integration Summary

### Files to Modify

| File | Changes |
|------|---------|
| `pyodide_multiplayer_game.js` | Add P2PInputSender class, modify `_handleP2PMessage()`, add to `step()` |

### New Methods to Add

| Method | Purpose |
|--------|---------|
| `encodeInputPacket()` | Binary encode input packet |
| `decodeInputPacket()` | Binary decode input packet |
| `encodePing()` / `encodePong()` | Ping/pong message encoding |
| `_handleBinaryMessage()` | Route binary messages by type |
| `_handleInputPacket()` | Process received inputs |
| `_handlePing()` / `_handlePong()` | RTT measurement |
| `_startPingInterval()` | Begin periodic pings |

### New Classes to Add

| Class | Purpose |
|-------|---------|
| `P2PInputSender` | Manages redundant input sending |
| `RTTTracker` | Tracks RTT samples and computes averages |
| `ConnectionHealthMonitor` | Tracks packet loss and connection quality |

## Sources

### Primary (HIGH confidence)
- [MDN: RTCDataChannel](https://developer.mozilla.org/en-US/docs/Web/API/RTCDataChannel) - DataChannel API, binaryType, bufferedAmount
- [MDN: ArrayBuffer](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/ArrayBuffer) - Binary data handling
- [MDN: DataView](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/DataView) - Binary serialization

### Secondary (MEDIUM confidence)
- [INVERSUS Rollback Networking](https://blog.hypersect.com/rollback-networking-in-inversus/) - Redundant input pattern, packet structure
- [WebRTC for the Curious](https://webrtcforthecurious.com/docs/07-data-communication/) - Data communication patterns
- [GGPO Developer Guide](https://github.com/pond3r/ggpo/blob/master/doc/DeveloperGuide.md) - Rollback architecture reference
- [WebRTC.link DataChannel Guide](https://webrtc.link/en/articles/rtcdatachannel-usage-and-message-size-limits/) - Message size limits, binary format

### Tertiary (LOW confidence)
- WebSearch results for RTT measurement patterns - needs validation in testing

## Metadata

**Confidence breakdown:**
- Message format: HIGH - Based on MDN DataView/ArrayBuffer documentation
- Redundancy pattern: HIGH - Established pattern from INVERSUS, GGPO ecosystem
- RTT measurement: MEDIUM - Simple ping/pong pattern, untested in this codebase
- Health monitoring: MEDIUM - Thresholds need tuning based on real-world testing
- Integration points: HIGH - Directly analyzed existing pyodide_multiplayer_game.js

**Research date:** 2026-01-16
**Valid until:** 60 days (patterns are stable, no API changes expected)
