# Server as Frame-Aligned Stepper Architecture

## Overview

This document details the implementation plan for **Option B**: Server as Frame-Aligned Stepper. Unlike the full server-authoritative approach (which runs an independent game loop), this approach has the server step its environment **only when it has received actions from all players for a given frame**. This ensures perfect frame alignment and eliminates timing drift issues.

### Key Differences from Full Server-Authoritative

| Aspect | Full Server-Authoritative | Frame-Aligned Stepper (This Plan) |
|--------|--------------------------|-----------------------------------|
| Server loop | Independent timer-based | Event-driven (on action receipt) |
| Timing source | Server clock | Client frames (consensus) |
| When server steps | Every 1/FPS seconds | When all actions received for frame N |
| Drift risk | Server vs clients can drift | No drift - all step together |
| Server load | Continuous | On-demand |
| Complexity | Higher (timing sync) | Lower (deterministic) |

---

## Architecture

### Current Flow (Host-Based Resync)

```
Client A (Host)              Server                   Client B
     │                          │                          │
     │  action(frame=100)       │                          │
     ├─────────────────────────►│  relay to B              │
     │                          ├─────────────────────────►│
     │                          │                          │
     │                          │◄─────────────────────────┤
     │                          │  action(frame=100)       │
     │◄─────────────────────────┤  relay to A              │
     │                          │                          │
     │ (both step locally)      │  (no env on server)      │ (both step locally)
     │                          │                          │
     │  [hash mismatch]         │                          │
     │  request_full_state ────►│                          │
     │◄──── full_state ─────────│─────────────────────────►│
```

**Problems:**
- Server doesn't know the true state
- Resync requires 2 hops (Host → Server → Clients)
- Host is single point of failure for state

### Proposed Flow (Frame-Aligned Stepper)

```
Client A                     Server                   Client B
     │                          │                          │
     │  action(frame=100)       │  [buffer action]         │
     ├─────────────────────────►│                          │
     │                          │  relay to B              │
     │                          ├─────────────────────────►│
     │                          │                          │
     │                          │◄─────────────────────────┤
     │◄─────────────────────────┤  action(frame=100)       │
     │  relay to A              │  [all actions received!] │
     │                          │                          │
     │ (step locally)           │  (step server env)       │ (step locally)
     │                          │                          │
     │                          │  [every N frames]        │
     │◄─────────────────────────┤  authoritative_state     │
     │  (apply if different)    ├─────────────────────────►│
     │                          │                          │ (apply if different)
```

**Benefits:**
- Server has authoritative state at every frame
- Resync is 1 hop (Server → All Clients)
- No host dependency
- Perfect frame alignment (no drift)

---

## Implementation Plan

### Phase 1: Server-Side Environment Runner (Frame-Aligned)

#### 1.1 Create `ServerGameRunner` Class

**File**: `interactive_gym/server/server_game_runner.py` (new file)

