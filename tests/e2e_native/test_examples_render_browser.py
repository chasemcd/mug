"""Every shipped example is played in a real browser, and the picture is read back.

This exists because of a failure nothing else here caught. Three examples composed
their study, passed every test, and were unplayable: one raised on its first step,
and all three drew an empty canvas for as long as they ran. Each test in this file
would have failed on the day the fault was written, because each one opens the real
client in Chromium, plays the real game, and reads the pixels the browser drew.

Three claims are made about each example, and they are different claims:

- **Something was drawn.** The client mounts a canvas and paints its background in
  CSS, so a canvas nothing drew on holds no opaque pixel. A study whose render
  function was never called, or was called with nothing to draw, fails here.
- **It kept moving.** One drawn frame proves the opening keyframe arrived. A study
  whose environment refused to step, or whose delta never carried a change, draws
  the same picture forever, so the picture is read twice and must differ.
- **The pictures are the study's own.** A sprite the browser could not load draws
  nothing, and a shape with no colour draws nothing, so the count of distinct
  colours says the drawing really reached the canvas.

These tests need Chromium. They are not in the fast unit gate; run them with
``pytest tests/e2e_native``.

These modules use ASD-STE100 Simplified Technical English.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any

import pytest
from example_server import (
    ink,
    one_game_study,
    painted,
    play_to_the_canvas,
    serving,
    watch,
)
from playwright.sync_api import Browser, Page

from mug.content.assets import Asset

pytestmark = pytest.mark.e2e

# Short enough to finish quickly, long enough that the picture must change while
# somebody is looking at it.
_FRAMES = 40
_COUNTDOWN = 1


def _kitchen_game(key: str, *, seats: Any, max_steps: int) -> Any:
    """Return the Overcooked activity, shortened so a browser test finishes."""
    from examples.cogrid.env import (
        ACTION_BINDINGS,
        NOOP,
        kitchen_hud,
        overcooked_kitchen,
        overcooked_scene,
        render,
    )
    from mug.content import Game

    return Game(
        key,
        overcooked_kitchen("cramped_room", max_steps),
        seats=seats,
        keys=ACTION_BINDINGS,
        held_actions=False,
        default_action=NOOP,
        fps=10,
        render=render,
        scene=overcooked_scene("cramped_room", fps=10),
        hud=kitchen_hud,
    )


def _court_game(key: str, *, seats: Any, max_steps: int) -> Any:
    """Return the Slime Volleyball activity, shortened so a browser test finishes."""
    import functools

    from examples.slime_volleyball.env import (
        ACTION_BINDINGS,
        NOOP,
        court_scene,
        render,
        slime_court,
    )
    from mug.content import Game

    return Game(
        key,
        functools.partial(slime_court, max_steps=max_steps),
        seats=seats,
        keys=ACTION_BINDINGS,
        held_actions=True,
        default_action=NOOP,
        fps=10,
        render=render,
        scene=court_scene,
    )


def _mounted(which: str, partner: Any, *, max_steps: int) -> Any:
    """Return one example's activity, shortened so a browser test finishes.

    It is the **activity**, seating and all, not what a mount makes of it. A seated
    game wrapped back into ``Game(key, ...)`` loses its seats, mounts nothing, and
    the participant walks past it to the last page having played nothing.
    """
    from mug.content import Bot, Human

    if which == "kitchen":
        from examples.cogrid.env import CHEF_ONE, CHEF_TWO

        step = _kitchen_game(
            "play",
            seats={CHEF_ONE: Human(), CHEF_TWO: Bot(partner)},
            max_steps=max_steps,
        )
    else:
        from examples.slime_volleyball.env import LEFT_SEAT, RIGHT_SEAT

        step = _court_game(
            "play",
            seats={LEFT_SEAT: Human(), RIGHT_SEAT: Bot(partner)},
            max_steps=max_steps,
        )
    return step


def _mountain_car() -> tuple[Any, list[Asset]]:
    """The example that needs nothing installed: shapes only, no sprite sheet."""
    from examples.mountain_car.native_env import mountain_car_spec

    return replace(
        mountain_car_spec(), fps=10, max_steps=_FRAMES, countdown_seconds=_COUNTDOWN
    ), []


def _slime_volleyball() -> tuple[Any, list[Asset]]:
    """A person against a heuristic, drawn with polygons, lines, and circles."""
    slime = pytest.importorskip(
        "slime_volleyball", reason="uv pip install slime_volleyball"
    )
    assert slime is not None
    from examples.slime_volleyball.policies import ball_chaser

    # A seated game holds no pre-roll of its own: the countdown is written on the
    # one-person specification, and these tests wait for the first painted frame
    # rather than for a clock.
    return _mounted("court", ball_chaser(), max_steps=_FRAMES), []


def _overcooked() -> tuple[Any, list[Asset]]:
    """A person and a policy in one kitchen, drawn from packed sprite sheets."""
    pytest.importorskip("cogrid", reason="uv pip install cogrid==0.3.2")
    from examples.cogrid.partners import scripted_chef
    from examples.cogrid.sprites import overcooked_assets

    return _mounted("kitchen", scripted_chef(), max_steps=_FRAMES), overcooked_assets()


def _slime_against_a_network() -> tuple[Any, list[Asset]]:
    """The same court, with an exported network on the other side of the fence."""
    pytest.importorskip("slime_volleyball", reason="uv pip install slime_volleyball")
    pytest.importorskip("onnxruntime", reason="uv pip install onnxruntime")
    from examples.slime_volleyball.human_ai import MODEL
    from examples.slime_volleyball.policies import exported_partner

    return _mounted("court", exported_partner(MODEL), max_steps=_FRAMES), []


def _render_conformance() -> tuple[Any, list[Asset]]:
    """Every drawing primitive the renderer supports, in one scene."""
    from examples.render_conformance.scene import conformance_spec

    return replace(
        conformance_spec(), fps=10, max_steps=_FRAMES, countdown_seconds=_COUNTDOWN
    ), []


# Each example, and how few colours its drawing may honestly use. A sprite sheet
# brings dozens; a study drawn in flat shapes brings one per shape.
EXAMPLES: list[tuple[str, Callable[[], tuple[Any, list[Asset]]], int]] = [
    ("mountain_car", _mountain_car, 3),
    ("render_conformance", _render_conformance, 4),
    ("slime_volleyball", _slime_volleyball, 3),
    ("cogrid_overcooked", _overcooked, 8),
    ("slime_volleyball_onnx", _slime_against_a_network, 3),
]


@pytest.mark.parametrize(("name", "build", "colours"), EXAMPLES)
def test_an_example_draws_a_moving_picture_in_a_real_browser(
    page: Page,
    name: str,
    build: Callable[[], tuple[Any, list[Asset]]],
    colours: int,
) -> None:
    """The participant sees the game, and it is still going."""
    game, assets = build()
    with serving(one_game_study(name, game, assets)) as address:
        play_to_the_canvas(page, address)
        # Read the canvas over and over for as long as the game is on the screen.
        seen = watch(page)

    assert seen, f"{name} lost its canvas before anything could be read"
    first = seen[0]
    assert first["painted"] > 0, f"{name} drew nothing at all"
    assert first["colours"] >= colours, (
        f"{name} painted {first['colours']} colours; its own drawing uses more, so "
        "something it asked for did not reach the canvas"
    )
    assert len({one["signature"] for one in seen}) > 1, (
        f"{name} painted the same picture every time it was looked at, so the game "
        "was drawn once and then stopped moving"
    )


def test_the_keys_a_participant_presses_change_what_they_see(page: Page) -> None:
    """The whole input path, proven by the picture rather than by a wire frame.

    The kitchen is given the partner that fetches nothing, so with nobody at the
    keyboard the scene stands still. Anything that moves after that moved because a
    key was pressed in a real browser, was read as an input frame, was resolved to
    an action, was stepped, and was drawn back.
    """
    pytest.importorskip("cogrid", reason="uv pip install cogrid==0.3.2")
    from examples.cogrid.partners import station_keeper
    from examples.cogrid.sprites import overcooked_assets

    # The status line is taken off, and only here. It says how long is left, so it
    # changes on every frame whether or not anybody is playing -- and this is the
    # one test that reads "nothing moved" off the canvas. With it on, the kitchen
    # is never still and the reading below could not tell a key from a clock.
    played = _mounted("kitchen", station_keeper(), max_steps=120)
    game = replace(played, plays=replace(played.plays, hud=None))
    with serving(one_game_study("keys", game, overcooked_assets())) as address:
        play_to_the_canvas(page, address)
        still = painted(page)
        page.wait_for_timeout(1000)
        assert painted(page)["signature"] == still["signature"], (
            "the kitchen moved before anybody touched a key, so this test could "
            "not tell an input apart from the environment"
        )

        page.locator("canvas").focus()
        moved = False
        for _ in range(20):
            page.keyboard.down("ArrowRight")
            page.wait_for_timeout(150)
            page.keyboard.up("ArrowRight")
            page.wait_for_timeout(150)
            if painted(page)["signature"] != still["signature"]:
                moved = True
                break

    assert moved, "the participant pressed a key and nothing on the canvas moved"


@pytest.mark.parametrize(("name", "build", "colours"), EXAMPLES)
def test_an_example_reaches_the_end_of_its_game(
    page: Page,
    name: str,
    build: Callable[[], tuple[Any, list[Asset]]],
    colours: int,
) -> None:
    """The run ends, and the participant is moved past it.

    A game that raised while it stepped left the participant on a canvas that had
    stopped, with the socket closed under them and nothing said about it. Reaching
    the page after the game is the only proof from the outside that the whole
    episode ran and was recorded.
    """
    del colours
    game, assets = build()
    with serving(one_game_study(name, game, assets)) as address:
        play_to_the_canvas(page, address)
        page.wait_for_selector("text=Thank you", timeout=60_000)


def test_two_browsers_watch_one_server_stepped_kitchen(browser: Browser) -> None:
    """The multi-seat game draws, and it draws for everybody at the table.

    A one-person game and a several-person game took different paths through the
    transport, and only the first one drew. So a study that seated two people, or a
    person beside a model, pushed frames nobody could see. Two real browsers is the
    only way to say this is fixed: each one has its own canvas, its own surface, and
    its own idea of what it already holds.
    """
    pytest.importorskip("cogrid", reason="uv pip install cogrid==0.3.2")
    from examples.cogrid.env import CHEF_ONE, CHEF_TWO
    from examples.cogrid.sprites import overcooked_assets
    from mug.content import Human, Page, Study

    study = Study(
        Page("start", "# Ready\n\nPress continue to play."),
        _kitchen_game(
            "cook",
            seats={CHEF_ONE: Human(), CHEF_TWO: Human()},
            max_steps=120,
        ),
        Page("end", "# Thank you"),
        assets=overcooked_assets(),
    )

    with serving(study) as address:
        first = browser.new_context().new_page()
        second = browser.new_context().new_page()
        try:
            for page in (first, second):
                page.goto(address)
                page.wait_for_selector("text=connected", timeout=15_000)
                page.get_by_role("button", name="Continue").click()
            # Neither game starts until both people are at the table.
            for page in (first, second):
                page.wait_for_selector("canvas", timeout=20_000)

            # One of them plays, so there is something for both to see.
            first.locator("canvas").focus()
            seen: list[list[dict[str, int]]] = [[], []]
            for _ in range(40):
                first.keyboard.down("ArrowRight")
                first.wait_for_timeout(120)
                first.keyboard.up("ArrowRight")
                first.wait_for_timeout(120)
                for index, page in enumerate((first, second)):
                    read = ink(page)
                    if read is not None:
                        seen[index].append(read)
                if all(len({one["signature"] for one in each}) > 1 for each in seen):
                    break
        finally:
            first.context.close()
            second.context.close()

    for index, each in enumerate(seen):
        assert each, f"browser {index + 1} never had a canvas to read"
        assert each[0]["painted"] > 0, f"browser {index + 1} was shown a blank canvas"
        assert len({one["signature"] for one in each}) > 1, (
            f"browser {index + 1} was shown one frame of a game the other one "
            "was playing"
        )
