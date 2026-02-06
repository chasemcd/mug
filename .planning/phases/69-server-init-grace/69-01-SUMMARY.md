# Phase 69 Plan 01: Server-Side Init Grace Summary

Server-side grace mechanism preventing false disconnects during Pyodide WASM compilation via ping_timeout increase + per-client loading state tracking + disconnect handler grace check.

## What Was Done

### Task 1: Server-side grace period infrastructure
**Commit:** `e610a6a`
**Files modified:** `interactive_gym/server/app.py`

Four changes to app.py:
1. Increased `ping_timeout` from 8 to 30 seconds (total grace before disconnect: 38s, well beyond 15s worst-case Pyodide load). Multiplayer games already have P2P WebRTC 500ms disconnect detection, so the weaker Engine.IO detection is acceptable.
2. Added `LOADING_CLIENTS: dict[str, float]` global mapping subject_id to loading start timestamp, plus `LOADING_TIMEOUT_S = 60` safety constant.
3. Added `pyodide_loading_start` and `pyodide_loading_complete` socket event handlers that add/remove clients from `LOADING_CLIENTS` with duration logging.
4. Added `is_client_in_loading_grace()` function with 60s safety timeout and grace check at the top of `on_disconnect()` that preserves session state but skips all destructive cleanup (game removal, partner notifications) when client is loading.

### Task 2: Client-side loading signals in both Pyodide paths
**Commit:** `09eb6fa`
**Files modified:** `interactive_gym/server/static/js/index.js`, `interactive_gym/server/static/js/pyodide_remote_game.js`

Added loading signals to both places where Pyodide can block the main thread:
1. **index.js `preloadPyodide()`**: Emits `pyodide_loading_start` before `loadPyodide()` with 50ms event loop yield. Emits `pyodide_loading_complete` on success and on error (to clear grace state).
2. **pyodide_remote_game.js `RemoteGame.initialize()` fallback path**: Emits `pyodide_loading_start` before `loadPyodide()` with 50ms yield. Emits `pyodide_loading_complete` after micropip loaded. Guards socket access with `if (window.socket)` since RemoteGame may run in non-multiplayer contexts.

## Decisions Made

| Decision | Rationale |
|----------|-----------|
| ping_timeout=30 (not 20) | 38s total grace vs 15s worst case -- generous margin for slow machines under concurrent load |
| Dict with timestamps (not set) | Enables 60s safety timeout to prevent unbounded LOADING_CLIENTS growth if tab is closed |
| Grace check before admin logging | Early return preserves session but skips ALL destructive actions including admin disconnect logging |
| 50ms yield before loadPyodide() | Ensures socket.emit is sent before main thread blocks; pragmatically sufficient per research |
| Error path sends loading_complete | Prevents ghost entries in LOADING_CLIENTS when preload fails |

## Deviations from Plan

None -- plan executed exactly as written.

## Requirements Satisfied

- **GRACE-01**: `is_client_in_loading_grace()` used in `on_disconnect()` to skip destructive cleanup
- **GRACE-02**: `pyodide_loading_start` emitted from both client paths before blocking calls
- **GRACE-03**: `pyodide_loading_complete` emitted from both client paths; server handler removes from LOADING_CLIENTS

## Verification Results

1. `python -c "import interactive_gym.server.app"` -- no import errors
2. `is_client_in_loading_grace` defined at line 151, used in `on_disconnect()` at line 2731
3. `pyodide_loading_start` emitted from index.js (line 227) and pyodide_remote_game.js (line 59)
4. `pyodide_loading_complete` emitted from index.js (lines 253, 260) and pyodide_remote_game.js (line 71)
5. `ping_timeout=30` confirmed at line 204
6. Server handlers for loading_start/complete at lines 977-993

## Key Files

### Created
(none)

### Modified
- `interactive_gym/server/app.py` -- LOADING_CLIENTS, is_client_in_loading_grace(), event handlers, on_disconnect grace check, ping_timeout=30
- `interactive_gym/server/static/js/index.js` -- loading signals in preloadPyodide()
- `interactive_gym/server/static/js/pyodide_remote_game.js` -- loading signals in RemoteGame.initialize() fallback

## Duration

~3 minutes
