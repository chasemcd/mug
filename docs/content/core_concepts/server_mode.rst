Server Mode
===========

Server mode runs your environment on a server, with state streamed to participants' browsers in real-time. This mode is required for multi-player experiments and provides more flexibility than Pyodide mode.

When to Use Server Mode
------------------------

✅ **Use Server mode when:**

- Multi-player experiments (multiple humans together)
- Environment has compiled dependencies (C/C++ libraries)
- Using complex AI policies with GPU inference
- Need centralized data validation
- Want to ensure consistent performance across all participants
- Environment is computationally intensive

❌ **Don't need Server mode when:**

- Single-player experiment with pure Python environment
- Want to minimize server costs/load
- Want zero network latency
- Participants have reliable internet for Pyodide download

**Note:** Server mode is automatically used when your experiment requires it (e.g., multiple human players).

How Server Mode Works
----------------------

Architecture
^^^^^^^^^^^^

.. code-block:: text

    Participant 1 Browser          Server                  Participant 2 Browser
    ─────────────────────         ──────                  ─────────────────────

    1. Connect via WebSocket   →   Game Manager
    2. Assigned to Game 1      ←   ├── Game 1 (2 players)
                                   │   ├── Environment
    Display game state         ←   │   ├── AI Policies
                                   │   └── Game Loop
    Send action "left"         →   │
                                   │   Step environment
    Display updated state      ←   │   Render & send state
                                   │
    Send action "jump"         →   └── (repeat)

All computation happens on the server. Browsers only display and capture input.

Game Loop
^^^^^^^^^

The server runs a continuous loop:

.. code-block:: python

    # Simplified game loop
    while not done:
        # 1. Collect actions from all players
        actions = {
            "player_0": get_action_from_browser(player_0),
            "player_1": ai_policy.predict(obs),
        }

        # 2. Step environment
        obs, rewards, dones, infos = env.step(actions)

        # 3. Render
        visual_objects = env.render()

        # 4. Send to all connected clients
        socketio.emit('render_state', {
            'objects': visual_objects,
            'observations': obs,
            'rewards': rewards,
        })

        # 5. Wait for next frame
        time.sleep(1.0 / fps)

The loop runs at the configured FPS (e.g., 30 FPS = 33ms between frames).

Enabling Server Mode
--------------------

Automatic Activation
^^^^^^^^^^^^^^^^^^^^

Server mode is enabled automatically when you have multiple human players:

.. code-block:: python

    from interactive_gym.scenes import gym_scene
    from interactive_gym.configurations import configuration_constants

    game_scene = (
        gym_scene.GymScene()
        .scene(scene_id="multiplayer_game")
        .policies(
            policy_mapping={
                "player_0": configuration_constants.PolicyTypes.Human,
                "player_1": configuration_constants.PolicyTypes.Human,  # Two humans!
            }
        )
        # Server mode automatically used
    )

Explicit Configuration
^^^^^^^^^^^^^^^^^^^^^^

For single-player with server-side execution:

.. code-block:: python

    game_scene = (
        gym_scene.GymScene()
        .scene(scene_id="my_game")
        .environment(
            env_creator=make_my_env,
            env_config={"difficulty": "hard"},
        )
        .policies(
            policy_mapping={"player_0": configuration_constants.PolicyTypes.Human}
        )
        # No .runtime() call = server mode by default
    )

With AI Policies
^^^^^^^^^^^^^^^^

Human players with AI opponents:

.. code-block:: python

    def load_policy(policy_name):
        """Load a trained policy"""
        model = torch.load(f"policies/{policy_name}.pt")
        return model

    def run_inference(policy, observation):
        """Run inference with the policy"""
        with torch.no_grad():
            action = policy(observation)
        return action.item()

    game_scene = (
        gym_scene.GymScene()
        .scene(scene_id="human_vs_ai")
        .environment(env_creator=make_env)
        .policies(
            policy_mapping={
                "player_0": configuration_constants.PolicyTypes.Human,
                "player_1": "trained_agent",  # AI policy name
            },
            load_policy_fn=load_policy,
            policy_inference_fn=run_inference,
        )
    )

Game Manager
------------

The GameManager coordinates games for a scene:

Responsibilities
^^^^^^^^^^^^^^^^

1. **Create games** when participants join
2. **Assign participants** to available games
3. **Run game loops** for each active game
4. **Manage waiting rooms** when games are full
5. **Clean up** completed games
6. **Save data** from each game

Concurrent Games
^^^^^^^^^^^^^^^^

Multiple games can run simultaneously:

.. code-block:: python

    .hosting(
        max_concurrent_games=5,  # Up to 5 games at once
    )

**Example with 10 participants in a 2-player game:**

- Game 1: Participant 1 & 2
- Game 2: Participant 3 & 4
- Game 3: Participant 5 & 6
- Game 4: Participant 7 & 8
- Game 5: Participant 9 & 10

Each game runs independently with its own environment instance.

Waiting Room
^^^^^^^^^^^^

