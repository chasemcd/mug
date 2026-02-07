# Phase 57: P2P Probe Infrastructure - Research

**Researched:** 2026-02-03
**Domain:** WebRTC probe connection lifecycle without game context
**Confidence:** HIGH

## Summary

This phase establishes temporary WebRTC DataChannel connections between matchmaking candidates for RTT measurement BEFORE a game is created. The key insight is that this must work WITHOUT game context - no game_id exists yet, only two subject_ids in the waitroom that the matchmaker wants to probe.

The existing WebRTCManager client-side infrastructure is robust and handles the full connection lifecycle (signaling, ICE, DataChannel). The main challenge is orchestrating probe connections from the server-side matchmaker without coupling to the PyodideGameCoordinator (which requires a game to exist).

**Primary recommendation:** Create a new `ProbeCoordinator` server-side class that manages probe signaling independently of games, and a lightweight `ProbeConnection` client-side class that wraps WebRTCManager for measurement-only use.

## Standard Stack

### Core

The existing stack is already well-suited for this work:

| Component | Location | Purpose | Why Reuse |
|-----------|----------|---------|-----------|
| WebRTCManager | `static/js/webrtc_manager.js` | Full WebRTC connection lifecycle | Battle-tested, handles ICE, TURN, DataChannel |
| SocketIO signaling | `app.py` | SDP/ICE candidate relay | Existing infrastructure, just needs probe routing |
| MatchCandidate | `matchmaker.py` | Participant context | Already has subject_id, can add probe_socket_id |

### New Components Needed

| Component | Location | Purpose |
|-----------|----------|---------|
| ProbeCoordinator | `server/probe_coordinator.py` | Server-side probe signaling orchestration |
| ProbeConnection | `static/js/probe_connection.js` | Client-side probe wrapper around WebRTCManager |

### Dependencies

No new dependencies required. All functionality can be built with existing stack:
- Flask-SocketIO for signaling
- RTCPeerConnection (browser API) via WebRTCManager
- DataChannel (browser API) for RTT ping-pong

## Architecture Patterns

### Recommended Project Structure

```
interactive_gym/server/
  probe_coordinator.py      # NEW: Server-side probe orchestration
  matchmaker.py            # MODIFY: Add probe triggering
  app.py                   # MODIFY: Add probe signaling handlers

interactive_gym/server/static/js/
  probe_connection.js      # NEW: Client-side probe connection
  webrtc_manager.js        # REUSE: No changes needed
```

### Pattern 1: Probe-Game Separation

**What:** Keep probe infrastructure completely separate from game infrastructure
**When to use:** Always - probes must work before any game exists
**Why:** The PyodideGameCoordinator assumes a game_id exists. Probes happen during matchmaking when no game_id exists yet.

```
                    WAITROOM PHASE                           GAME PHASE
                    (no game_id)                             (game_id exists)

Client A  -----> ProbeConnection -----> DataChannel -----> measure RTT
                        |                     |
                        v                     v
Server    <---- ProbeCoordinator <---- signaling  (new)
                        |
                        v
                   Matchmaker (decides: probe these two candidates)

                              AFTER MATCH DECISION:

Client A  -----> WebRTCManager -----> DataChannel -----> game input
                        |                     |
                        v                     v
Server    <---- PyodideGameCoordinator (existing)
```

### Pattern 2: Probe Session ID (unique identifier)

**What:** Since there's no game_id, use a probe_session_id to track probe connections
**When to use:** For all probe operations
**Example:**

```python
# Server side (ProbeCoordinator)
def create_probe_session(subject_id_a: str, subject_id_b: str) -> str:
    """Create a probe session between two candidates."""
    probe_session_id = f"probe_{uuid.uuid4()}"
    self.probe_sessions[probe_session_id] = {
        'subject_a': subject_id_a,
        'subject_b': subject_id_b,
        'socket_a': None,  # Will be populated from PARTICIPANT_SESSIONS
        'socket_b': None,
        'state': 'pending',  # pending -> connecting -> measuring -> complete/failed
        'created_at': time.time(),
    }
    return probe_session_id
```

### Pattern 3: Reuse WebRTCManager with Probe Context

**What:** Create a lightweight wrapper that instantiates WebRTCManager with probe-specific options
**When to use:** Client-side probe initialization
**Why:** Don't duplicate WebRTC logic - WebRTCManager already handles all the complexity

