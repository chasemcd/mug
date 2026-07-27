"""The screens claim ``wcag-aa``. This checks a real browser agrees.

`tests/unit/content/test_accessibility_profiles.py` proves the declaration is
internally honest. A declaration nothing verifies is still a claim, so this drives
a headless Chromium through the shipped screens and checks the two things the `aa`
profile commits to: a participant can reach and operate every control with the
keyboard alone, and every control has an accessible name a screen reader would read.

It runs against both shipped clients, because the profile is declared once and both
of them have to meet it.

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

from mug.app import build_study_app
from mug.content import Choice, Form, Likert, Study, Text
from mug.content import Page as StudyPage
from mug.gateway import Gateway
from mug.storage import InMemoryStore

pytestmark = pytest.mark.e2e

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TS_ROOT = _REPO_ROOT / "ts"
_SHELL = _TS_ROOT / "src" / "client" / "index.html"
_DIST_WEB = _TS_ROOT / "dist-web"
_BOOTSTRAP = _DIST_WEB / "client" / "bootstrap.js"


def _study() -> Study:
    """A study of the screens that claim ``wcag-aa``: content, then a form."""
    return Study(
        StudyPage("intro", "# Welcome\n\nRead this, then answer three questions."),
        Form(
            "survey",
            Choice("agree", "Do you consent to take part?", ["yes", "no"]),
            Likert("mood", "How do you feel right now?", scale=5),
            Text("comment", "Anything you want to tell us?"),
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
    """Run the study on a background server and yield its base url."""
    app = build_study_app(
        study=_study(),
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
def a11y_server_url() -> Iterator[str]:
    """Serve the study through the bundled JavaScript client."""
    yield from _serve(None)


@pytest.fixture
def ts_a11y_server_url(tmp_path: Path) -> Iterator[str]:
    """Serve the same study through the TypeScript client."""
    if subprocess.run(["which", "node"], capture_output=True).returncode != 0:
        pytest.skip("node is not on the path")
    if not _BOOTSTRAP.exists():
        pytest.skip("ts/dist-web is not built; run `npm run build:web` in ts/")
    shutil.copy(_SHELL, tmp_path / "index.html")
    shutil.copytree(_DIST_WEB / "client", tmp_path / "client")
    shutil.copytree(_DIST_WEB / "kernel", tmp_path / "kernel")
    yield from _serve(tmp_path)


def _walk_the_study_with_the_keyboard(page: Page, url: str) -> None:
    """Reach the debrief using the keyboard alone, checking accessible names."""
    page.goto(url)
    expect(page.get_by_text("Read this")).to_be_visible(timeout=20_000)

    # The instructions are a named region a keyboard can reach, so a participant
    # who cannot use a mouse can still scroll them.
    region = page.get_by_role("region", name="Study instructions")
    expect(region).to_be_visible()

    # Continue without touching the mouse.
    page.keyboard.press("Tab")
    page.get_by_role("button", name="Continue").press("Enter")
    consent = page.get_by_role("group", name="Do you consent to take part?")
    expect(consent).to_be_visible(timeout=10_000)

    # Every question is a named group or a labelled control: this is what a screen
    # reader reads out, and asking by name is how the test proves the name exists.
    mood = page.get_by_role("group", name="How do you feel right now?")
    expect(mood).to_be_visible()
    expect(page.get_by_label("Anything you want to tell us?")).to_be_visible()

    # Answer with the keyboard only.
    page.get_by_role("radio", name="yes").check()
    page.get_by_role("radio", name="4").check()
    page.get_by_label("Anything you want to tell us?").fill("it was clear")
    page.get_by_role("button", name="Continue").press("Enter")

    expect(page.get_by_text("Thank you")).to_be_visible(timeout=10_000)


def _status_is_announced(page: Page) -> None:
    """The connection status changes on its own, so it is a live status region."""
    expect(page.get_by_role("status")).to_be_attached()


def test_the_bundled_client_meets_the_profile_it_declares(
    page: Page, a11y_server_url: str
) -> None:
    """The shipped JavaScript client delivers the ``wcag-aa`` it claims."""
    _walk_the_study_with_the_keyboard(page, a11y_server_url)
    _status_is_announced(page)


def test_the_typescript_client_meets_the_profile_it_declares(
    page: Page, ts_a11y_server_url: str
) -> None:
    """The TypeScript client declares the same profile, so it meets the same bar."""
    _walk_the_study_with_the_keyboard(page, ts_a11y_server_url)
