# Phase 69: Server-Side Init Grace - Research

**Researched:** 2026-02-06
**Domain:** Socket.IO/Engine.IO ping/pong mechanism, server-side grace periods, client loading state signaling
**Confidence:** HIGH

## Summary

This research investigates how to prevent false Socket.IO disconnections during Pyodide loading. The codebase has TWO distinct ping mechanisms that must be understood separately:

1. **Engine.IO transport-level ping/pong** -- The server sends PING packets at `ping_interval` and disconnects the client if no PONG is received within `ping_timeout`. This is the mechanism that causes false disconnects when the main thread is blocked by Pyodide WASM compilation. Currently configured as `ping_interval=8, ping_timeout=8`.

2. **Application-level custom ping/pong** -- The client emits a `'ping'` Socket.IO event every 1 second, and the server responds with a `'pong'` event containing `max_latency` data. This is purely for latency measurement and does NOT cause disconnections.

With Phase 67+68, the preloaded path eliminates the problem entirely (Pyodide loads during compat check, game startup is instant). However, the fallback path (preload failure, direct navigation) still runs `loadPyodide()` at game time, blocking the main thread for 5-15 seconds. Phase 69 adds a safety net for this fallback path.

**Primary recommendation:** Implement an application-level grace mechanism where the client signals loading state before Pyodide init begins and signals completion after. The server tracks per-client loading state and suppresses the `on_disconnect` handler's cleanup actions during the loading window. Increase `ping_timeout` to accommodate the loading window, or use the tuple form of `ping_interval` to add grace. The cleanest approach combines a generous Engine.IO timeout with application-level loading state tracking.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Flask-SocketIO | 5.3.6 | WebSocket server with Socket.IO protocol | Already in use, provides SocketIO configuration |
| python-socketio | 5.10.0 | Socket.IO server implementation | Underlying library, handles ping/pong |
| python-engineio | 4.8.0 | Engine.IO transport layer | Handles actual ping/pong frames and disconnect detection |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| N/A | - | No additional libraries needed | All changes are configuration + custom event handling |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Application-level grace | Just increase ping_timeout globally | Simple but weakens real disconnect detection for ALL clients |
| Per-client state tracking | Monkey-patch engine.io socket | Brittle, breaks on library updates, unnecessary complexity |
| Client heartbeat during load | WebSocket ping keepalive | Engine.IO already handles transport pings; can't control from JS in browser |

**Installation:**
```bash
# No new dependencies needed -- all changes use existing stack
```

## Architecture Patterns

### Two-Layer Architecture Understanding

The critical insight is that there are TWO separate ping systems:

```
Layer 1: Engine.IO Transport Pings (CAUSES DISCONNECTS)
=========================================================
  Server                         Browser
    |--- PING frame (every 8s) --->|
    |<-- PONG frame (auto) --------|  <-- Browser handles automatically
    |                               |      BUT: blocked main thread
    |                               |      prevents PONG response!
    |--- (no PONG after 8s) ------>|
    |--- DISCONNECT --------------->|

Layer 2: Application-Level Pings (LATENCY MEASUREMENT ONLY)
=========================================================
  Browser                        Server
    |--- emit('ping', {...}) ---->|  <-- setInterval(sendPing, 1000)
    |<-- emit('pong', {...}) -----|  <-- Returns max_latency info
    |                              |     Does NOT cause disconnects
```

### Recommended Approach: Three-Part Grace Mechanism

```
                   Client (index.js)                    Server (app.py)
                   ================                     ===============

1. SIGNAL LOADING START
   emit('pyodide_loading_start')  ───────────>  LOADING_CLIENTS.add(subject_id)
                                                 log "[Grace] Client entering loading"

2. PYODIDE LOADS (main thread blocked 5-15s)
   loadPyodide() / loadPackage() ...            Server PING sent, no PONG...
   [main thread blocked]                         check_ping_timeout() fires...
                                                 Engine.IO closes socket...
                                                 on_disconnect() handler fires...
                                                 IF subject_id in LOADING_CLIENTS:
                                                   log "[Grace] Suppressing disconnect"
                                                   DON'T run cleanup logic
                                                 ELSE:
                                                   run normal disconnect logic

3. PYODIDE READY (or page refreshes and reconnects)
   emit('pyodide_loading_complete') ─────────>  LOADING_CLIENTS.remove(subject_id)
                                                 log "[Grace] Client loading done"
```

