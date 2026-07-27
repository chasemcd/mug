"""A generic Gymnasium environment adapter for the stepping loop.

The adapter wraps any Gymnasium environment behind a small, typed surface: it
resets, it steps one action, and it returns the observation, the reward, and the
terminal and truncation flags, and the environment's own per-frame metrics. It
holds no environment-specific logic. The
environment identity, its action semantics, and its drawing all live with the
study that supplies them (see ``mug.game.spec.GameSpec``), never in the platform.

Gymnasium is an optional dependency (the ``game`` extra); this module imports it,
so it loads only where the extra is installed.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Any, NamedTuple, cast

import gymnasium
import numpy as np

# A study supplies a factory that builds its environment; the adapter never names
# an environment itself.
EnvFactory = Callable[[], "gymnasium.Env[Any, Any]"]


# The metrics an environment reports for a frame when it reports none. It is
# immutable and shared, so a default can never be written into by one caller.
NO_INFO: Mapping[str, Any] = MappingProxyType({})


class StepResult(NamedTuple):
    """The outcome of one environment step: a json-able observation and flags.

    ``info`` is the environment's own per-frame metrics. A study's dependent
    variable often lives there, so the loop records it rather than drop it.
    """

    observation: Any
    reward: float
    terminated: bool
    truncated: bool
    info: Mapping[str, Any] = NO_INFO


def _info(value: Any) -> Mapping[str, Any]:
    """Normalize an environment's info mapping to json-able data, or to nothing."""
    if not isinstance(value, dict) or not value:
        return NO_INFO
    return {
        str(key): _jsonable(item)
        for key, item in cast("dict[Any, Any]", value).items()
    }


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
        observation, info = self._env.reset(seed=self._seed)
        return StepResult(_jsonable(observation), 0.0, False, False, _info(info))

    def step(self, action: int) -> StepResult:
        """Step one action and return the observation, reward, flags, and metrics."""
        observation, reward, terminated, truncated, info = self._env.step(action)
        return StepResult(
            _jsonable(observation),
            float(reward),
            bool(terminated),
            bool(truncated),
            _info(info),
        )
