"""End to end: a real participant holds a recorded conversation in a browser.

The chat channel has been mounted on the transport for a while, but no shipped
client rendered its frames: a study that ran a conversation had to supply its own
client. This drives the whole vertical through a headless Chromium instead -- the
bundled JavaScript client and the TypeScript client both -- so "a participant
talks to the study's seat in a browser" is a thing that is shown, not a thing that
is claimed.

The seat answers through a deterministic fake adapter, so the run needs no model
and no key, and the reply text is a fact the test can wait for. What the ledger
records is covered by ``tests/unit/app/test_chat_flow.py``; what is proven here is
the screen: the participant reads the seat's message, writes one back, reads the
answer, and leaves the conversation, which advances the flow.

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
from typing import Any

import pytest
import uvicorn
from playwright.sync_api import Page, expect

from mug.agents import AgentIds
from mug.app import build_study_app
from mug.authoring import Chat, Fallback, History, LLMAgent, Provider, Thoughts
from mug.content import Choice, Form, Game, Study
from mug.content import Page as StudyPage
from mug.gateway import Gateway
from mug.participant_chat import ChatSeatSpec, ChatSpec
from mug.providers import ModelCall, ModelCompletion, Usage
from mug.storage import InMemoryStore

pytestmark = pytest.mark.e2e

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TS_ROOT = _REPO_ROOT / "ts"
_SHELL = _TS_ROOT / "src" / "client" / "index.html"
_DIST_WEB = _TS_ROOT / "dist-web"
_BOOTSTRAP = _DIST_WEB / "client" / "bootstrap.js"

_UUID = "019b6000-0000-7000-8000-{:012x}"
_SEAT_ACTOR = "actor_" + _UUID.format(0x500)
_GREETING = "Hello. What brings you here today?"


class _Interviewer(LLMAgent):
    """The study's chat seat: a keyless local runner with a fixed persona."""

    provider = Provider.OSS
    model = "fake-local"
    decides_every = 1
    on_timeout = Fallback.REPEAT_LAST

    def get_prompt(
        self,
        env: object,
        agent_id: str,
        history: History,
        chat: Chat,
        thoughts: Thoughts,
    ) -> str:
        return ""


async def _adapter(call: ModelCall) -> ModelCompletion:
    """Answer by quoting the participant, so the reply is a fact to wait for."""
    payload: Any = call.payload
    said = payload["messages"][-1]["text"]
    return ModelCompletion(
        outcome="completed",
        resolved_model="fake-local",
        usage=Usage(input_tokens=1, output_tokens=1, cost_micros=0),
        output={"text": f"You said: {said}"},
    )


def _chat_study() -> Study:
    """A short study whose one interactive activity is a conversation."""
    return Study(
        Form("consent", Choice("agree", "Do you consent to take part?", ["yes", "no"])),
        Game("interview"),
        StudyPage("debrief", "# Thank you\n\nYou have finished the study."),
    )


def _chat_spec() -> ChatSpec:
    return ChatSpec(
        seat=ChatSeatSpec(
            agent=_Interviewer(),
            adapter=_adapter,
            ids=AgentIds(
                agent_version_id="agentver_" + _UUID.format(0x530),
                agent_definition_id="agentdef_" + _UUID.format(0x531),
                agent_key="interviewer",
                version_number=1,
                prompt_version_id="promptver_" + _UUID.format(0x540),
                fallback_policy_key="chat-fallback",
            ),
            actor_id=_SEAT_ACTOR,
        ),
        channel_key="interview",
        greeting=_GREETING,
    )


def _free_port() -> int:
    sock = socketlib.socket()
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


def _serve(web_root: Path | None) -> Iterator[str]:
    """Run the chat study on a background server and yield its base url."""
    app = build_study_app(
        study=_chat_study(),
        store=InMemoryStore(),
        gateway=Gateway(),
        chat=_chat_spec(),
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
def chat_server_url() -> Iterator[str]:
    """Serve the chat study through the bundled JavaScript client."""
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
def ts_chat_server_url(tmp_path: Path) -> Iterator[str]:
    """Serve the same chat study through the TypeScript client instead."""
    if subprocess.run(["which", "node"], capture_output=True).returncode != 0:
        pytest.skip("node is not on the path")
    _ensure_web_built()
    if not _BOOTSTRAP.exists():
        pytest.skip("ts/dist-web is not built; run `npm run build:web` in ts/")
    shutil.copy(_SHELL, tmp_path / "index.html")
    shutil.copytree(_DIST_WEB / "client", tmp_path / "client")
    shutil.copytree(_DIST_WEB / "kernel", tmp_path / "kernel")
    yield from _serve(tmp_path)


def _hold_a_conversation(page: Page, url: str) -> None:
    """Consent, talk to the seat, leave the conversation, reach the debrief."""
    page.goto(url)
    page.wait_for_selector("input[name='agree']", timeout=10_000)
    page.locator("input[name='agree'][value='yes']").check()
    page.get_by_role("button", name="Continue").click()

    # The seat opens the conversation, so the participant reads before writing.
    expect(page.get_by_text(_GREETING)).to_be_visible(timeout=10_000)

    page.get_by_label("Your message").fill("I am here for the study.")
    page.get_by_role("button", name="Send").click()

    # The participant's own message shows at once -- the mount does not echo it --
    # and the seat's answer arrives on the socket.
    expect(page.get_by_text("You: I am here for the study.")).to_be_visible()
    expect(page.get_by_text("Them: You said: I am here for the study.")).to_be_visible(
        timeout=10_000
    )

    # Leaving the conversation is what advances the flow to the debrief.
    page.get_by_role("button", name="End the conversation").click()
    expect(page.get_by_text("Thank you")).to_be_visible(timeout=10_000)


def test_a_participant_holds_a_conversation_in_the_bundled_client(
    page: Page, chat_server_url: str
) -> None:
    """The shipped JavaScript client renders the chat frames it is sent."""
    _hold_a_conversation(page, chat_server_url)


def test_a_participant_holds_a_conversation_in_the_typescript_client(
    page: Page, ts_chat_server_url: str
) -> None:
    """The TypeScript client renders the same conversation the same way.

    It used to close the socket on the first chat frame: an unknown frame type was
    a wire violation, and a conversation is made of them.
    """
    _hold_a_conversation(page, ts_chat_server_url)
