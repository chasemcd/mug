---
phase: 20-mid-game-reconnection
plan: 01
subsystem: p2p-networking
tags: [webrtc, reconnection, pause, socketio]

dependency-graph:
  requires:
    - 19-waiting-room-validation
  provides:
    - connection-drop-detection
    - bilateral-pause-coordination
    - reconnection-state-machine
    - server-reconnection-tracking
  affects:
    - 20-02 (ICE restart and resume)

tech-stack:
  added: []
  patterns:
    - grace-period-timeout-pattern
    - bilateral-coordination-via-server
    - state-machine-for-reconnection

key-files:
  created: []
  modified:
    - interactive_gym/server/static/js/webrtc_manager.js
    - interactive_gym/server/static/js/pyodide_multiplayer_game.js
    - interactive_gym/server/pyodide_game_coordinator.py
    - interactive_gym/server/app.py

decisions:
  - id: RECON-GRACE
    choice: 3-second grace period before declaring connection lost
    rationale: ICE 'disconnected' may self-recover quickly; avoids false positives

metrics:
  duration: 4m 19s
  completed: 2026-01-22
---

# Phase 20 Plan 01: Connection Drop Detection and Pause Coordination Summary

Connection drop detection with 3-second grace period, bilateral pause coordination via server, and reconnection state machine for mid-game P2P disconnection handling.

## Completed Tasks

| Task | Name | Commit | Files Modified |
|------|------|--------|----------------|
| 1 | Add connection drop detection callbacks to WebRTCManager | 2bc174b | webrtc_manager.js |
| 2 | Add reconnection state machine and pause handling to multiplayer game | 28923da | pyodide_multiplayer_game.js |
| 3 | Add server-side reconnection coordination | 7e9d405 | pyodide_game_coordinator.py, app.py |

## Implementation Details

### Task 1: WebRTCManager Connection Drop Detection

Added connection drop detection with 3-second grace period:

- `onConnectionLost` callback: Called when connection drop is confirmed
- `onConnectionRestored` callback: Called if connection self-recovers
- `disconnectGracePeriodMs`: 3000ms grace period before declaring lost
- Grace period starts on ICE 'disconnected' state
- ICE 'failed' triggers `onConnectionLost` immediately (terminal state)
- DataChannel close while ICE connected also triggers `onConnectionLost`
- `wasDisconnected` flag tracks recovery for `onConnectionRestored`

### Task 2: Multiplayer Game Reconnection State Machine

Added comprehensive reconnection state tracking:

**reconnectionState object:**
- `state`: 'connected' | 'pausing' | 'paused' | 'reconnecting' | 'terminated'
- `isPaused`: Game loop paused flag
- `pauseStartTime` / `pauseFrame`: Pause tracking
- `timeoutMs`: Configurable timeout (default 30s, from scene_metadata)
- `disconnections`: Array of disconnection events for logging (LOG-01)
- `reconnectionAttempts`: Array of reconnection attempts (LOG-02)
- `totalPauseDuration`: Cumulative pause time (LOG-03)

**Methods:**
- `_onP2PConnectionLost(info)`: Handles WebRTCManager callback
- `_pauseForReconnection(pauseFrame)`: Pauses game loop
- `_handleServerPause(data)`: Handles server pause command
- `_startReconnectionTimeout()` / `_clearReconnectionTimeout()`: Timeout management
- `_onReconnectionTimeout()`: Handles timeout, notifies server
- `_handleReconnectionGameEnd(data)`: Handles game termination
- `getReconnectionData()`: Returns reconnection data for export

**Socket handlers:**
- `p2p_pause`: Server-coordinated pause command
- `p2p_resume`: Resume command (stub for Plan 02)
- `p2p_game_ended`: Game termination due to reconnection failure

### Task 3: Server-Side Reconnection Coordination

**PyodideGameState fields:**
- `reconnection_in_progress`: Whether reconnection is active
- `reconnection_start_time`: When reconnection started
- `reconnection_timeout_s`: Configurable timeout (default 30s)
- `reconnection_lost_players`: Set of players who detected disconnect
- `reconnection_recovered_players`: Set of players who recovered
- `total_pause_duration_ms`: Cumulative pause time

**PyodideGameCoordinator methods:**
- `handle_connection_lost(game_id, player_id, frame_number)`: Triggers pause
- `handle_reconnection_success(game_id, player_id)`: Tracks recovery
- `handle_reconnection_timeout(game_id)`: Ends game on timeout
- `get_reconnection_data(game_id)`: Returns reconnection data

**Socket handlers in app.py:**
- `p2p_connection_lost`: Coordinates bilateral pause via SocketIO
- `p2p_reconnection_success`: Resumes game when all players recover
- `p2p_reconnection_timeout`: Ends game and cleans up

## Key Design Decisions

1. **3-Second Grace Period**: ICE 'disconnected' state may self-recover quickly. Grace period avoids triggering pause for brief network hiccups.

2. **Bilateral Pause via SocketIO**: P2P is down when we need to pause, so server coordinates pause command via SocketIO (always available).

3. **First Player Triggers Pause**: When first player reports disconnection, server immediately emits pause to both. Second player's report is logged but doesn't re-trigger.

4. **Event Logging**: All disconnection events logged with timestamp, frame, iceState, dcState for research analysis.

## Success Criteria Met

- [x] RECON-01: Connection drop detected via ICE state change with 3-second grace period
- [x] RECON-02: Both clients pause simultaneously via server-coordinated p2p_pause event
- [x] LOG-01: Disconnection events logged with timestamp, frame, detectingPeer, iceState, dcState
- [x] Server tracks reconnection state and coordinates pause/resume/timeout

## Deviations from Plan

None - plan executed exactly as written.

## Next Phase Readiness

Plan 20-02 (ICE Restart and Resume) can proceed. Required infrastructure:
- WebRTCManager connection callbacks in place
- Reconnection state machine ready for resume handling
- Server coordination for resume event ready
- `onConnectionRestored` callback available for self-recovery detection
