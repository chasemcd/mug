# Server-Authoritative Multiplayer Architecture

## Overview

This document details the implementation plan for adding a server-side authoritative Python environment that runs in parallel with client-side Pyodide games. The server provides periodic state resyncs directly to all clients, eliminating the host-to-server-to-clients resync path.

### Goals

1. **Faster Resyncs**: Server broadcasts state directly to all clients (1 hop instead of 2)
2. **No Host Dependency**: Any client can disconnect without affecting resync capability
3. **Maintain Responsiveness**: Clients continue running locally with action queues
4. **Minimal Changes**: Extend existing architecture rather than replace it

---

## Current vs Proposed Architecture

### Current: Host-Based Resync

```
┌─────────────────┐         ┌─────────────────┐         ┌─────────────────┐
│    Client A     │         │     Server      │         │    Client B     │
│   (Host)        │         │  (Relay Only)   │         │   (Non-Host)    │
│                 │         │                 │         │                 │
│  ┌───────────┐  │ actions │                 │ actions │  ┌───────────┐  │
│  │  Pyodide  │──┼────────►│    Relay        │────────►│  │  Pyodide  │  │
│  │   Env     │  │         │                 │         │  │   Env     │  │
│  └───────────┘  │         │                 │         │  └───────────┘  │
│       │         │         │                 │         │        ▲        │
│       │ state   │         │                 │         │        │        │
│       └─────────┼────────►│    Relay        ├─────────┼────────┘        │
│   (on desync)   │         │                 │  state  │   (apply)       │
└─────────────────┘         └─────────────────┘         └─────────────────┘

Resync path: Host → Server → Other Clients (2 hops)
```

**Problems**:
- Resync adds latency (host → server → clients)
- If host disconnects, need host migration
- Host bears extra responsibility

### Proposed: Server-Authoritative Resync

```
┌─────────────────┐         ┌─────────────────┐         ┌─────────────────┐
│    Client A     │         │     Server      │         │    Client B     │
│                 │         │ (Authoritative) │         │                 │
│                 │         │                 │         │                 │
│  ┌───────────┐  │ actions │  ┌───────────┐  │ actions │  ┌───────────┐  │
│  │  Pyodide  │──┼────────►│  │  Python   │◄─┼────────│  │  Pyodide  │  │
│  │   Env     │  │         │  │   Env     │  │         │  │   Env     │  │
│  └─────┬─────┘  │         │  └─────┬─────┘  │         │  └─────┬─────┘  │
│        │        │         │        │        │         │        │        │
│        │ local  │  relay  │        │ state  │  relay  │  local │        │
│        │ sim    │◄────────┼────────┼────────┼────────►│  sim   │        │
│        ▼        │         │        ▼        │         │        ▼        │
│   Game Loop     │         │   Game Loop     │         │   Game Loop     │
│   (responsive)  │         │ (authoritative) │         │   (responsive)  │
└─────────────────┘         └─────────────────┘         └─────────────────┘
                                     │
                              periodic state
                              broadcast (resync)
                                     │
                    ┌────────────────┴────────────────┐
                    ▼                                 ▼
              ┌───────────┐                     ┌───────────┐
              │ Client A  │                     │ Client B  │
              │ (apply)   │                     │ (apply)   │
              └───────────┘                     └───────────┘

Resync path: Server → All Clients (1 hop, parallel)
```

**Benefits**:
- Resync is faster (server → all clients directly)
- No host/non-host distinction for state authority
- Clients stay responsive (local simulation continues)
- Server is always available for resync

---

## How It Works

### Client Behavior (Unchanged)

1. **Local Simulation**: Each client runs Pyodide environment locally
2. **Action Queue**: Queue actions from other players, apply on each frame
3. **Action Relay**: Send actions to server, server relays to other clients
4. **Responsive Gameplay**: No waiting for server state

### Server Behavior (New)

1. **Parallel Environment**: Server runs same environment in Python
2. **Action Consumption**: Server receives all player actions
3. **Authoritative State**: Server's state is the ground truth
4. **Periodic Broadcast**: Server sends state to all clients at intervals

### Resync Behavior (Changed)

**Before**: Hash mismatch → Host sends state → Server relays → Clients apply

**After**: Server periodically broadcasts authoritative state → All clients apply

---

## Implementation Plan

### Phase 1: Server-Side Environment Runner

