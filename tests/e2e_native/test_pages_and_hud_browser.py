"""What a participant reads, and what they are told while they play.

Three capabilities the platform lost in the rewrite, each checked here in a real
browser because each one is only true if a participant can **see** it:

- **a written page shows the study's own pictures.** The client used to put the
  page text in a ``<pre>``: a page that said ``**W** picks up`` showed the stars,
  and a page that wanted to show which chef was the participant's could not. What
  is checked is that a real ``<img>`` reached the page and that the browser really
  decoded it -- an image element with no pixels behind it looks the same in the
  document and shows the participant nothing.
- **a picture is named, never addressed.** A page names a declared asset. A name
  the study did not declare must leave the alternative text rather than a request
  to somewhere nobody declared.
- **the status line is on the canvas.** The score and the clock were on every
  screen of the legacy study. They are drawn onto the game's own surface, so this
  reads the pixels: a band of the status colour, at the top of the canvas.

These tests need Chromium. They are not in the fast unit gate; run them with
``pytest tests/e2e_native``.

These modules use ASD-STE100 Simplified Technical English.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from example_server import painted, play_to_the_canvas, serving
from playwright.sync_api import Page

from mug.content import Game, Study
from mug.content import Page as ContentPage
from mug.content.assets import Image
from mug.game.env import StepResult
from mug.game.spec import GameSpec
from mug.game.surface import Surface

pytestmark = pytest.mark.e2e

_FRAMES = 30
_COUNTDOWN = 1

# The status band the platform draws, as the client paints it.
_BAND = (0x10, 0x14, 0x18)

_INSTRUCTIONS = """
# The kitchen

You are ![Chef with a blue hat](blue-chef =36x48) and your partner is
![Chef with a green hat](green-chef =36x48).

Move with ![The arrow keys](arrow-keys =110x110).

