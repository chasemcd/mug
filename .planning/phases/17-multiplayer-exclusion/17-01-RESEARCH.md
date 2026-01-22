# Phase 17: Multiplayer Exclusion Handling - Research

**Researched:** 2026-01-21
**Domain:** Real-time multiplayer coordination, socket event handling, partial session data
**Confidence:** HIGH

## Summary

Phase 17 implements the server-side handler for mid-game exclusion events emitted by Phase 16's ContinuousMonitor. The core challenge is coordinating game termination across both players when one is excluded, ensuring the non-excluded player receives a clear, non-alarming notification ("Your partner experienced a technical issue") and that valid game data up to the exclusion point is preserved.

The research reveals that existing patterns in the codebase handle similar scenarios (player disconnect during active game) and can be adapted. The `PyodideGameCoordinator.remove_player()` method already sends `end_game` events to remaining players on disconnect. The key additions are: (1) a new socket handler for `mid_game_exclusion` events, (2) a custom notification message for partner exclusion vs. disconnect, (3) triggering data export for the non-excluded player before game cleanup, and (4) marking session data as partial.

**Primary recommendation:** Add `mid_game_exclusion` socket handler in `app.py` that calls a new `PyodideGameCoordinator.handle_player_exclusion()` method, which sends `partner_excluded` event to remaining player (distinct from `end_game`) and marks both players' data as partial sessions.

## Standard Stack

No new libraries required. Phase 17 uses existing infrastructure:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Flask-SocketIO | existing | WebSocket event handling | Already used for all game events |
| eventlet | existing | Async sleep before cleanup | Already used in `leave_game` |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| None | - | - | - |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Custom `partner_excluded` event | Reuse `end_game` with different message | Distinct event allows client-side differentiation (e.g., different UI treatment) |
| Marking partial in metrics JSON | Separate `_partial.json` file | Inline marker simpler, avoids file proliferation |

**Installation:**
No additional dependencies required.

## Architecture Patterns

### Event Flow for Mid-Game Exclusion

```
Player A (excluded)                     Server                      Player B (partner)
       |                                   |                                |
       |-- mid_game_exclusion ------------>|                                |
       |                                   |-- partner_excluded ----------->|
       |                                   |                                |-- (show notification)
       |                                   |-- trigger_data_export -------->|
       |                                   |                                |-- (emit metrics)
       |<-- end_game_request_redirect -----|                                |
       |                                   |                                |
       |                                   |-- cleanup game ---------------X|
```

### Recommended Project Structure

No new files needed. Modifications to existing:

```
interactive_gym/server/
├── app.py                      # Add @socketio.on('mid_game_exclusion') handler
├── pyodide_game_coordinator.py # Add handle_player_exclusion() method

interactive_gym/server/static/js/
├── pyodide_multiplayer_game.js # Add socket.on('partner_excluded') handler
├── index.js                    # No changes needed (end_game handler exists)
```

### Pattern 1: Socket Handler with Coordinator Delegation

**What:** Socket event handlers in `app.py` delegate to coordinator methods for actual logic
**When to use:** All multiplayer game events

**Example:**
```python
# Source: app.py existing pattern (line 1256)
@socketio.on('pyodide_player_action')
def on_pyodide_player_action(data):
    # ... validation ...
    PYODIDE_COORDINATOR.receive_action(
        game_id=data.get("game_id"),
        player_id=data.get("player_id"),
        # ...
    )
```

This pattern should be followed for `mid_game_exclusion`:
```python
@socketio.on('mid_game_exclusion')
def on_mid_game_exclusion(data):
    if PYODIDE_COORDINATOR is None:
        logger.error("Pyodide coordinator not initialized")
        return

    PYODIDE_COORDINATOR.handle_player_exclusion(
        game_id=data.get("game_id"),
        excluded_player_id=data.get("player_id"),
        reason=data.get("reason"),
        frame_number=data.get("frame_number")
    )
```

### Pattern 2: Distinct Event for Partner Notification

**What:** Use `partner_excluded` event instead of reusing `end_game`
**When to use:** When client needs to distinguish between termination reasons

