"""A whole shipped study, played end to end in a real browser, unmodified.

The rest of the browser suite proves the renderer: a study of one page, one game
shortened to four seconds, and one page. That is a real canvas with real pixels on
it, and it says nothing about whether a **study** works -- because a study is the
joins between its activities, and every join here was untested:

- a consent form the participant has to fill in before anything else happens;
- a game that runs at its **own** speed and length rather than a test's;
- rounds, with a rest between them, and a canvas that must paint in the second one
  as well as the first;
- a survey delivered **after** the game finished, not during it;
- a debrief the participant actually reaches.

Nothing here is shortened, replaced, or mounted beside the study. The study object
is the one the example ships, and the test walks it the way a participant does.

These tests are slow on purpose: a shipped round takes as long as it takes. They
need Chromium and are not in the fast gate -- run them with
``pytest tests/e2e_native/test_whole_study_browser.py``.

These modules use ASD-STE100 Simplified Technical English.
"""

from __future__ import annotations

import pytest
from example_server import serving
from playwright.sync_api import Page
from whole_study import Played, recorded, walk_the_whole_study

from mug.storage import InMemoryStore

pytestmark = pytest.mark.e2e

# What counts as a picture rather than an empty canvas. The client mounts a 600 by
# 400 canvas and paints its background in CSS, so a canvas nothing drew on holds no
# opaque pixel; a drawing that reached it holds thousands.
DREW_SOMETHING = 500

# How much of a later round's picture must match the first round's. It is a
# **fraction of the canvas**, so it says the same thing whatever size the canvas is.
#
# It is here because "did anything draw at all" is not the question. A round drawn
# with everything that is drawn once held back -- the whole room -- still paints the
# things that move, and two chefs on an empty floor beat any threshold set for an
# empty canvas. A round that opens with a fifth of what the round before it covered
# has lost its floor, and nothing about painted pixels alone would say so.
AS_MUCH_AS_THE_FIRST = 0.7


def test_the_mountain_car_study_is_walked_from_consent_to_debrief(page: Page) -> None:
    """The smallest complete study, played whole and unmodified.

    Five activities, in the order the example writes them: consent, instructions,
    the game, a survey, a debrief. Every one of them is met, answered, and left
    behind, and the game paints a moving picture while it is on the screen.
    """
    from examples.mountain_car.study import mountain_car_study

    store = InMemoryStore()
    with serving(mountain_car_study(), store=store) as address:
        walked = walk_the_whole_study(page, address)

    assert walked.activities == ["form", "page", "game", "form", "page"], (
        f"the participant met {walked.activities}, which is not the study as written"
    )
    drove = walked.games[0]
    assert drove.first_painted > DREW_SOMETHING, (
        f"the game opened with {drove.first_painted} painted pixels, so the "
        "participant was shown an all but empty canvas"
    )
    assert drove.moved, "the picture never changed, so the environment did not step"
    assert len(walked.forms) == 2, "the consent form and the survey were not both met"
    assert walked.finished, "the participant never reached the completion screen"

    left = recorded(store)
    assert left.get("visitplan", 0) == 1, f"no visit was recorded: {left}"
    assert left.get("interaction", 0) >= 1, f"the game recorded no interaction: {left}"


