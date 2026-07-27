"""Parity fixture 8: the rendering conformance scene, in a real browser.

Both shipped clients drew five of the primitives functional parity asks for, and
neither kept an object model: no images, no arcs, no ellipses, no sprite atlases,
no deltas, no removal, no depth, and no tweening. So a study could not draw a
sprite, and a scene of a thousand static tiles was re-sent every frame.

This is the fixture that says otherwise. It serves the conformance scene
(``examples/render_conformance``), drives a headless Chromium to the game, and
then *looks at the canvas*: each primitive is a flat block of one colour at a
stated place, so a sampled pixel names exactly one shape. A renderer that silently
drew nothing fails here, which a screenshot nobody inspects would not.

It runs against both shipped clients, because parity is claimed once and both of
them have to meet it.

It is not part of the fast unit gate; run it with ``pytest tests/e2e_native``
(Chromium required).
"""

from __future__ import annotations

import shutil
import socket as socketlib
import subprocess
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
import uvicorn
from playwright.sync_api import Page, expect

from examples.render_conformance.scene import (
    ARC,
    CIRCLE,
    ELLIPSE,
    LINE,
    MARKER,
    OVER,
    POLYGON,
    RECT,
    conformance_spec,
    conformance_study,
)
from mug.app import build_study_app
from mug.gateway import Gateway
from mug.storage import InMemoryStore

pytestmark = pytest.mark.e2e

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TS_ROOT = _REPO_ROOT / "ts"
_SHELL = _TS_ROOT / "src" / "client" / "index.html"
_DIST_WEB = _TS_ROOT / "dist-web"
_BOOTSTRAP = _DIST_WEB / "client" / "bootstrap.js"

# The colour of the declared image and of the atlas frame the scene draws. The
# atlas has a cyan frame and a yellow one; the scene draws the second.
BADGE = "#ff00ff"
SPRITE_FRAME_ONE = "#ffff00"


def _free_port() -> int:
    sock = socketlib.socket()
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


def _serve(web_root: Path | None) -> Iterator[str]:
    """Run the conformance scene on a background server and yield its base url."""
    app = build_study_app(
        study=conformance_study(),
        game=conformance_spec(),
        store=InMemoryStore(),
        gateway=Gateway(),
        web_root=web_root,
    )
    port = _free_port()
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


@pytest.fixture
def scene_url() -> Iterator[str]:
    """Serve the conformance scene through the bundled JavaScript client."""
    yield from _serve(None)


@pytest.fixture
def ts_scene_url(tmp_path: Path) -> Iterator[str]:
    """Serve the same scene through the TypeScript client."""
    if subprocess.run(["which", "node"], capture_output=True).returncode != 0:
        pytest.skip("node is not on the path")
    if not _BOOTSTRAP.exists():
        pytest.skip("ts/dist-web is not built; run `npm run build:web` in ts/")
    shutil.copy(_SHELL, tmp_path / "index.html")
    shutil.copytree(_DIST_WEB / "client", tmp_path / "client")
    shutil.copytree(_DIST_WEB / "kernel", tmp_path / "kernel")
    yield from _serve(tmp_path)


# The script that reads one pixel back off the canvas, as `#rrggbb`. Reading the
# canvas is the point: a renderer that drew nothing is invisible to any assertion
# that only looks at the DOM.
_SAMPLE = """
([relX, relY]) => {
  const canvas = document.querySelector('canvas');
  const ctx = canvas.getContext('2d');
  const x = Math.round(relX * canvas.width);
  const y = Math.round(relY * canvas.height);
  const [r, g, b] = ctx.getImageData(x, y, 1, 1).data;
  const hex = (n) => n.toString(16).padStart(2, '0');
  return '#' + hex(r) + hex(g) + hex(b);
}
"""


def _reach_the_scene(page: Page, url: str) -> None:
    """Consent, and wait for the canvas the conformance scene draws on."""
    page.goto(url)
    page.wait_for_selector("text=connected", timeout=20_000)
    page.get_by_role("radio", name="yes").check()
    page.get_by_role("button", name="Continue").click()
    page.wait_for_selector("canvas", timeout=20_000)
    # The first frame is pushed as soon as the episode opens; give it one moment
    # to arrive and be painted before anything is sampled.
    page.wait_for_function(
        """() => {
          const canvas = document.querySelector('canvas');
          if (!canvas) return false;
          const ctx = canvas.getContext('2d');
          const [r, g, b, a] = ctx.getImageData(
            Math.round(0.05 * canvas.width), Math.round(0.05 * canvas.height), 1, 1,
          ).data;
          return a > 0 && (r > 0 || g > 0 || b > 0);
        }""",
        timeout=20_000,
    )


