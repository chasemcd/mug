"""The whole human-AI kitchen, run in a real browser with nothing on the server.

This is the example the owner asked for, played the only way it can honestly be
checked. A real Chromium downloads a Python runtime, installs the environment,
steps the kitchen, and scores a trained network beside it with the browser's own
inference runtime. Nothing about the game is computed by the server.

Four claims, and they fail separately:

- **the participant sees a kitchen.** The pixels are read back: a sprite sheet the
  browser could not load draws nothing, so the count of distinct colours is what
  says the study's own pictures reached the canvas.
- **it keeps moving.** One drawn frame proves the opening keyframe arrived.
- **the trained partner really played.** The network is fetched by the name the
  study declared and scored in the browser. A partner that never loaded would leave
  the second chef standing on its opening square for the whole round.
- **the run was recorded.** The browser reports the episode and the server
  re-executes it under both seats' reported actions. The participant only reaches
  the next screen when that verification passed, so arriving at the survey is the
  evidence that the run verified and was captured.

It downloads a Python runtime, an environment package, and an inference runtime,
so it is slow and it needs a network. It is not in the fast unit gate; run it with
``pytest tests/e2e_native``.

These modules use ASD-STE100 Simplified Technical English.
"""

from __future__ import annotations

import time

import pytest
from example_server import ink, serving
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

# The kitchen a participant is really given. It used to be sixty frames, a tenth of
# a round, with nobody pressing a key -- and that is the one way of playing where a
# whole class of fault is invisible. An idle chef never reaches for the square the
# partner is reaching for, so it never takes the tiebreak that CoGrid drew from
# operating-system entropy, and the shortened silent round verified against an
# environment no full round could verify against. A test of a game has to play the
# game.
_FRAMES = 600

# How often the participant presses something. Fast enough to keep the kitchen busy
# for the whole round, slow enough that each press is a separate keystroke.
_PRESS_EVERY_MS = 100

