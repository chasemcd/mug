"""What a seat is shown, when its own observation is not enough.

A policy decides from an observation, which is what the loop hands it. A seat that
**plans** does not: a partner walking a kitchen needs the grid and the pots, and a
partner on a court needs where the ball is going. None of that is in an observation.

The study cannot hold the environment itself, and this is the reason it must not try:
one study object serves every participant at once, so a study that kept the
environment it built would hand one participant's game to another participant's
partner. The second run to start would take the first's board.

So the loop asks the seat what it wants to see, and shows it the environment **it** is
stepping. Every loop reads its seats through the one helper, so a view cannot be
honoured on one path and quietly dropped on another.

These modules use ASD-STE100 Simplified Technical English.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from mug.game.controllers import HeuristicController
from mug.game.multiseat import MultiStepResult, run_multiseat_episode
from mug.game.seams import what_a_seat_reads

_SEATS = ("mover", "watcher")


class _Board:
    """A board that counts its own steps, and holds that count on itself.

    The observation is deliberately empty, so a seat that decides correctly here can
    only have read the board.
    """

    def __init__(self, name: str = "first") -> None:
        self.name = name
        self.count = 0

    def reset(self) -> MultiStepResult:
        """Start the board."""
        self.count = 0
        return self._frame()

    def step(self, actions: Any) -> MultiStepResult:
        """Take one step, whatever was played."""
        del actions
        self.count += 1
        return self._frame()

    def _frame(self) -> MultiStepResult:
        return MultiStepResult(
            observations=dict.fromkeys(_SEATS),
            rewards=dict.fromkeys(_SEATS, 0.0),
            terminated=False,
            truncated=False,
            info={},
        )


class _Seated:
    """The board behind the loop's seam, with the environment reachable."""

    def __init__(self, board: _Board) -> None:
        self._board = board

    @property
    def env(self) -> _Board:
        """Return the environment itself, which is what a view is called on."""
        return self._board

    def reset(self) -> MultiStepResult:
        """Reset the board."""
        return self._board.reset()

    def step(self, actions: Any) -> MultiStepResult:
        """Step the board."""
        return self._board.step(actions)


def _read_the_board(env: Any, agent_id: str) -> int:
    """Return what a planning seat is shown: the count only the board holds."""
    del agent_id
    return int(env.count)


def test_a_seat_with_no_view_is_shown_its_own_observation() -> None:
    """Nothing changes for a policy: it is handed what it was always handed."""
    seen: list[Any] = []
    source = HeuristicController(lambda observation: seen.append(observation) or 0)

    read = what_a_seat_reads(_Seated(_Board()), source, "mover", [1.0, 2.0])

    assert read == [1.0, 2.0]
    assert not seen, "the helper reads the view; it does not decide"


def test_a_seat_that_names_a_view_is_shown_the_environment() -> None:
    """The view is called on the environment the loop holds, for that seat."""
    source = HeuristicController(lambda seen: int(seen), sees=_read_the_board)
    board = _Board()
    seated = _Seated(board)
    board.count = 7

    assert what_a_seat_reads(seated, source, "mover", None) == 7


def test_a_planning_seat_reads_the_board_the_loop_is_stepping() -> None:
    """The whole point, through the real loop: the seat decides off live state.

    The observation is empty, so a seat that returns the step count can only have
    read the board -- and it read the board **this** run is stepping.
    """
    board = _Board()
    planner = HeuristicController(lambda seen: int(seen), sees=_read_the_board)

    summary = asyncio.run(
        run_multiseat_episode(
            _Seated(board),
            channel_key="game",
            episode_id="episode_019b6000-0000-7000-8000-00000000000a",
            interaction_id="interaction_019b6000-0000-7000-8000-00000000000b",
            agent_ids=list(_SEATS),
            sources={"mover": planner, "watcher": _Still()},
            now=lambda: "2026-07-30T00:00:00.000000Z",
            fps=0,
            max_steps=4,
        )
    )

    played = [one.actions["mover"] for one in summary.trajectory]
    assert played == [0, 1, 2, 3], (
        "the seat did not read the count the loop was stepping"
    )


