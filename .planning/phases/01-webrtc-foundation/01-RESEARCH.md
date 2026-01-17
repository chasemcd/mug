# Phase 1: WebRTC Foundation - Research

**Researched:** 2026-01-16
**Domain:** WebRTC DataChannel, Browser P2P, SocketIO Signaling
**Confidence:** HIGH

## Summary

This phase establishes the foundational WebRTC infrastructure for peer-to-peer communication between two browser clients. The existing Flask/SocketIO server provides an excellent signaling backbone - we extend it with new events for SDP offer/answer and ICE candidate exchange. The WebRTC API is mature and well-documented across all major browsers since January 2020.

The primary work involves:
1. Creating a new `WebRTCManager` JavaScript class to handle RTCPeerConnection lifecycle
2. Adding SocketIO event handlers on the server to relay signaling messages
3. Establishing an unreliable/unordered DataChannel optimized for game inputs

**Primary recommendation:** Use the native WebRTC API directly (no wrapper libraries). Create a `webrtc_manager.js` module that integrates with the existing SocketIO socket and exposes a clean interface for the multiplayer game code.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Native WebRTC API | Browser-native | RTCPeerConnection, RTCDataChannel | No external dependencies, excellent browser support, full control |
| Flask-SocketIO | Existing | Signaling channel for SDP/ICE | Already in use, bidirectional real-time communication |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| msgpack | Existing | Binary serialization | Already used in codebase; use for DataChannel messages |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Native WebRTC | simple-peer | Simpler API but not maintained (last release 2021), adds abstraction layer |
| Native WebRTC | PeerJS | Higher-level but wants own signaling server, poor SocketIO integration |

**Installation:**
```bash
# No new dependencies required - WebRTC is browser-native
# SocketIO already installed
```

## Architecture Patterns

### Recommended Project Structure
```
interactive_gym/server/static/js/
    webrtc_manager.js        # NEW: WebRTC peer connection lifecycle
    pyodide_multiplayer_game.js  # MODIFY: Use WebRTCManager for P2P
```

### Pattern 1: Signaling via SocketIO
**What:** Server relays WebRTC signaling messages (SDP offer/answer, ICE candidates) between peers without understanding content
**When to use:** Always - peers cannot discover each other without server assistance
**Example:**
```javascript
// Source: MDN WebRTC documentation
// Client sends signaling message to server
socket.emit('webrtc_signal', {
    type: 'offer',
    targetPlayerId: peerId,
    gameId: this.gameId,
    sdp: peerConnection.localDescription
});

// Server relays to target peer (in app.py)
@socketio.on('webrtc_signal')
def handle_webrtc_signal(data):
    target_socket = get_socket_for_player(data['targetPlayerId'], data['gameId'])
    if target_socket:
        socketio.emit('webrtc_signal', data, room=target_socket)
```

### Pattern 2: Trickle ICE
**What:** Send ICE candidates to peer as they are discovered, rather than waiting for all candidates
**When to use:** Always - reduces connection setup time significantly
**Example:**
```javascript
// Source: https://webrtc.org/getting-started/peer-connections
peerConnection.addEventListener('icecandidate', event => {
    if (event.candidate) {
        // Send immediately as discovered
        socket.emit('webrtc_signal', {
            type: 'ice-candidate',
            targetPlayerId: peerId,
            gameId: this.gameId,
            candidate: event.candidate
        });
    }
});
```

### Pattern 3: Initiator/Answerer Role Assignment
**What:** One peer creates the offer (initiator), the other creates the answer
**When to use:** Every connection - WebRTC requires asymmetric roles
**Example:**
```javascript
// Lower player ID is initiator (deterministic, no race condition)
const isInitiator = this.myPlayerId < peerId;

if (isInitiator) {
    // Create offer
    const offer = await peerConnection.createOffer();
    await peerConnection.setLocalDescription(offer);
    socket.emit('webrtc_signal', {
        type: 'offer',
        targetPlayerId: peerId,
        gameId: this.gameId,
        sdp: peerConnection.localDescription
    });
} else {
    // Wait for offer, then create answer
    peerConnection.ondatachannel = (event) => {
        this.setupDataChannel(event.channel, peerId);
    };
}
```

