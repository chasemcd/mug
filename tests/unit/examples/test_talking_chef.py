"""The Overcooked partner that cooks and talks: what its reply means.

The agent reads one model reply three ways -- the job it does, the words the
participant reads, and the plan it carries. What is checked here is the reading,
because it is where a study of this shape goes wrong in a way that looks like a bad
model rather than a bug:

**What the partner says must not decide what it does.** ``LLMAgent.parse_reply``
defaults to "the last name anywhere in the reply", which is right for an agent that
only plays. Give that agent a sentence to say and the sentence is read for the move.

The rest is the coarser grain in this kitchen: a job is a place to go, an unknown
job is nowhere, and the chef walks a whole route from one decision.

The kitchen needs ``cogrid``: ``uv pip install cogrid==0.3.2``.

These modules use ASD-STE100 Simplified Technical English.
"""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("cogrid", reason="uv pip install cogrid==0.3.2")

from examples.cogrid.chef_agent import JOBS, MOVES, TalkingChef
from examples.cogrid.env import (
    NOOP,
    caught_up,
    chef_at,
    overcooked_kitchen,
)
from examples.cogrid.kitchen_text import kitchen_as_text

CHEF = "1"


@pytest.fixture
def kitchen() -> Any:
    """Return one built Overcooked kitchen, reset and ready to read."""
    built = overcooked_kitchen("cramped_room", 400)()
    built.reset(seed=7)
    return built


def _job(chef: TalkingChef, reply: str, env: Any) -> str | None:
    """Return the name of the job one reply chooses, or nothing."""
    found = chef.parse_reply(reply, env, CHEF)
    return None if found is None else JOBS[found]


def test_what_the_partner_says_does_not_decide_what_it_does(kitchen: Any) -> None:
    """The one thing that must not be got wrong.

    The reply names ``DELIVER`` as its job and mentions ``FETCH_ONION`` **later**,
    in the sentence it says out loud. The default parser takes the last name
    anywhere in the reply and would answer ``FETCH_ONION`` -- so the partner would
    walk to the crates while telling its partner it was delivering, and the study
    would blame the model.

    The order of the two names is the whole test. Written the other way round, or
    with the job repeated in the plan, the default parser gets the right answer by
    luck and this test passes with the study's own parser deleted.
    """
    chef = TalkingChef()
    reply = "JOB: DELIVER\nSAY: after this I will FETCH_ONION again\nPLAN: keep going"

    assert reply.rfind("FETCH_ONION") > reply.rfind("DELIVER"), (
        "the test needs the spoken job to come last, or it proves nothing"
    )
    assert _job(chef, reply, kitchen) == "DELIVER", (
        "the job was read out of the sentence the partner says rather than out of "
        "its JOB line"
    )
    assert chef.say(reply, kitchen, CHEF) == "after this I will FETCH_ONION again"


def test_the_job_is_read_whatever_order_the_lines_come_in(kitchen: Any) -> None:
    """A model that answers the three lines in another order is still read."""
    chef = TalkingChef()
    reply = "SAY: I am on the onions\nPLAN: fill the pot\nJOB: FETCH_ONION"

    assert _job(chef, reply, kitchen) == "FETCH_ONION"
    assert chef.reflect(reply, kitchen, CHEF) == "fill the pot"


def test_a_reply_that_names_no_job_is_a_fallback(kitchen: Any) -> None:
    """An unreadable job is answered ``None``, and the seat then falls back.

    This is the shape of a small model breaking format, which is expected rather
    than exceptional. It must be a fallback and never a job read out of prose.
    """
    chef = TalkingChef()

    assert _job(chef, "I think I will go and get an onion, probably.", kitchen) is None
    assert _job(chef, "", kitchen) is None


def test_a_partner_with_nothing_to_say_says_nothing(kitchen: Any) -> None:
    """Silence is a real answer, so the words for it are not published."""
    chef = TalkingChef()

    for said in ("NOTHING", "nothing", "NONE", "-", ""):
        reply = f"JOB: STAND_BY\nSAY: {said}\nPLAN: wait"
        assert chef.say(reply, kitchen, CHEF) is None, f"{said!r} was published"


def test_the_model_decides_jobs_and_the_run_is_recorded_in_moves(kitchen: Any) -> None:
    """Two vocabularies, and each is used where it belongs.

    ``decides_among`` is what the model chooses between; ``available_actions`` is
    what the **runtime** names every seat's move with when it writes this agent's
    history. If they were one list, the person cooking beside the model would have
    their grid moves recorded under job names.
    """
    chef = TalkingChef()

    assert chef.decides_among(kitchen, CHEF) == list(JOBS)
    assert chef.available_actions(kitchen, CHEF) == list(MOVES)
    assert set(JOBS).isdisjoint(MOVES)


def test_one_job_is_carried_out_over_many_frames(kitchen: Any) -> None:
    """A decision that lasts is what makes a language model able to hold a seat.

    The chef is told to fetch an onion once and then stepped. It walks: several
    frames of movement out of one decision, which at one decision a second is the
    whole reason the kitchen can run at thirty frames a second with a model in it.
    """
    chef = TalkingChef()
    fetch = JOBS.index("FETCH_ONION")
    where = []
    for _frame in range(12):
        move = chef.carry_out(kitchen, CHEF, fetch)
        kitchen.step({0: NOOP, 1: NOOP if move is None else move})
        at = chef_at(caught_up(kitchen), CHEF)
        where.append((int(at.pos[0]), int(at.pos[1]), int(at.dir)))

    assert len(set(where)) > 1, (
        f"the chef never moved over twelve frames of one job: {where[0]}"
    )


def test_a_job_nobody_named_is_nowhere_and_the_chef_stands_still(
    kitchen: Any,
) -> None:
    """No choice, and an out-of-range choice, both mean nobody has said.

    Answering ``None`` is what the seat reads as "nothing to do this frame", and it
    takes the game's own idle action. So the study never writes what the idle action
    is in order to say "stand still".
    """
    chef = TalkingChef()

    assert chef.carry_out(kitchen, CHEF, None) is None
    assert chef.carry_out(kitchen, CHEF, len(JOBS)) is None
    assert chef.carry_out(kitchen, CHEF, JOBS.index("STAND_BY")) is None


def test_the_kitchen_reads_as_something_a_model_can_act_on(kitchen: Any) -> None:
    """The text view says the four things a cook acts on, and names the reader.

    The platform hands this seat 892 numbers. What the study has to supply is the
    same kitchen in words, and it has to be true: a partner told it is chef 1 when
    it is chef 0 walks the other cook's route all round.
    """
    said = kitchen_as_text(kitchen, CHEF)

    assert "You are chef 1" in said, "the model is not told which chef it is"
    assert "Your partner is chef 0" in said
    assert "The kitchen has" in said and "row 0:" in said, "there is no floor plan"
    assert "The pot at" in said, "the pots are not described"
    assert "Steps left in the shift:" in said, "the model cannot tell the time"

    # And it is about **this** kitchen: the chef it names is where it says.
    at = chef_at(caught_up(kitchen), CHEF)
    assert f"at row {int(at.pos[0])} column {int(at.pos[1])}" in said


def test_the_other_chef_reads_the_same_kitchen_from_the_other_side(
    kitchen: Any,
) -> None:
    """The view is from one seat, so the two seats are not told the same thing."""
    assert "You are chef 0" in kitchen_as_text(kitchen, "0")
    assert "You are chef 1" in kitchen_as_text(kitchen, "1")