#### 1.1 Create `AuthoritativeGameRunner` Class

**File**: `interactive_gym/server/authoritative_game_runner.py`

```python
"""
Authoritative Game Runner for Server-Side Environment Execution

Runs a Python environment on the server in parallel with client Pyodide games.
Provides periodic state broadcasts for client resynchronization.
"""

import threading
import time
import logging
from typing import Any, Dict, Optional
import eventlet

logger = logging.getLogger(__name__)


class AuthoritativeGameRunner:
    """
    Runs an authoritative game environment on the server.

    The server environment runs in parallel with client Pyodide environments.
    Clients continue to simulate locally for responsiveness, but periodically
    receive authoritative state from the server to correct any drift.

    Responsibilities:
    1. Initialize environment from the same code clients use
    2. Receive and apply actions from all players (via relay)
    3. Step environment in sync with client frame rate
    4. Broadcast authoritative state at configured intervals
    """

    def __init__(
        self,
        game_id: str,
        environment_code: str,
        num_players: int,
        fps: int = 30,
        state_broadcast_interval: int = 30,  # Frames between broadcasts
        socketio=None,
    ):
        self.game_id = game_id
        self.environment_code = environment_code
        self.num_players = num_players
        self.fps = fps
        self.state_broadcast_interval = state_broadcast_interval
        self.socketio = socketio

        # Game state
        self.env = None
        self.is_running = False
        self.frame_number = 0
        self.step_num = 0
        self.episode_num = 0
        self.cumulative_rewards = {}

        # Action handling - mirrors client action queue approach
        self.player_actions: Dict[str, Any] = {}  # Latest action per player
        self.action_lock = threading.Lock()
        self.default_action = 0

        # Player tracking
        self.players: Dict[str, str] = {}  # player_id -> socket_id

        # Timing
        self.frame_duration = 1.0 / fps
        self.last_frame_time = 0

    def initialize_environment(self, rng_seed: int = None):
        """
        Execute environment initialization code and create env instance.

        Uses the same initialization code that clients execute in Pyodide.
        """
        env_globals = {"__name__": "__main__"}

        # Execute the environment initialization code
        exec(self.environment_code, env_globals)

        if "env" not in env_globals:
            raise RuntimeError(
                "Environment initialization code must define 'env' variable"
            )

        self.env = env_globals["env"]

        # Reset and get initial observation
        obs, info = self.env.reset(seed=rng_seed)

        # Initialize cumulative rewards
        for player_id in obs.keys():
            self.cumulative_rewards[str(player_id)] = 0
            self.player_actions[str(player_id)] = self.default_action

        logger.info(
            f"[AuthoritativeRunner] Environment initialized for game {self.game_id}"
        )
        return obs

    def receive_action(self, player_id: str, action: Any, frame_number: int):
        """
        Receive an action from a player.

        Actions update the latest known action for each player.
        The server applies the most recent action each frame.
        """
        with self.action_lock:
            self.player_actions[str(player_id)] = action

    def get_actions_for_step(self) -> Dict[str, Any]:
        """
        Get actions for all players for the current step.

        Uses latest known action for each player (same as client fallback).
        """
        with self.action_lock:
            return {pid: action for pid, action in self.player_actions.items()}

    def step(self) -> Dict[str, Any]:
        """
        Step the environment with current actions and return state.
        """
        actions = self.get_actions_for_step()

        # Step the environment
        obs, rewards, terminateds, truncateds, info = self.env.step(actions)

        # Update cumulative rewards
        for player_id, reward in rewards.items():
            self.cumulative_rewards[str(player_id)] += reward

        self.frame_number += 1
        self.step_num += 1

        return {
            "terminateds": terminateds,
            "truncateds": truncateds,
        }

    def get_full_state(self) -> Dict[str, Any]:
        """
        Get full state for broadcast to clients.

        Returns the same structure that clients use for state sync.
        """
        state = {
            "episode_num": self.episode_num,
            "step_num": self.step_num,
            "frame_number": self.frame_number,
            "cumulative_rewards": self.cumulative_rewards.copy(),
        }

        # Include environment state if available
        if hasattr(self.env, "get_state"):
            state["env_state"] = self.env.get_state()

        return state

    def broadcast_state(self):
        """
        Broadcast authoritative state to all connected clients.
        """
        if self.socketio is None:
            return

        state = self.get_full_state()

        # Use MessagePack for efficient encoding
        try:
            import msgpack

            encoded_state = msgpack.packb(state, use_bin_type=True)
            compressed = True
        except ImportError:
            import json

            encoded_state = json.dumps(state)
            compressed = False

        self.socketio.emit(
            "authoritative_state_sync",
            {"game_id": self.game_id, "state": encoded_state, "compressed": compressed},
            room=self.game_id,
        )

        logger.debug(
            f"[AuthoritativeRunner] Broadcast state at frame {self.frame_number}"
        )

    def run_game_loop(self):
        """
        Main game loop - runs at fixed FPS, broadcasts state periodically.

        Should be called in a greenlet/thread.
        """
        self.is_running = True
        self.last_frame_time = time.time()

        logger.info(
            f"[AuthoritativeRunner] Starting game loop for {self.game_id} "
            f"at {self.fps} FPS, broadcast every {self.state_broadcast_interval} frames"
        )

        while self.is_running:
            current_time = time.time()
            elapsed = current_time - self.last_frame_time

            if elapsed >= self.frame_duration:
                self.last_frame_time = current_time

                try:
                    # Step the environment
                    result = self.step()

                    # Broadcast state at configured interval
                    if self.frame_number % self.state_broadcast_interval == 0:
                        self.broadcast_state()

                    # Handle episode end
                    if result.get("terminateds", {}).get("__all__", False):
                        self.handle_episode_end()

                except Exception as e:
                    logger.error(f"[AuthoritativeRunner] Error in game loop: {e}")
                    import traceback

                    traceback.print_exc()

            # Yield to other greenlets
            eventlet.sleep(0)

    def handle_episode_end(self):
        """Handle end of episode - reset environment."""
        self.episode_num += 1
        self.step_num = 0

        # Reset environment
        obs, info = self.env.reset()

        # Optionally reset cumulative rewards (configurable)
        # For now, keep them (matches client behavior with hud_score_carry_over)

        # Broadcast state after reset so clients sync
        self.broadcast_state()

        logger.info(
            f"[AuthoritativeRunner] Episode {self.episode_num} started for {self.game_id}"
        )

    def stop(self):
        """Stop the game loop."""
        self.is_running = False
        logger.info(f"[AuthoritativeRunner] Stopped game loop for {self.game_id}")
```

