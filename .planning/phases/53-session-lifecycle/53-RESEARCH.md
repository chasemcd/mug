# Phase 53: Session Lifecycle - Research

**Researched:** 2026-02-02
**Domain:** Game session state management, state machines in Python
**Confidence:** HIGH

## Summary

This research investigates how to implement explicit session lifecycle states (WAITING -> MATCHED -> VALIDATING -> PLAYING -> ENDED) for Phase 53. The codebase currently has implicit state tracking through multiple data structures and status fields, but lacks a unified session state model.

Key findings:
1. **Current state is fragmented** - Session state is tracked across `GameStatus` (Inactive/Active/Reset/Done), `waiting_games` list, `active_games` set, and various coordinator flags. No single source of truth.
2. **Simple enum-based state tracking is sufficient** - The `python-statemachine` library adds complexity with async/sync engine concerns that don't align with eventlet's cooperative threading. A simple enum + transition validation approach is cleaner.
3. **Session must be created per-game, not per-scene** - Currently `GameManager` is reused per-scene, leading to stale state issues. Session objects should be created for each game and destroyed when complete.

**Primary recommendation:** Implement a simple `SessionState` enum with explicit transition validation in `RemoteGameV2`, avoiding external state machine libraries.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| enum (stdlib) | N/A | Define session states | Built-in, no deps, thread-safe |
| dataclasses (stdlib) | N/A | Session data container | Already used in codebase |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| logging (stdlib) | N/A | State transition logging | All transitions should be logged |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Simple enum | `python-statemachine` | Library adds async engine complexity, thread safety concerns with eventlet; overkill for 5 linear states |
| Inline state | Separate Session class | Separate class is cleaner but requires more refactoring; inline enum is sufficient |

## Architecture Patterns

### Current State Tracking (Fragmented)

The current codebase tracks session state across multiple places:

```
RemoteGameV2.status: GameStatus (Inactive -> Active -> Reset -> Done)
GameManager.waiting_games: list[GameID] (indicates WAITING state)
GameManager.active_games: set[GameID] (indicates PLAYING state)
PyodideGameState.is_active: bool (indicates PLAYING)
PyodideGameState.validation_start_time: float | None (indicates VALIDATING)
PyodideGameState.reconnection_in_progress: bool (indicates reconnection sub-state)
```

**Problem:** No single place to check "what state is this session in?"

### Recommended: Session State Enum

```python
# Source: Based on REQUIREMENTS.md SESS-01
from enum import Enum, auto

class SessionState(Enum):
    """Explicit session lifecycle states per SESS-01."""
    WAITING = auto()     # In waiting room, waiting for players
    MATCHED = auto()     # All players matched, about to validate
    VALIDATING = auto()  # P2P connection validation in progress
    PLAYING = auto()     # Game is running
    ENDED = auto()       # Game complete, session will be destroyed
```

### Pattern 1: State Transition Validation

**What:** Validate all state transitions, reject invalid ones
**When to use:** Every state change must go through validation
**Example:**
```python
class Session:
    VALID_TRANSITIONS = {
        SessionState.WAITING: {SessionState.MATCHED, SessionState.ENDED},
        SessionState.MATCHED: {SessionState.VALIDATING, SessionState.ENDED},
        SessionState.VALIDATING: {SessionState.PLAYING, SessionState.WAITING, SessionState.ENDED},
        SessionState.PLAYING: {SessionState.ENDED},
        SessionState.ENDED: set(),  # Terminal state
    }

    def transition_to(self, new_state: SessionState) -> bool:
        """Transition to new state if valid."""
        if new_state not in self.VALID_TRANSITIONS[self.state]:
            logger.error(
                f"Invalid state transition: {self.state} -> {new_state}. "
                f"Valid: {self.VALID_TRANSITIONS[self.state]}"
            )
            return False

        old_state = self.state
        self.state = new_state
        logger.info(f"Session {self.game_id}: {old_state} -> {new_state}")
        return True
```

### Pattern 2: Session Created Per-Game

