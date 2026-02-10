Footsies
========

The Footsies example demonstrates competitive fighting game mechanics using Unity WebGL integration. This advanced example showcases human skill learning experiments with adaptive AI opponents and comprehensive survey collection.

Overview
--------

Footsies is a minimalist fighting game focused on spacing and fundamentals. Participants train against AI opponents of varying difficulty, then face challenge rounds. This example is designed for research studies on human learning, AI training partners, and difficulty adaptation.

**What you'll learn:**

- Unity WebGL game integration
- Multi-scene experiment flows with surveys
- Dynamic difficulty adjustment systems
- Controllable AI opponent parameters
- Randomized scene ordering
- Completion code generation

Features Demonstrated
---------------------

.. list-table::
   :widths: 30 70

   * - **Execution Mode**
     - Unity WebGL (client-side game)
   * - **Players**
     - Human vs AI
   * - **Environment**
     - Unity-built fighting game
   * - **AI Policies**
     - Multiple ONNX models with configurable parameters
   * - **Input**
     - A/D keys (movement), Space bar (attack)
   * - **Surveys**
     - Likert scales, multiple choice, text responses
   * - **Complexity**
     - Advanced (research experiment)

Prerequisites
-------------

1. Clone the MUG repository and install with server dependencies:

   .. code-block:: bash

       git clone https://github.com/chasemcd/interactive-gym.git
       cd interactive-gym
       pip install -e .[server]

2. **Unity WebGL Build**: The Footsies game is pre-built as a Unity WebGL export located in the project's static assets.

Running the Example
-------------------

From the repository root, run as a module:

.. code-block:: bash

    python -m mug.examples.footsies.footsies_experiment

Then:

1. **Open browser** to http://localhost:5702
2. **Complete surveys** and tutorial
3. **Play initial challenge** rounds (10 episodes)
4. **Train** with adaptive AI partner (45 episodes)
5. **Complete final challenge** rounds (10 episodes)
6. **Receive completion code** for payment/recruitment platforms

File Structure
--------------

.. code-block:: text

    footsies/
    ├── footsies_experiment.py           # Main experiment with full flow
    ├── scenes.py                        # All scene definitions
    ├── footsies_scene.py                # Custom FootsiesScene class
    └── static/
        ├── introduction.html            # Welcome instructions
        ├── tutorial_static.html         # Tutorial content
        └── controllable_difficulty.html # Difficulty slider UI

Code Walkthrough
----------------

Experiment Flow
^^^^^^^^^^^^^^^

**footsies_experiment.py** orchestrates a complex multi-scene experiment:

.. code-block:: python

    from mug.scenes import stager, scene
    from mug.examples.footsies import scenes

    stager = stager.Stager(
        scenes=[
            scenes.start_scene,
            scenes.footsies_initial_survey_scene,
            scenes.footsies_tutorial_scene,
            scenes.footsies_initial_challenge_intro,
            scenes.footsies_initial_challenge_scene,
            scenes.footsies_initial_challenge_survey_scene,
            scene.RandomizeOrder(
                [
                    scenes.footsies_dynamic_difficulty_rounds,
                    scenes.footsies_controllable_difficulty_rounds,
                    scenes.footsies_high_skill_rounds,
                    scenes.footsies_low_skill_rounds,
                    scenes.footsies_random_difficulty_rounds,
                    scenes.footsies_dynamic_empowerment_rounds,
                    scenes.footsies_empowerment_rounds,
                ],
                keep_n=1,  # Randomly select ONE training condition
            ),
            scenes.footsies_training_survey_scene,
            scenes.footsies_mc_survey,
            scenes.footsies_final_challenge_intro,
            scenes.footsies_final_challenge_scene,
            scenes.footsies_end_survey_scene,
            scenes.footsies_end_scene,
        ]
    )

This creates a between-subjects design where each participant experiences one of seven training conditions.

Unity WebGL Scene
^^^^^^^^^^^^^^^^^

**scenes.py** defines FootsiesScene for Unity game integration:

