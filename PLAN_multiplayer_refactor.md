# Plan: Loosely-Coupled Multiplayer Synchronization

## Goal

Refactor the multiplayer Pyodide system from **lock-step synchronization** to **independent execution with periodic state sync**. Each client runs its own game loop independently, using `action_population_method` for missing player actions, with periodic state synchronization to correct drift.

---

## Current Architecture Problems

1. **Lock-step causes frame drift**: Clients wait for `pyodide_actions_ready` before stepping. If one client is faster, it sends actions before the other, causing frame number mismatch.

2. **Dropped actions cause deadlock**: Server drops actions when frame diff > 2, so `_broadcast_actions` never fires, clients wait forever.

3. **Tight coupling to network latency**: Game speed is bounded by slowest client + network round-trip.

---

## Target Architecture

```
CLIENT 1                          SERVER                          CLIENT 2
   │                                │                                │
   ├─ Step immediately              │                                │
   │  (use default/prev for P2)     │                                │
   │                                │                                │
   ├─ Broadcast my action ──────────┼────────────────────────────────→
   │                                │                                │
   │                                │  ← Receive P2's action ────────┤
   │                                │                                │
   │  ← Receive P2's action ────────┤                                │
   │    (for NEXT frame prediction) │                                │
   │                                │                                │
   │  ... N frames pass ...         │                                │
   │                                │                                │
   │                          [SYNC POINT]                           │
   │                                │                                │
   ├─ Send state hash ──────────────→  ← Send state hash ────────────┤
   │                                │                                │
   │                          Compare hashes                         │
   │                                │                                │
   │                          If mismatch:                           │
   │  ← Request state from host ────┤                                │
   │                                │                                │
   ├─ Send full state ──────────────→                                │
   │                                │                                │
   │                                ├── Apply state to non-host ─────→
   │                                │                                │
   │                          [RESUME]                               │
```

---

## Changes Required

### 1. Client-Side: `pyodide_multiplayer_game.js`

#### 1.1 Remove blocking action wait

**Current** (lines 379-387):
```javascript
const allActions = await this.waitForAllActions();  // BLOCKS
if (allActions === null) {
    return null;
}
const stepResult = await this.stepWithActions(allActions);
```

**New**:
```javascript
// Step immediately with best-available actions
const stepResult = await this.stepWithActions(allActionsDict);

// Send my action to server for other clients (non-blocking)
socket.emit('pyodide_player_action', {
    game_id: this.gameId,
    player_id: this.myPlayerId,
    action: myAction,
    frame_number: this.frameNumber,
    timestamp: Date.now()
});
```

#### 1.2 Add action prediction from other players

**Add new handler** for receiving other players' actions:
```javascript
socket.on('pyodide_other_player_action', (data) => {
    // Store for next frame's prediction
    this.lastKnownActions[data.player_id] = data.action;
});
```

**Modify `buildPyodideActionDict()`** in `phaser_gym_graphics.js`:
```javascript
// For other human players in multiplayer:
if (isMultiplayer && agentID != myPlayerId && policy == "human") {
    // Use last known action or action_population_method
    if (this.pyodide_remote_game.lastKnownActions[agentID] !== undefined) {
        actions[agentID] = this.pyodide_remote_game.lastKnownActions[agentID];
    } else if (scene_metadata.action_population_method === "previous_submitted_action") {
        actions[agentID] = previousSubmittedActions[agentID] || scene_metadata.default_action;
    } else {
        actions[agentID] = scene_metadata.default_action;
    }
}
```

#### 1.3 Remove `isStepInProgress` guard

The step function should no longer block, so remove:
- `this.isStepInProgress` flag
- All checks for `isStepInProgress`

#### 1.4 Remove `waitForAllActions()` function

Delete entirely - no longer needed.

---

### 2. Server-Side: `pyodide_game_coordinator.py`

#### 2.1 Change action handling from "collect all" to "broadcast immediately"

**Current** (lines 244-254):
```python
game.pending_actions[player_id] = action

# Wait until ALL players submitted
if len(game.pending_actions) == len(game.players):
    self._broadcast_actions(game_id)
```

