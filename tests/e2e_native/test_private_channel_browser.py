"""End to end: a private side channel, drawn by both shipped clients (NS-05).

The server never sends a participant a channel they are not in, which is what the
unit tests hold. But a study that gives one participant a coach needs the screen to
show two conversations and keep them apart, and neither shipped client had ever
drawn more than one. A client that quietly dropped the second channel, or mixed the
two transcripts together, would pass every test on the server side.

So this drives it through a headless Chromium: the participant reads the public
channel, moves to the coaching channel, writes there, and reads an answer that
belongs to that channel and not to the other one. Both clients claim the same
thing, so both are asked.

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
from mug.participant_chat import ChatChannel, ChatSeatSpec, ChatSpec
from mug.providers import ModelCall, ModelCompletion, Usage
from mug.storage import InMemoryStore

pytestmark = pytest.mark.e2e

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TS_ROOT = _REPO_ROOT / "ts"
_SHELL = _TS_ROOT / "src" / "client" / "index.html"
_DIST_WEB = _TS_ROOT / "dist-web"
_BOOTSTRAP = _DIST_WEB / "client" / "bootstrap.js"

_UUID = "019b6000-0000-7000-8000-{:012x}"
_PARTNER_ACTOR = "actor_" + _UUID.format(0x600)
_COACH_ACTOR = "actor_" + _UUID.format(0x601)


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
        chat: Chat,
        thoughts: Thoughts,
    ) -> str:
        return ""


def _voice(name: str) -> Any:
    """Build an adapter that answers in one seat's own voice, deterministically."""

    async def adapter(call: ModelCall) -> ModelCompletion:
        payload: Any = call.payload
        said = payload["messages"][-1]["text"]
        return ModelCompletion(
            outcome="completed",
            resolved_model="fake-local",
            usage=Usage(input_tokens=1, output_tokens=1, cost_micros=0),
            output={"text": f"{name} heard: {said}"},
        )

    return adapter


def _ids(key: str) -> AgentIds:
    return AgentIds(
        agent_version_id="agentver_" + _UUID.format(0x630),
        agent_definition_id="agentdef_" + _UUID.format(0x631),
        agent_key=key,
        version_number=1,
        prompt_version_id="promptver_" + _UUID.format(0x640),
        fallback_policy_key="chat-fallback",
    )


def _coached_study() -> Study:
    """A short study whose one interactive activity is a coached conversation."""
    return Study(
        Form("consent", Choice("agree", "Do you consent to take part?", ["yes", "no"])),
        Game("talk"),
        StudyPage("debrief", "# Thank you\n\nYou have finished the study."),
    )


def _coached_spec() -> ChatSpec:
    """A partner on the public channel and a coach on a channel of its own."""
    return ChatSpec(
        seats=(
            ChatSeatSpec(
                agent=_Model(),
                adapter=_voice("partner"),
                ids=_ids("partner"),
                actor_id=_PARTNER_ACTOR,
            ),
            ChatSeatSpec(
                agent=_Model(),
                adapter=_voice("coach"),
                ids=_ids("coach"),
                actor_id=_COACH_ACTOR,
                channel="coach",
                hears=("chat",),
            ),
        ),
        channels=(
            ChatChannel(key="chat"),
            ChatChannel(key="coach", visibility="private", seats=("seat-1",)),
        ),
    )


def _free_port() -> int:
    sock = socketlib.socket()
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


def _serve(web_root: Path | None) -> Iterator[str]:
    """Run the coached study on a background server and yield its base url."""
    app = build_study_app(
        study=_coached_study(),
        store=InMemoryStore(),
        gateway=Gateway(),
        chat=_coached_spec(),
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
def coached_url() -> Iterator[str]:
    """Serve the coached study through the bundled JavaScript client."""
    yield from _serve(None)


@pytest.fixture
def ts_coached_url(tmp_path: Path) -> Iterator[str]:
    """Serve the same study through the TypeScript client instead."""
    if subprocess.run(["which", "node"], capture_output=True).returncode != 0:
        pytest.skip("node is not on the path")
    if not _BOOTSTRAP.exists():
        pytest.skip("ts/dist-web is not built; run `npm run build:web` in ts/")
    shutil.copy(_SHELL, tmp_path / "index.html")
    shutil.copytree(_DIST_WEB / "client", tmp_path / "client")
    shutil.copytree(_DIST_WEB / "kernel", tmp_path / "kernel")
    yield from _serve(tmp_path)


def _two_channels_stay_apart(page: Page, url: str) -> None:
    """Talk on both channels, and read each answer where it belongs."""
    page.goto(url)
    page.wait_for_selector("input[name='agree']", timeout=10_000)
    page.locator("input[name='agree'][value='yes']").check()
    page.get_by_role("button", name="Continue").click()

    # The client was told which channels this participant is in, and drew one tab
    # for each. A study with one channel draws none, so the tabs are the proof
    # that the manifest reached the screen.
    tabs = page.locator("[data-testid='chat-channels'] [role='tab']")
    expect(tabs).to_have_count(2, timeout=10_000)
    expect(tabs.nth(0)).to_have_attribute("data-channel", "chat")
    expect(tabs.nth(1)).to_have_attribute("data-channel", "coach")

    # A message on the public channel is answered by the partner, on that channel.
    page.get_by_label("Your message").fill("hello there")
    page.get_by_role("button", name="Send").click()
    expect(page.get_by_text("Them: partner heard: hello there")).to_be_visible(
        timeout=10_000
    )
    # The coach answered too, but on its own channel, which is not the one shown.
    expect(page.get_by_text("coach heard: hello there")).not_to_be_visible()

    # Move to the coaching channel: its answer is there, and the public one is not.
    tabs.nth(1).click()
    expect(page.get_by_text("Them: coach heard: hello there")).to_be_visible(
        timeout=10_000
    )
    expect(page.get_by_text("partner heard: hello there")).not_to_be_visible()

    # And back again: the public conversation is where it was left.
    tabs.nth(0).click()
    expect(page.get_by_text("Them: partner heard: hello there")).to_be_visible()

    page.get_by_role("button", name="End the conversation").click()
    expect(page.get_by_text("Thank you")).to_be_visible(timeout=10_000)


def test_the_bundled_client_keeps_a_private_channel_apart(
    page: Page, coached_url: str
) -> None:
    """The shipped JavaScript client draws both channels and does not mix them."""
    _two_channels_stay_apart(page, coached_url)


def test_the_typescript_client_keeps_a_private_channel_apart(
    page: Page, ts_coached_url: str
) -> None:
    """The TypeScript client claims the same thing, so it is asked the same thing."""
    _two_channels_stay_apart(page, ts_coached_url)
