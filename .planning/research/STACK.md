# Stack Research: Session Lifecycle Management

**Project:** Interactive Gym — P2P Multiplayer Waiting Room Overhaul (v1.12)
**Researched:** 2026-02-02
**Focus:** Patterns for managing game session lifecycle in real-time multiplayer (cleanup, state machines, preventing stale references)

## Executive Summary

The core bug ("Game manager already exists for scene X, reusing it" with stale game managers capturing new participants) stems from **implicit lifecycle management** rather than **explicit state machine transitions**. The current codebase uses `GameStatus` (Inactive/Active/Reset/Done) but lacks a coordinated session-level state machine that governs the full lifecycle from creation through disposal.

The fix requires: (1) explicit session state machine with entry/exit actions, (2) deterministic cleanup triggers, and (3) reference tracking to prevent orphaned state.

## Patterns for Session State Management

### Pattern 1: Explicit Finite State Machine (Recommended)

**What:** Define discrete, mutually exclusive states with explicit transitions and entry/exit actions.

**Why:** The current implicit status checks (`game.status in [Active, Reset]`, `game_id in self.active_games`) are scattered across multiple files and can get out of sync. An explicit FSM centralizes lifecycle logic.

**Session States for v1.12:**

```
CREATED -> WAITING -> MATCHED -> VALIDATING -> PLAYING -> ENDED -> DISPOSED
              |          |           |            |
              v          v           v            v
           TIMEOUT   VALIDATION_FAILED  DISCONNECT  COMPLETE
              |          |               |
              +----------+---------------+
                         |
                         v
                      DISPOSED
```

**State Definitions:**

| State | Entry Action | Exit Action | Valid Transitions |
|-------|--------------|-------------|-------------------|
| CREATED | Initialize game data structures | - | WAITING |
| WAITING | Start timeout timer, emit waiting_room | Cancel timeout | MATCHED, TIMEOUT |
| MATCHED | Assign players, create PyodideGameState | - | VALIDATING, DISPOSED |
| VALIDATING | Start P2P validation | Cancel validation timer | PLAYING, VALIDATION_FAILED |
| PLAYING | Start game loop, emit start_game | Stop game loop | ENDED |
| ENDED | Emit end_game, trigger data export | - | DISPOSED |
| DISPOSED | Release all resources, remove from maps | Assert no references remain | (terminal) |

**Implementation Options:**