```python
"""
Server Game Runner - Frame-Aligned Authoritative Environment

Runs a Python environment on the server that steps in sync with client frames.
Unlike the timer-based AuthoritativeGameRunner, this steps ONLY when all
player actions for a frame have been received.

Key properties:
- Deterministic: Steps exactly when clients step
- No drift: Server frame always matches client consensus
- On-demand: No background loop, steps on action events
"""

import logging
import threading
from typing import Any, Dict

logger = logging.getLogger(__name__)


class ServerGameRunner:
    """
    Frame-aligned authoritative game environment.

    Steps only when all player actions are received for the current frame.
    Broadcasts authoritative state periodically.
    """

    def __init__(
        self,
        game_id: str,
        environment_code: str,
        num_players: int,
        state_broadcast_interval: int = 30,
        sio=None,
    ):
        self.game_id = game_id
        self.environment_code = environment_code
        self.num_players = num_players
        self.state_broadcast_interval = state_broadcast_interval
        self.sio = sio

        # Environment state
        self.env = None
        self.frame_number = 0
        self.step_num = 0
        self.episode_num = 0
        self.cumulative_rewards: Dict[str, float] = {}
        self.is_initialized = False

        # Action collection for current frame
        self.pending_actions: Dict[int, Dict[str, Any]] = {}  # frame -> {player_id: action}
        self.action_lock = threading.Lock()

        # Track expected players
        self.player_ids: set = set()

        # Default action for fallback
        self.default_action = 0

    def initialize_environment(self, rng_seed: int):
        """
        Initialize environment from code string.
        Uses exec() to run the same code clients run in Pyodide.
        """
        env_globals = {"__name__": "__main__"}

        # Set up numpy seed before execution
        exec(f"""
import numpy as np
import random
np.random.seed({rng_seed})
random.seed({rng_seed})
""", env_globals)

        # Execute environment initialization code
        exec(self.environment_code, env_globals)

        if "env" not in env_globals:
            raise RuntimeError(
                "Environment initialization code must define 'env' variable"
            )

        self.env = env_globals["env"]

        # Reset with seed
        obs, info = self.env.reset(seed=rng_seed)

        # Initialize cumulative rewards
        for player_id in obs.keys():
            self.cumulative_rewards[str(player_id)] = 0.0

        self.is_initialized = True
        self.frame_number = 0
        self.step_num = 0

        logger.info(
            f"[ServerGameRunner] Initialized environment for game {self.game_id} "
            f"with seed {rng_seed}"
        )

    def add_player(self, player_id: str | int):
        """Register a player ID."""
        self.player_ids.add(str(player_id))

    def receive_action(
        self,
        player_id: str | int,
        action: Any,
        frame_number: int
    ) -> bool:
        """
        Receive an action from a player.

        Returns True if this action completed the frame (all players submitted).
        """
        player_id_str = str(player_id)

        with self.action_lock:
            # Initialize frame action dict if needed
            if frame_number not in self.pending_actions:
                self.pending_actions[frame_number] = {}

            # Store action
            self.pending_actions[frame_number][player_id_str] = action

            # Check if we have all actions for this frame
            frame_actions = self.pending_actions[frame_number]
            have_all = len(frame_actions) >= len(self.player_ids)

            if have_all:
                logger.debug(
                    f"[ServerGameRunner] Game {self.game_id}: "
                    f"All actions received for frame {frame_number}"
                )

            return have_all

    def step_frame(self, frame_number: int) -> Dict[str, Any]:
        """
        Step the environment for a specific frame.

        Call this after receive_action returns True.
        Returns step results and whether to broadcast state.
        """
        with self.action_lock:
            if frame_number not in self.pending_actions:
                logger.warning(
                    f"[ServerGameRunner] No actions for frame {frame_number}"
                )
                return None

            frame_actions = self.pending_actions[frame_number]

            # Build action dict with proper types
            actions = {}
            for player_id in self.player_ids:
                if player_id in frame_actions:
                    actions[player_id] = frame_actions[player_id]
                else:
                    # Fallback to default
                    actions[player_id] = self.default_action

            # Clean up old frames
            self._cleanup_old_frames(frame_number)

        # Step environment (outside lock to avoid blocking)
        try:
            # Convert keys to int if needed (environment expects int keys)
            env_actions = {
                int(k) if k.isnumeric() else k: v
                for k, v in actions.items()
            }

            obs, rewards, terminateds, truncateds, infos = self.env.step(env_actions)

            # Update cumulative rewards
            for player_id, reward in rewards.items():
                pid_str = str(player_id)
                if pid_str in self.cumulative_rewards:
                    self.cumulative_rewards[pid_str] += reward

            self.frame_number = frame_number
            self.step_num += 1

            # Check if should broadcast
            should_broadcast = (
                self.step_num % self.state_broadcast_interval == 0
            )

            # Check for episode end
            episode_done = terminateds.get("__all__", False) or truncateds.get("__all__", False)

            return {
                "terminateds": terminateds,
                "truncateds": truncateds,
                "episode_done": episode_done,
                "should_broadcast": should_broadcast,
                "frame_number": frame_number,
            }

        except Exception as e:
            logger.error(
                f"[ServerGameRunner] Error stepping game {self.game_id}: {e}"
            )
            import traceback
            traceback.print_exc()
            return None

    def get_authoritative_state(self) -> Dict[str, Any]:
        """
        Get full authoritative state for broadcast.
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
        Broadcast authoritative state to all clients.
        """
        if self.sio is None:
            return

        state = self.get_authoritative_state()

        self.sio.emit(
            "server_authoritative_state",
            {
                "game_id": self.game_id,
                "state": state,
            },
            room=self.game_id,
        )

        logger.debug(
            f"[ServerGameRunner] Broadcast state at frame {self.frame_number}"
        )

    def handle_episode_end(self):
        """
        Handle episode completion - reset environment.
        """
        self.episode_num += 1
        self.step_num = 0

        obs, info = self.env.reset()

        # Broadcast state after reset
        self.broadcast_state()

        logger.info(
            f"[ServerGameRunner] Episode {self.episode_num} started for {self.game_id}"
        )

    def _cleanup_old_frames(self, current_frame: int):
        """Remove action data for old frames."""
        frames_to_remove = [
            f for f in self.pending_actions.keys()
            if f < current_frame - 10  # Keep small buffer
        ]
        for f in frames_to_remove:
            del self.pending_actions[f]

    def stop(self):
        """Clean up resources."""
        self.is_initialized = False
        self.env = None
        logger.info(f"[ServerGameRunner] Stopped game {self.game_id}")
```

