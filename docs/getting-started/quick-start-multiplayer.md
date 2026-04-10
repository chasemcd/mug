# Quick Start: Multiplayer

This guide extends the single-player [Quick Start](quick-start.md) to build a two-player experiment. You will create a simple grid-based coordination game where two participants move on the same board, with their environments synchronized in real time.

## Prerequisites

Complete the single-player [Quick Start](quick-start.md) first, then ensure you have MUG installed with server dependencies:

```bash
pip install multi-user-gymnasium[server]
```

You should be familiar with:

- Creating custom environments with the Surface API
- Writing experiment scripts with scenes and stagers
- Running a MUG server

## Architecture Overview

MUG supports two multiplayer architectures. Choose the one that fits your experiment's requirements.

### Peer-to-Peer (P2P) with GGPO Rollback Netcode

In P2P mode, each participant runs the environment locally in their browser via Pyodide. Inputs are exchanged directly between browsers using WebRTC data channels. GGPO rollback netcode keeps the simulations synchronized.

```text
+-------------------+         WebRTC DataChannel         +-------------------+
|   Player 1        | <--------------------------------> |   Player 2        |
|   Browser          |                                   |   Browser          |
|                   |                                     |                   |
|  +--------------+ |                                     | +--------------+  |
|  | Pyodide      | |                                     | | Pyodide      |  |
|  |  - env.step()| |                                     | | - env.step() |  |
|  |  - render()  | |                                     | | - render()   |  |
|  +--------------+ |                                     | +--------------+  |
+-------------------+                                     +-------------------+
         |                                                         |
         |              MUG Server (Flask-SocketIO)                |
         |         (signaling, matchmaking, data logging)          |
         +------------------------+--------------------------------+
                                  |
                           +------+------+
                           | MUG Server  |
                           | - waitroom  |
                           | - signaling |
                           | - logging   |
                           +-------------+
```

**When to use P2P:**

- Low-latency requirements (fighting games, fast-paced coordination)
- Experiments where both participants need immediate input feedback
- You want to minimize server load

### Server-Authoritative Mode

In server-authoritative mode, the environment runs on the MUG server. Participant inputs are sent to the server, which steps the environment, renders the frame, and broadcasts the result to all connected clients.

```text
+-------------------+                                     +-------------------+
|   Player 1        |        SocketIO (actions)           |   Player 2        |
|   Browser          | ------>                    <------ |   Browser          |
|                   |                                     |                   |
|   (render only)   |        SocketIO (frames)            |   (render only)   |
|                   | <------                    ------> |                    |
+-------------------+         |              |            +-------------------+
                              v              v
                        +---------------------+
                        |     MUG Server      |
                        |  (Flask-SocketIO)   |
                        |                     |
                        |  +---------------+  |
                        |  | env.step()    |  |
                        |  | render()      |  |
                        |  +---------------+  |
                        +---------------------+
```

**When to use server-authoritative:**

- The environment has hidden state that participants should not see
- You need a single canonical game state (e.g., economic games, turn-based tasks)
- Determinism is critical and you cannot tolerate rollback artifacts
- The environment requires server-side resources (large models, databases)

---

## Step 1: Create the Environment

Create a file called `coordination_grid_env.py`. This is a simple two-player grid world where players must navigate to a shared goal location.

