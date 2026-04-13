# Overcooked: Human-Human (Client-Side)

Two-player cooperative experiment where both participants play together in real time using peer-to-peer (P2P) synchronization. Each browser runs its own copy of the environment via Pyodide, with GGPO rollback netcode keeping game states synchronized over a WebRTC DataChannel.

This example complements the [Quick Start: Multiplayer](../getting-started/quick-start-multiplayer.md) guide by showing a more complex P2P multiplayer setup with sprite-based rendering, latency-aware matchmaking, and participant management features.

## Overview

Two human participants collaborate as chefs to prepare and deliver dishes. The environment runs client-side in each browser, and inputs are exchanged peer-to-peer. GGPO rollback netcode provides a responsive, low-latency experience even over the internet.

**What you'll learn:**

- P2P multiplayer with GGPO rollback netcode
- Latency-aware matchmaking with `FIFOMatchmaker`
- Entry screening (browser requirements, ping limits)
- WebRTC / TURN relay configuration
- Partner disconnect handling
- Sprite-based rendering with atlases in multiplayer

## Features Demonstrated

| Feature | Details |
|---------|---------|
| **Execution Mode** | Client-side (P2P with GGPO) |
| **Players** | 2 humans |
| **Sync** | GGPO rollback netcode over WebRTC DataChannel |
| **Environment** | CoGrid Overcooked (Cramped Room layout) |
| **Rendering** | Sprite atlases with tile-based rendering |
| **Input** | Arrow keys + action keys (W, Q) |
| **Matchmaking** | FIFO with P2P RTT filtering |
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
python -m examples.cogrid.overcooked_human_human_multiplayer --experiment-id my_experiment
```

Then:

1. **Open two browser windows** to http://localhost:5702
2. **Read instructions** on the start screen
3. **Complete tutorial** - Solo practice to learn controls
4. **Wait for partner** - Both players wait in the lobby until matched
5. **Play together** - Collaborate across 20 episodes on the Cramped Room layout
6. **Provide feedback** - Complete survey about your partner

**Controls:**

- **Arrow Keys**: Move chef up/down/left/right
- **W**: Pick up / drop objects
- **Q**: Toggle (interact with pots)

## File Structure

```text
cogrid/
├── overcooked_human_human_multiplayer.py  # Main experiment file
├── scenes/
│   └── scenes.py                          # Scene definitions
├── environments/
│   └── cramped_room_environment_initialization_hh.py  # Pyodide env init
└── overcooked_utils.py                    # Rendering functions
```

## Architecture

In P2P mode, each browser runs its own Pyodide instance with a copy of the environment. Players exchange inputs (not game state) over a WebRTC DataChannel, and GGPO rollback netcode keeps both copies synchronized:

```text
Browser 1 (Pyodide)                 Browser 2 (Pyodide)
───────────────────                 ───────────────────
Environment copy 1                  Environment copy 2
GGPO rollback engine                GGPO rollback engine
     │                                   │
     └───── WebRTC DataChannel ──────────┘
             (inputs, state hashes)

Server: matchmaking, waitroom, data export, TURN relay
```

The server's role is lightweight: it matches players, serves static assets, collects exported data, and optionally relays WebRTC connections through TURN. All environment computation happens in the browser.

## Experiment Flow

```python
from examples.cogrid.scenes import scenes as oc_scenes
from mug.scenes import stager, static_scene

stager = stager.Stager(
    scenes=[
        hh_start_scene,                 # Welcome and instructions
        oc_scenes.tutorial_gym_scene,   # Solo practice
        oc_scenes.cramped_room_human_human  # P2P multiplayer (20 episodes)
            .gameplay(num_episodes=20, max_steps=1350)
            .multiplayer(pause_on_partner_background=False),
        oc_scenes.multiplayer_feedback_scene,  # Partner survey
        oc_scenes.end_scene,            # Completion code
    ]
)
```

Each participant pair experiences:

1. **Start Scene** - Instructions and consent
2. **Tutorial** - Solo practice in a simple layout (runs in Pyodide)
3. **Multiplayer** - 20 episodes of collaboration on the Cramped Room layout
4. **Feedback Survey** - Questions about partner effectiveness and experience
5. **End Scene** - Completion code for crowdsourcing platforms

## Scene Configuration

The multiplayer scene is defined in `scenes/scenes.py` and customized in the experiment script. Here is the base scene definition:

```python
from mug.scenes import gym_scene
from mug.configurations import configuration_constants
from mug.server.matchmaker import FIFOMatchmaker

