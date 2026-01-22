# Phase 20: Mid-Game Reconnection - Research

**Researched:** 2026-01-22
**Domain:** WebRTC P2P reconnection handling during active gameplay
**Confidence:** HIGH

## Summary

Phase 20 implements mid-game reconnection handling when P2P DataChannel connections drop during active gameplay. The system must detect connection drops immediately, pause gameplay for both players, show a reconnecting overlay, and either resume seamlessly on reconnection success or end cleanly on timeout.

The existing codebase provides strong foundations:
- `WebRTCManager` already handles ICE connection state changes and has ICE restart logic
- Phase 19's validation state machine provides patterns for state tracking
- `ContinuousMonitor` demonstrates pause/resume patterns
- Partner exclusion handling (Phase 17) shows coordinated game termination patterns

Key challenges:
1. **Detection timing**: DataChannel `close` vs ICE `disconnected` vs `failed` states require different handling
2. **Bilateral pause coordination**: Both clients must pause simultaneously when either detects disconnection
3. **Reconnection strategy**: ICE restart needs signaling server coordination
4. **State machine complexity**: Multiple concurrent failure/recovery paths

**Primary recommendation:** Extend existing WebRTCManager callbacks to trigger a bilateral pause protocol via server, use ICE restart for recovery, and add configurable timeout with clean termination fallback.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| WebRTC APIs | Browser-native | RTCPeerConnection, RTCDataChannel | Already in use, handles ICE restart natively |
| SocketIO | Existing | Signaling relay, pause coordination | Already integrated for WebRTC signaling |
| Page Visibility API | Browser-native | Tab/focus state | Already used in ContinuousMonitor |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| None new | - | - | All required tools already in codebase |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| ICE restart | Full reconnection | ICE restart preserves connection faster, avoids full re-negotiation |
| Server-coordinated pause | Client-only pause | Server ensures bilateral pause, prevents desync |
| Single timeout | Exponential backoff | Simple timeout clearer for research validity |

**Installation:**
```bash
# No new dependencies - uses existing WebRTC and SocketIO infrastructure
```

## Architecture Patterns

### Recommended Reconnection State Machine

```
Connection States (extend existing):

      [connected]
          |
          | (iceConnectionState = 'disconnected' OR dataChannel.readyState = 'closing')
          v
      [pausing]  -----> emit 'p2p_connection_lost' to server
          |
          | (server emits 'p2p_pause' to both clients)
          v
      [paused]   -----> show overlay, stop game loop
          |
          | (ICE restart in progress)
          v
      [reconnecting] -> attempt ICE restart, send new offer/answer
          |
          +---> (success: dataChannel re-opens)
          |         |
          |         v
          |     [resuming] -> emit 'p2p_reconnection_success' to server
          |         |
          |         | (server emits 'p2p_resume' to both)
          |         v
          |     [connected] -> hide overlay, resume game loop
          |
          +---> (timeout reached)
                  |
                  v
              [terminated] -> emit 'p2p_reconnection_timeout' to server
                  |
                  | (server emits 'p2p_game_ended' to both)
                  v
              [game_over] -> show end screen, export data
```

### Pattern 1: Connection Loss Detection (Multiple Signals)

**What:** Monitor both ICE and DataChannel states for comprehensive detection
**When to use:** During active gameplay after validation complete
**Example:**
```javascript
// In webrtc_manager.js - enhance existing handlers

// ICE disconnected: Connection may recover spontaneously
this.peerConnection.oniceconnectionstatechange = () => {
    const state = this.peerConnection.iceConnectionState;
    console.log(`[WebRTC] ICE connection state: ${state}`);

    switch (state) {
        case 'disconnected':
            // Start disconnect timer - may self-recover
            this._startDisconnectGracePeriod();
            this.onConnectionDisconnected?.();
            break;
        case 'failed':
            // Terminal without ICE restart
            this._cancelDisconnectGracePeriod();
            this.onConnectionFailed?.();
            break;
        case 'connected':
        case 'completed':
            this._cancelDisconnectGracePeriod();
            this.iceRestartAttempts = 0;
            this.onConnectionRestored?.();
            break;
    }
};

// DataChannel close: More immediate than ICE state
dc.onclose = () => {
    console.log('[WebRTC] DataChannel closed');
    this.onDataChannelClose?.();  // Immediate pause trigger
};

// New callback for game layer
this.onConnectionDisconnected = null;  // Soft disconnect
this.onConnectionRestored = null;      // Recovery without restart
```

