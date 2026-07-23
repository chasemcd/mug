"""The MountainCar study example: its spec, its environment, and its drawing.

MountainCar is study code under ``examples/``, not platform code. These tests
check the example supplies a well-formed ``GameSpec``, builds a stepping
environment, and draws the hill, the goal flag, and the car onto a surface.
"""

from __future__ import annotations

from typing import cast

from examples.mountain_car.native_env import mountain_car_spec, render
from mug.game.env import GymEnv, StepResult
from mug.game.surface import Surface


def test_the_spec_names_the_environment_and_its_bindings() -> None:
    """The spec carries the channel, the key bindings, and the no-input default."""
    spec = mountain_car_spec()
    assert spec.channel_key == "mountain-car"
    assert spec.action_bindings == {"ArrowLeft": 0, "ArrowRight": 2}
    assert spec.default_action == 1


def test_the_environment_resets_and_steps() -> None:
    """The factory builds a MountainCar that returns a two-value observation."""
    env = GymEnv(mountain_car_spec().make_env, seed=0)
    start = env.reset()
    observation = cast("list[float]", start.observation)
    assert len(observation) == 2
    result = env.step(2)
    assert result.reward == -1.0


def test_the_render_draws_the_hill_the_flag_and_the_car() -> None:
    """The study render draws the ground, the flag, its pole, and the car."""
    surface = Surface()
    state = StepResult(
        observation=[-0.5, 0.0], reward=0.0, terminated=False, truncated=False
    )
    render(surface, state)
    by_id = {command.id: command for command in surface.commands()}
    assert by_id["ground"].op == "polygon"
    assert by_id["flag"].op == "polygon"
    assert by_id["flag-pole"].op == "line"
    assert by_id["car"].op == "circle"
    assert by_id["car"].relative is True
