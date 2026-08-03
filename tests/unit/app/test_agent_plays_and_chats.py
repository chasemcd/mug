"""A model partner plays and comments in one activity (W7, NS-07).

``MultiAgentEpisode.post_message`` said "the transport calls this" and no transport
called it, so a playing seat could be told nothing. And there was no way for a
playing seat to *say* anything at all: a controller decided an action and that was
the whole of what a reply produced.

These drive both directions through the running application. One reply is read
three ways -- the action steps the environment, the thought is carried forward, and
the words are published on the conversation the study wrote beside the game. The
seat reads what the participant says on the same channel next decision.

**The two are judged apart**, which is what NS-07 asks for: a reply whose action
nobody can read still publishes its message and falls back on the action alone.
And the seat is not asked to speak once per frame -- it speaks on the cadence it
decides at, which is what ``decides_every`` already governs.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any, ClassVar, cast

from fastapi.testclient import TestClient
from starlette.testclient import WebSocketTestSession

from mug.agents import AgentGameSpec, AgentIds, AgentSeatSpec
from mug.app import build_study_app
from mug.authoring import Fallback, History, LLMAgent, Provider, Thoughts, Transcript
from mug.content import Game, Page, Study
from mug.conversation.anchors import read_anchors
from mug.game.multiseat import MultiStepResult
from mug.gateway import Gateway
from mug.participant_chat import ChatChannel
from mug.providers import ModelCall, ModelCompletion, Usage
from mug.storage import InMemoryStore, Store
from tests.support.agents import warmed, warming
from tests.support.chat import written_chat

_UUID = "019b6000-0000-7000-8000-{:012x}"

_AGENTS = ("north",)
_PARTNER_ACTOR = "actor_" + _UUID.format(0x800)
_EPISODE_LEN = 6


class _OneSeatEnv:
    """A one-seat environment that ends after a fixed number of steps."""

    ACTIONS: ClassVar[list[str]] = ["LEFT", "RIGHT", "STAY"]

    def __init__(self) -> None:
        self._t = 0

    def reset(self) -> MultiStepResult:
        self._t = 0
        return MultiStepResult(
            observations={agent: [0.0] for agent in _AGENTS},
            rewards=dict.fromkeys(_AGENTS, 0.0),
            terminated=False,
            truncated=False,
        )

    def step(self, actions: Mapping[str, int]) -> MultiStepResult:
        self._t += 1
        done = self._t >= _EPISODE_LEN
        return MultiStepResult(
            observations={agent: [float(self._t)] for agent in _AGENTS},
            rewards=dict.fromkeys(_AGENTS, 1.0 if done else 0.0),
            terminated=done,
            truncated=False,
        )

    def legal_actions(self, agent_id: str) -> list[str]:
        return list(self.ACTIONS)

    def text_view(self, agent_id: str) -> str:
        return f"t={self._t}; you are {agent_id}"


class _Partner(LLMAgent):
    """A partner that plays and comments, reading both out of one reply."""

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
        heard = "; ".join(message.text for message in chat.last(5))
        return f"{env.text_view(agent_id)}\nheard: {heard}"  # type: ignore[attr-defined]

    def say(self, reply: str, env: Any, agent_id: str) -> str | None:
        for line in str(reply).splitlines():
            if line.startswith("Say: "):
                return line.removeprefix("Say: ").strip()
        return None


class _Adapter:
    """A keyless adapter that records every prompt and answers on a script."""

    def __init__(self, *, action: str | None = "RIGHT", say: str = "on my way") -> None:
        self._action = action
        self._say = say
        self.prompts: list[str] = []

    async def __call__(self, call: ModelCall) -> ModelCompletion:
        if warming(call):
            return warmed()
        payload: Any = call.payload
        self.prompts.append(payload["messages"][0]["content"])
        # It says something only on its first decision, so the test can count the
        # messages exactly rather than race the loop.
        said = f"\nSay: {self._say}" if len(self.prompts) == 1 else ""
        action = f"Action: {self._action}" if self._action else "no action here"
        return ModelCompletion(
            outcome="completed",
            resolved_model="fake-local",
            usage=Usage(input_tokens=1, output_tokens=1, cost_micros=0),
            output={"text": f"{action}{said}"},
        )


def _view(env: Any, agent_id: str) -> str:
    return cast("str", env.text_view(agent_id))


def _spec(adapter: _Adapter) -> AgentGameSpec:
    seat = AgentSeatSpec(
        agent=_Partner(),
        adapter=adapter,
        ids=AgentIds(
            agent_version_id="agentver_" + _UUID.format(0x830),
            agent_definition_id="agentdef_" + _UUID.format(0x831),
            agent_key="partner",
            version_number=1,
            prompt_version_id="promptver_" + _UUID.format(0x840),
            fallback_policy_key="partner-fallback",
        ),
        agent_id="north",
        seat_key="seat-north",
        actor_id=_PARTNER_ACTOR,
        text_view=_view,
    )
    return AgentGameSpec(
        channel_key="agent-game",
        make_env=_OneSeatEnv,
        seats=(seat,),
        decision_timeout=1.0,
        fps=0,
        max_steps=_EPISODE_LEN + 5,
    )


def _study() -> Study:
    """A study whose one activity is an agent game with a conversation beside it."""
    return Study(
        Game("play", chat=written_chat("talk")),
        Page("debrief", "# Thanks"),
    )


def _client(store: InMemoryStore, adapter: _Adapter) -> TestClient:
    return TestClient(
        build_study_app(
            study=_study(),
            store=store,
            gateway=Gateway(),
            agent_game=_spec(adapter),
        )
    )


def _read_until(
    socket: WebSocketTestSession, kind: str, limit: int = 200
) -> dict[str, Any]:
    for _ in range(limit):
        frame = cast("dict[str, Any]", socket.receive_json())
        if frame.get("type") == kind:
            return frame
    raise AssertionError(f"no {kind!r} frame arrived")


def _states(store: Store) -> list[dict[str, Any]]:
    heads: list[dict[str, Any]] = []
    for _id, state in store.scan_aggregates():
        if isinstance(state, dict):
            heads.append(cast("dict[str, Any]", state))
    return heads


def _of_kind(store: Store, name: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for state in _states(store):
        schema = state.get("schema")
        if not isinstance(schema, dict):
            continue
        if cast("dict[str, Any]", schema).get("name") == name:
            found.append(state)
    return found


def _episodes(store: Store) -> list[dict[str, Any]]:
    """Return every recorded episode head, as typed mappings."""
    found: list[dict[str, Any]] = []
    for aggregate_id, state in store.scan_aggregates():
        if aggregate_id.startswith("episode_") and isinstance(state, dict):
            found.append(cast("dict[str, Any]", state))
    return found


def _anchor_ref(episode: dict[str, Any]) -> dict[str, Any] | None:
    """Return the anchor artifact one run recorded, or None when it recorded none."""
    recorded = episode.get("anchors")
    return cast("dict[str, Any]", recorded) if isinstance(recorded, dict) else None


def _messages(store: Store) -> list[dict[str, Any]]:
    return sorted(
        _of_kind(store, "mug.api-08.chat-message"),
        key=lambda state: int(state["sequence"]),
    )


# -- the agent says what its reply said -------------------------------------------


def test_a_playing_seat_publishes_what_it_said() -> None:
    """The proof, outbound: the partner plays and its words reach the channel."""
    store = InMemoryStore()
    adapter = _Adapter()
    with _client(store, adapter).websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        assert socket.receive_json()["delivery"]["kind"] == "game"
        _read_until(socket, "delivery", limit=400)

    said = _messages(store)
    assert len(said) == 1
    assert said[0]["author_actor_id"] == _PARTNER_ACTOR
    assert said[0]["channel_key"] == "talk"
    # It played as well: the run was captured with the frames it stepped.
    episodes = _episodes(store)
    assert len(episodes) == 1
    assert episodes[0]["frame_count"] >= _EPISODE_LEN


def test_the_seat_is_not_asked_to_speak_once_per_frame() -> None:
    """It talks on the cadence it decides at, which is the same model call."""
    store = InMemoryStore()
    adapter = _Adapter()
    with _client(store, adapter).websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        socket.receive_json()
        _read_until(socket, "delivery", limit=400)

    # One message came out of many decisions, and every decision was one call. A
    # seat asked to speak per frame would have made a call per frame **extra**.
    assert len(_messages(store)) == 1
    assert len(adapter.prompts) <= _EPISODE_LEN + 1


def test_an_unreadable_action_does_not_cost_the_participant_the_message() -> None:
    """Independent validity end to end: the words publish, the action falls back."""
    store = InMemoryStore()
    adapter = _Adapter(action=None, say="I am stuck")
    with _client(store, adapter).websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        socket.receive_json()
        _read_until(socket, "delivery", limit=400)

    said = _messages(store)
    assert len(said) == 1
    assert said[0]["author_actor_id"] == _PARTNER_ACTOR


def test_what_the_seat_said_is_anchored_to_the_frame_it_was_said_at() -> None:
    """The message relates to game progress the same way a participant's does."""
    store = InMemoryStore()
    adapter = _Adapter()
    with _client(store, adapter).websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        socket.receive_json()
        _read_until(socket, "delivery", limit=400)

    episodes = _episodes(store)
    recorded = _anchor_ref(episodes[0])
    assert recorded is not None, "the run recorded nothing about what was said"
    data = asyncio.run(cast("Any", store).read_artifact(recorded["artifact_id"]))
    anchors = read_anchors(cast("bytes", data))
    assert [anchor.channel_key for anchor in anchors] == ["talk"]
    assert 0 <= anchors[0].frame_number <= episodes[0]["frame_count"]


