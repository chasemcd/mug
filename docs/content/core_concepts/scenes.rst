Scenes
======

Scenes are the building blocks of Interactive Gym experiments. Each scene represents a stage in your experiment, from welcome screens to interactive gameplay to final thank-you pages.

Scene Types
-----------

Interactive Gym provides four types of scenes:

StartScene
^^^^^^^^^^

The entry point for participants. Every experiment must begin with a StartScene.

.. code-block:: python

    from interactive_gym.scenes import static_scene

    start_scene = (
        static_scene.StartScene()
        .scene(scene_id="welcome")
        .display(
            scene_header="Welcome to the Experiment",
            scene_body="<p>Thank you for participating...</p>"
        )
    )

**Use for:**

- Welcome messages
- Initial instructions
- Consent forms (with custom HTML)

**Key features:**

- Always shows a "Continue" button to advance
- Can include HTML in scene_body
- Required as first scene in every Stager

GymScene
^^^^^^^^

Interactive environment where participants engage with a Gymnasium-based environment.

.. code-block:: python

    from interactive_gym.scenes import gym_scene
    from interactive_gym.configurations import configuration_constants

    game_scene = (
        gym_scene.GymScene()
        .scene(scene_id="gameplay")
        .environment(env_creator=make_env, env_config={})
        .rendering(fps=30, game_width=600, game_height=400)
        .gameplay(
            num_episodes=5,
            action_mapping={"ArrowLeft": 0, "ArrowRight": 1},
            default_action=0,
        )
        .policies(policy_mapping={"human": configuration_constants.PolicyTypes.Human})
    )

**Use for:**

- Interactive gameplay
- Data collection during environment interaction
- Human-only, AI-only, or human-AI experiments

**Key features:**

- Supports Gymnasium environments
- Real-time rendering
- Flexible action mappings
- Episode management
- Policy execution (human, AI, or mixed)

EndScene
^^^^^^^^

The final scene shown to participants. Every experiment must end with an EndScene.

.. code-block:: python

    end_scene = (
        static_scene.EndScene()
        .scene(scene_id="thanks")
        .display(
            scene_header="Thank You!",
            scene_body="<p>Your participation is complete.</p>"
        )
    )

**Use for:**

- Thank you messages
- Redirecting to external surveys (e.g., Prolific, MTurk)
- Final instructions or debriefing

**Key features:**

- No "Continue" button (experiment ends here)
- Can trigger redirect after timeout
- Required as last scene in every Stager

StaticScene
^^^^^^^^^^^

Custom HTML pages for non-interactive content.

.. code-block:: python

    survey_scene = (
        static_scene.StaticScene()
        .scene(scene_id="demographics")
        .display(
            scene_header="Demographics Survey",
            scene_body="""
                <form id="demographics">
                    <label>Age: <input type="number" name="age"></label>
                    <label>Gender: <input type="text" name="gender"></label>
                </form>
            """
        )
    )

**Use for:**

- Surveys and questionnaires
- Additional instructions between games
- Attention checks
- Custom interactive HTML

**Key features:**

- Full HTML/CSS/JavaScript support
- Can disable "Continue" button until form completion
- Data can be collected via custom callbacks

Scene Configuration
-------------------

All scenes share common configuration methods:

.scene()
^^^^^^^^

Identify and configure the scene:

.. code-block:: python

    .scene(
        scene_id="unique_identifier",        # Required: unique ID for this scene
        experiment_config={},                 # Optional: scene-specific metadata
        should_export_metadata=True,          # Optional: save scene config to file
    )

.display()
^^^^^^^^^^

Set the visual content:

.. code-block:: python

    .display(
        scene_header="Scene Title",           # Displayed at top
        scene_body="<p>HTML content</p>",    # Main content area
        scene_body_filepath="path/to/file.html",  # Or load from file
    )

**Note:** Use either ``scene_body`` OR ``scene_body_filepath``, not both.

