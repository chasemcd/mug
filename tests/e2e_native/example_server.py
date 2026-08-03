"""Serve one study under uvicorn, for a real browser to play.

Every browser test here needs the same three things: a study wrapped around the
game it is about, a real server on a real port, and a participant who clicks
through to the canvas. The bookkeeping lives here so each test says only what it
proves.

These modules use ASD-STE100 Simplified Technical English.
"""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import uvicorn
from playwright.sync_api import Page

from mug.app import build_study_app
from mug.content import Study
from mug.content.assets import Asset
from mug.gateway import Gateway
from mug.storage import InMemoryStore

# What a blank canvas looks like, and what one drawn frame must beat. The client
# paints the canvas background in CSS, so a canvas nothing drew on holds no opaque
# pixel at all whatever size it was fitted to.
BLANK = 0


def free_port() -> int:
    """Return a port nothing is listening on."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


@contextmanager
def serving(
    study: Study, store: InMemoryStore | None = None, **mounted: Any
) -> Iterator[str]:
    """Serve one study under uvicorn and yield the address it answers on.

    ``mounted`` is whatever the application mounts beside the study -- a
    ``browser_game`` for a study the participant's own machine runs, say. It is
    passed straight through, so a test mounts what its study needs and says so.

    ``store`` lets a test read what the run recorded. A test that only drives the
    screen does not need it; one that asks what was written after the participant
    went away does, because there is no screen left to read.
    """
    app = build_study_app(
        store=store or InMemoryStore(), gateway=Gateway(), study=study, **mounted
    )
    port = free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def one_game_study(key: str, game: Any, assets: list[Asset] | None = None) -> Study:
    """Wrap one game in the shortest study a participant can walk.

    The study is one page, the game, and one page. What is proven is the game: that
    it steps, that it draws, and that the participant reaches the end of it. How a
    consent form or a survey behaves is proven elsewhere and would only make this
    slower to fail.
    """
    from mug.content import Game, Page, Step

    # A game already written as an activity is used as it is. A study that seats
    # somebody -- two chefs, a court with a partner -- is written that way, and
    # wrapping it a second time in ``Game(key, ...)`` throws its seating away: the
    # activity then mounts nothing and the participant walks past it to the last
    # page without ever meeting a canvas.
    played = game if isinstance(game, Step) else Game(key, game)
    return Study(
        Page("start", "# Ready\n\nPress continue to play."),
        played,
        Page("end", "# Thank you"),
        assets=assets or [],
    )


# Read the canvas back as a picture: how much of it was painted, how many colours
# were used, and one number that changes when anything on it moves. An image the
# browser failed to load draws nothing at all, so this catches a missing sprite
# sheet as well as a drawing that was never called.
_INK = """
() => {
  const canvas = document.querySelector('canvas');
  if (!canvas) return null;
  const pixels = canvas.getContext('2d')
    .getImageData(0, 0, canvas.width, canvas.height).data;
  const colours = new Set();
  let painted = 0;
  let signature = 0;
  for (let at = 0; at < pixels.length; at += 4) {
    if (pixels[at + 3] === 0) continue;
    painted += 1;
    colours.add((pixels[at] << 16) | (pixels[at + 1] << 8) | pixels[at + 2]);
    signature = (signature * 31 + pixels[at] + pixels[at + 1] * 3 + at) >>> 0;
  }
  return {
    painted,
    colours: colours.size,
    signature,
    pixels: canvas.width * canvas.height,
    wide: canvas.width,
    tall: canvas.height,
    shown: Math.round(canvas.getBoundingClientRect().width),
    high: Math.round(canvas.getBoundingClientRect().height),
  };
}
"""


def ink(page: Page) -> dict[str, int] | None:
    """Return what is painted on the game canvas, or None once the game has gone.

    It reads the pixels the browser really drew, so it answers the one question a
    render packet cannot: did the participant **see** anything.
    """
    read = page.evaluate(_INK)
    if read is None:
        return None
    return {str(key): int(value) for key, value in dict(read).items()}


def painted(page: Page) -> dict[str, int]:
    """Return what is painted now, and refuse to answer for a canvas that has gone."""
    read = ink(page)
    assert read is not None, "the page has no canvas"
    return read


def watch(page: Page, looks: int = 80, every: int = 100) -> list[dict[str, int]]:
    """Read the canvas repeatedly, and stop when the game is over.

    A game is a moving picture, so one reading proves almost nothing. This collects
    a series of them for as long as the canvas is on the screen, which is what a
    test needs to say that the picture changed while the participant watched.
    """
    seen: list[dict[str, int]] = []
    for _ in range(looks):
        read = ink(page)
        if read is None:
            break
        seen.append(read)
        page.wait_for_timeout(every)
    return seen


def play_to_the_canvas(page: Page, address: str) -> None:
    """Open the study, continue past the first page, and reach the drawn game."""
    page.goto(address)
    page.wait_for_selector("text=connected", timeout=15_000)
    page.get_by_role("button", name="Continue").click()
    page.wait_for_selector("canvas", timeout=15_000)
    # The countdown holds the first frames back, so the canvas exists before
    # anything is on it. Wait for paint, not for the element.
    for _ in range(150):
        read = ink(page)
        if read is not None and read["painted"] > BLANK:
            return
        page.wait_for_timeout(100)
    raise AssertionError("nothing was ever painted on the canvas")


__all__ = [
    "BLANK",
    "free_port",
    "ink",
    "one_game_study",
    "painted",
    "play_to_the_canvas",
    "serving",
    "watch",
]
