Overcooked: Human-AI (Client-Side)
===================================

Human-AI coordination experiment where one human player collaborates with an AI teammate to prepare and deliver dishes. The environment runs client-side with AI policy inference in the browser or on the server. In the example, we show Experiment 1 from from [McDonald & Gonzalez (2025)](https://arxiv.org/abs/2503.05455). 
It represents an experiment where humans play with two different AI partners, produced by two separate algorithms. Participants play 
with the agents across layouts and their subjective preferences between the two are evaluated, alongside survey responses. 

Overview
--------

Participants work alongside an AI chef to complete cooking tasks in various kitchen layouts. This example demonstrates client-side execution with trained ONNX policies, tutorial onboarding, and randomized layout selection for research experiments.

**What you'll learn:**

- Client-side Human-AI coordination experiments
- Tutorial scenes for participant onboarding
- Randomized scene selection for between-subjects designs
- ONNX policy integration with multiple trained models
- Complex sprite-based rendering with atlases

Features Demonstrated
---------------------

.. list-table::
   :widths: 30 70

   * - **Execution Mode**
     - Client-side
   * - **Players**
     - 1 human + 1 AI
   * - **Environment**
     - CoGrid Overcooked with 5 kitchen layouts
   * - **Rendering**
     - Sprite atlases with tile-based rendering
   * - **Input**
     - Arrow keys + action keys (W, Q)
   * - **AI Policies**
     - Self-Play (SP) and Behavior Shaping (BS) models for each layout
   * - **Complexity**
     - Advanced

Prerequisites
-------------

1. Clone the Interactive Gym repository and install with server dependencies:

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

    python -m interactive_gym.examples.cogrid.overcooked_human_ai_client_side

Then:

1. **Open browser** to http://localhost:5702
2. **Read instructions** on the start screen
3. **Complete tutorial** - Solo practice to learn controls
4. **Play main game** - Collaborate with AI on one randomly-selected layout
5. **Provide feedback** - Complete survey about AI teammate

**Controls:**

- **Arrow Keys**: Move chef up/down/left/right
- **W**: Pick up / drop objects
- **Q**: Toggle (interact with pots)

File Structure
--------------

.. code-block:: text

    cogrid/
    ├── overcooked_human_ai_client_side.py  # Main experiment file
    ├── scenes/
    │   └── scenes.py                       # Scene definitions
    ├── overcooked_utils.py                 # Rendering functions
    └── overcooked_callback.py              # Game callbacks

Experiment Flow
---------------

The experiment uses a Stager to manage scene progression:

.. code-block:: python

    from interactive_gym.scenes import stager, scene
    from interactive_gym.examples.cogrid.scenes import scenes as oc_scenes

    stager = stager.Stager(
        scenes=[
            oc_scenes.start_scene,           # Welcome and instructions
            oc_scenes.tutorial_gym_scene,    # Solo practice
            scene.RandomizeOrder(            # Random layout selection
                scenes=[
                    oc_scenes.cramped_room_0,
                    oc_scenes.counter_circuit_0,
                    oc_scenes.forced_coordination_0,
                    oc_scenes.asymmetric_advantages_0,
                    oc_scenes.coordination_ring_0,
                ],
                keep_n=1,                   # Only play on one of the 5 layouts
            ),
            oc_scenes.feedback_scene,        # Survey
            oc_scenes.end_scene,             # Thank you
        ]
    )

Each participant experiences:

1. **Start Scene** - Instructions and consent
2. **Tutorial** - Solo practice in a simple layout
3. **One Random Layout** - Collaboration with AI
4. **Feedback Survey** - Questions about the AI teammate
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

Each layout has trained AI policies:

- **Self-Play (SP)** policies: Trained via self-play reinforcement learning
- **Behavior Shaping (BS)** policies: Trained to complement human partners using behavioral shaping techniques (McDonald & Gonzalez, 2025)

AI Policies
-----------

Policy Configuration
^^^^^^^^^^^^^^^^^^^^

Each layout has two policy variants defined in ``scenes/scenes.py``. The Behavior Shaping (BS) policies are trained using techniques from McDonald & Gonzalez (2025) to create AI teammates that complement human partners:

.. code-block:: python

    # Cramped Room policies
    SP_POLICY_MAPPING_CRAMPED_ROOM = {
        0: configuration_constants.PolicyTypes.Human,
        1: "static/assets/overcooked/models/sp_cramped_room_00.onnx",
    }

    BS_POLICY_MAPPING_CRAMPED_ROOM = {
        0: configuration_constants.PolicyTypes.Human,
        1: "static/assets/overcooked/models/ibc_cramped_room_00.onnx",
    }

    # Similarly for other layouts...
    # - SP_POLICY_MAPPING_ASYMMETRIC_ADVANTAGES
    # - BS_POLICY_MAPPING_COUNTER_CIRCUIT
    # - SP_POLICY_MAPPING_FORCED_COORDINATION
    # - BS_POLICY_MAPPING_COORDINATION_RING

Scene Creation
^^^^^^^^^^^^^^

Each layout scene is configured with its policy:

.. code-block:: python

    cramped_room_0 = (
        gym_scene.GymScene()
        .scene(scene_id="cramped_room_0", experiment_config={})
        .policies(policy_mapping=SP_POLICY_MAPPING_CRAMPED_ROOM)
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

Solo practice before playing with AI:

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
            scene_body_filepath="interactive_gym/server/static/templates/overcooked_controls.html",
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

The tutorial allows participants to learn:

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

    from interactive_gym.configurations import object_contexts

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

Data Collection
---------------

Interactive Gym automatically tracks:

- Each player's observations
- Actions taken by human and AI
- Shared team reward (dishes delivered)
- Episode score and time
- Timestamped event logs

Feedback Survey
^^^^^^^^^^^^^^^

The experiment includes a post-game survey:

.. code-block:: python

    feedback_scene = (
        static_scene.ScalesAndTextBox(
            scale_questions=[
                "The AI teammate was helpful.",
                "I enjoyed working with the AI teammate.",
                "The AI teammate understood my intentions.",
            ],
            scale_labels=[
                ["Strongly Disagree", "Neutral", "Strongly Agree"],
                ["Strongly Disagree", "Neutral", "Strongly Agree"],
                ["Strongly Disagree", "Neutral", "Strongly Agree"],
            ],
            text_box_header="Please describe your experience working with the AI teammate.",
            scale_size=7,
        )
        .scene(scene_id="feedback_scene", experiment_config={})
    )

Research Applications
---------------------

This example is designed for research on:

**Human-AI Coordination**
  Study how humans adapt to different AI policies

**Policy Comparison**
  Compare Self-Play vs Behavior Shaping policies with human partners

**Layout Effects**
  Investigate how environment structure affects coordination

**Learning and Adaptation**
  Track how humans change strategy when working with AI

**Theory of Mind**
  Study mental model formation during collaboration

References
----------

McDonald, C., & Gonzalez, C. (2025). Controllable Complementarity: Subjective Preferences in Human-AI Collaboration. *arXiv preprint arXiv:2503.05455*.
