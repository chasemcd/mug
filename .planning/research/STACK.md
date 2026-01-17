# Technology Stack: P2P GGPO Rollback in Browser

**Project:** Interactive Gym P2P Multiplayer
**Researched:** 2026-01-16
**Confidence:** MEDIUM (WebRTC DataChannel options verified via MDN; GGPO libraries assessed from training knowledge + codebase analysis)

## Executive Summary

The existing codebase already implements GGPO-style rollback netcode in JavaScript (`pyodide_multiplayer_game.js`) with input delay, state snapshots, rollback/replay, and prediction. The missing piece is **true P2P communication via WebRTC DataChannels** to replace SocketIO relay through the server.

**Recommendation:** Use the native WebRTC API directly (no wrapper library) with SocketIO as the signaling channel. This leverages existing infrastructure while adding near-UDP latency for input exchange.

---

## Recommended Stack

### WebRTC Layer (NEW)

| Technology | Version | Purpose | Confidence |
|------------|---------|---------|------------|
| Native WebRTC API | Browser-native | P2P DataChannel connections | HIGH |
| SocketIO | Existing | ICE candidate/SDP signaling | HIGH |
| Metered TURN | Service | NAT traversal fallback | MEDIUM |

**Why native WebRTC instead of a wrapper library:**

1. **Simple-peer**: Popular but not actively maintained (last npm release 2021). The project already has complex networking code; adding another layer of abstraction with uncertain maintenance is risky.

2. **PeerJS**: Higher-level abstraction, but opinionated about signaling (wants its own server). Doesn't integrate well with existing SocketIO infrastructure.

3. **Native API**: Modern browsers have excellent WebRTC support. The API is well-documented, and for this use case (two peers, one DataChannel, known topology) the complexity is manageable. No dependency to maintain.

**WebRTC DataChannel Configuration for Game Inputs:**

```javascript
// Optimal settings for GGPO input exchange
const dataChannelOptions = {
  ordered: false,           // Accept out-of-order (GGPO handles ordering via frame numbers)
  maxRetransmits: 0,        // No retries - if input is late, GGPO handles via prediction
  // Note: maxPacketLifeTime is mutually exclusive with maxRetransmits
};

// Alternative: slightly more reliable
const reliableOptions = {
  ordered: false,
  maxRetransmits: 2,        // Allow 2 retries before giving up
};
```

**Rationale:** GGPO is designed for unreliable transport. Inputs carry frame numbers, so out-of-order delivery is fine. Late inputs trigger rollback, so retransmission is unnecessary (GGPO already predicts and corrects). This matches classic GGPO over UDP.

### STUN/TURN Infrastructure (NEW)

| Provider | Purpose | Cost | Confidence |
|----------|---------|------|------------|
| Google STUN | ICE candidate gathering | Free | HIGH |
| Metered.ca TURN | NAT traversal relay | ~$0.40/GB | MEDIUM |

**ICE Configuration:**

```javascript
const iceConfig = {
  iceServers: [
    // Free STUN servers (sufficient for most connections)
    { urls: 'stun:stun.l.google.com:19302' },
    { urls: 'stun:stun1.l.google.com:19302' },

    // TURN fallback (required for ~15-20% of connections)
    {
      urls: 'turn:relay.metered.ca:443?transport=tcp',
      username: 'YOUR_API_KEY',
      credential: 'YOUR_SECRET'
    }
  ],
  iceCandidatePoolSize: 10  // Pre-gather candidates for faster connection
};
```

**Why TURN is needed:**
- Symmetric NAT (common in corporate networks, mobile carriers) blocks direct P2P
- ~15-20% of connections require TURN relay
- Without TURN: some player pairs will fail to connect entirely
- Cost is minimal for research use case (inputs are small, ~50 bytes/frame)

**TURN Provider Options:**
1. **Metered.ca** (recommended): Pay-as-you-go, easy API, reasonable pricing
2. **Twilio TURN**: More expensive but enterprise support
3. **Self-hosted Coturn**: Free but requires server ops, not recommended for research focus

### Existing Stack (KEEP)

| Technology | Version | Purpose | Notes |
|------------|---------|---------|-------|
| Flask | 2.x | HTTP server, experiment orchestration | No change |
| Flask-SocketIO | Existing | WebSocket signaling for WebRTC | Extend for ICE/SDP |
| Pyodide | Latest stable | Python environment in browser | No change |
| Gymnasium | Latest | RL environment interface | No change |
| Phaser.js | Existing | Game rendering | No change |
| msgpack | Existing | Binary serialization | Use for DataChannel messages |

### GGPO Implementation (EXISTING - ENHANCE)

The codebase already has comprehensive GGPO:

| Feature | File | Status |
|---------|------|--------|
| Input delay (configurable frames) | `pyodide_multiplayer_game.js` | DONE |
| State snapshots with RNG | `pyodide_multiplayer_game.js` | DONE |
| Rollback and replay | `pyodide_multiplayer_game.js` | DONE |
| Prediction (configurable method) | `pyodide_multiplayer_game.js` | DONE |
| Frame-indexed input buffer | `pyodide_multiplayer_game.js` | DONE |
| State hash verification | `pyodide_multiplayer_game.js` | DONE |

**Enhancement needed:** Replace SocketIO input relay with WebRTC DataChannel. The GGPO logic stays the same; only the transport changes.

---

## Integration Architecture

