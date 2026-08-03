"""End-to-end: a real browser plays the server-mode game through the new stack.

This boots the new-stack application under uvicorn and drives it with a headless
Chromium: it answers the consent form, answers the survey, reaches the game, and
sees the debrief after the episode. It proves the browser client (the shell, the
transport, the canvas renderer, and the countdown) works in a real browser, not
only through the Python test client.

It runs the server-execution game, so it needs no Pyodide download. It is not part
of the fast unit gate; run it with ``pytest tests/e2e_native`` (Chromium required).
The full browser (Pyodide) path is proven server-side in ``tests/unit/game`` and
``tests/unit/app``; a Pyodide browser run downloads a large runtime and is left to
a manual check.
"""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator
from dataclasses import replace

import pytest
import uvicorn
from playwright.sync_api import Page, expect

from examples.mountain_car.native_env import mountain_car_spec
from mug.app import build_demo_app
from mug.gateway import Gateway
from mug.storage import InMemoryStore

pytestmark = pytest.mark.e2e


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


@pytest.fixture
def server_url() -> Iterator[str]:
    """Serve a fast server-mode game under uvicorn and yield its base url."""
    spec = replace(mountain_car_spec(), fps=4, max_steps=4, countdown_seconds=1)
    app = build_demo_app(store=InMemoryStore(), gateway=Gateway(), game=spec)
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


def test_a_participant_plays_the_server_game_in_a_real_browser(
    page: Page, server_url: str
) -> None:
    """Consent, survey, play the canvas game, then see the debrief -- in Chromium."""
    page.goto(server_url)
    page.wait_for_selector("text=connected", timeout=10_000)

    # Consent, then survey.
    page.locator("label:has(input[name='agree'][value='yes'])").click()
    page.get_by_role("button", name="Continue").click()
    page.locator("label:has(input[name='mood'][value='4'])").click()
    page.get_by_role("button", name="Continue").click()

    # The game mounts a canvas; the episode plays and the flow reaches the debrief.
    page.wait_for_selector("canvas", timeout=10_000)
    expect(page.get_by_text("Thank you")).to_be_visible(timeout=15_000)