### Pattern 2: Bilateral Pause Coordination

**What:** Server coordinates pause to ensure both clients pause simultaneously
**When to use:** When either client detects connection loss
**Example:**
```javascript
// In pyodide_multiplayer_game.js

// Connection loss detected (from WebRTCManager callbacks)
_onP2PConnectionLost() {
    if (this.reconnectionState.isPaused) {
        return;  // Already paused
    }

    p2pLog.warn('P2P connection lost, requesting bilateral pause');

    // Log disconnection event (LOG-01)
    this.reconnectionState.disconnections.push({
        timestamp: Date.now(),
        frame: this.frameNumber,
        detectingPeer: this.myPlayerId,
        iceState: this.webrtcManager?.peerConnection?.iceConnectionState,
        dcState: this.webrtcManager?.dataChannel?.readyState
    });

    // Notify server to coordinate pause
    socket.emit('p2p_connection_lost', {
        game_id: this.gameId,
        player_id: this.myPlayerId,
        frame_number: this.frameNumber,
        timestamp: Date.now()
    });

    // Local pause (will be confirmed by server)
    this._pauseForReconnection();
}

_pauseForReconnection() {
    this.reconnectionState.isPaused = true;
    this.reconnectionState.pauseStartTime = Date.now();

    // Pause game loop
    this.continuousMonitor?.pause();

    // Show overlay (RECON-03)
    this._showReconnectingOverlay();

    // Start reconnection timeout (RECON-04)
    this.reconnectionState.timeoutId = setTimeout(() => {
        this._onReconnectionTimeout();
    }, this.reconnectionState.timeoutMs);
}
```

### Pattern 3: ICE Restart for Recovery

**What:** Use RTCPeerConnection.restartIce() to re-establish connection
**When to use:** After pause confirmed, during reconnecting state
**Example:**
```javascript
// In webrtc_manager.js - enhance existing _handleIceFailure

async attemptIceRestart() {
    if (this.iceRestartAttempts >= this.maxIceRestarts) {
        console.error('[WebRTC] Max ICE restart attempts reached');
        this.onConnectionFailed?.();
        return false;
    }

    this.iceRestartAttempts++;
    console.log(`[WebRTC] ICE restart attempt ${this.iceRestartAttempts}/${this.maxIceRestarts}`);

    try {
        // Step 1: Request ICE restart
        this.peerConnection.restartIce();

        // Step 2: Create new offer with ICE restart flag
        const offer = await this.peerConnection.createOffer({ iceRestart: true });
        await this.peerConnection.setLocalDescription(offer);

        // Step 3: Send offer via signaling
        this._sendSignal('offer', this.peerConnection.localDescription);

        return true;
    } catch (error) {
        console.error('[WebRTC] ICE restart failed:', error);
        return false;
    }
}
```

### Pattern 4: Server-Side Reconnection Coordination

**What:** Server tracks reconnection state and coordinates both clients
**When to use:** Handle p2p_connection_lost, track timeout, emit resume/end
**Example:**
```python
# In pyodide_game_coordinator.py

@dataclasses.dataclass
class PyodideGameState:
    # ... existing fields ...

    # Reconnection state (Phase 20)
    reconnection_in_progress: bool = False
    reconnection_start_time: float | None = None
    reconnection_timeout_s: float = 30.0  # Default 30 seconds
    reconnection_lost_players: set = dataclasses.field(default_factory=set)
    reconnection_recovered_players: set = dataclasses.field(default_factory=set)
    total_pause_duration_ms: float = 0.0

def handle_connection_lost(self, game_id: str, player_id: str | int):
    """Handle P2P connection loss from a client."""
    with self.lock:
        game = self.games.get(game_id)
        if not game:
            return None

        game.reconnection_lost_players.add(str(player_id))

        if not game.reconnection_in_progress:
            game.reconnection_in_progress = True
            game.reconnection_start_time = time.time()
            game.reconnection_recovered_players = set()

            # Return 'pause' to signal both clients should pause
            return 'pause'

        # Already in reconnection - just track this player
        return 'already_pausing'

def handle_reconnection_success(self, game_id: str, player_id: str | int):
    """Handle successful reconnection from a client."""
    with self.lock:
        game = self.games.get(game_id)
        if not game:
            return None

        game.reconnection_recovered_players.add(str(player_id))

        # Check if all lost players have recovered
        if game.reconnection_lost_players <= game.reconnection_recovered_players:
            # All recovered - calculate pause duration
            pause_duration = (time.time() - game.reconnection_start_time) * 1000
            game.total_pause_duration_ms += pause_duration

            # Reset reconnection state
            game.reconnection_in_progress = False
            game.reconnection_start_time = None
            game.reconnection_lost_players = set()
            game.reconnection_recovered_players = set()

            return 'resume'

        return 'waiting'
```

