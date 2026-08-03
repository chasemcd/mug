"""How long one key press lasts, read off the screen a participant is looking at.

The platform read the keys a participant was **holding** and mapped them to an
action on every frame. For a game on a grid that is wrong in a way a participant
feels at once: a tap of the pick-up key that lasts a tenth of a second is three
actions at thirty frames a second, so a dish goes down and comes straight back up,
and a tap of an arrow crosses the room.

The frozen contract already had both readings (API-09 ``InputScheme.mode``), and
nothing produced or read them. Both are checked here in a real browser, because
this is a fault about what a key press **does**, and the only place that is true is
under a real keyboard driving a real client.

These tests need Chromium. They are not in the fast unit gate; run them with
``pytest tests/e2e_native``.

These modules use ASD-STE100 Simplified Technical English.
"""

from __future__ import annotations

import pytest
from example_server import play_to_the_canvas, serving
from playwright.sync_api import Page

from mug.content import Game, Study
from mug.content import Page as ContentPage
from mug.game.env import StepResult
from mug.game.spec import GameSpec
from mug.game.surface import Surface

pytestmark = pytest.mark.e2e

# Where the square starts, how far one action moves it, and how fast the game runs.
_NEAR = 0.05
_STEP = 0.05
_FPS = 10

# Where the square's left edge is now, as a fraction of the canvas width.
_WHERE = """
() => {
  const canvas = document.querySelector('canvas');
  if (!canvas) return -1;
  const data = canvas.getContext('2d')
    .getImageData(0, 0, canvas.width, canvas.height).data;
  for (let x = 0; x < canvas.width; x++) {
    for (let y = 0; y < canvas.height; y++) {
      const at = (y * canvas.width + x) * 4;
      const hit = data[at] === 204 && data[at + 1] === 51 && data[at + 2] === 102;
      if (hit) return x / canvas.width;
    }
  }
  return -1;
}
"""
# --- how long one press lasts ------------------------------------------------

# A game whose square steps one notch per action, so where it ends up is a count
# of the actions a held key produced.
_STEP = 0.05


def _stepping_game(*, mode: str) -> GameSpec:
    """A game that moves one notch right for each move action it is given."""

    class Steps:
        def __init__(self) -> None:
            self.at = 0

        def reset(self, *, seed: int | None = None) -> tuple[list[float], dict]:
            self.at = 0
            return [0.0], {"at": 0}

        def step(self, action: int) -> tuple[list[float], float, bool, bool, dict]:
            if action == 1:
                self.at += 1
            return [float(self.at)], 0.0, False, False, {"at": self.at}

    def render(surface: Surface, state: StepResult) -> None:
        surface.rect(
            x=_NEAR + int(state.info["at"]) * _STEP,
            y=0.45,
            w=0.04,
            h=0.12,
            color="#cc3366",
            object_id="stepper",
        )

    return GameSpec(
        channel_key="steps",
        make_env=lambda: Steps(),  # pyright: ignore[reportArgumentType]
        render=render,
        action_bindings={"ArrowRight": 1},
        default_action=0,
        input_mode=mode,
        fps=_FPS,
        max_steps=200,
        countdown_seconds=0,
    )


def _stepping_study(*, mode: str) -> Study:
    """Return a study whose one game counts the actions a key press produced."""
    return Study(
        ContentPage("start", "# Ready"),
        Game("play", _stepping_game(mode=mode)),
        ContentPage("end", "# Thank you"),
    )


def _steps_taken(page: Page) -> int:
    """Return how many notches the square has moved from where it started."""
    where = float(page.evaluate(_WHERE))
    return round((where - _NEAR) / _STEP)


def _hold(page: Page, ms: int) -> None:
    """Hold one key down for a while, as a participant leaning on it does."""
    page.keyboard.down("ArrowRight")
    page.wait_for_timeout(ms)
    page.keyboard.up("ArrowRight")
    page.wait_for_timeout(400)


def test_one_press_is_one_move_when_the_study_counts_presses(page: Page) -> None:
    """The fault the owner met, read off the screen: a tap must move one square.

    The key is held for about a second at ten frames a second. Under the reading
    the platform always had, that is ten moves.
    """
    with serving(_stepping_study(mode="single_keystroke")) as address:
        play_to_the_canvas(page, address)
        page.locator("canvas").click()
        _hold(page, 1000)
        moved = _steps_taken(page)

    assert moved == 1, f"one press moved the square {moved} squares"


def test_a_held_key_keeps_acting_when_the_study_reads_what_is_held(page: Page) -> None:
    """The other mode still works, so the fix is a choice rather than a change.

    Without this the first test would pass on a platform that had simply stopped
    reading held keys, which would break every game of continuous control.
    """
    with serving(_stepping_study(mode="pressed_keys")) as address:
        play_to_the_canvas(page, address)
        page.locator("canvas").click()
        _hold(page, 1000)
        moved = _steps_taken(page)

    assert moved > 3, f"a key held for a second moved the square only {moved} squares"


def _chord_game() -> GameSpec:
    """A game whose one chord is worth a big step, so the screen says which fired."""

    class Steps:
        def __init__(self) -> None:
            self.at = 0

        def reset(self, *, seed: int | None = None) -> tuple[list[float], dict]:
            self.at = 0
            return [0.0], {"at": 0}

        def step(self, action: int) -> tuple[list[float], float, bool, bool, dict]:
            self.at += action
            return [float(self.at)], 0.0, False, False, {"at": self.at}

    def render(surface: Surface, state: StepResult) -> None:
        surface.rect(
            x=_NEAR + int(state.info["at"]) * _STEP,
            y=0.45,
            w=0.04,
            h=0.12,
            color="#cc3366",
            object_id="stepper",
        )

    return GameSpec(
        channel_key="chords",
        make_env=lambda: Steps(),  # pyright: ignore[reportArgumentType]
        render=render,
        # A chord is a sequence of keys, and it means something neither key does.
        action_bindings={
            "ArrowRight": 1,
            "ArrowUp": 2,
            ("ArrowUp", "ArrowRight"): 5,
        },
        default_action=0,
        input_mode="single_keystroke",
        fps=_FPS,
        max_steps=200,
        countdown_seconds=0,
    )


def test_two_keys_held_together_are_their_own_action_under_a_real_keyboard(
    page: Page,
) -> None:
    """The chord fires, and it is not either of the keys in it.

    The arrival completes the chord, so the press is worth five rather than the two
    of the key that arrived or the one of the key already down.
    """
    study = Study(
        ContentPage("start", "# Ready"),
        Game("play", _chord_game()),
        ContentPage("end", "# Thank you"),
    )
    with serving(study) as address:
        play_to_the_canvas(page, address)
        page.locator("canvas").click()
        page.keyboard.down("ArrowRight")
        page.wait_for_timeout(300)
        page.keyboard.down("ArrowUp")
        page.wait_for_timeout(400)
        page.keyboard.up("ArrowUp")
        page.keyboard.up("ArrowRight")
        page.wait_for_timeout(400)
        moved = _steps_taken(page)

    assert moved == 6, (
        f"one press of ArrowRight and one of the chord should be 1 + 5; got {moved}"
    )