#### 1.2 Extend PyodideGameCoordinator

**File**: `interactive_gym/server/pyodide_game_coordinator.py`

Add to `PyodideGameState` dataclass:

```python
@dataclasses.dataclass
class PyodideGameState:
    # ... existing fields ...

    # New fields for server-authoritative mode
    server_authoritative: bool = False
    game_runner: "AuthoritativeGameRunner | None" = None
```

Add methods to `PyodideGameCoordinator`:

```python
def create_game(
    self,
    game_id: str,
    num_players: int,
    server_authoritative: bool = False,
    environment_code: str = None,
    fps: int = 30,
    state_broadcast_interval: int = 30,
) -> PyodideGameState:
    """
    Initialize a new Pyodide multiplayer game.

    Args:
        server_authoritative: If True, server runs parallel authoritative env
        environment_code: Python code to initialize environment
        fps: Target frame rate
        state_broadcast_interval: Frames between state broadcasts
    """
    # ... existing game creation code ...

    game_state.server_authoritative = server_authoritative

    if server_authoritative and environment_code:
        from interactive_gym.server.authoritative_game_runner import (
            AuthoritativeGameRunner,
        )

        game_state.game_runner = AuthoritativeGameRunner(
            game_id=game_id,
            environment_code=environment_code,
            num_players=num_players,
            fps=fps,
            state_broadcast_interval=state_broadcast_interval,
            socketio=self.socketio,
        )

    return game_state


def start_authoritative_runner(self, game_id: str):
    """Start the authoritative game runner when all players are ready."""
    game = self.games.get(game_id)
    if not game or not game.server_authoritative or not game.game_runner:
        return

    runner = game.game_runner
    runner.players = game.players.copy()

    # Initialize environment with same seed as clients
    runner.initialize_environment(rng_seed=game.rng_seed)

    # Start game loop in greenlet
    eventlet.spawn(runner.run_game_loop)

    logger.info(f"[Coordinator] Started authoritative runner for {game_id}")


def receive_action(self, game_id: str, player_id: str, action: Any, frame_number: int):
    """
    Receive action from player - relay to others AND to authoritative runner.
    """
    game = self.games.get(game_id)
    if not game:
        return

    # Existing behavior: relay to other players
    for other_player_id, socket_id in game.players.items():
        if other_player_id != player_id:
            self.socketio.emit(
                "pyodide_other_player_action",
                {
                    "player_id": player_id,
                    "action": action,
                    "frame_number": frame_number,
                    "timestamp": time.time(),
                },
                room=socket_id,
            )

    # NEW: Also send to authoritative runner if enabled
    if game.server_authoritative and game.game_runner:
        game.game_runner.receive_action(player_id, action, frame_number)
```