```javascript
// Client side (probe_connection.js)
class ProbeConnection {
    constructor(socket, probeSessionId, mySubjectId, peerSubjectId, options = {}) {
        // Use subject_id comparison for deterministic initiator (same as game connections)
        const isInitiator = mySubjectId < peerSubjectId;

        // Reuse WebRTCManager with probe-specific configuration
        this.webrtcManager = new WebRTCManager(
            socket,
            probeSessionId,  // Use probe_session_id where game_id would go
            mySubjectId,     // Use subject_id where player_id would go
            {
                turnUsername: options.turnUsername,
                turnCredential: options.turnCredential,
                // Probes don't need forceRelay - let them find best path
            }
        );

        // Callback for measurement completion
        this.onMeasurementComplete = null;
        this.onConnectionFailed = null;
    }

    start() {
        // Connect to peer using same deterministic role as game connections
        this.webrtcManager.connectToPeer(this.peerSubjectId);
    }

    close() {
        this.webrtcManager.close();
    }
}
```

### Pattern 4: Probe Signaling Namespace

**What:** Use different SocketIO event names for probe signaling to avoid collision with game signaling
**When to use:** All probe-related signaling
**Why:** Prevents confusion between probe signals and game signals

```python
# Probe signaling events (NEW)
@socketio.on('probe_signal')
def handle_probe_signal(data):
    """Relay WebRTC signals for probe connections."""
    PROBE_COORDINATOR.handle_signal(
        probe_session_id=data.get('probe_session_id'),
        target_subject_id=data.get('target_subject_id'),
        signal_type=data.get('type'),
        payload=data.get('payload'),
        sender_socket_id=flask.request.sid
    )
```

### Anti-Patterns to Avoid

- **Sharing game signaling path:** Don't try to reuse `webrtc_signal` event - it expects game_id and player_id context that probes don't have
- **Creating "fake" games for probes:** Don't create RemoteGameV2 objects just to get a game_id - this pollutes state
- **Embedding probe logic in PyodideGameCoordinator:** Keep probe coordination separate - the coordinator already has too many responsibilities

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| WebRTC connection lifecycle | Custom ICE/SDP handling | WebRTCManager | Handles TURN fallback, ICE restart, candidate buffering |
| Deterministic initiator | Random selection | String comparison of IDs | Already implemented in WebRTCManager._comparePlayerIds() |
| Connection type detection | Custom stats parsing | WebRTCManager.getConnectionType() | Already extracts direct vs relay from getStats() |
| RTT measurement | Custom ping timing | LatencyTelemetry class | Already implements getStats() polling for RTT |

**Key insight:** The existing WebRTCManager and LatencyTelemetry classes do all the hard WebRTC work. ProbeConnection is just orchestration glue.

## Common Pitfalls

### Pitfall 1: Signaling Race Conditions
**What goes wrong:** Client A creates offer, sends via server, but Client B hasn't initialized their ProbeConnection yet
**Why it happens:** Server signals "start probe" but clients initialize asynchronously
**How to avoid:** Two-phase probe initialization:
1. Server sends `probe_prepare` to both clients
2. Clients create ProbeConnection and emit `probe_ready`
3. Server waits for both `probe_ready` then sends `probe_start`
4. Lower-ID client creates offer (deterministic)
**Warning signs:** ICE candidates arriving before remote description set, answered with errors

### Pitfall 2: Socket ID Stale References
**What goes wrong:** Server has old socket_id for a participant who reconnected
**Why it happens:** Participant's socket changed but PARTICIPANT_SESSIONS wasn't updated
**How to avoid:** Always look up socket_id fresh from PARTICIPANT_SESSIONS, don't cache
**Warning signs:** Signaling messages never received by client

### Pitfall 3: Probe Timeout Without Cleanup
**What goes wrong:** Probe times out but ProbeConnection still exists, hogging resources
**Why it happens:** No cleanup triggered on timeout
**How to avoid:**
- Server sets hard timeout (e.g., 15s) for entire probe lifecycle
- Client ProbeConnection has self-cleanup timer
- Server removes probe session on timeout or completion
**Warning signs:** Memory growth over time, orphaned RTCPeerConnection objects

### Pitfall 4: TURN Credentials for Probes
**What goes wrong:** Probes fail because no TURN credentials passed
**Why it happens:** Probe initialization doesn't receive TURN config like games do
**How to avoid:** Pass TURN credentials from experiment config to ProbeCoordinator, include in `probe_prepare` event
**Warning signs:** Probes fail only for participants behind strict NATs

