"""The seams the game loops share: the seat action source and the env steps.

Both the single-seat facade (``mug.game.runtime.run_episode``) and the core
multi-seat loop (``mug.game.multiseat.run_multiseat_episode``) read one action from
a seat each frame and step an environment. These seams live here, below both loops,
so the facade can build on the core loop while both still depend only on the seam,
never on each other.

A ``SeatActionSource`` is what the loop reads each frame to get one seat's next
action: a person's ``InputState`` maps held keys, a controller decides from the
observation, and a scheduled seat holds the latest decided action. A
``SteppableEnv`` is the minimal single-seat environment the facade steps; the
multi-seat loop lifts it into its own seam with ``solo_env``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from mug.game.env import StepResult

# Return one instant in the canonical wire form. The loop reads it once per frame
# to stamp the recorded transition, so the caller injects the clock (no wall time).
Clock = Callable[[], str]


class SeatActionSource(Protocol):
    """What a loop reads each frame to get one seat's next action.

    A human seat's ``InputState`` maps the held keys and ignores the observation; a
    controller (API-05) decides from the observation; a scheduled seat holds the
    latest decided action. All satisfy this seam, so a loop drives a bot exactly as
    it drives a person -- the source of the action is the only difference.
    """

    def decide(self, observation: object) -> int: ...


class SteppableEnv(Protocol):
    """The minimal single-seat environment the facade steps: reset and step one.

    ``GymEnv`` satisfies it, and so does any study environment the facade drives
    directly. Typing to the seam (not to ``GymEnv``) lets a runtime pass a richer
    environment -- one an LLM controller also reads for its text view -- to the same
    facade without a cast.
    """

    def reset(self) -> StepResult: ...
    def step(self, action: int) -> StepResult: ...


__all__ = ["Clock", "SeatActionSource", "SteppableEnv"]