**What:** Create new Session object for each game, destroy when game ends
**When to use:** When GameManager creates a game
**Example:**
```python
class GameManager:
    def _create_game(self) -> RemoteGameV2:
        game_id = str(uuid.uuid4())
        game = RemoteGameV2(
            scene=self.scene,
            experiment_config=self.experiment_config,
            game_id=game_id,
            # Session starts in WAITING state
        )
        # game.session_state is WAITING at creation
        self.games[game_id] = game
        return game

    def cleanup_game(self, game_id: GameID):
        """End session and destroy object."""
        if game_id not in self.games:
            return  # Already cleaned (idempotent)

        game = self.games[game_id]
        game.transition_to(SessionState.ENDED)

        # ... cleanup logic ...

        del self.games[game_id]  # SESS-02: Session destroyed
```

### Anti-Patterns to Avoid

- **Reusing game objects:** NEVER reset a game object for a new game; create new instance
- **Implicit state checks:** NEVER check `if game_id in waiting_games`; check `game.session_state == SessionState.WAITING`
- **State transitions without validation:** NEVER set `game.session_state = X` directly; use `transition_to()`

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Complex FSM with guards | Full state machine implementation | Simple enum + validation dict | Only 5 linear states; no conditional guards needed |
| Async state transitions | Async state machine library | Synchronous transitions with eventlet cooperative yield | Flask-SocketIO uses eventlet; async libraries introduce threading complexity |
| State persistence | Database-backed state | In-memory enum with logging | Sessions are ephemeral (minutes); no persistence needed |

**Key insight:** State machines are overkill when you have a simple linear progression with few branches. The complexity cost of `python-statemachine` (engine pattern, async/sync detection, potential threading issues) exceeds the benefit for this use case.

## Common Pitfalls

### Pitfall 1: State Machine Library with Eventlet

**What goes wrong:** `python-statemachine` uses an engine pattern that auto-detects async callbacks. If any async callback exists, it creates an `AsyncEngine` that may conflict with eventlet's cooperative threading.

**Why it happens:** The library documentation warns "All handlers will run on the same thread they are called. Therefore, mixing synchronous and asynchronous code is not recommended."

**How to avoid:** Use simple enum-based state tracking instead of external library. Flask-SocketIO with eventlet is cooperative, not async.

**Warning signs:** Deadlocks, race conditions, or "event loop already running" errors.

### Pitfall 2: Forgetting Transition Points

**What goes wrong:** State transitions happen in wrong order or are skipped entirely, leading to inconsistent state.

**Why it happens:** State changes scattered across multiple methods (join_game, start_game, cleanup_game).

**How to avoid:**
1. Document all transition points explicitly
2. Use single `transition_to()` method that logs every change
3. Add assertions in key methods to verify expected state

**Warning signs:** Log shows unexpected state transitions (e.g., WAITING -> PLAYING skipping MATCHED/VALIDATING).

### Pitfall 3: Session Reuse

**What goes wrong:** Old session state pollutes new games, causing the "stale game" bug this milestone is fixing.

**Why it happens:** Temptation to "reset" a session object instead of creating new one.

**How to avoid:**
1. `cleanup_game()` MUST `del self.games[game_id]` (already done in Phase 52)
2. Never add a "reset session" method
3. ENDED state has no valid transitions

**Warning signs:** Log shows "Game manager already exists for scene X, reusing it" with stale game_ids.

### Pitfall 4: Race Conditions in State Transitions

**What goes wrong:** Multiple concurrent events (two players clicking start) can cause duplicate state transitions.

**Why it happens:** Flask-SocketIO handlers can execute concurrently (though eventlet is cooperative).

**How to avoid:**
1. State transitions happen under `game.lock` (already exists)
2. `transition_to()` checks current state before transitioning
3. Idempotent handlers (already improved in Phase 52)

**Warning signs:** Log shows same transition happening twice, or "invalid transition" errors.

## Code Examples

### State Definition

```python
# interactive_gym/server/remote_game.py
from enum import Enum, auto

class SessionState(Enum):
    """Session lifecycle states per SESS-01."""
    WAITING = auto()     # In waiting room
    MATCHED = auto()     # Players matched, starting validation
    VALIDATING = auto()  # P2P validation in progress
    PLAYING = auto()     # Game running
    ENDED = auto()       # Terminal, session will be destroyed

# Keep existing GameStatus for game-loop state (Active/Reset/Done)
# SessionState is for overall lifecycle; GameStatus is for game-loop phase
```