#### 1.2 Extend PyodideGameCoordinator

**File**: `interactive_gym/server/pyodide_game_coordinator.py`

Add to `PyodideGameState`:

```python
@dataclasses.dataclass
class PyodideGameState:
    # ... existing fields ...

    # Server-side environment runner (frame-aligned)
    server_runner: "ServerGameRunner | None" = None
    server_authoritative: bool = False
```

Modify `create_game()`:

```python
def create_game(
    self,
    game_id: str,
    num_players: int,
    server_authoritative: bool = False,
    environment_code: str = None,
    state_broadcast_interval: int = 30,
) -> PyodideGameState:
    """
    Initialize a new Pyodide multiplayer game.

    If server_authoritative=True and environment_code is provided,
    creates a ServerGameRunner that steps in sync with client frames.
    """
    # ... existing creation code ...

    game_state.server_authoritative = server_authoritative

    if server_authoritative and environment_code:
        from interactive_gym.server.server_game_runner import ServerGameRunner

        game_state.server_runner = ServerGameRunner(
            game_id=game_id,
            environment_code=environment_code,
            num_players=num_players,
            state_broadcast_interval=state_broadcast_interval,
            sio=self.sio,
        )

    return game_state
```

Modify `_start_game()`:

```python
def _start_game(self, game_id: str):
    """Mark game as active and initialize server runner if enabled."""
    game = self.games[game_id]
    game.is_active = True

    # Initialize server runner with same seed as clients
    if game.server_authoritative and game.server_runner:
        for player_id in game.players.keys():
            game.server_runner.add_player(player_id)
        game.server_runner.initialize_environment(game.rng_seed)
        logger.info(f"[Coordinator] Started server runner for {game_id}")

    # ... rest of existing code ...
```

Modify `receive_action()`:

```python
def receive_action(
    self,
    game_id: str,
    player_id: str | int,
    action: Any,
    frame_number: int
):
    """
    Receive action from player.

    1. Relay to other players (existing behavior)
    2. Send to server runner (if enabled)
    3. If all actions received, step server env and maybe broadcast
    """
    with self.lock:
        if game_id not in self.games:
            return

        game = self.games[game_id]

        if not game.is_active:
            return

        # Existing: Relay to other players
        for other_player_id, socket_id in game.players.items():
            if other_player_id != player_id:
                self.sio.emit('pyodide_other_player_action', {
                    'player_id': player_id,
                    'action': action,
                    'frame_number': frame_number,
                    'timestamp': time.time()
                }, room=socket_id)

        # NEW: Feed to server runner if enabled
        if game.server_authoritative and game.server_runner:
            all_received = game.server_runner.receive_action(
                player_id, action, frame_number
            )

            if all_received:
                # Step the server environment
                result = game.server_runner.step_frame(frame_number)

                if result:
                    # Broadcast state if it's time
                    if result.get("should_broadcast"):
                        game.server_runner.broadcast_state()

                    # Handle episode end
                    if result.get("episode_done"):
                        game.server_runner.handle_episode_end()
```

---

### Phase 2: Client-Side Handler

