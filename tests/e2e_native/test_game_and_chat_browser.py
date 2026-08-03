"""End to end: a game and a conversation on one screen, in both clients (NS-06).

The server side of a composed activity is held by the unit tests: one interaction,
two channels, one reader, and an anchor per message. None of that says the
participant can actually use it. Two panes on one screen have a problem no server
test can see -- **the arrow keys both steer and move a caret** -- and a client that
let the game read the keyboard while somebody was typing would pass everything on
the server and be unusable in the hand.

So this drives a real browser: the participant plays, moves the keyboard to the
message box with Tab, writes while the game is running, and moves back. What is
checked is the part that can only be wrong here -- that both panes are mounted,
that the keyboard belongs to one of them at a time and says which, and that typing
an arrow key does not drive the car.

Both clients claim the same thing, so both are asked.

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
from typing import Any

import pytest
import uvicorn
from playwright.sync_api import Page, expect

from examples.mountain_car.native_env import mountain_car_spec
from mug.agents import AgentIds
from mug.app import build_study_app
from mug.authoring import Fallback, History, LLMAgent, Provider, Thoughts, Transcript
from mug.content import Choice, Form, Game, Study
from mug.content import Page as StudyPage
from mug.gateway import Gateway
from mug.participant_chat import ChatSeatSpec, ChatSpec
from mug.providers import ModelCall, ModelCompletion, Usage
from mug.storage import InMemoryStore
from tests.support.chat import written_chat

pytestmark = pytest.mark.e2e

_REPO_ROOT = Path(__file__).resolve().parents[2]

_TS_ROOT = _REPO_ROOT / "ts"
_SHELL = _TS_ROOT / "src" / "client" / "index.html"
_DIST_WEB = _TS_ROOT / "dist-web"
_BOOTSTRAP = _DIST_WEB / "client" / "bootstrap.js"

_UUID = "019b6000-0000-7000-8000-{:012x}"
_PARTNER_ACTOR = "actor_" + _UUID.format(0x700)


class _Model(LLMAgent):
    """A study's chat seat: a keyless local runner."""

    provider = Provider.OSS
    model = "fake-local"
    decides_every = 1
    on_timeout = Fallback.REPEAT_LAST

    def get_prompt(
        self,
        env: object,
        agent_id: str,
        history: History,
        chat: Transcript,
        thoughts: Thoughts,
    ) -> str:
        # The shape the shipped example writes. A double whose prompt says nothing
        # would let the mount drop the author's words and still pass.
        return "\n".join(f"{one.sender}: {one.text}" for one in chat.last(50))


async def _adapter(call: ModelCall) -> ModelCompletion:
    """Answer with what was said, so the reply is recognisable on the screen."""
    payload: Any = call.payload
    # ``content`` is where every provider reads the words of a message. A
    # double that reads them anywhere else passes while the real model is
    # sent nothing at all.
    spoken = str(payload["messages"][-1]["content"]).splitlines()
    lines = [one for one in spoken if one.startswith("user: ")]
    said = lines[-1][len("user: ") :] if lines else spoken[-1]
    return ModelCompletion(
        outcome="completed",
        resolved_model="fake-local",
        usage=Usage(input_tokens=1, output_tokens=1, cost_micros=0),
        output={"text": f"partner heard: {said}"},
    )


def _spec() -> ChatSpec:
    """One partner seat, in the conversation that sits beside the game."""
    return written_chat(
        seat=ChatSeatSpec(
            agent=_Model(),
            adapter=_adapter,
            ids=AgentIds(
                agent_version_id="agentver_" + _UUID.format(0x730),
                agent_definition_id="agentdef_" + _UUID.format(0x731),
                agent_key="partner",
                version_number=1,
                prompt_version_id="promptver_" + _UUID.format(0x740),
                fallback_policy_key="chat-fallback",
            ),
            actor_id=_PARTNER_ACTOR,
        ),
        channel_key="talk",
    )