```python
import numpy as np
import gymnasium as gym
from gymnasium import spaces
from mug.rendering import Surface


class CoordinationGridEnv(gym.Env):
    """Two-player grid coordination game."""

    metadata = {"render_modes": ["mug"]}

    def __init__(self, render_mode="mug", grid_size=10):
        super().__init__()
        self.render_mode = render_mode
        self.grid_size = grid_size
        self.cell_size = 50
        self.width = grid_size * self.cell_size
        self.height = grid_size * self.cell_size

        self.surface = Surface(width=self.width, height=self.height)

        # Action space: 0=up, 1=down, 2=left, 3=right, 4=noop
        self.action_space = spaces.Dict({
            "player_0": spaces.Discrete(5),
            "player_1": spaces.Discrete(5),
        })

        self.observation_space = spaces.Dict({
            "player_0": spaces.Box(low=0, high=grid_size - 1, shape=(2,), dtype=np.int32),
            "player_1": spaces.Box(low=0, high=grid_size - 1, shape=(2,), dtype=np.int32),
        })

        self.goal = np.array([grid_size - 1, grid_size - 1], dtype=np.int32)
        self.positions = {}

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        self.surface.reset()

        self.positions = {
            "player_0": np.array([0, 0], dtype=np.int32),
            "player_1": np.array([self.grid_size - 1, 0], dtype=np.int32),
        }

        obs = {pid: self.positions[pid].copy() for pid in self.positions}
        return obs, {}

    def step(self, actions: dict[str, int]):
        moves = {
            0: np.array([0, -1]),   # up
            1: np.array([0, 1]),    # down
            2: np.array([-1, 0]),   # left
            3: np.array([1, 0]),    # right
            4: np.array([0, 0]),    # noop
        }

        for pid, action in actions.items():
            delta = moves.get(action, np.array([0, 0]))
            new_pos = self.positions[pid] + delta
            new_pos = np.clip(new_pos, 0, self.grid_size - 1)
            self.positions[pid] = new_pos

        # Both players must reach the goal
        both_at_goal = all(
            np.array_equal(self.positions[pid], self.goal)
            for pid in self.positions
        )

        reward = {pid: 1.0 if both_at_goal else 0.0 for pid in self.positions}
        terminated = both_at_goal
        truncated = False

        obs = {pid: self.positions[pid].copy() for pid in self.positions}
        return obs, reward, terminated, truncated, {}

    def render(self):
        assert self.render_mode == "mug"

        cs = self.cell_size

        # persistent: grid lines
        for i in range(self.grid_size + 1):
            self.surface.line(
                points=[(i * cs, 0), (i * cs, self.height)],
                color="#cccccc", width=1,
                persistent=True, id=f"vline_{i}",
            )
            self.surface.line(
                points=[(0, i * cs), (self.width, i * cs)],
                color="#cccccc", width=1,
                persistent=True, id=f"hline_{i}",
            )

        # persistent: goal
        gx, gy = self.goal
        self.surface.rect(
            x=gx * cs, y=gy * cs, width=cs, height=cs,
            color="#90EE90",
            persistent=True, id="goal",
        )

        # transient: players
        for pid, color in [("player_0", "#FF6B6B"), ("player_1", "#4ECDC4")]:
            px, py = self.positions[pid]
            self.surface.circle(
                x=px * cs + cs // 2,
                y=py * cs + cs // 2,
                radius=cs // 3,
                color=color,
            )

        return self.surface.commit()


# Environment instance loaded by Pyodide (must be named 'env')
env = CoordinationGridEnv(render_mode="mug")
```

!!! note

    The environment accepts a `dict` of actions keyed by player ID. This is required for all multiplayer environments in MUG, regardless of architecture.

---

## Step 2: Create the Experiment Script

Create the main experiment file `coordination_experiment.py`:

```python
from __future__ import annotations

import eventlet

eventlet.monkey_patch()

from mug.server import app
from mug.scenes import stager, static_scene, gym_scene
from mug.configurations import experiment_config, configuration_constants

# Action constants
UP = 0
DOWN = 1
LEFT = 2
RIGHT = 3
NOOP = 4

# Key mappings (same for both players)
action_mapping = {
    "ArrowUp": UP,
    "ArrowDown": DOWN,
    "ArrowLeft": LEFT,
    "ArrowRight": RIGHT,
}

# Scene 1: Welcome
start_scene = (
    static_scene.StartScene()
    .scene(scene_id="welcome")
    .display(
        scene_header="Welcome to Coordination Grid!",
        scene_body=(
            "You and a partner will navigate a grid together. "
            "Both of you must reach the green goal square. "
            "Use arrow keys to move."
        ),
    )
)

# Scene 2: Wait room
wait_scene = (
    static_scene.WaitScene()
    .scene(scene_id="waitroom")
    .display(
        scene_header="Waiting for partner...",
        scene_body="Please wait while we find another participant.",
    )
)

# Scene 3: Game
game_scene = (
    gym_scene.GymScene()
    .scene(scene_id="coordination_game")
    .policies(
        policy_mapping={
            "player_0": configuration_constants.PolicyTypes.Human,
            "player_1": configuration_constants.PolicyTypes.Human,
        }
    )
    .rendering(
        fps=15,
        game_width=500,
        game_height=500,
    )
    .gameplay(
        default_action=NOOP,
        action_mapping=action_mapping,
        num_episodes=3,
        max_steps=200,
        input_mode=configuration_constants.InputModes.PressedKeys,
    )
    .content(
        scene_header="Coordination Grid",
        scene_body="<center><p>Loading environment...</p></center>",
        in_game_scene_body="<center><p>Navigate to the green square together!</p></center>",
    )
    .multiplayer(
        num_players=2,
        player_ids=["player_0", "player_1"],
    )
    .waitroom(
        min_players=2,
        max_wait_time=120,
        timeout_scene_id="thanks",
    )
    .runtime(
        run_through_pyodide=True,
        environment_initialization_code_filepath="coordination_grid_env.py",
    )
)

# Scene 4: Thank you
end_scene = (
    static_scene.EndScene()
    .scene(scene_id="thanks")
    .display(
        scene_header="Thanks for participating!",
        scene_body="You've completed the experiment.",
    )
)

# Sequence scenes
experiment_stager = stager.Stager(
    scenes=[start_scene, wait_scene, game_scene, end_scene]
)

if __name__ == "__main__":
    config = (
        experiment_config.ExperimentConfig()
        .experiment(stager=experiment_stager, experiment_id="coordination_grid")
        .hosting(port=8000, host="0.0.0.0")
    )
    app.run(config)
```

