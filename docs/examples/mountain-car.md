# Mountain Car

<div align="center">
  <video src="../assets/images/mountain_car_example.webm" autoplay loop muted playsinline width="600">
    Your browser does not support the video tag.
  </video>
</div>

A single-player Pyodide experiment where a participant controls a car trying to reach a flag on top of a hill. The environment is Gymnasium's `MountainCar-v0` with `render()` reimplemented against MUG's Surface API so it can run in the browser.

**Source:** [`examples/mountain_car/mountain_car_experiment.py`](https://github.com/chasemcd/interactive-gym/blob/main/examples/mountain_car/mountain_car_experiment.py)

See [Examples](index.md) for install and run instructions. This example uses [Gymnasium](https://gymnasium.farama.org/), which we install in the user's browser (Gymnasium also ships with MUG, so no separate local install is needed).

## File Structure

```text
mountain_car/
├── mountain_car_experiment.py    # Main experiment configuration
└── mountain_car_env.py       # Environment with custom rendering
```

## Environment (`mountain_car_env.py`)

The standard `MountainCarEnv` uses pygame, which cannot run in Pyodide. This file subclasses it and replaces `render()` with Surface draw calls.

```python
from __future__ import annotations

import numpy as np
from gymnasium.envs.classic_control.mountain_car import \
    MountainCarEnv as _BaseMountainCarEnv

from mug.rendering import Surface
from mug.configurations.configuration_constants import \
PolicyTypes, InputModes


class MountainCarEnv(_BaseMountainCarEnv):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # The Surface is the drawing target. Width/height are the canvas pixel
        # dimensions, but with relative=True on each draw call we'll address it
        # as a 0-1 coordinate space.
        self.surface = Surface(width=600, height=400)

    def reset(self, *args, **kwargs):
        obs, info = super().reset(*args, **kwargs)
        # Clear any state the Surface tracks across frames (persistent object
        # cache, etc.) so the new episode starts from a clean slate.
        self.surface.reset()
        return obs, info

    def step(self, actions: dict[str, int | float]):
        # MUG passes actions as a dict keyed by agent ID. There's only one
        # agent here ("human"), so unwrap it and forward to the base env.
        assert "human" in actions, "Must be using human agent ID!"
        action = actions["human"]
        return super().step(action)

    def render(self):
        # MUG requests rendering with render_mode="mug"; guard so misuse fails
        # loudly rather than returning an unexpected type.
        assert self.render_mode == "mug"

        # The environment's y=0 is the hill bottom, but we want the drawn
        # ground line to sit just above the canvas bottom — y_offset lifts
        # everything up so the car never clips the edge.
        y_offset = 0.05
        min_pos, max_pos = (
            env.unwrapped.min_position,
            env.unwrapped.max_position,
        )
        env_ = self.unwrapped

        # Map env x (in [min_pos, max_pos]) onto the 0-1 canvas x-axis.
        def _normalize_x(vals, minn=min_pos, maxx=max_pos):
            vals -= minn
            return vals / (maxx - minn)

        # --- Ground line ---
        # Sample 100 points along the hill curve. env_._height() is the sinusoid
        # the env uses for its physics; we flip y (1 - ...) because canvas y
        # grows downward while env y grows upward.
        xs = np.linspace(min_pos, max_pos, 100)
        ys = 1 - env_._height(xs) + y_offset
        xs = _normalize_x(xs)
        xys = list(zip(xs, ys))
        self.surface.line(
            id="ground_line",
            color="#964B00",
            points=xys,
            width=1,
            fill_below=True,    # fills the area beneath the line — the "earth"
            persistent=True,    # terrain never changes; send once, not per frame
            relative=True,      # interpret points as 0-1 fractions of the canvas
        )

        # --- Car ---
        # Draw the car at its current position on the hill curve. The car is
        # transient (persistent=False by default), so it gets retransmitted
        # every frame as it moves.
        car_x = env_.state[0]
        car_y = 1 - env_._height(car_x) + y_offset
        car_x = _normalize_x(car_x)
        self.surface.circle(
            id="car",
            color="#000000",
            x=car_x,
            y=car_y,
            # Radius is in relative units too, so convert 16 pixels to the
            # fraction of the canvas that represents.
            radius=16 / max(self.surface.width, self.surface.height),
            relative=True,
        )

        # --- Flag pole ---
        # Vertical line from the hill surface at the goal up to near the top.
        flagx = env_.goal_position
        flagy1 = 1 - env_._height(env_.goal_position)   # bottom of pole (on ground)
        flagy2 = 0.05                                   # top of pole
        flagx = _normalize_x(flagx)
        self.surface.line(
            id="flag_line",
            color="#000000",
            points=[(flagx, flagy1), (flagx, flagy2)],
            width=3,
            persistent=True,    # goal position doesn't move
            relative=True,
        )

        # --- Flag ---
        # Triangle pinned to the top of the pole, pointing left.
        self.surface.polygon(
            id="flag",
            color="#00FF00",
            points=[
                (flagx, flagy1),                 # anchor at pole
                (flagx, flagy1 + 0.03),          # down along pole
                (flagx - 0.02, flagy1 + 0.015),  # tip of the flag
            ],
            persistent=True,
            relative=True,
        )

        # commit() returns a RenderPacket containing only objects that are
        # new or changed since the last frame (persistent objects are skipped
        # on subsequent calls). to_dict() serializes it to the wire format
        # the browser-side renderer consumes.
        return self.surface.commit().to_dict()


# Pyodide loads this module and looks for a top-level `env` variable.
env = MountainCarEnv(render_mode="mug")
```

## Experiment (`mountain_car_experiment.py`)

Three scenes are sequenced by a `Stager`:

```python
start_scene = static_scene.StartScene()
    .scene(scene_id="mountain_car_start_scene")
    .display(
        scene_header="Welcome!",
        scene_body=(
            "<center>"
            "This is a demonstration of "
            "how to set up a basic experiment "
            "in the classic Mountain Car environment.",
            "</center>",
        ),
    )

mountain_car_scene = (
    gym_scene.GymScene()
    .scene(scene_id="mountain_car_scene")
    .policies(policy_mapping={"human": PolicyTypes.Human})
    .rendering(fps=30, game_width=600, game_height=400)
    .gameplay(
        default_action=NOOP_ACTION,  # When no key is pressed
        action_mapping={"ArrowLeft": LEFT_ACCELERATION, "ArrowRight": RIGHT_ACCELERATION},
        num_episodes=1,
        max_steps=200,
        input_mode=InputModes.PressedKeys,
    )
    .content(
        scene_header="Mountain Car",

        # This is what displays before the game starts. We can use
        # native HTML here, as in other displays.
        scene_body="<center><p>"
        "Get ready to play!"
        "</p></center>",
    )
    .runtime(
        environment_initialization_code_filepath="examples/mountain_car/mountain_car_env.py",
        packages_to_install=[
            "gymnasium",
        ],
    )
)

end_scene = static_scene.EndScene()
    .scene(scene_id="mountain_car_end_scene")
    .display(
        scene_header="Thanks for playing!",
        scene_body=(
            "For more information on MUG or to contact us with any questions, "
            "visit multi-user-gymnasium.readthedocs.io!"
        ),
    )



stager = stager.Stager(
    scenes=[
        start_scene,
        mountain_car_scene,
        end_scene,
    ]
)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--port", type=int, default=5702, help="Port number to listen on"
    )
    args = parser.parse_args()

    experiment_config = (
        experiment_config.ExperimentConfig()
        .experiment(stager=stager, experiment_id="mountain_car_demo")
        .hosting(port=5702, host="0.0.0.0")
    )

    app.run(experiment_config)
```