GymScene-Specific Configuration
--------------------------------

GymScene has additional configuration methods for interactive gameplay:

.environment()
^^^^^^^^^^^^^^

Define what environment to run:

.. code-block:: python

    .environment(
        env_creator=make_my_env,              # Function that returns a Gym env
        env_config={"difficulty": "hard"},    # Kwargs passed to env_creator
        seed=42,                               # Random seed for reproducibility
    )

.rendering()
^^^^^^^^^^^^

Control visual display:

.. code-block:: python

    .rendering(
        fps=30,                                # Frames per second
        game_width=600,                        # Canvas width in pixels
        game_height=400,                       # Canvas height in pixels
        env_to_state_fn=my_render_fn,        # Custom rendering function
        hud_text_fn=my_hud_fn,                # Function to generate HUD text
        location_representation="relative",    # "relative" (0-1) or "pixels"
        background="#FFFFFF",                  # Background color
    )

.gameplay()
^^^^^^^^^^^

Configure game mechanics:

.. code-block:: python

    .gameplay(
        num_episodes=5,                        # Number of episodes to play
        max_steps=1000,                        # Max steps per episode
        action_mapping={                       # Map keys to actions
            "ArrowLeft": 0,
            "ArrowRight": 1,
        },
        default_action=0,                      # Action when no key pressed
        action_population_method=              # How to handle missing actions
            configuration_constants.ActionSettings.DefaultAction,
        input_mode=                            # How to collect input
            configuration_constants.InputModes.PressedKeys,
        reset_freeze_s=0,                      # Freeze time after episode ends
    )

.policies()
^^^^^^^^^^^

Define who/what controls each agent:

.. code-block:: python

    .policies(
        policy_mapping={                       # Map agent IDs to policies
            "player_0": configuration_constants.PolicyTypes.Human,
            "player_1": "my_ai_policy",
        },
        load_policy_fn=load_policy,           # Function to load AI policies
        policy_inference_fn=run_inference,    # Function to run policy inference
        frame_skip=4,                          # Actions applied every N frames
    )

.content()
^^^^^^^^^^

Customize participant-facing text:

.. code-block:: python

    .content(
        scene_header="Game Title",
        scene_body="<p>Loading...</p>",       # Shown before game starts
        in_game_scene_body="<p>Instructions during game</p>",
        scene_body_filepath="instructions.html",  # Or load from file
        in_game_scene_body_filepath="hud.html",
    )

.runtime()
^^^^^^^^^^

Configure browser-based execution:

.. code-block:: python

    .runtime(
        run_through_pyodide=True,              # Enable Pyodide mode
        environment_initialization_code="import gym\nenv = gym.make('CartPole-v1')",
        environment_initialization_code_filepath="path/to/env.py",
        packages_to_install=["gymnasium==1.0.0", "numpy"],
        restart_pyodide=False,                 # Restart Pyodide between scenes
    )

Scene Lifecycle
---------------

Each scene goes through a lifecycle:

1. **Build**: Scene configuration is finalized
2. **Activate**: Scene becomes active for a participant
3. **Interact**: Participant engages with the scene
4. **Deactivate**: Participant advances, scene cleanup occurs

**Lifecycle Hooks:**

.. code-block:: python

    class CustomScene(gym_scene.GymScene):

        def on_connect(self, sio, room):
            """Called when participant connects to server"""
            pass

        def activate(self, sio, room):
            """Called when scene becomes active"""
            super().activate(sio, room)
            # Custom activation logic

        def deactivate(self):
            """Called when participant leaves scene"""
            # Cleanup logic
            super().deactivate()

Scene Metadata
--------------

Scenes can export metadata for analysis:

.. code-block:: python

    .scene(
        scene_id="my_scene",
        experiment_config={"version": "1.0", "condition": "A"},
        should_export_metadata=True,
    )

This saves a JSON file with:

- Scene ID
- Scene type
- All configuration parameters
- Timestamp
- Custom experiment_config data

Metadata is saved to ``data/{scene_id}/{subject_id}_metadata.json``.

Custom HTML in Scenes
---------------------

StartScene, EndScene, and StaticScene support full HTML:

.. code-block:: python

    scene = (
        static_scene.StaticScene()
        .scene(scene_id="survey")
        .display(
            scene_header="Quick Survey",
            scene_body="""
                <style>
                    .question { margin: 20px 0; }
                    label { display: block; margin: 5px 0; }
                </style>

                <div class="question">
                    <p>How much did you enjoy the game?</p>
                    <label><input type="radio" name="enjoy" value="1"> Not at all</label>
                    <label><input type="radio" name="enjoy" value="5"> Very much</label>
                </div>

                <script>
                    // Custom JavaScript for validation, etc.
                    document.querySelector('form').addEventListener('submit', (e) => {
                        // Validation logic
                    });
                </script>
            """
        )
    )

**Accessing form data:**

Use client callbacks to capture custom data (see :doc:`../guides/data_collection/callbacks`).

Multi-Scene Experiments
------------------------

Experiments can have any number of scenes between Start and End:

.. code-block:: python

    from interactive_gym.scenes import stager

    experiment = stager.Stager(scenes=[
        start_scene,                 # Required first
        instructions_scene,          # StaticScene
        practice_game_scene,         # GymScene
        survey_scene_1,              # StaticScene
        main_game_scene,             # GymScene
        survey_scene_2,              # StaticScene
        end_scene,                   # Required last
    ])

Participants progress through scenes by clicking "Continue" or completing episodes.

Scene IDs and Data Organization
--------------------------------

Scene IDs determine data organization:

.. code-block:: text

    data/
    ├── welcome/                    # StartScene data
    │   └── subject_123_metadata.json
    ├── game_scene_1/              # GymScene data
    │   ├── subject_123.csv
    │   ├── subject_123_globals.json
    │   └── subject_123_metadata.json
    ├── survey/                     # StaticScene data
    │   └── subject_123.csv
    └── thanks/                     # EndScene data
        └── subject_123_metadata.json

Use descriptive scene IDs to organize your data clearly.

Best Practices
--------------

1. **Use descriptive scene_ids**: ``"tutorial_level_1"`` not ``"scene1"``
2. **Keep instructions clear**: Participants won't ask for clarification
3. **Test the flow**: Complete the experiment yourself before running with participants
4. **Export metadata**: Set ``should_export_metadata=True`` for reproducibility
5. **Validate forms**: Use JavaScript to validate StaticScene forms before allowing "Continue"
6. **Handle errors**: Test what happens when participants refresh, go back, etc.

Common Patterns
---------------

**Practice + Main Game:**

.. code-block:: python

    practice_scene = (
        gym_scene.GymScene()
        .scene(scene_id="practice")
        .gameplay(num_episodes=3)  # Fewer episodes
        # ... other config
    )

    main_scene = (
        gym_scene.GymScene()
        .scene(scene_id="main_game")
        .gameplay(num_episodes=10)  # Full experiment
        # ... other config
    )

**Conditional Scene Content:**

.. code-block:: python

    .content(
        game_page_html_fn=lambda game, subject_id:
            f"<p>Your current score: {game.total_rewards[subject_id]}</p>"
    )

**Multiple Conditions:**

.. code-block:: python

    # Assign conditions in your experiment script
    import random

    condition = random.choice(["A", "B"])

    game_scene = (
        gym_scene.GymScene()
        .scene(
            scene_id=f"game_condition_{condition}",
            experiment_config={"condition": condition}
        )
        # Different config based on condition
    )

Next Steps
----------

- **Learn about the Stager**: :doc:`stager` to sequence scenes
- **Explore rendering**: :doc:`object_contexts` for visual elements
- **See examples**: :doc:`../examples/index` for complete experiments
