Quick Start: Multiplayer
========================

Build a two-player Slime Volleyball experiment where participants play against each other in real time. The environment runs in each participant's browser using Pyodide, with peer-to-peer synchronization via WebRTC and GGPO rollback netcode.

If you haven't already, read the :doc:`quick_start` guide first to understand the basics of MUG experiments.

Prerequisites
-------------

Install MUG with server dependencies:

.. code-block:: bash

    pip install multi-user-gymnasium[server]

You'll also need **two browser windows** to test locally (one per player).

Architecture Overview
---------------------

MUG supports two multiplayer architectures:

**Peer-to-Peer (P2P)** — the default

Each player's browser runs its own copy of the environment via Pyodide. Players exchange inputs over a WebRTC DataChannel, and GGPO rollback netcode keeps the game states synchronized. The server only handles matchmaking and data collection.

.. code-block:: text

    Player 1 Browser                     Player 2 Browser
    ────────────────                     ────────────────
    Pyodide + Environment                Pyodide + Environment
         │                                    │
         └──── WebRTC DataChannel ────────────┘
                  (inputs, state hashes)

    Server: matchmaking, waitroom, data export

**Server-Authoritative** — for environments that can't run in Pyodide

The server runs the environment and streams render state to thin browser clients. Use this when your environment has compiled dependencies or requires GPU.

.. code-block:: text

    Player 1 Browser         Server              Player 2 Browser
    ────────────────        ──────              ────────────────
    Thin client        ←→  Environment  ←→     Thin client
    (display + input)      (step, render)      (display + input)

This guide focuses on P2P mode. See :doc:`core_concepts/server_mode` for server-authoritative setup.

Step 1: Create the Environment
------------------------------

For P2P multiplayer, environments must implement two additional methods beyond the standard Gymnasium API: ``get_state()`` and ``set_state()``. These enable GGPO rollback — when a late input arrives, the engine rolls back to a snapshot, replays with the correct inputs, and fast-forwards to the current frame.

Create ``slimevb_env.py``:

.. code-block:: python

    from __future__ import annotations
    import math
    import numpy as np
    import slime_volleyball.slimevolley_env as slimevolley_env
    from slime_volleyball.core import constants
    from mug.rendering import Surface

    def to_x(x):
        return x / constants.REF_W + 0.5

    def to_y(y):
        return 1 - y / constants.REF_W

    class SlimeVBEnvIG(slimevolley_env.SlimeVolleyEnv):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.surface = Surface(width=600, height=250)

        def reset(self, *args, **kwargs):
            obs, info = super().reset(*args, **kwargs)
            self.surface.reset()
            # Flatten nested obs for ONNX compatibility
            if isinstance(obs, dict):
                obs = {
                    k: v["obs"] if isinstance(v, dict) and "obs" in v else v
                    for k, v in obs.items()
                }
            return obs, info

        def step(self, actions):
            obs, rewards, terminateds, truncateds, infos = super().step(actions)
            if isinstance(obs, dict):
                obs = {
                    k: v["obs"] if isinstance(v, dict) and "obs" in v else v
                    for k, v in obs.items()
                }
            return obs, rewards, terminateds, truncateds, infos

        def render(self):
            # ... Surface draw calls ...
            return self.surface.commit().to_dict()

        def get_state(self) -> dict:
            """Serialize full environment state for GGPO snapshots."""
            s = self._env_state
            return {
                "t": self.t,
                "ball_pos_x": float(s.ball_pos[0]),
                "ball_pos_y": float(s.ball_pos[1]),
                # ... all dynamic state fields ...
            }

        def set_state(self, state: dict) -> None:
            """Restore environment from a state dict (called during rollback)."""
            import dataclasses
            self.t = state["t"]
            self._env_state = dataclasses.replace(
                self._env_state,
                ball_pos=np.array([state["ball_pos_x"], state["ball_pos_y"]], dtype=np.float32),
                # ... restore all fields ...
            )

    env = SlimeVBEnvIG(config={"human_inputs": True, "seed": 42}, render_mode="mug")

**Key points:**

