"""What a playing seat carries across the rest between rounds (W24).

An activity of several rounds runs one episode per round -- a fresh environment, a
fresh trajectory, and, until this was held, a fresh controller. So a model partner
walked into round two having forgotten every word of round one, while the
participant's own screen still showed the whole conversation. A partner that can be
reminded of what it agreed to and has no memory of agreeing is worse than one that
never agreed.

Three things are checked, and each was wrong in a different way:

- **the transcript carries.** It is one conversation, and the room has held it all
  along; only the seat's own view of it was thrown away each round.
- **the plan carries.** The model's thoughts are about the task, not the round.
- **the history does not**, because it is the episode's own transitions. Joining
  two rounds would make one list whose ticks run 1..n, 1..n.

And one thing that only breaks once the transcript carries: **a message must not be
delivered twice.** The watcher that feeds the seats belonged to a round and the room
outlives the round, so a watcher left behind by round one would go on writing round
two's messages into a dead episode -- and, with a carried transcript, into the same
list the live one writes to. A model would read a partner who says everything twice.

These modules use ASD-STE100 Simplified Technical English.
"""

from __future__ import annotations

import itertools
from typing import Any, cast

from fastapi.testclient import TestClient
from starlette.testclient import WebSocketTestSession

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


class _Rememberer(LLMAgent):
    """A partner whose prompt is everything it is carrying, so it can be read back.

    The prompt says exactly what the seat holds: how many messages it has been told
    about, how many plans it has carried, and how many frames of **this** episode it
    has seen. A test then reads the prompts and knows what the model knew.
    """

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
        heard = " | ".join(f"{one.sender}: {one.text}" for one in chat.last(50))
        return (
            f"messages={len(chat)} plans={len(thoughts)} frames={len(history)}\n"
            f"latest_plan={thoughts.latest}\nheard={heard}"
        )

    def reflect(self, reply: str, env: Any, agent_id: str) -> str | None:
        return f"plan after {reply}"


class _Clerk(LLMAgent):
    """A speaker in the room, so a message written in the rest has a reply to wait on.

    It is not the playing seat. It exists because a test that wrote into the rest
    between rounds and did not wait for anything would race the round it was about
    to start, and a racing test that passes says nothing.
    """

    provider = Provider.OSS
    model = "fake-local"
    decides_every = 1
    on_timeout = Fallback.WAIT

    def get_prompt(
        self,
        env: Any,
        agent_id: str,
        history: History,
        chat: Transcript,
        thoughts: Thoughts,
    ) -> str:
        return "\n".join(f"{one.sender}: {one.text}" for one in chat.last(20))


async def _clerk(call: ModelCall) -> ModelCompletion:
    if warming(call):
        return warmed()
    """Answer anything, so the room delivers a frame the test can wait for."""
    return ModelCompletion(
        outcome="completed",
        resolved_model="fake-local",
        usage=Usage(input_tokens=1, output_tokens=1, cost_micros=0),
        output={"text": "noted"},
    )