#### 2.1 Update `pyodide_multiplayer_game.js`

Add handler for server authoritative state:

```javascript
// In setupMultiplayerHandlers()

// Receive authoritative state from server
socket.on('server_authoritative_state', async (data) => {
    if (data.game_id !== this.gameId) return;

    const state = data.state;

    // Check if we're significantly out of sync
    const frameDiff = Math.abs(this.frameNumber - state.frame_number);

    if (frameDiff > 5) {
        console.log(
            `[MultiplayerPyodide] Applying server state ` +
            `(drift: ${frameDiff} frames)`
        );
        await this.applyServerState(state);
    } else {
        // Minor drift - just update rewards for HUD consistency
        this.cumulative_rewards = state.cumulative_rewards;
        ui_utils.updateHUDText(this.getHUDText());
    }
});

// New method
async applyServerState(state) {
    /**
     * Apply authoritative state from server.
     * Only called when drift exceeds threshold.
     */

    // Apply environment state if present
    if (state.env_state) {
        await this.pyodide.runPythonAsync(`
env.set_state(${JSON.stringify(state.env_state)})
        `);
    }

    // Update tracking variables
    this.frameNumber = state.frame_number;
    this.step_num = state.step_num;
    this.num_episodes = state.episode_num;
    this.cumulative_rewards = state.cumulative_rewards;

    // Clear action queues since we've snapped to server state
    for (const playerId in this.otherPlayerActionQueues) {
        this.otherPlayerActionQueues[playerId] = [];
    }

    // Update HUD
    ui_utils.updateHUDText(this.getHUDText());

    console.log(
        `[MultiplayerPyodide] Applied server state, ` +
        `now at frame ${this.frameNumber}`
    );
}
```

#### 2.2 Disable/Reduce Hash-Based Sync When Server Authoritative

When server is authoritative, client-to-client hash verification becomes redundant:

```javascript
// In step() method

// Optionally trigger periodic state sync (only if not server-authoritative)
if (!this.serverAuthoritative &&
    this.stateSyncFrequencyFrames !== null &&
    this.frameNumber % this.stateSyncFrequencyFrames === 0) {
    this.triggerStateVerification();
}
```

Add config flag:

```javascript
constructor(config) {
    // ... existing ...

    // Server authoritative mode (disables client hash verification)
    this.serverAuthoritative = config.server_authoritative || false;
}
```

---

### Phase 3: Configuration

#### 3.1 Add Options to GymScene

**File**: `interactive_gym/scenes/gym_scene.py`

Add to `__init__`:

```python
# Server-authoritative multiplayer settings
self.server_authoritative: bool = False
self.server_state_broadcast_interval: int = 30  # Frames between broadcasts
```

