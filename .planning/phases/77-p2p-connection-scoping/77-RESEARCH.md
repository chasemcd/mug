# Phase 77: P2P Connection Scoping - Research

**Researched:** 2026-02-07
**Domain:** Client-side WebRTC lifecycle, scene transition cleanup, overlay suppression
**Confidence:** HIGH

## Summary

This phase requires two changes: (1) close WebRTC connections when a GymScene exits, and (2) suppress the "partner disconnected" overlay on non-GymScene scenes. Both are client-side problems in `index.js` and `pyodide_multiplayer_game.js`.

The root causes are well-understood from direct code tracing. When a game completes normally (all episodes done), `signalEpisodeComplete()` sets `state = "done"`, which triggers `checkPyodideDone` in index.js to emit `advance_scene`. The server calls `stager.advance()`, which calls `current_scene.deactivate()` (emitting `terminate_scene`), then `current_scene.activate()` for the next scene (emitting `activate_scene`). On the client, `terminateGymScene()` is called, which does UI cleanup and data export, but **never closes the WebRTC connection** and **never nullifies `pyodideRemoteGame`**. The old `MultiplayerPyodideGame` instance persists with its socket listeners still registered, meaning `p2p_game_ended` events can still fire `_handleReconnectionGameEnd()` and show the partner-disconnected overlay even when the participant has moved to a survey or end screen.

**Primary recommendation:** Add WebRTC cleanup to `terminateGymScene()` in index.js, and add a guard condition in `_handleReconnectionGameEnd()` / `_showPartnerDisconnectedOverlay()` that checks whether the game is in a terminal-but-still-active state vs. a fully-exited state.

## Standard Stack

No new libraries needed. All changes are within existing codebase files.

### Core Files to Modify

| File | Purpose | Changes Needed |
|------|---------|----------------|
| `interactive_gym/server/static/js/index.js` | Client scene management | Add WebRTC cleanup in `terminateGymScene()` |
| `interactive_gym/server/static/js/pyodide_multiplayer_game.js` | P2P multiplayer game | Add `sceneExited` flag, guard overlay methods, add cleanup method |

### Supporting Files (Verification Only)

| File | Purpose | Why |
|------|---------|-----|
| `interactive_gym/server/static/js/webrtc_manager.js` | WebRTC management | Verify `close()` is idempotent (it is) |
| `interactive_gym/server/app.py` | Server event handlers | Verify `advance_scene` handler (already resets participant state) |
| `interactive_gym/scenes/stager.py` | Scene advancement | Verify `advance()` calls `deactivate()` then `activate()` |

## Architecture Patterns

### Scene Lifecycle Flow (Normal Game Completion)

```
1. MultiplayerPyodideGame.signalEpisodeComplete()
   -> sets this.state = "done"

2. checkPyodideDone interval (index.js) detects isDone() === true
   -> emits advance_scene to server

3. Server: advance_scene handler
   -> Resets ParticipantState to IDLE
   -> Calls stager.advance(socketio, room)

4. stager.advance()
   -> current_scene.deactivate()  [emits "terminate_scene"]
   -> current_scene = next_scene
   -> current_scene.activate()    [emits "activate_scene"]

5. Client: "terminate_scene" handler
   -> Calls terminateGymScene(data)  [line 1527 in index.js]
   -> Does: graphics_end(), emitMultiplayerMetrics(), emit_remote_game_data
   -> Does NOT: close WebRTC, null pyodideRemoteGame, remove socket listeners

6. Client: "activate_scene" handler
   -> Calls activateScene(data)
   -> Routes to startStaticScene/startEndScene/startGymScene based on scene_type
```

### Problem 1: WebRTC Connection Persists (P2P-01)

After `terminateGymScene()`, the following remain alive:
- `pyodideRemoteGame` (the `MultiplayerPyodideGame` instance) -- module-level variable, never nullified
- `pyodideRemoteGame.webrtcManager` -- `RTCPeerConnection` and `DataChannel` still open
- `pyodideRemoteGame.webrtcManager._boundSignalHandler` -- still listening on `webrtc_signal` socket event
- Socket listeners registered in constructor: `p2p_game_ended`, `p2p_pause`, `p2p_resume`, `partner_excluded`, etc.
- `pyodideRemoteGame.timerWorker` -- Web Worker may still be running
- `pyodideRemoteGame.latencyTelemetry` -- polling interval still active
- `pyodideRemoteGame.qualityMonitor` (via webrtcManager) -- polling interval still active