When games are full, participants wait:

.. code-block:: python

    .waitroom(
        timeout_redirect_url="https://example.com/sorry",
    )

Participants see a waiting screen until:

- A game slot opens up
- They create a new game
- Timeout expires (if set)

Multi-Player Configuration
---------------------------

Two-Player Game
^^^^^^^^^^^^^^^

.. code-block:: python

    game_scene = (
        gym_scene.GymScene()
        .scene(scene_id="two_player")
        .environment(env_creator=make_two_player_env)
        .policies(
            policy_mapping={
                "player_0": configuration_constants.PolicyTypes.Human,
                "player_1": configuration_constants.PolicyTypes.Human,
            }
        )
        .gameplay(
            action_mapping={
                "w": 0,  # Player 0 controls
                "a": 1,
                "s": 2,
                "d": 3,
                "ArrowUp": 0,  # Player 1 controls
                "ArrowLeft": 1,
                "ArrowDown": 2,
                "ArrowRight": 3,
            }
        )
    )

**Action routing:**

The server automatically routes actions to the correct player based on their socket connection.

Many-Player Game
^^^^^^^^^^^^^^^^

.. code-block:: python

    N_PLAYERS = 4

    policy_mapping = {
        f"player_{i}": configuration_constants.PolicyTypes.Human
        for i in range(N_PLAYERS)
    }

    game_scene = (
        gym_scene.GymScene()
        .scene(scene_id="four_player")
        .environment(env_creator=make_multiplayer_env)
        .policies(policy_mapping=policy_mapping)
    )

Mixed Human-AI
^^^^^^^^^^^^^^

.. code-block:: python

    game_scene = (
        gym_scene.GymScene()
        .scene(scene_id="coop_with_ai")
        .environment(env_creator=make_coop_env)
        .policies(
            policy_mapping={
                "player_0": configuration_constants.PolicyTypes.Human,
                "player_1": configuration_constants.PolicyTypes.Human,
                "npc_1": "helpful_agent",
                "npc_2": "helpful_agent",
            },
            load_policy_fn=load_policy,
            policy_inference_fn=run_inference,
        )
    )

Two humans cooperate with two AI teammates.

Action Handling
---------------

Action Mapping
^^^^^^^^^^^^^^

Map keyboard keys to environment actions:

.. code-block:: python

    .gameplay(
        action_mapping={
            "w": 0,          # Move up
            "a": 1,          # Move left
            "s": 2,          # Move down
            "d": 3,          # Move right
            " ": 4,          # Space = jump
        },
        default_action=0,    # Action when no key pressed
    )

Input Modes
^^^^^^^^^^^

**PressedKeys** (default):

.. code-block:: python

    .gameplay(
        input_mode=configuration_constants.InputModes.PressedKeys,
    )

Actions sent continuously while key is held.

**KeyDown:**

.. code-block:: python

    .gameplay(
        input_mode=configuration_constants.InputModes.KeyDown,
    )

Action sent once when key is first pressed.

**KeyUp:**

.. code-block:: python

    .gameplay(
        input_mode=configuration_constants.InputModes.KeyUp,
    )

Action sent when key is released.

Action Population
^^^^^^^^^^^^^^^^^

When an action is missing (e.g., network delay):

.. code-block:: python

    .gameplay(
        default_action=0,
        action_population_method=configuration_constants.ActionSettings.DefaultAction,
    )

Uses ``default_action`` to fill missing actions.

Performance Considerations
--------------------------

Server Resources
^^^^^^^^^^^^^^^^

Each game consumes:

- CPU: Environment computation + rendering
- Memory: Environment state + history
- Network: State streaming to participants

**Scaling:**

- Small environments: 50-100 concurrent games per server
- Complex environments: 10-20 concurrent games per server
- GPU inference: Depends on batch size and model

Network Latency
^^^^^^^^^^^^^^^

Participants experience latency equal to:

.. code-block:: text

    Latency = Network RTT + Server Computation Time

**Typical values:**

- Local network: 5-20 ms
- Same region: 20-50 ms
- Cross-region: 50-200 ms
- International: 100-500+ ms

**Mitigation:**

1. Deploy servers close to participants
2. Optimize environment step time
3. Reduce FPS for slower games
4. Use prediction/interpolation on client

Frame Rate
^^^^^^^^^^

Higher FPS = smoother but more load:

.. code-block:: python

    .rendering(
        fps=60,  # Smooth, high load
    )

    .rendering(
        fps=30,  # Balanced (recommended)
    )

    .rendering(
        fps=10,  # Low load, choppier
    )

**Recommendation:** Start with 30 FPS, adjust based on testing.

Data Collection
---------------

Automatic Logging
^^^^^^^^^^^^^^^^^

Server mode automatically logs:

- Observations
- Actions (per player)
- Rewards (per player)
- Episode metadata
- Timestamps

Saved to: ``data/{scene_id}/{subject_id}.csv``