def _sample(page: Page, x: float, y: float) -> str:
    """Return the colour the canvas holds at one relative point."""
    return str(page.evaluate(_SAMPLE, [x, y]))


def _every_primitive_drew(page: Page) -> None:
    """Each of the eight primitives put its own colour where it said it would."""
    assert _sample(page, 0.06, 0.06) == RECT
    assert _sample(page, 0.25, 0.08) == CIRCLE
    assert _sample(page, 0.45, 0.08) == ELLIPSE
    assert _sample(page, 0.65, 0.08) == ARC
    assert _sample(page, 0.15, 0.30) == LINE
    assert _sample(page, 0.50, 0.31) == POLYGON
    # Text is drawn as glyphs, so it is asked for as "something dark is here"
    # rather than as one pixel of a known colour.
    assert _dark_pixels_near(page, 0.05, 0.44) > 0


def _dark_pixels_near(page: Page, x: float, y: float) -> int:
    """Count the dark pixels in a small box, which is how a glyph is detected."""
    return int(
        page.evaluate(
            """([relX, relY]) => {
              const canvas = document.querySelector('canvas');
              const ctx = canvas.getContext('2d');
              const x = Math.round(relX * canvas.width);
              const y = Math.round(relY * canvas.height);
              const box = ctx.getImageData(x, y - 20, 200, 30).data;
              let dark = 0;
              for (let i = 0; i < box.length; i += 4) {
                const [r, g, b, a] = [box[i], box[i+1], box[i+2], box[i+3]];
                if (a > 0 && r < 80 && g < 80 && b < 80) {
                  dark += 1;
                }
              }
              return dark;
            }""",
            [x, y],
        )
    )


def _the_declared_assets_drew(page: Page) -> None:
    """The image and the atlas frame the study declared reached the canvas."""
    assert _sample(page, 0.85, 0.07) == BADGE
    assert _sample(page, 0.85, 0.27) == SPRITE_FRAME_ONE


def _depth_decided_what_covers_what(page: Page) -> None:
    """The deeper block is on top where they overlap, and beside it is the other."""
    assert _sample(page, 0.30, 0.61) == OVER


def _the_object_moved_and_then_went_away(page: Page) -> None:
    """The persistent marker travels as a delta, then a keyframe drops it."""
    # It starts on the left.
    expect(page.locator("canvas")).to_be_visible()
    page.wait_for_function(
        _pixel_is(0.13, 0.92, MARKER),
        timeout=20_000,
    )
    # It moves right: the delta carried only this object, and the tween landed.
    page.wait_for_function(_pixel_is(0.83, 0.92, MARKER), timeout=20_000)
    # Then it is removed, and the frame that removed it is a keyframe without it.
    page.wait_for_function(_pixel_is_not(0.83, 0.92, MARKER), timeout=20_000)


def _pixel_is(x: float, y: float, colour: str) -> str:
    return _pixel_predicate(x, y, colour, equal=True)


def _pixel_is_not(x: float, y: float, colour: str) -> str:
    return _pixel_predicate(x, y, colour, equal=False)


def _pixel_predicate(x: float, y: float, colour: str, *, equal: bool) -> str:
    """Build the browser predicate that waits for one pixel to be (or stop being)."""
    comparison = "===" if equal else "!=="
    return f"""
      () => {{
        const canvas = document.querySelector('canvas');
        if (!canvas) return false;
        const ctx = canvas.getContext('2d');
        const px = Math.round({x} * canvas.width);
        const py = Math.round({y} * canvas.height);
        const [r, g, b] = ctx.getImageData(px, py, 1, 1).data;
        const hex = (n) => n.toString(16).padStart(2, '0');
        return ('#' + hex(r) + hex(g) + hex(b)) {comparison} '{colour}';
      }}
    """


def test_the_bundled_client_renders_the_conformance_scene(
    page: Page, scene_url: str
) -> None:
    """Parity fixture 8 through the shipped JavaScript client."""
    _reach_the_scene(page, scene_url)
    _every_primitive_drew(page)
    _the_declared_assets_drew(page)
    _depth_decided_what_covers_what(page)
    _the_object_moved_and_then_went_away(page)


def test_the_typescript_client_renders_the_conformance_scene(
    page: Page, ts_scene_url: str
) -> None:
    """Parity fixture 8 through the TypeScript client, which claims the same."""
    _reach_the_scene(page, ts_scene_url)
    _every_primitive_drew(page)
    _the_declared_assets_drew(page)
    _depth_decided_what_covers_what(page)
    _the_object_moved_and_then_went_away(page)
