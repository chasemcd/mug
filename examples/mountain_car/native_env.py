"""MountainCar for the native stepping loop: the study side of the game.

This is study code, not platform code. It supplies the environment factory, the
seat key bindings, and the per-frame drawing for the classic MountainCar control
task, bundled as one ``GameSpec``. It draws the hill, the goal flag, and the car
in relative coordinates, so the platform renderer needs no environment knowledge.
It mirrors the legacy ``examples/mountain_car`` env, ported onto the ``GameSpec``
seam of the new stack.

Run the demo with ``uvicorn examples.mountain_car.native_demo:app`` (see the
sibling module).
"""

from __future__ import annotations

import math
from typing import cast

import gymnasium

from mug.game.env import StepResult
from mug.game.spec import GameSpec
from mug.game.surface import Surface

# MountainCar-v0: discrete actions 0 = left, 1 = noop, 2 = right; the observation
# is [position, velocity]. The car reaches the goal at position >= 0.5.
_MIN_POSITION = -1.2
_MAX_POSITION = 0.6
_GOAL_POSITION = 0.5


def _height(position: float) -> float:
    """Return the hill height at a world position (the MountainCar profile)."""
    return math.sin(3 * position) * 0.45 + 0.55


def _screen_x(position: float) -> float:
    return (position - _MIN_POSITION) / (_MAX_POSITION - _MIN_POSITION)


def _screen_y(height: float) -> float:
    # The canvas y grows downward, so a taller hill maps to a smaller y.
    return 1.0 - height


def render(surface: Surface, state: StepResult) -> None:
    """Draw the hill, the goal flag, and the car for the current observation."""
    observation = cast("list[float]", state.observation)
    position = float(observation[0])

    samples = 60
    curve: list[tuple[float, float]] = []
    for index in range(samples + 1):
        world = _MIN_POSITION + (_MAX_POSITION - _MIN_POSITION) * index / samples
        curve.append((_screen_x(world), _screen_y(_height(world))))

    ground = [(0.0, 1.0), *curve, (1.0, 1.0)]
    surface.polygon(points=ground, color="#964b00", object_id="ground")

    goal_x = _screen_x(_GOAL_POSITION)
    goal_y = _screen_y(_height(_GOAL_POSITION))
    surface.line(
        points=[(goal_x, goal_y), (goal_x, goal_y - 0.18)],
        color="#000000",
        object_id="flag-pole",
    )
    surface.polygon(
        points=[
            (goal_x, goal_y - 0.18),
            (goal_x + 0.06, goal_y - 0.14),
            (goal_x, goal_y - 0.10),
        ],
        color="#00a000",
        object_id="flag",
    )

    car_x = _screen_x(position)
    car_y = _screen_y(_height(position))
    surface.circle(
        x=car_x, y=car_y - 0.03, radius=0.03, color="#101010", object_id="car"
    )


def mountain_car_spec() -> GameSpec:
    """Return the game specification for the MountainCar demo activity."""
    return GameSpec(
        channel_key="mountain-car",
        make_env=lambda: gymnasium.make("MountainCar-v0"),
        render=render,
        action_bindings={"ArrowLeft": 0, "ArrowRight": 2},
        default_action=1,
        fps=30,
        max_steps=200,
    )
