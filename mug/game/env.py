"""A generic Gymnasium environment adapter for the stepping loop.

The adapter wraps any Gymnasium environment behind a small, typed surface: it
resets, it steps one action, and it returns the observation, the reward, and the
terminal and truncation flags. It holds no environment-specific logic. The
environment identity, its action semantics, and its drawing all live with the
study that supplies them (see ``mug.game.spec.GameSpec``), never in the platform.

Gymnasium is an optional dependency (the ``game`` extra); this module imports it,
so it loads only where the extra is installed.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, NamedTuple, cast

import gymnasium
import numpy as np

# A study supplies a factory that builds its environment; the adapter never names
# an environment itself.
EnvFactory = Callable[[], "gymnasium.Env[Any, Any]"]


class StepResult(NamedTuple):
    """The outcome of one environment step: a json-able observation and flags."""

    observation: Any
    reward: float
    terminated: bool
    truncated: bool


def _jsonable(value: Any) -> Any:
    """Normalize an observation to json-able data (arrays and scalars included)."""
    if isinstance(value, np.ndarray):
        return cast("list[Any]", value.tolist())
    if isinstance(value, np.generic):
        return cast("Any", value.item())
    if isinstance(value, dict):
        return {
            str(key): _jsonable(item)
            for key, item in cast("dict[Any, Any]", value).items()
        }
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in cast("list[Any]", value)]
    return value


class GymEnv:
    """A Gymnasium environment stepped by the loop, built from a study factory."""

    def __init__(self, factory: EnvFactory, *, seed: int | None = None) -> None:
        self._env = factory()
        self._seed = seed

    def reset(self) -> StepResult:
        """Reset the environment and return its initial observation."""
        observation, _ = self._env.reset(seed=self._seed)
        return StepResult(_jsonable(observation), 0.0, False, False)

    def step(self, action: int) -> StepResult:
        """Step one action and return the new observation, reward, and flags."""
        observation, reward, terminated, truncated, _ = self._env.step(action)
        return StepResult(
            _jsonable(observation), float(reward), bool(terminated), bool(truncated)
        )
