"""The picture is the size the study drew it, and smaller when there is not room.

A drawing is made of relative coordinates, so it has no size of its own: it fills
whatever it is given. The client gave it 600 by 400, always. So a kitchen of five
squares by four, whose sprites are forty-five pixels square, was painted over a
picture larger than the game in it -- every square a fifth wider than it was tall,
every sprite blurred over three times its own size, and several times the pixels to
paint on every one of thirty frames a second.

So a study says how large its picture is, and the screen draws it at that size. It
draws it **smaller**, in proportion, when there is not room -- a narrow window, a
pane beside a conversation -- and never larger.

This has to be a real browser. There is no layout without one: the size the picture
ends up is a fact about a pane, a caption, a scrollbar and a window, and every
double for those would be agreeing with the arithmetic that is under test.

These tests need Chromium. Run them with ``pytest tests/e2e_native``.

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

_FRAMES = 400
_WINDOW = {"width": 1440, "height": 900}

# The size the kitchen this file draws is drawn at: five squares by four, at
# forty-five pixels a square, which is what the legacy study drew it at.
_SIZE = (225, 180)

# How near the shape has to be. One CSS pixel of rounding on each side is far
# below anything this is measuring.
_NEAR = 0.02

# A status line as long as the shipped kitchen's. At the platform's own font it is
# half again as wide as a picture 225 across.
_STATUS = "Dishes delivered: 000     Time left: 12.3s"


def _counting_game(hud: bool = False) -> GameSpec:
    """A game that draws one moving square, for as long as it is watched."""

    class Counter:
        def __init__(self) -> None:
            self.frame = 0

        def reset(self, *, seed: int | None = None) -> tuple[list[float], dict]:
            self.frame = 0
            return [0.0], {"at": 0}

        def step(self, action: int) -> tuple[list[float], float, bool, bool, dict]:
            self.frame += 1
            return [float(self.frame)], 0.0, False, False, {"at": self.frame}

    def render(surface: Surface, state: StepResult) -> None:
        where = (state.info.get("at", 0) % 10) / 10
        surface.rect(x=where, y=0.4, w=0.1, h=0.2, color="#cc3366", object_id="block")

    return GameSpec(
        channel_key="counter",
        make_env=lambda: Counter(),  # pyright: ignore[reportArgumentType]
        render=render,
        hud=(lambda state: _STATUS) if hud else None,
        action_bindings={"ArrowRight": 1},
        default_action=0,
        fps=10,
        max_steps=_FRAMES,
        countdown_seconds=0,
    )


def _study(size: tuple[int, int] | None = None, hud: bool = False) -> Study:
    return Study(
        ContentPage("start", "# Ready\n\nPress continue to play."),
        Game("play", _counting_game(hud), size=size),
        ContentPage("end", "# Thank you"),
    )


_MEASURED = """
() => {
  const canvas = document.querySelector('canvas');
  const box = canvas.getBoundingClientRect();
  return {
    shown: box.width,
    high: box.height,
    top: box.top,
    wide: canvas.width,
    tall: canvas.height,
    window: window.innerHeight,
    density: window.devicePixelRatio || 1,
  };
}
"""


def _measure(page: Page) -> dict[str, float]:
    return {str(k): float(v) for k, v in dict(page.evaluate(_MEASURED)).items()}


def test_the_picture_is_the_size_the_study_drew_it(page: Page) -> None:
    """A study that says 225 by 180 gets 225 by 180 on the screen.

    Not larger. The room is there -- the window is 1440 by 900 -- and a picture
    fitted to the room rather than to itself is a kitchen blown up over three
    times its own sprites.
    """
    page.set_viewport_size(_WINDOW)
    with serving(_study(size=_SIZE)) as address:
        play_to_the_canvas(page, address)
        read = _measure(page)

    assert (read["shown"], read["high"]) == (_SIZE[0], _SIZE[1]), (
        f"the picture is {read['shown']:.0f} by {read['high']:.0f} where the study "
        f"drew it at {_SIZE[0]} by {_SIZE[1]}"
    )


def test_a_study_that_says_nothing_keeps_600_by_400(page: Page) -> None:
    """The default is what every game was drawn at before a study could say."""
    page.set_viewport_size(_WINDOW)
    with serving(_study()) as address:
        play_to_the_canvas(page, address)
        read = _measure(page)

    assert (read["shown"], read["high"]) == (600, 400), (
        f"a game that said nothing is {read['shown']:.0f} by {read['high']:.0f}"
    )


def test_the_picture_is_drawn_at_the_size_it_is_shown_at(page: Page) -> None:
    """The canvas holds real device pixels, so it is not blown up from a smaller one.

    Fitting by CSS alone would stretch the drawing over the canvas it was given and
    the participant would read a blurred kitchen.
    """
    page.set_viewport_size(_WINDOW)
    with serving(_study(size=_SIZE)) as address:
        play_to_the_canvas(page, address)
        read = _measure(page)

    wanted = read["shown"] * min(read["density"], 2)
    assert abs(read["wide"] - wanted) <= 2, (
        f"the canvas holds {read['wide']:.0f} pixels across and is shown "
        f"{read['shown']:.0f} across at a density of {read['density']}, so the "
        "picture is stretched from a smaller one"
    )


def test_a_picture_with_no_room_for_it_is_drawn_smaller(page: Page) -> None:
    """A window too narrow for the picture gets the picture, in proportion.

    This is the whole of what "fitted" now means. A picture that kept its size in a
    window that has no room for it overflows, and the participant plays a game they
    have to scroll sideways to see.
    """
    page.set_viewport_size(_WINDOW)
    with serving(_study(size=(900, 600))) as address:
        play_to_the_canvas(page, address)
        before = _measure(page)
        assert (before["shown"], before["high"]) == (900, 600)
        page.set_viewport_size({"width": 500, "height": 700})
        page.wait_for_timeout(400)
        after = _measure(page)

    assert after["shown"] < before["shown"], (
        f"the picture stayed {after['shown']:.0f} across in a window narrowed to "
        "500, so it is now wider than what it is in"
    )
    shape = after["shown"] / after["high"]
    assert abs(shape - 900 / 600) < _NEAR, (
        f"the picture came out {shape:.3f} to one when it was made smaller, so one "
        "side was fitted and the other was not"
    )


# The rightmost column of the status band that anything was written in, or -1 when
# nothing was. The band is drawn dark and the writing light, so the writing is what
# is lighter than the band it is on.
_LAST_INK = """
() => {
  const canvas = document.querySelector('canvas');
  const band = Math.round(canvas.height * 0.085);
  const pixels = canvas.getContext('2d').getImageData(0, 0, canvas.width, band).data;
  let last = -1;
  for (let y = 0; y < band; y++) {
    for (let x = 0; x < canvas.width; x++) {
      const at = (y * canvas.width + x) * 4;
      if (pixels[at] > 120 && pixels[at + 3] > 0 && x > last) last = x;
    }
  }
  return {last, wide: canvas.width};
}
"""


def test_the_status_line_is_not_cut_off_by_a_small_picture(page: Page) -> None:
    """A study's own status line fits the picture it is drawn on.

    The platform draws the status line onto the game's own surface, so it is in the
    record and in a replay -- which is right, and it means the line has to live
    inside whatever the study drew. The line the shipped kitchen writes is half
    again as wide as a picture 225 across at the platform's own font, so it used to
    run off the edge and the participant read "Dishes delivered: 000    Tim".

    What is read is the pixels: writing that was **cut** reaches the last column of
    the canvas, and writing that was fitted stops short of it.
    """
    page.set_viewport_size(_WINDOW)
    with serving(_study(size=_SIZE, hud=True)) as address:
        play_to_the_canvas(page, address)
        read = {str(k): int(v) for k, v in dict(page.evaluate(_LAST_INK)).items()}

    assert read["last"] > 0, "the status line was never drawn at all"
    assert read["last"] < read["wide"] - 1, (
        f"the status line reaches column {read['last']} of {read['wide']}, so it "
        "runs off the edge of the picture and the participant reads a sentence "
        "that stops in the middle of a word"
    )
