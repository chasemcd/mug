# Pitfalls Research: Matchmaking & Lobby Bugs

**Domain:** Multiplayer matchmaking and lobby/waiting room systems
**Researched:** 2026-02-02
**Confidence:** HIGH (verified against codebase analysis, official Unity/PlayFab docs, and community post-mortems)

## Executive Summary

The "Start button disappears but nothing happens" bug is a **stale GameManager capture** problem - a classic pitfall in multiplayer lobby systems. When `GAME_MANAGERS` is keyed by `scene_id` and GameManagers are reused across game sessions, new participants get routed to a GameManager whose internal state (games, waiting queues) reflects a previous completed game. The participant joins what they believe is a fresh waiting room but is actually captured by state leftover from a completed game.

This research documents the root cause, related pitfalls in multiplayer matchmaking, and prevention strategies for v1.12.

---

## Stale State Bugs

### The Core Problem: GameManager Reuse Without Reset

**What happens:**
1. Participants A and B complete a game on scene "game_scene_1"
2. GameManager for "game_scene_1" remains in `GAME_MANAGERS` dict
3. Individual games are cleaned up via `cleanup_game()`, but the GameManager persists
4. New participant C arrives, advances to "game_scene_1"
5. Code checks `if current_scene.scene_id not in GAME_MANAGERS` - it IS in there
6. Logs "Game manager already exists for scene X, reusing it"
7. Participant C calls `join_game` on a GameManager with stale internal state
8. Depending on state, participant may be stuck in limbo

**Why it's insidious:**
The bug only manifests when:
- A previous session fully completed
- A new participant arrives at the same scene later
- The server hasn't restarted

**Evidence from codebase:**
```python
# app.py lines 491-508
if current_scene.scene_id not in GAME_MANAGERS:
    logger.info(f"Instantiating game manager for scene {current_scene.scene_id}")
    game_manager = gm.GameManager(...)
    GAME_MANAGERS[current_scene.scene_id] = game_manager
else:
    logger.info(f"Game manager already exists for scene {current_scene.scene_id}, reusing it")
```

The "reusing it" path doesn't verify the GameManager's internal state is clean for new participants.

**Prevention:**
1. **Explicit lifecycle boundaries:** GameManager should either be deleted after its last participant leaves, OR it should have a `reset()` method called before routing new participants
2. **Per-session GameManagers:** Key by `(scene_id, session_epoch)` instead of just `scene_id`
3. **State validation on join:** Before routing participant to GameManager, validate the manager is in an appropriate state (no active games, waiting queue is fresh)

---

### Stale State Variants

#### Variant 1: Stale Waiting Queue

**What goes wrong:** Previous participants left the waiting queue without cleanup. New participant joins, sees "1/2 players waiting" but the other player is a ghost reference.

**Warning signs:**
- `len(game_manager.waiting_games) > 0` when no active participants exist
- Subject IDs in waiting queue don't correspond to connected sockets

**Prevention:**
```python
def validate_waiting_queue(self):
    """Remove ghost entries from waiting queue."""
    valid_games = []
    for game_id in self.waiting_games:
        game = self.games.get(game_id)
        if game and game.cur_num_human_players() > 0:
            # Verify each player is still connected
            for subject_id in game.human_players.values():
                if subject_id in CONNECTED_SUBJECTS:
                    valid_games.append(game_id)
                    break
    self.waiting_games = valid_games
```

#### Variant 2: Stale Subject Mappings

**What goes wrong:** `subject_games` and `subject_rooms` dicts retain mappings for disconnected subjects. New subject with same ID (UUID collision or reused session) inherits corrupted state.

**Warning signs:**
- `subject_id in game_manager.subject_games` returns True for a freshly joined participant
- Log shows "Subject X already in game Y" for first-time participant

**Prevention:**
- Clear mappings on disconnect: `del subject_games[subject_id]`, `del subject_rooms[subject_id]`
- Validate mappings point to valid games before use
- Use unique subject IDs per connection (not reused across sessions)

#### Variant 3: Active Game Flag Stuck

**What goes wrong:** A game's status (active vs waiting) gets stuck after abnormal termination. New participants routed to what looks like "waiting" but is actually a terminated game.