### Pattern 1: Engine.IO Timeout Increase for Loading Window

**What:** Increase `ping_timeout` to 30 seconds (from 8s) to accommodate worst-case Pyodide loading.
**When to use:** As the primary defense -- prevents Engine.IO from disconnecting during the loading window.
**Why not just this:** Weakens disconnect detection for ALL clients. A client that truly disconnected won't be detected for 30s instead of 8s. This is acceptable but not ideal.
**Example:**
```python
# Source: python-engineio base_server.py, Flask-SocketIO docs
socketio = flask_socketio.SocketIO(
    app,
    cors_allowed_origins="*",
    # Increase timeout to accommodate Pyodide WASM compilation (5-15s)
    ping_interval=8,    # Still ping every 8 seconds
    ping_timeout=30,    # But wait 30 seconds for response
    # Total grace before disconnect: 8 + 30 = 38 seconds
)
```

### Pattern 2: Application-Level Loading State Tracking (GRACE-02, GRACE-03)

**What:** Client emits `'pyodide_loading_start'` before loading and `'pyodide_loading_complete'` after. Server tracks per-client loading state.
**When to use:** To enable the server to distinguish "client is loading Pyodide" from "client actually disconnected."
**Example:**
```python
# Server-side (app.py)
LOADING_CLIENTS: set[str] = set()  # subject_ids currently loading Pyodide

@socketio.on("pyodide_loading_start")
def on_pyodide_loading_start(data):
    subject_id = get_subject_id_from_session_id(flask.request.sid)
    if subject_id:
        LOADING_CLIENTS.add(subject_id)
        logger.info(f"[Grace] {subject_id} starting Pyodide loading")

@socketio.on("pyodide_loading_complete")
def on_pyodide_loading_complete(data):
    subject_id = get_subject_id_from_session_id(flask.request.sid)
    if subject_id:
        LOADING_CLIENTS.discard(subject_id)
        logger.info(f"[Grace] {subject_id} completed Pyodide loading")
```

```javascript
// Client-side (index.js) -- in preloadPyodide() and RemoteGame.initialize()
socket.emit('pyodide_loading_start', {});
// ... loadPyodide() happens ...
socket.emit('pyodide_loading_complete', {});
```

### Pattern 3: Disconnect Handler Grace Check (GRACE-01)

**What:** Modify `on_disconnect()` to check if the client was in a loading state and suppress destructive cleanup.
**When to use:** Even with increased `ping_timeout`, protect against edge cases where loading takes longer than expected.
**Example:**
```python
@socketio.on("disconnect")
def on_disconnect():
    subject_id = get_subject_id_from_session_id(flask.request.sid)

    if subject_id and subject_id in LOADING_CLIENTS:
        logger.warning(
            f"[Grace] {subject_id} disconnected during Pyodide loading. "
            f"Suppressing cleanup -- client will reconnect."
        )
        # Save session state but DON'T trigger game removal or partner notification
        session = PARTICIPANT_SESSIONS.get(subject_id)
        if session:
            session.socket_id = None
            session.is_connected = False
            session.last_updated_at = time.time()
        return  # Skip all cleanup

    # ... existing disconnect logic ...
```

### Anti-Patterns to Avoid
- **Monkey-patching engine.io internals:** Do not try to override `check_ping_timeout()` per-socket. The library does not support this and it will break on version upgrades.
- **Disabling ping entirely:** Setting `ping_interval=0` disables heartbeats, meaning dead connections are never detected. This is dangerous for a multi-player system.
- **Sending keepalive from client during loading:** The main thread IS blocked during WASM compilation. You cannot send messages from JS while `loadPyodide()` is running. The grace signal must be sent BEFORE loading starts.
- **Using WebSocket-level ping/pong from browser JS:** Browser JavaScript cannot send WebSocket ping frames. Only the browser's WebSocket implementation can respond to them, and it does so automatically -- unless the main thread is blocked.

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Per-client ping override | Custom ping scheduler | Increased ping_timeout + app-level grace | Engine.IO has no per-client timeout override; working around it is fragile |
| Loading state signaling | Complex handshake protocol | Simple emit before/after | Two socket events are sufficient; no need for acknowledgments |
| Reconnection handling | Custom reconnection logic | Existing session restoration (PARTICIPANT_SESSIONS) | The codebase already handles reconnection with stager state persistence |

