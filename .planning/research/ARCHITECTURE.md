# Architecture Research: Waiting Room & Session Management

**Domain:** Multiplayer game session lifecycle management
**Researched:** 2026-02-02
**Overall confidence:** HIGH (based on codebase analysis + industry patterns)

---

> **Note:** This document supersedes previous architecture research for v1.12. Prior research on rollback netcode data collection remains valid but is focused on a different aspect of the system.

---

## Executive Summary

The current architecture tightly couples matchmaking logic with session management in the `GameManager` class, leading to the "stale game" bug where participants are routed to old games. The fix requires clear separation of concerns: a **Matchmaker** (matching participants), a **SessionManager** (game instance lifecycle), and proper **state machine** governance over participant journeys. The key insight is that each game session must have an explicit, finite lifecycle with deterministic cleanup - not implicit cleanup that can fail silently.

## Component Separation

### Current Architecture (Problems)

```
GAME_MANAGERS[scene_id] (global dict)
    -> GameManager (1 per scene, REUSED across participants)
        -> waiting_games[] (list of game_ids waiting for players)
        -> games{} (dict of active RemoteGameV2)
        -> subject_games{} (dict of subject -> game mappings)

PyodideGameCoordinator (global singleton)
    -> games{} (dict of PyodideGameState)
```

**Problems:**
1. `GameManager` is reused across ALL participants for a scene - if cleanup fails, stale state persists
2. No single source of truth for "what state is this participant in?"
3. `waiting_games[]` can contain stale game_ids if removal fails
4. No explicit lifecycle governance - state transitions are implicit

### Recommended Architecture

```
                    +------------------+
                    |   Orchestrator   |  (new: coordinates all state)
                    +------------------+
                            |
        +-------------------+-------------------+
        |                   |                   |
+---------------+   +----------------+   +------------------+
|  Matchmaker   |   | SessionManager |   | ParticipantState |
| (per-scene)   |   |   (per-game)   |   |   (per-subject)  |
+---------------+   +----------------+   +------------------+
```

**Matchmaker** (1 per GymScene):
- Owns the waiting queue
- Matches participants by criteria (RTT, group membership)
- Creates sessions when match is made
- Does NOT manage game state

**SessionManager** (1 per game instance):
- Owns a single game's lifecycle
- Knows its participants and their player_ids
- Handles P2P coordination for that game
- Destroyed when game ends (not reused!)

**ParticipantStateTracker** (global singleton):
- Single source of truth for "where is this participant?"
- States: `IDLE`, `IN_WAITROOM`, `VALIDATING_P2P`, `IN_GAME`, `GAME_ENDED`
- Prevents routing to wrong game

### Component Boundaries

| Component | Responsibility | Does NOT Own |
|-----------|---------------|--------------|
| Matchmaker | Matching logic, queue management | Game execution, cleanup |
| SessionManager | Single game lifecycle, P2P setup | Matching, other games |
| ParticipantStateTracker | Participant state across scenes | Game logic |
| Orchestrator | State transitions, cleanup triggers | Direct game execution |

## Lifecycle Flow

### Current Flow (Problematic)

```
Participant clicks Start
  -> GameManager.add_subject_to_game()
     -> Checks waiting_games[] (may be stale)
     -> Creates or joins game
     -> If ready: start_game()
     -> If not ready: send to waiting room

Game ends
  -> cleanup_game() (may not be called)
  -> _remove_game() (may fail silently)
  -> State persists in GAME_MANAGERS
```

### Recommended Flow

```
Phase 1: MATCHMAKING
  Participant clicks Start
    -> Orchestrator.request_match(subject_id, scene_id)
    -> ParticipantStateTracker.set_state(subject_id, IN_WAITROOM)
    -> Matchmaker.enqueue(subject_id)

  Matchmaker finds match
    -> Orchestrator.create_session(subject_ids, scene_id)
    -> Returns session_id

Phase 2: SESSION_CREATION
  Orchestrator.create_session()
    -> SessionManager.create(session_id, subject_ids)
    -> PyodideCoordinator.create_game(session_id)
    -> For each subject: ParticipantStateTracker.set_state(subject_id, VALIDATING_P2P)
    -> Emit 'pyodide_player_assigned' to each

Phase 3: P2P_VALIDATION
  All players report P2P ready
    -> SessionManager.start_game()
    -> ParticipantStateTracker.set_state(*, IN_GAME)
    -> Emit 'pyodide_game_ready'

Phase 4: GAMEPLAY
  Game runs normally
  Disconnect detected
    -> SessionManager.handle_disconnect(player_id)
    -> Attempts reconnection or triggers end

Phase 5: CLEANUP (CRITICAL)
  Game ends (normal or early)
    -> Orchestrator.end_session(session_id)
    -> PyodideCoordinator.remove_game(session_id)
    -> SessionManager.destroy()  <- Explicit destruction
    -> For each subject: ParticipantStateTracker.set_state(subject_id, GAME_ENDED)
    -> GroupManager.record_group(subject_ids)
```

### State Machine