---

## Multiplayer Configuration

The key difference from a single-player experiment is the additional configuration methods on the game scene.

### `.multiplayer()`

Configures the multiplayer session:

```python
.multiplayer(
    num_players=2,                    # Number of human players
    player_ids=["player_0", "player_1"],  # Must match env action/obs keys
)
```

- `num_players` -- the number of human participants in each session.
- `player_ids` -- a list of string IDs that correspond to the keys in the environment's action and observation dictionaries.

### `.waitroom()`

Configures the matchmaking wait room:

```python
.waitroom(
    min_players=2,         # Minimum players to start the game
    max_wait_time=120,     # Seconds before timeout
    timeout_scene_id="thanks",  # Scene to redirect to on timeout
)
```

- `min_players` -- the game starts once this many participants are waiting.
- `max_wait_time` -- if a match is not found within this duration, the participant is redirected to `timeout_scene_id`.

### `.rendering()`

In multiplayer mode, rendering works the same as single-player. Each participant sees the same rendered frame. If you need per-player views, use the `player_id` argument in your `render()` method.

```python
.rendering(
    fps=15,
    game_width=500,
    game_height=500,
)
```

!!! note

    Lower FPS values (10-15) are recommended for multiplayer experiments to reduce bandwidth and synchronization overhead.

### `.gameplay()`

Gameplay configuration is shared across all players by default. Each participant uses the same `action_mapping` and `default_action`.

```python
.gameplay(
    default_action=NOOP,
    action_mapping=action_mapping,
    num_episodes=3,
    max_steps=200,
    input_mode=configuration_constants.InputModes.PressedKeys,
)
```

---

## GGPO Rollback Netcode

When using P2P mode (`run_through_pyodide=True` with multiple human players), MUG uses GGPO-style rollback netcode to keep the two browser-side simulations in sync.

**How it works:**

1. Each browser runs its own copy of the environment via Pyodide.
2. On each frame, the local player's input is applied immediately (zero input lag).
3. The remote player's input is predicted (typically: repeat last known input).
4. When the actual remote input arrives over WebRTC, the engine compares it to the prediction.
5. If the prediction was wrong, the engine rolls back to the last confirmed state, replays with correct inputs, and fast-forwards to the current frame.

**Benefits:**

- Local inputs feel instant -- no waiting for the network
- Short-lived mispredictions are corrected within a few frames
- Works well on connections with up to ~150ms round-trip latency

**Configuration:**

```python
.multiplayer(
    num_players=2,
    player_ids=["player_0", "player_1"],
    ggpo_max_rollback_frames=8,    # Max frames to roll back (default: 8)
    ggpo_input_delay_frames=2,     # Intentional input delay to reduce rollbacks (default: 2)
)
```

- `ggpo_max_rollback_frames` -- the maximum number of frames the engine will roll back. Higher values tolerate more latency but may cause visible "jumps" on correction.
- `ggpo_input_delay_frames` -- adds a small intentional delay to local input, giving remote inputs more time to arrive before the frame is simulated. A value of 2 means inputs are applied 2 frames after being pressed.

!!! warning

    Your environment's `step()` and `render()` methods must be **deterministic** for rollback to work correctly. Given the same sequence of actions from the same initial state, both clients must produce identical results. Avoid using `random.random()` directly; use the environment's seeded RNG via `self.np_random` instead.

---

## Server-Authoritative Mode

To run the environment on the server instead of in the browser, set `run_through_pyodide=False` and provide the environment class directly.

Replace the `.runtime()` call in the game scene:

```python
from coordination_grid_env import CoordinationGridEnv

game_scene = (
    gym_scene.GymScene()
    .scene(scene_id="coordination_game")
    .policies(
        policy_mapping={
            "player_0": configuration_constants.PolicyTypes.Human,
            "player_1": configuration_constants.PolicyTypes.Human,
        }
    )
    .rendering(
        fps=15,
        game_width=500,
        game_height=500,
    )
    .gameplay(
        default_action=NOOP,
        action_mapping=action_mapping,
        num_episodes=3,
        max_steps=200,
        input_mode=configuration_constants.InputModes.PressedKeys,
    )
    .content(
        scene_header="Coordination Grid",
        scene_body="<center><p>Waiting for game to start...</p></center>",
        in_game_scene_body="<center><p>Navigate to the green square together!</p></center>",
    )
    .multiplayer(
        num_players=2,
        player_ids=["player_0", "player_1"],
    )
    .waitroom(
        min_players=2,
        max_wait_time=120,
        timeout_scene_id="thanks",
    )
    .runtime(
        run_through_pyodide=False,
        environment_class=CoordinationGridEnv,
        environment_kwargs={"render_mode": "mug", "grid_size": 10},
    )
)
```