**New**:
```python
# Broadcast this player's action to OTHER players immediately
for other_player_id, socket_id in game.players.items():
    if other_player_id != player_id:
        self.sio.emit('pyodide_other_player_action', {
            'player_id': player_id,
            'action': action,
            'frame_number': frame_number
        }, room=socket_id)

# Track for sync verification (optional)
game.last_actions[player_id] = action
```

#### 2.2 Remove frame number validation that drops actions

**Current** (lines 228-235):
```python
frame_diff = abs(frame_number - game.frame_number)
if frame_diff > 2:
    logger.warning(...)
    return  # DROPS ACTION
```

**New**:
```python
# Log frame differences for debugging but don't drop actions
frame_diff = abs(frame_number - game.frame_number)
if frame_diff > 5:
    logger.warning(f"Large frame drift: player {player_id} at {frame_number}, expected ~{game.frame_number}")
# Continue processing - never drop
```

#### 2.3 Update frame tracking to be per-player

**Change** `PyodideGameState`:
```python
@dataclasses.dataclass
class PyodideGameState:
    # Remove: frame_number: int
    # Add:
    player_frame_numbers: Dict[str | int, int]  # Track each player's frame
    last_actions: Dict[str | int, Any]  # Last action from each player
```

---

### 3. State Synchronization

Keep the existing sync mechanism but adjust:

#### 3.1 Increase sync frequency during testing

**File:** `pyodide_game_coordinator.py`
```python
self.verification_frequency = 30  # Every 30 frames (~1 second at 30fps)
```

Consider making this configurable per-game.

#### 3.2 Sync uses host's state as ground truth

The existing `getFullState()` / `applyFullState()` mechanism is correct:
- Host serializes state via `env.get_state()`
- Non-host clients restore via `env.set_state()`
- RNG state is synchronized

#### 3.3 After sync, both clients continue from same state

The current implementation clears action buffers and resumes - keep this.

---

### 4. `phaser_gym_graphics.js` Changes

#### 4.1 Remove multiplayer step blocking check

**Current** (lines 319-327):
```javascript
if (stepResult === null) {
    const isMultiplayerStepInProgress = this.pyodide_remote_game.isStepInProgress;
    if (!isMultiplayerStepInProgress) {
        this.isProcessingPyodide = false;
    }
    return;
}
```

**New** (step should never return null except for done/reset states):
```javascript
if (stepResult === null) {
    this.isProcessingPyodide = false;
    return;
}
```

---

### 5. Environment `get_state` / `set_state` Implementation

The dummy implementation needs to be replaced with actual serialization.

**File:** `cramped_room_environment_initialization_hh.py`

```python
def get_state(self) -> dict:
    """Serialize environment state for sync."""
    # Agents
    agents = {}
    for agent_id, agent in self.grid.grid_agents.items():
        agents[agent_id] = {
            'pos': list(agent.pos),
            'dir': agent.dir,
            'inventory': [type(item).__name__ for item in agent.inventory],
        }

    # Dynamic objects (pots, items on counters)
    pots = []
    counter_items = []
    for obj in self.grid.grid:
        if obj is None:
            continue
        if hasattr(obj, 'cooking_timer'):  # Pot
            pots.append({
                'pos': list(obj.pos),
                'cooking_timer': obj.cooking_timer,
                'objects_in_pot': [type(o).__name__ for o in getattr(obj, 'objects_in_pot', [])],
            })
        if hasattr(obj, 'obj_placed_on') and obj.obj_placed_on is not None:
            counter_items.append({
                'pos': list(obj.pos),
                'item_type': type(obj.obj_placed_on).__name__,
            })

    return {
        't': self.t,
        'agents': agents,
        'pots': pots,
        'counter_items': counter_items,
        'reward_weights': self.reward_weights,
        'per_agent_reward': dict(self.per_agent_reward),
    }

def set_state(self, state: dict) -> None:
    """Restore environment from serialized state."""
    self.t = state['t']

    # Restore agents
    for agent_id, agent_data in state['agents'].items():
        agent = self.grid.grid_agents[int(agent_id)]
        agent.pos = tuple(agent_data['pos'])
        agent.dir = agent_data['dir']
        # Restore inventory...

    # Restore pots...
    # Restore counter items...

    self.reward_weights = state['reward_weights']
    self.per_agent_reward = state['per_agent_reward']
```