**Rationale:** The `end_game` event is used for multiple scenarios (normal end, disconnect, timeout). Using a distinct `partner_excluded` event allows:
- Clear partner notification message without conditional logic
- Potential future UI differences (e.g., less alarming styling)
- Metrics distinguishing exclusion vs. disconnect

**Example:**
```python
# In PyodideGameCoordinator.handle_player_exclusion()
self.sio.emit(
    'partner_excluded',
    {
        'message': 'Your partner experienced a technical issue. The game has ended.',
        'reason': 'partner_exclusion',  # For metrics
        'frame_number': frame_number
    },
    room=partner_socket_id
)
```

### Pattern 3: Marking Sessions as Partial

**What:** Add `is_partial_session` flag to exported metrics
**When to use:** When game ends prematurely (exclusion, disconnect mid-game)

**Example in metrics export:**
```python
# In _create_aggregated_metrics (app.py) or individual metrics save
aggregated = {
    # ... existing fields ...
    "sessionStatus": {
        "isPartial": True,
        "terminationReason": "partner_exclusion",  # or "self_exclusion", "disconnect"
        "terminatedAtFrame": frame_number,
        "terminatedAtTimestamp": timestamp
    }
}
```

### Anti-Patterns to Avoid

- **Reusing end_game without differentiation:** Makes it impossible for client to show appropriate message
- **Not triggering data export for partner:** Partner's data up to exclusion point is valid and valuable
- **Synchronous cleanup before notification:** Partner might not receive message if game room is destroyed first

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Finding partner in game | Manual player iteration | `PyodideGameState.players` dict | Already tracks all players by socket |
| Room-based messaging | Direct socket iteration | `socketio.emit(..., room=socket_id)` | Room abstraction handles connection state |
| Game cleanup | Custom teardown | `PyodideGameCoordinator.remove_player()` | Handles all cleanup including server runner |

**Key insight:** The coordinator already has `remove_player()` which handles most of the cleanup. The new method needs to call this after sending notifications.

## Common Pitfalls

### Pitfall 1: Race Condition Between Notification and Cleanup

**What goes wrong:** Partner notification sent to room that's already being cleaned up, message never received
**Why it happens:** `remove_player()` deletes from `game.players` and may destroy room before emit completes
**How to avoid:**
1. Get partner socket ID before any cleanup
2. Emit `partner_excluded` directly to socket ID (not room)
3. Add brief `eventlet.sleep(0.1)` before cleanup (existing pattern in `leave_game`)
**Warning signs:** Partner sees no notification, or notification appears after redirect

### Pitfall 2: Excluded Player Gets Partner Notification

**What goes wrong:** Excluded player sees "Your partner experienced a technical issue" instead of their own exclusion message
**Why it happens:** Broadcasting to game room includes the excluded player
**How to avoid:** Emit only to partner's socket ID, not to game room
**Warning signs:** Both players see partner message

### Pitfall 3: Data Not Exported Before Cleanup

**What goes wrong:** Partner's valid game data lost because game cleaned up before export triggered
**Why it happens:** Server cleanup races with client's data export emit
**How to avoid:**
1. Send `trigger_data_export` event to partner before cleanup
2. Wait for acknowledgment or brief timeout
3. Alternative: Mark game as "pending_export" and clean up on next client disconnect
**Warning signs:** Partner's metrics JSON missing or incomplete

### Pitfall 4: Partial Session Not Marked in Data

**What goes wrong:** Researcher cannot distinguish partial sessions from complete ones
**Why it happens:** No flag added to indicate premature termination
**How to avoid:** Add `is_partial_session: true` and `termination_reason` to metrics export
**Warning signs:** All sessions appear identical in data analysis

## Code Examples

### Server-Side: Mid-Game Exclusion Handler

