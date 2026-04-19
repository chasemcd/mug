# Overcooked: Human-Human (Client-Side)

Two human participants collaborate as chefs on the Cramped Room kitchen, with each browser running its own Pyodide copy of the environment and exchanging inputs peer-to-peer over WebRTC. GGPO rollback netcode keeps the two simulations synchronized, and FIFO matchmaking with a maximum P2P RTT filters out high-latency pairings.

**Source:** [`examples/cogrid/overcooked_human_human_multiplayer.py`](https://github.com/chasemcd/interactive-gym/blob/main/examples/cogrid/overcooked_human_human_multiplayer.py)

For a simpler P2P walkthrough with the full GGPO explanation, see [Quick Start: Multiplayer](../getting-started/quick-start-multiplayer.md). For the server-authoritative version, see [Overcooked: Server-Side](overcooked-multiplayer.md).

See [Examples](index.md) for install and run instructions. This example also requires:

```bash
pip install cogrid
```

## File Structure

```text
cogrid/
├── overcooked_human_human_multiplayer.py
├── scenes/scenes.py
├── environments/
│   └── cramped_room_environment_initialization_hh.py   # Pyodide env init
└── overcooked_utils.py
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
        oc_scenes.cramped_room_human_human
            .gameplay(num_episodes=20, max_steps=1350)
            .multiplayer(pause_on_partner_background=False),
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

cramped_room_human_human = (
    gym_scene.GymScene()
    .scene(scene_id="cramped_room_hh")
    .policies(policy_mapping=HUMAN_HUMAN_POLICY_MAPPING)
    .rendering(fps=30, game_width=..., game_height=..., background="#e6b453",
               hud_text_fn=overcooked_utils.hud_text_fn)
    .assets(assets_to_preload=overcooked_utils.overcooked_preload_assets_spec())
    .gameplay(default_action=Noop, action_mapping=action_mapping,
              num_episodes=5, max_steps=1350,
              input_mode=configuration_constants.InputModes.SingleKeystroke)
    .waitroom(timeout=300000, timeout_message="Sorry, we could not find enough players...")
    .runtime(
        environment_initialization_code_filepath=(
            "examples/cogrid/environments/cramped_room_environment_initialization_hh.py"
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

For production deployments behind firewalls, configure a TURN relay via environment variables; MUG reads them automatically when `.webrtc()` is called:

```bash
export TURN_USERNAME="your-openrelay-username"
export TURN_CREDENTIAL="your-openrelay-api-key"
```

Set `force_relay=True` to route all WebRTC traffic through TURN (useful for testing). See [Server Mode](../core-concepts/server-mode.md) for TURN setup.

## Client-Side vs Server-Authoritative

| | Client-Side (P2P) | Server-Authoritative |
|---|---|---|
| Environment runs | In each browser (Pyodide) | On the server |
| Perceived latency | Low (local sim + GGPO) | Higher (input round-trips server) |
| Server load | Minimal (matchmaking only) | Proportional to active games |
| Dependencies | Pure Python only | Any Python code |
| Requires `get_state`/`set_state` | Yes | No |
| Initial load time | 30-90s (Pyodide startup) | Instant |