### Pattern 5: Reconnection Event Logging

**What:** Log all disconnection/reconnection events for data export (LOG-01, LOG-02, LOG-03)
**When to use:** Throughout reconnection lifecycle
**Example:**
```javascript
// In pyodide_multiplayer_game.js

// Reconnection state and logging
this.reconnectionState = {
    isPaused: false,
    pauseStartTime: null,
    timeoutMs: 30000,          // Configurable (RECON-04)
    timeoutId: null,
    attemptCount: 0,

    // Logging data (LOG-01, LOG-02, LOG-03)
    disconnections: [],        // [{timestamp, frame, detectingPeer, iceState, dcState}]
    reconnectionAttempts: [],  // [{timestamp, duration, outcome}]
    totalPauseDuration: 0      // Cumulative ms paused
};

// On reconnection success
_onReconnectionSuccess() {
    const duration = Date.now() - this.reconnectionState.pauseStartTime;

    // Log attempt (LOG-02)
    this.reconnectionState.reconnectionAttempts.push({
        timestamp: Date.now(),
        duration: duration,
        outcome: 'success',
        attempts: this.reconnectionState.attemptCount
    });

    // Update total pause (LOG-03)
    this.reconnectionState.totalPauseDuration += duration;

    // Reset state
    this._clearReconnectionTimeout();
    this.reconnectionState.isPaused = false;
    this.reconnectionState.pauseStartTime = null;
    this.reconnectionState.attemptCount = 0;

    // Hide overlay, resume
    this._hideReconnectingOverlay();
    this.continuousMonitor?.resume();
}

// Export reconnection data
getReconnectionData() {
    return {
        disconnections: this.reconnectionState.disconnections,
        reconnectionAttempts: this.reconnectionState.reconnectionAttempts,
        totalPauseDurationMs: this.reconnectionState.totalPauseDuration
    };
}
```

### Anti-Patterns to Avoid

- **Reacting to every ICE `disconnected`:** This state is transient; may self-recover in 1-2s
- **Client-only pause decision:** Both clients must agree via server to prevent desync
- **Blocking game loop during reconnection:** Use async/event-driven approach
- **No timeout:** Must have upper bound for research validity
- **Immediate ICE restart on `disconnected`:** Wait briefly, check with getStats() first
- **Full re-signaling on ICE restart:** ICE restart preserves existing SDP, only refreshes candidates

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| ICE connection recovery | Custom reconnection protocol | `RTCPeerConnection.restartIce()` | Native WebRTC handles candidate re-gathering |
| Connection state detection | Custom heartbeat only | ICE + DataChannel state callbacks | More comprehensive, handles edge cases |
| Bilateral pause | Client-to-client messaging | Server coordination | Reliable even when P2P is down |
| Timeout management | Manual setInterval | setTimeout with clear | Simpler, avoids accumulation |
| Overlay UI | Custom DOM manipulation | Existing UI patterns from exclusion | Consistent with codebase |

**Key insight:** ICE restart is the WebRTC-native recovery mechanism. The complexity is in coordinating both clients and handling the state machine, not in the reconnection itself.

## Common Pitfalls

### Pitfall 1: Reacting Too Quickly to `disconnected` State

