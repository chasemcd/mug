Quick Start
===========

This guide will walk you through building your first MUG experiment. We'll create a Mountain Car experiment where participants control a car trying to reach a flag on a hill.

What You'll Build
-----------------

A browser-based experiment where participants:

1. See a welcome screen with instructions
2. Play 5 episodes of Mountain Car using arrow keys
3. See custom graphics (car, hill, flag) rendered in the browser
4. See a thank you screen when finished

The environment runs entirely in the participant's browser using Pyodide.

Prerequisites
-------------

Install MUG with server dependencies:

.. code-block:: bash

    pip install multi-user-gymnasium[server]

Step 1: Create the Custom Environment
--------------------------------------

First, we'll create a custom Mountain Car environment with MUG's rendering system. The standard Mountain Car uses pygame for rendering, which isn't available in the browser. We'll override the ``render()`` method to use MUG's object-based rendering instead.

Create a file called ``mountain_car_rgb_env.py``:

.. code-block:: python

    """
    Custom Mountain Car that renders using MUG's object contexts.
    This allows it to run in the browser via Pyodide.
    """

    import numpy as np
    from gymnasium.envs.classic_control.mountain_car import MountainCarEnv as _BaseMountainCarEnv
    from mug.configurations.object_contexts import Circle, Line, Polygon


    class MountainCarEnv(_BaseMountainCarEnv):

        def step(self, actions: dict[str, int | float]):
            """Override step to accept dict of actions (required for multi-agent format)"""
            assert "human" in actions, "Must be using human agent ID!"
            action = actions["human"]
            return super().step(action)

        def render(self):
            """Return a list of visual objects to render in the browser"""
            assert self.render_mode == "mug"

            # Get environment bounds for coordinate normalization
            y_offset = 0.05
            min_pos = self.unwrapped.min_position
            max_pos = self.unwrapped.max_position

            def _normalize_x(vals):
                """Normalize x coordinates to 0-1 range for rendering"""
                vals = vals - min_pos
                return vals / (max_pos - min_pos)

            # 1. Create the car (rendered as a black circle)
            car_x = self.state[0]
            car_y = 1 - self._height(car_x) + y_offset
            car_x = _normalize_x(car_x)

            car = Circle(
                uuid="car",
                color="#000000",
                x=car_x,
                y=car_y,
                radius=16,
            )

            # 2. Create the ground (brown line with fill)
            xs = np.linspace(min_pos, max_pos, 100)
            ys = 1 - self._height(xs) + y_offset
            xs = _normalize_x(xs)
            points = list(zip(xs, ys))

            ground = Line(
                uuid="ground_line",
                color="#964B00",
                points=points,
                width=1,
                fill_below=True,
            )

            # 3. Create the flag pole (black vertical line)
            flag_x = _normalize_x(self.goal_position)
            flag_y1 = 1 - self._height(self.goal_position)
            flag_y2 = 0.05

            flag_pole = Line(
                uuid="flag_pole",
                color="#000000",
                points=[(flag_x, flag_y1), (flag_x, flag_y2)],
                width=3,
            )

            # 4. Create the flag (green triangle)
            flag = Polygon(
                uuid="flag",
                color="#00FF00",
                points=[
                    (flag_x, flag_y1),
                    (flag_x, flag_y1 + 0.03),
                    (flag_x - 0.02, flag_y1 + 0.015),
                ],
            )

            # Return list of objects as dictionaries
            return [
                car.as_dict(),
                ground.as_dict(),
                flag_pole.as_dict(),
                flag.as_dict(),
            ]


    # Create the environment instance (must be named 'env')
    env = MountainCarEnv(render_mode="mug")

**Key Points:**

- Use ``render_mode="mug"`` when creating the environment
- The ``render()`` method returns a list of object dictionaries
- Objects are created using classes from ``mug.configurations.object_contexts``
- Coordinates are typically normalized to 0-1 range (relative to canvas size)
- Each object needs a unique ``uuid`` identifier

Step 2: Create the Experiment Script
-------------------------------------

Now create the main experiment file ``mountain_car_experiment.py``:

.. code-block:: python

    from __future__ import annotations

    import eventlet

    eventlet.monkey_patch()

    from mug.server import app
    from mug.scenes import stager, static_scene, gym_scene
    from mug.configurations import experiment_config, configuration_constants

    # Define action constants
    LEFT_ACCELERATION = 0
    NOOP_ACTION = 1
    RIGHT_ACCELERATION = 2

    # Map keyboard keys to actions
    action_mapping = {
        "ArrowLeft": LEFT_ACCELERATION,
        "ArrowRight": RIGHT_ACCELERATION,
    }

    # Scene 1: Welcome screen
    start_scene = (
        static_scene.StartScene()
        .scene(scene_id="welcome")
        .display(
            scene_header="Welcome to Mountain Car!",
            scene_body="You'll control a car trying to reach the flag on the hill. Use the arrow keys to accelerate left or right."
        )
    )

    # Scene 2: Game scene
    mountain_car_scene = (
        gym_scene.GymScene()
        .scene(scene_id="mountain_car_game")
        .policies(
            policy_mapping={"human": configuration_constants.PolicyTypes.Human}
        )
        .rendering(
            fps=30,
            game_width=600,
            game_height=400,
        )
        .gameplay(
            default_action=NOOP_ACTION,
            action_mapping=action_mapping,
            num_episodes=5,
            max_steps=200,
            input_mode=configuration_constants.InputModes.PressedKeys,
        )
        .content(
            scene_header="Mountain Car",
            scene_body="<center><p>Loading Python environment...</p></center>",
            in_game_scene_body="<center><p>Use arrow keys to reach the flag!</p></center>",
        )
        .runtime(
            run_through_pyodide=True,
            environment_initialization_code_filepath="mountain_car_rgb_env.py",
        )
    )

    # Scene 3: Thank you screen
    end_scene = (
        static_scene.EndScene()
        .scene(scene_id="thanks")
        .display(
            scene_header="Thanks for participating!",
            scene_body="You've completed the experiment."
        )
    )

    # Sequence the scenes
    experiment_stager = stager.Stager(
        scenes=[start_scene, mountain_car_scene, end_scene]
    )

    if __name__ == "__main__":
        config = (
            experiment_config.ExperimentConfig()
            .experiment(stager=experiment_stager, experiment_id="mountain_car_demo")
            .hosting(port=8000, host="0.0.0.0")
        )
        app.run(config)

**Key Points:**

- **Eventlet monkey patching** must be at the top before other imports
- **Scenes** define each stage: welcome, game, thank you
- **Stager** sequences scenes and manages progression
- **Pyodide** runs the environment in the browser (``run_through_pyodide=True``)
- **Policy mapping** assigns "human" control to the participant

Step 3: Run Your Experiment
----------------------------

Start the server:

.. code-block:: bash

    python mountain_car_experiment.py

Open your browser to ``http://localhost:8000`` and play!

What Just Happened?
-------------------

You've created a complete browser-based experiment with:

1. **Custom rendering**: Objects (Circle, Line, Polygon) define the visuals
2. **Client-side execution**: The environment runs in the participant's browser via Pyodide
3. **Scene flow**: Welcome → Game → Thank you
4. **Human control**: Arrow keys map to environment actions

Quick Customizations
--------------------

**Change the number of episodes:**

.. code-block:: python

    .gameplay(
        num_episodes=10,  # Play 10 episodes
        # ...
    )

**Change keyboard controls:**

.. code-block:: python

    action_mapping = {
        "a": LEFT_ACCELERATION,
        "d": RIGHT_ACCELERATION,
    }

**Change colors:**

.. code-block:: python

    car = Circle(
        uuid="car",
        color="#FF0000",  # Red car
        x=car_x,
        y=car_y,
        radius=16,
    )

Next Steps
----------

Now that you've built your first experiment:

- **Learn more about rendering**: :doc:`core_concepts/object_contexts` explains all available object types
- **Understand the architecture**: :doc:`core_concepts/index` covers scenes, stagers, and more
- **See more examples**: :doc:`examples/index` shows complete experiments
- **Add AI opponents**: :doc:`guides/policies/ai_policies` for human-AI experiments

Run Built-in Examples
----------------------

MUG includes several complete examples you can try:

.. code-block:: bash

    # Mountain Car (similar to what we built)
    python -m mug.examples.mountain_car.mountain_car_experiment

    # Slime Volleyball (human vs AI)
    python -m mug.examples.slime_volleyball.human_ai_server

    # Overcooked (two-player cooperation)
    python -m mug.examples.cogrid.overcooked_human_human_server_side

Troubleshooting
---------------

**"Cannot import eventlet"**

Install server dependencies:

.. code-block:: bash

    pip install multi-user-gymnasium[server]

**"File not found: mountain_car_rgb_env.py"**

Make sure the file path in ``.runtime()`` is relative to where you run the script, or use an absolute path.

**Browser shows blank page or loading forever**

1. Check browser console (F12 → Console) for errors
2. First load takes 30-60 seconds to download Pyodide packages
3. Make sure you have a stable internet connection

**Port already in use**

Change the port:

.. code-block:: python

    .hosting(port=8080, host="0.0.0.0")

Get Help
--------

- **Core Concepts**: :doc:`core_concepts/index` for detailed explanations
- **Full Documentation**: Browse all docs at the main page
- **GitHub Issues**: Report bugs at `github.com/chasemcd/interactive-gym/issues <https://github.com/chasemcd/interactive-gym/issues>`_
- **Examples**: Check ``mug/examples/`` in the repository