### Pitfall 5: Probe Interfering with Subsequent Game Connection
**What goes wrong:** After successful probe, game WebRTC connection fails
**Why it happens:** Browser has limit on RTCPeerConnection objects, probe not properly closed
**How to avoid:** Ensure ProbeConnection.close() is ALWAYS called - on success, failure, or timeout
**Warning signs:** Second WebRTC connection (game) fails with ICE errors

## Code Examples

### Probe Coordinator Server-Side

```python
# server/probe_coordinator.py
from __future__ import annotations
import logging
import time
import uuid
from typing import Dict, Any, Callable

import flask_socketio

logger = logging.getLogger(__name__)


class ProbeCoordinator:
    """Manages WebRTC probe connections for RTT measurement.

    Probes are temporary DataChannel connections between matchmaking candidates.
    They exist independently of games - no game_id is needed.
    """

    def __init__(
        self,
        sio: flask_socketio.SocketIO,
        get_socket_for_subject: Callable[[str], str | None],
        turn_username: str | None = None,
        turn_credential: str | None = None,
    ):
        self.sio = sio
        self.get_socket_for_subject = get_socket_for_subject
        self.turn_username = turn_username
        self.turn_credential = turn_credential

        # Active probe sessions: probe_session_id -> ProbeSession
        self.probe_sessions: Dict[str, Dict[str, Any]] = {}

        # Timeout for entire probe lifecycle
        self.probe_timeout_s = 15.0

    def create_probe(
        self,
        subject_a: str,
        subject_b: str,
        on_complete: Callable[[str, str, float | None], None],
    ) -> str:
        """Create a probe session between two candidates.

        Args:
            subject_a: First participant's subject_id
            subject_b: Second participant's subject_id
            on_complete: Callback(subject_a, subject_b, rtt_ms) - rtt_ms is None on failure

        Returns:
            probe_session_id
        """
        probe_session_id = f"probe_{uuid.uuid4()}"

        socket_a = self.get_socket_for_subject(subject_a)
        socket_b = self.get_socket_for_subject(subject_b)

        if not socket_a or not socket_b:
            logger.warning(
                f"Cannot create probe: missing socket. "
                f"subject_a={subject_a} socket={socket_a}, "
                f"subject_b={subject_b} socket={socket_b}"
            )
            on_complete(subject_a, subject_b, None)
            return probe_session_id

        self.probe_sessions[probe_session_id] = {
            'subject_a': subject_a,
            'subject_b': subject_b,
            'socket_a': socket_a,
            'socket_b': socket_b,
            'ready_count': 0,
            'state': 'preparing',
            'created_at': time.time(),
            'on_complete': on_complete,
        }

        # Send prepare signal to both clients
        prepare_data = {
            'probe_session_id': probe_session_id,
            'peer_subject_id': subject_b,
            'turn_username': self.turn_username,
            'turn_credential': self.turn_credential,
        }
        self.sio.emit('probe_prepare', prepare_data, room=socket_a)

        prepare_data['peer_subject_id'] = subject_a
        self.sio.emit('probe_prepare', prepare_data, room=socket_b)

        logger.info(f"Created probe session {probe_session_id}: {subject_a} <-> {subject_b}")

        return probe_session_id

    def handle_ready(self, probe_session_id: str, subject_id: str):
        """Handle client reporting ready to probe."""
        session = self.probe_sessions.get(probe_session_id)
        if not session:
            return

        session['ready_count'] += 1

        if session['ready_count'] >= 2:
            session['state'] = 'connecting'
            # Both ready - signal start
            self.sio.emit('probe_start', {'probe_session_id': probe_session_id},
                         room=session['socket_a'])
            self.sio.emit('probe_start', {'probe_session_id': probe_session_id},
                         room=session['socket_b'])
            logger.info(f"Probe {probe_session_id}: both ready, starting")

    def handle_signal(
        self,
        probe_session_id: str,
        target_subject_id: str,
        signal_type: str,
        payload: Any,
        sender_socket_id: str,
    ):
        """Relay WebRTC signaling for probe connections."""
        session = self.probe_sessions.get(probe_session_id)
        if not session:
            logger.warning(f"Signal for unknown probe {probe_session_id}")
            return

        # Find target socket
        if target_subject_id == session['subject_a']:
            target_socket = session['socket_a']
        elif target_subject_id == session['subject_b']:
            target_socket = session['socket_b']
        else:
            logger.warning(f"Unknown target {target_subject_id} for probe {probe_session_id}")
            return

        # Find sender subject
        sender_subject = None
        if sender_socket_id == session['socket_a']:
            sender_subject = session['subject_a']
        elif sender_socket_id == session['socket_b']:
            sender_subject = session['subject_b']

        self.sio.emit('probe_signal', {
            'probe_session_id': probe_session_id,
            'type': signal_type,
            'from_subject_id': sender_subject,
            'payload': payload,
        }, room=target_socket)

    def handle_result(self, probe_session_id: str, rtt_ms: float | None, success: bool):
        """Handle probe measurement result from client."""
        session = self.probe_sessions.get(probe_session_id)
        if not session:
            return

        session['state'] = 'complete' if success else 'failed'

        # Call completion callback
        on_complete = session.get('on_complete')
        if on_complete:
            on_complete(session['subject_a'], session['subject_b'], rtt_ms if success else None)

        # Cleanup
        del self.probe_sessions[probe_session_id]
        logger.info(
            f"Probe {probe_session_id} complete: "
            f"{'success' if success else 'failed'}, rtt={rtt_ms}ms"
        )

    def cleanup_stale_probes(self):
        """Remove probes that have timed out."""
        now = time.time()
        stale = [
            sid for sid, session in self.probe_sessions.items()
            if now - session['created_at'] > self.probe_timeout_s
        ]
        for probe_session_id in stale:
            session = self.probe_sessions[probe_session_id]
            on_complete = session.get('on_complete')
            if on_complete:
                on_complete(session['subject_a'], session['subject_b'], None)
            del self.probe_sessions[probe_session_id]
            logger.warning(f"Probe {probe_session_id} timed out")
```

