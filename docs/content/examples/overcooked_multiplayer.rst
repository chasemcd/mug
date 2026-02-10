Overcooked: Human-Human (Server-Side)
======================================

Multi-player coordination experiment where two human players collaborate to prepare and deliver dishes. The environment runs server-side with synchronized gameplay and matchmaking.

.. raw:: html

   <div style="background-color: #f0f0f0; border: 2px solid #ff0000; padding: 10px; margin: 10px 0;">
   <h3 style="color: #ff0000;">⚠️ Warning</h3>

.. warning::
    Server-side multi-player experiments are currently being refactored to be more robust. They are currently out of date. For the current status on multi-human
    experiments, please see `Issue #14 <https://github.com/chasemcd/interactive-gym/issues/14>`_.
.. raw:: html

   </div>



Overview
--------

Two participants work together as chefs to complete cooking tasks in various kitchen layouts. This example demonstrates server-side execution with player matchmaking, synchronized multi-player gameplay, and collaborative task completion.

**What you'll learn:**

- Server-side multi-player coordination experiments
- Player matchmaking and waitroom functionality
- Synchronized gameplay between two browsers
- Tutorial scenes for participant onboarding
- Randomized layout selection for between-subjects designs
- Complex sprite-based rendering with atlases

Features Demonstrated
---------------------

.. list-table::
   :widths: 30 70

   * - **Execution Mode**
     - Server-side (required for multiplayer)
   * - **Players**
     - 2 humans
   * - **Environment**
     - CoGrid Overcooked with 5 kitchen layouts
   * - **Rendering**
     - Sprite atlases with tile-based rendering
   * - **Input**
     - Arrow keys + action keys (W, Q)
   * - **Matchmaking**
     - Automatic player pairing in waitroom
   * - **Complexity**
     - Advanced

Prerequisites
-------------

1. Clone the MUG repository and install with server dependencies:

   .. code-block:: bash

       git clone https://github.com/chasemcd/interactive-gym.git
       cd interactive-gym
       pip install -e .[server]

2. Install the CoGrid Overcooked environment:

   .. code-block:: bash

       pip install git+https://github.com/chasemcd/cogrid.git

Running the Example
-------------------

From the repository root, run as a module:

.. code-block:: bash

    python -m mug.examples.cogrid.overcooked_human_human_server_side

Then:

1. **Open two browser windows** to http://localhost:5702
2. **Wait for matchmaking** - Both players must connect before game starts
3. **Read instructions** on the start screen
4. **Complete tutorial** - Each player practices solo to learn controls
5. **Play main game** - Collaborate with partner on one randomly-selected layout
6. **Provide feedback** - Complete survey about teammate collaboration

**Controls:**

- **Arrow Keys**: Move chef up/down/left/right
- **W**: Pick up / drop objects
- **Q**: Toggle (interact with pots)

File Structure
--------------

.. code-block:: text

    cogrid/
    ├── overcooked_human_human_server_side.py  # Main experiment file
    ├── scenes/
    │   └── scenes.py                          # Scene definitions
    └── overcooked_utils.py                    # Rendering functions

Experiment Flow
---------------

The experiment uses a Stager to manage scene progression for both players:

.. code-block:: python

    from mug.scenes import stager, scene
    from mug.examples.cogrid.scenes import scenes as oc_scenes

    stager = stager.Stager(
        scenes=[
            oc_scenes.start_scene,           # Welcome and instructions
            oc_scenes.tutorial_gym_scene,    # Solo practice (each player)
            scene.RandomizeOrder(            # Random layout selection
                scenes=[
                    oc_scenes.cramped_room_human_human,
                    oc_scenes.counter_circuit_human_human,
                    oc_scenes.forced_coordination_human_human,
                    oc_scenes.asymmetric_advantages_human_human,
                    oc_scenes.coordination_ring_human_human,
                ],
            ),
            oc_scenes.feedback_scene,        # Survey
            oc_scenes.end_scene,             # Thank you
        ]
    )

Each participant pair experiences:

1. **Start Scene** - Instructions and consent
2. **Tutorial** - Solo practice in a simple layout (each player individually)
3. **One Random Layout** - Collaboration with human partner
4. **Feedback Survey** - Questions about the collaboration
5. **End Scene** - Thank you message

Kitchen Layouts
---------------

Five layouts with different coordination challenges:

**Cramped Room**
  Small kitchen requiring tight coordination and turn-taking