```
                            [Start Click]
                                 |
                                 v
                          +-------------+
                          |   IDLE      |
                          +-------------+
                                 |
                                 v
                          +-------------+
            +------------>| IN_WAITROOM |
            |             +-------------+
            |                    |
            |         [Match found]
            |                    v
            |           +-----------------+
            |           | VALIDATING_P2P  |
            |           +-----------------+
            |              /          \
            |    [Validation      [Validation
            |      fails]          succeeds]
            |        /                  \
            |       v                    v
            |  +-------------+    +-------------+
            +--| RE_POOLED   |    |  IN_GAME    |
               +-------------+    +-------------+
                                        |
                                  [Game ends]
                                        |
                                        v
                                 +-------------+
                                 | GAME_ENDED  |
                                 +-------------+
                                        |
                            [Advance scene or redirect]
                                        |
                                        v
                                 +-------------+
                                 |   IDLE      |
                                 +-------------+
```

## State Ownership

### Who Owns What

| State | Owner | Cleanup Trigger |
|-------|-------|-----------------|
| Participant current state | ParticipantStateTracker | Socket disconnect OR explicit transition |
| Waiting queue | Matchmaker | Match made OR timeout |
| Game instance | SessionManager | Game end (normal or error) |
| P2P connection state | PyodideCoordinator | Game cleanup |
| Player groups | GroupManager | Never (persist for re-matching) |

### Cleanup Chain

When a game ends, cleanup MUST happen in order:

1. **Notify participants** (emit events)
2. **Export data** (save game data)
3. **Stop game runner** (if server-authoritative)
4. **Remove from PyodideCoordinator** (release P2P resources)
5. **Destroy SessionManager** (release game state)
6. **Update ParticipantStateTracker** (mark as GAME_ENDED)
7. **Remove from Matchmaker** (if was in waiting queue)

**Current bug source:** Step 5 doesn't happen reliably because `GameManager` is reused, not destroyed.

### Orphan Prevention

```python
class SessionManager:
    def __init__(self, session_id, ...):
        self._cleanup_scheduled = False
        self._created_at = time.time()

    def schedule_cleanup(self, reason: str, delay_ms: int = 0):
        """Guarantee cleanup happens, even if errors occur."""
        if self._cleanup_scheduled:
            return  # Already scheduled
        self._cleanup_scheduled = True

        if delay_ms > 0:
            eventlet.spawn_after(delay_ms / 1000, self._do_cleanup, reason)
        else:
            self._do_cleanup(reason)

    def _do_cleanup(self, reason: str):
        """Idempotent cleanup - safe to call multiple times."""
        try:
            # 1. Notify participants
            # 2. Export data
            # 3. Stop runners
            # 4. Remove from coordinator
            # 5. Update participant states
        finally:
            # Always mark as cleaned up
            self._destroyed = True
```

## Event Flow

### Happy Path Events

```
[Participant A clicks Start]
  -> Server: request_match(A)
  -> Server: A enters waitroom
  <- Client A: waiting_room{cur: 1, needed: 1}

[Participant B clicks Start]
  -> Server: request_match(B)
  -> Server: Match found (A, B)
  -> Server: create_session(A, B)
  <- Client A: pyodide_player_assigned{player_id: 0}
  <- Client B: pyodide_player_assigned{player_id: 1}

[P2P Validation]
  -> Server: p2p_validation_success(A)
  -> Server: p2p_validation_success(B)
  -> Server: start_game()
  <- Client A, B: pyodide_game_ready{}
  <- Client A, B: server_episode_start{state}

[Game Ends]
  -> Server: game_completed(session_id)
  -> Server: cleanup_session(session_id)
  <- Client A, B: p2p_game_ended{reason: 'completed'}
```

### Error Path Events

```
[Player Disconnects Mid-Game]
  -> Server: socket_disconnect(B)
  -> Server: handle_disconnect(session_id, B)
  <- Client A: p2p_game_ended{reason: 'partner_disconnected'}
  -> Server: schedule_cleanup(session_id, 'disconnect')
  -> Server: [cleanup chain executes]
```

### Events to Add

| Event | Direction | Purpose |
|-------|-----------|---------|
| `session_created` | S -> C | Confirm participant is in a session |
| `session_cleanup_started` | S -> C | Warn participants cleanup is happening |
| `participant_state_changed` | S -> C | Sync state machine to client |

## Integration Points

### How Matchmaker Integrates

```python
# In app.py advance_scene()

if isinstance(current_scene, gym_scene.GymScene):
    # Get or create matchmaker for this scene
    matchmaker = MATCHMAKERS.get(current_scene.scene_id)
    if matchmaker is None:
        matchmaker = Matchmaker(
            scene_id=current_scene.scene_id,
            required_players=len([p for p in scene.policy_mapping.values()
                                 if p == PolicyTypes.Human]),
            orchestrator=ORCHESTRATOR,
            group_manager=GROUP_MANAGER,
        )
        MATCHMAKERS[current_scene.scene_id] = matchmaker

# In join_game()

matchmaker = MATCHMAKERS.get(current_scene.scene_id)
matchmaker.enqueue(subject_id)  # Matchmaker handles the rest
```

