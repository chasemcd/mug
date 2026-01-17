# Architecture Patterns: Browser-Based P2P GGPO Systems

**Domain:** P2P multiplayer with GGPO rollback netcode in browser
**Researched:** 2026-01-16
**Confidence:** MEDIUM (based on existing codebase analysis and established GGPO patterns)

## Executive Summary

Browser-based P2P GGPO systems follow a well-established architecture pattern from fighting games, adapted for web constraints. The system separates concerns into: (1) Transport layer for peer communication, (2) Input synchronization layer for timing/buffering, (3) Simulation layer for deterministic game state, and (4) Rollback layer for misprediction correction.

The existing interactive-gym codebase already implements GGPO fundamentals (input delay, prediction, rollback) in `pyodide_multiplayer_game.js`. The primary architectural change needed is replacing server-relayed communication with true P2P via WebRTC DataChannels.

## Current Architecture Analysis

### Existing Components and Their Roles

```
+-------------------+     SocketIO      +-------------------+
|   Client A        |<----------------->|    Flask Server   |
|                   |                   |                   |
| Pyodide (Python)  |                   | PyodideGame-      |
| GymEnvironment    |                   | Coordinator       |
| GGPO Logic        |                   |                   |
| Phaser Renderer   |<----------------->| ServerGameRunner  |
+-------------------+     SocketIO      | (optional)        |
                                        +-------------------+
                                               ^
                                               | SocketIO
                                               v
+-------------------+
|   Client B        |<------------------+
|                   |
| Pyodide (Python)  |
| GymEnvironment    |
| GGPO Logic        |
| Phaser Renderer   |
+-------------------+
```

**Current Data Flow:**
1. Client A captures input, schedules for frame N+INPUT_DELAY
2. Client A sends action to server via `pyodide_player_action` SocketIO event
3. Server relays to Client B via `pyodide_other_player_action`
4. Both clients execute same action on target frame (or predict + rollback)

**Latency Path (Current):**
```
Input -> Client A -> Server -> Client B
         ~0ms        50-100ms   50-100ms
Total: 100-200ms RTT for action to reach peer
```

### What Already Works Well

| Component | Location | Status |
|-----------|----------|--------|
| GGPO Input Delay | `pyodide_multiplayer_game.js:INPUT_DELAY` | Complete |
| Frame-indexed Input Buffer | `pyodide_multiplayer_game.js:inputBuffer` | Complete |
| State Snapshots | `pyodide_multiplayer_game.js:stateSnapshots` | Complete |
| Rollback/Replay | `pyodide_multiplayer_game.js:performRollback()` | Complete |
| Prediction Logic | `pyodide_multiplayer_game.js:getPredictedAction()` | Complete |
| Hash-based Desync Detection | `pyodide_multiplayer_game.js:computeQuickStateHash()` | Complete |
| Deterministic Environments | `env.get_state()`, `env.set_state()` | Required by env |

### What Needs to Change

| Current | Target | Impact |
|---------|--------|--------|
| Server-relayed actions | P2P DataChannel | New component |
| SocketIO signaling only | SocketIO signaling + WebRTC data | Transport change |
| Implicit host (first joiner) | Symmetric peers | Remove host concept |
| Server state authority | Peer consensus or no authority | Mode selection |

---

## Target Architecture: P2P GGPO

### Component Diagram

```
+---------------------------+          WebRTC          +---------------------------+
|       Client A            |<------------------------>|       Client B            |
|                           |       DataChannel        |                           |
| +-------+   +----------+  |                          |  +----------+   +-------+ |
| |Phaser |<->| GGPO     |  |   Signaling (SocketIO)   |  | GGPO     |<->|Phaser | |
| |Render |   | Manager  |<-|------------------------->|->| Manager  |   |Render | |
| +-------+   +----------+  |                          |  +----------+   +-------+ |
|                 |         |                          |         |                 |
|            +----v----+    |                          |    +----v----+            |
|            | Pyodide |    |                          |    | Pyodide |            |
|            |   Env   |    |                          |    |   Env   |            |
|            +---------+    |                          |    +---------+            |
+---------------------------+                          +---------------------------+
         |                                                          |
         |                   +----------------+                     |
         +------------------>|  Flask Server  |<--------------------+
           Signaling only    |  (signaling,   |    Signaling only
                             |  data logging) |
                             +----------------+
```

