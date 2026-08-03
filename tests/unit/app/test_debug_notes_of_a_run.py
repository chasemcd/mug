"""What the run writes down while a model seat plays, and who is allowed to read it.

A study with a model partner is opaque in the one place a researcher needs to see.
The partner stood still for a round: was it asked at all, what was it asked, what
came back, and could an action be read out of it? Four different faults produce one
picture on the screen -- a chef that does not move -- and the ledger tells them
apart only after the run, in a form nobody reads while the game is on.

So the run says what it is doing, and this asks two things of that.

**It has to say enough to tell the four apart.** A note that says a decision was
made is what the counters already said. What is asked here is the chain: the seat
was asked, this is the prompt, this came back, this action was read out of it, and
this is what it said.

**It has to be readable by nobody else.** The notes hold the prompt, the reply, and
what the participant wrote. A deception study's prompt says what the deception is.
So the path does not exist at all unless the process was started in debug mode, and
the resolved credential is never in a note whether it was or not.

These modules use ASD-STE100 Simplified Technical English.
"""

from __future__ import annotations

from typing import Any, cast

import httpx
from fastapi.testclient import TestClient

from mug.app import build_study_app
from mug.authoring import Fallback, History, LLMAgent, Provider, Thoughts, Transcript
from mug.content import Game, Human, Model, Page, Study
from mug.content.seats import MultiSeatGame
from mug.gateway import Gateway
from mug.providers import ModelCall, ModelCompletion, Usage
from mug.storage import InMemoryStore
from tests.support.agents import warmed, warming

# The credential the hosted seat names, and the value the resolver answers with. The
# value is what must never reach a note; the name is what a note is allowed to carry.
_SECRET_NAME = "the-study-key"
_SECRET_VALUE = "sk-live-do-not-write-this-down-9f2a"


class _Cook(LLMAgent):
    """A partner that plays and comments, on a hosted provider with a credential."""

    provider = Provider.ANTHROPIC
    model = "claude-fake-1"
    secret = _SECRET_NAME
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
        return f"you are the {agent_id}; you have played {len(history)} frames"

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


async def _speaks(call: ModelCall) -> ModelCompletion:
    if warming(call):
        return warmed()
    """A hosted adapter that answers with an action and a word, and holds the key."""
    assert call.secret == _SECRET_VALUE, "the adapter was not given the credential"
    return ModelCompletion(
        outcome="completed",
        resolved_model="claude-fake-1-20260101",
        usage=Usage(input_tokens=11, output_tokens=4, cost_micros=7),
        output={"text": "RIGHT\nSAY: taking the plates"},
    )


async def _refuses(call: ModelCall) -> ModelCompletion:
    if warming(call):
        return warmed()
    """An adapter that cannot reach its model at all, the way a real one fails."""
    raise ConnectionRefusedError("connection refused to http://localhost:11434")


async def _mumbles(call: ModelCall) -> ModelCompletion:
    if warming(call):
        return warmed()
    """An adapter whose reply holds no action anybody can read."""
    return ModelCompletion(
        outcome="completed",
        resolved_model="claude-fake-1-20260101",
        usage=Usage(input_tokens=11, output_tokens=4, cost_micros=7),
        output={"text": "I am thinking about it"},
    )


class _TwoSeats:
    """The smallest two-seat environment: it ends after four frames."""

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


def _study(adapter: Any) -> Study:
    return Study(
        Game(
            "play",
            MultiSeatGame(
                make_env=_TwoSeats,
                channel_key="two-seats",
                fps=0,
                max_steps=4,
                default_action=1,
            ),
            seats={
                "chef": Human(),
                "partner": Model(
                    _Cook(),
                    adapter=adapter,
                    resolve_secret=lambda _name: _SECRET_VALUE,
                ),
            },
        ),
        Page("debrief", "# Thanks"),
    )


def _serving(study: Study, *, debug: bool = False) -> httpx.Client:
    """Serve one study, and return the client as the httpx type that is typed.

    Starlette's ``TestClient`` **is** an ``httpx.Client``, and the base type is the
    one that carries the annotations, so a reader of what a request answered gets
    real types rather than ``Unknown``.
    """
    return TestClient(
        build_study_app(
            study=study, store=InMemoryStore(), gateway=Gateway(), debug=debug
        )
    )


def _walked(client: httpx.Client) -> None:
    """Play the study's one round to its end, reading every frame."""
    with cast("TestClient", client).websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        for _ in range(400):
            frame = cast("dict[str, Any]", socket.receive_json())
            if frame.get("type") == "delivery" and (
                frame["delivery"].get("kind") != "game"
            ):
                return
    raise AssertionError("the round never ended")


def _notes(client: httpx.Client) -> list[dict[str, Any]]:
    answer = client.get("/_debug/notes?since=0")
    assert answer.status_code == 200
    return cast("list[dict[str, Any]]", answer.json()["notes"])


