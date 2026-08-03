"""End-to-end: a real participant completes a study in the TypeScript client.

This is the second half of the P8 definition of done. It builds the TypeScript
participant client (`ts/dist-web`), serves it in place of the bundled JavaScript
client through the ``web_root`` seam, and drives it with a headless Chromium: it
answers the consent form, answers the survey, reaches the game, and sees the
debrief after the episode. So the same participant journey the JavaScript client
proves now runs on the TypeScript client, built on the kernel twin.

It runs the server-execution game, so it needs no Pyodide download. It is not part
of the fast unit gate; run it with ``pytest tests/e2e_native`` (Chromium required).
It builds the ``ts/`` workspace on demand and skips cleanly when ``node`` or the
build is absent.
"""

from __future__ import annotations

import shutil
import socket
import subprocess
import threading
import time
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest
import uvicorn
from playwright.sync_api import Page, expect

from examples.mountain_car.native_env import mountain_car_spec
from mug.app import build_demo_app
from mug.gateway import Gateway
from mug.storage import InMemoryStore

pytestmark = pytest.mark.e2e

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TS_ROOT = _REPO_ROOT / "ts"
_SHELL = _TS_ROOT / "src" / "client" / "index.html"
_DIST_WEB = _TS_ROOT / "dist-web"
_BOOTSTRAP = _DIST_WEB / "client" / "bootstrap.js"


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


def _ensure_web_built() -> None:
    """Build the TypeScript web client on demand; tolerate a failed build.

    The current TypeScript needs a modern node (see ``ts/.nvmrc``); on a shell that
    resolves an old system node the build produces no ``dist-web`` and the caller
    skips.
    """
    if _BOOTSTRAP.exists():
        return
    tsc = _TS_ROOT / "node_modules" / ".bin" / "tsc"
    if not tsc.exists():
        return
    subprocess.run(
        [str(tsc), "-p", "tsconfig.web.json"],
        cwd=_TS_ROOT,
        capture_output=True,
        check=False,
        timeout=180,
    )


def _assemble_web_root(destination: Path) -> Path:
    """Lay out the served root: the shell plus the compiled client and kernel."""
    shutil.copy(_SHELL, destination / "index.html")
    shutil.copy(
        _SHELL.parents[3] / "mug" / "webclient" / "app.css",
        destination / "app.css",
    )
    shutil.copytree(_DIST_WEB / "client", destination / "client")
    shutil.copytree(_DIST_WEB / "kernel", destination / "kernel")
    return destination


@pytest.fixture
def ts_server_url(tmp_path: Path) -> Iterator[str]:
    """Serve the TypeScript client over a fast server-mode game; yield its base url."""
    if subprocess.run(["which", "node"], capture_output=True).returncode != 0:
        pytest.skip("node is not on the path")
    _ensure_web_built()
    if not _BOOTSTRAP.exists():
        pytest.skip("ts/dist-web is not built; run `npm run build:web` in ts/")

    web_root = _assemble_web_root(tmp_path)
    spec = replace(mountain_car_spec(), fps=4, max_steps=4, countdown_seconds=1)
    app = build_demo_app(
        store=InMemoryStore(), gateway=Gateway(), game=spec, web_root=web_root
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


def test_a_participant_completes_a_study_in_the_typescript_client(
    page: Page, ts_server_url: str
) -> None:
    """Consent, survey, play the canvas game, then the debrief -- in the TS client."""
    page.goto(ts_server_url)
    page.wait_for_selector("text=connected", timeout=10_000)

    # Consent, then survey.
    page.locator("label:has(input[name='agree'][value='yes'])").click()
    page.get_by_role("button", name="Continue").click()
    page.locator("label:has(input[name='mood'][value='4'])").click()
    page.get_by_role("button", name="Continue").click()

    # The game mounts a canvas; the episode plays and the flow reaches the debrief.
    page.wait_for_selector("canvas", timeout=10_000)
    expect(page.get_by_text("Thank you")).to_be_visible(timeout=15_000)
