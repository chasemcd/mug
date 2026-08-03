"""A conversation is an activity of its own, beside a game rather than instead of it.

A study used to write ``Game("talk")`` and hand ``build_study_app`` a conversation,
which replaced the whole game hook. Three things were wrong with that at once:

- the study said "a game" where a conversation happens;
- the recorded activity kind said the participant played a game, while the screen
  that rendered it was the chat screen -- two names for one activity, and the wrong
  one recorded;
- a study could hold a conversation **or** a game, never one of each. The keywords
  are not mutually exclusive, so ``build_study_app(study=s, game=g, chat=...)`` was
  accepted: the chat arm won and the game was dropped with nothing said.

So ``Chat`` is a step, written in the list beside ``Form``, ``Page``, and ``Game``.
"""

from __future__ import annotations

import functools
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from mug.app import build_study_app
from mug.authoring import Fallback, History, LLMAgent, Provider, Thoughts, Transcript
from mug.content import Chat, Game, Page, Study, flow_of
from mug.content.players import Human, Model
from mug.game.env import StepResult
from mug.game.surface import Surface
from mug.gateway import Gateway
from mug.storage import InMemoryStore

gymnasium = pytest.importorskip("gymnasium", reason="the game extra is not installed")


class _Interviewer(LLMAgent):
    """The model in the room. What it says does not matter to these tests."""

    provider = Provider.OSS
    model = "fake-local"
    on_timeout = Fallback.REPEAT_LAST

    def get_prompt(
        self,
        env: object,
        agent_id: str,
        history: History,
        chat: Transcript,
        thoughts: Thoughts,
    ) -> str:
        del env, agent_id, history, thoughts, chat
        return "Say something."


def hill() -> Any:
    """Build the environment the game activity plays."""
    return functools.partial(gymnasium.make, "MountainCar-v0", max_episode_steps=3)


def draw_hill(surface: Surface, step: StepResult) -> None:
    """Draw the car. What it paints does not matter to these tests."""
    observed = cast("list[float]", step.observation)
    where = (float(observed[0]) + 1.2) / 1.8
    surface.circle(x=where, y=0.85, radius=0.03, color="#1b6ac9", object_id="car")


# -- the study surface ---------------------------------------------------------------


def test_a_conversation_is_recorded_as_a_conversation() -> None:
    """The kind the study wrote is the kind the flow carries."""
    study = Study(
        Page("intro", "# Ready"),
        Chat("interview", Model(agent=_Interviewer())),
    )

    assert [one.kind for one in study.activities] == ["content", "chat"]
    assert study.talks["interview"].participants == 1
    assert len(study.talks["interview"].speakers) == 1


def test_a_study_holds_a_game_and_a_conversation() -> None:
    """The fault this closes: the two keywords were mutually exclusive in effect."""
    study = Study(
        Game("drive", hill(), seats={"agent": Human()}, render=draw_hill),
        Chat("interview", Model(agent=_Interviewer())),
    )

    assert set(study.game_activities) == {"drive"}
    assert set(study.talks) == {"interview"}


def test_a_conversation_between_participants_names_no_model() -> None:
    """Two people talking is a conversation with nobody else in it."""
    study = Study(Chat("pair", participants=2, greeting="Say hello"))

    assert study.talks["pair"].speakers == ()
    assert study.talks["pair"].participants == 2
    assert study.talks["pair"].greeting == "Say hello"


# -- what a participant is delivered -------------------------------------------------


def test_the_participant_is_delivered_a_conversation_not_a_game() -> None:
    """The delivery says what the activity is, so the client asks for it by name.

    It used to arrive as ``kind: "game", mode: "chat"`` -- a game the client had to be
    told was not one.
    """
    store = InMemoryStore()
    study = Study(
        Chat("interview", Model(agent=_Interviewer()), greeting="Hello"),
        Page("debrief", "# Thank you"),
    )
    client = TestClient(build_study_app(study=study, store=store, gateway=Gateway()))
    with client.websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        delivery = cast("dict[str, Any]", socket.receive_json())["delivery"]

    assert delivery["kind"] == "chat"
    assert delivery["activity_key"] == "interview"


def test_a_game_and_a_conversation_are_two_activities_in_one_visit() -> None:
    """Both are in the flow, in the order they were written, each as what it is."""
    store = InMemoryStore()
    study = Study(
        Game("drive", hill(), seats={"agent": Human()}, render=draw_hill),
        Chat("interview", Model(agent=_Interviewer())),
        Page("debrief", "# Thank you"),
    )
    client = TestClient(build_study_app(study=study, store=store, gateway=Gateway()))
    with client.websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        first = cast("dict[str, Any]", socket.receive_json())["delivery"]
        # The game activity plays itself out; the render frames follow, then the
        # conversation is delivered.
        seen: list[dict[str, Any]] = []
        for _ in range(60):
            message = cast("dict[str, Any]", socket.receive_json())
            if message["type"] == "delivery":
                seen.append(message["delivery"])
                break
        flow_id = _flow_id(store)

    assert first["activity_key"] == "drive"
    assert seen and seen[0]["kind"] == "chat"

    state = flow_of(store.load_aggregate(flow_id))
    assert state is not None
    assert [(one.activity_key, one.kind) for one in state.activities] == [
        ("drive", "game"),
        ("interview", "chat"),
        ("debrief", "content"),
    ]


def _flow_id(store: InMemoryStore) -> str:
    found = [
        aggregate_id
        for aggregate_id, _ in store.scan_aggregates()
        if aggregate_id.startswith("visitplan_")
    ]
    assert len(found) == 1
    return found[0]