.. code-block:: python

    from mug.examples.footsies import footsies_scene

    FOOTSIES_BUILD_NAME = "footsies_webgl_47f26fc"

    footsies_initial_challenge_scene = (
        footsies_scene.FootsiesScene()
        .display(
            scene_header="Footsies",
            scene_subheader="""
                <div style="text-align: center;">
                    <p>INITIAL CHALLENGE</p>
                </div>
            """
        )
        .scene(scene_id="footsies_initial_challenge", experiment_config={})
        .webgl(
            build_name=FOOTSIES_BUILD_NAME,
            height=1080 / 3,
            width=1960 / 3,
            preload_game=True,
        )
        .game(
            num_episodes=10,
            score_fn=lambda data: int(data["winner"] == "P1"),
        )
        .set_opponent_sequence(
            [
                footsies_scene.OpponentConfig(
                    model_path="4fs-16od-13c7f7b-0.05to0.01-sp-00",
                    frame_skip=4,
                    obs_delay=16,
                    inference_cadence=4,
                    softmax_temperature=1.0,
                ),
                # ... more opponent configs
            ],
            randomize=True,
        )
    )

**Key Methods:**

- ``.webgl(build_name, height, width)``: Loads Unity WebGL build
- ``.game(num_episodes, score_fn)``: Defines episode count and scoring
- ``.set_opponent_sequence([configs])``: Configures AI opponents

AI Opponent Configuration
^^^^^^^^^^^^^^^^^^^^^^^^^^

**OpponentConfig** controls AI behavior:

.. code-block:: python

    footsies_scene.OpponentConfig(
        model_path="4fs-16od-13c7f7b-0.05to0.01-sp-00",  # ONNX model file
        frame_skip=4,                # AI acts every 4 frames (slower = easier)
        obs_delay=16,                # Input lag for AI (higher = easier)
        inference_cadence=4,         # How often policy is queried
        softmax_temperature=1.0,     # Action randomness (higher = more random)
    )

**Difficulty Tuning:**

.. list-table::
   :header-rows: 1
   :widths: 30 20 50

   * - Parameter
     - Range
     - Effect
   * - frame_skip
     - 4-24
     - Higher values make AI slower/easier
   * - obs_delay
     - 8-24
     - Simulates reaction time delay
   * - softmax_temperature
     - 0.5-2.0
     - Higher values add randomness/mistakes
   * - inference_cadence
     - 2-8
     - How frequently AI updates action

Training Conditions
^^^^^^^^^^^^^^^^^^^

The experiment includes seven different training approaches:

**1. Fixed High Skill**

Constant difficult opponent:

.. code-block:: python

    footsies_fixed_high_skill_rounds = (
        footsies_scene.FootsiesScene()
        .game(num_episodes=45)
        .set_opponent_sequence([
            footsies_scene.OpponentConfig(
                model_path="4sf-16od-1c73fcc-0.03to0.01-500m-00",
                frame_skip=4,           # Fast
                softmax_temperature=1.0, # Deterministic
            )
        ])
    )

**2. Fixed Low Skill**

Constant easy opponent:

.. code-block:: python

    footsies_fixed_low_skill_rounds = (
        footsies_scene.FootsiesScene()
        .game(num_episodes=45)
        .set_opponent_sequence([
            footsies_scene.OpponentConfig(
                model_path="4sf-16od-1c73fcc-0.03to0.01-500m-00",
                frame_skip=24,          # Slow
                softmax_temperature=1.6, # Random
            )
        ])
    )

**3. Fixed Empowerment**

Uses empowerment-trained policy:

.. code-block:: python

    footsies_fixed_empowerment_rounds = (
        footsies_scene.FootsiesScene()
        .set_opponent_sequence([
            footsies_scene.OpponentConfig(
                model_path="esr-0.5alpha-00",  # Empowerment policy
                frame_skip=4,
                softmax_temperature=1.0,
            )
        ])
    )

**4. Dynamic Difficulty**

Adjusts difficulty based on player performance (implemented in FootsiesDynamicDifficultyScene).

**5. Random Difficulty**

Randomly samples difficulty each episode (implemented in FootsiesRandomDifficultyScene).

**6. Dynamic Empowerment**

Empowerment-based adaptive difficulty (implemented in FootsiesDynamicEmpowermentScene).

**7. Controllable Difficulty**

Player controls difficulty via slider:

.. code-block:: python

    footsies_controllable_difficulty_scene = (
        footsies_scene.FootsiesControllableDifficultyScene()
        .display(
            scene_body_filepath="mug/examples/footsies/static/controllable_difficulty.html",
        )
        .game(num_episodes=45)
    )

The HTML file includes a slider UI that participants use to adjust opponent difficulty in real-time.

Survey Collection
^^^^^^^^^^^^^^^^^

