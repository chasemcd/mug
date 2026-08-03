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
from mug.game.keys import Bindings
from mug.game.surface import Surface

# Draw one frame for the current step result onto the surface.
RenderFn = Callable[[Surface, StepResult], None]

# Say, in one line, what a participant needs to know while they play: the score
# they have, the time they have left, what they are carrying. The platform draws
# it; the study says only what it reads.
HudFn = Callable[[StepResult], str]


@dataclass(frozen=True)
class GameSpec:
    """One game channel a study supplies: its environment, drawing, and input.

    ``action_bindings`` maps a key -- or a **sequence of keys held together**, a
    chord -- to a discrete action; ``default_action``
    fills a frame with no bound key pressed. ``channel_key`` names the channel on
    the recorded transitions. ``countdown_seconds`` is the pre-roll the episode
    holds after the participant continues, so the first frames are not stepped
    while the participant is still settling in.

    ``input_mode`` says how long a press lasts: ``pressed_keys`` acts on every
    frame a key is held (a game of continuous control), ``single_keystroke`` acts
    once per press (a game on a grid). See ``mug.game.runtime.InputState``.

    ``hud`` is the line a participant reads while they play. It is drawn onto the
    same surface as the game, so it is in the render packet, in the record, and in
    a replay: what the participant was told is part of what happened to them.
    """

    channel_key: str
    make_env: EnvFactory
    render: RenderFn
    action_bindings: Bindings
    default_action: int
    fps: int = 30
    max_steps: int = 200
    countdown_seconds: int = 3
    input_mode: str = "pressed_keys"
    hud: HudFn | None = None
