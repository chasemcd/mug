"""A page in a real browser writes state, and a later activity is delivered it.

`tests/unit/app/test_participant_state.py` drives the whole server path over the
socket. What it cannot show is that the client a participant actually runs exposes
the bridge and re-reads what the server sends back. So this drives a headless
Chromium through the shipped JavaScript client and uses the page bridge the way a
study's own page would: read what is carried, write a namespace, walk on, and find
it delivered to the next activity.

It is not part of the fast unit gate; run it with ``pytest tests/e2e_native``
(Chromium required).
"""

from __future__ import annotations

import socket as socketlib
import threading
import time
from collections.abc import Iterator

import pytest
import uvicorn
from playwright.sync_api import Page, expect

from mug.app import build_study_app
from mug.content import Choice, Form, Study
from mug.content import Page as StudyPage
from mug.gateway import Gateway
from mug.storage import InMemoryStore
from mug.visits.state import State

pytestmark = pytest.mark.e2e


def _study() -> Study:
    """Two screens and two namespaces: one the participant keeps, one they cannot."""
    return Study(
        Form(
            "consent",
            Choice("agree", "Do you consent to take part?", ["yes", "no"]),
        ),
        StudyPage("middle", "# Halfway"),
        StudyPage("debrief", "# Thank you"),
        state=[State("progress"), State("scoring", write="study")],
    )


def _free_port() -> int:
    sock = socketlib.socket()
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


@pytest.fixture
def state_server_url() -> Iterator[str]:
    """Serve the study through the bundled JavaScript client."""
    app = build_study_app(study=_study(), store=InMemoryStore(), gateway=Gateway())
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


def test_a_page_writes_state_and_a_later_activity_reads_it(
    page: Page, state_server_url: str
) -> None:
    """The bridge a study's own page calls, in the browser a participant runs."""
    page.goto(state_server_url)
    consent = page.get_by_role("group", name="Do you consent to take part?")
    expect(consent).to_be_visible(timeout=20_000)

    # A namespace nobody has written yet reads as empty, not as missing.
    assert page.evaluate("window.mug.state.get('progress')") == {}

    page.evaluate("window.mug.state.set('progress', {answered: ['consent']})")
    page.get_by_role("radio", name="yes").focus()
    page.keyboard.press("Space")
    page.get_by_role("button", name="Continue").click()
    expect(page.get_by_text("Halfway")).to_be_visible(timeout=10_000)

    # The next activity is delivered what the previous page wrote.
    assert page.evaluate("window.mug.state.get('progress')") == {
        "answered": ["consent"]
    }

    # A second write in the same activity names the revision the first produced.
    page.evaluate("window.mug.state.set('progress', {answered: ['consent', 'middle']})")
    page.wait_for_function(
        "() => window.mug.state.revision('progress') === 2", timeout=10_000
    )
    page.get_by_role("button", name="Continue").click()
    expect(page.get_by_text("Thank you")).to_be_visible(timeout=10_000)
    assert page.evaluate("window.mug.state.get('progress')") == {
        "answered": ["consent", "middle"]
    }


def test_a_page_cannot_write_a_namespace_the_study_keeps_to_itself(
    page: Page, state_server_url: str
) -> None:
    """R-13 through the real client: the refusal reaches the browser, and holds.

    The optimistic write is put back when the server refuses it, so the page is
    not left one revision ahead and silently failing every write after.
    """
    page.goto(state_server_url)
    consent = page.get_by_role("group", name="Do you consent to take part?")
    expect(consent).to_be_visible(timeout=20_000)

    page.evaluate("window.mug.state.set('scoring', {points: 9000})")
    # The rollback happens when the refusal arrives, so wait for it rather than
    # read a value the client has not been told about yet.
    page.wait_for_function(
        "() => window.mug.state.revision('scoring') === 0", timeout=10_000
    )
    # The value is put back to what the server holds, which is nothing: the study
    # declared this namespace readable, so it is delivered, and empty.
    assert page.evaluate("window.mug.state.get('scoring')") == {}

    # The participant carries on; a refused write is not a broken session.
    page.get_by_role("radio", name="yes").focus()
    page.keyboard.press("Space")
    page.get_by_role("button", name="Continue").click()
    expect(page.get_by_text("Halfway")).to_be_visible(timeout=10_000)
    # The refused write reached no store: the namespace is still empty.
    assert page.evaluate("window.mug.state.get('scoring')") == {}