Configure via `.runtime()` for browser execution and `.multiplayer()` for multiplayer/server-authoritative settings:

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
    # ... existing code ...
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
        server_authoritative: If True, server runs a parallel environment
            that steps in sync with clients and broadcasts authoritative
            state periodically. This eliminates host dependency and ensures
            faster resyncs. Default False.
        state_broadcast_interval: Frames between server state broadcasts.
            Lower = more bandwidth, faster drift correction.
            Higher = less bandwidth, potential for longer drift.
            Default 30 (~1 sec at 30fps).
    """
    # ... existing code ...

    if server_authoritative is not NotProvided:
        assert isinstance(server_authoritative, bool)
        self.server_authoritative = server_authoritative

    if state_broadcast_interval is not NotProvided:
        assert isinstance(state_broadcast_interval, int)
        assert state_broadcast_interval > 0
        self.server_state_broadcast_interval = state_broadcast_interval

    return self
```

---

### Phase 4: GameManager Integration

**File**: `interactive_gym/server/game_manager.py`

In the Pyodide game creation section, pass server_authoritative config:

```python
# When creating Pyodide coordinator game
if self.scene.run_through_pyodide and self.scene.pyodide_multiplayer:
    env_code = None

    if self.scene.server_authoritative:
        env_code = self.scene.environment_initialization_code

    self.pyodide_coordinator.create_game(
        game_id=game.game_id,
        num_players=num_human_players,
        server_authoritative=self.scene.server_authoritative,
        environment_code=env_code,
        state_broadcast_interval=self.scene.server_state_broadcast_interval,
    )
```

---

### Phase 5: Pass Config to Client

**File**: `interactive_gym/server/static/js/index.js` or where game config is built

Ensure `server_authoritative` is passed to the client game:

```javascript
// When creating MultiplayerPyodideGame
const gameConfig = {
    // ... existing config ...
    server_authoritative: sceneConfig.server_authoritative || false,
};
```

---

## Configuration Example

```python
slime_scene = (
    gym_scene.GymScene()
    .scene(scene_id="slime_gym_scene")
    .policies(policy_mapping={0: "human", 1: "human"})
    .rendering(fps=30, game_width=600, game_height=250)
    .gameplay(
        default_action=0,
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
        # Enable server-authoritative mode
        server_authoritative=True,
        state_broadcast_interval=30,  # ~1 sec at 30fps
    )
)
```

---

## Message Flow Summary

### Normal Gameplay

```
Client A                     Server                     Client B
    │                           │                           │
    │ action(frame=N, p=0)      │                           │
    ├──────────────────────────►│ buffer action for p=0     │
    │                           ├──────────────────────────►│ relay
    │                           │                           │
    │                           │◄──────────────────────────┤
    │◄──────────────────────────┤ action(frame=N, p=1)      │
    │ relay                     │ buffer action for p=1     │
    │                           │                           │
    │ step(N) locally           │ [all actions received]    │ step(N) locally
    │                           │ step(N) on server         │
    │                           │                           │
```

### State Broadcast (Every N Frames)

```
                             Server
                                │
                    [step_num % 30 == 0]
                                │
                    server_authoritative_state
                                │
              ┌─────────────────┴─────────────────┐
              ▼                                   ▼
          Client A                            Client B
    [if drift > 5: apply]               [if drift > 5: apply]
```

---

## Benefits Over Current System

1. **No Host Dependency**: Server has authoritative state, any client can disconnect
2. **Faster Resync**: 1 hop (Server → Clients) vs 2 hops (Host → Server → Clients)
3. **Deterministic**: Server steps exactly when clients step (same frame numbers)
4. **No Timing Drift**: No independent server clock that can drift from clients
5. **On-Demand Processing**: Server only does work when actions arrive (no idle loop)
6. **Gradual Degradation**: Clients continue running even if server lags; corrections are smooth

---

## Implementation Checklist

### Phase 1: Server Runner
- [ ] Create `server_game_runner.py` with `ServerGameRunner` class
- [ ] Implement `initialize_environment()` with exec-based setup
- [ ] Implement `receive_action()` with frame-based buffering
- [ ] Implement `step_frame()` for synchronized stepping
- [ ] Implement `broadcast_state()` for periodic state push

### Phase 2: Coordinator Integration
- [ ] Add `server_runner` and `server_authoritative` to `PyodideGameState`
- [ ] Modify `create_game()` to optionally create server runner
- [ ] Modify `_start_game()` to initialize server runner with seed
- [ ] Modify `receive_action()` to feed actions to server and step when complete

### Phase 3: Configuration
- [ ] Add `server_authoritative` to `GymScene`
- [ ] Add `server_state_broadcast_interval` to `GymScene`
- [ ] Update `.runtime()` and `.multiplayer()` methods to accept new parameters

### Phase 4: Client
- [ ] Add `server_authoritative_state` socket handler
- [ ] Implement `applyServerState()` method
- [ ] Add `serverAuthoritative` config flag
- [ ] Optionally disable hash verification when server authoritative

### Phase 5: Integration
- [ ] Pass config through GameManager to coordinator
- [ ] Pass config to client via scene config
- [ ] Test with SlimeVolleyball

### Phase 6: Testing
- [ ] Verify frame alignment (server and clients at same frame)
- [ ] Test state broadcast and application
- [ ] Test with artificial latency
- [ ] Test player disconnect scenarios
- [ ] Measure resync latency improvement

---

## Future Enhancements

1. **Delta Compression**: Send only state changes instead of full state
2. **Adaptive Broadcast Rate**: Increase frequency when detecting drift
3. **Client Verification**: Allow clients to compare their state to server (debug mode)
4. **Graceful Degradation**: If server runner fails, fall back to host-based resync
