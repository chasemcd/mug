# Overcooked: Human-Human (Server-Side)

Two-player cooperative experiment where the environment runs on the server and streams render state to both participants' browsers. The browsers are thin clients that display the game and capture input. Use server-authoritative mode when your environment has compiled dependencies, requires GPU inference, or cannot run in Pyodide.

For the client-side (P2P/GGPO) version of this example, see [Overcooked: Client-Side](overcooked-client-side.md).

## Overview

Two human participants collaborate as chefs to prepare and deliver dishes in the Cramped Room kitchen layout. The server runs the environment, collects actions from both browsers, steps the environment, renders the state, and streams it back to both clients.

**What you'll learn:**

- Server-authoritative multiplayer configuration
- Using `.multiplayer(mode="server_authoritative")`
- Using `.environment()` for server-side environment creation
- Player matchmaking and waitroom functionality
- Sprite-based rendering with atlas preloading
- Post-game feedback surveys

## Features Demonstrated

| Feature | Details |
|---------|---------|
| **Execution Mode** | Server-authoritative |
| **Players** | 2 humans |
| **Environment** | CoGrid Overcooked (Cramped Room layout) |
| **Rendering** | Sprite atlases with tile-based rendering |
| **Input** | Arrow keys + action keys (W, Q) |
| **Matchmaking** | Automatic FIFO player pairing in waitroom |
| **Complexity** | Advanced |

## Prerequisites

1. Clone the MUG repository and install with server dependencies:

    ```bash
    git clone https://github.com/chasemcd/mug.git
    cd mug
    pip install -e .[server]
    ```

2. Install the CoGrid Overcooked environment:

    ```bash
    pip install cogrid
    ```

## Running the Example

From the repository root:

```bash
python -m examples.cogrid.overcooked_server_auth --experiment-id my_experiment
```

Then:

1. **Open two browser windows** to http://localhost:5703
2. **Read instructions** on the start screen
3. **Wait for partner** - Both players wait in the lobby until matched
4. **Play together** - Collaborate on the Cramped Room layout for 5 episodes
5. **Provide feedback** - Complete survey about your partner

**Controls:**

- **Arrow Keys**: Move chef up/down/left/right
- **W**: Pick up / drop objects
- **Q**: Toggle (interact with pots)

## File Structure

```text
cogrid/
├── overcooked_server_auth.py       # Main experiment file
├── scenes/
│   └── scenes.py                   # Shared scene definitions
├── environments/
│   └── cramped_room_environment_initialization_hh.py  # Environment setup
└── overcooked_utils.py             # Rendering and HUD functions
```

## Architecture

In server-authoritative mode, the server is the single source of truth. Both browsers are thin clients:

```text
Browser 1 (Thin client)       Server                   Browser 2 (Thin client)
───────────────────────      ──────                   ───────────────────────
Display game state      ←    Environment instance  →   Display game state
Capture input           →    Collect both actions  ←   Capture input
                             env.step(actions)
                             env.render()
                             Stream state to both
```

The server:

1. **Matches players** when two connect to the waitroom
2. **Creates the environment** using the `env_creator` function
3. **Runs the game loop** at the configured FPS (30)
4. **Collects actions** from both browsers each frame
5. **Steps the environment** with both actions simultaneously
6. **Renders and streams** the visual state to both browsers
7. **Saves data** at the end of each episode

## Experiment Flow

```python
from examples.cogrid.scenes import scenes as oc_scenes
from mug.scenes import stager, static_scene

stager = stager.Stager(
    scenes=[
        hh_start_scene,                 # Welcome and instructions
        server_auth_scene,              # Server-authoritative gameplay
        oc_scenes.multiplayer_feedback_scene,  # Partner survey
        oc_scenes.end_scene,            # Completion code
    ]
)
```

Each participant pair experiences:

1. **Start Scene** - Instructions and consent
2. **Gameplay** - 5 episodes of collaboration on the Cramped Room layout
3. **Feedback Survey** - Questions about partner effectiveness
4. **End Scene** - Completion code

## Scene Configuration

The server-authoritative scene differs from the P2P version in three key ways:

1. **`.multiplayer(mode="server_authoritative")`** instead of P2P mode
2. **`.environment(env_creator=..., env_config=...)`** since the server creates the environment
3. **No `.runtime()`** call since there is no Pyodide

```python
from mug.scenes import gym_scene
from mug.configurations import configuration_constants

HUMAN_HUMAN_POLICY_MAPPING = {
    0: configuration_constants.PolicyTypes.Human,
    1: configuration_constants.PolicyTypes.Human,
}

def _create_overcooked_env(**kwargs):
    """Lazy env_creator — imports cogrid only when the server creates the env."""
    from examples.cogrid.environments.cramped_room_environment_initialization_hh import (
        OvercookedEnv, overcooked_config,
    )
    return OvercookedEnv(config=overcooked_config, **kwargs)

server_auth_scene = (
    gym_scene.GymScene()
    .scene(scene_id="cramped_room_server_auth", experiment_config={})
    .policies(policy_mapping=HUMAN_HUMAN_POLICY_MAPPING)
    .environment(
        env_creator=_create_overcooked_env,
        env_config={"render_mode": "mug"},
    )
    .rendering(
        fps=30,
        hud_text_fn=overcooked_utils.hud_text_fn,
        game_width=overcooked_utils.TILE_SIZE * 5,
        game_height=overcooked_utils.TILE_SIZE * 4,
        background="#e6b453",
    )
    .gameplay(
        default_action=Noop,
        action_mapping=action_mapping,
        num_episodes=5,
        max_steps=1350,
        input_mode=configuration_constants.InputModes.SingleKeystroke,
    )
    .content(
        scene_header="Overcooked - Server Authoritative",
        scene_body="...",
        game_page_html_fn=overcooked_utils.overcooked_game_page_header_fn,
        in_game_scene_body="...",
    )
    .multiplayer(mode="server_authoritative")
)
```

