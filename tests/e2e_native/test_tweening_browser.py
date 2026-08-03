"""A sprite that is told to move smoothly is read, mid-move, part way there.

The legacy client tweened a sprite by its own id, whatever else the study said
about it. This one tied tweening to **persistence**, so a study that redrew a
character whole each frame -- which is what a character that changes what it is
carrying and which way it faces has to do -- had its ``tween_duration`` read and
thrown away. The chef jumped a whole square per move.

That is a capability with no effect, and the only honest test for it is to look at
the canvas **between** the two positions. A test that asserted the sprite arrived
would pass on a renderer that teleported it.

So this drives one square from one side of the canvas to the other, samples where
it is painted while the tween should be running, and holds the renderer to three
things: the square is somewhere in between, it is never ahead of where it was
sent, and it does get there in the end.

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

# Where the square starts and how far it jumps each time it moves. The jump is
# most of the canvas, so a frame caught mid-tween is unmistakably in between.
_NEAR = 0.05
_FAR = 0.75

# How long one move takes, and how many frames pass between moves. The environment
# steps ten times a second, so the tween is running for about four of the frames
# after each move -- long enough to be caught, short enough to finish before the
# next one.
_TWEEN_MS = 400
_EVERY = 8
_FPS = 10

_COLOUR = (0xCC, 0x33, 0x66)


def _walking_game(*, tween: int) -> GameSpec:
    """A game with one square that steps from side to side, and back."""

    class Walk:
        def __init__(self) -> None:
            self.frame = 0

        def reset(self, *, seed: int | None = None) -> tuple[list[float], dict]:
            self.frame = 0
            return [0.0], {"at": _NEAR}

        def step(self, action: int) -> tuple[list[float], float, bool, bool, dict]:
            self.frame += 1
            far = (self.frame // _EVERY) % 2 == 1
            at = _FAR if far else _NEAR
            return [float(self.frame)], 0.0, False, False, {"at": at}

    def render(surface: Surface, state: StepResult) -> None:
        # Not persistent, deliberately: this is the shape a character is drawn in,
        # and it is the shape whose tween used to be ignored.
        surface.rect(
            x=float(state.info["at"]),
            y=0.45,
            w=0.08,
            h=0.12,
            color="#cc3366",
            object_id="walker",
            tween_duration=tween,
        )

    return GameSpec(
        channel_key="walk",
        make_env=lambda: Walk(),  # pyright: ignore[reportArgumentType]
        render=render,
        action_bindings={},
        default_action=0,
        fps=_FPS,
        max_steps=_EVERY * 4,
        countdown_seconds=0,
    )


def _study(*, tween: int) -> Study:
    """Return the shortest study that walks a square across a canvas."""
    return Study(
        ContentPage("start", "# Ready"),
        Game("play", _walking_game(tween=tween)),
        ContentPage("end", "# Thank you"),
    )


# Where the square's left edge is right now, as a fraction of the canvas width,
# or -1 when it is not painted at all.
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


def _watch(page: Page, looks: int = 90, every: int = 40) -> list[float]:
    """Sample where the square is, often enough to catch it part way."""
    seen: list[float] = []
    for _ in range(looks):
        where = page.evaluate(_WHERE)
        if where is None:
            break
        seen.append(float(where))
        page.wait_for_timeout(every)
    return seen


def test_a_sprite_told_to_move_smoothly_is_caught_part_way_there(page: Page) -> None:
    """The square is painted between its two places, so it moved rather than jumped.

    This is the test the renderer failed: the square was only ever at one end or
    the other, because its tween was read and thrown away for not being persistent.
    """
    with serving(_study(tween=_TWEEN_MS)) as address:
        play_to_the_canvas(page, address)
        seen = [one for one in _watch(page) if one >= 0]

    assert seen, "the square was never painted"
    between = [one for one in seen if _NEAR + 0.08 < one < _FAR - 0.08]
    assert between, (
        "the square was only ever at one end or the other, so it jumped between "
        f"its two places rather than moving: {sorted(set(round(x, 2) for x in seen))}"
    )
    assert max(seen) <= _FAR + 0.02, "the square went past where it was sent"
    assert min(seen) >= _NEAR - 0.02, "the square went behind where it started"


def test_a_sprite_with_no_tween_is_only_ever_where_it_was_sent(page: Page) -> None:
    """A study that asked for no tween gets none, so the smoothing is its choice.

    Without this the first test would pass on a renderer that smoothed everything,
    which would be a different fault: an environment whose object is meant to
    appear somewhere would be shown sliding there.
    """
    with serving(_study(tween=0)) as address:
        play_to_the_canvas(page, address)
        seen = [one for one in _watch(page) if one >= 0]

    assert seen, "the square was never painted"
    between = [one for one in seen if _NEAR + 0.08 < one < _FAR - 0.08]
    assert not between, (
        f"a square that asked for no tween was smoothed anyway: {between[:5]}"
    )


def test_the_kitchen_asks_for_its_chefs_to_move_smoothly(page: Page) -> None:
    """The study half: Overcooked really does ask, so the renderer half matters.

    A renderer that tweened perfectly would still show a jumpy kitchen if the
    kitchen never asked, so what the drawing sends is checked rather than assumed.
    """
    pytest.importorskip("cogrid", reason="uv pip install cogrid==0.3.2")
    from examples.cogrid.env import draw_kitchen, kitchen_scene, make_kitchen

    surface = Surface()
    env = make_kitchen("cramped_room", 60)
    env.reset()
    draw_kitchen(surface, kitchen_scene(env, 5, 4))
    commands, _keyframe = surface.frame()

    chefs = [one for one in commands if str(one.id or "").startswith("chef-")]
    assert chefs, "the kitchen drew no chefs"
    assert all((one.tween_duration or 0) > 0 for one in chefs), (
        "a chef was drawn with no tween, so it will jump a square at a time"
    )