### Pattern 4: Unreliable/Unordered DataChannel for Game Inputs
**What:** Configure DataChannel with `ordered: false, maxRetransmits: 0` for UDP-like behavior
**When to use:** For GGPO input exchange where late inputs are handled by rollback
**Example:**
```javascript
// Source: MDN RTCDataChannel documentation
// Initiator creates the DataChannel
const dataChannel = peerConnection.createDataChannel('game', {
    ordered: false,           // Accept out-of-order delivery
    maxRetransmits: 0         // No retries - GGPO handles via prediction
});

// Configure for binary data
dataChannel.binaryType = 'arraybuffer';
```

### Anti-Patterns to Avoid
- **Waiting for ICE gathering complete:** Delays connection by seconds; use trickle ICE instead
- **Reliable ordered channels for inputs:** Causes head-of-line blocking and input bunching
- **Adding ICE candidates before setRemoteDescription:** Candidates will be silently ignored; buffer until remote description is set
- **Not cleaning up event handlers on close:** Memory leaks and stale callbacks

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| STUN/TURN servers | Self-hosted Coturn | Google STUN + Metered TURN | Ops overhead not justified for research |
| Signaling protocol | Custom WebSocket | Existing SocketIO | Already in use, handles reconnection |
| Connection state machine | Manual state tracking | RTCPeerConnection.connectionState | Browser handles complexity |
| ICE candidate buffering | Manual queue | RTCPeerConnection handles internally | Adding candidates before remote desc is handled |

**Key insight:** The WebRTC API handles most edge cases internally. Trust the browser's implementation for connection establishment; focus custom code on the signaling relay and DataChannel message handling.

## Common Pitfalls

### Pitfall 1: Wrong Order of Async Operations
**What goes wrong:** ICE candidates ignored, connection fails silently
**Why it happens:** `addIceCandidate()` called before `setRemoteDescription()`
**How to avoid:** Always set remote description first; buffer incoming ICE candidates until description is set
**Warning signs:** ICE candidates received but connection stays in "checking" state
**Example fix:**
```javascript
// Buffer candidates until remote description is set
const pendingCandidates = [];

socket.on('webrtc_signal', async (data) => {
    if (data.type === 'ice-candidate') {
        if (peerConnection.remoteDescription) {
            await peerConnection.addIceCandidate(data.candidate);
        } else {
            // Buffer until we have remote description
            pendingCandidates.push(data.candidate);
        }
    } else if (data.type === 'answer') {
        await peerConnection.setRemoteDescription(data.sdp);
        // Flush buffered candidates
        for (const candidate of pendingCandidates) {
            await peerConnection.addIceCandidate(candidate);
        }
        pendingCandidates.length = 0;
    }
});
```

### Pitfall 2: Not Setting Local Description Before Sending
**What goes wrong:** SDP sent without local description set, ICE gathering never starts
**Why it happens:** Sending offer/answer immediately after `createOffer()/createAnswer()`
**How to avoid:** Always call `setLocalDescription()` before sending the SDP
**Warning signs:** No `icecandidate` events fire after creating offer
**Example:**
```javascript
// WRONG
const offer = await peerConnection.createOffer();
socket.emit('webrtc_signal', { type: 'offer', sdp: offer });

// CORRECT
const offer = await peerConnection.createOffer();
await peerConnection.setLocalDescription(offer);  // REQUIRED before sending
socket.emit('webrtc_signal', { type: 'offer', sdp: peerConnection.localDescription });
```

### Pitfall 3: Closing Call on "disconnected" State
**What goes wrong:** Connection dropped prematurely during temporary network issues
**Why it happens:** Treating `disconnected` ICE state as terminal failure
**How to avoid:** Only close on `failed` or `closed` states; `disconnected` can recover
**Warning signs:** Brief network hiccups end the game immediately