**Key insight:** The existing session restoration mechanism (PARTICIPANT_SESSIONS, stager state saving in `on_disconnect`) already handles the reconnection case. Phase 69 only needs to prevent the disconnect handler from triggering destructive game cleanup actions (partner notifications, game teardown) when the disconnect is caused by Pyodide loading.

## Common Pitfalls

### Pitfall 1: Signaling After Main Thread Block
**What goes wrong:** If you try to emit `'pyodide_loading_start'` and then immediately call `loadPyodide()`, the emit may not be sent before the main thread blocks. Socket.IO uses microtask scheduling.
**Why it happens:** `socket.emit()` queues the message but the WebSocket send may be deferred. If `loadPyodide()` blocks before the event loop processes the send queue, the signal never reaches the server.
**How to avoid:** Use a small `setTimeout(fn, 0)` or `await new Promise(r => setTimeout(r, 50))` between the emit and the blocking call to ensure the event loop processes the send. Or, more robustly, emit the signal and use a server acknowledgment callback before proceeding.
**Warning signs:** Server never logs "loading_start" but does see the disconnect.

### Pitfall 2: Loading Client Set Not Cleaned Up on Timeout
**What goes wrong:** If a client crashes during loading (tab closed, browser killed), they stay in `LOADING_CLIENTS` forever.
**Why it happens:** The `'pyodide_loading_complete'` signal is never sent if the tab is closed.
**How to avoid:** Add a timeout mechanism: when a client enters loading state, record the timestamp. Periodically (or in the disconnect handler), check if the loading has exceeded a maximum threshold (e.g., 60 seconds). If so, remove from `LOADING_CLIENTS` and proceed with normal disconnect handling.
**Warning signs:** `LOADING_CLIENTS` grows unbounded; old subject IDs never get cleaned up.

### Pitfall 3: Increased ping_timeout Delays Real Disconnect Detection
**What goes wrong:** Setting `ping_timeout=30` means ALL disconnections take up to 38 seconds (8 + 30) to detect, not just loading-related ones.
**Why it happens:** Engine.IO ping settings are global, not per-client.
**How to avoid:** Accept this tradeoff. In this use case, 30s detection delay is acceptable because: (a) multiplayer games already have P2P WebRTC with 500ms disconnect detection, (b) the application-level ping runs every 1s and can be used for faster UI-level feedback, (c) true disconnects during single-player Pyodide games have no partner to notify. Alternatively, use `ping_timeout=20` as a compromise.
**Warning signs:** Partner disconnect notifications take much longer during multiplayer games. Mitigated by P2P layer already handling this.

### Pitfall 4: Race Between Loading Signal and Disconnect Handler
**What goes wrong:** The `'pyodide_loading_start'` emit is processed by the server, but the client's Engine.IO connection times out in the SAME eventlet tick, so the disconnect handler runs before the loading signal handler.
**Why it happens:** Eventlet scheduling is cooperative. If the server processes events in a specific order, the disconnect could fire before the loading signal is registered.
**How to avoid:** The loading signal is emitted BEFORE `loadPyodide()` starts, so it should always arrive at the server well before any timeout. The ping_interval is 8 seconds -- the loading signal arrives in milliseconds. The only risk is if the loading signal is dropped at the network layer, which is extremely unlikely on a WebSocket connection.
**Warning signs:** Disconnect logs appear without corresponding loading_start logs despite client correctly emitting the signal.

### Pitfall 5: Two Loading Paths Need Grace Signals
**What goes wrong:** Grace signals are added to `preloadPyodide()` (Phase 67 path) but not to the fallback `loadPyodide()` in `RemoteGame.initialize()`, or vice versa.
**Why it happens:** There are TWO places where Pyodide loading can block the main thread: (1) `preloadPyodide()` in index.js during compat check, (2) the fallback path in `RemoteGame.initialize()` when preload did not happen.
**How to avoid:** Add loading signals to BOTH paths. However, `preloadPyodide()` runs during compat check when the client has not yet joined a game, so a disconnect there has minimal impact. The critical path is the fallback in `RemoteGame.initialize()`.
**Warning signs:** Disconnects during preload (non-critical) vs disconnects during game initialization (critical).