- **W** picks up and puts down.
- A name nobody declared shows ![this text instead](no-such-picture).
"""


def _pictures() -> list[Image]:
    """Declare the pictures the page shows, from the files the examples ship."""
    from examples.cogrid.sprites import PAGE_PICTURES

    return [
        Image(name, str(path))
        for name, path in PAGE_PICTURES.items()
        if name in ("blue-chef", "green-chef", "arrow-keys")
    ]


def _counting_game() -> GameSpec:
    """A game that draws one moving square and counts what it has delivered."""

    class Counter:
        def __init__(self) -> None:
            self.frame = 0

        def reset(self, *, seed: int | None = None) -> tuple[list[float], dict]:
            self.frame = 0
            return [0.0], {"delivered": 0}

        def step(self, action: int) -> tuple[list[float], float, bool, bool, dict]:
            self.frame += 1
            return [float(self.frame)], 0.0, False, False, {"delivered": self.frame}

    def render(surface: Surface, state: StepResult) -> None:
        where = (state.info.get("delivered", 0) % 10) / 10
        surface.rect(x=where, y=0.4, w=0.1, h=0.2, color="#cc3366", object_id="block")

    return GameSpec(
        channel_key="counter",
        make_env=lambda: Counter(),  # pyright: ignore[reportArgumentType]
        render=render,
        hud=lambda state: f"Dishes delivered: {state.info.get('delivered', 0):03d}",
        action_bindings={"ArrowRight": 1},
        default_action=0,
        fps=10,
        max_steps=_FRAMES,
        countdown_seconds=_COUNTDOWN,
    )


def _study(caption: str | None = None) -> Study:
    """Return the study these tests walk: one written page, then one game."""
    return Study(
        ContentPage("instructions", _INSTRUCTIONS),
        Game("play", _counting_game(), caption=caption),
        ContentPage("end", "# Thank you"),
        assets=list(_pictures()),
    )


def test_a_written_page_shows_the_pictures_the_study_declared(page: Page) -> None:
    """A real image reaches the page, and the browser really decoded it.

    ``naturalWidth`` is the test that matters. An ``<img>`` whose address answered
    nothing is still an ``<img>`` in the document, and a page that checked only for
    the element would pass while the participant saw a broken picture.
    """
    with serving(_study()) as address:
        page.goto(address)
        page.wait_for_selector("text=connected", timeout=15_000)
        page.wait_for_selector("img[data-asset='blue-chef']", timeout=15_000)

        loaded = page.evaluate(
            """() => [...document.querySelectorAll('img[data-asset]')].map(
                (one) => [one.dataset.asset, one.naturalWidth, one.naturalHeight])"""
        )

    assert sorted(one[0] for one in loaded) == [
        "arrow-keys",
        "blue-chef",
        "green-chef",
    ], "the page did not show every picture it named"
    for name, width, height in loaded:
        assert width > 0 and height > 0, f"the browser could not decode {name}"


def test_a_page_reads_as_written_material_rather_than_as_its_own_source(
    page: Page,
) -> None:
    """The markup a study writes is rendered; the participant never reads the stars."""
    with serving(_study()) as address:
        page.goto(address)
        page.wait_for_selector("text=connected", timeout=15_000)
        page.wait_for_selector("[data-testid='content-page'] h1", timeout=15_000)

        heading = page.locator("[data-testid='content-page'] h1").inner_text()
        bold = page.locator("[data-testid='content-page'] strong").first.inner_text()
        items = page.locator("[data-testid='content-page'] li").count()
        text = page.locator("[data-testid='content-page']").inner_text()

    assert heading.strip() == "The kitchen"
    assert bold.strip() == "W"
    assert items == 2, "the list a study wrote was not shown as a list"
    assert "**" not in text and "![" not in text, "the page showed its own source"


def test_a_picture_the_study_never_declared_shows_its_words_instead(
    page: Page,
) -> None:
    """A page cannot make a browser fetch from somewhere the study did not declare."""
    with serving(_study()) as address:
        page.goto(address)
        page.wait_for_selector("text=connected", timeout=15_000)
        page.wait_for_selector("[data-testid='content-page']", timeout=15_000)

        missing = page.locator("[data-missing-asset='no-such-picture']")
        count = missing.count()
        words = missing.inner_text() if count else ""
        images = page.locator("img[data-asset='no-such-picture']").count()

    assert count == 1 and images == 0
    assert words.strip() == "this text instead"


def test_the_status_line_is_painted_on_the_canvas_the_participant_watches(
    page: Page,
) -> None:
    """The band and its words are really on the canvas, not merely in a packet.

    A render packet full of drawing commands and a blank canvas look the same from
    the server, which is the whole reason this file opens a browser.
    """
    with serving(_study()) as address:
        page.goto(address)
        page.wait_for_selector("text=connected", timeout=15_000)
        page.get_by_role("button", name="Continue").click()
        page.wait_for_selector("canvas", timeout=15_000)
        for _ in range(150):
            if painted(page)["painted"] > 0:
                break
            page.wait_for_timeout(100)

        # The top band, and how much of it is the status colour. The band is the
        # full width of the canvas, so a canvas with no status line has none of it.
        band = page.evaluate(
            """() => {
              const canvas = document.querySelector('canvas');
              const height = Math.round(canvas.height * 0.085);
              const data = canvas.getContext('2d')
                .getImageData(0, 0, canvas.width, height).data;
              let band = 0;
              let ink = 0;
              for (let at = 0; at < data.length; at += 4) {
                const dark = data[at] === 16 && data[at+1] === 20
                  && data[at+2] === 24;
                if (dark) band += 1;
                else if (data[at + 3] > 0) ink += 1;
              }
              return {band, ink, of: (data.length / 4)};
            }"""
        )

    assert band["band"] > band["of"] * 0.5, (
        "the status band was not painted across the top of the canvas"
    )
    assert band["ink"] > 40, (
        "the band was painted but nothing was written on it, so the participant "
        "was shown an empty bar"
    )
    assert _BAND == (0x10, 0x14, 0x18)


def test_the_caption_a_study_writes_is_beside_the_game_it_plays(page: Page) -> None:
    """What the participant reads while they play is the study's, not the client's.

    The client used to show one study's instructions -- about arrow keys and a flag
    -- above every game any study ran.
    """
    caption = "You are ![Chef with a blue hat](blue-chef =20x27). Press **W** to lift."
    with serving(_study(caption)) as address:
        play_to_the_canvas(page, address)

        legend = page.locator("[data-testid='game-caption']")
        words = legend.inner_text()
        picture = legend.locator("img[data-asset='blue-chef']").count()
        flag = page.get_by_text("reach the flag").count()

    assert "You are" in words and "lift" in words
    assert picture == 1, "the caption did not show the picture it named"
    assert flag == 0, "the client still ships one study's instructions to all of them"


def test_a_game_with_no_caption_shows_none(page: Page) -> None:
    """A study that writes nothing beside its game has nothing beside its game."""
    with serving(_study()) as address:
        play_to_the_canvas(page, address)
        assert page.locator("[data-testid='game-caption']").count() == 0


def test_the_status_line_says_what_the_frame_says(page: Page) -> None:
    """The words change as the run does, so the participant reads the run itself."""
    with serving(_study()) as address:
        play_to_the_canvas(page, address)
        first = _band_signature(page)
        page.wait_for_timeout(1200)
        later = _band_signature(page)

    assert first != later, "the status line never changed while the run went on"


def _band_signature(page: Page) -> int:
    """Return one number for what is written on the status band right now."""
    return int(
        page.evaluate(
            """() => {
              const canvas = document.querySelector('canvas');
              const height = Math.round(canvas.height * 0.085);
              const data = canvas.getContext('2d')
                .getImageData(0, 0, canvas.width, height).data;
              let signature = 0;
              for (let at = 0; at < data.length; at += 4) {
                if (data[at] === 16 && data[at+1] === 20 && data[at+2] === 24) continue;
                signature = (signature * 31 + at + data[at]) >>> 0;
              }
              return signature;
            }"""
        )
    )


def test_the_status_line_is_a_game_the_study_asked_for(page: Page) -> None:
    """A game whose study wrote no status line is drawn without one."""
    plain = replace(_counting_game(), hud=None)
    study = Study(
        ContentPage("start", "# Ready"),
        Game("play", plain),
        ContentPage("end", "# Thank you"),
    )
    with serving(study) as address:
        play_to_the_canvas(page, address)
        band = page.evaluate(
            """() => {
              const canvas = document.querySelector('canvas');
              const height = Math.round(canvas.height * 0.085);
              const data = canvas.getContext('2d')
                .getImageData(0, 0, canvas.width, height).data;
              let band = 0;
              for (let at = 0; at < data.length; at += 4) {
                const dark = data[at] === 16 && data[at+1] === 20
                  && data[at+2] === 24;
                if (dark) band += 1;
              }
              return band;
            }"""
        )

    assert band == 0, "a study that asked for no status line was given one"