### Current Integration Points to Preserve

1. **PyodideGameCoordinator** - Keep as is, but SessionManager wraps it
2. **GroupManager** - Keep as is, called during cleanup
3. **PARTICIPANT_SESSIONS** - Becomes part of ParticipantStateTracker
4. **Socket events** - Most stay the same, add new ones

### Integration with Existing Code

The new architecture wraps existing components:

```python
class SessionManager:
    def __init__(self, coordinator: PyodideGameCoordinator, ...):
        self.coordinator = coordinator

    def create(self):
        # Creates game in existing coordinator
        self.coordinator.create_game(...)

    def add_player(self, player_id, socket_id, subject_id):
        # Uses existing coordinator method
        self.coordinator.add_player(...)
```

## Suggested Build Order

Based on dependencies, build in this order:

### Phase 1: Foundation (No Breaking Changes)

1. **ParticipantStateTracker** - New class, no integration yet
   - Define states enum
   - Track state per participant
   - Unit tests

2. **SessionManager** - New class wrapping existing
   - Wraps PyodideGameCoordinator.create_game()
   - Has explicit destroy() method
   - Idempotent cleanup

### Phase 2: Orchestrator Integration

3. **Orchestrator** - Coordinates state transitions
   - Integrates ParticipantStateTracker
   - Integrates SessionManager
   - Handles cleanup chain

4. **Wire to advance_scene/join_game** - Replace GameManager usage
   - Use Orchestrator instead of direct GameManager
   - Keep GameManager for backward compat (mark deprecated)

### Phase 3: Matchmaker Extraction

5. **Matchmaker** - Extract from GameManager
   - Move waiting_games logic
   - Move RTT matching logic
   - Move group wait logic

6. **Complete Migration** - Remove GameManager
   - Verify no remaining usages
   - Remove deprecated code

### Dependency Graph

```
ParticipantStateTracker (no deps)
            |
            v
   SessionManager (depends on ParticipantStateTracker, PyodideCoordinator)
            |
            v
   Orchestrator (depends on SessionManager, ParticipantStateTracker)
            |
            v
   Matchmaker (depends on Orchestrator)
```

## Recommendations for v1.12

### Immediate Fixes (v1.12 Scope)

1. **Add session-per-game instead of manager-per-scene**
   - Create `Session` class that owns a single game
   - Session is destroyed when game ends
   - Fixes the "reusing GameManager" bug

2. **Add ParticipantStateTracker**
   - Single source of truth
   - Check state before routing to game
   - Prevents routing to stale games

3. **Explicit cleanup chain**
   - Schedule cleanup at every exit point
   - Idempotent cleanup methods
   - Log cleanup for debugging

### Deferred to Later (Post-v1.12)

- Full Matchmaker extraction (works now, just coupled)
- Orchestrator class (can inline logic initially)
- Event-based state sync to clients

### Migration Strategy

```
v1.12 (This milestone):
  - Add Session class that wraps game lifecycle
  - Add ParticipantStateTracker
  - Keep GameManager but use Session internally
  - Fix the stale game bug

v1.13 (Future):
  - Extract Matchmaker from GameManager
  - Add Orchestrator
  - Deprecate direct GameManager usage

v1.14 (Future):
  - Remove GameManager
  - Full component separation
```

## Confidence Assessment

| Area | Level | Reason |
|------|-------|--------|
| Root cause diagnosis | HIGH | Clear from code: GameManager reuse + no explicit cleanup |
| Session-per-game fix | HIGH | Standard industry pattern, straightforward implementation |
| State machine approach | HIGH | Well-established pattern for game lifecycles |
| Migration strategy | MEDIUM | Depends on codebase complexity, may need adjustment |
| Component boundaries | MEDIUM | May need refinement during implementation |

## Sources

### Codebase Analysis
- `/interactive_gym/server/game_manager.py` - Current GameManager implementation
- `/interactive_gym/server/pyodide_game_coordinator.py` - P2P coordination
- `/interactive_gym/server/app.py:507` - "Game manager already exists" bug location
- `/interactive_gym/server/player_pairing_manager.py` - Group tracking

### Industry Patterns
- [Game Matchmaking Architecture - AccelByte](https://accelbyte.io/blog/scaling-matchmaking-to-one-million-players) - Matchmaking service patterns
- [Session-Based Games Best Practices - OpenKruise](https://openkruise.io/kruisegame/best-practices/session-based-game) - State management for game rooms
- [Multiplayer State Machine with Durable Objects](https://www.astahmer.dev/posts/multiplayer-state-machine-with-durable-objects) - XState for game state machines
- [Microsoft PlayFab Server Lifecycle](https://learn.microsoft.com/en-us/gaming/playfab/multiplayer/servers/multiplayer-game-server-lifecycle) - Server lifecycle patterns
- [GarbageTruck: Distributed Garbage Collection](https://medium.com/@ronantech/garbagetruck-lease-based-distributed-garbage-collection-for-microservice-architectures-874d60c921f0) - Orphan cleanup patterns
