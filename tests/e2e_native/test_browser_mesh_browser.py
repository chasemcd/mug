"""End to end: two real browsers play one peer-to-peer episode over real WebRTC.

Everything else in this suite simulates either the browser or the data channels,
which is what makes those tests deterministic. This one simulates nothing: two
Chromium contexts each boot Pyodide, run the shipped rollback engine, open real
`RTCPeerConnection` data channels to each other, play an episode, and submit the
capture the server records. It is the only test that proves the parts nothing else
can -- Pyodide actually runs the shipped bundle, and a real data channel actually
carries the packets.

It is slow and it needs the network (Pyodide comes from a CDN), so it is marked
``e2e`` and ``slow`` and runs outside the fast gate:

    pytest tests/e2e_native/test_browser_mesh_browser.py

Two Chromium contexts on one machine reach each other over host ICE candidates,
so no STUN or TURN server is needed here. A real deployment does need them; that
is a deployment concern, not a runtime one.
"""

from __future__ import annotations

import asyncio
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
from fastapi import FastAPI
from playwright.sync_api import Browser, Page, expect

from examples.tandem.browser_mesh_env import tandem_mesh_spec
from examples.tandem.study import tandem_study
from mug.app import build_study_app
from mug.gateway import Gateway
from mug.kernel import PrincipalRef
from mug.launch import provision_launch_ticket
from mug.participant_p2p_types import BrowserP2PConfig
from mug.storage import InMemoryStore, Store
from tests.e2e_native.browser_sim import off_thread

pytestmark = [pytest.mark.e2e, pytest.mark.slow]

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TS_ROOT = _REPO_ROOT / "ts"
_SHELL = _TS_ROOT / "src" / "client" / "index.html"
_DIST_WEB = _TS_ROOT / "dist-web"
_BOOTSTRAP = _DIST_WEB / "client" / "bootstrap.js"

_RESEARCHER = PrincipalRef(
    kind="researcher", id="researcher_019b6000-0000-7000-8000-0000000000ab"
)


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


def _ensure_web_built() -> None:
    """Build the TypeScript web client on demand; tolerate a failed build."""
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


class MeshStudy:
    """One served application, its store, and the two launch links it issued."""

    def __init__(self, base_url: str, store: Store, tickets: list[str]) -> None:
        self.base_url = base_url
        self.store = store
        self.links = [f"{base_url}/?ticket={ticket}" for ticket in tickets]


@pytest.fixture
def mesh_study(tmp_path: Path) -> Iterator[MeshStudy]:
    """Serve the TypeScript client over a short two-player Tandem mesh."""
    if subprocess.run(["which", "node"], capture_output=True).returncode != 0:
        pytest.skip("node is not on the path")
    _ensure_web_built()
    if not _BOOTSTRAP.exists():
        pytest.skip("ts/dist-web is not built; run `npm run build:web` in ts/")

    web_root = _assemble_web_root(tmp_path)
    store: Store = InMemoryStore()
    gateway = Gateway()
    # A short episode: this test is about the wiring, not about playing a long game.
    spec = replace(tandem_mesh_spec(), max_steps=20, fps=10, countdown_seconds=0)

    def build() -> tuple[FastAPI, str]:
        app = build_study_app(
            study=tandem_study(),
            store=store,
            gateway=gateway,
            browser_p2p=BrowserP2PConfig(
                channel_key="tandem", size=2, game=spec, seed=5
            ),
            require_launch=True,
            web_root=web_root,
        )
        issued = asyncio.run(
            provision_launch_ticket(gateway, store, researcher=_RESEARCHER)
        )
        return app, issued.ticket_handle

    app, second_ticket = off_thread(build)
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
        yield MeshStudy(
            f"http://127.0.0.1:{port}",
            store,
            [str(app.state.launch_ticket), second_ticket],
        )
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def _play_the_forms(page: Page) -> None:
    """Walk the author's own activities up to the game, in a real browser.

    This is the study from ``examples/tandem/study.py``: a two-part consent, an
    instructions page, and a two-question pre-survey. The bundled client renders
    them from the form specification alone, so an author writes activities and
    gets a working page with no client code.

    The wait is on the form, not on a status line: the runtime downloads while the
    participant reads, so the status has already moved on to reporting that.
    """
    page.wait_for_selector("input[name='agree'][value='yes']", timeout=30_000)
    page.locator("label:has(input[name='agree'][value='yes'])").click()
    page.locator("label:has(input[name='data-sharing'][value='yes'])").click()
    page.get_by_role("button", name="Continue").click()

    # The instructions page: the author's markdown, with nothing to answer.
    page.wait_for_selector("text=Working together", timeout=10_000)
    page.get_by_role("button", name="Continue").click()

    # The pre-survey the author wrote, on the scales the author chose.
    page.wait_for_selector("input[name='games-experience']", timeout=10_000)
    page.locator("label:has(input[name='games-experience'][value='3'])").click()
    page.locator("label:has(input[name='cooperation-comfort'][value='5'])").click()
    page.get_by_role("button", name="Continue").click()


def test_two_real_browsers_play_one_peer_to_peer_episode(
    browser: Browser, mesh_study: MeshStudy
) -> None:
    """Two Chromium contexts boot Pyodide, mesh over WebRTC, and finish a run."""
    first_context = browser.new_context()
    second_context = browser.new_context()
    try:
        first = first_context.new_page()
        second = second_context.new_page()
        first.goto(mesh_study.links[0])
        second.goto(mesh_study.links[1])

        _play_the_forms(first)
        _play_the_forms(second)

        # Pyodide downloads while the forms are answered, so the wait here is for
        # the room, not for the runtime. It is still generous: the first run of a
        # session fetches the whole Python runtime from a CDN.
        for page in (first, second):
            expect(page.locator("#status")).to_contain_text(
                "peer game finished", timeout=180_000
            )

        # The server recorded exactly one peer-authority episode for the room.
        episodes = [
            state
            for _, state in mesh_study.store.scan_aggregates()
            if isinstance(state, dict) and state.get("authority") == "peer"
        ]
        assert len(episodes) == 1
        assert episodes[0]["frame_count"] == 20
        assert episodes[0]["channel_key"] == "tandem"

        # And the study continues past the game: the author's post-survey is
        # rendered next, from the same specification, in the same browser.
        for page in (first, second):
            page.wait_for_selector("input[name='teamwork']", timeout=30_000)
            page.locator("label:has(input[name='teamwork'][value='6'])").click()
            page.locator("label:has(input[name='partner-strategy'][value='4'])").click()
            page.get_by_role("button", name="Continue").click()
            page.wait_for_selector("text=Thank you", timeout=15_000)
    finally:
        first_context.close()
        second_context.close()