- ``get_state()`` must return a JSON-serializable dict capturing ALL mutable state
- ``set_state(state)`` must restore the environment to the exact state described by the dict
- After ``set_state(get_state())``, the environment must behave identically to before
- These methods are called frequently (snapshots every 5 frames by default), so keep them fast

See the full implementation at ``examples/slime_volleyball/slimevb_env.py``.

Step 2: Create the Experiment Script
-------------------------------------

The key differences from a single-player experiment are:

1. More than one human policy in the policy mapping
2. ``.multiplayer()`` configuration for P2P sync
3. ``.waitroom()`` so players wait for a partner
4. ``.runtime()`` with Pyodide and the environment's pip package

Create ``slimevb_human_human.py``:

.. code-block:: python

    from __future__ import annotations
    import eventlet
    eventlet.monkey_patch()

    from mug.configurations import configuration_constants, experiment_config
    from mug.scenes import gym_scene, stager, static_scene
    from mug.server import app

    # Both players are human
    POLICY_MAPPING = {
        "agent_left": configuration_constants.PolicyTypes.Human,
        "agent_right": configuration_constants.PolicyTypes.Human,
    }

    # Action constants
    NOOP = 0
    LEFT = 1
    UPLEFT = 2
    UP = 3
    UPRIGHT = 4
    RIGHT = 5

    # Keyboard mapping — both players share the same keys
    # (each player only controls their own agent)
    ACTION_MAPPING = {
        "ArrowLeft": LEFT,
        ("ArrowLeft", "ArrowUp"): UPLEFT,
        "ArrowUp": UP,
        ("ArrowRight", "ArrowUp"): UPRIGHT,
        "ArrowRight": RIGHT,
    }

    start_scene = (
        static_scene.StartScene()
        .scene(scene_id="slimevb_start_scene")
        .display(
            scene_header="Welcome",
            scene_body="Welcome to Slime Volleyball! You'll be paired with another player.",
        )
    )

    slime_scene = (
        gym_scene.GymScene()
        .scene(scene_id="slime_gym_scene")
        .policies(policy_mapping=POLICY_MAPPING, frame_skip=1)
        .rendering(
            fps=30,
            game_width=600,
            game_height=250,
            rollback_smoothing_duration=300,
        )
        .gameplay(
            default_action=NOOP,
            action_mapping=ACTION_MAPPING,
            num_episodes=5,
            max_steps=3000,
            input_mode=configuration_constants.InputModes.PressedKeys,
            action_population_method=configuration_constants.ActionSettings.PreviousSubmittedAction,
        )
        .content(
            scene_header="Slime Volleyball",
            scene_body="<center><p>Press start when ready.</p></center>",
            in_game_scene_body="<center><p>Use arrow keys to control your slime!</p></center>",
        )
        .waitroom(timeout=120000)
        .runtime(
            run_through_pyodide=True,
            environment_initialization_code_filepath="slimevb_env.py",
            packages_to_install=["slimevb==0.1.1"],
        )
        .multiplayer(
            multiplayer=True,
            input_delay=2,
        )
    )

    end_scene = (
        static_scene.EndScene()
        .scene(scene_id="slimevb_end_scene")
        .display(
            scene_header="Thanks!",
            scene_body="Thanks for playing!",
        )
    )

    experiment_stager = stager.Stager(
        scenes=[start_scene, slime_scene, end_scene]
    )

    if __name__ == "__main__":
        config = (
            experiment_config.ExperimentConfig()
            .experiment(stager=experiment_stager, experiment_id="slimevb_multiplayer")
            .hosting(port=8000, host="0.0.0.0")
            .static_files(directories=["assets"])
        )
        app.run(config)

Let's walk through the multiplayer-specific configuration.

Multiplayer Configuration
-------------------------

``.multiplayer()``
^^^^^^^^^^^^^^^^^^

This is the core configuration for P2P games:

.. code-block:: python

    .multiplayer(
        multiplayer=True,   # Enable P2P Pyodide coordination
        input_delay=2,      # GGPO input delay in frames
    )

``multiplayer=True``
    Enables the P2P multiplayer system. Both clients run Pyodide, exchange inputs via WebRTC, and use GGPO to stay synchronized.