def test_one_interaction_holds_the_game_and_the_conversation() -> None:
    """The agent game's channels are the room's channels, in one interaction."""
    store = InMemoryStore()
    with _client(store, _Adapter()).websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        socket.receive_json()
        _read_until(socket, "delivery", limit=400)

    interactions = _of_kind(store, "mug.api-06.interaction")
    assert len(interactions) == 1
    assert sorted(interactions[0]["channels"]) == ["agent-game", "talk"]
    # The playing seat is a member of the conversation, so who was in it is
    # recorded rather than remembered.
    access = {
        (state["actor_id"], state["channel_key"]): state["access"]
        for state in _of_kind(store, "mug.api-06.membership")
    }
    assert access[(_PARTNER_ACTOR, "talk")] == "read_write"


# -- what the participant says reaches the playing seat ---------------------------


class _LongEnv(_OneSeatEnv):
    """The same environment, long enough to be instructed part way through."""

    def step(self, actions: Mapping[str, int]) -> MultiStepResult:
        self._t += 1
        done = self._t >= 60
        return MultiStepResult(
            observations={agent: [float(self._t)] for agent in _AGENTS},
            rewards=dict.fromkeys(_AGENTS, 1.0 if done else 0.0),
            terminated=done,
            truncated=False,
        )


