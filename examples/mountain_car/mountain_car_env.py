"""
MountainCar renders an environment using libraries that aren't
pure python. Here, we override the rgb_array rendering to
use pure python in a way that will allow it to be run via Pyodide.
"""

from __future__ import annotations

import numpy as np
from gymnasium.envs.classic_control.mountain_car import \
    MountainCarEnv as _BaseMountainCarEnv

from mug.rendering import Surface


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
                (flagx, flagy1),               # anchor at pole
                (flagx, flagy1 + 0.03),        # down along pole
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


env = MountainCarEnv(render_mode="mug")
env
