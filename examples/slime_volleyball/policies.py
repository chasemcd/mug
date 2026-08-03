"""The partners a person can play against: a heuristic, and an exported network.

Both satisfy the one seam the game loop reads -- ``decide(observation)`` returns
one discrete action. The platform holds that seam and nothing else; what an
observation means, and how it becomes an action, is the study's own business and
lives here.
"""

from __future__ import annotations

from typing import Any

from examples.slime_volleyball.env import (
    LEFT,
    NOOP,
    RIGHT,
    UP,
    UPLEFT,
    UPRIGHT,
    the_court,
)
from mug.casting import OnnxPolicy
from mug.casting.types import OnnxPreprocessing
from mug.game.controllers import HeuristicController, OnnxController


class BallChaser:
    """Chase where the ball is going, and jump into a ball that is dropping close.

    The court spans x in [-24, 24] with the fence at x = 0, and each slime keeps
    to its own half. The policy leads the ball a little so that it meets the ball
    rather than trails it, and it returns to the middle of its half when the ball
    is on the other side.
    """

    # Where to wait when the ball is not coming, in world units.
    HOME_X = 12.0
    # How far ahead of the ball to aim, in seconds of its current speed.
    LOOKAHEAD = 0.15
    # How close to the target counts as arrived, so the slime does not shake.
    DEADZONE = 0.7
    # How near the ball must be, and how low it must have fallen, before jumping.
    JUMP_RANGE = 3.0
    JUMP_HEIGHT = 6.0

    def decide(self, court: dict[str, Any], seat: str) -> int:
        """Return the action for one slime, from the court it is standing on.

        The court is the same description the drawing reads, so what the partner
        decided from is in the run beside what the participant saw.
        """
        if not court:
            return NOOP
        on_the_right = "right" in str(seat)
        side = 1.0 if on_the_right else -1.0

        mine = float(court["right" if on_the_right else "left"][0])
        ball_x, ball_y = (float(one) for one in court["ball"])
        ball_vx, ball_vy = (float(one) for one in court["ball_speed"])

        # Lead the ball, so the slime arrives with it rather than behind it.
        predicted = ball_x + ball_vx * self.LOOKAHEAD
        coming = predicted * side > 0
        target = predicted if coming else self.HOME_X * side

        difference = target - mine
        move = NOOP
        if difference > self.DEADZONE:
            move = RIGHT
        elif difference < -self.DEADZONE:
            move = LEFT

        close = abs(ball_x - mine) < self.JUMP_RANGE
        dropping = ball_vy < 0 and ball_y < self.JUMP_HEIGHT
        if coming and close and dropping:
            if move == RIGHT:
                return UPRIGHT
            if move == LEFT:
                return UPLEFT
            return UP
        return move


def ball_chaser(*, decide_every: int = 1) -> HeuristicController:
    """Return the heuristic partner, on the loop's own seat seam.

    ``decide_every`` is the frame skip. It defaults to one, and a court is the case
    where that is right: the slime holds a direction until it decides otherwise, so
    a paced seat that let go between decisions would stop mid-court.

    It names ``sees``, because where to stand is decided from where the ball is going
    and a velocity is not in an observation.
    """
    chaser = BallChaser()
    return HeuristicController(
        lambda seen: chaser.decide(*seen),
        decide_every=decide_every,
        sees=the_court,
    )


def exported_partner(
    model_path: str,
    *,
    policy_ref: str = "slimevb-policy@1",
    input_name: str = "input",
    output_name: str = "logits",
    decide_every: int = 1,
) -> OnnxController:
    """Return a partner that runs an exported network from ``model_path``.

    The inference is the study's, because the observation shape and the
    preprocessing belong to the environment. The platform owns only the declared
    action selection, which is why ``OnnxPolicy`` is a record rather than code:
    the study says ``argmax``, and what argmax means is not the study's to change.

    ``decide_every`` is the frame skip: how many frames pass between one decision
    and the next, with the chosen action held between. A court wants one, because
    letting go of a direction is itself a decision.

    It needs ``onnxruntime``: ``uv pip install onnxruntime``.
    """
    policy = OnnxPolicy(
        policy_ref=policy_ref,
        preprocessing=OnnxPreprocessing(transform="flatten"),
        selection_mode="argmax",
    )

    def infer(observation: Any) -> list[float]:
        import numpy
        import onnxruntime

        flat = numpy.asarray(observation, dtype=numpy.float32).reshape(1, -1)
        session = _session(model_path, onnxruntime)
        scores = session.run([output_name], {input_name: flat})[0]
        return [float(one) for one in scores[0]]

    return OnnxController(policy, infer, decide_every=decide_every)


_SESSIONS: dict[str, Any] = {}


def _session(model_path: str, runtime: Any) -> Any:
    """Return the inference session for one model, loaded once."""
    if model_path not in _SESSIONS:
        _SESSIONS[model_path] = runtime.InferenceSession(model_path)
    return _SESSIONS[model_path]


__all__ = ["BallChaser", "ball_chaser", "exported_partner"]