### Problem 2: Stale Overlay Triggers (P2P-02)

The partner-disconnected overlay can appear on non-game scenes because:

1. Former partner disconnects (closes browser/tab)
2. Server's `on_disconnect()` finds the partner in PYODIDE_COORDINATOR.games
3. Server calls `remove_player(notify_others=True)` -- note: the check on line 2787 (`is_in_active_gym_scene`) only gates the _disconnecting player's_ scene check, not the receiving player's scene
4. Server emits `p2p_game_ended` to the remaining player's socket
5. The remaining player (now on a survey scene) still has the old `MultiplayerPyodideGame` instance with its `p2p_game_ended` listener
6. `_handleReconnectionGameEnd()` runs, calls `_showPartnerDisconnectedOverlay()`
7. Overlay hides ALL page content and shows "partner disconnected" message on the survey page

### Solution Architecture

**Two complementary fixes:**

#### Fix A: Close WebRTC on GymScene exit (P2P-01)
Add a cleanup call in `terminateGymScene()` in index.js:

```javascript
function terminateGymScene(data) {
    // ... existing cleanup ...

    // P2P-01: Close WebRTC connections when GymScene exits
    if (pyodideRemoteGame && pyodideRemoteGame.webrtcManager) {
        pyodideRemoteGame.webrtcManager.close();
    }
    // Also clean up any remaining resources
    if (pyodideRemoteGame && typeof pyodideRemoteGame.cleanupForSceneExit === 'function') {
        pyodideRemoteGame.cleanupForSceneExit();
    }
}
```

#### Fix B: Guard overlay display against scene exit state (P2P-02)
Add a flag to `MultiplayerPyodideGame` and check it before showing overlays:

```javascript
// In MultiplayerPyodideGame:
this.sceneExited = false;  // Set true when terminateGymScene is called

cleanupForSceneExit() {
    this.sceneExited = true;
    // Stop latency telemetry
    if (this.latencyTelemetry) this.latencyTelemetry.stop();
    // Stop P2P health reporting
    this._stopP2PHealthReporting();
    // Destroy timer worker
    this._destroyTimerWorker();
}

// Guard in _handleReconnectionGameEnd:
_handleReconnectionGameEnd(data) {
    if (this.sceneExited) {
        p2pLog.info('Ignoring p2p_game_ended - scene already exited');
        return;
    }
    // ... existing logic ...
}
```

### Why Both Fixes are Needed

Fix A alone is insufficient because:
- There's a race window between `terminateGymScene()` and the partner disconnecting
- The `webrtcManager.close()` removes the `webrtc_signal` listener but does NOT remove the `p2p_game_ended` socket listener (that's on the multiplayer game's constructor, not webrtcManager)
- Even after closing WebRTC, the socket listeners on the game instance remain

Fix B alone is insufficient because:
- WebRTC connections would still linger, consuming resources (ICE keepalives, TURN bandwidth)
- DataChannel callbacks could still fire unexpectedly
- Quality monitor and latency telemetry would still be polling

### Anti-Patterns to Avoid

- **Do NOT set `pyodideRemoteGame = null`**: The game instance may be reused if the next scene is also a GymScene (see `initializePyodideRemoteGame` logic at line 1594-1617). Setting it to null would force re-initialization of Pyodide. Instead, just close the WebRTC connection and set the scene-exit flag.
- **Do NOT remove socket listeners by name**: The listeners are registered as anonymous arrow functions in the constructor. There's no clean way to `socket.off('p2p_game_ended', ...)` because the reference isn't stored. The `sceneExited` guard is safer and simpler.
- **Do NOT modify the `isDone()` override**: The `partnerDisconnectedTerminal` check exists for a good reason (prevents scene advance when partner disconnects mid-game). The fix should be in the _handler_ that sets that flag, not in isDone().

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| WebRTC cleanup | Custom close logic | `WebRTCManager.close()` | Already handles DataChannel, PeerConnection, quality monitor, timers, signal handler cleanup |
| Socket listener cleanup | Manual `socket.off` | Guard flag (`sceneExited`) | Arrow function listeners have no stored reference; guard is idempotent and safe |

## Common Pitfalls

