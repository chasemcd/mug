"""End to end: a real annotator reads two model answers in a browser and picks one.

``tests/unit/app/test_generation_comparison_flow.py`` proves what the ledger holds
and what the frame carries. This proves the screen: the two recorded generations
are rendered as their text, the provider that wrote each one is nowhere on the
page, and a click reaches the debrief -- in the bundled JavaScript client and in
the TypeScript client both.

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

from mug.agents.generation import GenerationSet, ModelUnderTest
from mug.app import build_study_app
from mug.authoring import (
    Chat,
    Comparison,
    Fallback,
    History,
    LLMAgent,
    Provider,
    Thoughts,
)
from mug.content import Page as StudyPage
from mug.content import Study
from mug.gateway import Gateway
from mug.providers import ModelCall, ModelCompletion, Usage
from mug.storage import InMemoryStore

pytestmark = pytest.mark.e2e

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TS_ROOT = _REPO_ROOT / "ts"
_SHELL = _TS_ROOT / "src" / "client" / "index.html"
_DIST_WEB = _TS_ROOT / "dist-web"
_BOOTSTRAP = _DIST_WEB / "client" / "bootstrap.js"

_ASK = "Which answer is better?"
_WARM = "Gravity is the pull that brings you back down when you jump."
_DRY = "Gravity is the mutual attraction of masses."


class _Writer(LLMAgent):
    """An author's model under test: a keyless local runner."""

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


def _adapter(text: str):
    """Build a provider adapter that answers one fixed text."""

    async def answer(call: ModelCall) -> ModelCompletion:
        return ModelCompletion(
            outcome="completed",
            resolved_model="fake-local-v3",
            usage=Usage(input_tokens=1, output_tokens=1, cost_micros=0),
            output={"text": text, "vendor_trace": "provider-internal-42"},
        )

    return answer


def _generation_study() -> Study:
    """Read a page, then say which of the two recorded answers is better."""
    return Study(
        StudyPage("intro", "# Two answers\n\nRead both, then pick one."),
        Comparison(
            key="which-answer",
            ask=_ASK,
            of="model_output",
            options={"Warm": "warm-answer", "Dry": "dry-answer"},
        ),
        StudyPage("debrief", "# Thank you\n\nYou have finished the study."),
    )


def _generations() -> GenerationSet:
    return GenerationSet(
        input={"messages": [{"role": "user", "text": "Explain gravity to a child."}]},
        models={
            "warm-answer": ModelUnderTest(agent=_Writer(), adapter=_adapter(_WARM)),
            "dry-answer": ModelUnderTest(agent=_Writer(), adapter=_adapter(_DRY)),
        },
    )


def _free_port() -> int:
    sock = socketlib.socket()
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


def _serve(web_root: Path | None) -> Iterator[str]:
    """Run the generation study on a background server and yield its base url."""
    app = build_study_app(
        study=_generation_study(),
        store=InMemoryStore(),
        gateway=Gateway(),
        generate=_generations(),
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
def generation_server_url() -> Iterator[str]:
    """Serve the generation study through the bundled JavaScript client."""
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
def ts_generation_server_url(tmp_path: Path) -> Iterator[str]:
    """Serve the same generation study through the TypeScript client instead."""
    if subprocess.run(["which", "node"], capture_output=True).returncode != 0:
        pytest.skip("node is not on the path")
    _ensure_web_built()
    if not _BOOTSTRAP.exists():
        pytest.skip("ts/dist-web is not built; run `npm run build:web` in ts/")
    shutil.copy(_SHELL, tmp_path / "index.html")
    shutil.copytree(_DIST_WEB / "client", tmp_path / "client")
    shutil.copytree(_DIST_WEB / "kernel", tmp_path / "kernel")
    yield from _serve(tmp_path)


def _answer_the_comparison(page: Page, url: str) -> None:
    """Read the intro, continue, read both answers, pick one, reach the debrief."""
    page.goto(url)
    expect(page.get_by_text("Read both")).to_be_visible(timeout=20_000)
    page.get_by_role("button", name="Continue").click()

    expect(page.get_by_text(_ASK)).to_be_visible(timeout=20_000)
    options = page.locator("[data-testid='comparison-options'] button")
    expect(options).to_have_count(2, timeout=10_000)

    # The screen is the two answers themselves. Nothing on it says which model
    # wrote which, and the vendor's own fields never left the raw artifact.
    texts = sorted(option.inner_text() for option in options.all())
    assert texts == sorted([_DRY, _WARM])
    assert "provider-internal-42" not in page.content()
    assert "fake-local" not in page.content()
    expect(page.get_by_text("Warm")).to_have_count(0)

    options.first.click()
    expect(page.get_by_text("Thank you")).to_be_visible(timeout=10_000)


def test_an_annotator_answers_a_generation_comparison_in_the_bundled_client(
    page: Page, generation_server_url: str
) -> None:
    """The shipped JavaScript client renders the two generations it is sent."""
    _answer_the_comparison(page, generation_server_url)


def test_an_annotator_answers_a_generation_comparison_in_the_typescript_client(
    page: Page, ts_generation_server_url: str
) -> None:
    """The TypeScript client renders the same question the same way."""
    _answer_the_comparison(page, ts_generation_server_url)