### Phase 2: Client-Side Handler

#### 2.1 Update `pyodide_multiplayer_game.js`

Add handler for authoritative state sync:

```javascript
// In setupSocketHandlers()

// Receive authoritative state from server (replaces host-based resync)
socket.on('authoritative_state_sync', async (data) => {
    if (data.game_id !== this.gameId) return;

    console.log(`[MultiplayerPyodide] Received authoritative state at frame ${this.frameNumber}`);

    // Decode state
    let state;
    if (data.compressed) {
        state = msgpack.decode(new Uint8Array(data.state));
    } else {
        state = JSON.parse(data.state);
    }

    // Apply authoritative state (same as current applyFullState)
    await this.applyAuthoritativeState(state);
});

// New method
async applyAuthoritativeState(state) {
    /**
     * Apply authoritative state from server.
     * This replaces the host-based resync mechanism.
     */

    // Update frame tracking
    this.frameNumber = state.frame_number;
    this.step_num = state.step_num;
    this.num_episodes = state.episode_num;

    // Update cumulative rewards
    this.cumulative_rewards = state.cumulative_rewards;

    // Apply environment state if present
    if (state.env_state) {
        await this.pyodide.runPythonAsync(`
env.set_state(${JSON.stringify(state.env_state)})
        `);
    }

    // Clear action queues for fresh start after resync
    for (const playerId in this.otherPlayerActionQueues) {
        this.otherPlayerActionQueues[playerId] = [];
    }

    // Update HUD
    this.updateHUD();

    console.log(`[MultiplayerPyodide] Applied authoritative state, now at frame ${this.frameNumber}`);
}
```

### Phase 3: Configuration

#### 3.1 Add Options to GymScene

**File**: `interactive_gym/scenes/gym_scene.py`

```python
def runtime(
    self,
    run_through_pyodide: bool = NotProvided,
    environment_initialization_code: str = NotProvided,
    environment_initialization_code_filepath: str = NotProvided,
    packages_to_install: list[str] = NotProvided,
    # ... browser execution params ...
):
    """Configure Pyodide-based browser execution."""
    # ...
    return self

def multiplayer(
    self,
    multiplayer: bool = NotProvided,
    server_authoritative: bool = NotProvided,
    state_broadcast_interval: int = NotProvided,
    # ... other multiplayer params ...
):
    """
    Configure multiplayer settings.

    Args:
        server_authoritative: If True, server runs parallel authoritative env
            and broadcasts state periodically. Clients still run locally but
            resync to server state instead of host state.
        state_broadcast_interval: How often (in frames) server broadcasts
            authoritative state. Lower = more bandwidth, faster correction.
            Higher = less bandwidth, potential for longer drift.
    """
    if multiplayer is not NotProvided:
        self.pyodide_multiplayer = multiplayer
    if server_authoritative is not NotProvided:
        self.server_authoritative = server_authoritative
    if state_broadcast_interval is not NotProvided:
        self.server_state_broadcast_interval = state_broadcast_interval
    # ... rest of existing code ...
    return self
```

### Phase 4: GameManager Integration

**File**: `interactive_gym/server/game_manager.py`

In `_create_game()`:

```python
if self.scene.run_through_pyodide and self.scene.multiplayer:
    # Get environment code for server-authoritative mode
    env_code = None
    server_authoritative = getattr(self.scene, "server_authoritative", False)

    if server_authoritative:
        if self.scene.environment_initialization_code:
            env_code = self.scene.environment_initialization_code
        elif self.scene.environment_initialization_code_filepath:
            with open(self.scene.environment_initialization_code_filepath) as f:
                env_code = f.read()

    self.pyodide_coordinator.create_game(
        game_id=game.game_id,
        num_players=self.scene.num_players,
        server_authoritative=server_authoritative,
        environment_code=env_code,
        fps=self.scene.fps,
        state_broadcast_interval=getattr(
            self.scene, "authoritative_broadcast_interval", 30
        ),
    )
```

