# Overcooked: Human-Human

<div align="center">
  <video src="../assets/images/overcooked_human_human.webm" autoplay loop muted playsinline width="600">
    Your browser does not support the video tag.
  </video>
</div>

Two human participants collaborate as chefs across the five classic Overcooked kitchens — Cramped Room, Asymmetric Advantages, Coordination Ring, Forced Coordination, and Counter Circuit. Each participant pair is randomly assigned one layout via `RandomizeOrder(keep_n=1)`. Each browser runs its own Pyodide copy of the environment and exchanges inputs peer-to-peer over WebRTC; GGPO rollback netcode keeps the two simulations synchronized, and FIFO matchmaking with a maximum P2P RTT filters out high-latency pairings.

**Source:** [`examples/cogrid/overcooked_human_human_multiplayer.py`](https://github.com/chasemcd/interactive-gym/blob/main/examples/cogrid/overcooked_human_human_multiplayer.py)

For a simpler P2P walkthrough with the full GGPO explanation, see [Quick Start: Multiplayer](../getting-started/quick-start-multiplayer.md). For a version where the environment runs on the server instead, see the [Running server-authoritative instead](#running-server-authoritative-instead) section at the bottom.

See [Examples](index.md) for install and run instructions. This example also requires the [CoGrid Overcooked environment](https://github.com/chasemcd/cogrid), which we install in the user's browser (install locally with `pip install cogrid==0.2.1` if you want to run the environment outside the experiment).

## File Structure

```text
cogrid/
├── overcooked_human_human_multiplayer.py
├── scenes/scenes.py                    # Builds one scene per layout + RandomizeOrder wrapper
├── environments/
│   └── overcooked_hh_template.py       # Pyodide env template (placeholders filled per layout)
└── overcooked_utils.py                 # HH_LAYOUTS + make_hh_env_init_code helpers
```

## Architecture

```text
Browser 1 (Pyodide)                 Browser 2 (Pyodide)
Environment copy 1                  Environment copy 2
GGPO rollback engine                GGPO rollback engine
     |                                   |
     +------- WebRTC DataChannel --------+
             (inputs, state hashes)

Server: matchmaking, waitroom, static assets, data export, optional TURN relay
```

The server only handles matchmaking, static assets, and data export. All environment computation happens in the browsers.

## Experiment Flow

```python
stager = stager.Stager(
    scenes=[
        hh_start_scene,
        oc_scenes.tutorial_gym_scene,
        oc_scenes.randomized_human_human_layouts,   # RandomizeOrder(keep_n=1) over 5 layouts
        oc_scenes.multiplayer_feedback_scene,
        oc_scenes.end_scene,
    ]
)
```

## Layout list and per-layout scenes

The five layouts — their CoGrid name, grid dimensions, and preview image — are listed in one place, `HH_LAYOUTS` in [`overcooked_utils.py`](https://github.com/chasemcd/interactive-gym/blob/main/examples/cogrid/overcooked_utils.py):

| Label | CoGrid layout | cols × rows |
|---|---|---|
| Cramped Room | `overcooked_cramped_room_v0` | 5 × 4 |
| Asymmetric Advantages | `overcooked_asymmetric_advantages_v0` | 9 × 5 |
| Coordination Ring | `overcooked_coordination_ring_v0` | 5 × 5 |
| Forced Coordination | `overcooked_forced_coordination_v0` | 5 × 4 |
| Counter Circuit | `overcooked_counter_circuit_v0` | 8 × 5 |

Each entry also carries a preview image path that's shown on the pre-game screen so participants see the kitchen they're about to play on.

`scenes.py` builds one `GymScene` per layout with `_build_human_human_scene(layout_name, cols, rows, label, preview_img)` and wraps them in `RandomizeOrder(keep_n=1)` so each participant pair plays exactly one randomly-selected kitchen:

```python
human_human_layout_scenes = [
    _build_human_human_scene(layout_name, cols, rows, label, preview_img)
    for layout_name, cols, rows, label, preview_img in overcooked_utils.HH_LAYOUTS
]

randomized_human_human_layouts = scene.RandomizeOrder(
    human_human_layout_scenes,
    keep_n=1,
)
```

## Per-layout scene template

Since each layout has different grid dimensions (and therefore different canvas size and CoGrid env id), `_build_human_human_scene` parametrizes those at build time. The rest of the configuration — policy mapping, matchmaker, GGPO settings, feedback copy — is the same for every layout.

```python
HUMAN_HUMAN_POLICY_MAPPING = {
    0: configuration_constants.PolicyTypes.Human,
    1: configuration_constants.PolicyTypes.Human,
}

def _build_human_human_scene(layout_name, cols, rows, label):
    return (
        gym_scene.GymScene()
        .scene(scene_id=f"hh_{layout_name}")
        .policies(policy_mapping=HUMAN_HUMAN_POLICY_MAPPING)
        .rendering(
            fps=30,
            game_width=overcooked_utils.TILE_SIZE * cols,
            game_height=overcooked_utils.TILE_SIZE * rows,
            background="#e6b453",
            hud_text_fn=overcooked_utils.hud_text_fn,
        )
        .assets(assets_to_preload=overcooked_utils.overcooked_preload_assets_spec())
        .gameplay(
            default_action=Noop, action_mapping=action_mapping,
            num_episodes=5, max_steps=1350,
            input_mode=configuration_constants.InputModes.SingleKeystroke,
        )
        .waitroom(timeout=300000, timeout_message="Sorry, we could not find enough players...")
        .runtime(
            environment_initialization_code=overcooked_utils.make_hh_env_init_code(
                layout_name, cols, rows
            ),
            packages_to_install=["numpy", "cogrid==0.2.1", "opencv-python"],
        )
        .multiplayer(
            input_delay=3,
            matchmaker=FIFOMatchmaker(max_p2p_rtt_ms=100),
            hide_lobby_count=True,
            partner_disconnect_message="Your partner disconnected...",
            partner_disconnect_show_completion_code=True,
        )
    )
```

## Environment template

`environments/overcooked_hh_template.py` is the Python file each browser executes in Pyodide. It subclasses `CoGridEnv` with a MUG `Surface` renderer and, at the top, declares three layout defaults that `make_hh_env_init_code()` rewrites per layout:

```python
# examples/cogrid/environments/overcooked_hh_template.py
LAYOUT_NAME = "overcooked_cramped_room_v0"
LAYOUT_COLS = 5
LAYOUT_ROWS = 4
# ... renderer + env class + registry.register(...) below ...
env = registry.make(ENV_ID, render_mode="mug")
```

`overcooked_utils.make_hh_env_init_code()` reads the file, replaces those three lines with the target layout's values, and returns the resulting code string — which is then passed to `.runtime(environment_initialization_code=...)` instead of a static `..._filepath`. The defaults make the template parse as-is (so the server-auth example can import `OvercookedEnv` and `overcooked_config` directly).

### `.multiplayer()`

- `input_delay=3` — delays all inputs by 3 frames (~100ms @ 30 FPS). Gives remote inputs time to arrive, reducing rollbacks.
- `matchmaker=FIFOMatchmaker(max_p2p_rtt_ms=100)` — FIFO pairing, rejecting matches whose measured peer-to-peer RTT exceeds 100ms.
- `hide_lobby_count=True` — hides "1 of 2" from the lobby UI, useful for crowdsourcing.
- `partner_disconnect_message` + `partner_disconnect_show_completion_code=True` — if a partner drops, the remaining player gets a graceful exit with a completion code.
- `pause_on_partner_background` — when `False` (set in the experiment script), the game continues when a partner's tab loses focus.

### `.waitroom()`

Players wait until paired. If not matched within `timeout` ms, they see `timeout_message` (or `timeout_redirect_url` if configured).

### `.runtime()`

Each browser runs the environment in Pyodide. `environment_initialization_code_filepath` points to a file that is executed in Pyodide; it must leave a module-level `env` and must implement `get_state()` / `set_state()` for rollback. `packages_to_install` are installed into Pyodide before running the file.

### `.multiplayer()`

- `input_delay=3` — delays all inputs by 3 frames (~100ms @ 30 FPS). Gives remote inputs time to arrive, reducing rollbacks.
- `matchmaker=FIFOMatchmaker(max_p2p_rtt_ms=100)` — FIFO pairing, rejecting matches whose measured peer-to-peer RTT exceeds 100ms.
- `hide_lobby_count=True` — hides "1 of 2" from the lobby UI, useful for crowdsourcing.
- `partner_disconnect_message` + `partner_disconnect_show_completion_code=True` — if a partner drops, the remaining player gets a graceful exit with a completion code.
- `pause_on_partner_background` — when `False` (set in the experiment script), the game continues when a partner's tab loses focus.

### `.waitroom()`

Players wait until paired. If not matched within `timeout` ms, they see `timeout_message` (or `timeout_redirect_url` if configured).

## Experiment Configuration

```python
experiment_config = (
    experiment_config.ExperimentConfig()
    .experiment(stager=stager, experiment_id=args.experiment_id)
    .hosting(port=args.port, host="0.0.0.0")
    .entry_screening(
        browser_requirements=["Chrome", "Safari"],
        browser_blocklist=["Firefox"],
        max_ping=200,
    )
    .webrtc(force_relay=False)
)
```

`.entry_screening()` rejects participants before the experiment loads — by browser (Chrome/Safari have the best WebRTC support) and by server ping.

For production deployments, also configure a TURN relay so participants behind restrictive NATs can connect. See [WebRTC / TURN Configuration](../getting-started/quick-start-multiplayer.md#webrtc-turn-configuration) for the options.

## Running server-authoritative instead

Use server-authoritative mode when the environment has compiled dependencies, needs GPU inference, or otherwise cannot run in Pyodide. Three changes to the scene above are enough to flip the mode:

1. **Drop `.runtime(...)`** — there is no Pyodide, so no env-init file to execute in the browser.
2. **Add `.environment(env_creator=..., env_config=...)`** — the server constructs the env itself. A lazy `env_creator` avoids importing heavy dependencies at module load time.
3. **Change `.multiplayer(mode="server_authoritative")`** — turns off GGPO / rollback / `get_state` / `set_state`; every input round-trips through the server and both browsers receive the same rendered state each frame.

```python
def _create_overcooked_env(**kwargs):
    """Lazy env_creator so cogrid is only imported when the server creates the env."""
    from examples.cogrid.environments.overcooked_hh_template import (
        OvercookedEnv, overcooked_config,
    )
    return OvercookedEnv(config=overcooked_config, **kwargs)


server_auth_scene = (
    gym_scene.GymScene()
    .scene(scene_id="cramped_room_server_auth")
    .policies(policy_mapping=HUMAN_HUMAN_POLICY_MAPPING)
    .environment(env_creator=_create_overcooked_env, env_config={"render_mode": "mug"})
    .rendering(fps=30, ...)
    .gameplay(default_action=Noop, action_mapping=action_mapping, ...)
    .multiplayer(mode="server_authoritative")
)
```

To equalize perceived latency across players on different networks, add a fixed `input_delay`:

```python
.multiplayer(mode="server_authoritative", input_delay=2)  # ~66ms @ 30 FPS
```

See [`examples/cogrid/overcooked_server_auth.py`](https://github.com/chasemcd/interactive-gym/blob/main/examples/cogrid/overcooked_server_auth.py) for the full working example.