### Pitfall 4: DataChannel Readiness Check
**What goes wrong:** `send()` fails with error or silently drops data
**Why it happens:** Sending before DataChannel `readyState === 'open'`
**How to avoid:** Wait for `onopen` event or check `readyState` before every send
**Warning signs:** First few messages don't arrive, or error logged
**Example:**
```javascript
send(message) {
    if (this.dataChannel && this.dataChannel.readyState === 'open') {
        this.dataChannel.send(msgpack.encode(message));
        return true;
    }
    console.warn('DataChannel not ready, dropping message');
    return false;
}
```

### Pitfall 5: Memory Leaks on Disconnect
**What goes wrong:** Event handlers accumulate, multiple connections created
**Why it happens:** Not removing event listeners when connection closes
**How to avoid:** Remove all handlers in cleanup function, set references to null
**Warning signs:** Performance degrades after multiple game sessions

## Code Examples

Verified patterns from official sources:

### Complete WebRTCManager Class Structure
```javascript
// Source: Pattern derived from MDN examples and webrtc.org
export class WebRTCManager {
    constructor(socket, gameId, myPlayerId) {
        this.socket = socket;
        this.gameId = gameId;
        this.myPlayerId = myPlayerId;

        this.peerConnection = null;
        this.dataChannel = null;
        this.pendingCandidates = [];

        this.onDataChannelOpen = null;    // Callback when ready
        this.onDataChannelMessage = null; // Callback for messages
        this.onDataChannelClose = null;   // Callback when closed
        this.onConnectionFailed = null;   // Callback for failure

        this.setupSignalingHandlers();
    }

    setupSignalingHandlers() {
        this.socket.on('webrtc_signal', (data) => this.handleSignal(data));
    }

    async handleSignal(data) {
        // Handle offer, answer, ice-candidate
        // See detailed implementation below
    }

    async connectToPeer(peerId) {
        this.createPeerConnection(peerId);

        const isInitiator = this.myPlayerId < peerId;

        if (isInitiator) {
            this.dataChannel = this.peerConnection.createDataChannel('game', {
                ordered: false,
                maxRetransmits: 0
            });
            this.setupDataChannel(this.dataChannel);

            const offer = await this.peerConnection.createOffer();
            await this.peerConnection.setLocalDescription(offer);
            this.sendSignal(peerId, 'offer', this.peerConnection.localDescription);
        }
        // Answerer waits for ondatachannel event
    }

    createPeerConnection(peerId) {
        const config = {
            iceServers: [
                { urls: 'stun:stun.l.google.com:19302' },
                { urls: 'stun:stun1.l.google.com:19302' }
            ]
        };

        this.peerConnection = new RTCPeerConnection(config);

        this.peerConnection.onicecandidate = (event) => {
            if (event.candidate) {
                this.sendSignal(peerId, 'ice-candidate', event.candidate);
            }
        };

        this.peerConnection.onconnectionstatechange = () => {
            const state = this.peerConnection.connectionState;
            console.log(`[WebRTC] Connection state: ${state}`);

            if (state === 'failed') {
                this.onConnectionFailed?.();
            }
        };

        this.peerConnection.ondatachannel = (event) => {
            this.dataChannel = event.channel;
            this.setupDataChannel(this.dataChannel);
        };
    }

    setupDataChannel(dc) {
        dc.binaryType = 'arraybuffer';

        dc.onopen = () => {
            console.log('[WebRTC] DataChannel open');
            this.onDataChannelOpen?.();
        };

        dc.onmessage = (event) => {
            this.onDataChannelMessage?.(event.data);
        };

        dc.onclose = () => {
            console.log('[WebRTC] DataChannel closed');
            this.onDataChannelClose?.();
        };

        dc.onerror = (error) => {
            console.error('[WebRTC] DataChannel error:', error);
        };
    }

    sendSignal(targetPlayerId, type, payload) {
        this.socket.emit('webrtc_signal', {
            type: type,
            targetPlayerId: targetPlayerId,
            gameId: this.gameId,
            payload: type === 'ice-candidate' ? payload : payload
        });
    }

    send(message) {
        if (this.dataChannel?.readyState === 'open') {
            this.dataChannel.send(message);
            return true;
        }
        return false;
    }

    close() {
        if (this.dataChannel) {
            this.dataChannel.close();
            this.dataChannel = null;
        }
        if (this.peerConnection) {
            this.peerConnection.close();
            this.peerConnection = null;
        }
        this.pendingCandidates = [];
    }
}
```