def _study() -> Study:
    """A study whose one game activity also carries a conversation.

    The run is long and slow on purpose: the participant has to still be playing
    while they write, because a conversation beside a finished game would prove
    nothing about the two sharing a keyboard.
    """
    game = replace(mountain_car_spec(), fps=20, max_steps=600, countdown_seconds=0)
    return Study(
        Form("consent", Choice("agree", "Do you consent to take part?", ["yes", "no"])),
        Game("play", game, chat=_spec()),
        StudyPage("debrief", "# Thank you\n\nYou have finished the study."),
    )


def _free_port() -> int:
    sock = socketlib.socket()
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


def _serve(web_root: Path | None) -> Iterator[str]:
    """Run the composed study on a background server and yield its base url."""
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
def composed_url() -> Iterator[str]:
    """Serve the composed study through the bundled JavaScript client."""
    yield from _serve(None)


@pytest.fixture
def ts_composed_url(tmp_path: Path) -> Iterator[str]:
    """Serve the same study through the TypeScript client instead."""
    if subprocess.run(["which", "node"], capture_output=True).returncode != 0:
        pytest.skip("node is not on the path")
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


def _plays_and_talks(page: Page, url: str) -> None:
    """Play and write at the same time, and keep the keyboard where it is put."""
    page.goto(url)
    page.wait_for_selector("input[name='agree']", timeout=10_000)
    page.locator("label:has(input[name='agree'][value='yes'])").click()
    page.get_by_role("button", name="Continue").click()

    # Two panes, both mounted, with the conversation beside the canvas.
    frame = page.locator("[data-testid='composed']")
    expect(frame).to_be_visible(timeout=10_000)
    expect(frame).to_have_attribute("data-placement", "beside")
    expect(page.locator("[data-testid='game-pane'] canvas")).to_be_visible()
    expect(page.locator("[data-testid='chat-pane'] [role='log']")).to_be_visible()

    # The game has the keyboard to begin with, and the screen says so.
    hint = page.locator("[data-testid='focus-hint']")
    expect(hint).to_contain_text("The game has the keyboard", timeout=10_000)

    # Tab moves it to the message box, and the screen says that too. This is the
    # whole point of the composed screen: a participant whose arrow keys stopped
    # working can see why rather than guess.
    page.keyboard.press("Tab")
    expect(hint).to_contain_text("The conversation has the keyboard")
    box = page.get_by_label("Your message")
    expect(box).to_be_focused()

    # **The arrow key moves the caret and does not steer.** This is the assertion
    # the whole test exists for, and it has to be made on the caret: if the game
    # were still reading the keyboard it would call `preventDefault` on the arrow,
    # the caret would not move, and the inserted character would land at the end.
    page.keyboard.type("go left")
    page.keyboard.press("ArrowLeft")
    page.keyboard.press("ArrowLeft")
    page.keyboard.type("X")
    expect(box).to_have_value("go leXft")

    # Tab **cycles** rather than toggling: this conversation has one channel, so
    # the stops are the canvas and the box, and one more Tab is back at the game.
    # A screen that let the browser's own Tab order take over would land on the
    # Send button instead, and the channel tabs of a two-channel room would be
    # reachable by mouse alone.
    page.keyboard.press("Tab")
    expect(hint).to_contain_text("The game has the keyboard")
    page.keyboard.press("Tab")
    expect(box).to_be_focused()

    # The message goes through while the run is still playing, and is answered.
    box.fill("go left")
    page.keyboard.press("Enter")
    expect(
        page.locator("[data-author=them] .bubble", has_text="partner heard: go left")
    ).to_be_visible(timeout=10_000)
    # The run did not end while they typed: the game pane is still the game.
    expect(page.locator("[data-testid='game-pane'] canvas")).to_be_visible()

    # Escape is the fast way back, and the keyboard is the game's again.
    page.keyboard.press("Escape")
    expect(hint).to_contain_text("The game has the keyboard")


def test_the_bundled_client_plays_and_talks_on_one_screen(
    page: Page, composed_url: str
) -> None:
    """The shipped JavaScript client mounts both panes and shares the keyboard."""
    _plays_and_talks(page, composed_url)


def test_the_typescript_client_plays_and_talks_on_one_screen(
    page: Page, ts_composed_url: str
) -> None:
    """The TypeScript client claims the same thing, so it is asked the same thing."""
    _plays_and_talks(page, ts_composed_url)
