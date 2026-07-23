"""MountainCar for the browser (Pyodide) stepping mode: the study side.

This is study code, not platform code. It supplies the same environment, key
bindings, and drawing as the native server-side spec, but for the browser
execution mode: the environment runs in the participant browser through Pyodide,
and the ``source_bundle`` is the Python the browser runs. The bundle is
self-contained -- it imports only ``gymnasium`` (installed by ``requires``) and
defines two names the platform client drives: ``make_env()`` and ``draw()``.

Run the browser demo with ``uvicorn examples.mountain_car.browser_demo:app``.
"""

from __future__ import annotations

from mug.game.browser import BrowserGameSpec

# The Python the client runs in Pyodide. It defines ``make_env`` (the environment
# factory) and ``draw`` (the per-frame surface commands in relative coordinates),
# the browser twin of the server-side factory and render function.
_SOURCE_BUNDLE = '''
import math

import gymnasium

_MIN_POSITION = -1.2
_MAX_POSITION = 0.6
_GOAL_POSITION = 0.5


def make_env():
    return gymnasium.make("MountainCar-v0")


def _height(position):
    return math.sin(3 * position) * 0.45 + 0.55


def _screen_x(position):
    return (position - _MIN_POSITION) / (_MAX_POSITION - _MIN_POSITION)


def _screen_y(height):
    return 1.0 - height


def draw(observation):
    position = float(observation[0])
    samples = 60
    curve = []
    for index in range(samples + 1):
        world = _MIN_POSITION + (_MAX_POSITION - _MIN_POSITION) * index / samples
        curve.append([_screen_x(world), _screen_y(_height(world))])
    ground = [[0.0, 1.0]] + curve + [[1.0, 1.0]]

    goal_x = _screen_x(_GOAL_POSITION)
    goal_y = _screen_y(_height(_GOAL_POSITION))
    car_x = _screen_x(position)
    car_y = _screen_y(_height(position))
    return [
        {"op": "polygon", "id": "ground", "relative": True, "color": "#964b00",
         "points": ground},
        {"op": "line", "id": "flag-pole", "relative": True, "color": "#000000",
         "points": [[goal_x, goal_y], [goal_x, goal_y - 0.18]]},
        {"op": "polygon", "id": "flag", "relative": True, "color": "#00a000",
         "points": [[goal_x, goal_y - 0.18], [goal_x + 0.06, goal_y - 0.14],
                    [goal_x, goal_y - 0.10]]},
        {"op": "circle", "id": "car", "relative": True, "color": "#101010",
         "x": car_x, "y": car_y - 0.03, "radius": 0.03},
    ]
'''


def mountain_car_browser_spec() -> BrowserGameSpec:
    """Return the browser-execution specification for the MountainCar demo."""
    return BrowserGameSpec(
        channel_key="mountain-car",
        source_bundle=_SOURCE_BUNDLE,
        requires=("gymnasium==0.29.1",),
        action_bindings={"ArrowLeft": 0, "ArrowRight": 2},
        default_action=1,
        seed=42,
        hooks=("snapshot-restore", "state-hash"),
        fps=30,
        max_steps=200,
    )