### Pitfall 1: Race Between Scene Exit and Partner Disconnect
**What goes wrong:** Partner disconnects in the brief window between `terminate_scene` and WebRTC close. The `p2p_game_ended` event arrives and shows the overlay on the wrong scene.
**Why it happens:** Scene termination and WebRTC cleanup are not atomic.
**How to avoid:** Set the `sceneExited` flag FIRST (synchronous), THEN close WebRTC (async-ish). The guard check in `_handleReconnectionGameEnd` catches any events that arrive after the flag is set.
**Warning signs:** Partner-disconnected overlay appearing briefly during scene transition.

### Pitfall 2: Double WebRTC Close
**What goes wrong:** `webrtcManager.close()` is called both from `terminateGymScene()` and from a terminal state handler (partner_excluded, focus_loss_timeout, reconnection_timeout).
**Why it happens:** Multiple exit paths can overlap.
**How to avoid:** `WebRTCManager.close()` is already idempotent (checks for null peerConnection/dataChannel). No special handling needed.
**Verification:** Confirmed at lines 856-893 in `webrtc_manager.js` -- close() checks each resource before closing.

### Pitfall 3: Reuse Scenario -- Next Scene is Also a GymScene
**What goes wrong:** Closing WebRTC in `terminateGymScene()` and then the next scene is also a multiplayer GymScene, but the game instance was reused (`reinitialize_environment` path).
**Why it happens:** `initializePyodideRemoteGame()` has a `needsNewInstance` check. If the next scene is also multiplayer, it reuses the existing instance.
**How to avoid:** The reuse path calls `reinitialize_environment()`, and a new `_initP2PConnection()` will create a fresh `WebRTCManager`. The closed one is simply replaced. But we should also reset `sceneExited = false` when a new game initializes.
**Verification:** Line 5587 shows `this.webrtcManager = new WebRTCManager(...)` which replaces any previous manager.