---

## Implementation Order

### Phase 1: Make clients run independently (no blocking)
1. [ ] Remove `waitForAllActions()` and blocking logic in `step()`
2. [ ] Add `lastKnownActions` tracking for other players
3. [ ] Modify server to broadcast actions immediately (not collect-all)
4. [ ] Update `buildPyodideActionDict()` to use `action_population_method` for other players
5. [ ] Test: Both clients should run independently

### Phase 2: Fix state synchronization
1. [ ] Implement proper `get_state()` / `set_state()` in environment
2. [ ] Test sync mechanism manually (trigger desync)
3. [ ] Verify sync recovers correctly

### Phase 3: Polish and optimize
1. [ ] Tune `verification_frequency` for balance of sync vs performance
2. [ ] Add metrics/logging for drift detection
3. [ ] Consider adding "soft sync" (action hints) vs "hard sync" (full state)

---

## Testing Checklist

- [ ] Both clients can run at different frame rates
- [ ] Actions from one client appear in other client's game (with 1-frame delay)
- [ ] State verification detects intentional desync
- [ ] State sync recovers from desync correctly
- [ ] Host migration works after disconnect
- [ ] Data logging only happens on host
- [ ] Game feels responsive (no waiting for network)

---

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| Visual desync (players see different states) | Frequent sync checks (every 30 frames) |
| Action prediction wrong | Use `action_population_method` consistently |
| Sync payload too large | Optimize `get_state()` to only serialize changes |
| Network latency causes permanent drift | Hard sync resets to ground truth |
| One client much faster than other | Sync frequency handles this |

---

## Questions to Resolve

1. **Should other player actions be rendered with prediction?**
   - Option A: Show predicted position, snap on sync
   - Option B: Show delayed position (always 1 frame behind)

2. **What `action_population_method` should be default for multiplayer?**
   - `previous_submitted_action` feels more natural
   - `default_action` (noop) is safer

3. **How often should state sync happen?**
   - Every 30 frames (1 sec) is current
   - Could make configurable per-scene

---
---

# Alternative: Option B - Action Queue Synchronization

## Concept

Instead of syncing full game state, synchronize **actions only**. Each client maintains a queue of the other player's actions. The game stays perfectly synchronized because both clients execute the exact same action sequence.

```
CLIENT 1 (Player 0)                SERVER                    CLIENT 2 (Player 1)
      │                              │                              │
      │                              │                              │
      ├─ My action: 2 ───────────────┼──────────────────────────────→
      │                              │                     [Queue: P0→2]
      │                              │                              │
      │              ←───────────────┼─────────── My action: 3 ─────┤
      │  [Queue: P1→3]               │                              │
      │                              │                              │
      ├─ Step frame N:               │                 Step frame N:┤
      │   P0 action = 2 (mine)       │            P0 action = 2 (queue.pop)
      │   P1 action = 3 (queue.pop)  │            P1 action = 3 (mine)
      │                              │                              │
      │  [IDENTICAL STATE]           │            [IDENTICAL STATE] │
```

## Key Insight

If both clients execute the **same actions in the same order**, their states remain identical without ever transferring state. The only thing that needs to sync is the action stream.

---

## Architecture

### Action Queues (per client)

```javascript
// In MultiplayerPyodideGame
this.otherPlayerActionQueues = {};  // { player_id: [action1, action2, ...] }
this.myActionHistory = [];          // For debugging/replay
```

### Flow

1. **Client sends action immediately** when user presses key
2. **Server broadcasts** to other clients
3. **Other clients queue** the action
4. **On step**: Pop from queue if available, else use `action_population_method`
5. **No state sync needed** if queues stay populated

---

## Client-Side: `pyodide_multiplayer_game.js`

### Constructor additions

```javascript
constructor(config) {
    super(config);

    // Action queues for other players
    this.otherPlayerActionQueues = {};  // { player_id: [actions...] }
    this.maxQueueSize = 10;             // Prevent memory issues

    // ... existing code ...
}
```

### New socket handler