### Component Boundaries

| Component | Responsibility | Inputs | Outputs |
|-----------|---------------|--------|---------|
| **WebRTCManager** | Establish and manage P2P connections | Signaling messages | DataChannel events |
| **P2PTransport** | Send/receive game data over DataChannels | GGPO messages | Received messages |
| **GGPOManager** | Input synchronization, rollback orchestration | Local inputs, remote inputs | Simulation commands |
| **PyodideEnv** | Deterministic game simulation | Actions per frame | State, render data |
| **SignalingRelay** | WebRTC offer/answer/ICE via server | WebRTC signaling | Forwarded signals |

### Suggested Class/Module Structure

```
interactive_gym/
  server/
    static/js/
      webrtc_manager.js      # NEW: WebRTC connection management
      p2p_transport.js       # NEW: P2P message protocol
      ggpo_manager.js        # REFACTOR: Extract from pyodide_multiplayer_game.js
      pyodide_multiplayer_game.js  # MODIFY: Use P2P instead of server relay
    pyodide_game_coordinator.py  # MODIFY: Add WebRTC signaling handlers
```

---

## Data Flow: P2P GGPO

### Connection Establishment

```
1. Both clients connect to server via SocketIO
2. Server pairs players, assigns game_id
3. Server sends "start_p2p_connection" with peer info
4. Initiator (lower player_id) creates WebRTC offer
5. Offer/answer exchange via SocketIO signaling
6. ICE candidates exchanged via SocketIO
7. DataChannel established
8. Clients confirm ready via "p2p_connected" event
9. Server sends "game_ready" to start simulation
```

### Per-Frame Input Flow

```
Frame N, Client A (local player):

1. Capture input from Phaser (e.g., key press)
2. Schedule input for frame N + INPUT_DELAY
3. Store in local inputBuffer[N + INPUT_DELAY]
4. Send to peer via DataChannel: {type: 'input', frame: N+DELAY, action: X}
5. Check inputBuffer for frame N inputs
6. If both players' inputs available: use confirmed
   Else: use prediction (last confirmed action)
7. Step Pyodide environment with actions
8. Save state snapshot every K frames
9. Render via Phaser
```

### Rollback Flow

```
Late input arrives for frame M (M < current frame N):

1. Receive input via DataChannel: {type: 'input', frame: M, action: X}
2. Store in inputBuffer[M]
3. Check if prediction at frame M was wrong:
   - Look up what we executed at frame M (actionSequence)
   - Compare to confirmed input X
4. If different:
   a. Find nearest snapshot at or before frame M
   b. Load snapshot (env.set_state + RNG restore)
   c. Replay frames M through N-1 with confirmed inputs
   d. Continue simulation
5. If same: no rollback needed
```

### P2P Message Protocol

```javascript
// Input message (most common)
{
  type: 'input',
  frame: number,        // Target frame (with delay applied)
  playerId: string,     // Sender's player ID
  action: any,          // Action value
  timestamp: number     // For diagnostics
}

// State hash verification (periodic)
{
  type: 'state_hash',
  frame: number,
  hash: string          // MD5 of env.get_state()
}

// Full state sync (on desync or join)
{
  type: 'state_sync',
  frame: number,
  state: object,        // env.get_state() result
  rngState: object      // numpy + random state
}

// Keepalive/ping
{
  type: 'ping',
  timestamp: number
}

// Pong response
{
  type: 'pong',
  timestamp: number,
  echoTimestamp: number // Original ping timestamp
}
```

---

## Integration with Existing Codebase

### Files to Modify

| File | Changes |
|------|---------|
| `pyodide_multiplayer_game.js` | Replace server relay with P2P transport; extract GGPO to separate module |
| `pyodide_game_coordinator.py` | Add WebRTC signaling handlers; keep for data logging/fallback |
| `gym_scene.py` | Add `p2p_mode: bool` configuration option |
| `index.js` | Initialize WebRTC connection on `start_game` |
| `socket_handlers.js` | Add handlers for signaling messages |

