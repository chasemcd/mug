---
phase: 58-rtt-measurement
plan: 01
subsystem: p2p-networking
tags: [webrtc, rtt, ping-pong, measurement]

dependency-graph:
  requires:
    - 57-p2p-probe-infrastructure (ProbeConnection, ProbeManager)
  provides:
    - measureRTT ping-pong protocol for reliable application-level RTT measurement
  affects:
    - 59-matchmaker-rtt-integration (will use RTT measurements for match decisions)

tech-stack:
  added: []
  patterns:
    - async ping-pong measurement with per-ping timeout
    - median calculation for stable RTT estimate

file-tracking:
  key-files:
    created: []
    modified:
      - interactive_gym/server/static/js/probe_connection.js
      - interactive_gym/server/static/js/index.js

decisions:
  - id: PING-01
    choice: "JSON message format for ping/pong (not binary)"
    why: "Small payload (seq + ts), simplicity over micro-optimization"
  - id: PING-02
    choice: "5 pings default, 2s timeout per ping, 100ms interval"
    why: "Balance between measurement stability and speed"
  - id: PING-03
    choice: "Median over mean for RTT aggregation"
    why: "Median is robust to outliers (single bad ping won't skew result)"
  - id: PING-04
    choice: "No stabilization delay before ping-pong"
    why: "getStats() needed delay for ICE stats; ping-pong measures directly"

metrics:
  duration: 2min
  completed: 2026-02-03
---

# Phase 58 Plan 01: RTT Ping-Pong Protocol Summary

Reliable application-level RTT measurement using ping-pong messages over WebRTC DataChannel, replacing single-shot getStats() approach.

## What Changed

### Task 1: DataChannel Message Handlers (f40b771)

Added ping/pong message handling to ProbeConnection:

```javascript
// Message format
// Ping: {"type": "ping", "seq": N, "ts": timestamp_ms}
// Pong: {"type": "pong", "seq": N, "ts": original_timestamp_ms}

_handleDataChannelMessage(data) {
    const message = JSON.parse(data);
    if (message.type === 'ping') {
        // Immediately echo back pong with same seq and ts
        this.webrtcManager.dataChannel?.send(JSON.stringify({
            type: 'pong', seq: message.seq, ts: message.ts
        }));
    } else if (message.type === 'pong') {
        // Resolve pending measurement, calculate RTT from Date.now() - sentAt
        const pending = this.pendingPings.get(message.seq);
        if (pending) {
            clearTimeout(pending.timeout);
            const rtt = Date.now() - pending.sentAt;
            pending.resolve(rtt);
        }
    }
}
```

- Added `pendingPings` Map for tracking in-flight measurements
- Added `nextPingSeq` counter for sequence numbers
- Wired up `webrtcManager.onDataChannelMessage` callback

### Task 2: measureRTT Implementation (ac3bd50)

Added configurable ping-pong measurement method:

```javascript
async measureRTT({ numPings = 5, pingTimeout = 2000, pingInterval = 100 } = {}) {
    // Send numPings sequential pings
    // Each with independent timeout
    // Packet loss continues to next ping
    // Returns median of successful measurements (null if all fail)
}

_sendPing(seq, timeout) {
    // Returns Promise that resolves with RTT or rejects on timeout
}
```

Key behaviors:
- Default 5 pings, 2 second timeout per ping, 100ms between pings
- Timed-out pings are logged and skipped (measurement continues)
- Median calculation for final result (robust to outliers)
- Returns null only if ALL pings fail

### Task 3: ProbeManager Integration (dac4042)

Updated `_onProbeConnected` to use new protocol:

```javascript
async _onProbeConnected(probeSessionId) {
    console.log(`[ProbeManager] Probe ${probeSessionId} connected, measuring RTT via ping-pong`);

    // No stabilization delay needed - ping-pong is immediate
    const rtt = await this.activeProbe.measureRTT();

    this.socket.emit('probe_result', {
        probe_session_id: probeSessionId,
        rtt_ms: rtt,
        success: rtt !== null,
    });
}
```

- Removed 500ms stabilization delay (was only needed for getStats())
- measureRTT() handles all logging internally

## Console Log Output

Expected logs during probe measurement:

```
[Probe probe_xxx] DataChannel open
[ProbeManager] Probe probe_xxx connected, measuring RTT via ping-pong
[Probe probe_xxx] Sending ping seq=0
[Probe probe_xxx] Received pong seq=0, RTT=45ms
[Probe probe_xxx] Sending ping seq=1
[Probe probe_xxx] Received pong seq=1, RTT=42ms
...
[Probe probe_xxx] Measurement complete: 5/5 pings, median RTT=44ms
```

If pings timeout:

```
[Probe probe_xxx] Sending ping seq=3
[Probe probe_xxx] Ping seq=3 timed out
[Probe probe_xxx] Sending ping seq=4
...
[Probe probe_xxx] Measurement complete: 3/5 pings, median RTT=48ms
```

## Deviations from Plan

None - plan executed exactly as written.

## Verification Results

| Criterion | Status |
|-----------|--------|
| DataChannel message handler for ping/pong | PASS |
| measureRTT sends configurable pings (default 5) | PASS |
| Each ping has independent timeout (default 2000ms) | PASS |
| Packet loss doesn't fail entire measurement | PASS |
| Median RTT returned via probe_result | PASS |
| Console logs show protocol execution | PASS |

## Files Modified

| File | Changes |
|------|---------|
| `probe_connection.js` | +134 lines: pendingPings, _handleDataChannelMessage, measureRTT, _sendPing |
| `index.js` | -4 lines: simplified _onProbeConnected to use measureRTT |

## Next Phase Readiness

Phase 58-01 provides reliable RTT measurement via ping-pong protocol. Phase 59 can now integrate RTT measurements into matchmaker decisions.

No blockers identified.
