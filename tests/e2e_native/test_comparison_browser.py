"""End to end: a real participant answers a comparison in a browser.

``tests/unit/app/test_comparison_flow.py`` proves what the ledger holds. This
proves the screen: a participant plays two rounds in a headless Chromium, is shown
the two runs blinded, clicks one, and reaches the debrief -- in the bundled
JavaScript client and in the TypeScript client both, because a study should not
have to write its own client to ask a question.

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
from dataclasses import replace
from pathlib import Path

import pytest
import uvicorn
from playwright.sync_api import Page, expect

from examples.mountain_car.native_env import mountain_car_spec
from mug.app import build_study_app
from mug.authoring import Comparison
from mug.content import Game, Study
from mug.content import Page as StudyPage
from mug.gateway import Gateway
from mug.storage import InMemoryStore

pytestmark = pytest.mark.e2e

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TS_ROOT = _REPO_ROOT / "ts"
_SHELL = _TS_ROOT / "src" / "client" / "index.html"
_DIST_WEB = _TS_ROOT / "dist-web"
_BOOTSTRAP = _DIST_WEB / "client" / "bootstrap.js"

_ASK = "Which round went better?"


def _comparison_study() -> Study:
    """Two short rounds, then the one question about them."""
    return Study(
        Game("practice"),
        Game("play"),
        Comparison(
            key="which-was-better",
            ask=_ASK,
            options={"Practice": "practice", "Real round": "play"},
        ),
        StudyPage("debrief", "# Thank you\n\nYou have finished the study."),
    )


def _free_port() -> int:
    sock = socketlib.socket()
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


def _serve(web_root: Path | None) -> Iterator[str]:
    """Run the comparison study on a background server and yield its base url."""
    app = build_study_app(
        study=_comparison_study(),
        store=InMemoryStore(),
        gateway=Gateway(),
        game=replace(mountain_car_spec(), fps=0, max_steps=3, countdown_seconds=0),
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
def comparison_server_url() -> Iterator[str]:
    """Serve the comparison study through the bundled JavaScript client."""
    yield from _serve(None)


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


@pytest.fixture
def ts_comparison_server_url(tmp_path: Path) -> Iterator[str]:
    """Serve the same comparison study through the TypeScript client instead."""
    if subprocess.run(["which", "node"], capture_output=True).returncode != 0:
        pytest.skip("node is not on the path")
    _ensure_web_built()
    if not _BOOTSTRAP.exists():
        pytest.skip("ts/dist-web is not built; run `npm run build:web` in ts/")
    shutil.copy(_SHELL, tmp_path / "index.html")
    shutil.copy(
        _SHELL.parents[3] / "mug" / "webclient" / "app.css",
        tmp_path / "app.css",
    )
    shutil.copytree(_DIST_WEB / "client", tmp_path / "client")
    shutil.copytree(_DIST_WEB / "kernel", tmp_path / "kernel")
    yield from _serve(tmp_path)


def _answer_the_comparison(page: Page, url: str) -> None:
    """Play both rounds, read the two options, pick one, reach the debrief."""
    page.goto(url)
    # Both rounds run themselves at three frames with no countdown, so the
    # question is the first thing that waits for the participant.
    expect(page.get_by_text(_ASK)).to_be_visible(timeout=20_000)

    options = page.locator("[data-testid='comparison-options'] .option")
    expect(options).to_have_count(2, timeout=10_000)
    # The screen says which of the participant's own rounds each option was and
    # what it recorded. It never says which condition it was.
    expect(options.first).to_contain_text("frames")
    expect(page.get_by_text("Practice")).to_have_count(0)

    # The option is the control: an answer is given by pressing the thing it is
    # about, and sent by one submit that names what it is going to send.
    submit = page.locator("[data-testid='comparison-submit']")
    expect(submit).to_be_disabled()
    options.first.click()
    expect(submit).to_be_enabled()
    submit.click()
    expect(page.get_by_text("Thank you")).to_be_visible(timeout=10_000)


def test_a_participant_answers_a_comparison_in_the_bundled_client(
    page: Page, comparison_server_url: str
) -> None:
    """The shipped JavaScript client renders the comparison frames it is sent."""
    _answer_the_comparison(page, comparison_server_url)


def test_a_participant_answers_a_comparison_in_the_typescript_client(
    page: Page, ts_comparison_server_url: str
) -> None:
    """The TypeScript client renders the same question the same way."""
    _answer_the_comparison(page, ts_comparison_server_url)