## Code Examples

Verified patterns from official sources and codebase analysis:

### Engine.IO Ping Timeout Configuration
```python
# Source: python-engineio base_server.py, python-engineio 4.8.0
# Tuple form: (ping_interval, grace_period)
# grace_period is added to pingInterval sent to CLIENT in handshake
# The client expects pings every (interval + grace) seconds
# The server sends pings every (interval) seconds
socketio = flask_socketio.SocketIO(
    app,
    ping_interval=8,    # Server sends PING every 8 seconds
    ping_timeout=30,    # Wait 30 seconds for PONG before disconnect
)
# Note: Tuple form of ping_interval affects CLIENT expectation only.
# e.g., ping_interval=(8, 15) means server pings every 8s,
# but tells client "I'll ping every 23s" -- client is more patient.
# NOT useful here because the CLIENT disconnects if no ping, but the
# actual problem is the SERVER disconnecting when it gets no PONG.
```

### Client-Side Loading Signal (GRACE-02)
```javascript
// Source: Codebase pattern analysis
// In index.js preloadPyodide()
async function preloadPyodide(pyodideConfig) {
    if (!pyodideConfig || !pyodideConfig.needs_pyodide) {
        window.pyodidePreloadStatus = 'ready';
        return;
    }

    console.log('[PyodidePreload] Starting preload...');
    window.pyodidePreloadStatus = 'loading';

    // Signal server BEFORE blocking the main thread
    socket.emit('pyodide_loading_start', {});
    // Brief yield to ensure the emit is sent before main thread blocks
    await new Promise(resolve => setTimeout(resolve, 50));

    try {
        const pyodide = await loadPyodide();
        // ... rest of loading ...

        window.pyodidePreloadStatus = 'ready';
        socket.emit('pyodide_loading_complete', {});
    } catch (error) {
        window.pyodidePreloadStatus = 'error';
        socket.emit('pyodide_loading_complete', { error: true });
    }
}
```

### Server-Side Loading Tracking (GRACE-01, GRACE-03)
```python
# Source: Codebase pattern analysis
# Global loading state tracker
LOADING_CLIENTS: dict[str, float] = {}  # subject_id -> start_timestamp

LOADING_TIMEOUT_S = 60  # Max loading time before considering client dead

@socketio.on("pyodide_loading_start")
def on_pyodide_loading_start(data):
    subject_id = get_subject_id_from_session_id(flask.request.sid)
    if subject_id:
        LOADING_CLIENTS[subject_id] = time.time()
        logger.info(f"[Grace] {subject_id} starting Pyodide loading")

@socketio.on("pyodide_loading_complete")
def on_pyodide_loading_complete(data):
    subject_id = get_subject_id_from_session_id(flask.request.sid)
    if subject_id:
        start_time = LOADING_CLIENTS.pop(subject_id, None)
        if start_time:
            duration = time.time() - start_time
            logger.info(f"[Grace] {subject_id} completed Pyodide loading in {duration:.1f}s")

def is_client_in_loading_grace(subject_id: str) -> bool:
    """Check if client is in loading grace period (not timed out)."""
    start_time = LOADING_CLIENTS.get(subject_id)
    if start_time is None:
        return False
    if time.time() - start_time > LOADING_TIMEOUT_S:
        LOADING_CLIENTS.pop(subject_id, None)
        return False
    return True
```