``input_delay``
    Number of frames to delay all inputs (both local and remote). This serves two purposes in P2P mode:

    1. **Reduces rollbacks** — by delaying when inputs take effect, remote inputs have more time to arrive before they're needed, so the engine predicts less and rolls back less.
    2. **Equalizes perceived latency** — both players experience the same fixed delay, regardless of their individual network conditions. Without input delay, the local player's actions feel instant while the remote player's are visibly late, creating an asymmetric experience.

    Recommended values:

    - **0**: No delay. Maximum responsiveness, frequent rollbacks. Only for LAN.
    - **2**: Good balance for most games. ~66ms delay at 30fps.
    - **3-4**: Conservative. Better for high-latency connections.

``snapshot_interval``
    How often to save a state snapshot (default: 5 frames). Lower values mean faster rollback recovery but more memory. You rarely need to change this.

``input_confirmation_timeout_ms``
    Timeout for partner input confirmation at episode boundaries (default: 500ms). Ensures both players agree on the final frame before exporting data.

``.waitroom()``
^^^^^^^^^^^^^^^

In multiplayer, players need to be paired before the game starts:

.. code-block:: python

    .waitroom(timeout=120000)  # 2-minute timeout

Players see a waiting screen until a partner connects. If the timeout expires, they can be redirected:

.. code-block:: python

    .waitroom(
        timeout=120000,
        timeout_redirect_url="https://example.com/no-partner",
        timeout_message="Sorry, no partner was found.",
    )

By default, the waitroom uses a FIFO matchmaker that pairs players in arrival order. MUG includes alternative matchmakers — ``LatencyFIFOMatchmaker`` (filters by estimated P2P latency) and ``GroupReunionMatchmaker`` (re-pairs previous partners) — and you can implement your own by subclassing ``Matchmaker``:

.. code-block:: python

    from mug.server.matchmaker import LatencyFIFOMatchmaker

    .multiplayer(
        multiplayer=True,
        matchmaker=LatencyFIFOMatchmaker(max_rtt_ms=150),
    )

``.rendering()`` — Rollback Smoothing
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

When a rollback correction moves objects to new positions, you can smooth the transition instead of snapping:

.. code-block:: python

    .rendering(
        fps=30,
        game_width=600,
        game_height=250,
        rollback_smoothing_duration=300,  # 300ms tween after rollback
    )

This applies a tween animation to objects that changed position during a rollback, hiding the visual "jank" from state corrections. Set to ``None`` to disable.

``.gameplay()`` — Action Population
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

In multiplayer, inputs can arrive late. The ``action_population_method`` controls what happens when an action is missing:

.. code-block:: python

    .gameplay(
        action_population_method=configuration_constants.ActionSettings.PreviousSubmittedAction,
    )

- ``PreviousSubmittedAction``: Repeat the player's last known action. Good for continuous-movement games like Slime Volleyball.
- ``DefaultAction``: Use the ``default_action`` value. Good for turn-based or discrete games.

GGPO Rollback Netcode
---------------------

MUG's P2P multiplayer uses GGPO-style rollback netcode, the same approach used by fighting games. Here's how it works:

1. **Both players run the same environment locally.** Each browser has its own Pyodide instance with a copy of the environment.

2. **Inputs are exchanged, not game state.** Players send their button presses to each other over a WebRTC DataChannel (unordered, unreliable — like UDP).

3. **Input delay buffers against latency.** With ``input_delay=2``, the game waits 2 frames before using any input, giving remote inputs time to arrive.

4. **Prediction when inputs are late.** If a remote input hasn't arrived yet, the engine predicts using ``action_population_method`` and continues simulating.

5. **Rollback on misprediction.** When a late input arrives that differs from the prediction, the engine:

   a. Loads the nearest state snapshot (saved every ``snapshot_interval`` frames via ``get_state()``)
   b. Replays all frames from the snapshot to the current frame using the correct inputs
   c. Applies rollback smoothing to hide visual corrections

6. **State hash verification.** Both clients periodically hash their game state and compare. If hashes diverge, one client corrects by loading the other's state.

This gives players a responsive, low-latency experience even over the internet, at the cost of occasional visual corrections when predictions are wrong.

Server-Authoritative Mode
-------------------------

If your environment can't run in Pyodide (compiled dependencies, GPU requirements), use server-authoritative mode instead:

.. code-block:: python

    slime_scene = (
        gym_scene.GymScene()
        .scene(scene_id="slime_gym_scene")
        .policies(policy_mapping=POLICY_MAPPING)
        .rendering(fps=30, game_width=600, game_height=250)
        .gameplay(
            default_action=NOOP,
            action_mapping=ACTION_MAPPING,
            num_episodes=5,
            max_steps=3000,
        )
        .multiplayer(
            mode="server_authoritative",
            input_delay=2,
        )
    )

Key differences from P2P:

- **No ``.runtime()``** call needed — the environment runs on the server, not in Pyodide
- **No ``get_state()``/``set_state()``** required — there's only one environment instance
- **No GGPO** — the server is the single source of truth
- **Higher latency** — every input round-trips through the server
- **No ``packages_to_install``** — dependencies are installed on the server

Use ``mode="server_authoritative"`` when you need compiled libraries, GPU inference, or centralized validation.

**Mitigating latency with input delay**

In server-authoritative mode, all inputs round-trip through the server, which introduces latency. A player close to the server will have a faster response time than a player farther away, creating an uneven experience. Setting ``input_delay`` alleviates this: the client queues each keypress and delays sending it by N render frames. This adds a small fixed delay for all players, but equalizes the experience — both players feel the same responsiveness regardless of their individual network distance to the server. An ``input_delay`` of 2-3 frames (66-100ms at 30fps) is usually enough to smooth out typical RTT differences.

Step 3: Run the Experiment
--------------------------

Start the server:

.. code-block:: bash

    python slimevb_human_human.py

Open **two browser windows** to ``http://localhost:8000``:

1. **Window 1**: First player connects, enters the waitroom
2. **Window 2**: Second player connects, both are paired
3. **Both click Start**: Pyodide loads, WebRTC connects, game begins
4. **Play**: Both players use arrow keys to control their slime

WebRTC / TURN Configuration
----------------------------

P2P connections work directly on local networks and most home connections. For production deployments where participants may be behind corporate firewalls or restrictive NAT, configure a TURN relay server as fallback:

.. code-block:: python

    config = (
        experiment_config.ExperimentConfig()
        .experiment(stager=experiment_stager, experiment_id="slimevb_multiplayer")
        .hosting(port=8000, host="0.0.0.0")
        .webrtc()  # Loads TURN_USERNAME and TURN_CREDENTIAL from environment
    )

Set credentials via environment variables:

.. code-block:: bash

    export TURN_USERNAME="your-openrelay-username"
    export TURN_CREDENTIAL="your-openrelay-api-key"

See :doc:`core_concepts/server_mode` for full TURN setup instructions.

To force all traffic through the relay (useful for testing):

.. code-block:: python

    .webrtc(force_relay=True)

Troubleshooting
---------------

**Players stuck in waitroom**

- Both players must be on the same experiment URL
- Check that the server is running and accessible from both browsers
- For remote testing, ensure the server port is open

**"WebRTC connection failed"**

- Most common on restrictive networks (corporate firewalls)
- Configure TURN relay (see above)
- Check browser console for ICE connection errors

**Game desyncs (different state on each screen)**

- Ensure ``get_state()`` captures ALL mutable state
- Ensure ``set_state()`` restores state perfectly: ``set_state(get_state())`` must be a no-op
- Check that the environment is fully deterministic given the same inputs and state

**High rollback frequency**

- Increase ``input_delay`` (e.g., 3 or 4)
- Check network quality between participants
- Consider server-authoritative mode for high-latency scenarios

**Visual jank after rollbacks**

- Increase ``rollback_smoothing_duration`` (e.g., 300-500ms)
- Higher ``input_delay`` reduces rollback frequency

Next Steps
----------

- **Full slime volleyball example**: See ``examples/slime_volleyball/`` for the complete implementation including rendering, human-AI, and human-human configurations
- **State sync API**: Read the full :doc:`../multiplayer_state_sync_api` documentation
- **Server mode details**: :doc:`core_concepts/server_mode` covers server-authoritative deployment, TURN setup, and scaling
- **Overcooked multiplayer**: ``examples/cogrid/`` demonstrates a more complex multiplayer environment with sprites and atlas rendering