### Key Configuration Details

#### `.environment()` -- Server-Side Environment Creation

In server-authoritative mode, the server creates the environment. The `env_creator` is a callable that returns a Gymnasium-compatible environment:

```python
.environment(
    env_creator=_create_overcooked_env,
    env_config={"render_mode": "mug"},
)
```

Using a lazy creator function (as shown above) avoids importing heavy dependencies at module load time, which is useful when the example is imported for inspection.

#### `.multiplayer(mode="server_authoritative")`

This single parameter switches the scene to server-authoritative mode:

```python
.multiplayer(mode="server_authoritative")
```

When `mode="server_authoritative"`:

- The environment runs on the server, not in Pyodide
- No `get_state()`/`set_state()` required (no rollback)
- No GGPO -- the server is the single source of truth
- Both browsers receive the same rendered state each frame
- Every input round-trips through the server

**No `.runtime()`** -- since there is no Pyodide, you do not call `.runtime()`. Dependencies are installed on the server.

### Experiment Configuration

```python
experiment_config = (
    experiment_config.ExperimentConfig()
    .experiment(stager=stager, experiment_id=args.experiment_id)
    .hosting(port=args.port, host="0.0.0.0")
    .static_files(directories=[
        "examples/cogrid/assets",
        "examples/shared/assets",
    ])
)

app.run(experiment_config)
```

#### Serving Assets

Because sprites and images live outside the MUG package (under `examples/cogrid/assets/`), the experiment config registers them with `.static_files()` so the server can serve them to the browser. Each directory is served at a URL that matches its filesystem path.

## Server-Side Multiplayer Flow

```text
Browser 1 (Human)           Server                  Browser 2 (Human)
─────────────────           ──────                 ───────────────────

1. Connect                                         1. Connect
2. Wait in lobby       ←→   Match players      ←→  2. Wait in lobby
3. Display state       ←    Create game
4. Send action         →    5. Collect actions  ←  4. Send action
                            6. Wait for both actions
                            7. env.step(actions)
                            8. env.render()
                            9. Save data
10. Display state      ←    Send to both       →   10. Display state
(Repeat 4-10)
```

### Synchronized Gameplay

During gameplay:

1. **Action Collection**: Server waits for actions from both players each frame
2. **Simultaneous Step**: Environment steps with both actions at once
3. **State Broadcasting**: Rendered state sent to both browsers
4. **Frame Synchronization**: Both players see identical game state

This ensures:

- No action is processed until both players have submitted
- Both players always see the same game state
- Fair gameplay with no timing advantages

### Latency Considerations

In server-authoritative mode, every input round-trips through the server. A player close to the server has lower latency than a player farther away. For experiments where equal responsiveness matters, you can add input delay:

```python
.multiplayer(
    mode="server_authoritative",
    input_delay=2,  # ~66ms at 30fps
)
```

This adds a fixed delay for all players, equalizing perceived latency regardless of network distance.

## Data Collection

Server-authoritative mode automatically logs:

- Each player's actions per frame
- Shared team reward (dishes delivered)
- Episode score and time
- Timestamped event logs
- Individual player metrics

Data is saved server-side at the end of each episode.

### Feedback Survey

The experiment includes a post-game survey asking about partner effectiveness, enjoyment, contribution, and whether the partner seemed human. See the source at `examples/cogrid/scenes/scenes.py` for the full survey configuration.

## Research Applications

This example is designed for research on:

**Human-Human Coordination**
:   Study how humans develop coordination strategies

**Communication and Theory of Mind**
:   Investigate implicit communication without chat

**Task Allocation**
:   Analyze how pairs divide labor spontaneously

**Environments with Complex Dependencies**
:   Run experiments with environments that can't run in Pyodide (compiled extensions, GPU inference)

## Comparison with Client-Side (P2P)

| Feature | Server-Authoritative - This Example | Client-Side (P2P) |
|---------|-------------------------------------|---------------------|
| **Environment runs** | On the server | In each browser (Pyodide) |
| **Perceived latency** | Higher (input round-trips server) | Low (local sim + GGPO) |
| **Server load** | Proportional to active games | Minimal (matchmaking only) |
| **Dependencies** | Any Python code | Pure Python only |
| **Requires get_state/set_state** | No | Yes |
| **Initial load time** | Instant | 30-90s (Pyodide startup) |
| **Single source of truth** | Yes (server) | No (eventual consistency via GGPO) |

For the client-side version of this example, see [Overcooked: Client-Side](overcooked-client-side.md).

## Next Steps

- **Client-side version**: [Overcooked: Client-Side](overcooked-client-side.md) for P2P multiplayer with GGPO
- **Human-AI version**: [Overcooked: Human-AI](overcooked-human-ai.md) for single-player with trained AI partners
- **Server mode details**: [Server Mode](../core-concepts/server-mode.md) for deployment, scaling, and TURN configuration
- **Multiplayer quickstart**: [Quick Start: Multiplayer](../getting-started/quick-start-multiplayer.md) for a simpler P2P example