class _Adapter:
    """A keyless adapter that records every prompt it is sent."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def __call__(self, call: ModelCall) -> ModelCompletion:
        if warming(call):
            return warmed()
        payload: Any = call.payload
        self.prompts.append(str(payload["messages"][0]["content"]))
        return ModelCompletion(
            outcome="completed",
            resolved_model="fake-local",
            usage=Usage(input_tokens=1, output_tokens=1, cost_micros=0),
            output={"text": "STAY"},
        )


def _study(adapter: _Adapter) -> Study:
    """A short three-round game with one person, one model, and a conversation."""
    return Study(
        Game(
            "play",
            _kitchen(),
            seats={"car": Human(), "partner": Model(_Rememberer(), adapter=adapter)},
            episodes=_ROUNDS,
            between="Rest",
            chat=written_chat("talk", Model(_Clerk(), adapter=_clerk)),
        ),
        Page("debrief", "# Thanks"),
    )


def _kitchen() -> Any:
    """Return a two-seat environment that ends after a few frames."""
    return MultiSeatGame(
        make_env=_TwoSeats,
        channel_key="two-seats",
        fps=0,
        max_steps=4,
        default_action=1,
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


def _client(store: InMemoryStore, study: Study) -> TestClient:
    return TestClient(build_study_app(study=study, store=store, gateway=Gateway()))


def _read_until(
    socket: WebSocketTestSession, kind: str, limit: int = 400
) -> dict[str, Any]:
    for _ in range(limit):
        frame = cast("dict[str, Any]", socket.receive_json())
        if frame.get("type") == kind:
            return frame
    raise AssertionError(f"no {kind!r} frame arrived")


def _say(socket: WebSocketTestSession, text: str) -> dict[str, Any]:
    """Write one message and read the reply the room delivers back."""
    socket.send_json({"type": "chat", "text": text})
    return _read_until(socket, "chat")


def _walk_three_rounds(adapter: _Adapter) -> InMemoryStore:
    """Play the three rounds, saying one thing in each rest between them."""
    store = InMemoryStore()
    with _client(store, _study(adapter)).websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        socket.receive_json()
        for round_number in range(1, _ROUNDS):
            assert _read_until(socket, "interval")["round"] == round_number + 1
            _say(socket, f"after round {round_number}")
            socket.send_json({"type": "interval_done"})
        _read_until(socket, "delivery")
    return store


def _said(prompt: str) -> int:
    """Return how many messages one prompt says the seat was holding."""
    return int(prompt.split("messages=", 1)[1].split(" ", 1)[0])


def _plans(prompt: str) -> int:
    """Return how many carried plans one prompt says the seat was holding."""
    return int(prompt.split("plans=", 1)[1].split(" ", 1)[0])


def _frames(prompt: str) -> int:
    """Return how many frames of this episode one prompt says the seat had seen."""
    return int(prompt.split("frames=", 1)[1].split("\n", 1)[0])


def _openings(prompts: list[str]) -> list[str]:
    """Return the first prompt of each round, found by the history going back down.

    A round's own history restarts at the rest, so a frame count lower than the one
    before it is a new round beginning. It is read from the prompts rather than
    counted by the test, because the test must not assume how many decisions a
    round happened to fit in.
    """
    opening = [prompts[0]]
    for before, after in itertools.pairwise(prompts):
        if _frames(after) < _frames(before):
            opening.append(after)
    return opening


def test_the_transcript_carries_across_the_rest_between_rounds() -> None:
    """A partner told something in round one still knows it in round three.

    The participant says one thing in each rest, so a seat that remembers has read
    strictly more by the last round than by the first. A seat rebuilt each round
    reads its own empty transcript every time and never gets past one.
    """
    adapter = _Adapter()
    _walk_three_rounds(adapter)

    assert adapter.prompts, "the model was never asked to decide"
    assert _said(adapter.prompts[-1]) >= _ROUNDS - 1, (
        f"by the last round the partner was holding {_said(adapter.prompts[-1])} "
        f"messages of the {_ROUNDS - 1} the participant said: the conversation was "
        "thrown away at the rest between rounds"
    )
    assert "after round 1" in adapter.prompts[-1], (
        "the partner had forgotten what it was told in the first round"
    )


def test_the_partners_own_plan_carries_across_the_rest_between_rounds() -> None:
    """A plan is about the task, not about the round, so it is not thrown away."""
    adapter = _Adapter()
    _walk_three_rounds(adapter)

    # It must be compared where each round **starts**. Thoughts pile up inside one
    # round anyway, so the last prompt holding more than the first says nothing at
    # all about what survived the rest between them.
    opening = _openings(adapter.prompts)
    assert len(opening) == _ROUNDS, f"{len(opening)} rounds opened, not {_ROUNDS}"
    assert _plans(opening[0]) == 0, "the first round opened already carrying a plan"
    assert all(_plans(one) > 0 for one in opening[1:]), (
        f"a round opened with no carried plan (counts were "
        f"{[_plans(one) for one in opening]}): the partner's reasoning was thrown "
        "away at the rest between rounds"
    )
    assert opening[-1].splitlines()[1] != "latest_plan=None"


def test_the_history_of_one_round_does_not_leak_into_the_next() -> None:
    """Each round is its own episode, so its transitions start again at nothing.

    This is the other half of the same decision. What carried between rounds is
    exactly what was said and what was planned; a history joined across rounds
    would number two runs' frames into one list, and no reader could tell where
    one round ended.
    """
    adapter = _Adapter()
    _walk_three_rounds(adapter)

    # The frame is recorded before the decision is started, so the count is never
    # nought at prompt time. What says the history is the round's own is that it
    # goes **back down** at each round, once per rest.
    seen = [_frames(one) for one in adapter.prompts]
    restarts = sum(1 for before, after in itertools.pairwise(seen) if after < before)
    assert restarts == _ROUNDS - 1, (
        f"the history restarted {restarts} times over {_ROUNDS} rounds "
        f"(counts were {seen}): a round carried the round before it into its own "
        "trajectory"
    )


def test_a_message_is_delivered_to_a_playing_seat_exactly_once() -> None:
    """The watcher belongs to the round, so a finished round stops listening.

    With the transcript carried across rounds, a watcher left behind by round one
    writes round two's messages into the same list the live round writes to. The
    model then reads a partner who says everything twice, which no record anywhere
    would contradict.
    """
    adapter = _Adapter()
    _walk_three_rounds(adapter)

    last = adapter.prompts[-1]
    for said in (f"after round {one}" for one in range(1, _ROUNDS)):
        assert last.count(said) == 1, (
            f"{said!r} reached the partner {last.count(said)} times: a round that "
            "ended is still feeding the seats"
        )


def test_a_study_with_one_round_is_unchanged() -> None:
    """Nothing about carrying applies to an activity that plays once."""
    adapter = _Adapter()
    store = InMemoryStore()
    study = Study(
        Game(
            "play",
            _kitchen(),
            seats={"car": Human(), "partner": Model(_Rememberer(), adapter=adapter)},
            chat=written_chat("talk"),
        ),
        Page("debrief", "# Thanks"),
    )
    with _client(store, study).websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        socket.receive_json()
        _read_until(socket, "delivery")

    assert adapter.prompts, "the model was never asked to decide"
    assert all(_said(one) == 0 for one in adapter.prompts)
