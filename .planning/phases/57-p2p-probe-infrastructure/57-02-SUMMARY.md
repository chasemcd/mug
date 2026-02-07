---
phase: 57
plan: 02
subsystem: p2p-probe
tags: [webrtc, probe, rtt, client]
requires:
  - 57-01
provides:
  - ProbeConnection client class
  - ProbeManager client integration
affects:
  - 58-rtt-measurement
  - 59-matchmaker-rtt-integration
tech-stack:
  added: []
  patterns:
    - WebRTC wrapper pattern (ProbeConnection wrapping WebRTCManager)
    - Event-driven probe lifecycle (prepare -> ready -> start -> result)
key-files:
  created:
    - interactive_gym/server/static/js/probe_connection.js
  modified:
    - interactive_gym/server/static/js/index.js
decisions:
  - id: D57-02-01
    choice: "Wrap WebRTCManager rather than duplicate WebRTC logic"
    why: "WebRTCManager already handles ICE, TURN, DataChannel complexity"
  - id: D57-02-02
    choice: "Override _sendSignal to route through probe_signal events"
    why: "Keeps probe signaling separate from game signaling (different event namespace)"
  - id: D57-02-03
    choice: "10 second connection timeout for probes"
    why: "Long enough for TURN fallback, short enough to not block matchmaking"
  - id: D57-02-04
    choice: "500ms delay before RTT measurement after connection"
    why: "Allow connection to stabilize for more accurate getStats() reading"
metrics:
  duration: ~5 minutes
  completed: 2026-02-03
---

# Phase 57 Plan 02: Client-Side Probe Infrastructure Summary

Client-side WebRTC probe wrapper with ProbeManager integration in index.js for P2P RTT measurement during matchmaking.

## What Changed

### New Files

**`interactive_gym/server/static/js/probe_connection.js`**
- `ProbeConnection` class wrapping WebRTCManager for probe-only use
- Uses probe_signal events instead of webrtc_signal for signaling separation
- Connection timeout (10s) prevents hanging probes
- `getRTT()` method uses WebRTC getStats() API for accurate measurement
- Proper cleanup on close() to free RTCPeerConnection resources

### Modified Files

**`interactive_gym/server/static/js/index.js`**
- Import ProbeConnection class
- Add ProbeManager object with full probe lifecycle handling
- Handle probe_prepare: create ProbeConnection, emit probe_ready
- Handle probe_start: start WebRTC connection to peer
- Measure RTT on connection success, report via probe_result event
- ProbeManager.init() called on socket connect with subject_id

## Implementation Details

### ProbeConnection Pattern

```javascript
// ProbeConnection wraps WebRTCManager, overrides signaling path
this.webrtcManager = new WebRTCManager(
    socket,
    probeSessionId,  // Acts as gameId for internal routing
    mySubjectId,     // Acts as playerId
    { turnUsername, turnCredential }
);

// Override _sendSignal to use probe events
this.webrtcManager._sendSignal = (type, payload) => {
    this.socket.emit('probe_signal', {
        probe_session_id: this.probeSessionId,
        target_subject_id: this.peerSubjectId,
        type, payload
    });
};
```

### Probe Lifecycle

```
Server                     Client A                    Client B
   |                          |                           |
   |---- probe_prepare ------>|                           |
   |---- probe_prepare ------------------------------->   |
   |                          |                           |
   |<---- probe_ready --------|                           |
   |<---- probe_ready ----------------------------------- |
   |                          |                           |
   |---- probe_start -------->|                           |
   |---- probe_start --------------------------------->   |
   |                          |                           |
   |                    (WebRTC connection established)   |
   |                          |                           |
   |<---- probe_result -------|  (with rtt_ms)            |
   |<---- probe_result -----------------------------------|
```

## Decisions Made

| Decision | Choice | Rationale |
|----------|--------|-----------|
| WebRTC wrapper | Wrap WebRTCManager | Avoids duplicating ICE/TURN/DataChannel complexity |
| Signaling namespace | probe_signal events | Separates probe traffic from game traffic |
| Connection timeout | 10 seconds | Allows TURN fallback without blocking matchmaking |
| RTT measurement delay | 500ms after connect | Connection stabilization for accurate stats |

## Commits

| Hash | Message |
|------|---------|
| c6081e4 | feat(57-02): create ProbeConnection class for P2P RTT probing |
| 83e63a0 | feat(57-02): integrate ProbeManager into client entry point |

## Deviations from Plan

None - plan executed exactly as written.

## Next Phase Readiness

Phase 58 (RTT Measurement) can now:
- Use client-side probe infrastructure to measure P2P RTT
- Server sends probe_prepare to trigger ProbeConnection creation
- RTT results received via probe_result event

Required before Phase 58:
- Server-side ProbeCoordinator must be integrated (57-01 complete)
- SocketIO handlers for probe events must be registered (57-01 complete)