### Probe Connection Client-Side

```javascript
// static/js/probe_connection.js
import { WebRTCManager } from './webrtc_manager.js';

/**
 * Lightweight WebRTC connection for RTT probing.
 * Wraps WebRTCManager for measurement-only use.
 */
export class ProbeConnection {
    /**
     * @param {Object} socket - SocketIO socket
     * @param {string} probeSessionId - Unique probe session identifier
     * @param {string} mySubjectId - This participant's subject_id
     * @param {string} peerSubjectId - Peer participant's subject_id
     * @param {Object} options - Options (turnUsername, turnCredential)
     */
    constructor(socket, probeSessionId, mySubjectId, peerSubjectId, options = {}) {
        this.socket = socket;
        this.probeSessionId = probeSessionId;
        this.mySubjectId = mySubjectId;
        this.peerSubjectId = peerSubjectId;

        // Reuse WebRTCManager
        this.webrtcManager = new WebRTCManager(
            socket,
            probeSessionId,  // Acts as "game_id" for signaling routing
            mySubjectId,     // Acts as "player_id"
            {
                turnUsername: options.turnUsername,
                turnCredential: options.turnCredential,
            }
        );

        // Callbacks
        this.onConnected = null;
        this.onFailed = null;

        this._setupCallbacks();
        this._setupSignaling();
    }

    _setupCallbacks() {
        this.webrtcManager.onDataChannelOpen = () => {
            console.log(`[Probe ${this.probeSessionId}] DataChannel open`);
            this.onConnected?.();
        };

        this.webrtcManager.onConnectionFailed = () => {
            console.log(`[Probe ${this.probeSessionId}] Connection failed`);
            this.onFailed?.();
        };

        this.webrtcManager.onDataChannelClose = () => {
            console.log(`[Probe ${this.probeSessionId}] DataChannel closed`);
        };
    }

    _setupSignaling() {
        // Use probe-specific signaling events
        this._boundSignalHandler = (data) => {
            if (data.probe_session_id !== this.probeSessionId) return;

            // Translate probe signal to WebRTC signal format
            const webrtcSignal = {
                type: data.type,
                from_player_id: data.from_subject_id,
                game_id: this.probeSessionId,
                payload: data.payload,
            };

            // WebRTCManager's signal handler expects 'webrtc_signal' format
            // We need to manually invoke the handler
            this.webrtcManager._handleSignal(webrtcSignal);
        };

        this.socket.on('probe_signal', this._boundSignalHandler);
    }

    /**
     * Start the probe connection.
     * Deterministic: lower subject_id is initiator.
     */
    start() {
        console.log(`[Probe ${this.probeSessionId}] Starting connection to ${this.peerSubjectId}`);

        // Override _sendSignal to use probe events instead
        const originalSendSignal = this.webrtcManager._sendSignal.bind(this.webrtcManager);
        this.webrtcManager._sendSignal = (type, payload) => {
            this.socket.emit('probe_signal', {
                probe_session_id: this.probeSessionId,
                target_subject_id: this.peerSubjectId,
                type: type,
                payload: payload,
            });
        };

        this.webrtcManager.connectToPeer(this.peerSubjectId);
    }

    /**
     * Check if probe connection is ready for measurement.
     * @returns {boolean}
     */
    isReady() {
        return this.webrtcManager.isReady();
    }

    /**
     * Send data over the probe DataChannel.
     * @param {string|ArrayBuffer} data
     * @returns {boolean}
     */
    send(data) {
        return this.webrtcManager.send(data);
    }

    /**
     * Set up message handler for received data.
     * @param {Function} handler
     */
    onMessage(handler) {
        this.webrtcManager.onDataChannelMessage = handler;
    }

    /**
     * Get RTT via WebRTC stats (if connection is established).
     * @returns {Promise<number|null>} RTT in ms or null
     */
    async getRTT() {
        if (!this.webrtcManager.peerConnection) return null;

        try {
            const stats = await this.webrtcManager.peerConnection.getStats();
            let selectedPairId = null;
            stats.forEach(report => {
                if (report.type === 'transport' && report.selectedCandidatePairId) {
                    selectedPairId = report.selectedCandidatePairId;
                }
            });

            if (!selectedPairId) return null;

            let rtt = null;
            stats.forEach(report => {
                if (report.type === 'candidate-pair' && report.id === selectedPairId) {
                    if (report.currentRoundTripTime !== undefined) {
                        rtt = report.currentRoundTripTime * 1000;  // Convert to ms
                    }
                }
            });

            return rtt;
        } catch (e) {
            console.warn('[Probe] getRTT failed:', e);
            return null;
        }
    }

    /**
     * Close the probe connection and clean up.
     */
    close() {
        console.log(`[Probe ${this.probeSessionId}] Closing`);

        if (this._boundSignalHandler) {
            this.socket.off('probe_signal', this._boundSignalHandler);
            this._boundSignalHandler = null;
        }

        this.webrtcManager.close();
    }
}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Server-to-server RTT only | P2P RTT measurement | This phase | More accurate match quality prediction |
| Create game then measure | Measure before game creation | This phase | Avoids wasted game creation on bad matches |

**Deprecated/outdated:**
- Server ping as proxy for P2P latency: Server RTT doesn't reflect actual P2P path

## Open Questions

### Question 1: When to Trigger Probes?
**What we know:** Matchmaker receives arriving participant and waiting list
**What's unclear:** Should probes be triggered:
- (A) For every possible pair when candidate arrives?
- (B) Only when matchmaker is about to match (defer to Phase 59)?
- (C) Proactively for all waitroom participants in background?

**Recommendation:** Option (B) - let Phase 58/59 decide when to probe. This phase just provides the infrastructure. The matchmaker will call `probe_coordinator.create_probe()` when it needs RTT data.

### Question 2: Client-Side Probe State Management
**What we know:** Clients need to handle `probe_prepare`, create ProbeConnection, signal ready
**What's unclear:** Where should this state live on the client?

**Recommendation:** Create a minimal `ProbeManager` in the client that:
- Listens for `probe_prepare`
- Creates/tracks active ProbeConnection
- Handles lifecycle (success, failure, timeout)
- Can be integrated into `index.js` or a new module

## Sources

### Primary (HIGH confidence)
- Codebase: `interactive_gym/server/static/js/webrtc_manager.js` - Full WebRTC lifecycle reference
- Codebase: `interactive_gym/server/pyodide_game_coordinator.py` - Signaling relay patterns
- Codebase: `interactive_gym/server/app.py` - SocketIO handler patterns

### Secondary (MEDIUM confidence)
- Prior phase research: Phase 19 (Waiting Room Validation) - P2P validation patterns
- Prior phase research: Phase 20 (Mid-Game Reconnection) - Connection state management

### Tertiary (LOW confidence)
- None needed - all patterns derived from existing codebase

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - reusing existing WebRTCManager
- Architecture: HIGH - clear separation from game infrastructure
- Pitfalls: HIGH - derived from existing WebRTC implementation experience

**Research date:** 2026-02-03
**Valid until:** 2026-03-03 (30 days - stable WebRTC patterns)
