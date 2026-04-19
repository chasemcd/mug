# Overcooked: Human-Human (Server-Side)

Two human participants collaborate as chefs on the Cramped Room kitchen, with the environment running on the server and both browsers acting as thin clients that capture input and display rendered frames. Use this mode when the environment has compiled dependencies, needs GPU inference, or cannot run in Pyodide.

**Source:** [`examples/cogrid/overcooked_server_auth.py`](https://github.com/chasemcd/interactive-gym/blob/main/examples/cogrid/overcooked_server_auth.py)

For the client-side (P2P/GGPO) version, see [Overcooked: Client-Side](overcooked-client-side.md).

See [Examples](index.md) for install and run instructions. This example also requires:

```bash
pip install cogrid
```

## File Structure

```text
cogrid/
├── overcooked_server_auth.py
├── scenes/scenes.py
├── environments/
│   └── cramped_room_environment_initialization_hh.py   # env setup
└── overcooked_utils.py
```

## Architecture

```text
Browser 1 (thin client)     Server                        Browser 2 (thin client)
Display state           <-  Environment instance       ->  Display state
Capture input           ->  Collect both actions       <-  Capture input
                            env.step(actions)
                            env.render()
                            Stream state to both
```

Each frame the server waits for actions from both browsers, steps the environment once with both actions, renders, and broadcasts the result. Both players always see identical state.

## Experiment Flow

```python
stager = stager.Stager(
    scenes=[
        hh_start_scene,
        server_auth_scene,
        oc_scenes.multiplayer_feedback_scene,
        oc_scenes.end_scene,
    ]
)
```

## Scene Configuration

```python
HUMAN_HUMAN_POLICY_MAPPING = {
    0: configuration_constants.PolicyTypes.Human,
    1: configuration_constants.PolicyTypes.Human,
}

def _create_overcooked_env(**kwargs):
    """Lazy env_creator so cogrid is only imported when the server creates the env."""
    from examples.cogrid.environments.cramped_room_environment_initialization_hh import (
        OvercookedEnv, overcooked_config,
    )
    return OvercookedEnv(config=overcooked_config, **kwargs)

server_auth_scene = (
    gym_scene.GymScene()
    .scene(scene_id="cramped_room_server_auth")
    .policies(policy_mapping=HUMAN_HUMAN_POLICY_MAPPING)
    .environment(env_creator=_create_overcooked_env, env_config={"render_mode": "mug"})
    .rendering(fps=30, game_width=..., game_height=..., background="#e6b453",
               hud_text_fn=overcooked_utils.hud_text_fn)
    .gameplay(default_action=Noop, action_mapping=action_mapping,
              num_episodes=5, max_steps=1350,
              input_mode=configuration_constants.InputModes.SingleKeystroke)
    .multiplayer(mode="server_authoritative")
)
```

### `.environment()`

The server creates the env via `env_creator`. A lazy creator function avoids importing heavy dependencies at module load time. `env_config` is passed to the constructor.

### `.multiplayer(mode="server_authoritative")`

Switches the scene off P2P/Pyodide. No rollback, no `get_state`/`set_state`, no GGPO. Every input round-trips through the server.

To equalize perceived latency across players on different networks, add a fixed `input_delay`:

```python
.multiplayer(mode="server_authoritative", input_delay=2)  # ~66ms @ 30 FPS
```

## Server-Side vs Client-Side (P2P)

| | Server-Authoritative | Client-Side (P2P) |
|---|---|---|
| Environment runs | On the server | In each browser (Pyodide) |
| Perceived latency | Higher (round-trip per input) | Low (local sim + GGPO) |
| Server load | Proportional to active games | Minimal (matchmaking only) |
| Dependencies | Any Python code | Pure Python only |
| Requires `get_state`/`set_state` | No | Yes |
| Initial load time | Instant | 30-90s (Pyodide startup) |
| Single source of truth | Yes (server) | No (eventual consistency) |
