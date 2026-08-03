"""The model is reached when the participant arrives, not first met inside a round.

Two things go wrong when the first call a study makes is a call a participant is
waiting on.

**A provider that cannot be reached draws itself as a partner that stands still.**
A runner nobody started, a model nobody pulled, a credential that expired: every one
of them reaches the participant as a chef that does nothing, which is the one
picture they cannot read and the one the study cannot tell from a model that chose
to wait. Reaching the provider before the first frame turns it into something the
run knows and says.

**The first call is the slowest one.** A runner reuses its cached reading of the
longest prefix a call shares with the last one, and a model quiet for the length of a
consent form has been unloaded. Both are paid on the first call anybody makes.

**And where it is paid is the whole of it.** A warm-up in front of the round is the
same wait with another wait in front of it: measured on a local llama3.2 it took the
round starting to the chef's first move from 3.1 s to 5.1 s. The warm-up therefore
runs when the **session** is established -- minutes of consent form and instructions
before a game -- where it costs the participant nothing at all.

What must **not** happen is the warm-up changing the round it precedes. It reads an
environment of its own, so the one the round is played on is untouched; it reflects
on nothing and takes nothing from the reply, so the seat carries exactly what it
would have carried; and it names itself, so an adapter that answers by sequence --
a script, a simulation, a double -- is not thrown one answer behind.

These modules use ASD-STE100 Simplified Technical English.
"""

from __future__ import annotations

import time
from typing import Any, cast

from fastapi.testclient import TestClient

from mug.app import build_study_app
from mug.authoring import Fallback, History, LLMAgent, Provider, Thoughts, Transcript
from mug.content import Game, Human, Model, Page, Study
from mug.content.seats import MultiSeatGame
from mug.gateway import Gateway
from mug.providers import ModelCall, ModelCompletion, Usage
from mug.storage import InMemoryStore

_ROUNDS = 2

# What the study's own prompt says. A warm-up that carries these words asked the
# study's question; one that does not asked a stand-in, and warms the model without
# warming the words -- which is where most of the waiting is.
_STUDY_WORDS = "you are cooking in a kitchen"


class _Cook(LLMAgent):
    """A partner on a keyless local runner."""

    provider = Provider.OSS
    model = "fake-local"
    decides_every = 1
    on_timeout = Fallback.WAIT

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
        return f"{_STUDY_WORDS}; the pot is at {cast('_Kitchen', env).pot}"

    def reflect(self, reply: str, env: Any, agent_id: str) -> str | None:
        return reply.strip()


class _Adapter:
    """An adapter that answers **by sequence**, the way a script or a double does."""

    def __init__(self, *replies: str) -> None:
        self._replies = list(replies) or ["RIGHT"]
        self.calls: list[ModelCall] = []

    async def __call__(self, call: ModelCall) -> ModelCompletion:
        self.calls.append(call)
        said = self._replies[min(len(self.decisions) - 1, len(self._replies) - 1)]
        return ModelCompletion(
            outcome="completed",
            resolved_model="fake-local",
            usage=Usage(input_tokens=1, output_tokens=1, cost_micros=0),
            output={"text": "STAY" if call.purpose == "warm-up" else said},
        )

    @property
    def decisions(self) -> list[ModelCall]:
        return [one for one in self.calls if one.purpose == "decision"]

    @property
    def warm_ups(self) -> list[ModelCall]:
        return [one for one in self.calls if one.purpose == "warm-up"]


class _Unreachable:
    """A provider nobody can reach: the runner is not running."""

    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, call: ModelCall) -> ModelCompletion:
        self.calls += 1
        raise ConnectionRefusedError("connection refused to http://localhost:11434")


class _Kitchen:
    """A two-seat environment whose reset moves the pot, so a second one shows."""

    AGENTS = ("chef", "partner")
    made = 0

    def __init__(self) -> None:
        type(self).made += 1
        self._t = 0
        self.pot = 0
        self.resets = 0

    def reset(self) -> Any:
        from mug.game.multiseat import MultiStepResult

        self._t = 0
        self.resets += 1
        # The pot moves on every reset. A warm-up that reset the round's own
        # environment would leave the round playing a kitchen nobody arranged.
        self.pot = self.resets
        return MultiStepResult(
            observations={one: [0.0] for one in self.AGENTS},
            rewards=dict.fromkeys(self.AGENTS, 0.0),
            terminated=False,
            truncated=False,
        )

    def step(self, actions: Any) -> Any:
        from mug.game.multiseat import MultiStepResult

        self._t += 1
        return MultiStepResult(
            observations={one: [float(self._t)] for one in self.AGENTS},
            rewards=dict.fromkeys(self.AGENTS, 0.0),
            terminated=self._t >= 3,
            truncated=False,
        )


def _study(adapter: Any) -> Study:
    return Study(
        Game(
            "play",
            MultiSeatGame(
                make_env=_Kitchen,
                channel_key="kitchen",
                fps=0,
                max_steps=3,
                default_action=1,
            ),
            seats={"chef": Human(), "partner": Model(_Cook(), adapter=adapter)},
            episodes=_ROUNDS,
            between="Rest",
        ),
        Page("debrief", "# Thanks"),
    )


