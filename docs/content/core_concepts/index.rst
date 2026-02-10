Core Concepts
=============

This section provides in-depth documentation of MUG's architecture and key components. If you're new to MUG, start with the :doc:`../quick_start` guide first.

Overview
--------

MUG is built around a simple architecture for running human experiments with Python-based environments in the browser:

.. code-block:: text

    Experiment
    ├── Stager (manages scene progression)
    │   ├── StartScene (welcome/instructions)
    │   ├── GymScene(s) (interactive environments)
    │   └── EndScene (thank you/redirect)
    │
    └── ExperimentConfig (server settings, data collection)

Key Components
--------------

:doc:`scenes`
    Scenes represent stages in your experiment. Each scene defines what participants see and how they interact.

    - **StartScene**: Welcome screens and instructions
    - **GymScene**: Interactive environment gameplay
    - **EndScene**: Thank you messages and redirects
    - **StaticScene**: Custom HTML pages (surveys, consent forms, etc.)

:doc:`stager`
    The Stager manages participants' progression through a sequence of scenes. Each participant gets their own Stager instance to track their progress independently.

:doc:`object_contexts`
    Object contexts are lightweight dataclasses that define visual elements for rendering. Available types: Circle, Line, Polygon, Text, and Sprite.

:doc:`rendering_system`
    Understanding how MUG renders environments: coordinate systems, depth ordering, object lifecycle, and the frame-by-frame rendering process.

:doc:`pyodide_mode`
    Run environments entirely in the participant's browser using Pyodide. Best for single-player experiments with pure Python environments.

:doc:`server_mode`
    Run environments on your server for multi-player experiments, complex environments, or when using AI policies alongside humans.

Execution Modes
---------------

MUG supports two execution modes:

**Pyodide (Client-Side)**

- Environment runs in participant's browser
- No server-side computation
- Best for: Single-player experiments
- Requires: Pure Python environment (no compiled dependencies)
- Latency: None (fully local)

**Server (Server-Side)**

- Environment runs on your server
- Supports multiple participants
- Best for: Multi-player, human-AI experiments
- Requires: Server infrastructure
- Latency: Depends on network/server

See :doc:`pyodide_mode` and :doc:`server_mode` for detailed comparisons.

Architecture Flow
-----------------

1. **Participant connects** → Server creates a Stager instance for them
2. **Stager activates StartScene** → Participant sees welcome screen
3. **Participant clicks "Continue"** → Stager advances to GymScene
4. **GymScene activates** → GameManager creates/assigns to a game
5. **Game loop runs** → Environment steps, renders, sends state to browser
6. **Episodes complete** → Stager advances to EndScene
7. **Data saved** → Participant redirected or sees thank you message

Common Patterns
---------------

**Simple Single-Player Experiment**

.. code-block:: python

    start_scene = static_scene.StartScene().display(...)
    game_scene = gym_scene.GymScene().runtime(run_through_pyodide=True)
    end_scene = static_scene.EndScene().display(...)

    stager = stager.Stager(scenes=[start_scene, game_scene, end_scene])

**Multi-Player Experiment**

.. code-block:: python

    game_scene = (
        gym_scene.GymScene()
        .policies(policy_mapping={
            "player_0": PolicyTypes.Human,
            "player_1": PolicyTypes.Human,
        })
        # Server mode is automatic when multiple humans
    )

**Human-AI Experiment**

.. code-block:: python

    game_scene = (
        gym_scene.GymScene()
        .policies(
            policy_mapping={
                "player_0": PolicyTypes.Human,
                "player_1": "my_trained_policy",
            },
            load_policy_fn=load_my_policy,
            policy_inference_fn=run_inference,
        )
    )

Data Flow
---------

**Pyodide Mode:**

.. code-block:: text

    Browser (Pyodide)              Server
    ──────────────────            ──────
    1. Load environment
    2. Render frame
    3. Display to user
    4. Capture input
    5. Step environment
    6. Collect data              → 7. Save data
    (Repeat 2-6)

**Server Mode:**

.. code-block:: text

    Browser                       Server
    ───────                      ──────
    1. Display UI              ← 2. Send state
    3. Capture input           → 4. Receive action
                                 5. Step environment
                                 6. Render
    (Repeat 1-6)                 7. Save data

Configuration Philosophy
------------------------

MUG uses a fluent API for configuration:

.. code-block:: python

    scene = (
        gym_scene.GymScene()
        .scene(scene_id="my_game")           # Identification
        .environment(env_creator=make_env)    # What to run
        .rendering(fps=30, game_width=600)    # How to display
        .gameplay(num_episodes=5)             # Game mechanics
        .policies(policy_mapping={...})       # Who plays
        .content(scene_header="...")            # UI text
        .runtime(run_through_pyodide=True)   # Execution mode
    )

Each method returns the scene object, allowing you to chain configurations. This makes experiments readable and easy to modify.

Thread Safety
-------------

MUG handles multiple participants concurrently using thread-safe data structures:

- Each participant has their own Stager instance
- Games are managed with locks to prevent race conditions
- SocketIO handles real-time bidirectional communication
- Eventlet provides cooperative multitasking

You don't need to worry about thread safety in your experiment code—it's handled internally.

Next Steps
----------

- **Dive deeper**: Read the detailed pages for each component
- **See examples**: Check :doc:`../examples/index` for complete experiments
- **Build something**: Start with :doc:`../quick_start` if you haven't already

.. toctree::
   :maxdepth: 1
   :hidden:

   scenes
   stager
   object_contexts
   rendering_system
   pyodide_mode
   server_mode