**Asymmetric Advantages**
  Asymmetric layout where players have different optimal roles

**Counter Circuit**
  Large kitchen with circular counter layout promoting specialization

**Forced Coordination**
  Layout requiring specific division of labor to succeed

**Coordination Ring**
  Ring-shaped kitchen with central cooking area

Each layout tests different aspects of human-human coordination and task allocation.

Multi-Player Scene Configuration
---------------------------------

Scene Creation for Two Humans
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Each layout scene is configured for two human players:

.. code-block:: python

    from mug.scenes import gym_scene
    from mug.configurations import configuration_constants

    # Action definitions
    MoveUp = 0
    MoveDown = 1
    MoveLeft = 2
    MoveRight = 3
    PickupDrop = 4
    Toggle = 5
    Noop = 6

    # Both players are human
    HUMAN_HUMAN_POLICY_MAPPING = {
        0: configuration_constants.PolicyTypes.Human,
        1: configuration_constants.PolicyTypes.Human,
    }

    action_mapping = {
        "ArrowLeft": MoveLeft,
        "ArrowRight": MoveRight,
        "ArrowUp": MoveUp,
        "ArrowDown": MoveDown,
        "w": PickupDrop,
        "W": PickupDrop,
        "q": Toggle,
        "Q": Toggle,
    }

    cramped_room_human_human = (
        gym_scene.GymScene()
        .scene(scene_id="cramped_room_hh", experiment_config={})
        .policies(policy_mapping=HUMAN_HUMAN_POLICY_MAPPING)
        .rendering(
            fps=30,
            env_to_state_fn=overcooked_utils.overcooked_env_to_render_fn,
            assets_to_preload=overcooked_utils.overcooked_preload_assets_spec(),
            hud_text_fn=overcooked_utils.hud_text_fn,
            game_width=overcooked_utils.TILE_SIZE * 7,
            game_height=overcooked_utils.TILE_SIZE * 6,
            background="#e6b453",
        )
        .gameplay(
            default_action=Noop,
            action_mapping=action_mapping,
            num_episodes=3,
            max_steps=30 * 60,  # 60 seconds at 30 FPS
            input_mode=configuration_constants.InputModes.SingleKeystroke,
        )
        .environment(
            env_creator=make_cramped_room_env,
            env_name="cramped_room",
        )
    )

Tutorial Scene
--------------

Solo practice before playing with partner:

.. code-block:: python

    tutorial_gym_scene = (
        gym_scene.GymScene()
        .scene(scene_id="overcooked_tutorial", experiment_config={})
        .policies(
            policy_mapping={
                0: configuration_constants.PolicyTypes.Human,
            },
        )
        .rendering(
            fps=30,
            env_to_state_fn=overcooked_utils.overcooked_env_to_render_fn,
            assets_to_preload=overcooked_utils.overcooked_preload_assets_spec(),
            hud_text_fn=overcooked_utils.hud_text_fn,
            game_width=overcooked_utils.TILE_SIZE * 7,
            game_height=overcooked_utils.TILE_SIZE * 6,
            background="#e6b453",
        )
        .gameplay(
            default_action=Noop,
            action_mapping=action_mapping,
            num_episodes=1,
            max_steps=1000,
            input_mode=configuration_constants.InputModes.SingleKeystroke,
        )
        .content(
            scene_header="Overcooked Tutorial",
            scene_body_filepath="mug/server/static/templates/overcooked_controls.html",
            in_game_scene_body="""
                <center>
                <p>Use arrow keys and W to pick up/drop. Try delivering a dish!</p>
                </center>
            """,
        )
        .environment(
            env_creator=make_tutorial_env,
            env_name="tutorial",
        )
    )

The tutorial allows each participant to independently learn:

- Movement with arrow keys
- Picking up onions with W
- Dropping onions in pots with W
- Picking up plates
- Delivering completed dishes

Rendering System
----------------

Sprite Atlases
^^^^^^^^^^^^^^

Overcooked uses texture atlases for efficient rendering:

.. code-block:: python

    from mug.configurations import object_contexts

    def overcooked_preload_assets_spec():
        terrain = object_contexts.AtlasSpec(
            name="terrain",
            img_path="static/assets/overcooked/sprites/terrain.png",
            atlas_path="static/assets/overcooked/sprites/terrain.json",
        )
        chefs = object_contexts.AtlasSpec(
            name="chefs",
            img_path="static/assets/overcooked/sprites/chefs.png",
            atlas_path="static/assets/overcooked/sprites/chefs.json",
        )
        objects = object_contexts.AtlasSpec(
            name="objects",
            img_path="static/assets/overcooked/sprites/objects.png",
            atlas_path="static/assets/overcooked/sprites/objects.json",
        )
        return [terrain.as_dict(), chefs.as_dict(), objects.as_dict()]

Tile-Based Coordinates
^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    TILE_SIZE = 45

    def get_x_y(pos: tuple[int, int], game_height: int, game_width: int):
        col, row = pos
        x = row * TILE_SIZE / game_width
        y = col * TILE_SIZE / game_height
        return x, y

Static vs Dynamic Rendering
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Permanent objects (counters, stacks, delivery zones) are rendered once:

.. code-block:: python

    def overcooked_env_to_render_fn(env, config):
        render_objects = []

        # Static objects rendered only on first frame
        if env.t == 0:
            render_objects += generate_counter_objects(env, config)
            render_objects += generate_delivery_areas(env, config)
            render_objects += generate_static_tools(env, config)

        # Dynamic objects every frame
        render_objects += generate_agent_sprites(env, config)
        render_objects += generate_objects(env, config)

        return [obj.as_dict() for obj in render_objects]

HUD Display
^^^^^^^^^^^

.. code-block:: python

    def hud_text_fn(game):
        score = int(list(game.episode_rewards.values())[0])
        time_left = (game.env.max_steps - game.tick_num) / game.config.fps
        return f"Score: {score:03d}   |    Time Left: {time_left:.1f}s"

How It Works
------------

Server-Side Multiplayer Flow
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: text

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

The server coordinates both players and ensures synchronized gameplay.

Matchmaking and Waitroom
^^^^^^^^^^^^^^^^^^^^^^^^^

When the first player connects:

.. code-block:: text

    Player 1                    Server
    ────────                    ──────

    1. Connect to server   →    2. Create waitroom
                           ←    3. Show "Waiting for partner..."
    4. Wait

When the second player connects:

.. code-block:: text

    Player 2                    Server                  Player 1
    ────────                    ──────                  ────────

    1. Connect            →     2. Match with P1
                          →     3. Start experiment →   Start game
    Start game            ←     4. Send start signal

Both players proceed through scenes together, with synchronized scene transitions.

Synchronized Gameplay
^^^^^^^^^^^^^^^^^^^^^

During gameplay:

1. **Action Collection**: Server waits for actions from both players
2. **Simultaneous Step**: Environment steps with both actions at once
3. **State Broadcasting**: Same rendered state sent to both browsers
4. **Frame Synchronization**: Both players see identical game state

This ensures:

- No action is processed until both players have submitted
- Both players always see the same game state
- Fair gameplay with no timing advantages

Data Collection
---------------

MUG automatically tracks for both players:

- Each player's observations
- Actions taken by both players
- Shared team reward (dishes delivered)
- Episode score and time
- Timestamped event logs
- Individual player metrics

Feedback Survey
^^^^^^^^^^^^^^^

The experiment includes a post-game survey:

.. code-block:: python

    feedback_scene = (
        static_scene.ScalesAndTextBox(
            scale_questions=[
                "My teammate was helpful.",
                "I enjoyed working with my teammate.",
                "My teammate and I coordinated well.",
                "I understood my teammate's intentions.",
            ],
            scale_labels=[
                ["Strongly Disagree", "Neutral", "Strongly Agree"],
                ["Strongly Disagree", "Neutral", "Strongly Agree"],
                ["Strongly Disagree", "Neutral", "Strongly Agree"],
                ["Strongly Disagree", "Neutral", "Strongly Agree"],
            ],
            text_box_header="Please describe your experience working with your teammate.",
            scale_size=7,
        )
        .scene(scene_id="feedback_scene", experiment_config={})
    )

Research Applications
---------------------

This example is designed for research on:

**Human-Human Coordination**
  Study how humans develop coordination strategies

**Communication and Theory of Mind**
  Investigate implicit communication without chat

**Task Allocation**
  Analyze how pairs divide labor spontaneously

**Learning and Adaptation**
  Track strategy evolution across episodes

**Layout Effects**
  Compare coordination difficulty across kitchen designs

**Individual Differences**
  Study personality and skill effects on teamwork