```javascript
setupMultiplayerHandlers() {
    // ... existing handlers ...

    // Receive other player's action
    socket.on('pyodide_other_player_action', (data) => {
        const { player_id, action, frame_number } = data;

        // Initialize queue if needed
        if (!this.otherPlayerActionQueues[player_id]) {
            this.otherPlayerActionQueues[player_id] = [];
        }

        // Add to queue (FIFO)
        const queue = this.otherPlayerActionQueues[player_id];
        queue.push({ action, frame_number });

        // Trim if too long (drop oldest)
        while (queue.length > this.maxQueueSize) {
            queue.shift();
        }

        console.debug(`[MultiplayerPyodide] Queued action ${action} from player ${player_id} (queue size: ${queue.length})`);
    });
}
```

### Modified step function

```javascript
async step(allActionsDict) {
    // ... validation checks ...

    // Build complete action dict with queue lookups
    const finalActions = {};

    for (const [agentId, policy] of Object.entries(this.policyMapping)) {
        if (agentId == this.myPlayerId) {
            // My action - from input
            finalActions[agentId] = allActionsDict[agentId];
        } else if (policy === 'human') {
            // Other human player - pop from queue
            finalActions[agentId] = this.getOtherPlayerAction(agentId);
        } else {
            // Bot - from allActionsDict (already computed)
            finalActions[agentId] = allActionsDict[agentId];
        }
    }

    // Send MY action to server (for other clients)
    socket.emit('pyodide_player_action', {
        game_id: this.gameId,
        player_id: this.myPlayerId,
        action: finalActions[this.myPlayerId],
        frame_number: this.frameNumber,
        timestamp: Date.now()
    });

    // Step environment with complete actions
    const stepResult = await this.stepWithActions(finalActions);

    // ... rest of step logic ...
}

getOtherPlayerAction(playerId) {
    const queue = this.otherPlayerActionQueues[playerId];

    if (queue && queue.length > 0) {
        // Pop oldest action from queue
        const { action } = queue.shift();
        return action;
    } else {
        // Queue empty - use fallback
        console.debug(`[MultiplayerPyodide] Queue empty for player ${playerId}, using fallback`);

        if (this.actionPopulationMethod === 'previous_submitted_action') {
            return this.lastExecutedActions[playerId] ?? this.defaultAction;
        } else {
            return this.defaultAction;
        }
    }
}
```

---

## Server-Side: `pyodide_game_coordinator.py`

### Simplified action handling

```python
def receive_action(
    self,
    game_id: str,
    player_id: str | int,
    action: Any,
    frame_number: int
):
    """
    Receive action from a player and broadcast to others.
    No collection, no waiting - just relay.
    """
    with self.lock:
        if game_id not in self.games:
            return

        game = self.games[game_id]

        if not game.is_active:
            return

        # Broadcast to ALL OTHER players immediately
        for other_player_id, socket_id in game.players.items():
            if other_player_id != player_id:
                self.sio.emit('pyodide_other_player_action', {
                    'player_id': player_id,
                    'action': action,
                    'frame_number': frame_number,
                    'timestamp': time.time()
                }, room=socket_id)

        logger.debug(
            f"Game {game_id}: Relayed action {action} from player {player_id} "
            f"to {len(game.players) - 1} other players"
        )
```

### Remove collect-and-broadcast logic

Delete `_broadcast_actions()` - no longer needed.

### Remove frame validation

No frame number tracking needed on server - clients handle their own pacing.

---

## `phaser_gym_graphics.js` Changes

### Update `buildPyodideActionDict()`

```javascript
async buildPyodideActionDict() {
    let actions = {};

    let isMultiplayer = this.pyodide_remote_game &&
                        this.pyodide_remote_game.myPlayerId !== undefined;
    let myPlayerId = isMultiplayer ? String(this.pyodide_remote_game.myPlayerId) : null;

    for (let [agentID, policy] of Object.entries(this.scene_metadata.policy_mapping)) {
        if (policy == "human") {
            if (isMultiplayer) {
                if (agentID == myPlayerId) {
                    // MY action - get from keyboard
                    actions[agentID] = this.getHumanAction();
                } else {
                    // Other player - will be filled from queue in step()
                    // Put placeholder that will be replaced
                    actions[agentID] = null;  // Signals "get from queue"
                }
            } else {
                actions[agentID] = this.getHumanAction();
            }
        } else {
            actions[agentID] = this.getBotAction(agentID);
        }
    }

    return actions;
}
```