**Key differences from P2P mode:**

- `run_through_pyodide=False` -- the environment runs on the server
- `environment_class` -- pass the class directly (not a file path)
- `environment_kwargs` -- keyword arguments forwarded to the environment constructor
- No GGPO rollback -- the server is the single source of truth
- Higher latency -- every input round-trips through the server before the frame updates

!!! note

    In server-authoritative mode, participants do not need to download Pyodide or your environment code. This means faster initial load times but higher per-frame latency.

For a full server-authoritative example, see [Overcooked Multiplayer](../examples/overcooked-multiplayer.md).

---

## Step 3: Run the Experiment

Start the server:

```bash
python coordination_experiment.py
```

Open two browser tabs (or two separate browsers) to `http://localhost:8000`. Each tab represents one participant. After both click through the welcome screen, they will be matched in the wait room and the game will begin.

!!! tip

    For local testing, use two browser windows side by side. In production, each participant connects from their own machine.

---

## WebRTC / TURN Configuration

P2P mode uses WebRTC data channels for direct browser-to-browser communication. In most local and LAN setups, WebRTC connects automatically via STUN servers. However, when participants are behind restrictive firewalls or symmetric NATs, you need a TURN relay server.

**Default configuration (STUN only):**

```python
config = (
    experiment_config.ExperimentConfig()
    .experiment(stager=experiment_stager, experiment_id="coordination_grid")
    .hosting(port=8000, host="0.0.0.0")
    .webrtc(
        ice_servers=[
            {"urls": "stun:stun.l.google.com:19302"},
        ]
    )
)
```

**With a TURN server:**

```python
config = (
    experiment_config.ExperimentConfig()
    .experiment(stager=experiment_stager, experiment_id="coordination_grid")
    .hosting(port=8000, host="0.0.0.0")
    .webrtc(
        ice_servers=[
            {"urls": "stun:stun.l.google.com:19302"},
            {
                "urls": "turn:your-turn-server.example.com:3478",
                "username": "your_username",
                "credential": "your_password",
            },
        ]
    )
)
```

!!! warning

    Without a TURN server, some participants behind corporate firewalls or carrier-grade NAT will fail to connect in P2P mode. For production experiments with diverse participant networks, always configure a TURN server. Free/open TURN options include [coturn](https://github.com/coturn/coturn) (self-hosted) and [Twilio Network Traversal Service](https://www.twilio.com/docs/stun-turn).

---

## Troubleshooting

**Players are not matched**

- Ensure both participants are accessing the same server URL.
- Check that `min_players` in `.waitroom()` matches `num_players` in `.multiplayer()`.
- Verify the wait room scene is included in the stager's scene list before the game scene.

**"WebRTC connection failed"**

- Check browser console (F12) for ICE connection errors.
- If participants are on different networks, configure a TURN server (see above).
- Ensure the MUG server is accessible to both participants (check firewall rules).

**High latency or stuttering in P2P mode**

- Reduce `fps` in `.rendering()` to 10 or lower.
- Increase `ggpo_input_delay_frames` to 3 or 4 to reduce rollback frequency.
- Test with participants on lower-latency connections.

**Environment state diverges between players (P2P)**

- Ensure your environment is fully deterministic. Use `self.np_random` instead of `random` or `np.random`.
- Verify that `step()` produces identical output given identical inputs and state.
- Check that you are not using Python `dict` iteration order in a way that differs between clients (unlikely in Python 3.7+ but worth verifying).

**"Max wait time exceeded"**

- Participants waited longer than `max_wait_time` without a match.
- Increase `max_wait_time` or coordinate participant arrival times.
- In the `timeout_scene_id` scene, consider providing a message explaining the timeout and offering a way to retry.

**Server-authoritative mode: slow frame updates**

- Reduce environment complexity or rendering detail.
- Lower `fps` to reduce the number of frames per second the server must compute and send.
- Consider switching to P2P mode if latency is the primary concern.

---

## Next Steps

- See [Server Mode](../core-concepts/server-mode.md) for a detailed explanation of server-authoritative architecture and advanced configuration
- See [Overcooked Client-Side](../examples/overcooked-client-side.md) for a full P2P multiplayer example with GGPO
- See [Overcooked Multiplayer](../examples/overcooked-multiplayer.md) for a full server-authoritative example
- Review the [Quick Start](quick-start.md) if you need a refresher on single-player experiment basics
