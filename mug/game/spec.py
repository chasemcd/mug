"""The study-supplied game specification: the seam the stepping loop runs.

A study supplies one ``GameSpec`` per game channel. It names the environment
factory, the per-frame render function, and the seat key bindings. The core loop
holds none of this -- it reads the spec. This keeps every environment-specific
detail (the environment identity, its action semantics, and its drawing) with the
study, not in the platform. See ``examples/mountain_car/native_env.py`` for one.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from mug.game.env import EnvFactory, StepResult
from mug.game.surface import Surface

# Draw one frame for the current step result onto the surface.
RenderFn = Callable[[Surface, StepResult], None]


@dataclass(frozen=True)
class GameSpec:
    """One game channel a study supplies: its environment, drawing, and input.

    ``action_bindings`` maps a key name to a discrete action; ``default_action``
    fills a frame with no bound key pressed. ``channel_key`` names the channel on
    the recorded transitions. ``countdown_seconds`` is the pre-roll the episode
    holds after the participant continues, so the first frames are not stepped
    while the participant is still settling in.
    """

    channel_key: str
    make_env: EnvFactory
    render: RenderFn
    action_bindings: dict[str, int]
    default_action: int
    fps: int = 30
    max_steps: int = 200
    countdown_seconds: int = 3