In `add_subject_to_game()`, after all players joined:

```python
# After emitting pyodide_game_ready
if self.scene.server_authoritative:
    self.pyodide_coordinator.start_authoritative_runner(game.game_id)
```

---

## Message Flow

### Normal Gameplay (Unchanged)

```
Client A                      Server                      Client B
    │                            │                            │
    │  pyodide_player_action     │                            │
    ├───────────────────────────►│  pyodide_other_player_     │
    │  {action, frame}           │  action                    │
    │                            ├───────────────────────────►│
    │                            │  {action, frame}           │
    │                            │                            │
    │                            │  (Also feeds action to     │
    │                            │   AuthoritativeGameRunner) │
    │                            │                            │
```

### Periodic State Broadcast (New)

```
                              Server
                                │
                    ┌───────────┴───────────┐
                    │  AuthoritativeRunner  │
                    │  (every N frames)     │
                    └───────────┬───────────┘
                                │
            authoritative_state_sync
                                │
           ┌────────────────────┼────────────────────┐
           ▼                    ▼                    ▼
       Client A             Client B             Client C
       (apply)              (apply)              (apply)
```

---

## Configuration Example

```python
slime_scene = (
    gym_scene.GymScene()
    .scene(scene_id="slime_gym_scene", experiment_config={})
    .policies(policy_mapping=POLICY_MAPPING, frame_skip=1)
    .rendering(fps=30, game_width=600, game_height=250)
    .gameplay(
        default_action=NOOP,
        action_mapping=ACTION_MAPPING,
        num_episodes=5,
        max_steps=3000,
    )
    .runtime(
        run_through_pyodide=True,
        environment_initialization_code_filepath="slimevb_env.py",
        packages_to_install=["slimevb==0.0.4"],
    )
    .multiplayer(
        multiplayer=True,
        # Current client-side sync settings (still used)
        state_broadcast_interval=20,
        # New server-authoritative settings
        server_authoritative=True,
    )
)
```

---

## Comparison: Current vs Server-Authoritative

| Aspect | Current (Host-Based) | Server-Authoritative |
|--------|---------------------|---------------------|
| **Client Simulation** | Local Pyodide | Local Pyodide (unchanged) |
| **Action Relay** | Server-relayed | Server-relayed (unchanged) |
| **Resync Source** | Host client | Server |
| **Resync Path** | Host → Server → Clients | Server → All Clients |
| **Resync Latency** | 2 network hops | 1 network hop |
| **Host Dependency** | Required | None |
| **Server Load** | Relay only | Relay + 1 Python env per game |
| **Hash Verification** | Client-to-client | Optional (server is authoritative) |

---

## Implementation Checklist

### Phase 1: Core Infrastructure
- [ ] Create `AuthoritativeGameRunner` class
- [ ] Add `server_authoritative` field to `PyodideGameState`
- [ ] Extend `receive_action` to feed actions to runner
- [ ] Implement `start_authoritative_runner` method
- [ ] Add eventlet-based game loop

### Phase 2: Configuration
- [ ] Add `server_authoritative` option to `GymScene.multiplayer()`
- [ ] Add `authoritative_broadcast_interval` option
- [ ] Update `GameManager._create_game()` to pass config
- [ ] Start runner when all players join

### Phase 3: Client
- [ ] Add `authoritative_state_sync` socket handler
- [ ] Implement `applyAuthoritativeState()` method
- [ ] Optionally disable hash verification when server-authoritative

### Phase 4: Testing
- [ ] Test with SlimeVolleyball
- [ ] Verify state stays in sync
- [ ] Measure resync latency improvement
- [ ] Test with client disconnect/reconnect

---

## Future Enhancements

1. **Disable Client Hash Checks**: When server-authoritative, client-to-client hash checks become redundant
2. **Adaptive Broadcast Rate**: Increase frequency when detecting drift, decrease when stable
3. **Delta Compression**: Only send state changes instead of full state
4. **Client Verification**: Clients can optionally compare their state to server for debugging