### New Files to Create

| File | Purpose |
|------|---------|
| `webrtc_manager.js` | WebRTC peer connection lifecycle |
| `p2p_transport.js` | Message serialization, send/receive over DataChannel |
| `ggpo_manager.js` | Extracted GGPO logic (optional refactor) |

### GymScene Configuration

```python
# Existing pattern in gym_scene.py
scene.pyodide(
    run_through_pyodide=True,
    multiplayer=True,
    server_authoritative=False,  # Already exists
    # NEW OPTIONS:
    p2p_mode=True,               # Enable WebRTC P2P
    p2p_turn_servers=[...],      # TURN server config for NAT traversal
    p2p_ice_servers=[...],       # Additional ICE servers
)
```

### Server-Side Signaling

```python
# New handlers in pyodide_game_coordinator.py

@sio.on('webrtc_offer')
def handle_offer(data):
    """Relay WebRTC offer to peer"""
    game_id = data['game_id']
    target_player = data['target_player']
    # Forward to target player's socket

@sio.on('webrtc_answer')
def handle_answer(data):
    """Relay WebRTC answer to peer"""
    # Similar to offer

@sio.on('webrtc_ice')
def handle_ice_candidate(data):
    """Relay ICE candidate to peer"""
    # Forward to target player
```

### Client-Side WebRTC Manager

```javascript
// webrtc_manager.js (new file)

export class WebRTCManager {
    constructor(gameId, playerId, signalingSocket) {
        this.gameId = gameId;
        this.playerId = playerId;
        this.socket = signalingSocket;
        this.peerConnections = new Map();  // peerId -> RTCPeerConnection
        this.dataChannels = new Map();     // peerId -> RTCDataChannel
        this.onMessage = null;             // Callback for received messages
    }

    async connectToPeer(peerId, isInitiator) {
        const pc = new RTCPeerConnection(this.iceConfig);
        this.peerConnections.set(peerId, pc);

        if (isInitiator) {
            const dc = pc.createDataChannel('game', {
                ordered: false,  // UDP-like for lowest latency
                maxRetransmits: 0
            });
            this.setupDataChannel(dc, peerId);
        } else {
            pc.ondatachannel = (event) => {
                this.setupDataChannel(event.channel, peerId);
            };
        }

        // ICE handling...
        // Offer/answer exchange via signaling socket...
    }

    send(peerId, message) {
        const dc = this.dataChannels.get(peerId);
        if (dc && dc.readyState === 'open') {
            dc.send(JSON.stringify(message));
        }
    }

    broadcast(message) {
        for (const peerId of this.dataChannels.keys()) {
            this.send(peerId, message);
        }
    }
}
```

---

## Anti-Patterns to Avoid

### 1. Synchronous State Sync on Every Frame

**What goes wrong:** Sending full state every frame kills performance
**Instead:** Use periodic hash comparison (every ~30 frames), only sync on mismatch

### 2. Blocking on Peer Input

**What goes wrong:** If one peer lags, both freeze (lockstep anti-pattern)
**Instead:** GGPO predicts missing inputs, steps immediately, rollbacks later

### 3. TCP-like Reliable Ordered Channels

**What goes wrong:** Head-of-line blocking causes input bunching
**Instead:** Use unreliable unordered DataChannel for inputs (like UDP)

### 4. Large State in Snapshots

**What goes wrong:** Snapshot serialization becomes bottleneck
**Instead:** Optimize `get_state()` to return minimal JSON-serializable dict

### 5. Ignoring NAT Traversal

**What goes wrong:** P2P fails for many users behind symmetric NAT
**Instead:** Always configure TURN servers as fallback

### 6. Single Point of Trust

**What goes wrong:** If "host" cheats, other players suffer
**Instead:** Either all peers verify (no host) or accept research context (controlled environment)

---

## Build Order and Dependencies

### Phase 1: WebRTC Foundation (Prerequisites: None)