### Disconnect Handler with Grace Check
```python
# Source: Codebase analysis of existing on_disconnect() at line 2665
@socketio.on("disconnect")
def on_disconnect():
    subject_id = get_subject_id_from_session_id(flask.request.sid)

    if subject_id and is_client_in_loading_grace(subject_id):
        logger.warning(
            f"[Grace] {subject_id} disconnected during Pyodide loading. "
            f"Preserving session for reconnection."
        )
        # Save session state (existing pattern from lines 2712-2723)
        session = PARTICIPANT_SESSIONS.get(subject_id)
        if session:
            participant_stager = STAGERS.get(subject_id)
            if participant_stager:
                session.stager_state = participant_stager.get_state()
            session.socket_id = None
            session.is_connected = False
            session.last_updated_at = time.time()
        return  # Skip game cleanup, partner notifications, etc.

    # ... rest of existing on_disconnect() logic unchanged ...
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| 5s stagger delay between games | Pyodide preload during compat check (Phase 67-68) | v1.16 (current) | Eliminates most loading-time disconnects |
| Single global ping_timeout | Application-level grace + increased timeout | Phase 69 (planned) | Handles fallback path without weakening real disconnect detection too much |
| Engine.IO ping drives disconnect | P2P WebRTC provides faster disconnect detection for multiplayer | v1.3 | Multiplayer games already have 500ms disconnect detection via DataChannel |

**Key insight for timing:**
- Engine.IO currently: `ping_interval=8, ping_timeout=8` = disconnect after ~16s of no PONG
- Pyodide WASM compilation: 5-15 seconds of main thread blocking
- Current setup: Marginal -- heavy loads can push past 16s threshold
- With `ping_timeout=30`: disconnect after ~38s, well beyond worst case

## Open Questions

Things that couldn't be fully resolved:

1. **Should ping_timeout be 20s or 30s?**
   - What we know: Pyodide loading takes 5-15s. Current total grace is 16s. We need at least 20-25s total.
   - What's unclear: Exact worst-case loading time on slow machines with concurrent loads.
   - Recommendation: Use `ping_timeout=30` (38s total grace). The downside (slower disconnect detection for non-loading clients) is mitigated by P2P WebRTC detection (500ms) for multiplayer games. For single-player Pyodide games, 30s disconnect detection is fine since there's no partner to notify.

2. **Should the preloadPyodide() path also signal loading state?**
   - What we know: `preloadPyodide()` runs during compat check, before any game is joined. A disconnect here just means the client reconnects and gets a new session.
   - What's unclear: Whether the disconnect causes any problems with PARTICIPANT_SESSIONS or STAGERS state.
   - Recommendation: Yes, add signals to both paths for consistency and safety, but the critical path is the fallback in `RemoteGame.initialize()`.

3. **Is the setTimeout(50ms) yield sufficient before loadPyodide()?**
   - What we know: Socket.IO uses the WebSocket send buffer. A 50ms yield should be enough for the event loop to process the queued emit.
   - What's unclear: Whether browser WebSocket implementations guarantee delivery within 50ms.
   - Recommendation: 50ms is pragmatically sufficient. If paranoid, use Socket.IO's callback acknowledgment (`socket.emit('event', data, ack_callback)`) to confirm delivery before proceeding.

## Sources

### Primary (HIGH confidence)
- python-engineio 4.8.0 source code (async_socket.py, base_server.py, server.py) - Ping/pong mechanism, timeout implementation, grace period handling
- Flask-SocketIO 5.3.6 documentation - ping_interval tuple form, global configuration
- Codebase analysis: `interactive_gym/server/app.py` lines 175-186 (SocketIO config), 938-955 (app-level ping), 2665-2875 (disconnect handler)
- Codebase analysis: `interactive_gym/server/static/js/index.js` lines 216-253 (preloadPyodide), 531-537 (app-level ping)

### Secondary (MEDIUM confidence)
- [Socket.IO Engine.IO Protocol docs](https://socket.io/docs/v4/engine-io-protocol/) - Ping/pong protocol specification
- [python-socketio API docs](https://python-socketio.readthedocs.io/en/latest/api.html) - Server configuration parameters
- [Flask-SocketIO API docs](https://flask-socketio.readthedocs.io/en/latest/api.html) - SocketIO class parameters including tuple form

### Tertiary (LOW confidence)
- [Socket.IO Issue #3507](https://github.com/socketio/socket.io/issues/3507) - Mobile browser ping timeout behavior (relevant context)
- [python-engineio Issue #183](https://github.com/miguelgrinberg/python-engineio/issues/183) - Ping/pong timeout problems

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Using existing installed libraries, versions verified
- Architecture: HIGH - Engine.IO ping mechanism verified from source code, two-layer ping architecture confirmed from codebase analysis
- Pitfalls: HIGH - Based on understanding of main thread blocking during WASM compilation and Socket.IO event processing

**Research date:** 2026-02-06
**Valid until:** 2026-03-06 (stable libraries, no major version changes expected)