1. **python-statemachine** (Recommended for Python)
   - Mature library with lifecycle callbacks (on_enter_STATE, on_exit_STATE)
   - Supports validators and guards for transitions
   - Good documentation: [python-statemachine docs](https://python-statemachine.readthedocs.io/en/latest/transitions.html)

2. **transitions** library
   - Simpler API, good for straightforward state machines
   - Less boilerplate than python-statemachine

3. **Custom implementation**
   - Current GameStatus is close but lacks transition logic
   - Would need to add transition guards and lifecycle hooks

### Pattern 2: Ownership and Reference Tracking

**What:** Establish clear ownership hierarchies and track all references to session objects.

**Why:** The stale game manager bug occurs because `GAME_MANAGERS[scene_id]` persists after games end, and references in `PyodideGameCoordinator.games` can outlive their intended lifecycle.

**Ownership Hierarchy (Current):**

```
GAME_MANAGERS (global dict, keyed by scene_id)
  -> GameManager (one per scene, long-lived)
     -> games (dict, keyed by game_id)
        -> RemoteGameV2 instances
     -> waiting_games (list of game_ids)
     -> active_games (set of game_ids)

PYODIDE_COORDINATOR (global singleton)
  -> games (dict, keyed by game_id)
     -> PyodideGameState instances
```

**Problem:** When a game ends, cleanup happens in multiple places:
- `GameManager._remove_game()` removes from `games`, `waiting_games`, `active_games`, `waitroom_timeouts`, `reset_events`
- `PyodideGameCoordinator.remove_game()` removes from `games`
- But these are not always called together, and not always in the right order

**Solution: Single Source of Truth**

```python
class SessionLifecycle:
    """Central coordinator for all session state."""

    def __init__(self):
        self._sessions: Dict[str, Session] = {}
        self._refs: Dict[str, Set[str]] = defaultdict(set)  # session_id -> referencing_component_ids

    def create_session(self, session_id: str) -> Session:
        """Create and register a new session."""
        if session_id in self._sessions:
            raise ValueError(f"Session {session_id} already exists!")
        session = Session(session_id)
        self._sessions[session_id] = session
        return session

    def acquire_ref(self, session_id: str, component_id: str):
        """Register that a component holds a reference to this session."""
        self._refs[session_id].add(component_id)

    def release_ref(self, session_id: str, component_id: str):
        """Release a component's reference to this session."""
        self._refs[session_id].discard(component_id)
        if not self._refs[session_id] and self._sessions[session_id].state == SessionState.DISPOSED:
            del self._sessions[session_id]
            del self._refs[session_id]

    def dispose_session(self, session_id: str):
        """Mark session for disposal. Actual cleanup happens when all refs released."""
        session = self._sessions.get(session_id)
        if session:
            session.transition_to(SessionState.DISPOSED)
```

### Pattern 3: Deterministic Cleanup Triggers

**What:** Define exactly when and how cleanup occurs, with no implicit cleanup paths.

**Why:** Current code has multiple cleanup paths:
- `leave_game()` called on disconnect
- `cleanup_game()` called on game end
- `_remove_game()` called directly in some cases
- `remove_player()` in PyodideGameCoordinator with optional `notify_others`

**Cleanup Trigger Matrix:**

| Event | GameManager Action | PyodideCoordinator Action | Order |
|-------|-------------------|---------------------------|-------|
| Normal game end | `cleanup_game()` | `remove_game()` | GM first |
| Player disconnect (waiting) | `leave_game()` -> `_remove_game()` | `remove_player()` | GM first |
| Player disconnect (playing) | `cleanup_game()` | `remove_game()` | GM first |
| Waitroom timeout | `leave_game()` | `remove_player()` | GM first |
| P2P validation failure | `_remove_game()` | `remove_game()` | Coord first |
| Partner exclusion | `cleanup_game()` | (via handle_player_exclusion) | Coord first |

**Recommendation:** Consolidate to a single `dispose_session()` method that handles all paths.

## Cleanup Strategies

### Strategy 1: Exit Actions on State Transitions

**What:** Every state transition triggers exit actions that clean up resources associated with the previous state.

```python
class SessionStateMachine(StateMachine):
    # States
    waiting = State('waiting', initial=True)
    playing = State('playing')
    ended = State('ended')
    disposed = State('disposed', final=True)

    # Transitions
    start_game = waiting.to(playing)
    end_game = playing.to(ended)
    dispose = ended.to(disposed) | waiting.to(disposed)

    def on_exit_waiting(self):
        """Clean up waiting room resources."""
        self._cancel_timeout_timer()
        self._remove_from_waiting_list()

    def on_exit_playing(self):
        """Clean up active game resources."""
        self._stop_game_loop()
        self._export_data()

    def on_enter_disposed(self):
        """Final cleanup - must leave no dangling references."""
        self._remove_from_all_collections()
        self._close_room()
        self._notify_admin_aggregator()
```

### Strategy 2: Weak References for Cross-Component Links

**What:** Use `weakref` for references that should not prevent garbage collection.

**Why:** Prevents memory leaks when components hold references to sessions that should be cleaned up.

```python
import weakref

class GameManager:
    def __init__(self):
        # Strong reference - GameManager owns these
        self._sessions: Dict[str, Session] = {}

        # Weak reference - PyodideCoordinator can be notified but doesn't prevent GC
        self._coordinator_ref: weakref.ref | None = None

    def set_coordinator(self, coordinator):
        self._coordinator_ref = weakref.ref(coordinator)

    def notify_coordinator(self, session_id: str, event: str):
        coordinator = self._coordinator_ref()
        if coordinator is not None:
            coordinator.handle_event(session_id, event)
```

### Strategy 3: Idempotent Cleanup Methods

**What:** Make cleanup methods safe to call multiple times.

**Why:** In async/event-driven systems, cleanup can be triggered from multiple paths (disconnect, timeout, error). Idempotent methods prevent double-free bugs.

```python
def cleanup_session(self, session_id: str) -> bool:
    """Clean up a session. Returns True if cleanup occurred, False if already cleaned."""
    session = self._sessions.get(session_id)
    if session is None:
        logger.debug(f"Session {session_id} already cleaned up or never existed")
        return False

    if session.state == SessionState.DISPOSED:
        logger.debug(f"Session {session_id} already disposed")
        return False

    # Perform cleanup
    session.transition_to(SessionState.DISPOSED)
    del self._sessions[session_id]
    return True
```

### Strategy 4: Cleanup Queues for Async Paths

**What:** Queue cleanup requests and process them in a dedicated greenlet/task.

**Why:** Prevents race conditions when multiple events trigger cleanup simultaneously.

```python
class CleanupQueue:
    def __init__(self):
        self._queue = queue.Queue()
        self._worker = eventlet.spawn(self._process_cleanup)

    def schedule_cleanup(self, session_id: str, reason: str):
        self._queue.put((session_id, reason, time.time()))

    def _process_cleanup(self):
        while True:
            session_id, reason, queued_at = self._queue.get()
            try:
                self._do_cleanup(session_id, reason)
            except Exception as e:
                logger.error(f"Cleanup failed for {session_id}: {e}")
```

## Flask-SocketIO Specific Patterns

### Room Management Best Practices

**Current Issue:** Rooms are created but not always properly closed. The `close_room()` call in `_remove_game()` is good, but there's no verification that all clients have left.

**Pattern: Room Lifecycle Tracking**

```python
class RoomManager:
    def __init__(self, sio):
        self.sio = sio
        self._room_members: Dict[str, Set[str]] = defaultdict(set)

    def join_room(self, sid: str, room: str):
        flask_socketio.join_room(room)
        self._room_members[room].add(sid)
        logger.debug(f"Socket {sid} joined room {room}. Members: {len(self._room_members[room])}")

    def leave_room(self, sid: str, room: str):
        flask_socketio.leave_room(room)
        self._room_members[room].discard(sid)
        logger.debug(f"Socket {sid} left room {room}. Members: {len(self._room_members[room])}")

    def close_room(self, room: str):
        if self._room_members[room]:
            logger.warning(f"Closing room {room} with {len(self._room_members[room])} members still present")
        self.sio.close_room(room)
        del self._room_members[room]
```

### Disconnect Handler Best Practices

**Current Issue:** The `on_disconnect` handler is commented out, and disconnect handling is fragmented.

**Pattern: Centralized Disconnect Handling**

```python
@socketio.on('disconnect')
def on_disconnect():
    sid = flask.request.sid
    subject_id = SESSION_ID_TO_SUBJECT_ID.get(sid)

    if subject_id is None:
        logger.debug(f"Disconnect from unregistered socket {sid}")
        return

    # Update session state
    session = PARTICIPANT_SESSIONS.get(subject_id)
    if session:
        session.is_connected = False
        session.socket_id = None

    # Check if subject is in any game
    for scene_id, game_manager in GAME_MANAGERS.items():
        if game_manager.subject_in_game(subject_id):
            # Delegate to game manager
            game_manager.handle_disconnect(subject_id, reason='socket_disconnect')
            break

    # Clean up admin tracking
    if ADMIN_AGGREGATOR:
        ADMIN_AGGREGATOR.log_activity("disconnect", subject_id)
```

### Namespace Isolation

**Current Issue:** All game events are in the default namespace, making it hard to isolate cleanup.

**Pattern: Scene-Scoped Namespaces**

```python
class SceneNamespace(flask_socketio.Namespace):
    def __init__(self, scene_id: str, game_manager: GameManager):
        super().__init__(f'/scene/{scene_id}')
        self.scene_id = scene_id
        self.game_manager = game_manager

    def on_connect(self):
        pass  # Auth handled in main namespace

    def on_disconnect(self):
        # This only fires for this namespace
        self.game_manager.handle_disconnect(flask.request.sid)

    def on_join_game(self, data):
        # Scene-specific handling
        pass
```

## Anti-Patterns to Avoid

### Anti-Pattern 1: Implicit State Transitions

**What happens:** Checking `game.status == Active` in multiple places rather than explicit transitions.

**Current code example:**
```python
# In game_manager.py
game_was_active = (
    game.game_id in self.active_games
    and game.status in [GameStatus.Active, GameStatus.Reset]
)
```

**Why it's bad:** State can be inconsistent between `active_games` set and `game.status` attribute.

**Instead:** Use explicit state machine with atomic transitions.

### Anti-Pattern 2: Long-Lived Singletons for Per-Session Data

**What happens:** `GAME_MANAGERS[scene_id]` persists for the entire server lifetime, accumulating stale game references.

**Current code example:**
```python
# In app.py advance_scene()
if current_scene.scene_id not in GAME_MANAGERS:
    game_manager = gm.GameManager(...)
    GAME_MANAGERS[current_scene.scene_id] = game_manager
else:
    logger.info(f"Game manager already exists for scene {current_scene.scene_id}, reusing it")
```

**Why it's bad:** The GameManager's internal state (waiting_games, active_games) can contain stale entries from previous sessions.

**Instead:** Either create fresh GameManager per experiment run, or ensure complete cleanup when games end.

### Anti-Pattern 3: Cleanup in Multiple Uncoordinated Places

**What happens:** `_remove_game()`, `cleanup_game()`, `leave_game()`, and `remove_player()` all do partial cleanup.

**Why it's bad:** Easy to miss a cleanup step, leaving orphaned references.

**Instead:** Single `dispose_session()` method that calls all necessary cleanup in the correct order.

### Anti-Pattern 4: Missing Cleanup on Error Paths

**What happens:** If game creation fails partway through, partial state remains.

**Current code example:**
```python
# In _create_game()
try:
    game_id = str(uuid.uuid4())
    game = remote_game.RemoteGameV2(...)
    self.games[game_id] = game
    self.waiting_games.append(game_id)
    # ... more setup
    if self.scene.pyodide_multiplayer:
        self.pyodide_coordinator.create_game(...)  # If this fails, game is orphaned
except Exception as e:
    # Only emits error, doesn't clean up partial state
    self.sio.emit("create_game_failed", ...)
```

**Instead:** Use try/finally or context managers to ensure cleanup on all paths.

### Anti-Pattern 5: Relying on GC for Cleanup

**What happens:** Expecting Python garbage collection to clean up WebSocket rooms, timers, or greenlets.

**Why it's bad:**
- Greenlets with cyclic references may never be collected ([greenlet GC docs](https://greenlet.readthedocs.io/en/stable/greenlet_gc.html))
- WebSocket rooms are server-side state, not Python objects
- Timers/background tasks continue running until explicitly cancelled

**Instead:** Explicit cleanup in state machine exit actions.

## Recommendations for v1.12

### Immediate Fixes (Bug Fixes)

1. **Add session state tracking to GameManager**
   - Add `session_states: Dict[str, SessionState]` to track each game's lifecycle
   - Check state before adding players: reject if not in WAITING state
   - Check state before reusing GameManager: verify no WAITING or PLAYING games exist

2. **Ensure cleanup consistency**
   - Make `_remove_game()` idempotent
   - Call `PyodideGameCoordinator.remove_game()` from `_remove_game()` (not separately)
   - Add assertions after cleanup to verify all references removed

3. **Fix the "reusing" path**
   - When "Game manager already exists", validate its internal state is clean
   - If stale games exist, clean them up before reusing

### Medium-Term (Matchmaker Abstraction)

4. **Introduce SessionLifecycle coordinator**
   - Central point for all session state changes
   - Emits events that GameManager and PyodideCoordinator subscribe to
   - Ensures consistent cleanup across components

5. **Use python-statemachine for session states**
   - Define explicit states: CREATED, WAITING, MATCHED, VALIDATING, PLAYING, ENDED, DISPOSED
   - Add transition guards (can't go from ENDED to WAITING)
   - Add lifecycle hooks for cleanup

### Long-Term (Architecture)

6. **Consider eventlet deprecation**
   - Eventlet is in maintenance mode ([GitHub discussion](https://github.com/miguelgrinberg/Flask-SocketIO/discussions/2037))
   - Migration path: threading mode or gevent
   - Plan for this before it becomes urgent

7. **Room-per-game architecture**
   - Each game gets unique room ID (current behavior)
   - Track room membership explicitly
   - Close room only after all members have left

## Confidence Assessment

| Area | Confidence | Rationale |
|------|------------|-----------|
| Root cause analysis | HIGH | Code review confirms implicit state management and scattered cleanup |
| State machine pattern | HIGH | Well-established pattern, mature Python libraries available |
| Flask-SocketIO patterns | MEDIUM | Based on official docs and community patterns, specific eventlet interactions not fully verified |
| Cleanup strategies | HIGH | Standard patterns from game server literature |
| Anti-patterns | HIGH | Directly observed in codebase |
| Eventlet deprecation | MEDIUM | Official discussions confirm, but timeline unclear |

## Sources

- [Flask-SocketIO Documentation](https://flask-socketio.readthedocs.io/en/latest/)
- [Flask-SocketIO User Session Blog Post](https://blog.miguelgrinberg.com/post/flask-socketio-and-the-user-session)
- [Greenlet Garbage Collection Documentation](https://greenlet.readthedocs.io/en/stable/greenlet_gc.html)
- [Game Programming Patterns - State](https://gameprogrammingpatterns.com/state.html)
- [python-statemachine Documentation](https://python-statemachine.readthedocs.io/en/latest/transitions.html)
- [State Management Patterns in Multiplayer Game Development](https://peerdh.com/blogs/programming-insights/state-management-patterns-in-multiplayer-game-development)
- [Beyond If-Else Hell: Elegant State Machines in Game Development](https://dev.to/niraj_gaming/beyond-if-else-hell-elegant-state-machines-pattern-in-game-development-2i7g)
- [Handling WebSocket Disconnections in FastAPI](https://hexshift.medium.com/handling-websocket-disconnections-gracefully-in-fastapi-9f0a1de365da)
- [Socket.IO Tutorial - Handling Disconnections](https://socket.io/docs/v4/tutorial/handling-disconnections)
- [Flask-SocketIO and Eventlet Future Discussion](https://github.com/miguelgrinberg/Flask-SocketIO/discussions/2037)
- [Building Real-Time Multiplayer Game Server with Socket.io](https://dev.to/dowerdev/building-a-real-time-multiplayer-game-server-with-socketio-and-redis-architecture-and-583m)