**What goes wrong:** ICE restart triggered immediately on `disconnected`, causes unnecessary re-negotiation
**Why it happens:** `disconnected` is transient; connection often self-recovers in 1-2 seconds
**How to avoid:** Add grace period (2-5s) before triggering ICE restart; verify with `getStats()` that no data is flowing
**Warning signs:** High rate of unnecessary ICE restarts on stable networks
**Example:**
```javascript
// Wait before reacting to disconnected
_startDisconnectGracePeriod() {
    this._cancelDisconnectGracePeriod();
    this.disconnectGraceId = setTimeout(() => {
        // Verify still disconnected before acting
        if (this.peerConnection?.iceConnectionState === 'disconnected') {
            this._checkDataFlowBeforeRestart();
        }
    }, 3000);  // 3 second grace period
}

async _checkDataFlowBeforeRestart() {
    const stats1 = await this._getTransportStats();
    await new Promise(r => setTimeout(r, 1000));
    const stats2 = await this._getTransportStats();

    // If no bytes transferred, connection is truly dead
    if (stats1.bytesReceived === stats2.bytesReceived &&
        stats1.bytesSent === stats2.bytesSent) {
        this.attemptIceRestart();
    }
}
```

### Pitfall 2: Pause Desync Between Clients

**What goes wrong:** One client pauses, other continues playing, state diverges
**Why it happens:** Connection loss means P2P messages don't reach peer
**How to avoid:** Server must coordinate pause; both clients wait for server confirmation
**Warning signs:** After reconnection, game states don't match
**Example fix:**
```python
# Server ensures both clients pause
@socketio.on('p2p_connection_lost')
def handle_p2p_connection_lost(data):
    game_id = data.get('game_id')

    result = PYODIDE_COORDINATOR.handle_connection_lost(game_id, data['player_id'])

    if result == 'pause':
        # Emit to ALL players in game (via SocketIO room), not just P2P
        socketio.emit('p2p_pause', {
            'game_id': game_id,
            'frame_to_pause_at': data['frame_number'],
            'detecting_player': data['player_id']
        }, room=game_id)  # SocketIO room, not P2P
```

### Pitfall 3: DataChannel Not Recreated After ICE Restart

**What goes wrong:** ICE restart succeeds but DataChannel remains closed
**Why it happens:** Some browsers/scenarios require new DataChannel after ICE restart
**How to avoid:** Listen for `negotiationneeded`, create new DataChannel if needed
**Warning signs:** ICE connected but no data flowing
**Reference:** [GitHub Issue: RTCDataChannel broken after reconnection](https://github.com/webrtc/samples/issues/991)

### Pitfall 4: Timeout Fires After Successful Reconnection

**What goes wrong:** Game ends even though reconnection succeeded
**Why it happens:** Timeout not cleared immediately on reconnection
**How to avoid:** Clear timeout as FIRST action in success handler
**Example:**
```javascript
_onReconnectionSuccess() {
    // FIRST: Clear timeout
    this._clearReconnectionTimeout();

    // THEN: Process success
    // ...
}

_clearReconnectionTimeout() {
    if (this.reconnectionState.timeoutId) {
        clearTimeout(this.reconnectionState.timeoutId);
        this.reconnectionState.timeoutId = null;
    }
}
```

### Pitfall 5: Overlay Blocks Game Input After Resume

**What goes wrong:** Game resumes but player can't input
**Why it happens:** Overlay not properly hidden or input listeners not re-enabled
**How to avoid:** Resume flow must explicitly re-enable input handling
**Warning signs:** Player complains they can't control game after reconnection

### Pitfall 6: Memory Leak from Repeated Reconnection Attempts

**What goes wrong:** Multiple timeouts/intervals accumulate
**Why it happens:** Not clearing previous timers before starting new ones
**How to avoid:** Always clear before setting; use single source of truth
**Example:**
```javascript
_startReconnectionTimeout() {
    // ALWAYS clear first
    this._clearReconnectionTimeout();

    this.reconnectionState.timeoutId = setTimeout(() => {
        this._onReconnectionTimeout();
    }, this.reconnectionState.timeoutMs);
}
```

## Code Examples

### Reconnecting Overlay UI
```javascript
// In pyodide_multiplayer_game.js

_showReconnectingOverlay() {
    // Create overlay if doesn't exist
    let overlay = document.getElementById('reconnect-overlay');
    if (!overlay) {
        overlay = document.createElement('div');
        overlay.id = 'reconnect-overlay';
        overlay.style.cssText = `
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.7);
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
            z-index: 10000;
            color: white;
            font-family: sans-serif;
        `;
        overlay.innerHTML = `
            <div style="font-size: 24px; margin-bottom: 20px;">
                Connection Lost
            </div>
            <div class="spinner" style="
                width: 40px;
                height: 40px;
                border: 4px solid #333;
                border-top: 4px solid #fff;
                border-radius: 50%;
                animation: spin 1s linear infinite;
            "></div>
            <div id="reconnect-status" style="margin-top: 20px; font-size: 16px;">
                Reconnecting...
            </div>
            <style>
                @keyframes spin {
                    0% { transform: rotate(0deg); }
                    100% { transform: rotate(360deg); }
                }
            </style>
        `;
        document.body.appendChild(overlay);
    }

    overlay.style.display = 'flex';
}

_hideReconnectingOverlay() {
    const overlay = document.getElementById('reconnect-overlay');
    if (overlay) {
        overlay.style.display = 'none';
    }
}

_updateReconnectingStatus(message) {
    const status = document.getElementById('reconnect-status');
    if (status) {
        status.textContent = message;
    }
}
```

