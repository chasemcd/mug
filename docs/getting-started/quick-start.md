# Quick Start

Build a Mountain Car experiment where participants control a car trying to reach a flag on a hill. The environment runs in the participant's browser using Pyodide.

## Prerequisites

Install MUG with server dependencies:

```bash
pip install multi-user-gymnasium[server]
```

## Step 1: Create the Custom Environment

The standard Mountain Car uses pygame for rendering, which is not available in the browser. We override the `render()` method to use MUG's Surface API instead.

Create a file called `mountain_car_rgb_env.py`:

```python
import numpy as np
from gymnasium.envs.classic_control.mountain_car import MountainCarEnv as _BaseMountainCarEnv
from mug.rendering import Surface


class MountainCarEnv(_BaseMountainCarEnv):

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.surface = Surface(width=600, height=400)

    def step(self, actions: dict[str, int | float]):
        """Accept dict of actions (required for multi-agent format)."""
        assert "human" in actions, "Must be using human agent ID!"
        action = actions["human"]
        return super().step(action)

    def reset(self, **kwargs):
        self.surface.reset()
        return super().reset(**kwargs)

    def _to_pixel(self, pos):
        """Map environment x-position to pixel (x, y) on a 600x400 canvas."""
        min_pos = self.unwrapped.min_position
        max_pos = self.unwrapped.max_position
        px = (pos - min_pos) / (max_pos - min_pos) * 600
        py = (1.0 - self.unwrapped._height(pos)) * 350 + 20
        return px, py

    def render(self):
        assert self.render_mode == "mug"

        min_pos = self.unwrapped.min_position
        max_pos = self.unwrapped.max_position

        # persistent: ground doesn't change between frames
        xs = np.linspace(min_pos, max_pos, 100)
        ground_points = [self._to_pixel(x) for x in xs]
        self.surface.line(
            points=ground_points, color="#964B00", width=1,
            persistent=True, id="ground",
        )

        # persistent: flag pole and flag don't move
        flag_px, flag_py = self._to_pixel(self.unwrapped.goal_position)
        self.surface.line(
            points=[(flag_px, flag_py), (flag_px, 20)],
            color="#000000", width=3,
            persistent=True, id="flag_pole",
        )
        self.surface.polygon(
            points=[
                (flag_px, flag_py),
                (flag_px, flag_py - 12),
                (flag_px - 16, flag_py - 6),
            ],
            color="#00ff00",
            persistent=True, id="flag",
        )

        # transient: car moves each frame
        car_x, car_y = self._to_pixel(self.state[0])
        self.surface.circle(x=car_x, y=car_y, radius=16, color="#000000")

        return self.surface.commit()


# Environment instance loaded by Pyodide (must be named 'env')
env = MountainCarEnv(render_mode="mug")
```

The `_to_pixel` helper maps environment state to pixel coordinates on a 600x400 canvas. If you prefer normalized 0--1 coordinates, pass `relative=True` to any draw call -- see [Surface API](../core-concepts/surface-api.md) for details.

**Key Points:**

- Use `render_mode="mug"` when creating the environment
- The `render()` method calls Surface draw methods and returns `surface.commit()`
- `persistent=True` objects (ground, flag) are only sent once; transient objects (car) are sent every frame
- Surface is created once in `__init__` with pixel dimensions matching `game_width` / `game_height`

## Step 2: Create the Experiment Script

Create the main experiment file `mountain_car_experiment.py`:

```python
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
```

**Key Points:**

- **Eventlet monkey patching** must be at the top before other imports
- **Scenes** define each stage: welcome, game, thank you
- **Stager** sequences scenes and manages progression
- **Pyodide** runs the environment in the browser (`run_through_pyodide=True`)
- **Policy mapping** assigns "human" control to the participant

!!! tip

    If your experiment uses custom assets (sprites, ONNX models, images) stored outside the MUG
    package, register their directories with `static_files()`:

    ```python
    config = (
        experiment_config.ExperimentConfig()
        .experiment(stager=stager, experiment_id="my_experiment")
        .hosting(port=8000, host="0.0.0.0")
        .static_files(directories=["path/to/my/assets"])
    )
    ```

    Each directory is served at a URL matching its filesystem path. For example,
    a file at `path/to/my/assets/sprite.png` is available at
    `/path/to/my/assets/sprite.png` in the browser.

## Step 3: Run Your Experiment

Start the server:

```bash
python mountain_car_experiment.py
```

Open your browser to `http://localhost:8000` and play!

For draw method details see [Surface API](../core-concepts/surface-api.md). For an overview of the rendering pipeline see [Rendering System](../core-concepts/rendering-system.md).

## Troubleshooting

**"Cannot import eventlet"**

Install server dependencies:

```bash
pip install multi-user-gymnasium[server]
```

**"File not found: mountain_car_rgb_env.py"**

Make sure the file path in `.runtime()` is relative to where you run the script, or use an absolute path.

**Browser shows blank page or loading forever**

1. Check browser console (F12 then Console) for errors
2. First load takes 30-60 seconds to download Pyodide packages
3. Make sure you have a stable internet connection

**Port already in use**

Change the port:

```python
.hosting(port=8080, host="0.0.0.0")
```
