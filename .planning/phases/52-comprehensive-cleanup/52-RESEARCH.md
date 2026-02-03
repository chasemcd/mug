# Phase 52: Comprehensive Cleanup - Research

**Researched:** 2026-02-02
**Domain:** Game state management and cleanup in Flask-SocketIO multiplayer framework
**Confidence:** HIGH

## Summary

This phase addresses a critical bug where new participants are sometimes routed to stale game sessions. Research into the codebase reveals that state is tracked across multiple data structures (subject_games, subject_rooms, active_games, waiting_games, and the PYODIDE_COORDINATOR.games dictionary), with cleanup scattered across different exit paths. The core problem is that cleanup_game() in GameManager does not clean subject_games and subject_rooms, leaving orphaned entries when games end.

The existing Phase 51 diagnostic logging has added validate_subject_state() which performs self-healing cleanup on join_game, but this is reactive rather than proactive. A comprehensive solution requires making cleanup_game() idempotent and ensuring it runs on ALL exit paths, cleaning ALL state tracking structures.

**Primary recommendation:** Modify cleanup_game() to unconditionally clean subject_games and subject_rooms for all players in the game, make it idempotent (safe to call multiple times), and ensure it is called on every exit path including normal completion, partner disconnect, exclusion, timeout, and socket disconnect.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Flask-SocketIO | Current | WebSocket communication | Already in use, handles disconnect events |
| eventlet | Current | Concurrency primitives | Already in use for async game loops |
| ThreadSafeDict/Set | Custom | Thread-safe state containers | Already implemented in utils.py |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| threading.Lock | stdlib | Mutual exclusion | Protect critical sections during cleanup |
| contextlib | stdlib | Resource management | For cleanup context managers |

**Installation:** No new packages required - using existing stack.

## Architecture Patterns

### Current State Tracking Structure

The codebase tracks player-game associations in multiple places:

```
GameManager (per-scene):
├── subject_games: dict[SubjectID, GameID]    # Maps subject to their game
├── subject_rooms: dict[SubjectID, RoomID]    # Maps subject to their room (same as game_id)
├── active_games: set[GameID]                 # Games currently in play
├── waiting_games: list[GameID]               # Games waiting for players
├── games: dict[GameID, RemoteGameV2]         # Actual game objects
├── waitroom_timeouts: dict[GameID, float]    # Timeout timestamps
├── reset_events: dict[GameID, dict]          # Per-player reset events
├── group_waitrooms: dict[str, list]          # Group-based waiting rooms
└── group_wait_start_times: dict[SubjectID, float]

PyodideGameCoordinator (global):
├── games: dict[str, PyodideGameState]        # Pyodide game state
│   └── PyodideGameState:
│       ├── players: dict[player_id, socket_id]
│       └── player_subjects: dict[player_id, subject_id]
```

### Pattern 1: Centralized Cleanup Method

**What:** Single cleanup method that handles ALL state cleanup for a game.
**When to use:** When a game ends for any reason.
**Current Implementation (with gaps):**

```python
# From game_manager.py cleanup_game() - CURRENT
def cleanup_game(self, game_id: GameID):
    """End a game and persist player groups."""
    game = self.games[game_id]  # <-- BUG: Can crash if game already removed

    # Always record player groups when a game ends
    if self.pairing_manager:
        subject_ids = list(game.human_players.values())
        real_subjects = [sid for sid in subject_ids if sid != utils.Available and sid is not None]
        if len(real_subjects) > 1:
            self.pairing_manager.create_group(real_subjects, self.scene.scene_id)

    if self.scene.callback is not None:
        self.scene.callback.on_game_end(game)

    game.tear_down()
    self._remove_game(game_id)
    # <-- MISSING: Does NOT clean subject_games or subject_rooms!
```

**Recommended Implementation:**

```python
def cleanup_game(self, game_id: GameID):
    """End a game and clean up ALL associated state.

    Idempotent: safe to call multiple times for the same game_id.
    """
    # Guard: make idempotent
    if game_id not in self.games:
        logger.debug(f"cleanup_game called for already-cleaned game {game_id}")
        return

    game = self.games[game_id]

    # Record player groups before cleanup
    if self.pairing_manager:
        subject_ids = list(game.human_players.values())
        real_subjects = [sid for sid in subject_ids if sid != utils.Available and sid is not None]
        if len(real_subjects) > 1:
            self.pairing_manager.create_group(real_subjects, self.scene.scene_id)

    # Clean up subject tracking for ALL players in this game
    for subject_id in list(game.human_players.values()):
        if subject_id and subject_id != utils.Available:
            if subject_id in self.subject_games:
                del self.subject_games[subject_id]
            if subject_id in self.subject_rooms:
                del self.subject_rooms[subject_id]

    if self.scene.callback is not None:
        self.scene.callback.on_game_end(game)

    game.tear_down()
    self._remove_game(game_id)
```

### Pattern 2: Idempotent Cleanup