**Warning signs:**
- `game_id in game_manager.active_games` but game has no players
- `game.game_state` indicates terminated but wasn't cleaned up

**Prevention:**
- Invariant check: Active games must have players
- Cleanup routine that removes empty games from `active_games` set

---

## Race Conditions in Matching

### Race 1: Concurrent Join to Same Waiting Game

**What goes wrong:**
Two participants call `join_game` simultaneously. Both see one open slot. Both get added, exceeding expected player count.

**Timeline:**
```
T1: Participant A checks: 1 slot available
T2: Participant B checks: 1 slot available
T3: Participant A added to game
T4: Participant B added to game
T5: Game has 3 players, expected 2
```

**Why it happens:**
The check-then-add pattern without locking:
```python
# DANGEROUS: Not atomic
if game.has_available_slot():
    self._add_subject_to_game(subject_id, game)
```

**Prevention:**
```python
# Use lock around check-and-add
with self.waiting_games_lock:
    with game.lock:
        if game.has_available_slot():
            self._add_subject_to_game(subject_id, game)
```

The codebase has `waiting_games_lock` but it's crucial to ensure ALL paths use it.

---

### Race 2: Game Starts While Player Joining

**What goes wrong:**
Player A and B are in waiting room. Player C joins, triggering game start. But C's `join_game` hasn't finished - they're in limbo between "added to game" and "received game_start event."

**Timeline:**
```
T1: C calls join_game
T2: C added to game.human_players
T3: game.is_ready_to_start() returns True
T4: start_game() called, emits "game_started"
T5: C's join_game handler still running, hasn't registered socket listeners
T6: C misses "game_started" event
```

**Warning signs:**
- Participant sees "Joining game..." forever
- Server logs show participant in game, but client never transitions

**Prevention:**
1. **Acknowledgment pattern:** Don't start game until all participants have acknowledged readiness
2. **Re-emit on join:** After adding participant, if game is active, re-send current state
3. **Client-side timeout:** If no game state received within N seconds, re-request

---

### Race 3: Disconnect During Matching

**What goes wrong:**
Player A joins waiting room, gets paired with B. A disconnects before game starts. B is stuck waiting, or worse, game starts 1v0.

**Timeline:**
```
T1: A and B in waiting room, matched
T2: A disconnects (socket close)
T3: Game start triggered (B only)
T4: B enters game alone (no partner)
```

**Warning signs:**
- Single-player in supposedly multiplayer game
- Partner placeholder remains "Available" at game start

**Prevention:**
```python
def start_game(self, game):
    # Validate all expected players are still connected
    actual_players = game.cur_num_human_players()
    expected_players = self.scene.num_human_players

    if actual_players < expected_players:
        logger.warning(f"Game {game.game_id} has {actual_players}/{expected_players} players. Aborting start.")
        self._return_players_to_pool(game)
        return

    # Proceed with start
    self.active_games.add(game.game_id)
    # ...
```

---

### Race 4: Double-Add from Rapid Clicks

**What goes wrong:**
User clicks "Start" button rapidly or network retry sends duplicate `join_game` events. Same participant added twice.

**Warning signs:**
- Same `subject_id` appears twice in `game.human_players`
- Error: "Subject X already in game"

**Prevention:**
```javascript
// Client-side debounce
let joinInProgress = false;
function handleStartClick() {
    if (joinInProgress) return;
    joinInProgress = true;
    socket.emit('join_game', {...});
}

// Server-side idempotency
def join_game(self, subject_id):
    if subject_id in self.subject_games:
        logger.info(f"Subject {subject_id} already in game, ignoring duplicate join")
        return
```

---

## Routing Bugs

### Bug 1: Participant Sent to Wrong Scene's GameManager

**What goes wrong:**
Participant's stager says they're on scene A, but they get routed to GameManager for scene B.

**How it happens:**
- Stager state corrupted
- `current_scene_id` not updated after `advance_scene`
- Cache staleness between client and server

**Warning signs:**
- Client shows scene A content, server logs show scene B
- Actions/events don't match expected scene behavior