### Server Socket Handlers
```python
# In app.py

@socketio.on('p2p_connection_lost')
def handle_p2p_connection_lost(data):
    """Handle P2P connection loss - coordinate bilateral pause (Phase 20)."""
    global PYODIDE_COORDINATOR

    if PYODIDE_COORDINATOR is None:
        return

    game_id = data.get('game_id')
    player_id = data.get('player_id')
    frame_number = data.get('frame_number')

    logger.warning(f"P2P connection lost in game {game_id} detected by player {player_id} at frame {frame_number}")

    result = PYODIDE_COORDINATOR.handle_connection_lost(game_id, player_id)

    if result == 'pause':
        # Emit pause to ALL players via SocketIO (works even when P2P down)
        socketio.emit('p2p_pause', {
            'game_id': game_id,
            'pause_frame': frame_number,
            'detecting_player': player_id
        }, room=game_id)


@socketio.on('p2p_reconnection_success')
def handle_p2p_reconnection_success(data):
    """Handle successful P2P reconnection (Phase 20)."""
    global PYODIDE_COORDINATOR

    if PYODIDE_COORDINATOR is None:
        return

    game_id = data.get('game_id')
    player_id = data.get('player_id')

    result = PYODIDE_COORDINATOR.handle_reconnection_success(game_id, player_id)

    if result == 'resume':
        logger.info(f"All players reconnected in game {game_id}")
        socketio.emit('p2p_resume', {
            'game_id': game_id
        }, room=game_id)


@socketio.on('p2p_reconnection_timeout')
def handle_p2p_reconnection_timeout(data):
    """Handle reconnection timeout - end game cleanly (Phase 20)."""
    global PYODIDE_COORDINATOR

    if PYODIDE_COORDINATOR is None:
        return

    game_id = data.get('game_id')
    player_id = data.get('player_id')

    logger.warning(f"P2P reconnection timeout in game {game_id}")

    # Get reconnection data for logging
    reconnection_data = PYODIDE_COORDINATOR.get_reconnection_data(game_id)

    # Emit game ended to all players
    socketio.emit('p2p_game_ended', {
        'game_id': game_id,
        'reason': 'reconnection_timeout',
        'reconnection_data': reconnection_data
    }, room=game_id)

    # Clean up game
    PYODIDE_COORDINATOR.end_game_for_reconnection_timeout(game_id)
```

