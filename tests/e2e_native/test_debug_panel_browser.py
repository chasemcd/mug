"""The debug drawer, in a real browser, over a study a model seat is playing.

The server tests hold the notes: the chain of one decision is written down, a reply
nobody could read is its own fault, and the credential is never in one. None of that
says a **person** can see any of it. The drawer is the part that has to work in the
hand: it has to appear when the study is in debug mode, hold the prompt and the reply
of an inference that really happened, and be reachable without a mouse.

Two of the three things asked here are about what it must **not** do.

It must not appear for a participant. A note holds prompts and what a participant
wrote, so a study that is not in debug mode must have no drawer, no toggle, and
nothing to open -- not a hidden one, and not one the server refuses to fill.

It must not resize the game. The picture a participant plays is the size the study
drew it (``Game(size=)``), and a panel that took part of the width would shrink the
kitchen to make room for a debugging aid. So the game is measured with the drawer
shut and again with it open, and the two must be the same.

These tests need Chromium. Run them with ``pytest tests/e2e_native``.

These modules use ASD-STE100 Simplified Technical English.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest
from example_server import serving
from playwright.sync_api import Page

from mug.authoring import (
    Fallback,
    History,
    LLMAgent,
    Provider,
    Thoughts,
    Transcript,
)
from mug.content import Game, Human, Model, Study
from mug.content import Page as ContentPage
from mug.content.seats import MultiSeatGame
from mug.game.surface import Surface
from mug.providers import ModelCall, ModelCompletion, Usage

pytestmark = pytest.mark.e2e

_WINDOW = {"width": 1440, "height": 900}
_SIZE = (225, 180)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TS_ROOT = _REPO_ROOT / "ts"
_SHELL = _TS_ROOT / "src" / "client" / "index.html"
_DIST_WEB = _TS_ROOT / "dist-web"
_BOOTSTRAP = _DIST_WEB / "client" / "bootstrap.js"


def _ts_web_root(tmp_path: Path) -> Path:
    """Copy the built TypeScript client where a server can serve it."""
    if not _BOOTSTRAP.exists():
        pytest.skip("ts/dist-web is not built; run `npm run build:web` in ts/")
    shutil.copy(_SHELL, tmp_path / "index.html")
    shutil.copy(_REPO_ROOT / "mug" / "webclient" / "app.css", tmp_path / "app.css")
    shutil.copytree(_DIST_WEB / "client", tmp_path / "client")
    shutil.copytree(_DIST_WEB / "kernel", tmp_path / "kernel")
    return tmp_path

# What the study puts in its prompt and what the model answers with. Both are
# deliberately unmistakable: what is read off the screen has to be the real prompt
# and the real reply, not a label the client made up.
_IN_THE_PROMPT = "the pot on the left is nearly ready"
_IN_THE_REPLY = "plating up now"


class _Cook(LLMAgent):
    """A partner on a keyless local runner, so no credential is in play here."""

    provider = Provider.OSS
    model = "fake-local"
    decides_every = 5
    on_timeout = Fallback.REPEAT_LAST

    def available_actions(self, env: Any, agent_id: str) -> list[str]:
        return ["LEFT", "STAY", "RIGHT"]

    def get_prompt(
        self,
        env: Any,
        agent_id: str,
        history: History,
        chat: Transcript,
        thoughts: Thoughts,
    ) -> str:
        return f"you are the {agent_id}. {_IN_THE_PROMPT}"

    def parse_reply(self, reply: str, env: Any, agent_id: str) -> int | None:
        for index, name in enumerate(self.available_actions(env, agent_id)):
            if name in reply:
                return index
        return None

    def say(self, reply: str, env: Any, agent_id: str) -> str | None:
        for line in reply.splitlines():
            if line.startswith("SAY:"):
                return line.split(":", 1)[1].strip()
        return None


async def _answers(call: ModelCall) -> ModelCompletion:
    """A local adapter that answers in the shape the study reads."""
    return ModelCompletion(
        outcome="completed",
        resolved_model="fake-local",
        usage=Usage(input_tokens=9, output_tokens=5, cost_micros=0),
        output={"text": f"RIGHT\nSAY: {_IN_THE_REPLY}"},
    )


class _Kitchen:
    """A two-seat environment that runs long enough to be watched."""

    AGENTS = ("chef", "partner")

    def __init__(self) -> None:
        self._t = 0

    def reset(self) -> Any:
        from mug.game.multiseat import MultiStepResult

        self._t = 0
        return MultiStepResult(
            observations={one: [0.0] for one in self.AGENTS},
            rewards=dict.fromkeys(self.AGENTS, 0.0),
            terminated=False,
            truncated=False,
            info={"at": 0},
        )

    def step(self, actions: Any) -> Any:
        from mug.game.multiseat import MultiStepResult

        self._t += 1
        return MultiStepResult(
            observations={one: [float(self._t)] for one in self.AGENTS},
            rewards=dict.fromkeys(self.AGENTS, 0.0),
            terminated=self._t >= 200,
            truncated=False,
            info={"at": self._t},
        )


def _draw(surface: Surface, state: Any) -> None:
    """Draw a floor and one thing that moves, so the canvas is a real picture."""
    surface.rect(
        x=0.0, y=0.0, w=1.0, h=0.6, color="#8b6b3f", object_id="floor", persistent=True
    )
    at = (float(state.info.get("at", 0)) % 10) / 10
    surface.circle(x=at, y=0.8, radius=0.06, color="#2d6cdf", object_id="walker")


def _study() -> Study:
    return Study(
        ContentPage("start", "# Ready\n\nPress continue to play."),
        Game(
            "play",
            MultiSeatGame(
                make_env=_Kitchen,
                render=_draw,
                channel_key="kitchen",
                fps=10,
                max_steps=200,
                default_action=1,
                action_bindings={"ArrowLeft": 0, "ArrowRight": 2},
            ),
            seats={"chef": Human(), "partner": Model(_Cook(), adapter=_answers)},
            size=_SIZE,
        ),
        ContentPage("end", "# Thank you"),
    )


_CANVAS = """
() => {
  const box = document.querySelector('canvas').getBoundingClientRect();
  return {shown: box.width, high: box.height};
}
"""


def _reach_the_game(page: Page, address: str) -> None:
    page.goto(address)
    page.wait_for_selector("text=connected", timeout=15_000)
    page.get_by_role("button", name="Continue").click()
    page.wait_for_selector("canvas", timeout=15_000)


def test_a_study_that_is_not_in_debug_mode_has_no_drawer(page: Page) -> None:
    """A participant's screen holds nothing of this at all.

    Not a shut drawer, not a toggle they could find, and not a panel the server
    would refuse to fill. The client asks the server once whether it is watching;
    a server that is not has no such path, so nothing is ever built.
    """
    page.set_viewport_size(_WINDOW)
    with serving(_study()) as address:
        _reach_the_game(page, address)
        page.wait_for_timeout(1200)

        assert page.locator("[data-testid=debug-panel]").count() == 0, (
            "a participant's screen has a debug drawer on it"
        )
        assert page.locator("[data-testid=debug-toggle]").count() == 0


def _read_the_drawer(page: Page, address: str) -> str:
    """Reach the game, open the drawer, and return what it has written on it."""
    _reach_the_game(page, address)
    page.locator("[data-testid=debug-toggle]").click()
    notes = page.locator("[data-testid=debug-notes]")
    notes.locator("[data-kind='agent.action']").first.wait_for(timeout=20_000)
    return str(notes.inner_text())


def _assert_the_chain_is_on_the_screen(read: str) -> None:
    """The prompt, the reply, and the action read out of it, all of them there."""
    assert _IN_THE_PROMPT in read, (
        "the drawer never showed what the seat was asked, so the one question it "
        "exists to answer is still unanswered"
    )
    assert _IN_THE_REPLY in read, "the drawer never showed what came back"
    assert "RIGHT" in read, "the drawer never named the action that was read out"
    assert "model.reply" in read and "agent.action" in read


def test_the_drawer_holds_the_prompt_and_the_reply_of_a_real_inference(
    page: Page,
) -> None:
    """What the seat was asked and what came back, on the screen, while it plays.

    The prompt is the study's own words and the reply is the adapter's own words, so
    what is read off the screen is a real inference and not a label the client wrote
    for itself. This is the whole reason the drawer exists: a partner that stands
    still is four different faults, and only the chain tells them apart.
    """
    page.set_viewport_size(_WINDOW)
    with serving(_study(), debug=True) as address:
        read = _read_the_drawer(page, address)

    _assert_the_chain_is_on_the_screen(read)


def test_the_typescript_client_draws_the_same_drawer(
    page: Page, tmp_path: Path
) -> None:
    """Both shipped clients hold it, because a study may be served by either.

    The two clients are written apart and drift apart, and a debugging aid that
    exists in one of them is a debugging aid that is missing exactly when somebody
    switches to the other to find out why the first behaved strangely.
    """
    page.set_viewport_size(_WINDOW)
    with serving(_study(), debug=True, web_root=_ts_web_root(tmp_path)) as address:
        read = _read_the_drawer(page, address)

    _assert_the_chain_is_on_the_screen(read)


def test_the_drawer_does_not_resize_the_game(page: Page) -> None:
    """The picture stays the size the study drew it, open or shut.

    A drawer that took part of the width would shrink the kitchen to make room for a
    debugging aid, which is the wrong way round: the participant's picture is sized
    by the study and a tool for watching it must cost it nothing.
    """
    page.set_viewport_size(_WINDOW)
    with serving(_study(), debug=True) as address:
        _reach_the_game(page, address)
        page.wait_for_timeout(600)
        shut = dict(page.evaluate(_CANVAS))
        page.locator("[data-testid=debug-toggle]").click()
        page.wait_for_timeout(600)
        open_now = dict(page.evaluate(_CANVAS))

    assert (shut["shown"], shut["high"]) == (_SIZE[0], _SIZE[1]), (
        f"the picture was {shut['shown']:.0f} by {shut['high']:.0f} before the "
        "drawer was opened at all"
    )
    assert open_now == shut, (
        f"the picture went from {shut['shown']:.0f} across to "
        f"{open_now['shown']:.0f} when the drawer was opened"
    )


def test_the_drawer_opens_and_shuts_on_a_key(page: Page) -> None:
    """The backtick opens it, and it is the one key no study binds to a move.

    A drawer only a mouse can reach is a drawer nobody opens mid-round, which is
    exactly when a study is worth watching. The key must also cost the participant
    nothing: a key a game reads would be a step taken every time it was opened.
    """
    page.set_viewport_size(_WINDOW)
    with serving(_study(), debug=True) as address:
        _reach_the_game(page, address)
        drawer = page.locator("[data-testid=debug-panel]")
        drawer.wait_for(timeout=15_000)
        assert drawer.get_attribute("data-open") == "false"

        page.keyboard.press("`")
        page.wait_for_timeout(300)
        assert drawer.get_attribute("data-open") == "true", (
            "the backtick did not open the drawer"
        )

        page.keyboard.press("`")
        page.wait_for_timeout(300)
        assert drawer.get_attribute("data-open") == "false"