### Signaling Flow (SocketIO)

```
Player A                    Server                     Player B
   |                          |                           |
   |-- join_game ------------>|                           |
   |                          |<--------- join_game ------|
   |                          |                           |
   |<-- webrtc_offer_request -|                           |
   |                          |                           |
   |-- webrtc_offer --------->|-- webrtc_offer ---------->|
   |                          |                           |
   |<-- webrtc_answer --------|<--------- webrtc_answer --|
   |                          |                           |
   |-- ice_candidate -------->|-- ice_candidate --------->|
   |<-- ice_candidate --------|<--------- ice_candidate --|
   |                          |                           |
   |============ WebRTC DataChannel Established ==========|
   |                          |                           |
   |<-- INPUT (P2P) ---------------------------------->---|
```

### Message Format (DataChannel)

```javascript
// Input message (sent every frame)
{
  type: 'input',
  frame: 42,           // Target frame (sender's frame + INPUT_DELAY)
  player: 0,           // Sender's player ID
  action: 3,           // Action value
  ts: 1705408800000    // Timestamp for latency measurement
}

// Optional: State sync for P2P mode (no server authority)
{
  type: 'state_hash',
  frame: 30,
  hash: 'abc123...'    // 16-char MD5 prefix
}
```

**Serialization:** Use msgpack (already in codebase) for smaller messages:
- JSON input message: ~80 bytes
- msgpack input message: ~25 bytes
- At 30 FPS for 2 players: JSON = 4.8 KB/s, msgpack = 1.5 KB/s

---

## What NOT to Use

| Technology | Why Avoid |
|------------|-----------|
| simple-peer | Not actively maintained; adds abstraction layer that complicates debugging |
| PeerJS | Wants own signaling server; doesn't fit existing SocketIO architecture |
| WebSocket for P2P | Not possible; WebSocket is client-server only |
| WebTransport | Newer API with less browser support; WebRTC DataChannel is sufficient |
| GGPO-JS libraries | Existing implementation is already comprehensive and tailored to Pyodide |
| Coturn self-hosted | Operations overhead not justified for research project |

---

## Browser Compatibility

WebRTC DataChannel baseline support since January 2020:

| Browser | DataChannel | Unreliable Mode |
|---------|-------------|-----------------|
| Chrome 80+ | Yes | Yes |
| Firefox 75+ | Yes | Yes |
| Safari 13+ | Yes | Yes |
| Edge 80+ | Yes | Yes |

**Confidence:** HIGH (MDN verified)

---

## Implementation Roadmap Impact

Based on this stack, suggested phase structure:

### Phase 1: WebRTC Signaling Infrastructure
- Add SocketIO events for SDP/ICE exchange
- Server-side `PyodideGameCoordinator` extensions
- Minimal client-side RTCPeerConnection setup

### Phase 2: DataChannel Integration
- Replace SocketIO input relay with DataChannel
- Maintain SocketIO as fallback when P2P fails
- Add connection quality monitoring

### Phase 3: TURN Integration
- Configure TURN credentials
- Implement fallback logic
- Test with various NAT configurations

### Phase 4: Remove Server-Authoritative Dependency
- P2P state hash verification (already exists as `p2p_state_sync`)
- Clean up server-side env runner for pure P2P mode
- Keep server-authoritative as optional mode for research flexibility

---

## Configuration Additions

```python
# New config options for GymScene
class GymScene:
    def p2p_multiplayer(
        self,
        enable_webrtc: bool = True,           # Use WebRTC for input exchange
        turn_server: str | None = None,        # TURN server URL
        turn_credentials: dict | None = None,  # {username, credential}
        fallback_to_socketio: bool = True,     # Fall back if P2P fails
        ice_timeout_ms: int = 5000,            # ICE gathering timeout
    ):
        ...
```

```javascript
// New JS config in MultiplayerPyodideGame
const p2pConfig = {
  enableWebRTC: true,
  iceServers: [...],
  dataChannelOptions: {
    ordered: false,
    maxRetransmits: 0
  },
  fallbackToSocketIO: true,
  connectionTimeout: 5000
};
```

---

## Cost Estimate (Research Use)

| Item | Estimate | Notes |
|------|----------|-------|
| STUN | Free | Google public servers |
| TURN (Metered) | ~$5/month | Assuming 100 sessions @ 10MB each |
| Server hosting | Existing | No change |

---

## Sources

- [MDN: Using WebRTC Data Channels](https://developer.mozilla.org/en-US/docs/Web/API/WebRTC_API/Using_data_channels) - HIGH confidence
- [MDN: RTCDataChannel](https://developer.mozilla.org/en-US/docs/Web/API/RTCDataChannel) - HIGH confidence
- Existing codebase analysis: `pyodide_multiplayer_game.js`, `pyodide_game_coordinator.py` - HIGH confidence
- GGPO principles from training knowledge - MEDIUM confidence (classic algorithm, well-documented)
- TURN provider pricing from training knowledge - LOW confidence (verify current rates)

---

## Open Questions

1. **TURN provider selection:** Need to verify Metered.ca current pricing and evaluate Twilio as alternative
2. **Mobile browser WebRTC:** Safari iOS has some WebRTC quirks; test needed if mobile support matters
3. **N>2 players:** Current design assumes 2-player. Mesh vs. relay topology decision needed for N>2

---

*Stack research: 2026-01-16*