def test_what_the_participant_says_reaches_the_playing_seat() -> None:
    """The proof, inbound: an instruction is in the seat's next prompt.

    ``MultiAgentEpisode.post_message`` said "the transport calls this" and no
    transport called it, so a playing seat could be told nothing at all. Now the
    conversation and the game share one socket and one interaction, and a
    participant can instruct the partner mid-run.
    """
    store = InMemoryStore()
    adapter = _Adapter()
    slow = _spec(adapter)
    # A long run with a real frame clock, so the instruction lands mid-episode
    # rather than after the seats have stopped deciding.
    slow = AgentGameSpec(
        channel_key=slow.channel_key,
        make_env=_LongEnv,
        seats=slow.seats,
        decision_timeout=1.0,
        fps=25,
        max_steps=80,
    )
    app = build_study_app(
        study=_study(), store=store, gateway=Gateway(), agent_game=slow
    )
    with TestClient(app).websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        assert socket.receive_json()["delivery"]["kind"] == "game"
        # The partner's own words arrive among the game frames, so read past
        # whatever comes rather than demanding ten frames in a row.
        seen = 0
        while seen < 10:
            if socket.receive_json().get("type") == "frame":
                seen += 1
        socket.send_json({"type": "chat", "text": "take the left side"})
        _read_until(socket, "delivery", limit=600)

    assert any("take the left side" in prompt for prompt in adapter.prompts), (
        "the seat played a whole episode and was never told what the participant said"
    )
    # And it was recorded as a message of the shared conversation, not a side channel.
    said = _messages(store)
    assert any(state["channel_key"] == "talk" for state in said)


def test_a_playing_seat_is_not_told_its_own_words_back() -> None:
    """A seat reads the conversation, not an echo of itself.

    Its own reply is already its own reasoning, carried forward by ``reflect``.
    Feeding it back as somebody else's message would have the model answer itself
    and would fill the prompt with what it just said.
    """
    store = InMemoryStore()
    adapter = _Adapter(say="on my way")
    base = _spec(adapter)
    slow = AgentGameSpec(
        channel_key=base.channel_key,
        make_env=_LongEnv,
        seats=base.seats,
        decision_timeout=1.0,
        fps=25,
        max_steps=80,
    )
    app = build_study_app(
        study=_study(), store=store, gateway=Gateway(), agent_game=slow
    )
    with TestClient(app).websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        socket.receive_json()
        _read_until(socket, "delivery", limit=800)

    assert adapter.prompts, "the seat never decided"
    # It said "on my way" on its first decision. No later prompt heard it.
    assert not any("heard: on my way" in prompt for prompt in adapter.prompts)


def test_a_playing_seat_is_not_told_a_channel_it_is_not_in() -> None:
    """A private channel stays private from a playing seat, exactly as from a person.

    The room decides who may see what, and the transport feeds a seat only the
    channel its membership admits. A seat fed everything said in the interaction
    would be the one way a private channel leaks.
    """
    store = InMemoryStore()
    adapter = _Adapter()
    base = _spec(adapter)
    study = Study(
        Game(
            "play",
            chat=written_chat(
                "talk",
                channels=(
                    ChatChannel(key="talk"),
                    ChatChannel(key="aside", visibility="private"),
                ),
            ),
        ),
        Page("debrief", "# Thanks"),
    )
    slow = AgentGameSpec(
        channel_key=base.channel_key,
        make_env=_LongEnv,
        seats=base.seats,
        decision_timeout=1.0,
        fps=25,
        max_steps=80,
    )
    app = build_study_app(
        study=study, store=store, gateway=Gateway(), agent_game=slow
    )
    with TestClient(app).websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        socket.receive_json()
        seen = 0
        while seen < 8:
            if socket.receive_json().get("type") == "frame":
                seen += 1
        socket.send_json(
            {"type": "chat", "channel": "aside", "text": "a private thought"}
        )
        _read_until(socket, "delivery", limit=800)

    # It was really said, on the channel the participant named.
    assert any(state["channel_key"] == "aside" for state in _messages(store))
    # And the playing seat, which is in "talk" and not in "aside", never read it.
    assert not any("a private thought" in prompt for prompt in adapter.prompts)
