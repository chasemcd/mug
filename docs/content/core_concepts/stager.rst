Stager
======

The Stager manages participants' progression through a sequence of scenes. It tracks where each participant is in the experiment, handles scene transitions, and ensures each participant experiences scenes in the correct order.

What is a Stager?
-----------------

A Stager is a container for scenes that:

- Defines the sequence of scenes in your experiment
- Manages per-participant state (which scene they're on)
- Handles scene activation and deactivation
- Coordinates data collection across scenes

**One Stager instance per participant:**

When a participant joins, the server creates a Stager instance for them. Each participant's Stager is independent, allowing multiple participants to be at different stages of the experiment simultaneously.

Creating a Stager
-----------------

Basic Usage
^^^^^^^^^^^

.. code-block:: python

    from mug.scenes import stager, static_scene, gym_scene

    # Define your scenes
    start_scene = static_scene.StartScene().display(...)
    game_scene = gym_scene.GymScene().gameplay(...)
    end_scene = static_scene.EndScene().display(...)

    # Create the stager
    experiment_stager = stager.Stager(
        scenes=[start_scene, game_scene, end_scene]
    )

**Required structure:**

- First scene must be a ``StartScene``
- Last scene must be an ``EndScene``
- Any number of scenes can be between them

With Options
^^^^^^^^^^^^

.. code-block:: python

    experiment_stager = stager.Stager(
        scenes=[start_scene, game_scene, end_scene],
        stager_id="my_experiment_v1",              # Optional: identifier
        allow_scene_skipping=False,                 # Optional: prevent skipping
    )

How Staging Works
-----------------

Scene Progression
^^^^^^^^^^^^^^^^^

Participants move through scenes in order:

1. **StartScene**: Participant sees welcome/instructions, clicks "Continue"
2. **Next scene activates**: Could be GymScene, StaticScene, etc.
3. **Scene completes**: GymScene ends after episodes, StaticScene on "Continue"
4. **Process repeats**: Until EndScene is reached
5. **EndScene**: Experiment ends, participant sees thank you/redirect

**Automatic Progression:**

- StartScene/StaticScene: Clicking "Continue" advances to next scene
- GymScene: Automatically advances after all episodes complete
- EndScene: No progression (experiment ends)

Per-Participant State
^^^^^^^^^^^^^^^^^^^^^

Each participant's Stager tracks:

.. code-block:: python

    stager_instance = {
        "current_scene_index": 2,           # Which scene they're on
        "subject_id": "participant_123",    # Their unique ID
        "scenes": [scene1, scene2, scene3], # Scene sequence
        "metadata": {                        # Custom data
            "condition": "A",
            "start_time": "2024-01-01T10:00:00",
        }
    }

This state is maintained throughout the experiment, surviving scene transitions.

Multi-Participant Management
-----------------------------

Multiple participants can be in different scenes simultaneously:

.. code-block:: text

    Participant 1: Welcome Scene (scene 0)
    Participant 2: Game Scene (scene 1)
    Participant 3: Survey Scene (scene 2)
    Participant 4: Game Scene (scene 1)
    Participant 5: Thank You Scene (scene 3)

Each has their own independent Stager instance managing their progress.

Stager Lifecycle
----------------

For each participant:

1. **Connection**: Participant connects to server
2. **Stager Creation**: New Stager instance created with scene sequence
3. **Scene 0 Activation**: First scene (StartScene) becomes active
4. **Progression Loop**:

   - Participant completes current scene
   - Stager deactivates current scene
   - Stager activates next scene
   - Repeat until EndScene

5. **Completion**: Participant finishes EndScene, connection closes
6. **Cleanup**: Stager instance and associated resources released

Scene Activation/Deactivation
------------------------------

The Stager handles scene lifecycle:

**Activation:**

.. code-block:: python

    def activate_scene(self, scene_index):
        # Deactivate current scene (if any)
        if self.current_scene:
            self.current_scene.deactivate()

        # Activate new scene
        self.current_scene = self.scenes[scene_index]
        self.current_scene.activate(socketio=self.socketio, room=self.room)
        self.current_scene_index = scene_index

**Deactivation:**

.. code-block:: python

    def deactivate_current_scene(self):
        if self.current_scene:
            self.current_scene.deactivate()
            # Cleanup: save data, release resources, etc.

This ensures proper initialization and cleanup for each scene.

Advanced Usage
--------------

Custom Stager Subclass
^^^^^^^^^^^^^^^^^^^^^^

Extend the Stager for custom behavior:

.. code-block:: python

    from mug.scenes.stager import Stager

    class ConditionalStager(Stager):

        def get_next_scene_index(self):
            """Override to implement conditional branching"""
            current = self.current_scene_index

            # Example: Skip scene 2 if condition met
            if current == 1 and self.check_condition():
                return 3  # Skip to scene 3
            else:
                return current + 1  # Normal progression

        def check_condition(self):
            # Custom logic
            return self.metadata.get("skip_tutorial", False)

Scene Branching
^^^^^^^^^^^^^^^

Implement conditional scene sequences:

.. code-block:: python

    class BranchingStager(Stager):

        def __init__(self, scenes, condition_fn):
            super().__init__(scenes)
            self.condition_fn = condition_fn

        def get_next_scene_index(self):
            current = self.current_scene_index

            # Branch based on performance
            if current == 1:  # After practice game
                score = self.get_participant_score()
                if self.condition_fn(score):
                    return 2  # Go to hard version
                else:
                    return 3  # Go to easy version

            return current + 1

**Usage:**

.. code-block:: python

    def high_performer(score):
        return score > 50

    branching_stager = BranchingStager(
        scenes=[start, practice, hard_game, easy_game, survey, end],
        condition_fn=high_performer
    )

Metadata Tracking
^^^^^^^^^^^^^^^^^

Add custom metadata to track throughout the experiment:

.. code-block:: python

    stager_instance = stager.Stager(scenes=[...])

    # Add metadata programmatically
    stager_instance.metadata["condition"] = random.choice(["A", "B"])
    stager_instance.metadata["start_time"] = datetime.now().isoformat()

    # Access in scene callbacks
    def on_game_complete(game, stager_instance):
        condition = stager_instance.metadata["condition"]
        # Log or adjust based on condition

Stager and GameManager
-----------------------

For GymScenes, the Stager interacts with the GameManager:

.. code-block:: text

    Stager (per participant)
    ├── Activates GymScene
    │   └── GymScene creates/joins Game via GameManager
    │       ├── GameManager assigns to Game
    │       ├── Game runs environment
    │       └── Game collects data
    │
    └── Waits for Game completion
        └── Deactivates GymScene
            └── Advances to next scene

The Stager delegates game mechanics to the GameManager but maintains overall experiment flow.

Data Organization
-----------------

The Stager doesn't directly handle data collection, but it organizes where data is saved:

.. code-block:: text

    data/
    ├── {scene_0_id}/           # StartScene data
    │   └── {subject_id}_metadata.json
    ├── {scene_1_id}/           # First GymScene
    │   ├── {subject_id}.csv
    │   └── {subject_id}_metadata.json
    ├── {scene_2_id}/           # StaticScene (survey)
    │   └── {subject_id}.csv
    └── {scene_3_id}/           # EndScene
        └── {subject_id}_metadata.json

Each scene's ID determines its data directory.

Common Patterns
---------------

Simple Linear Experiment
^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    stager = stager.Stager(scenes=[
        start_scene,
        game_scene,
        end_scene,
    ])

Practice + Main Game
^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    stager = stager.Stager(scenes=[
        start_scene,
        tutorial_scene,
        practice_game_scene,      # Low stakes
        instructions_scene,
        main_game_scene,          # Real data collection
        survey_scene,
        end_scene,
    ])

Multiple Conditions
^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    import random

    condition = random.choice(["control", "treatment"])

    if condition == "control":
        game_scene = control_game_scene
    else:
        game_scene = treatment_game_scene

    stager = stager.Stager(scenes=[
        start_scene,
        game_scene,  # Different based on condition
        end_scene,
    ])

    # Save condition to scene metadata
    game_scene.experiment_config["condition"] = condition

Repeated Measures
^^^^^^^^^^^^^^^^^

.. code-block:: python

    # Same participant plays multiple game versions
    stager = stager.Stager(scenes=[
        start_scene,
        game_version_a,
        survey_1,
        game_version_b,
        survey_2,
        game_version_c,
        survey_3,
        end_scene,
    ])

Between-Subjects Design
^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    # Different participants get different scene sequences
    participant_id = get_participant_id()
    condition = assign_condition(participant_id)

    if condition == "A":
        scenes = [start, game_a, survey, end]
    elif condition == "B":
        scenes = [start, game_b, survey, end]
    else:
        scenes = [start, game_c, survey, end]

    stager = stager.Stager(scenes=scenes)

Debugging and Testing
---------------------

Test Scene Progression
^^^^^^^^^^^^^^^^^^^^^^

Run through your experiment to verify scenes flow correctly:

.. code-block:: python

    # Start server
    python my_experiment.py

    # Open browser, complete each scene
    # Check logs for:
    # - Scene activation messages
    # - Data saving confirmations
    # - Any errors during transitions

Check Stager State
^^^^^^^^^^^^^^^^^^

Add logging to see what's happening:

.. code-block:: python

    class DebugStager(Stager):

        def activate_scene(self, scene_index):
            print(f"Activating scene {scene_index}: {self.scenes[scene_index].scene_id}")
            super().activate_scene(scene_index)

        def deactivate_current_scene(self):
            print(f"Deactivating scene {self.current_scene_index}")
            super().deactivate_current_scene()

Best Practices
--------------

1. **Use descriptive scene IDs**: Makes data organization clearer
2. **Test the full flow**: Complete the entire experiment yourself
3. **Handle disconnections**: Consider what happens if a participant refreshes
4. **Log state transitions**: Useful for debugging progression issues
5. **Validate scene order**: Ensure StartScene is first, EndScene is last
6. **Keep metadata light**: Don't store large objects in stager metadata

Common Issues
-------------

**Scene not advancing**

- Check that GymScene has correct ``num_episodes`` set
- Verify "Continue" button is enabled in StaticScenes
- Look for JavaScript errors in browser console

**Data not saving**

- Confirm ``scene_id`` is set for each scene
- Check file permissions in data directory
- Verify ``should_export_metadata=True`` if expecting metadata files

**Participants see wrong scene**

- Check scene order in Stager initialization
- Verify no custom ``get_next_scene_index()`` logic causing issues
- Look for race conditions in custom Stager subclass

**Multiple participants interfering**

- Each participant should have their own Stager instance (handled automatically)
- Check that you're not sharing game state across participants
- Verify thread-safety in custom callbacks

Next Steps
----------

- **Learn about scenes**: :doc:`scenes` for detailed scene documentation
- **Explore examples**: :doc:`../examples/index` for complete experiments
- **Data collection**: :doc:`../guides/data_collection/automatic_logging`
