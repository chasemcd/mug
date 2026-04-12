# Mountain Car

The Mountain Car example demonstrates how to create a single-player Pyodide experiment with custom rendering. It's the perfect starting point for learning MUG.

## Overview

In this experiment, participants control a car trying to reach a flag on top of a hill. The environment runs entirely in the participant's browser using Pyodide, with no server-side computation.

**What you'll learn:**

- Setting up browser-side execution
- Converting RGB array environments to Surface-based rendering
- Configuring keyboard controls
- Creating a complete three-scene experiment

![Mountain Car gameplay](https://raw.githubusercontent.com/chasemcd/interactive-gym/main/docs/_static/mountain_car_demo.gif)

## Features Demonstrated

| Feature | Details |
|---------|---------|
| **Execution Mode** | Pyodide (client-side) |
| **Players** | Single human |
| **Environment** | Gymnasium MountainCar-v0 with custom rendering |
| **Rendering** | Surface API (circle, line, polygon) |
| **Input** | Arrow keys (left/right acceleration) |
| **Complexity** | Beginner-friendly |

## Prerequisites

1. Clone the MUG repository and install with server dependencies:

    ```bash
    git clone https://github.com/chasemcd/interactive-gym.git
    cd interactive-gym
    pip install -e .[server]
    ```

2. No additional dependencies required—this example uses only Gymnasium, which is included with MUG.

## Running the Example

From the repository root, run as a module:

```bash
python -m examples.mountain_car.mountain_car_experiment
```

Then:

1. **Open your browser** to http://localhost:5702

2. **Play the game**:

    - Use arrow keys to accelerate left/right
    - Build momentum to reach the flag
    - Complete 5 episodes

## File Structure

```text
mountain_car/
├── mountain_car_experiment.py    # Main experiment configuration
└── mountain_car_rgb_env.py       # Environment with custom rendering
```

## Code Walkthrough

### Main Experiment File

**mountain_car_experiment.py** sets up the complete experiment flow.

**1. Eventlet Monkey Patching**

All MUG experiments must start with:

```python
from __future__ import annotations
import eventlet
eventlet.monkey_patch()
```

This enables asynchronous networking for the Flask server.

**2. Action Configuration**

Define the action space and keyboard mapping:

```python
LEFT_ACCELERATION = 0
NOOP_ACTION = 1
RIGHT_ACCELERATION = 2

action_mapping = {
    "ArrowLeft": LEFT_ACCELERATION,
    "ArrowRight": RIGHT_ACCELERATION,
}
```

Actions map JavaScript key events to Gymnasium action integers.

**3. Policy Mapping**

Specify that a human controls the environment:

```python
from mug.configurations import configuration_constants

POLICY_MAPPING = {
    "human": configuration_constants.PolicyTypes.Human,
}
```

**4. Start Scene**

Create a welcome screen:

```python
from mug.scenes import static_scene

start_scene = (
    static_scene.StartScene()
    .scene(
        scene_id="mountain_car_start_scene",
        experiment_config={},
        should_export_metadata=True,
    )
    .display(
        scene_header="Welcome",
        scene_body=(
            "Welcome to the Mountain Car experiment! This is a demonstration of "
            "how to set up a basic experiment with an environment that renders "
            "via an RGB image."
        ),
    )
)
```

**5. Game Scene**

Configure the main gameplay scene:

```python
from mug.scenes import gym_scene

mountain_car_scene = (
    gym_scene.GymScene()
    .scene(scene_id="mountain_car_scene", experiment_config={})
    .policies(policy_mapping=POLICY_MAPPING)
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
        in_game_scene_body="""
            <center>
            <p>Use the arrow keys to move the "car" (ball) up the hill!</p>
            </center>
        """,
    )
    .runtime(
        run_through_pyodide=True,
        environment_initialization_code_filepath=(
            "examples/mountain_car/mountain_car_rgb_env.py"
        ),
    )
)
```

Key configuration points:

- **Browser-side execution**: The environment runs directly in the participant's browser
- **Environment file**: Path to the custom environment implementation
- **Input mode**: `PressedKeys` means actions are sent while keys are held down
- **Episodes**: Participant plays 5 rounds with max 200 steps each

**6. End Scene**

Thank you page:

```python
end_scene = (
    static_scene.EndScene()
    .scene(scene_id="mountain_car_end_scene")
    .display(
        scene_header="Thanks for playing!",
        scene_body="For more information, visit interactive-gym.readthedocs.io!",
    )
)
```

**7. Stager and Server**

Combine scenes and run the server:

```python
from mug.scenes import stager
from mug.configurations import experiment_config
from mug.server import app

stager = stager.Stager(
    scenes=[start_scene, mountain_car_scene, end_scene]
)

experiment_config = (
    experiment_config.ExperimentConfig()
    .experiment(stager=stager, experiment_id="mountain_car_demo")
    .hosting(port=5702, host="0.0.0.0")
)

app.run(experiment_config)
```

### Environment Implementation

**mountain_car_rgb_env.py** extends Gymnasium's MountainCar with Surface-based rendering.

**Why Custom Rendering?**

Standard MountainCar uses pygame for rendering, which isn't pure Python and won't work in Pyodide. We override the `render()` method to use MUG's Surface API instead.

**1. Import Surface**

```python
from mug.rendering import Surface
```

**2. Extend MountainCarEnv**

```python
import numpy as np
from gymnasium.envs.classic_control.mountain_car import MountainCarEnv as _BaseMountainCarEnv

class MountainCarEnv(_BaseMountainCarEnv):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.surface = Surface(width=600, height=400)

    def reset(self, *args, **kwargs):
        obs, info = super().reset(*args, **kwargs)
        self.surface.reset()
        return obs, info

    def step(self, actions: dict[str, int | float]):
        """Accept dict actions for multi-agent format."""
        assert "human" in actions, "Must be using human agent ID!"
        action = actions["human"]
        return super().step(action)
```

MUG passes actions as dictionaries with agent IDs as keys. The Surface is created once in `__init__` and reset each episode.

**3. Custom Render Method**

```python
    def render(self):
        assert self.render_mode == "mug"

        y_offset = 0.05
        env_ = self.unwrapped
        min_pos = env_.min_position
        max_pos = env_.max_position

        def _normalize_x(vals, minn=min_pos, maxx=max_pos):
            """Convert position to 0-1 coordinate."""
            vals -= minn
            return vals / (maxx - minn)
```

The render method uses normalized 0-1 coordinates (`relative=True`) for positioning.

**4. Draw Terrain**

```python
        xs = np.linspace(min_pos, max_pos, 100)
        ys = 1 - env_._height(xs) + y_offset
        xs = _normalize_x(xs)
        xys = list(zip(xs, ys))
        self.surface.line(
            id="ground_line",
            color="#964B00",
            points=xys,
            width=1,
            fill_below=True,
            persistent=True,
            relative=True,
        )
```

Sample 100 points along the terrain curve to create a filled brown hill. `persistent=True` means the terrain is only sent on the first frame — the Surface tracks it and skips retransmission.

**5. Draw Car**

```python
        car_x = env_.state[0]
        car_y = 1 - env_._height(car_x) + y_offset
        car_x = _normalize_x(car_x)
        self.surface.circle(
            id="car",
            color="#000000",
            x=car_x,
            y=car_y,
            radius=16 / max(self.surface.width, self.surface.height),
            relative=True,
        )
```

The car is a black circle that moves each frame. The radius is converted to relative units by dividing by the max canvas dimension.

**6. Draw Flag**

```python
        flagx = env_.goal_position
        flagy1 = 1 - env_._height(env_.goal_position)
        flagy2 = 0.05
        flagx = _normalize_x(flagx)
        self.surface.line(
            id="flag_line",
            color="#000000",
            points=[(flagx, flagy1), (flagx, flagy2)],
            width=3,
            persistent=True,
            relative=True,
        )

        self.surface.polygon(
            id="flag",
            color="#00FF00",
            points=[
                (flagx, flagy1),
                (flagx, flagy1 + 0.03),
                (flagx - 0.02, flagy1 + 0.015),
            ],
            persistent=True,
            relative=True,
        )
```

The goal is shown as a green triangular flag on a black pole. Both are `persistent=True` since the flag doesn't move.

**7. Return Render Packet**

```python
        return self.surface.commit().to_dict()
```

`commit()` produces a delta-compressed render packet: only new or changed objects are included. `to_dict()` converts it to the wire format expected by the Phaser renderer.

**8. Create Environment Instance**

```python
env = MountainCarEnv(render_mode="mug")
```

The environment must be created with `render_mode="mug"` and assigned to a variable named `env`.

## How It Works

### Initialization Flow

1. **Participant loads page** -> HTML/JavaScript downloaded
2. **Pyodide initializes** -> WebAssembly Python runtime starts (~10-30s)
3. **Environment code executes** -> `mountain_car_rgb_env.py` runs in browser
4. **"Continue" button activates** -> Participant can start game
5. **Game begins** -> Episodes run locally in browser

### Game Loop

```text
Browser (Pyodide)                    Server
-----------------                    ------

1. Capture arrow key input
2. env.step({"human": action})
3. observation, reward, done, ...
4. env.render()
5. surface.commit().to_dict()
6. Render objects on canvas
7. Send data batch              ->   8. Save to CSV
(Repeat 1-7)
```

All computation happens in the browser. The server only receives and saves data.

### Data Collection

MUG automatically tracks:

- Observations
- Actions
- Rewards
- Done flags
- Timestamps
- Episode numbers

Data is saved to CSV files in the experiment's data directory.