### Server-Side Signaling Handler (Python)
```python
# Source: Integration pattern for Flask-SocketIO
# Add to app.py or new webrtc_signaling.py

@socketio.on('webrtc_signal')
def handle_webrtc_signal(data):
    """
    Relay WebRTC signaling messages between peers.

    Does NOT inspect or modify the payload - just routes to target.
    """
    game_id = data.get('game_id')
    target_player_id = data.get('targetPlayerId')
    signal_type = data.get('type')

    # Get the game to find target's socket
    if PYODIDE_COORDINATOR is None:
        logger.warning("WebRTC signal received but no coordinator")
        return

    game = PYODIDE_COORDINATOR.games.get(game_id)
    if game is None:
        logger.warning(f"WebRTC signal for unknown game {game_id}")
        return

    target_socket = game.players.get(target_player_id)
    if target_socket is None:
        logger.warning(f"WebRTC signal for unknown player {target_player_id}")
        return

    # Get sender's player ID from their socket
    sender_socket = flask.request.sid
    sender_player_id = None
    for pid, sid in game.players.items():
        if sid == sender_socket:
            sender_player_id = pid
            break

    # Forward signal with sender info
    socketio.emit('webrtc_signal', {
        'type': signal_type,
        'fromPlayerId': sender_player_id,
        'gameId': game_id,
        'payload': data.get('payload')
    }, room=target_socket)

    logger.debug(
        f"Relayed WebRTC {signal_type} from player {sender_player_id} "
        f"to player {target_player_id} in game {game_id}"
    )
```

### Handling Signaling Messages (Complete)
```javascript
// Source: Derived from MDN Signaling and Video Calling guide
async handleSignal(data) {
    const { type, fromPlayerId, payload } = data;

    // Ignore our own messages
    if (fromPlayerId === this.myPlayerId) return;

    console.log(`[WebRTC] Received ${type} from player ${fromPlayerId}`);

    switch (type) {
        case 'offer':
            // Create connection if we don't have one
            if (!this.peerConnection) {
                this.createPeerConnection(fromPlayerId);
            }

            // Set remote description (the offer)
            await this.peerConnection.setRemoteDescription(
                new RTCSessionDescription(payload)
            );

            // Flush any buffered ICE candidates
            for (const candidate of this.pendingCandidates) {
                await this.peerConnection.addIceCandidate(candidate);
            }
            this.pendingCandidates = [];

            // Create and send answer
            const answer = await this.peerConnection.createAnswer();
            await this.peerConnection.setLocalDescription(answer);
            this.sendSignal(fromPlayerId, 'answer', this.peerConnection.localDescription);
            break;

        case 'answer':
            await this.peerConnection.setRemoteDescription(
                new RTCSessionDescription(payload)
            );

            // Flush buffered candidates
            for (const candidate of this.pendingCandidates) {
                await this.peerConnection.addIceCandidate(candidate);
            }
            this.pendingCandidates = [];
            break;

        case 'ice-candidate':
            if (this.peerConnection?.remoteDescription) {
                await this.peerConnection.addIceCandidate(
                    new RTCIceCandidate(payload)
                );
            } else {
                // Buffer until remote description is set
                this.pendingCandidates.push(new RTCIceCandidate(payload));
            }
            break;
    }
}
```