**Prevention:**
- Always derive current scene from authoritative stager state
- Validate scene matches before routing to GameManager:
```python
def join_game(data):
    subject_id = get_subject_id_from_session_id(flask.request.sid)
    participant_stager = STAGERS.get(subject_id)
    current_scene = participant_stager.current_scene

    # Validate scene type
    if not isinstance(current_scene, gym_scene.GymScene):
        logger.error(f"Subject {subject_id} tried to join game from non-gym scene")
        return

    # Get correct GameManager
    game_manager = GAME_MANAGERS.get(current_scene.scene_id)
    if game_manager is None:
        logger.error(f"No GameManager for scene {current_scene.scene_id}")
        return
```

---

### Bug 2: Participant Routed to In-Progress Game

**What goes wrong:**
New participant joins and gets added to an active, in-progress game instead of waiting room.

**How it happens:**
- Waiting/active distinction not checked
- Game has "available" slots that should only be for waiting phase
- Matchmaking logic doesn't filter by game state

**Warning signs:**
- Participant joins mid-match, sees game in progress
- Other players see new player appear suddenly during gameplay

**Prevention:**
```python
def add_subject_to_game(self, subject_id):
    # Find game in WAITING state only
    for game_id in self.waiting_games:  # Not self.games.keys()
        game = self.games[game_id]
        if game.has_available_slot() and game_id not in self.active_games:
            return self._add_subject_to_game(subject_id, game)

    # No suitable waiting game, create new one
    return self._create_game_and_add_subject(subject_id)
```

---

### Bug 3: Scene ID Mismatch After Navigation

**What goes wrong:**
Participant navigates browser (back button, refresh), their stager advances but GameManager lookup uses old scene_id.

**How it happens:**
- Browser navigation triggers `advance_scene` but client state is stale
- Session restoration doesn't sync scene_id correctly

**Warning signs:**
- "No GameManager for scene X" errors
- Participant stuck on loading screen after navigation

**Prevention:**
- Session restoration must restore complete stager state
- `advance_scene` must update `PARTICIPANT_SESSIONS[subject_id].current_scene_id`
- Client-side state must be re-fetched on page load, not cached

---

## Cleanup Failures

### Failure 1: Game Ends But GameManager Persists with Stale State

**What goes wrong:**
`cleanup_game(game_id)` removes game from `games` dict but doesn't clean up:
- Entries in `subject_games`
- Entries in `subject_rooms`
- References in `active_games`
- Entries in `waiting_games`

**Current cleanup chain:**
```python
def cleanup_game(self, game_id):
    game = self.games[game_id]
    # ... persist groups, callback ...
    game.tear_down()
    self._remove_game(game_id)  # Only removes from games dict and waiting_games

def _remove_game(self, game_id):
    with self.waiting_games_lock:
        if game_id in self.waiting_games:
            self.waiting_games.remove(game_id)
    if game_id in self.games:
        del self.games[game_id]
    # NOTE: Doesn't clean subject_games, subject_rooms, active_games
```

**Prevention:**
```python
def cleanup_game(self, game_id):
    game = self.games.get(game_id)
    if game is None:
        return

    # Clean all subject mappings
    for subject_id in list(game.human_players.values()):
        if subject_id and subject_id != utils.Available:
            self.subject_games.pop(subject_id, None)
            self.subject_rooms.pop(subject_id, None)

    # Clean game state
    self.active_games.discard(game_id)

    # Then remove game
    game.tear_down()
    self._remove_game(game_id)
```

---

### Failure 2: WebSocket Room Not Closed

**What goes wrong:**
Game ends, but SocketIO room persists. New game with same room ID (if game_id reused, though UUID makes this rare) gets cross-talk.

**More common variant:** Participants leave room via `flask_socketio.leave_room()` but server-side room tracking isn't updated.

**Warning signs:**
- Events broadcast to wrong participants
- Participant receives events from games they're not in

**Prevention:**
- Always call `leave_room` for all participants before game deletion
- Use unique room IDs (UUID) that are never reused

---

### Failure 3: Timeout Handler Not Cancelled

**What goes wrong:**
Waiting room has a timeout (e.g., 30s to find partner). Game starts successfully, but timeout handler still fires later, trying to cleanup or redirect participants who are now in active game.

**Warning signs:**
- Active game suddenly ends with "timeout" message
- Participants kicked during gameplay

