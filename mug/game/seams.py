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
from typing import Any, Protocol

from mug.game.env import StepResult

# Return one instant in the canonical wire form. The loop reads it once per frame
# to stamp the recorded transition, so the caller injects the clock (no wall time).
Clock = Callable[[], str]

# What one seat is shown, when its own observation is not enough: read off the live
# environment, for that seat, once a frame.
#
# A policy decides from an observation, which is what the loop hands it. A seat that
# **plans** does not: a partner walking a kitchen needs the grid and the pots, and a
# partner on a court needs the ball's velocity. None of that is in an observation, and
# a study cannot hold the environment itself -- one study object serves every
# participant at once, so a study that kept the environment it built would hand one
# participant's kitchen to another's partner.
#
# So the loop asks. It is the same shape as an LLM seat's ``TextView``, which reads the
# environment for a seat and returns text; this returns whatever the study's own
# controller decides from.
SeatView = Callable[[Any, str], Any]


class SeatActionSource(Protocol):
    """What a loop reads each frame to get one seat's next action.

    A human seat's ``InputState`` maps the held keys and ignores the observation; a
    controller (API-05) decides from the observation; a scheduled seat holds the
    latest decided action. All satisfy this seam, so a loop drives a bot exactly as
    it drives a person -- the source of the action is the only difference.

    A source may also carry ``sees``, a ``SeatView``. With one, the loop shows it that
    view of the live environment instead of the seat's observation.
    """

    def decide(self, observation: object) -> int: ...


def what_a_seat_reads(
    env: Any, source: Any, agent_id: str, observation: Any
) -> Any:
    """Return what one seat decides from: its own view of the environment, or its
    observation.

    Every loop reads its seats through this, so a view is never honoured on one path
    and quietly dropped on another.
    """
    view = getattr(source, "sees", None)
    if view is None:
        return observation
    return view(getattr(env, "env", env), agent_id)


class SteppableEnv(Protocol):
    """The minimal single-seat environment the facade steps: reset and step one.

    ``GymEnv`` satisfies it, and so does any study environment the facade drives
    directly. Typing to the seam (not to ``GymEnv``) lets a runtime pass a richer
    environment -- one an LLM controller also reads for its text view -- to the same
    facade without a cast.
    """

    def reset(self) -> StepResult: ...
    def step(self, action: int) -> StepResult: ...


__all__ = [
    "Clock",
    "SeatActionSource",
    "SeatView",
    "SteppableEnv",
    "what_a_seat_reads",
]