def _walk(store: InMemoryStore, adapter: Any) -> None:
    """Play every round of the study to the end, and wait for the warm-up to land.

    The warm-up is never awaited by the study, which is the point of it -- so a walk
    that read only the frames could finish before it had been made and would report
    that a warm-up nobody waited for had not happened yet.
    """
    app = build_study_app(study=_study(adapter), store=store, gateway=Gateway())
    with TestClient(app).websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        for _ in range(900):
            frame = cast("dict[str, Any]", socket.receive_json())
            if frame.get("type") == "interval":
                socket.send_json({"type": "interval_done"})
            elif frame.get("type") == "delivery" and (
                frame["delivery"].get("kind") != "game"
            ):
                _settled(adapter)
                return
    raise AssertionError("the study never finished")


def _settled(adapter: Any) -> None:
    """Wait until the detached warm-up has been made."""
    for _ in range(400):
        if getattr(adapter, "warm_ups", None) or getattr(adapter, "calls", 0):
            return
        time.sleep(0.02)


def test_the_model_is_reached_before_the_round_and_in_the_study_s_own_words() -> None:
    """One warm-up, before any decision, asking the study's real question.

    Asking the study's own question is what makes the warm-up worth its call: the
    runner caches its reading of the shared prefix, so the first decision of the
    round reads the short changed tail instead of the whole prompt. A stand-in
    prompt would load the model and leave every word of the study's prompt cold.
    """
    adapter = _Adapter("RIGHT")
    _walk(InMemoryStore(), adapter)

    assert adapter.warm_ups, (
        "no warm-up was made, so the first thing this study ever asked its provider "
        "was a call a participant was waiting on"
    )
    assert adapter.calls[0].purpose == "warm-up", (
        "a decision was made before the model was ever reached, so everything the "
        "warm-up buys was paid inside the round instead"
    )
    asked = str(adapter.warm_ups[0].payload["messages"][0]["content"])
    assert _STUDY_WORDS in asked, (
        f"the warm-up asked {asked!r}, which is not the study's own question -- so "
        "it warms the model and leaves every word of the real prompt cold"
    )


def test_the_warm_up_reads_an_environment_of_its_own() -> None:
    """The round is played on the environment it would have been played on.

    A warm-up needs an environment to write a prompt about, and the obvious one is
    the round's. It is also the one it must not touch: this kitchen moves its pot on
    every reset, so a warm-up that reset the round's own environment would leave the
    participant playing a kitchen nobody arranged and nothing anywhere would say so.
    """
    adapter = _Adapter("RIGHT")
    _walk(InMemoryStore(), adapter)

    played = [
        str(one.payload["messages"][0]["content"]) for one in adapter.decisions
    ]
    assert played, "the seat never decided anything"
    assert all("the pot is at 1" in one for one in played), (
        f"a round was played on a kitchen that had been reset more than once: {played}"
    )


def test_a_warm_up_does_not_take_the_first_scripted_answer() -> None:
    """An adapter that answers by sequence is not thrown one answer behind.

    A script, a simulation and a test double all answer by sequence, and a warm-up
    the adapter cannot recognise takes the answer written for the first decision --
    so every answer after it is one behind, and the study runs a script it was never
    given. The call says why it is being made, so an adapter can tell.
    """
    adapter = _Adapter("LEFT", "RIGHT")
    _walk(InMemoryStore(), adapter)

    assert adapter.decisions, "the seat never decided anything"
    first = str(adapter.decisions[0].payload["messages"][0]["content"])
    assert _STUDY_WORDS in first, (
        "the first decision was not the study's own question, so the calls are out "
        "of step with the script"
    )


def test_the_model_is_reached_once_for_the_whole_process() -> None:
    """Two rounds, one warm-up: what it buys is the runner's, not a round's.

    A model loaded for the first round is loaded for the second, and a provider that
    answered once is not asked again to prove it. A warm-up per round would be a
    cost with no reader -- and on a paid provider, a cost with a bill.
    """
    adapter = _Adapter("RIGHT")
    _walk(InMemoryStore(), adapter)

    assert len(adapter.warm_ups) == 1, (
        f"the study warmed up {len(adapter.warm_ups)} times over {_ROUNDS} rounds"
    )


def test_a_provider_nobody_can_reach_is_reported_and_does_not_stop_the_study() -> None:
    """An unreachable model is said out loud, and the participant still plays.

    Saying it is the whole point: without it the participant meets a chef that never
    moves and the study records a partner that chose to wait. Stopping the study
    instead would be worse -- a quiet partner is a study with a quiet partner, and
    that is the author's call to make, not the platform's.
    """
    broken = _Unreachable()
    store = InMemoryStore()
    _walk(store, broken)

    assert broken.calls, "the provider was never reached at all"