**Prevention:**
```python
def start_game(self, game):
    # Cancel any pending timeout
    timeout_handle = self.waitroom_timeouts.pop(game.game_id, None)
    if timeout_handle:
        timeout_handle.cancel()  # greenlet.cancel() or equivalent

    # Proceed with game start
    self.active_games.add(game.game_id)
```

---

### Failure 4: Pyodide Coordinator Not Cleaned

**What goes wrong:**
GameManager cleans up its state, but `PyodideGameCoordinator` still has references. New game created, coordinator has conflicting state from previous game.

**Evidence from codebase:**
The coordinator tracks games independently:
```python
# In pyodide_game_coordinator.py
self.games: dict[GameID, PyodideGameState] = {}
```

**Warning signs:**
- "Game already exists in coordinator" errors
- Player state from previous game leaks into new game

**Prevention:**
- GameManager.cleanup_game must call coordinator.remove_game()
- Verify coordinator state is clean before creating new game

---

## Detection Strategies

### Strategy 1: Invariant Assertions

Add runtime checks that should always be true:

```python
def assert_invariants(self):
    """Call periodically or after state changes."""
    # Every subject in subject_games should have a valid game
    for subject_id, game_id in self.subject_games.items():
        assert game_id in self.games, f"Stale subject_games entry: {subject_id} -> {game_id}"

    # Every active game should have players
    for game_id in self.active_games:
        game = self.games.get(game_id)
        assert game is not None, f"Active game {game_id} doesn't exist"
        assert game.cur_num_human_players() > 0, f"Active game {game_id} has no players"

    # Every waiting game should not be active
    for game_id in self.waiting_games:
        assert game_id not in self.active_games, f"Game {game_id} in both waiting and active"
```

### Strategy 2: State Logging on Transitions

Log complete state snapshots at key transitions:

```python
def log_state_snapshot(self, event_name: str, subject_id: str = None):
    logger.info(f"STATE [{event_name}] subject={subject_id} "
                f"games={len(self.games)} "
                f"active={len(self.active_games)} "
                f"waiting={len(self.waiting_games)} "
                f"subject_games={len(self.subject_games)}")
```

Call at: `join_game`, `leave_game`, `start_game`, `cleanup_game`

### Strategy 3: Heartbeat Validation

Periodically verify connected participants match server state:

```python
def heartbeat_validation(self):
    """Run every 30 seconds."""
    connected_sockets = set(socketio.server.rooms.keys())  # Simplified

    for subject_id in list(self.subject_games.keys()):
        socket_id = get_socket_for_subject(subject_id)
        if socket_id not in connected_sockets:
            logger.warning(f"Subject {subject_id} in subject_games but not connected")
            self.cleanup_disconnected_subject(subject_id)
```

### Strategy 4: Timeout-Based Cleanup

Set a maximum lifetime for game states:

```python
MAX_GAME_AGE = 3600  # 1 hour

def cleanup_stale_games(self):
    """Run periodically."""
    now = time.time()
    for game_id, game in list(self.games.items()):
        if now - game.created_at > MAX_GAME_AGE:
            logger.warning(f"Game {game_id} exceeded max age, cleaning up")
            self.cleanup_game(game_id)
```

---

## Likely Root Causes for Known Bug

The "Start button disappears but nothing happens" bug based on the reported symptoms:

1. **Console shows "Joining game in session [ID]"** - Client successfully emits `join_game`
2. **UI doesn't change** - Server doesn't emit `join_game_success` or `waiting_room` event, OR client handler not firing
3. **Server shows "Game manager already exists for scene X, reusing it"** - Confirms GameManager reuse path taken
4. **Happens after previous participants completed their game** - Confirms stale state scenario

### Most Likely Root Cause

**Stale waiting queue with ghost game:**

```
1. Previous game completed, cleanup_game called
2. cleanup_game removed game from self.games dict
3. But waiting_games list may have been partially modified or another game was created during cleanup
4. New participant joins, add_subject_to_game finds a "waiting" game
5. The "waiting" game is actually in a broken state or full
6. Participant is "added" but no slot actually available
7. No waiting_room event emitted because internal state inconsistent
```

### Alternative Root Cause

**Subject already in subject_games:**