**Initial Survey** - Assess prior experience:

.. code-block:: python

    from mug.scenes import static_scene

    footsies_initial_survey_scene = (
        static_scene.ScalesAndTextBox(
            scale_questions=[
                "I play video games frequently.",
                "I have experience playing fighting games.",
                "I know the fundamental strategies of fighting games.",
            ],
            scale_labels=[
                ["Strongly Disagree", "Neutral", "Strongly Agree"],
                ["Strongly Disagree", "Neutral", "Strongly Agree"],
                ["Strongly Disagree", "Neutral", "Strongly Agree"],
            ],
            text_box_header="Please leave any additional comments about your experience with fighting games. Write N/A if you do not have anything to add.",
            scale_size=7,
        )
        .scene(scene_id="footsies_initial_survey_0", experiment_config={})
        .display(scene_subheader="Initial Survey")
    )

**Training Survey** - Collect feedback after training:

.. code-block:: python

    footsies_training_survey_scene = (
        static_scene.ScalesAndTextBox(
            scale_questions=[
                "My skills improved over the course of playing with my training partner.",
                "I learned new strategies from my training partner.",
                "I enjoyed playing against my training partner.",
                "I was motivated to beat my training partner.",
                "My training partner felt...",
            ],
            scale_labels=[
                ["Strongly Disagree", "Neutral", "Strongly Agree"],
                ["Strongly Disagree", "Neutral", "Strongly Agree"],
                ["Strongly Disagree", "Neutral", "Strongly Agree"],
                ["Strongly Disagree", "Neutral", "Strongly Agree"],
                ["Too Easy to Beat", "Evenly Matched", "Too Hard to Beat"],
            ],
            text_box_header="Please describe the general strategy you've learned from your training partner. What is your approach to winning?",
            scale_size=7,
        )
        .scene(scene_id="footsies_training_survey", experiment_config={})
    )

**Multiple Choice Quiz** - Test game knowledge:

.. code-block:: python

    footsies_mc_survey = (
        static_scene.MultipleChoice(
            questions=[
                "What key press(es) result in this movement?",
                "What key press(es) result in this attack?",
                # ... more questions
            ],
            choices=[
                [
                    "<img src='...' /> -> <img src='...' />",
                    # ... answer options with key images
                ],
                # ... choices for each question
            ],
            images=[
                "static/assets/footsies/gifs/backward_dash.gif",
                "static/assets/footsies/gifs/kick_ko.gif",
                # ... GIFs showing moves
            ],
            multi_select=True,
        )
        .scene(scene_id="footsies_mc_survey", experiment_config={})
    )

Participants see GIFs of moves and select the correct key presses.

Completion Codes
^^^^^^^^^^^^^^^^

End with a completion code for Prolific/MTurk:

.. code-block:: python

    footsies_end_scene = (
        static_scene.CompletionCodeScene()
        .scene(
            scene_id="footsies_end_completion_code_scene",
            should_export_metadata=True,
            experiment_config={},
        )
        .display(
            scene_header="Thank you for participating!",
        )
    )

MUG automatically generates a unique completion code displayed to the participant.

How It Works
------------

Unity-Flask Communication
^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: text

    Browser                         Flask Server                Unity Game
    ───────                        ─────────────               ──────────

    1. Load Unity WebGL build
    2. Initialize game
                                                            3. Request opponent config
    4. Display game           ←    5. Send config        ←
    6. Player presses space
    7. Send input to Unity    →
                                                            8. Step game logic
                                                            9. Run AI inference
                                                            10. Return game state
    11. Display updated frame ←                         ←
                                   12. Log data
    (Repeat 6-12)

Unity communicates with Flask via JavaScript bridge, allowing MUG to control opponent policies and collect data.

Opponent Randomization
^^^^^^^^^^^^^^^^^^^^^^

When ``randomize=True`` in ``.set_opponent_sequence()``:

.. code-block:: python

    .set_opponent_sequence(
        [opponent_1, opponent_2, opponent_3, ...],
        randomize=True,
    )

Each episode randomly samples one opponent configuration from the list, preventing participants from adapting to a specific opponent pattern.

Data Collection
^^^^^^^^^^^^^^^

Footsies tracks:

- Game state each frame
- Player actions and timing
- AI opponent actions
- Round outcomes (win/loss)
- Survey responses
- Completion codes

Custom data can be added via the Unity game build or scene callbacks.