---

## Handling Queue Edge Cases

### 1. Queue Empty (Other Player Lagging)

```javascript
getOtherPlayerAction(playerId) {
    const queue = this.otherPlayerActionQueues[playerId];

    if (queue && queue.length > 0) {
        return queue.shift().action;
    } else {
        // Fallback based on action_population_method
        if (this.actionPopulationMethod === 'previous_submitted_action') {
            return this.lastExecutedActions[playerId] ?? this.defaultAction;
        }
        return this.defaultAction;
    }
}
```

### 2. Queue Too Full (This Client Lagging)

```javascript
// In socket handler, trim queue
while (queue.length > this.maxQueueSize) {
    const dropped = queue.shift();
    console.warn(`[MultiplayerPyodide] Dropping old action from player ${player_id}, we're behind`);
}
```

### 3. Initial Sync (Game Start)

Both clients start with empty queues. First few frames may use default actions until queues populate. This is acceptable - game starts slow then catches up.

### 4. Network Hiccup (Temporary Disconnect)

Queue drains, defaults are used. When connection resumes, actions queue up and catch up. May cause brief "fast forward" effect.

---

## Comparison: Option A vs Option B

| Aspect | Option A: State Sync | Option B: Action Queue |
|--------|---------------------|----------------------|
| **Sync Mechanism** | Periodic full state transfer | Continuous action stream |
| **State Drift** | Corrected every N frames | Never drifts (same actions = same state) |
| **Network Payload** | Large (full state every 30 frames) | Small (single action per frame) |
| **Latency Handling** | State snap on resync | Queue buffers, graceful degradation |
| **Complexity** | Requires `get_state`/`set_state` | No state serialization needed |
| **Visual Consistency** | May have "jumps" on resync | Smooth (identical execution) |
| **Failure Mode** | Desync → full resync | Queue empty → use default action |
| **Host Dependency** | Host is ground truth | No host needed for sync |
| **Determinism Required** | No (state is transferred) | Yes (same actions must produce same state) |

---

## Hybrid Approach (Recommended)

Combine both options:

1. **Primary**: Use Action Queue (Option B) for normal operation
2. **Fallback**: Use State Sync (Option A) as safety net

```javascript
// Every 300 frames (~10 seconds), verify states match
if (this.frameNumber % 300 === 0) {
    const hash = await this.computeStateHash();
    socket.emit('pyodide_state_hash', { hash, frame: this.frameNumber });
}

// If hashes don't match, fall back to full state sync
socket.on('pyodide_desync_detected', async (data) => {
    console.warn('[MultiplayerPyodide] Desync detected, requesting full state sync');
    // Trigger Option A's state sync mechanism
});
```

---

## Implementation Order for Option B

### Phase 1: Basic Action Queue
1. [ ] Add `otherPlayerActionQueues` to `MultiplayerPyodideGame`
2. [ ] Add socket handler for `pyodide_other_player_action`
3. [ ] Modify `step()` to use `getOtherPlayerAction()`
4. [ ] Update server to broadcast actions immediately
5. [ ] Remove `waitForAllActions()` blocking

### Phase 2: Edge Case Handling
1. [ ] Implement queue size limits
2. [ ] Add fallback for empty queue (`action_population_method`)
3. [ ] Track `lastExecutedActions` for fallback
4. [ ] Handle game start (empty queues)

### Phase 3: Optional State Verification
1. [ ] Add periodic hash comparison (every 300 frames)
2. [ ] Keep state sync as fallback for detected desyncs
3. [ ] Implement `get_state()`/`set_state()` for fallback

---

## Testing Checklist for Option B

- [ ] Actions from Player 0 appear in Player 1's game
- [ ] Actions from Player 1 appear in Player 0's game
- [ ] Queue handles burst of actions (player mashing keys)
- [ ] Empty queue gracefully falls back to default action
- [ ] Full queue drops oldest actions (no memory leak)
- [ ] Both clients execute same action sequence
- [ ] Final game states match at episode end
- [ ] Network hiccup recovers gracefully
- [ ] No "waiting" feeling - game runs at full speed