```
1. Previous participant disconnected uncleanly
2. Their subject_id remains in subject_games pointing to old game_id
3. New participant (by coincidence or session reuse) has same subject_id
4. join_game checks subject_games[subject_id], finds existing entry
5. Returns early without adding to new game
6. But no feedback sent to client
```

### Verification Steps

1. Add logging at start of `join_game` handler:
```python
logger.info(f"join_game called: subject={subject_id}, already_in_game={subject_id in game_manager.subject_games}")
```

2. Add logging in `add_subject_to_game`:
```python
logger.info(f"add_subject_to_game: subject={subject_id}, waiting_games={self.waiting_games}, subject_games={self.subject_games}")
```

3. Check if `waiting_room` or error event is emitted (add logging to both paths)

---

## Prevention Strategies

### Strategy 1: Per-Session GameManager Lifecycle

Instead of reusing GameManagers, create fresh ones per "matching session":

```python
def advance_scene(data):
    # ...
    if isinstance(current_scene, gym_scene.GymScene):
        # Always create fresh GameManager
        session_key = f"{current_scene.scene_id}_{uuid.uuid4()}"
        game_manager = gm.GameManager(scene=current_scene, ...)
        GAME_MANAGERS[session_key] = game_manager

        # Store session_key in participant session for routing
        PARTICIPANT_SESSIONS[subject_id].game_manager_key = session_key
```

### Strategy 2: GameManager State Validation on Route

Before routing participant to GameManager, validate state:

```python
def join_game(data):
    subject_id = get_subject_id_from_session_id(flask.request.sid)
    game_manager = get_game_manager_for_subject(subject_id)

    # Validate GameManager is ready to accept
    if not game_manager.can_accept_new_participant():
        logger.error(f"GameManager for {subject_id} cannot accept new participants")
        # Either create fresh GameManager or return error
        socketio.emit("join_game_error", {"message": "Please refresh the page"}, room=flask.request.sid)
        return

    game_manager.add_subject_to_game(subject_id)
```

### Strategy 3: Explicit State Machine for Game Lifecycle

Define clear states and valid transitions:

```
States: WAITING_FOR_PLAYERS -> STARTING -> ACTIVE -> ENDING -> TERMINATED

Valid transitions:
- WAITING_FOR_PLAYERS -> STARTING (when enough players)
- WAITING_FOR_PLAYERS -> TERMINATED (timeout or all players left)
- STARTING -> ACTIVE (all players confirmed ready)
- STARTING -> TERMINATED (player disconnected during start)
- ACTIVE -> ENDING (game logic finished)
- ACTIVE -> TERMINATED (abnormal end)
- ENDING -> TERMINATED (cleanup complete)

Each state has allowed operations:
- WAITING_FOR_PLAYERS: add_player, remove_player
- STARTING: confirm_ready
- ACTIVE: game_action
- ENDING: none
- TERMINATED: none (cleanup happens here)
```

### Strategy 4: Comprehensive Cleanup Routine

Ensure ALL state is cleaned on game end:

```python
def cleanup_game(self, game_id: GameID):
    """Comprehensive cleanup - no state leakage."""
    game = self.games.get(game_id)
    if game is None:
        logger.warning(f"cleanup_game called for non-existent game {game_id}")
        return

    # 1. Cancel pending timers
    timeout = self.waitroom_timeouts.pop(game_id, None)
    if timeout:
        timeout.cancel()

    # 2. Clean subject mappings
    for subject_id in list(game.human_players.values()):
        if subject_id and subject_id != utils.Available:
            self.subject_games.pop(subject_id, None)
            self.subject_rooms.pop(subject_id, None)
            # Leave SocketIO room
            try:
                flask_socketio.leave_room(game_id, sid=get_socket_for_subject(subject_id))
            except:
                pass

    # 3. Clean game state collections
    self.active_games.discard(game_id)
    with self.waiting_games_lock:
        if game_id in self.waiting_games:
            self.waiting_games.remove(game_id)
    if game_id in self.reset_events:
        del self.reset_events[game_id]

    # 4. Clean coordinator state
    if self.pyodide_coordinator:
        self.pyodide_coordinator.remove_game(game_id)

    # 5. Invoke callbacks
    if self.scene.callback is not None:
        self.scene.callback.on_game_end(game)

    # 6. Tear down game object
    game.tear_down()

    # 7. Remove from games dict
    del self.games[game_id]

    # 8. Verify invariants
    self.assert_invariants()

    logger.info(f"Cleanup complete for game {game_id}")
```