### Test Message Exchange
```javascript
// Simple test to verify DataChannel works
// Add to WebRTCManager or test separately

testConnection() {
    if (!this.dataChannel || this.dataChannel.readyState !== 'open') {
        console.error('[WebRTC] DataChannel not open for test');
        return false;
    }

    const testMessage = {
        type: 'test',
        timestamp: Date.now(),
        playerId: this.myPlayerId
    };

    this.send(JSON.stringify(testMessage));
    console.log('[WebRTC] Sent test message');
    return true;
}

// In setupDataChannel:
dc.onmessage = (event) => {
    const data = event.data;

    // Handle test messages
    if (typeof data === 'string') {
        try {
            const msg = JSON.parse(data);
            if (msg.type === 'test') {
                console.log(`[WebRTC] Test message received from player ${msg.playerId}`);
                return;
            }
        } catch (e) {
            // Not JSON, treat as binary
        }
    }

    this.onDataChannelMessage?.(data);
};
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Callback-based API | Promise-based API | ~2020 | All methods return Promises, cleaner async |
| addStream() | addTrack() | 2018 | addStream deprecated, use addTrack for media |
| Plan B SDP | Unified Plan SDP | Chrome 72+ | Default SDP format changed |

**Deprecated/outdated:**
- `RTCPeerConnection.addStream()`: Deprecated; use `addTrack()` for media (not applicable for DataChannel-only)
- Callback-style `createOffer(success, failure)`: Use Promise-based `createOffer()`

## Open Questions

Things that couldn't be fully resolved:

1. **TURN server selection**
   - What we know: Metered.ca and Twilio are common providers
   - What's unclear: Current pricing, free tier limits
   - Recommendation: Defer TURN to Phase 4; use only STUN for Phase 1

2. **ICE restart behavior under network change**
   - What we know: `restartIce()` method exists
   - What's unclear: Whether to restart automatically or notify user
   - Recommendation: Log disconnections for now, implement restart in Phase 4

3. **Connection timeout threshold**
   - What we know: ICE gathering can take 5-30 seconds
   - What's unclear: Optimal timeout before falling back to SocketIO
   - Recommendation: Start with 10-second timeout, tune based on testing

## Integration Points

### Existing Code to Extend

1. **`pyodide_game_coordinator.py`**
   - Add `webrtc_signal` SocketIO event handler
   - Store peer connection state if needed for debugging

2. **`pyodide_multiplayer_game.js`**
   - Import and instantiate `WebRTCManager`
   - Call `connectToPeer()` after `pyodide_game_ready` event
   - Replace server-relay with DataChannel when connected

### Trigger Points

1. **When to initiate P2P connection:**
   - After both players join game (`pyodide_game_ready` event)
   - Server broadcasts "establish P2P" signal to both clients

2. **When DataChannel is ready:**
   - `onDataChannelOpen` callback fires
   - Set flag `this.p2pConnected = true`
   - Can begin sending inputs via P2P instead of SocketIO

## Browser Compatibility

WebRTC DataChannel baseline support since January 2020:

| Browser | DataChannel | Unreliable Mode | Notes |
|---------|-------------|-----------------|-------|
| Chrome 80+ | Yes | Yes | Reference implementation |
| Firefox 75+ | Yes | Yes | Fully compliant |
| Safari 13+ | Yes | Yes | Some iOS quirks in older versions |
| Edge 80+ (Chromium) | Yes | Yes | Same as Chrome |

**Confidence:** HIGH (verified via [MDN RTCDataChannel](https://developer.mozilla.org/en-US/docs/Web/API/RTCDataChannel))

## Sources

### Primary (HIGH confidence)
- [MDN: RTCPeerConnection](https://developer.mozilla.org/en-US/docs/Web/API/RTCPeerConnection) - Complete API reference
- [MDN: RTCDataChannel](https://developer.mozilla.org/en-US/docs/Web/API/RTCDataChannel) - DataChannel properties and events
- [MDN: Signaling and Video Calling](https://developer.mozilla.org/en-US/docs/Web/API/WebRTC_API/Signaling_and_video_calling) - Complete signaling flow example
- [webrtc.org: Getting Started](https://webrtc.org/getting-started/peer-connections) - Official best practices

### Secondary (MEDIUM confidence)
- Existing codebase analysis (`pyodide_multiplayer_game.js`, `pyodide_game_coordinator.py`)
- Prior stack research (`.planning/research/STACK.md`)

### Tertiary (LOW confidence)
- WebSearch results for error recovery patterns - would benefit from more testing

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Browser-native API, well-documented, in use since 2020
- Architecture: HIGH - Patterns derived from official MDN examples
- Pitfalls: HIGH - Well-documented common issues
- Code examples: MEDIUM - Synthesized from multiple sources, untested in this codebase

**Research date:** 2026-01-16
**Valid until:** 60 days (WebRTC API stable, no major changes expected)