def test_a_study_with_rounds_paints_every_round_and_rests_between_them(
    page: Page,
) -> None:
    """Several rounds of one activity, with the interval page the study writes.

    A round loop is where a study stops being one game: the second round has to
    reach a canvas of its own, and the participant has to be able to get past the
    rest between them. A study that painted the first round and then hung is
    indistinguishable from a slow one until somebody walks it.

    The rounds are shortened **only in the environment's own episode bound**, which
    is a property of the environment rather than of the study: the activity, its
    seating, its keys, its drawing, and its round loop are the shipped ones.
    """
    import functools

    import gymnasium

    from examples.mountain_car.native_env import render
    from mug.content import Choice, Form, Game, Human, Likert, Study
    from mug.content import Page as ContentPage

    rounds = 3
    hill = functools.partial(gymnasium.make, "MountainCar-v0", max_episode_steps=60)
    study = Study(
        Form("consent", Choice("agree", "Do you agree to take part?", ["yes", "no"])),
        ContentPage("instructions", "# Drive the car\n\nRock it out of the valley."),
        Game(
            "play",
            hill,
            seats={"agent": Human()},
            render=render,
            episodes=rounds,
            between="# Take a moment\n\nThe next round starts when you continue.",
        ),
        Form("post-survey", Likert("difficulty", "How hard was it?", scale=7)),
        ContentPage("debrief", "# Thank you"),
    )

    store = InMemoryStore()
    with serving(study, store=store) as address:
        walked = walk_the_whole_study(page, address)

    played = [one for one in walked.activities if one == "game"]
    assert len(played) == rounds, (
        f"{len(played)} of {rounds} rounds reached a canvas; the participant met "
        f"{walked.activities}"
    )
    for index, round_played in enumerate(walked.games, start=1):
        assert round_played.first_painted > DREW_SOMETHING, (
            f"round {index} opened with {round_played.first_painted} painted pixels"
        )
        assert round_played.moved, f"round {index} drew one picture and stopped"
    _every_round_drew_as_much_as_the_first(walked.games)
    assert walked.activities[-1] == "page", "the participant never reached the debrief"
    assert walked.finished, "the participant never reached the completion screen"


def _every_round_drew_as_much_as_the_first(games: list[Played]) -> None:
    """Hold that a later round covers about as much of the canvas as the first.

    This is what the walk was missing. Every round painted **something**, so a
    threshold for an empty canvas was met by every one of them -- while the rounds
    after the first were drawing two moving sprites on an empty floor, because the
    server was holding back everything it had already sent to a canvas the rest
    between rounds had thrown away.
    """
    first = games[0].covered
    assert first > 0, "the first round covered none of its canvas"
    for index, played in enumerate(games[1:], start=2):
        assert played.covered > first * AS_MUCH_AS_THE_FIRST, (
            f"round {index} covered {played.covered:.1%} of the canvas where round "
            f"one covered {first:.1%}. The round is drawing what moves and nothing "
            "that is drawn once, so the participant is playing on an empty floor"
        )


def test_the_overcooked_study_is_walked_with_both_partners_and_the_judgement(
    page: Page,
) -> None:
    """The most complex shipped study, played whole: two partners and a comparison.

    This is the one that exercises everything at once -- a seating with a person and
    a bot, a partner that reads the environment through ``sees``, sprite sheets, a
    status line, two game activities in one study, and a comparison between the two
    rounds that has to be delivered after both of them have been played.

    It is slow, because a round of it is 600 frames at 30 frames a second. That is
    the study as it ships, and a shortened one would not be evidence about it.
    """
    pytest.importorskip("cogrid", reason="uv pip install cogrid==0.3.2")
    pytest.importorskip("onnxruntime", reason="uv pip install onnxruntime")
    from examples.cogrid.overcooked_human_ai import overcooked_human_ai_study

    store = InMemoryStore()
    with serving(overcooked_human_ai_study(), store=store) as address:
        walked = walk_the_whole_study(page, address, screens=60)

    assert len(walked.games) == 2, (
        f"the participant played {len(walked.games)} rounds, not two; they met "
        f"{walked.activities}"
    )
    for played in walked.games:
        assert played.first_painted > DREW_SOMETHING, (
            f"a round opened with {played.first_painted} painted pixels, so the "
            "kitchen's sprite sheets did not reach the canvas"
        )
        assert played.moved, "the kitchen drew one picture and stopped"
    assert walked.activities[-1] == "page", "the participant never reached the debrief"
    assert walked.finished, "the participant never reached the completion screen"