def _of_kind(notes: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    return [one for one in notes if one["kind"] == kind]


def test_a_study_that_is_not_in_debug_mode_serves_nothing() -> None:
    """The notes are not a participant's to read, so the path does not exist.

    A gate that answered "you may not" would still be a gate somebody could find and
    push on. There is no route at all: the answer is the same not-found a study that
    has never heard of debugging gives, which is what the default has to be for a
    deployment that serves real participants.
    """
    client = _serving(_study(_speaks))

    assert client.get("/_debug").status_code == 404
    assert client.get("/_debug/notes").status_code == 404


def test_the_notes_tell_the_whole_chain_of_one_decision() -> None:
    """The seat was asked this, this came back, this action was read, this was said.

    Four faults look identical on the screen -- a partner that does not move -- and
    each is a different link of this chain. A run that wrote down only that a
    decision was made would tell a reader what the counters already told them.
    """
    client = _serving(_study(_speaks), debug=True)
    _walked(client)
    notes = _notes(client)

    turn = _of_kind(notes, "agent.turn")
    assert turn, "nothing said the seat was asked anything at all"
    # The label is the author's own name for the agent, not the seat number. An
    # environment that numbers its agents would otherwise label every line "1".
    assert turn[0]["subject"] == "cook", (
        f"the note is labelled {turn[0]['subject']!r}, which is not a name anybody "
        "chose"
    )
    assert turn[0]["fields"]["seat_key"] == "partner"
    assert turn[0]["fields"]["why"] == "decision"
    assert turn[0]["fields"]["model"] == "claude-fake-1"

    asked = [
        one for one in _of_kind(notes, "model.call")
        if one["fields"]["purpose"] == "decision"
    ]
    assert asked, "nothing said what the model was asked"
    prompt = asked[0]["fields"]["payload"]["messages"][0]["content"]
    assert "you are the partner" in prompt, (
        f"the prompt written down was {prompt!r}, which is not what the study wrote"
    )

    # The platform reaches the model once before the round, so the first call of a
    # run is its own and not the study's. A reader has to be able to tell them
    # apart, or the opening reply of every round reads as an answer to a question
    # nobody can find in the study.
    warming_up = [
        one for one in _of_kind(notes, "model.reply")
        if one["fields"]["purpose"] == "warm-up"
    ]
    assert warming_up, "the round was not warmed up, or the warm-up said nothing"

    came_back = [
        one for one in _of_kind(notes, "model.reply")
        if one["fields"]["purpose"] == "decision"
    ]
    assert came_back, "nothing said what came back from a decision"
    assert "taking the plates" in str(came_back[0]["fields"]["output"])
    assert came_back[0]["fields"]["input_tokens"] == 11
    assert came_back[0]["fields"]["took_ms"] >= 0

    acted = _of_kind(notes, "agent.action")
    assert acted, "nothing said what action was read out of the reply"
    assert acted[0]["fields"]["action_name"] == "RIGHT", (
        "the action was written down by its number alone, which is the one thing a "
        "reader cannot check against the study they wrote"
    )

    said = _of_kind(notes, "agent.said")
    assert said, "nothing said what the seat said"
    assert said[0]["fields"]["text"] == "taking the plates"


def test_a_reply_nobody_can_read_is_not_recorded_as_silence() -> None:
    """A reply with no action in it is its own fault, and the fallback beside it.

    "The model answered and nobody could read it" and "the model never answered" are
    two faults with two different fixes, and the seat holding a fallback action makes
    them the same picture. So the unreadable reply is written down **with the reply
    in it**, which is what a person needs to fix their own ``parse_reply``.
    """
    client = _serving(_study(_mumbles), debug=True)
    _walked(client)
    notes = _notes(client)

    missed = _of_kind(notes, "agent.unreadable")
    assert missed, (
        "a reply nobody could read an action out of left no note, so the seat just "
        "stood there and nothing anywhere says why"
    )
    assert "I am thinking about it" in str(missed[0]["fields"]["reply"])
    assert _of_kind(notes, "agent.fallback"), (
        "the seat fell back to its rule and nothing wrote down that the rule chose "
        "the action rather than the model"
    )


def test_no_note_carries_the_resolved_credential() -> None:
    """A note names a credential and never values it.

    It is the one field of a model call that must not be read, and this is the place
    it would leak from: the notes hold the whole payload, and they are served over
    HTTP. The adapter asserts it really was given the key, so this is a run where
    the value was resolved and passed, not one where there was nothing to leak.
    """
    client = _serving(_study(_speaks), debug=True)
    _walked(client)

    served = client.get("/_debug/notes?since=0").text
    assert _SECRET_VALUE not in served, (
        "the resolved credential is in what the debug path serves over HTTP"
    )
    assert _SECRET_NAME in served, (
        "the credential is not even named, so a reader cannot tell which key a "
        "failing call was made with"
    )


def test_a_reader_is_only_given_what_it_has_not_seen() -> None:
    """A panel that polls asks for what came after it, and gets that and no more.

    It is what makes polling twice a second cheap enough to be the whole transport:
    the second answer holds the notes written between the polls, not the run again.
    """
    client = _serving(_study(_speaks), debug=True)
    _walked(client)
    everything = _notes(client)
    assert len(everything) > 4

    highest = everything[-1]["sequence"]
    again = client.get(f"/_debug/notes?since={highest}").json()

    assert again["notes"] == []
    assert again["written"] == highest


def test_an_adapter_that_cannot_reach_its_model_says_so() -> None:
    """The most common real failure, and the one the ledger says least about.

    An unreachable runner, a model nobody pulled, a URL with a typo: the adapter
    raises, so the call never reaches an outcome and there is no ``ProviderError``
    to record. Every seat then falls back for the whole round, and the study looks
    like a partner that will not play rather than a runner that is not running.

    So it is written down before it is raised on, with the exception's own message
    in it, and the exception goes on exactly where it went before.
    """
    client = _serving(_study(_refuses), debug=True)
    _walked(client)
    notes = _notes(client)

    raised = _of_kind(notes, "model.raised")
    assert raised, (
        "the adapter could not reach its model and nothing wrote it down, so the "
        "run reads as a partner that would not play"
    )
    assert "connection refused" in str(raised[0]["fields"]["message"])
    assert raised[0]["fields"]["error"] == "ConnectionRefusedError"