---

## Recommendations for v1.12

### Priority 1: Fix the Immediate Bug

1. **Add diagnostic logging** to understand exact failure path
2. **Add state validation** in `join_game` handler
3. **Clean subject_games/subject_rooms** in all cleanup paths
4. **Add invariant checks** that run after each state mutation

### Priority 2: Prevent Future Bugs

5. **Implement GameManager reset** or per-session managers
6. **Add comprehensive cleanup_game** that covers all state
7. **Add periodic health check** that validates state consistency
8. **Add client-side timeout** that shows error if stuck

### Priority 3: Observability

9. **State machine logging** at every transition
10. **Metrics** for: games created, games cleaned, avg wait time, join failures
11. **Admin dashboard** showing current GameManager state

### Implementation Order

| Phase | Task | Addresses |
|-------|------|-----------|
| 1 | Diagnostic logging in join_game | Understanding bug |
| 1 | State validation before routing | Immediate prevention |
| 2 | Comprehensive cleanup_game | Cleanup failures |
| 2 | Subject mappings cleanup on disconnect | Stale state |
| 3 | Per-session GameManager OR reset() | Root cause |
| 3 | Invariant assertions | Early detection |
| 4 | Client-side timeout/retry | UX resilience |
| 4 | Health check periodic task | Ongoing monitoring |

---

## Confidence Assessment

| Area | Confidence | Rationale |
|------|------------|-----------|
| Root cause identification | HIGH | Codebase analysis shows clear path from symptom to cause |
| Race condition patterns | HIGH | Well-documented patterns in multiplayer literature |
| Cleanup failures | HIGH | Direct code inspection shows incomplete cleanup |
| Prevention strategies | MEDIUM | Standard patterns, need testing in this codebase |
| Implementation order | MEDIUM | Based on research, may need adjustment based on exploration |

---

## Sources

- [Unity Game Server Hosting: Server Lifecycle](https://docs.unity.com/ugs/en-us/manual/game-server-hosting/manual/concepts/server-lifecycle) - Multi-session allocation patterns, cleanup between sessions
- [PlayFab Multiplayer Server Lifecycle](https://learn.microsoft.com/en-us/gaming/playfab/multiplayer/servers/multiplayer-game-server-lifecycle) - Game server state management
- [Game Programming Patterns: Singleton](https://gameprogrammingpatterns.com/singleton.html) - Problems with global state in games
- [Game Programming Patterns: State](https://gameprogrammingpatterns.com/state.html) - Finite state machines for game logic
- [DEV Community: Handling Race Conditions in Real-Time Apps](https://dev.to/mattlewandowski93/handling-race-conditions-in-real-time-apps-49c8) - WebSocket race condition patterns
- [Unity Discussions: Singleton Race Conditions](https://discussions.unity.com/t/solved-potential-race-conditions-using-singleton/708852) - Thread safety in singletons
- [GameDev.net: Ping-Related Race Conditions](https://www.gamedev.net/forums/topic/703815-how-to-prevent-race-condition-bugs-due-to-ping/) - Network timing race conditions
- [Unity Multiplayer: Ownership Race Conditions](https://docs-multiplayer.unity3d.com/netcode/current/basics/race-conditions/) - Distributed authority pitfalls
- [GDevelop Forum: Multiplayer Lobby Bug](https://forum.gdevelop.io/t/multiplayer-lobby-bug/58689) - Stale state after leaving game
- [GameSparks: Real-Time Multiplayer Challenges](https://www.gamesparks.com/blog/four-tips-for-solving-technical-challenges-when-running-a-real-time-multiplayer-game/) - Server scalability and matching
- [Gamasutra: Matchmaking Requirements](https://www.gamedeveloper.com/design/the-requirements-of-good-matchmaking) - Player pool splitting, wait time management
- [AWS GameLift: Player Session Routing](https://repost.aws/questions/QUq4v0QEpzQcah5VMkt-YDpg/playersessionids-only-accepted-sometimes-by-gamelift-server) - Session ID routing bugs
- Interactive Gym codebase: `app.py`, `game_manager.py` - Direct analysis of implementation