**What:** Cleanup methods that are safe to call multiple times.
**When to use:** When cleanup may be triggered from multiple exit paths.
**Example:**

```python
def cleanup_game(self, game_id: GameID):
    """Idempotent cleanup - safe to call multiple times."""
    # Early return if already cleaned
    if game_id not in self.games:
        logger.debug(f"cleanup_game: game {game_id} already cleaned")
        return

    # ... perform cleanup ...
```

### Anti-Patterns to Avoid

- **Accessing dict before checking existence:** `game = self.games[game_id]` without checking if game_id in self.games
- **Partial cleanup:** Cleaning some structures (games, active_games) but not others (subject_games, subject_rooms)
- **Non-idempotent cleanup:** Methods that crash if called twice
- **Silent failures:** Swallowing errors during cleanup without logging

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Thread-safe dict operations | Manual locking on dict | ThreadSafeDict from utils.py | Already handles locking correctly |
| Socket room management | Manual room tracking | flask_socketio.close_room() | Handles all cleanup automatically |
| Multiple cleanup paths | Duplicating cleanup code | Single cleanup_game() method | DRY principle, single source of truth |

**Key insight:** The codebase already has cleanup logic in `_remove_game()` for game-level structures. The gap is that `cleanup_game()` doesn't clean subject-level mappings.

## Common Pitfalls

### Pitfall 1: Incomplete State Cleanup

**What goes wrong:** Subject-to-game mappings (subject_games, subject_rooms) are not cleaned when a game ends, causing new join attempts to find stale entries.
**Why it happens:** cleanup_game() delegates to _remove_game() which cleans game-level structures but not subject-level structures.
**How to avoid:** Explicitly clean subject_games and subject_rooms in cleanup_game() before calling _remove_game().
**Warning signs:** Logs showing "Subject X has stale game entry" or "Game manager already exists, reusing it"

### Pitfall 2: Race Conditions in Cleanup

**What goes wrong:** Multiple paths trigger cleanup simultaneously, causing double-cleanup errors or missed cleanup.
**Why it happens:** disconnect handler, leave_game, and game loop completion can all try to clean up the same game.
**How to avoid:** Make cleanup_game() idempotent by checking if game_id is still in self.games before proceeding.
**Warning signs:** KeyError exceptions during cleanup, or "game already cleaned" log messages

### Pitfall 3: PyodideCoordinator State Orphaned

**What goes wrong:** Games cleaned from GameManager but not from PYODIDE_COORDINATOR, or vice versa.
**Why it happens:** Two separate systems tracking game state with different cleanup paths.
**How to avoid:** Always clean BOTH systems on any exit path.
**Warning signs:** Coordinator shows active games that don't exist in GameManager

### Pitfall 4: Subject Still in Game After Cleanup

**What goes wrong:** game_manager.subject_in_game(subject_id) returns True after cleanup_game() is called.
**Why it happens:** cleanup_game() calls _remove_game() which does not clean subject_games.
**How to avoid:** Explicitly clean subject_games[subject_id] and subject_rooms[subject_id] in cleanup_game().
**Warning signs:** "Subject already in game" errors on re-join

## Code Examples

### Current _remove_game() Implementation (Reference)

```python
# From game_manager.py - what it DOES clean
def _remove_game(self, game_id: GameID) -> None:
    """Remove a game from the server."""
    with self.waiting_games_lock:
        if game_id in self.waiting_games:
            self.waiting_games.remove(game_id)

    if game_id in self.games:
        del self.games[game_id]
    if game_id in self.reset_events:
        del self.reset_events[game_id]
    if game_id in self.waitroom_timeouts:
        del self.waitroom_timeouts[game_id]
    if game_id in self.active_games:
        self.active_games.remove(game_id)

    self.sio.close_room(game_id)
    # NOTE: Does NOT clean subject_games or subject_rooms!
```

### Current validate_subject_state() (Phase 51 Self-Healing)

```python
# From game_manager.py - reactive cleanup on join
def validate_subject_state(self, subject_id: SubjectID) -> tuple[bool, str | None]:
    """Validate subject state before adding to a game."""
    # Check for orphaned subject_games entry
    if subject_id in self.subject_games:
        game_id = self.subject_games[subject_id]
        if game_id not in self.games:
            logger.warning(f"[StateValidation] Subject {subject_id} has orphaned subject_games entry.")
            # Clean up orphaned entry
            del self.subject_games[subject_id]
            if subject_id in self.subject_rooms:
                del self.subject_rooms[subject_id]
            return (True, None)  # Cleaned up, can proceed
    # ... more validation ...
```

### Exit Paths That Trigger Cleanup

