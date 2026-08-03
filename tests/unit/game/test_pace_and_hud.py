"""How often a seat decides, and what the participant is told while they play.

Two capabilities the platform was missing, and one failure each was found by:

- **the frame skip.** A partner asked for an action thirty times a second changes
  its mind faster than a person can read it. A study says how often its partner
  decides, and what the seat does on the frames between -- which is not a detail:
  a policy trained to act once per environment step plays a different policy when
  its last action is repeated four more times.
- **the status line.** The score and the clock were on every screen of the legacy
  study and on none of this one. They are drawn onto the same surface as the game,
  so what the participant was being told is in the render packet, in the record,
  and in a replay.

These modules use ASD-STE100 Simplified Technical English.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

import pytest

from mug.casting import OnnxPolicy
from mug.casting.types import OnnxPreprocessing
from mug.game.controllers import HeuristicController, OnnxController, Pace
from mug.game.env import StepResult
from mug.game.runtime import render_packet
from mug.game.spec import HudFn
from mug.game.surface import Surface
from mug.game.types import SurfaceCommand

_IDLE = 6


def _counting() -> tuple[list[int], Callable[[object], int]]:
    """Return the frames a policy was asked on, and the policy that records them."""
    asked: list[int] = []

    def policy(observation: object) -> int:
        frame = int(cast("int", observation))
        asked.append(frame)
        return frame + 100

    return asked, policy


def test_a_seat_decides_on_the_first_frame_and_then_every_nth() -> None:
    """The run opens on a chosen action, not on a default nobody chose."""
    asked, policy = _counting()
    seat = HeuristicController(policy, decide_every=5)

    for frame in range(11):
        seat.decide(frame)

    assert asked == [0, 5, 10], "the seat decided on the wrong frames"


def test_a_seat_that_names_no_idle_action_holds_what_it_decided() -> None:
    """Holding is right for a seat steering something that keeps moving."""
    _asked, policy = _counting()
    seat = HeuristicController(policy, decide_every=3)

    played = [seat.decide(frame) for frame in range(6)]

    assert played == [100, 100, 100, 103, 103, 103]


def test_a_seat_that_names_an_idle_action_does_that_between_decisions() -> None:
    """A grid seat idles, because repeating one step of a walk walks four squares.

    This is the difference that made the trained Overcooked partner useless: asked
    to step towards a pot and then repeated four times, it arrived past it.
    """
    _asked, policy = _counting()
    seat = HeuristicController(policy, decide_every=3, between=_IDLE)

    played = [seat.decide(frame) for frame in range(6)]

    assert played == [100, _IDLE, _IDLE, 103, _IDLE, _IDLE]


def test_a_paced_network_is_scored_only_on_the_frames_it_decides_on() -> None:
    """The frame skip paces the inference too, which is what makes a big model pay."""
    scored: list[int] = []

    def infer(observation: object) -> list[float]:
        scored.append(int(cast("int", observation)))
        return [0.0, 9.0, 0.0]

    seat = OnnxController(
        OnnxPolicy(
            policy_ref="paced@1",
            preprocessing=OnnxPreprocessing(transform="flatten"),
            selection_mode="argmax",
        ),
        infer,
        decide_every=4,
        between=_IDLE,
    )

    played = [seat.decide(frame) for frame in range(8)]

    assert scored == [0, 4], "the network ran on a frame the seat was not deciding on"
    assert played == [1, _IDLE, _IDLE, _IDLE, 1, _IDLE, _IDLE, _IDLE]


def test_a_pace_of_less_than_one_frame_is_refused() -> None:
    """A seat decides at least once every frame; zero is a study's mistake."""
    with pytest.raises(ValueError, match="at least once"):
        Pace(0)


# -- the status line ----------------------------------------------------------


def _frame(score: int) -> StepResult:
    """Return one stepped frame carrying what the status line reads."""
    return StepResult([0.0], 0.0, False, False, {"score": score})


def _says(state: StepResult) -> str:
    """Return the status line this study writes for one frame."""
    return f"Score: {state.info['score']}"


def _board(surface: Surface, _state: StepResult) -> None:
    """Draw the game under the status line: one filled rectangle."""
    surface.rect(x=0.0, y=0.0, w=1.0, h=1.0, color="#123456", object_id="board")


def _drawn(surface: Surface, hud: HudFn | None) -> list[SurfaceCommand]:
    """Draw one frame with a status line and return the commands it produced."""
    packet = render_packet(
        surface,
        _board,
        _frame(7),
        "episode_019b6000-0000-7000-8000-00000000000a",
        "player",
        1,
        hud,
    )
    return list(packet.commands)


def test_the_status_line_a_study_writes_reaches_the_render_packet() -> None:
    """What the participant is told travels with the frame it was told on."""
    commands = _drawn(Surface(), _says)

    said = [one.text for one in commands if one.op == "text"]
    assert said == ["Score: 7"], "the status line was not drawn"


def test_the_status_line_is_drawn_over_the_game_rather_than_under_it() -> None:
    """A drawing must not be able to paint over what the participant is being told."""
    commands = _drawn(Surface(), _says)

    board = next(one for one in commands if one.id == "board")
    text = next(one for one in commands if one.op == "text")
    band = next(one for one in commands if one.op == "rect" and one.id != "board")
    assert (text.depth or 0) > (band.depth or 0) > (board.depth or 0)


def test_a_game_with_no_status_line_draws_none() -> None:
    """A study that says nothing is shown nothing, not an empty band."""
    commands = _drawn(Surface(), None)

    assert [one.op for one in commands] == ["rect"]
