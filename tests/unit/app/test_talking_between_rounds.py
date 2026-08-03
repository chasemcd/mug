"""A partner answers while the participant is reading the rest between rounds.

The rest is where the round after it gets agreed. "You fetch the plates next time"
is said there or it is not said at all, because during the round both hands are on
the keys. So a partner that goes quiet for the whole rest is quiet exactly when it
is being talked to.

The seats already **heard** it: the message went into what they carry and the next
round's first prompt read it. What nothing did was answer. The participant wrote,
watched a partner that had been talking all round say nothing at all, and pressed
continue.

So the round that just ended answers. It has stopped stepping and it still holds
everything an answer needs -- the same seats, the same conversation, and the
environment standing where the round left it, which is what "we ran out of time on
that last soup" is about. Nothing is decided, because nothing is stepping: the turn
leaves a model call and, when the seat says something, a message.

These modules use ASD-STE100 Simplified Technical English.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, cast

from fastapi.testclient import TestClient

from mug.app import build_study_app
from mug.authoring import Fallback, History, LLMAgent, Provider, Thoughts, Transcript
from mug.content import Game, Human, Model, Page, Study
from mug.content.seats import MultiSeatGame
from mug.gateway import Gateway
from mug.providers import ModelCall, ModelCompletion, Usage
from mug.storage import InMemoryStore
from tests.support.agents import warmed, warming
from tests.support.chat import written_chat

_ROUNDS = 3

# How long a walk waits to see whether the resting seat starts another turn. It is
# the pause between one turn ending and the next beginning, which is a scheduling
# hop and nothing more.
_SETTLE = 0.02


class _Answerer(LLMAgent):
    """A partner that plays, and answers whatever it was last told."""

    provider = Provider.OSS
    model = "fake-local"
    # It never decides inside these four-frame rounds, so every model call the run
    # makes and every word it publishes was produced by a rest between rounds.
    # A test that could not tell the two apart would prove nothing about either.
    decides_every = 100
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
        heard = chat.last(1)
        return f"heard={heard[0].text if heard else 'nothing'}"

    def say(self, reply: str, env: Any, agent_id: str) -> str | None:
        """Say the SAY line, and nothing at all when the reply has none."""
        for line in reply.splitlines():
            if line.startswith("SAY:"):
                return line.split(":", 1)[1].strip()
        return None


class _Adapter:
    """A keyless adapter that answers what it was told, and counts its calls."""

    def __init__(self, *, quiet: bool = False, slow: float = 0.0) -> None:
        self.prompts: list[str] = []
        # How many calls were in flight at once, at the most. It is what says
        # whether the seat took its turns one at a time or all together.
        self.at_once = 0
        self.running = 0
        self._quiet = quiet
        self._slow = slow

    async def __call__(self, call: ModelCall) -> ModelCompletion:
        # The platform reaches the model once when the participant arrives, long
        # before a round. It is not a turn over this seat -- it has its own
        # throwaway seat and its own environment -- so it is neither counted as one
        # nor counted as running beside one.
        if warming(call):
            return warmed()
        payload: Any = call.payload
        prompt = str(payload["messages"][0]["content"])
        self.prompts.append(prompt)
        self.running += 1
        self.at_once = max(self.at_once, self.running)
        try:
            if self._slow:
                await asyncio.sleep(self._slow)
        finally:
            self.running -= 1
        heard = prompt.split("heard=", 1)[1]
        text = "STAY" if self._quiet else f"STAY\nSAY: you said {heard}"
        return ModelCompletion(
            outcome="completed",
            resolved_model="fake-local",
            usage=Usage(input_tokens=1, output_tokens=1, cost_micros=0),
            output={"text": text},
        )


class _TwoSeats:
    """The smallest two-seat environment: it ends after four frames."""

    AGENTS = ("car", "partner")

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
        )

    def step(self, actions: Any) -> Any:
        from mug.game.multiseat import MultiStepResult

        self._t += 1
        return MultiStepResult(
            observations={one: [float(self._t)] for one in self.AGENTS},
            rewards=dict.fromkeys(self.AGENTS, 0.0),
            terminated=self._t >= 4,
            truncated=False,
        )


def _kitchen() -> Any:
    return MultiSeatGame(
        make_env=_TwoSeats,
        channel_key="two-seats",
        fps=0,
        max_steps=4,
        default_action=1,
    )


def _study(adapter: _Adapter) -> Study:
    return Study(
        Game(
            "play",
            _kitchen(),
            seats={"car": Human(), "partner": Model(_Answerer(), adapter=adapter)},
            episodes=_ROUNDS,
            between="Rest",
            chat=written_chat("talk"),
        ),
        Page("debrief", "# Thanks"),
    )


def _client(store: InMemoryStore, study: Study) -> TestClient:
    return TestClient(build_study_app(study=study, store=store, gateway=Gateway()))


def _recorded(store: InMemoryStore, kind: str) -> int:
    """Count the records of one kind the run left behind."""
    return sum(
        1
        for aggregate_id, _ in store.scan_aggregates()
        if str(aggregate_id).startswith(f"{kind}_")
    )


def _nothing_heard() -> list[str]:
    """Return an empty, typed list of what a rest heard."""
    return []


@dataclass
class _Rest:
    """What one rest between rounds cost, told apart from the rounds around it.

    A round decides too -- every round opens by asking its seat, because at the
    opening frame the seat holds no choice for a cadence to protect. So a count
    taken over the whole run cannot say what the **rest** did. What can is the
    difference across it: the calls, the model-call records and the decision
    records before anybody spoke, and the same three once the seat has gone quiet.
    """

    heard: list[str] = field(default_factory=_nothing_heard)
    calls: int = 0
    modelcalls: int = 0
    decisions: int = 0


def _walk(store: InMemoryStore, adapter: _Adapter, *, says: list[str]) -> _Rest:
    """Play every round, saying things in the first rest, and report what it cost.

    It waits in the rest the way a participant does: for the turn its own message
    started, and not for a clock. Nothing on the server holds the next round back
    -- a participant who writes and presses continue at once must not watch a blank
    screen while a model finishes -- so a walk that pressed continue immediately
    would race the answer it came to read.
    """
    rest = _Rest()
    said_at: tuple[int, int, int] | None = None
    rests = 0
    with _client(store, _study(adapter)).websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        # Every frame is read, and nothing is thrown away: an answer said in the
        # rest arrives before the round after it, and a reader that skipped to the
        # next thing it wanted would drop exactly what it came to look for.
        for _ in range(900):
            frame = cast("dict[str, Any]", socket.receive_json())
            kind = frame.get("type")
            if kind == "chat" and frame.get("author") != "you":
                rest.heard.append(str(frame.get("text", "")))
            elif kind == "interval":
                rests += 1
                if rests == 1:
                    said_at = (
                        len(adapter.prompts),
                        _recorded(store, "modelcall"),
                        _recorded(store, "decision"),
                    )
                    for said in says:
                        socket.send_json({"type": "chat", "text": said})
                    _wait_for_the_turns(adapter)
                    rest.calls = len(adapter.prompts) - said_at[0]
                    rest.modelcalls = _recorded(store, "modelcall") - said_at[1]
                    rest.decisions = _recorded(store, "decision") - said_at[2]
                socket.send_json({"type": "interval_done"})
            elif kind == "delivery" and frame["delivery"].get("kind") != "game":
                break
    return rest


def _wait_for_the_turns(adapter: _Adapter) -> None:
    """Wait until the resting seat has stopped taking turns.

    The adapter is asked rather than the screen, because a seat is allowed to
    answer with **silence** and a walk that waited for words would wait out its
    whole budget for the one study that says nothing.

    What is waited for is the seat going quiet, not a number of turns. Two lines
    written in one tick are one turn about the second of them, and two lines a
    moment apart are two turns; both are right, so counting them would be a walk
    that only works for one of the two.
    """
    for _ in range(400):
        settled = len(adapter.prompts)
        if settled and adapter.running == 0:
            time.sleep(_SETTLE)
            if len(adapter.prompts) == settled and adapter.running == 0:
                return
        time.sleep(_SETTLE)
    raise AssertionError("the resting seat never answered anything")


def test_a_message_written_in_the_rest_is_answered() -> None:
    """The partner answers what it was told while the participant was reading.

    The seat's cadence is wider than a round, so the only thing that can answer a
    line written in the rest is the rest itself -- and what comes back has to be
    about that line rather than about anything the seat was already carrying.
    """
    adapter = _Adapter()
    store = InMemoryStore()
    rest = _walk(store, adapter, says=["fetch the plates next time"])

    assert rest.calls == 1, (
        f"the rest made {rest.calls} model calls where one line written in it "
        "should make one"
    )
    answered = [one for one in rest.heard if "fetch the plates next time" in one]
    assert answered, (
        "the partner said nothing about what it was told in the rest, so somebody "
        f"who wrote to it watched it ignore them. It said: {rest.heard}"
    )


def test_the_answer_is_a_recorded_model_call_and_not_a_decision() -> None:
    """The turn leaves the evidence a turn leaves, and invents no decision.

    Nothing is stepping, so a decision recorded here would say a seat acted on a
    frame that was never stepped, and a replay reading the run back would find an
    action with no transition under it.
    """
    adapter = _Adapter()
    store = InMemoryStore()
    rest = _walk(store, adapter, says=["are you there"])

    assert rest.modelcalls == 1, (
        f"the rest left {rest.modelcalls} model calls behind it, where the turn it "
        "took should leave exactly one -- so what the participant read has no "
        "record under it, or has more than one"
    )
    assert rest.decisions == 0, (
        f"the rest recorded {rest.decisions} decisions. Nothing was stepping, so "
        "there is no frame for an action to have been taken on, and a replay "
        "reading the run back would find an action with no transition under it"
    )


def test_a_seat_that_says_nothing_says_nothing() -> None:
    """Silence is an answer a partner is allowed to give.

    A study reads what its partner says out of the reply, and a reply with nothing
    to say produces nothing. The screen must never be given words the model did not
    produce.
    """
    quiet = _Adapter(quiet=True)
    store = InMemoryStore()
    rest = _walk(store, quiet, says=["hello"])

    assert rest.calls == 1, "the resting seat was never asked anything at all"
    assert not rest.heard, f"a silent partner was published as saying {rest.heard}"


def test_several_messages_in_one_rest_are_answered_one_turn_at_a_time() -> None:
    """Two lines written quickly do not become two turns over one seat.

    Two turns share the seat's transcript and the words it is holding to say, so the
    second would take the first one's message and publish it as its own answer --
    the participant reads one sentence twice and never gets an answer to what they
    wrote second.

    It also bounds what somebody can start. A message begins a model call, so a
    participant holding down the return key in the rest would otherwise open as many
    calls at once as they can type -- against a paid provider.

    The adapter is slow on purpose, so the second message really does arrive while
    the first turn is still running, and it counts how many calls were in flight at
    once. Reading the answers alone would not tell the two apart: run together or
    run in turn, each message is answered exactly once either way.
    """
    adapter = _Adapter(slow=0.05)
    store = InMemoryStore()
    rest = _walk(store, adapter, says=["first line", "second line"])

    assert adapter.at_once == 1, (
        f"{adapter.at_once} turns ran over one seat at once. They share its "
        "transcript, its carried thought, and the words it is holding to say"
    )
    assert rest.heard, "neither line was answered"
    assert any("second line" in one for one in rest.heard), (
        f"the partner answered {rest.heard} and never the last thing it was told"
    )