```python
# 1. Normal game completion (server-side game loop)
# In game_manager.py run_server_game():
if game.status != remote_game.GameStatus.Inactive:
    game.tear_down()
if self.scene.callback is not None:
    self.scene.callback.on_game_end(game)
self.sio.emit("end_game", {}, room=game.game_id)
self.cleanup_game(game.game_id)

# 2. Partner disconnect during active game
# In game_manager.py leave_game():
if game_was_active and not game_is_empty:
    self.sio.emit("end_game", {"message": "..."}, room=game.game_id)
    eventlet.sleep(0.1)
    self.cleanup_game(game_id)

# 3. Pyodide game disconnect
# In app.py on_disconnect():
PYODIDE_COORDINATOR.remove_player(game_id=game_id, player_id=player_id, notify_others=True)
# NOTE: This does NOT call cleanup_game() on GameManager!

# 4. Mid-game exclusion (ping/tab issues)
# In pyodide_game_coordinator.py handle_player_exclusion():
if game.server_runner:
    game.server_runner.stop()
del self.games[game_id]  # Only cleans coordinator, not GameManager!

# 5. Socket disconnect handler
# In app.py on_disconnect():
if is_in_active_gym_scene:
    game_manager.leave_game(subject_id=subject_id)  # This calls cleanup_game
else:
    game_manager.remove_subject_quietly(subject_id)  # This does NOT call cleanup_game!
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Separate cleanup per exit path | Centralized cleanup_game() | Existing | Reduced duplication but incomplete |
| No state validation | validate_subject_state() on join | Phase 51 | Self-healing but reactive |
| No diagnostic logging | Full state snapshot logging | Phase 51 | Better debugging |

**Deprecated/outdated:**
- Manual cleanup in each exit handler: Should be replaced with single cleanup_game() call
- Trusting state to be clean after _remove_game(): Must explicitly clean subject mappings

## Open Questions

Things that couldn't be fully resolved:

1. **GameManager reuse across scenes**
   - What we know: GameManager is created per-scene and reused if scene_id matches
   - What's unclear: Should GameManager be cleaned up when a scene completes for all users?
   - Recommendation: Leave as-is for now, ensure per-game cleanup is complete

2. **PyodideCoordinator/GameManager synchronization**
   - What we know: Both systems track games independently
   - What's unclear: Best pattern for coordinated cleanup
   - Recommendation: Call cleanup on both systems from same exit path

## Exit Path Analysis

### All Identified Exit Paths

| Exit Path | Current Handler | Calls cleanup_game? | Cleans PyodideCoordinator? | Gap |
|-----------|-----------------|---------------------|----------------------------|-----|
| Normal game completion | run_server_game | YES | N/A (server games) | None |
| Partner disconnect (active) | leave_game | YES | NO | Missing coordinator cleanup |
| All players leave waiting | leave_game | YES | YES (via leave_game) | None |
| Socket disconnect (active) | on_disconnect -> leave_game | YES | YES (separate path) | None |
| Socket disconnect (inactive) | on_disconnect -> remove_subject_quietly | NO | YES (separate path) | Missing cleanup_game |
| Mid-game exclusion | handle_player_exclusion | NO | YES | Missing GameManager cleanup |
| P2P validation failure | handle_p2p_validation_failed | Partial | YES | Subject cleanup done manually |
| Reconnection timeout | handle_p2p_reconnection_timeout | NO | YES | Missing GameManager cleanup |
| Waitroom timeout | leave_game | YES | YES | None |

## Sources

### Primary (HIGH confidence)
- `/Users/chasemcd/Repositories/interactive-gym/interactive_gym/server/game_manager.py` - GameManager class, cleanup_game(), _remove_game(), leave_game(), remove_subject_quietly()
- `/Users/chasemcd/Repositories/interactive-gym/interactive_gym/server/app.py` - on_disconnect(), leave_game(), join_game(), all socket handlers
- `/Users/chasemcd/Repositories/interactive-gym/interactive_gym/server/pyodide_game_coordinator.py` - PyodideGameCoordinator, remove_player(), handle_player_exclusion()
- `/Users/chasemcd/Repositories/interactive-gym/interactive_gym/server/remote_game.py` - RemoteGameV2, GameStatus, tear_down()

### Secondary (MEDIUM confidence)
- Phase 51 implementation - validate_subject_state() self-healing pattern
- Existing code comments and docstrings

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Direct code analysis of existing implementation
- Architecture: HIGH - Complete analysis of state tracking structures
- Pitfalls: HIGH - Identified from actual code paths and known bug report

**Research date:** 2026-02-02
**Valid until:** 90 days (stable internal architecture)

## Summary of Required Changes

1. **Make cleanup_game() idempotent:** Guard against double-cleanup with early return if game_id not in self.games
2. **Clean subject mappings in cleanup_game():** Explicitly delete subject_games[subject_id] and subject_rooms[subject_id] for all players in the game
3. **Ensure all exit paths call cleanup_game():**
   - remove_subject_quietly() should optionally clean game if empty
   - Pyodide exclusion handlers should call GameManager cleanup_game()
4. **Prevent routing to in-progress games:** validate_subject_state() already handles this reactively; cleanup_game() changes make it proactive