1. Create `webrtc_manager.js` with connection lifecycle
2. Add signaling handlers to `pyodide_game_coordinator.py`
3. Test: Two browsers can establish DataChannel

**Deliverable:** P2P connection works, can send test messages

### Phase 2: P2P Transport Layer (Prerequisites: Phase 1)

1. Create `p2p_transport.js` with message protocol
2. Implement input message serialization
3. Add keepalive/ping for connection health
4. Test: Inputs sent/received over DataChannel

**Deliverable:** Game inputs flow peer-to-peer

### Phase 3: GGPO Integration (Prerequisites: Phase 2)

1. Modify `pyodide_multiplayer_game.js` to use P2P transport
2. Remove server relay path when P2P connected
3. Keep server as fallback when P2P fails
4. Test: Two-player game runs with P2P inputs

**Deliverable:** Full game playable over P2P with GGPO

### Phase 4: Fallback and Resilience (Prerequisites: Phase 3)

1. Add TURN server configuration
2. Implement connection quality monitoring
3. Add automatic fallback to server relay
4. Test: Game continues when P2P degrades

**Deliverable:** Robust multiplayer across network conditions

### Phase 5: N-Player Support (Prerequisites: Phase 4)

1. Extend WebRTCManager for mesh topology
2. Add relay mode for N > 4 players
3. Handle partial mesh (some peers via relay)
4. Test: 3+ player games

**Deliverable:** Scalable P2P topology

---

## Scalability Considerations

| Concern | 2 Players | 4 Players | 8+ Players |
|---------|-----------|-----------|------------|
| Topology | Full mesh | Full mesh | Hybrid (mesh + relay) |
| Connections | 1 | 6 | Too many; use relay server |
| Bandwidth | ~1KB/s | ~3KB/s | Server relays high-volume |
| Latency | Optimal P2P | Acceptable | Variable |
| Rollback complexity | Simple | Moderate | High (consider lockstep) |

### Hybrid Topology for N > 4

```
Players 1-4: Full mesh P2P
Players 5+: Connect to server relay only

Server receives from all, broadcasts to all 5+
Players 1-4 get relay from server for player 5+ actions
```

---

## GGPO Parameter Tuning

| Parameter | Recommended Value | Rationale |
|-----------|-------------------|-----------|
| INPUT_DELAY | 2-3 frames | Balances responsiveness vs rollback frequency |
| snapshotInterval | 5 frames | Every ~167ms at 30fps; memory vs rollback speed |
| maxSnapshots | 30 | ~5 seconds of history; sufficient for typical RTT |
| inputBufferMaxSize | 120 | ~4 seconds; handles connection hiccups |
| pruneThreshold | frameNumber - 60 | ~2 seconds behind current; memory management |

**Tuning Guidelines:**
- Higher INPUT_DELAY = fewer rollbacks but more input lag
- Lower snapshotInterval = faster rollback but more memory
- Adjust based on observed RTT distribution in your user population

---

## Testing Strategy

### Unit Tests

- WebRTC signaling message format
- GGPO input buffer operations
- Rollback/replay determinism
- State hash computation

### Integration Tests

- P2P connection establishment
- Full game loop over DataChannel
- Fallback to server relay
- Reconnection after disconnect

### Load Tests

- Simulate various network conditions (latency, jitter, packet loss)
- Measure rollback frequency at different INPUT_DELAY values
- Test N-player scaling

---

## Sources and Confidence

**HIGH confidence:**
- Existing codebase analysis (`pyodide_multiplayer_game.js` demonstrates working GGPO)
- WebRTC DataChannel is standard browser API (MDN documentation)
- GGPO algorithm is well-documented (original GGPO library, GDC talks)

**MEDIUM confidence:**
- Specific parameter recommendations (would benefit from empirical testing)
- N-player topology thresholds (depends on real-world network conditions)
- TURN server necessity rates (varies by user population)

**Needs validation:**
- Pyodide performance under rapid rollback (many `set_state` calls)
- DataChannel reliability for game inputs in production
- Browser compatibility edge cases

---

*Architecture analysis: 2026-01-16*
