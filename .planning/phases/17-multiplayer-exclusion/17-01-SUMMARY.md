---
phase: 17
plan: 01
subsystem: multiplayer-coordination
tags: [python, javascript, socket.io, partner-notification, partial-session]
dependency-graph:
  requires:
    - 16 # Continuous monitoring (mid_game_exclusion event)
  provides:
    - mid_game_exclusion socket handler in app.py
    - handle_player_exclusion() method in PyodideGameCoordinator
    - partner_excluded and trigger_data_export socket events
    - Partial session marking in exported metrics
  affects:
    - 18 # Session data export (sessionStatus field)
tech-stack:
  added: []
  patterns:
    - Server-to-partner notification via distinct socket event
    - Partial session marking with termination reason
key-files:
  created: []
  modified:
    - interactive_gym/server/app.py
    - interactive_gym/server/pyodide_game_coordinator.py
    - interactive_gym/server/static/js/pyodide_multiplayer_game.js
decisions:
  - id: EXCL-01
    choice: Use distinct partner_excluded event (not reuse end_game)
    reason: Allows client to show appropriate message and UI styling
  - id: EXCL-02
    choice: Neutral gray UI styling for partner notification
    reason: Less alarming than red exclusion UI since partner did nothing wrong
  - id: EXCL-03
    choice: eventlet.sleep(0.1) before game cleanup
    reason: Ensures notification and export trigger are delivered before room destroyed
  - id: EXCL-04
    choice: sessionStatus object in metrics export
    reason: Enables research data analysis to filter partial sessions
metrics:
  duration: ~3 minutes
  completed: 2026-01-22
---

# Phase 17 Plan 01: Multiplayer Exclusion Handling Summary

Server-side mid-game exclusion handler with partner notification, coordinated game termination, and partial session data marking.

## What Was Built

### 1. Server-Side Exclusion Handler (app.py)
Added `@socketio.on('mid_game_exclusion')` handler that:
- Validates PYODIDE_COORDINATOR exists
- Extracts game_id, player_id, reason, frame_number from data
- Logs the exclusion event
- Delegates to `PYODIDE_COORDINATOR.handle_player_exclusion()`

### 2. Coordinator Exclusion Method (pyodide_game_coordinator.py)
Added `handle_player_exclusion()` method that:
- Acquires lock and validates game/player exist
- Finds partner socket(s) by iterating players excluding excluded player
- Emits `partner_excluded` event with:
  - message: "Your partner experienced a technical issue. The game has ended."
  - frame_number: the exclusion frame
  - reason: "partner_exclusion"
- Emits `trigger_data_export` event with:
  - is_partial: True
  - termination_reason: "partner_exclusion"
  - termination_frame: frame_number
- Uses `eventlet.sleep(0.1)` before cleanup (ensures message delivery)
- Stops server_runner if exists
- Deletes game from self.games

### 3. Client-Side Partner Notification (pyodide_multiplayer_game.js)
Added `socket.on('partner_excluded', ...)` handler that:
- Logs event via p2pLog.warn
- Sets `this.state = "done"` and `this.episodeComplete = true`
- Pauses continuousMonitor if exists
- Calls `_showPartnerExcludedUI(data.message)`
- Closes webrtcManager if exists

Added `socket.on('trigger_data_export', ...)` handler that:
- Sets `this.sessionPartialInfo` with isPartial, terminationReason, terminationFrame
- Calls `this.emitMultiplayerMetrics(this.sceneId)` to export data
- Emits `end_game_request_redirect` with partner_exclusion: true

### 4. Partner Notification UI
Added `_showPartnerExcludedUI(message)` method with:
- Fixed position dark overlay (rgba 0,0,0,0.75)
- White background card with padding and rounded corners
- Header: "Game Ended" in neutral #333 color (not red)
- Message paragraph with provided text
- Subtext: "Your game data has been saved. You will be redirected shortly..."

### 5. Partial Session Marking
Added `sessionStatus` object to `exportMultiplayerMetrics()`:
```javascript
sessionStatus: {
    isPartial: this.sessionPartialInfo?.isPartial || false,
    terminationReason: this.sessionPartialInfo?.terminationReason || 'normal',
    terminationFrame: this.sessionPartialInfo?.terminationFrame || this.frameNumber,
    completedEpisodes: this.cumulativeValidation?.episodes?.length || 0
}
```

Updated `_handleMidGameExclusion()` to set `sessionPartialInfo` before metrics export:
- Excluded player's reason: 'sustained_ping' or 'tab_hidden'
- Partner's reason: 'partner_exclusion'

Added `sessionPartialInfo = null` property initialization in constructor.

## Key Technical Decisions

| ID | Decision | Rationale |
|----|----------|-----------|
| EXCL-01 | Distinct partner_excluded event | Client can differentiate from end_game and show appropriate message |
| EXCL-02 | Neutral gray UI for partner | Partner did nothing wrong, less alarming than red exclusion UI |
| EXCL-03 | 0.1s delay before cleanup | Ensures notification delivered before game room destroyed |
| EXCL-04 | sessionStatus in metrics | Research can filter/analyze partial sessions separately |

## Event Flow

```
Player A (excluded)                     Server                      Player B (partner)
       |                                   |                                |
       |-- mid_game_exclusion ------------>|                                |
       |                                   |-- partner_excluded ----------->|
       |                                   |                                |-- (show UI)
       |                                   |-- trigger_data_export -------->|
       |                                   |                                |-- (export metrics)
       |                                   |                                |-- end_game_request_redirect
       |                                   |-- [0.1s delay] --------------->|
       |                                   |-- cleanup game ---------------X|
```

## Files Changed

| File | Change |
|------|--------|
| `interactive_gym/server/app.py` | +37 lines: mid_game_exclusion socket handler |
| `interactive_gym/server/pyodide_game_coordinator.py` | +71 lines: handle_player_exclusion() method |
| `interactive_gym/server/static/js/pyodide_multiplayer_game.js` | +110 lines: handlers, UI, partial session tracking |

## Commits

1. `dea389f` - feat(17-01): add server-side mid-game exclusion handler and coordinator method
2. `ada0dc3` - feat(17-01): add client-side partner notification handling
3. `c744a3b` - feat(17-01): add partial session marking in metrics export

## Deviations from Plan

None - plan executed exactly as written.

## Success Criteria Verification

- [x] **MULTI-01**: Non-excluded player sees "Your partner experienced a technical issue" message in neutral UI (gray #333 header)
- [x] **MULTI-02**: Game terminates cleanly - both players stop game loop, server cleans up game state after eventlet.sleep(0.1)
- [x] **MULTI-03**: Valid game data preserved - emitMultiplayerMetrics called before redirect, sessionStatus.isPartial = true with termination reason

## Next Phase Readiness

Phase 18 (Session Data Export) can now:
1. Access sessionStatus.isPartial to identify partial sessions
2. Use sessionStatus.terminationReason to categorize terminations
3. Filter or flag partial sessions in research data analysis