```python
# Source: New code for app.py, based on existing patterns

@socketio.on('mid_game_exclusion')
def on_mid_game_exclusion(data):
    """
    Handle mid-game exclusion from continuous monitoring.

    Called when a player is excluded due to sustained ping violations
    or tab visibility issues during gameplay.

    Args:
        data: {
            'game_id': str,
            'player_id': str | int,
            'reason': str ('sustained_ping', 'tab_hidden'),
            'frame_number': int,
            'timestamp': float
        }
    """
    global PYODIDE_COORDINATOR

    if PYODIDE_COORDINATOR is None:
        logger.error("Pyodide coordinator not initialized for mid_game_exclusion")
        return

    game_id = data.get("game_id")
    excluded_player_id = data.get("player_id")
    reason = data.get("reason")
    frame_number = data.get("frame_number")

    logger.info(
        f"Mid-game exclusion: player {excluded_player_id} in game {game_id} "
        f"(reason: {reason}, frame: {frame_number})"
    )

    PYODIDE_COORDINATOR.handle_player_exclusion(
        game_id=game_id,
        excluded_player_id=excluded_player_id,
        reason=reason,
        frame_number=frame_number
    )
```

### Server-Side: Coordinator Exclusion Method

```python
# Source: New code for pyodide_game_coordinator.py, based on remove_player() pattern

def handle_player_exclusion(
    self,
    game_id: str,
    excluded_player_id: str | int,
    reason: str,
    frame_number: int
):
    """
    Handle player exclusion from continuous monitoring.

    Notifies partner with clear message, triggers data export,
    and cleans up game state.

    Args:
        game_id: Game identifier
        excluded_player_id: ID of excluded player
        reason: Exclusion reason ('sustained_ping', 'tab_hidden')
        frame_number: Frame number when exclusion occurred
    """
    with self.lock:
        if game_id not in self.games:
            logger.warning(f"Exclusion for non-existent game {game_id}")
            return

        game = self.games[game_id]

        if excluded_player_id not in game.players:
            logger.warning(
                f"Excluded player {excluded_player_id} not in game {game_id}"
            )
            return

        # Find partner socket(s) before any cleanup
        partner_sockets = [
            socket_id for pid, socket_id in game.players.items()
            if pid != excluded_player_id
        ]

        # Notify partner(s) with clear, non-alarming message
        for socket_id in partner_sockets:
            self.sio.emit(
                'partner_excluded',
                {
                    'message': 'Your partner experienced a technical issue. The game has ended.',
                    'frame_number': frame_number,
                    'reason': 'partner_exclusion'
                },
                room=socket_id
            )

            # Trigger data export for partner before cleanup
            self.sio.emit(
                'trigger_data_export',
                {
                    'is_partial': True,
                    'termination_reason': 'partner_exclusion',
                    'termination_frame': frame_number
                },
                room=socket_id
            )

        logger.info(
            f"Notified {len(partner_sockets)} partner(s) of exclusion "
            f"in game {game_id}"
        )

        # Brief delay to ensure messages are delivered
        import eventlet
        eventlet.sleep(0.1)

        # Now clean up the game (reuse existing cleanup)
        # Stop server runner if it exists
        if game.server_runner:
            game.server_runner.stop()

        del self.games[game_id]
        logger.info(f"Cleaned up game {game_id} after player exclusion")
```

### Client-Side: Partner Exclusion Handler

```javascript
// Source: New code for pyodide_multiplayer_game.js

// Add to setupMultiplayerHandlers()
socket.on('partner_excluded', async (data) => {
    p2pLog.warn(`Partner excluded: ${data.message}`);

    // Stop game loop
    this.state = "done";
    this.episodeComplete = true;

    // Pause monitoring
    if (this.continuousMonitor) {
        this.continuousMonitor.pause();
    }

    // Show notification (less alarming than own exclusion)
    this._showPartnerExcludedUI(data.message);

    // Clean up WebRTC
    if (this.webrtcManager) {
        this.webrtcManager.close();
    }
});

socket.on('trigger_data_export', (data) => {
    // Mark session as partial in our metrics
    this.sessionPartialInfo = {
        isPartial: true,
        terminationReason: data.termination_reason,
        terminationFrame: data.termination_frame
    };

    // Export metrics immediately (before redirect)
    if (this.gameId) {
        this.emitMultiplayerMetrics(this.sceneId);
    }

    // Now request redirect
    socket.emit('end_game_request_redirect', {
        partner_exclusion: true
    });
});
```