### Pitfall 4: Server-Side PYODIDE_COORDINATOR Still Has the Game
**What goes wrong:** After normal game completion, the game entry may still exist in `PYODIDE_COORDINATOR.games`. When the partner later disconnects (on a different scene), the server finds the entry and emits `p2p_game_ended`.
**Why it happens:** `multiplayer_game_complete` handler only archives to admin -- it does NOT remove the game from PYODIDE_COORDINATOR.
**How to avoid:** The client-side guard (`sceneExited`) handles this. However, for completeness, we could also clean up server-side. But this is secondary -- the client guard is the critical fix.
**Note:** The `on_disconnect` handler at line 2786-2790 checks `is_in_active_gym_scene` for the _disconnecting_ player's current scene, which correctly avoids notifying when the disconnecting player isn't in a GymScene. But if the _remaining_ player has already moved past the GymScene while the disconnecting player is still in it (or their stager hasn't advanced), the notification still fires.

### Pitfall 5: Cleanup of Socket Listeners Across Game Instances
**What goes wrong:** If a participant plays two GymScenes in sequence, the first `MultiplayerPyodideGame` instance's socket listeners (`p2p_game_ended`, etc.) still exist alongside the second instance's listeners.
**Why it happens:** `socket.on()` adds listeners without removing old ones. When `needsNewInstance` is true (line 1599), a new instance is created, but the old instance's listeners persist.
**How to avoid:** The `game_id` check in each handler (e.g., `if (data.game_id === this.gameId)`) already filters events for the wrong game. Combined with `sceneExited`, this is sufficient. True listener cleanup would require storing references, which is a larger refactor.

## Code Examples

### Pattern 1: terminateGymScene Cleanup

```javascript
// Source: index.js terminateGymScene() -- lines to ADD
function terminateGymScene(data) {
    ui_utils.disableKeyListener();
    graphics_end();

    // Clear intervals (existing)
    if (checkPyodideDone) {
        clearInterval(checkPyodideDone);
        checkPyodideDone = null;
    }
    if (refreshStartButton) {
        clearInterval(refreshStartButton);
        refreshStartButton = null;
    }

    // P2P-01 + P2P-02: Clean up P2P resources when exiting GymScene
    if (pyodideRemoteGame && typeof pyodideRemoteGame.cleanupForSceneExit === 'function') {
        pyodideRemoteGame.cleanupForSceneExit();
    }

    // ... rest of existing terminateGymScene logic (sync globals, emit data, etc.)
}
```

### Pattern 2: MultiplayerPyodideGame Scene Exit Cleanup

```javascript
// Source: pyodide_multiplayer_game.js -- new method
cleanupForSceneExit() {
    // Set flag FIRST (synchronous) to guard all handlers
    this.sceneExited = true;
    p2pLog.info('Scene exit cleanup initiated');

    // Close WebRTC connection (P2P-01)
    if (this.webrtcManager) {
        this.webrtcManager.close();
        this.webrtcManager = null;
    }

    // Stop telemetry and monitoring
    if (this.latencyTelemetry) {
        this.latencyTelemetry.stop();
    }
    this._stopP2PHealthReporting();
    this._destroyTimerWorker();
}
```

### Pattern 3: Guard in _handleReconnectionGameEnd

```javascript
// Source: pyodide_multiplayer_game.js -- guard to ADD at top of method
_handleReconnectionGameEnd(data) {
    // P2P-02: Don't show overlay if scene already exited
    if (this.sceneExited) {
        p2pLog.info('Ignoring p2p_game_ended - scene already exited');
        return;
    }

    // ... existing logic unchanged ...
}
```

### Pattern 4: Guard in _onP2PConnectionLost

```javascript
// Source: pyodide_multiplayer_game.js -- existing guard at line 6264 covers this
_onP2PConnectionLost(info) {
    // Already has: if (this.reconnectionState.isPaused || this.state === 'done')
    // ADD: scene exit check
    if (this.sceneExited) return;
    // ... existing logic ...
}
```

### Pattern 5: Reset sceneExited on New Game Init

```javascript
// Source: pyodide_multiplayer_game.js -- in constructor or _initP2PConnection
// Ensure sceneExited is reset when starting a new game
this.sceneExited = false;
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| No cleanup on scene exit | WebRTC stays open forever | v1.0 (Phase 1) | Stale connections, wrong overlays |
| [Phase 77] | Close WebRTC + guard handlers | This phase | Clean lifecycle |

**The key gap:** v1.0 through v1.18 assumed a single GymScene per experiment or that participants wouldn't care about stale connections. Multi-scene experiments (GymScene -> Survey -> GymScene) expose this gap.

## Open Questions

1. **Server-side PYODIDE_COORDINATOR cleanup on normal completion**
   - What we know: `multiplayer_game_complete` archives to admin but doesn't remove from `PYODIDE_COORDINATOR.games`. The game entry lingers.
   - What's unclear: Whether the server should also remove the game from the coordinator on normal completion (not just on disconnect/timeout).
   - Recommendation: Don't add server-side cleanup in this phase. The client-side guards handle P2P-01 and P2P-02 completely. Server cleanup is a potential follow-up if we find resource leaks, but the game entries are small and the coordinator already handles them when the last player disconnects.

2. **Socket listener accumulation across multiple GymScenes**
   - What we know: Each new `MultiplayerPyodideGame` instance registers fresh `socket.on()` listeners without removing old ones. The `game_id` filter prevents wrong-game events from being processed.
   - What's unclear: Whether listener count grows unboundedly across many GymScenes.
   - Recommendation: The `game_id` filter + `sceneExited` guard is sufficient for correctness. Listener cleanup (storing references, calling `socket.off()`) is a separate optimization that could be addressed in a future refactor if participants play many (10+) GymScenes in one experiment.

## Sources

### Primary (HIGH confidence)
- Direct code tracing of all files listed in Key Files
- `interactive_gym/server/static/js/index.js` -- Scene lifecycle, `terminateGymScene()`, `initializePyodideRemoteGame()`
- `interactive_gym/server/static/js/pyodide_multiplayer_game.js` -- `_handleReconnectionGameEnd()`, `_showPartnerDisconnectedOverlay()`, `_initP2PConnection()`, `signalEpisodeComplete()`
- `interactive_gym/server/static/js/webrtc_manager.js` -- `close()` method (idempotent)
- `interactive_gym/server/app.py` -- `advance_scene()`, `on_disconnect()`, `handle_p2p_reconnection_timeout()`
- `interactive_gym/server/pyodide_game_coordinator.py` -- `remove_player()` and `p2p_game_ended` emission
- `interactive_gym/scenes/stager.py` -- `advance()` calls `deactivate()` then `activate()`
- `interactive_gym/scenes/scene.py` -- `deactivate()` emits `terminate_scene`

### Secondary (MEDIUM confidence)
- Prior phase summaries for context on overlay behavior (Phase 23, Phase 20, Phase 27)

### Tertiary (LOW confidence)
- None

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- direct code tracing, no external libraries involved
- Architecture: HIGH -- all code paths traced end-to-end
- Pitfalls: HIGH -- based on actual code review, not hypothetical scenarios

**Research date:** 2026-02-07
**Valid until:** Indefinite (internal codebase, no external dependency versioning concerns)