HUMAN_HUMAN_POLICY_MAPPING = {
    0: configuration_constants.PolicyTypes.Human,
    1: configuration_constants.PolicyTypes.Human,
}

cramped_room_human_human = (
    gym_scene.GymScene()
    .scene(scene_id="cramped_room_hh", experiment_config={})
    .policies(policy_mapping=HUMAN_HUMAN_POLICY_MAPPING)
    .rendering(
        fps=30,
        hud_text_fn=overcooked_utils.hud_text_fn,
        game_width=overcooked_utils.TILE_SIZE * 5,
        game_height=overcooked_utils.TILE_SIZE * 4,
        background="#e6b453",
    )
    .assets(
        assets_to_preload=overcooked_utils.overcooked_preload_assets_spec(),
    )
    .gameplay(
        default_action=Noop,
        action_mapping=action_mapping,
        num_episodes=5,
        max_steps=1350,
        input_mode=configuration_constants.InputModes.SingleKeystroke,
    )
    .content(
        scene_header="Overcooked - Multiplayer",
        scene_body="...",
        game_page_html_fn=overcooked_utils.overcooked_game_page_header_fn,
        in_game_scene_body="...",
    )
    .waitroom(
        timeout=300000,  # 5 minutes
        timeout_message="Sorry, we could not find enough players...",
    )
    .runtime(
        environment_initialization_code_filepath=(
            "examples/cogrid/environments/"
            "cramped_room_environment_initialization_hh.py"
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

Let's walk through the key multiplayer-specific configuration.

### `.runtime()` - Pyodide Environment

Because this is a P2P experiment, each browser runs the environment in Pyodide. The `.runtime()` call specifies:

- **`environment_initialization_code_filepath`**: A Python file that creates the environment. This file is loaded into Pyodide and executed in each browser.
- **`packages_to_install`**: Pip packages installed into Pyodide before running the environment code.

```python
.runtime(
    environment_initialization_code_filepath=(
        "examples/cogrid/environments/"
        "cramped_room_environment_initialization_hh.py"
    ),
    packages_to_install=["numpy", "cogrid==0.2.1", "opencv-python"],
)
```

The environment must implement `get_state()` and `set_state()` for GGPO rollback. See the [Quick Start: Multiplayer](../getting-started/quick-start-multiplayer.md) guide for details.

### `.multiplayer()` - GGPO and Matchmaking

```python
.multiplayer(
    input_delay=3,
    matchmaker=FIFOMatchmaker(max_p2p_rtt_ms=100),
    hide_lobby_count=True,
    partner_disconnect_message="Your partner disconnected...",
    partner_disconnect_show_completion_code=True,
)
```

`input_delay=3`
:   Delays all inputs by 3 frames (~100ms at 30 FPS). This gives remote inputs time to arrive before they're needed, reducing rollback frequency. A value of 3 is conservative and works well for typical internet connections.

`matchmaker=FIFOMatchmaker(max_p2p_rtt_ms=100)`
:   Pairs players in FIFO order, but rejects matches where the measured peer-to-peer round-trip time exceeds 100ms. This ensures paired players have low enough latency for a smooth GGPO experience. If a candidate is rejected, the matchmaker tries the next player in the queue.

`hide_lobby_count=True`
:   Hides the number of waiting participants from the lobby UI. Useful for crowdsourcing experiments where showing "1 of 2 players" might cause participants to leave prematurely.

`partner_disconnect_message`
:   Message shown if a partner disconnects mid-game. Combined with `partner_disconnect_show_completion_code=True`, this gives the remaining player a graceful exit with a completion code for compensation.

`pause_on_partner_background`
:   When `False` (set in the experiment script override), the game continues even if a partner's browser tab loses focus. When `True` (default), the game pauses until both tabs are in the foreground.

### `.waitroom()` - Player Pairing

```python
.waitroom(
    timeout=300000,  # 5 minutes
    timeout_message="Sorry, we could not find enough players...",
)
```

Players see a waiting screen until a partner connects. If no partner is found within 5 minutes, the participant sees the timeout message. You can also set `timeout_redirect_url` to redirect participants to an external URL (e.g., a crowdsourcing platform return page).

## Experiment Configuration

The experiment script configures hosting, entry screening, WebRTC, and static files:

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
    .static_files(directories=[
        "examples/cogrid/assets",
        "examples/shared/assets",
    ])
)
```

### Entry Screening

`.entry_screening()` filters participants before they enter the experiment:

- **`browser_requirements`**: Only allow specific browsers. Chrome and Safari have the best WebRTC support.
- **`browser_blocklist`**: Explicitly block browsers with known issues.
- **`max_ping`**: Reject participants with server ping above 200ms.

Participants who fail screening see a message explaining why they cannot participate.

### WebRTC / TURN Configuration

`.webrtc()` enables WebRTC peer-to-peer connections. For production deployments behind firewalls or restrictive NAT, configure a TURN relay server as fallback:

```bash
export TURN_USERNAME="your-openrelay-username"
export TURN_CREDENTIAL="your-openrelay-api-key"
```

MUG reads these environment variables automatically when `.webrtc()` is called. Set `force_relay=True` to route all traffic through TURN (useful for testing).

See [Server Mode](../core-concepts/server-mode.md) for full TURN setup instructions.

## How GGPO Keeps Games in Sync

1. **Both browsers run the same environment.** Each has a Pyodide instance with its own copy of the Overcooked environment, initialized with the same seed.

2. **Inputs are exchanged, not game state.** Players send key presses to each other over a WebRTC DataChannel.

3. **Input delay buffers latency.** With `input_delay=3`, inputs take effect 3 frames after being pressed, giving remote inputs time to arrive.

4. **Prediction when inputs are late.** If a remote input hasn't arrived, the engine uses the default action (Noop) and continues simulating.

5. **Rollback on misprediction.** When a late input arrives that differs from the prediction, the engine loads a state snapshot (via `get_state()`), replays with the correct inputs, and fast-forwards to the current frame.

6. **State hash verification.** Both clients periodically hash their state. If hashes diverge, one client resyncs from the other's full state.

For more details on GGPO, see the [Quick Start: Multiplayer](../getting-started/quick-start-multiplayer.md) guide.

## Comparison with Server-Authoritative

| Feature | Client-Side (P2P) - This Example | Server-Authoritative |
|---------|----------------------------------|----------------------|
| **Environment runs** | In each browser (Pyodide) | On the server |
| **Perceived latency** | Low (local sim + GGPO) | Higher (input round-trips server) |
| **Server load** | Minimal (matchmaking only) | Proportional to active games |
| **Dependencies** | Pure Python only | Any Python code |
| **Requires get_state/set_state** | Yes | No |
| **Initial load time** | 30-90s (Pyodide startup) | Instant |

For the server-authoritative version of this example, see [Overcooked: Server-Side](overcooked-multiplayer.md).

## Data Collection

In P2P mode, only the host player's browser exports data to avoid duplicates. MUG automatically tracks:

- Each player's actions per frame
- Shared team reward (dishes delivered)
- Episode score and time
- Timestamped event logs

### Feedback Survey

The experiment includes a post-game survey asking about partner effectiveness, enjoyment, contribution, and whether the partner seemed human:

```python
multiplayer_feedback_scene = (
    static_scene.ScalesAndTextBox(
        scale_questions=[
            "How effective was your partner as a teammate?",
            "How much did you enjoy playing with your partner?",
            "How much did your partner contribute to your team's success?",
            "How much did you contribute to your team's success?",
            "How likely is it that your partner is a human or a bot?",
        ],
        scale_labels=[
            [str(i + 1) for i in range(7)],
            # ...
        ],
        text_box_header="Please provide any additional feedback...",
        scale_size=7,
    )
    .scene(scene_id="multiplayer_feedback_scene", experiment_config={})
)
```

## Research Applications

This example is designed for research on:

**Human-Human Coordination**
:   Study how humans develop coordination strategies with real partners

**Real-Time Collaboration**
:   Investigate implicit communication and role division without explicit chat

**Network Effects on Gameplay**
:   Analyze how latency and connection quality affect collaborative performance

**Crowdsourced Experiments**
:   Run large-scale paired experiments on platforms like Prolific or MTurk with entry screening, timeout handling, and completion codes

## Next Steps

- **Multiplayer quickstart**: [Quick Start: Multiplayer](../getting-started/quick-start-multiplayer.md) for a simpler P2P example with full GGPO explanation
- **Server-authoritative version**: [Overcooked: Server-Side](overcooked-multiplayer.md) for when the environment can't run in Pyodide
- **Human-AI version**: [Overcooked: Human-AI](overcooked-human-ai.md) for single-player with trained AI partners
- **Server mode details**: [Server Mode](../core-concepts/server-mode.md) for deployment and scaling