### Client-Side: Partner Notification UI

```javascript
// Source: New code for pyodide_multiplayer_game.js

/**
 * Show partner excluded notification (less alarming than own exclusion).
 * @param {string} message - Notification message
 */
_showPartnerExcludedUI(message) {
    let overlay = document.getElementById('partnerExcludedOverlay');
    if (!overlay) {
        overlay = document.createElement('div');
        overlay.id = 'partnerExcludedOverlay';
        overlay.style.cssText = `
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.75);
            display: flex;
            justify-content: center;
            align-items: center;
            z-index: 10000;
        `;
        document.body.appendChild(overlay);
    }

    // Use neutral styling (not red like exclusion)
    overlay.innerHTML = `
        <div style="
            background: white;
            padding: 40px;
            border-radius: 8px;
            max-width: 500px;
            text-align: center;
        ">
            <h2 style="color: #333; margin-bottom: 20px;">Game Ended</h2>
            <p style="font-size: 16px; margin-bottom: 20px;">${message}</p>
            <p style="color: #666; font-size: 14px;">Your game data has been saved. You will be redirected shortly...</p>
        </div>
    `;
    overlay.style.display = 'flex';
}
```

### Metrics Export with Partial Session Marker

```javascript
// Source: Modification to exportMultiplayerMetrics() in pyodide_multiplayer_game.js

exportMultiplayerMetrics() {
    // ... existing code ...

    return {
        // ... existing fields ...

        // Session status (new for Phase 17)
        sessionStatus: {
            isPartial: this.sessionPartialInfo?.isPartial || false,
            terminationReason: this.sessionPartialInfo?.terminationReason || 'normal',
            terminationFrame: this.sessionPartialInfo?.terminationFrame || this.frameNumber,
            completedEpisodes: this.cumulativeValidation.episodes.length
        }
    };
}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Only handle disconnect | Handle exclusion as distinct event | Phase 17 | Partner gets clear message, data preserved |
| Single `end_game` for all terminations | Distinct events per scenario | Phase 17 | Better client-side handling |
| No partial session marker | `sessionStatus.isPartial` flag | Phase 17 | Data analysis can filter incomplete sessions |

**Deprecated/outdated:**
- None for this phase

## Open Questions

Things that couldn't be fully resolved:

1. **Should partner wait for data export acknowledgment?**
   - What we know: Current pattern uses brief `eventlet.sleep(0.1)` delay
   - What's unclear: Whether this is sufficient for data export emit to complete
   - Recommendation: Use the delay pattern initially; if data loss observed, add acknowledgment mechanism

2. **What if both players are excluded simultaneously?**
   - What we know: Theoretically possible if both have connection issues at same time
   - What's unclear: Which exclusion event arrives first, race condition handling
   - Recommendation: Handle gracefully - first exclusion event triggers full cleanup, second is no-op since game already removed

3. **Should excluded player's partial data also be saved?**
   - What we know: Excluded player already emits `leave_game` which may trigger data save
   - What's unclear: Whether current flow ensures their data is marked as partial
   - Recommendation: The excluded player's client-side `_handleMidGameExclusion()` should also set `sessionPartialInfo` before metrics export

## Sources

### Primary (HIGH confidence)
- `interactive_gym/server/app.py` - Existing socket handlers and coordinator delegation pattern
- `interactive_gym/server/pyodide_game_coordinator.py` - `remove_player()` and game state management
- `interactive_gym/server/static/js/pyodide_multiplayer_game.js` - `_handleMidGameExclusion()` from Phase 16
- `interactive_gym/server/game_manager.py` - `leave_game()` pattern with `eventlet.sleep(0.1)` before cleanup

### Secondary (MEDIUM confidence)
- `interactive_gym/server/static/js/index.js` - `end_game` handler and redirect flow

### Tertiary (LOW confidence)
- None

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - No new libraries, uses existing patterns
- Architecture: HIGH - Clear patterns exist in codebase
- Pitfalls: HIGH - Race conditions well-understood from existing code

**Research date:** 2026-01-21
**Valid until:** 2026-02-21 (stable patterns, no external dependencies)