Real-Time Validation
^^^^^^^^^^^^^^^^^^^^

Server can validate actions before stepping:

.. code-block:: python

    class ValidatedEnv(gym.Env):

        def step(self, actions):
            # Validate actions
            for player_id, action in actions.items():
                if not self.is_valid_action(action):
                    actions[player_id] = self.default_action

            # Step with validated actions
            return super().step(actions)

Callbacks
^^^^^^^^^

Custom data collection via callbacks:

.. code-block:: python

    def my_callback(game_instance, data):
        """Called at each step"""
        # Log custom metrics
        custom_metric = compute_metric(game_instance.env)
        data['custom_metric'] = custom_metric
        return data

    .gameplay(callback=my_callback)

Deployment
----------

Local Testing
^^^^^^^^^^^^^

.. code-block:: bash

    python my_experiment.py

    # Open browser to http://localhost:8000

Production Deployment
^^^^^^^^^^^^^^^^^^^^^

**Option 1: Single Server**

.. code-block:: bash

    python my_experiment.py --port 8000

Use Nginx for:

- HTTPS/TLS
- Static file serving
- Load balancing (if multiple workers)

**Option 2: Multiple Workers**

.. code-block:: bash

    # Start multiple instances on different ports
    python my_experiment.py --port 8001 &
    python my_experiment.py --port 8002 &
    python my_experiment.py --port 8003 &

    # Nginx load balances across them

**Option 3: Cloud Deployment**

- AWS EC2, GCP Compute Engine, Azure VMs
- Use appropriate instance size for your environment
- Consider auto-scaling for variable load

Docker
^^^^^^

.. code-block:: dockerfile

    FROM python:3.11

    WORKDIR /app

    COPY requirements.txt .
    RUN pip install -r requirements.txt

    COPY . .

    CMD ["python", "my_experiment.py"]

Run:

.. code-block:: bash

    docker build -t my-experiment .
    docker run -p 8000:8000 my-experiment

Monitoring
----------

Server Logs
^^^^^^^^^^^

Monitor for:

- Connection errors
- Environment errors
- Performance warnings
- Data saving issues

.. code-block:: python

    .experiment(
        logfile="experiment.log",
    )

Metrics
^^^^^^^

Track:

- Active games
- Connected participants
- Average FPS achieved
- Error rates

Use logging or monitoring tools (Prometheus, Grafana, etc.).

Debugging
---------

Test with Multiple Browsers
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Open multiple browser windows:

1. Window 1: Player 1
2. Window 2: Player 2
3. Complete gameplay together

Check Logs
^^^^^^^^^^

Server logs show:

- Participant connections
- Game creation/completion
- Errors during gameplay

.. code-block:: bash

    tail -f experiment.log

Network Tab
^^^^^^^^^^^

Browser DevTools → Network tab:

- Check WebSocket connection
- Monitor message frequency
- Verify state updates

Best Practices
--------------

1. **Test locally first**: Complete gameplay before deploying
2. **Monitor resources**: Track CPU/memory during experiments
3. **Set concurrent game limits**: Prevent server overload
4. **Deploy close to participants**: Minimize latency
5. **Log everything**: Easier to debug issues
6. **Validate actions**: Prevent invalid states
7. **Handle disconnections**: Participants may lose connection
8. **Test at scale**: Simulate max concurrent load

Comparison: Server vs Pyodide
------------------------------

.. list-table::
   :header-rows: 1
   :widths: 30 35 35

   * - Feature
     - Server Mode
     - Pyodide Mode
   * - **Players**
     - Multiple humans + AI
     - 1 human + AI
   * - **Latency**
     - Network-dependent
     - None (local)
   * - **Initial Load**
     - Instant
     - 30-90 seconds
   * - **Server Load**
     - Proportional to players
     - Minimal
   * - **Environment**
     - Any Python code
     - Pure Python only
   * - **AI Inference**
     - On server (can use GPU)
     - In browser
   * - **Data Security**
     - Real-time validation
     - Sent periodically
   * - **Debugging**
     - Server logs
     - Browser console
   * - **Scaling**
     - Requires server resources
     - Scales with participants

Common Issues
-------------

**High latency**

- Deploy server closer to participants
- Reduce environment computation time
- Lower FPS
- Check network quality

**Games not starting**

- Check ``max_concurrent_games`` setting
- Verify all players have connected
- Look for environment initialization errors

**Actions not registered**

- Check ``action_mapping`` configuration
- Verify keyboard input in browser console
- Test with different browsers

**Data not saving**

- Check file permissions on data directory
- Verify ``scene_id`` is set
- Look for errors in server logs

**Memory leaks**

- Profile environment with multiple episodes
- Clear large arrays in ``reset()``
- Monitor memory usage during long sessions

Next Steps
----------

- **Compare with Pyodide**: :doc:`pyodide_mode`
- **Learn about policies**: :doc:`../guides/policies/ai_policies`
- **See multiplayer example**: :doc:`../examples/cogrid_overcooked`