def test_two_runs_at_once_each_read_their_own_environment() -> None:
    """The failure a study holding its own environment would have.

    One study object serves every participant, so a partner that kept the environment
    it built would answer the second participant's board for the first. Here the view
    is called on whichever environment is being stepped, so two runs never cross.
    """
    first, second = _Board("first"), _Board("second")
    first.count, second.count = 3, 11
    reads_the_name = HeuristicController(
        lambda seen: 0, sees=lambda env, agent_id: env.name
    )

    assert what_a_seat_reads(_Seated(first), reads_the_name, "mover", None) == "first"
    assert what_a_seat_reads(_Seated(second), reads_the_name, "mover", None) == "second"


class _Still:
    """A seat that does nothing, so the run has a second agent in it."""

    def decide(self, observation: object) -> int:
        """Do nothing, whatever is seen."""
        del observation
        return 0


# -- what the records call a seat ----------------------------------------------------


def _drawn_for(seat: Any) -> Any:
    """Return one drawn frame for a seat, as the renderer builds it."""
    from mug.game.types import Digest, RenderPacket

    return RenderPacket(
        episode_id="episode_019b6000-0000-7000-8000-00000000000a",
        seat_key=seat,
        frame_number=0,
        render_digest=Digest(algorithm="sha-256", hex="0" * 64),
        keyframe=True,
        commands=[],
    )


def test_an_environment_that_numbers_its_agents_keeps_its_own_names() -> None:
    """A seat is named by the environment's agent, and a number is one of those.

    Both standard environment APIs number agents freely -- a PettingZoo environment
    answers ``[0, 1]``. The contract used to accept ``0`` as an ``env_agent_id`` and
    refuse it as a ``seat_key``, so a study seating a numbering environment composed,
    mounted, and stepped, and was then refused on the **first drawn frame**. That was
    an oversight in the contract, not something to work around by renaming the
    author's agents.
    """
    from mug.content.seats import seat_name

    assert seat_name(0) == "0"
    assert seat_name(1) == "1"


def test_a_name_the_contract_accepts_is_kept_exactly() -> None:
    """A study sees its environment's own words in the records, unchanged."""
    from mug.content.seats import seat_name

    assert seat_name("agent_left") == "agent_left"
    assert seat_name("traffic-light") == "traffic-light"


def test_a_name_the_contract_cannot_carry_is_folded_rather_than_refused() -> None:
    """A capital or a space is folded, so no study has to rename its agents."""
    from mug.content.seats import seat_name

    assert seat_name("Chef Two") == "chef-two"
    assert seat_name("Player Left") == "player-left"


def test_a_record_carries_a_numeric_seat_key_written_either_way() -> None:
    """The contract change itself: ``0`` and ``"0"`` are both accepted, as text.

    A record holds text, so a whole number is written down rather than travelling as
    a second shape -- nothing that reads a record has two forms to handle.
    """
    assert _drawn_for(0).seat_key == "0"
    assert _drawn_for("0").seat_key == "0"
    assert _drawn_for("agent_left").seat_key == "agent_left"


def test_a_seat_key_is_still_a_name_and_not_anything_at_all() -> None:
    """Relaxing the leading character did not relax the rest of the rule."""
    from pydantic import ValidationError

    for refused in ("Player Left", "-first", "a--b", "AGENT"):
        with pytest.raises(ValidationError):
            _drawn_for(refused)


def test_a_multi_agent_environment_wearing_a_single_agent_base_is_refused() -> None:
    """It derives as one agent whose action is a dictionary, and nothing plays that.

    ``slime_volleyball.SlimeVolleyEnv`` is exactly this, and it is widely used. Read as
    it declares itself, no key can bind to its action and the loop would hand it an
    integer -- and every one of those failures happens in front of a participant.
    """
    gymnasium = pytest.importorskip("gymnasium", reason="the game extra is needed")
    from mug.game.environments import EnvironmentRefused, derive

    class _TwoInOne(gymnasium.Env[Any, Any]):
        """One agent by declaration, two by action space."""

        def __init__(self) -> None:
            self.action_space = gymnasium.spaces.Dict(
                {
                    "left": gymnasium.spaces.Discrete(6),
                    "right": gymnasium.spaces.Discrete(6),
                }
            )

    with pytest.raises(EnvironmentRefused, match="wearing a single-agent base class"):
        derive(_TwoInOne)