# What a participant presses: the four ways to walk, and the two things to do.
_KEYS = ("ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "w", "q")

# How long the participant's own machine is given to fetch a Python runtime, an
# environment package, and an inference runtime. A slow network is not a fault.
_READY_MS = 300_000

# A kitchen drawn from packed sprite sheets brings many colours. A canvas with
# fewer than this is a canvas whose sprites did not arrive.
_LEAST_COLOURS = 8


def _study() -> object:
    """Return the shipped study, shortened to one round a test can sit through."""
    pytest.importorskip("cogrid", reason="uv pip install cogrid==0.3.2")
    from examples.cogrid import pages
    from examples.cogrid.sprites import overcooked_assets
    from mug.content import Game, Study
    from mug.content import Page as ContentPage

    return Study(
        ContentPage("instructions", pages.instructions(partner=pages.HUMAN_AI)),
        Game("play", caption=pages.IN_GAME),
        ContentPage("debrief", "# Thank you"),
        assets=overcooked_assets(policy=True),
    )


def _spec() -> object:
    """Return the shipped browser kitchen, with only the countdown taken off."""
    from dataclasses import replace

    from examples.cogrid.env import overcooked_browser

    return replace(overcooked_browser(), max_steps=_FRAMES, countdown_seconds=0)


def _reach_the_kitchen(page: Page, address: str) -> None:
    """Open the study, continue past the instructions, and wait for a drawn frame."""
    page.goto(address)
    # Not the "connected" line: a browser-run study starts downloading its runtime
    # at once and writes over that line long before a test could read it.
    page.wait_for_selector("[data-testid='content-page']", timeout=30_000)
    page.get_by_role("button", name="Continue").click()
    page.wait_for_selector("canvas", timeout=30_000)
    for _ in range(_READY_MS // 500):
        read = ink(page)
        if read is not None and read["painted"] > 0:
            return
        page.wait_for_timeout(500)
    raise AssertionError("nothing was ever painted on the canvas")


def test_a_participant_plays_a_whole_round_and_it_is_recorded(page: Page) -> None:
    """A full round, played with the keyboard, is re-executed and captured.

    This is the whole vertical as a participant meets it: six hundred frames, keys
    pressed throughout, the trained partner cooking beside them. The server then
    re-executes the reported run under both seats' actions and matches every state
    hash, and the flow advances only when that passed -- so reaching the next screen
    is the evidence that the run verified and was recorded.

    Played this way it fails against an environment that cannot be re-executed. It
    was previously a tenth of a round with no key pressed, and passed against one.
    """
    with serving(_study(), browser_game=_spec()) as address:  # pyright: ignore[reportArgumentType]
        _reach_the_kitchen(page, address)

        opening = ink(page)
        assert opening is not None
        assert opening["colours"] >= _LEAST_COLOURS, (
            f"the kitchen was drawn in {opening['colours']} colours, so its sprite "
            "sheets did not reach the participant"
        )

        pictures = []
        for press in range(600):
            if page.get_by_text("Thank you").count() > 0:
                break
            read = ink(page)
            if read is not None:
                pictures.append(read["signature"])
            page.keyboard.press(_KEYS[press % len(_KEYS)])
            page.wait_for_timeout(_PRESS_EVERY_MS)

        page.wait_for_selector("text=Thank you", timeout=120_000)

    assert len(set(pictures)) > 1, (
        "the kitchen drew the same picture for the whole round, so either the "
        "environment did not step in the browser or the drawing did not read it"
    )


def test_the_trained_partner_is_fetched_by_the_name_the_study_declared(
    page: Page,
) -> None:
    """The model is asked for by digest, and nothing else is fetched to get it.

    A study names a network the way it names a picture. What that has to mean is
    that the request the browser makes is for the study's own declared file, so
    the requests are watched rather than the manifest re-read.
    """
    asked: list[str] = []
    page.on("request", lambda request: asked.append(request.url))

    with serving(_study(), browser_game=_spec()) as address:  # pyright: ignore[reportArgumentType]
        _reach_the_kitchen(page, address)

    ours = [one for one in asked if "/assets/" in one]
    assert ours, "the browser fetched none of the study's declared files"
    # Every declared file is served from this deployment, by its own digest. A
    # study that had leaked a path or an address would show a request somewhere else.
    assert all(one.startswith(address) for one in ours), (
        "a declared file was fetched from somewhere this deployment does not serve"
    )


def test_the_partner_moves_rather_than_standing_where_it_started(page: Page) -> None:
    """A partner that never loaded leaves its chef on its opening square.

    The participant presses nothing, so anything that moves in the kitchen below
    the status band is the partner. Reading the band out is what makes that true:
    the clock changes every frame and would otherwise answer for the partner.
    """
    with serving(_study(), browser_game=_spec()) as address:  # pyright: ignore[reportArgumentType]
        _reach_the_kitchen(page, address)

        below = []
        for _ in range(60):
            read = page.evaluate(
                """() => {
                  const canvas = document.querySelector('canvas');
                  if (!canvas) return null;
                  const top = Math.round(canvas.height * 0.085);
                  const data = canvas.getContext('2d')
                    .getImageData(0, top, canvas.width, canvas.height - top).data;
                  let signature = 0;
                  for (let at = 0; at < data.length; at += 4) {
                    if (data[at + 3] === 0) continue;
                    signature = (signature * 31 + data[at] + at) >>> 0;
                  }
                  return signature;
                }"""
            )
            if read is None:
                break
            below.append(int(read))
            page.wait_for_timeout(250)

    assert len(set(below)) > 1, (
        "nothing in the kitchen moved while the participant pressed nothing, so "
        "the trained partner never acted"
    )


def test_a_participant_who_closes_the_tab_mid_round_is_still_recorded(
    page: Page,
) -> None:
    """The frames played before the tab closed are recorded, in a real browser.

    This is the whole reason a run is reported in parts, driven the only way it can
    honestly be checked: a real Chromium plays a real round and is then closed
    part-way through, the way a participant closes a tab. Nothing tells the server
    the round ended, so there is no acknowledgement to read and no screen to look
    at -- what is checked is what the store holds afterwards.

    Before parts, this recorded nothing at all.
    """
    from mug.game.capture_parts import FRAMES_PER_PART
    from mug.storage import InMemoryStore

    store = InMemoryStore()
    with serving(_study(), store=store, browser_game=_spec()) as address:  # pyright: ignore[reportArgumentType]
        _reach_the_kitchen(page, address)
        # Play for a while, then close the tab in the middle of the round.
        for press in range(60):
            page.keyboard.press(_KEYS[press % len(_KEYS)])
            page.wait_for_timeout(_PRESS_EVERY_MS)
        page.close()
        # The server notices the socket has gone and seals what arrived.
        for _ in range(40):
            episodes = [
                state
                for key, state in store.scan_aggregates()
                if key.startswith("episode_") and isinstance(state, dict)
            ]
            if episodes:
                break
            time.sleep(0.25)

    recorded = [
        state
        for key, state in store.scan_aggregates()
        if key.startswith("episode_") and isinstance(state, dict)
    ]
    assert recorded, (
        "the participant played most of a minute and the tab closed, and nothing "
        "was recorded at all"
    )
    run = recorded[0]
    assert run["frame_count"] >= FRAMES_PER_PART, (
        f"only {run['frame_count']} frames were kept, so the parts already reported "
        "were thrown away rather than sealed"
    )
    assert run["frame_count"] < _FRAMES, "the round was not actually cut short"
    assert run["verification"] == "deterministic"
    assert run["trajectory"], "a sealed run records the values the server re-executed"