### Transition Points

```python
# Where each transition happens:

# WAITING: Created in _create_game()
def _create_game(self):
    game = RemoteGameV2(...)  # starts in WAITING

# WAITING -> MATCHED: When all players joined
def add_subject_to_game(self, subject_id):
    if game.is_ready_to_start():
        game.transition_to(SessionState.MATCHED)
        self.start_game(game)

# MATCHED -> VALIDATING: For Pyodide multiplayer, when validation starts
def _start_game(self, game_id):
    if scene.pyodide_multiplayer:
        game.transition_to(SessionState.VALIDATING)
        coordinator.start_validation(game_id)
    else:
        game.transition_to(SessionState.PLAYING)

# VALIDATING -> PLAYING: When P2P validated
def on_p2p_validation_complete():
    game.transition_to(SessionState.PLAYING)

# VALIDATING -> WAITING: Validation failed, back to pool (Phase 19 behavior)
# VALIDATING -> ENDED: Validation timeout

# * -> ENDED: All exit paths (normal completion, disconnect, error)
def cleanup_game(self, game_id):
    game.transition_to(SessionState.ENDED)
    # ... cleanup and del self.games[game_id]
```

### Integration with Existing GameStatus

```python
class RemoteGameV2:
    def __init__(self, ...):
        # Session lifecycle state (new)
        self.session_state = SessionState.WAITING

        # Game loop state (existing, kept for game-loop logic)
        self.status = GameStatus.Inactive

    # Session transitions are about lifecycle (waiting room -> game -> end)
    # GameStatus transitions are about game loop (inactive -> active -> reset -> done)
    # They're orthogonal: session_state=PLAYING can have status=Active or Reset
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Implicit state via data structures | Explicit enum-based state | This phase | Clear state visibility, easier debugging |
| GameManager reused per scene | Session per game | This phase | Prevents stale state pollution |
| Multiple state indicators | Single source of truth | This phase | Simpler state reasoning |

**Deprecated/outdated:**
- Checking `game_id in waiting_games` to determine state (replaced by `session_state`)
- Checking `game_id in active_games` to determine state (replaced by `session_state`)

## Open Questions

1. **PyodideGameState alignment**
   - What we know: `PyodideGameState` has its own `is_active` and validation flags
   - What's unclear: Should `SessionState` be moved to/mirrored in `PyodideGameState`?
   - Recommendation: Keep `SessionState` in `RemoteGameV2` as source of truth; `PyodideGameState` remains coordinator-internal. Update coordinator to use game's state when querying.

2. **Transition to WAITING on validation failure**
   - What we know: Phase 19 implemented re-pooling on validation failure
   - What's unclear: Does this require creating a new Session, or can same session go back to WAITING?
   - Recommendation: For simplicity, end current session and have affected players join fresh. Avoids complexity of backwards transitions.

## Sources

### Primary (HIGH confidence)
- `/Users/chasemcd/Repositories/interactive-gym/interactive_gym/server/remote_game.py` - Current GameStatus implementation
- `/Users/chasemcd/Repositories/interactive-gym/interactive_gym/server/game_manager.py` - Current state tracking via data structures
- `/Users/chasemcd/Repositories/interactive-gym/interactive_gym/server/pyodide_game_coordinator.py` - Validation state tracking
- `/Users/chasemcd/Repositories/interactive-gym/interactive_gym/server/app.py` - State transition trigger points

### Secondary (MEDIUM confidence)
- [python-statemachine async docs](https://python-statemachine.readthedocs.io/en/latest/async.html) - Verified async/sync engine pattern and threading warnings

### Tertiary (LOW confidence)
- WebSearch for python-statemachine Flask-SocketIO integration - No direct integration examples found, suggesting this is not a common pattern

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Stdlib enum is verified, simple approach
- Architecture: HIGH - Based on direct codebase analysis
- Pitfalls: HIGH - Based on library documentation and codebase patterns

**Research date:** 2026-02-02
**Valid until:** 2026-03-02 (30 days - stable patterns)