### Client Socket Handlers
```javascript
// In index.js

socket.on('p2p_pause', function(data) {
    console.log('[P2P] Pause received from server');
    if (pyodideRemoteGame && pyodideRemoteGame.pauseForReconnection) {
        pyodideRemoteGame.pauseForReconnection(data.pause_frame);
    }
});

socket.on('p2p_resume', function(data) {
    console.log('[P2P] Resume received from server');
    if (pyodideRemoteGame && pyodideRemoteGame.resumeFromReconnection) {
        pyodideRemoteGame.resumeFromReconnection();
    }
});

socket.on('p2p_game_ended', function(data) {
    console.log('[P2P] Game ended due to reconnection timeout');

    // Clear reconnection state
    if (pyodideRemoteGame) {
        pyodideRemoteGame.handleReconnectionGameEnd(data.reconnection_data);
    }

    // Show appropriate message
    $('#reconnect-overlay').hide();
    $('#waitroomText').text('Connection could not be restored. Game ended.');
    $('#waitroomText').show();

    // Trigger data export and redirect
    socket.emit('end_game_request_redirect', {
        reconnection_timeout: true
    });
});
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Full re-signaling on disconnect | ICE restart | WebRTC spec matured | Faster recovery, less overhead |
| Immediate reaction to `disconnected` | Grace period + getStats check | Best practices evolved | Fewer false positives |
| Client-side only timeout | Server-coordinated | Phase 19 pattern | Bilateral consistency |
| Manual heartbeat detection | Native ICE + DC states | Always available | More reliable, less code |

**Current best practices (2025):**
- ICE restart is preferred over full re-signaling
- `disconnected` state is transient; wait before acting
- `failed` state requires intervention (ICE restart or reconnection)
- Server coordination essential when P2P is down
- Grace period of 2-5 seconds before triggering recovery

## Open Questions

1. **Grace period duration before ICE restart**
   - What we know: 2-5 seconds recommended, 30s is RFC timeout to `failed`
   - What's unclear: Optimal duration for gaming (latency-sensitive)
   - Recommendation: Start with 3 seconds, make configurable

2. **Max ICE restart attempts**
   - What we know: Existing code uses 3 attempts
   - What's unclear: Should this be configurable separately from timeout?
   - Recommendation: Keep at 3, configurable if needed

3. **DataChannel recreation after ICE restart**
   - What we know: Some browsers may need new DataChannel
   - What's unclear: Which browsers/versions are affected
   - Recommendation: Test empirically; add recreation logic if needed

4. **Resume synchronization**
   - What we know: Both clients need to resume at same frame
   - What's unclear: How to handle frames that occurred during pause on only one client
   - Recommendation: Resume from pause_frame, discard any inputs during pause

## Sources

### Primary (HIGH confidence)
- [MDN: RTCPeerConnection.restartIce()](https://developer.mozilla.org/en-US/docs/Web/API/RTCPeerConnection/restartIce) - ICE restart method documentation
- [MDN: RTCPeerConnection.connectionState](https://developer.mozilla.org/en-US/docs/Web/API/RTCPeerConnection/connectionState) - Connection state definitions
- [MDN: RTCDataChannel.readyState](https://developer.mozilla.org/en-US/docs/Web/API/RTCDataChannel/readyState) - DataChannel states
- [MDN: iceconnectionstatechange event](https://developer.mozilla.org/en-US/docs/Web/API/RTCPeerConnection/iceconnectionstatechange_event) - ICE state change handling
- Existing codebase: `webrtc_manager.js`, `pyodide_multiplayer_game.js`, `continuous_monitor.js`

### Secondary (MEDIUM confidence)
- [BlogGeek.me: Handling WebRTC session disconnections](https://bloggeek.me/handling-session-disconnections-in-webrtc/) - Best practices
- [Medium: ICE restarts by Philipp Hancke](https://medium.com/@fippo/ice-restarts-5d759caceda6) - In-depth ICE restart guide
- [WebRTC.ventures: Reconnection Mechanism](https://webrtc.ventures/2023/06/implementing-a-reconnection-mechanism-for-webrtc-mobile-applications/) - Reconnection patterns
- Phase 19 research and implementation - Validation patterns

### Tertiary (LOW confidence)
- [GitHub Issue: DataChannel broken after reconnection](https://github.com/webrtc/samples/issues/991) - Known edge case
- WebRTC discuss-webrtc Google Group threads - Community experience

## Metadata

**Confidence breakdown:**
- Connection state detection: HIGH - MDN documentation comprehensive
- ICE restart mechanism: HIGH - Well-documented WebRTC spec
- Bilateral pause coordination: MEDIUM - Based on existing Phase 17/19 patterns
- DataChannel recreation: LOW - Edge case, browser-dependent
- Timeout handling: HIGH - Standard patterns from existing code

**Research date:** 2026-01-22
**Valid until:** 60 days (WebRTC APIs stable, patterns well-established)
