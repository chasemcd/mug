"""One activity is a game and a conversation at once (W6, NS-06).

The platform ran a game **or** a conversation: the mount was chosen once for the
whole application, so a study that wanted people to talk while they played could
not have one. These tests hold what the composed activity owes.

**One interaction, two channels.** The room forms before either pane starts, and
the interaction it casts holds the game channel beside the conversation's. The two
are not ordered the same way, and each channel record says which it is: a
conversation is totally ordered because every message goes through the server, and
a game is ordered per producer.

**Two orderings, related and not merged.** Each run records what was said while it
played, and at which frame. That is the anchor NS-06 asks for -- it lets a replay
lay the messages along game progress without inventing one order over both, which
is exactly what NS-06 refuses.

**The conversation is not interrupted by the game.** Stepping does not wait on a
message, and a message can still be sent while the participant is reading the
screen between rounds.

**The author's own value decides the scope.** One written conversation placed on
two activities is one conversation that carries across them; two written
conversations are two.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from typing import Any, cast

from fastapi.testclient import TestClient
from starlette.testclient import WebSocketTestSession

from examples.mountain_car.native_env import mountain_car_spec
from mug.agents import AgentIds
from mug.app import build_study_app
from mug.authoring import Chat, Fallback, History, LLMAgent, Provider, Thoughts
from mug.content import Game, Page, Study
from mug.conversation.anchors import read_anchors
from mug.gateway import Gateway
from mug.participant_chat import ChatSeatSpec, ChatSpec
from mug.providers import ModelCall, ModelCompletion, Usage
from mug.runtime import read_ledger
from mug.storage import InMemoryStore, Store

_UUID = "019b6000-0000-7000-8000-{:012x}"
_PARTNER = "actor_" + _UUID.format(0x500)
# The game channel is the one the specification names, not the activity key: an
# activity is a step of the study, and a channel is what runs inside it.
_GAME = "mountain-car"


class _Partner(LLMAgent):
    """A keyless local chat agent, so no provider is reached in a test."""

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
    """Answer with how many messages were in the prompt, so replies differ."""
    payload: Any = call.payload
    turns = len(payload["messages"])
    return ModelCompletion(
        outcome="completed",
        resolved_model="fake-local",
        usage=Usage(input_tokens=turns, output_tokens=1, cost_micros=0),
        output={"text": f"heard {turns}"},
    )


async def _slow_adapter(call: ModelCall) -> ModelCompletion:
    """Take real time to answer, so a stalled loop would be visible as a gap."""
    await asyncio.sleep(0.4)
    return await _adapter(call)


def _seat(adapter: Any = _adapter) -> ChatSeatSpec:
    return ChatSeatSpec(
        agent=_Partner(),
        adapter=adapter,
        ids=AgentIds(
            agent_version_id="agentver_" + _UUID.format(0x530),
            agent_definition_id="agentdef_" + _UUID.format(0x531),
            agent_key="game-partner",
            version_number=1,
            prompt_version_id="promptver_" + _UUID.format(0x540),
            fallback_policy_key="chat-fallback",
        ),
        actor_id=_PARTNER,
    )


def _chat(seat: ChatSeatSpec | None = None, **overrides: Any) -> ChatSpec:
    fields: dict[str, Any] = {"seat": seat or _seat(), "channel_key": "talk"}
    fields.update(overrides)
    return ChatSpec(**fields)


def _game(max_steps: int = 6) -> Any:
    """A short round that steps as fast as the loop allows."""
    return replace(
        mountain_car_spec(), fps=0, max_steps=max_steps, countdown_seconds=0
    )


def _client(store: InMemoryStore, study: Study) -> TestClient:
    return TestClient(build_study_app(study=study, store=store, gateway=Gateway()))


def _read_until(
    socket: WebSocketTestSession, kind: str, limit: int = 60
) -> dict[str, Any]:
    """Read frames until one of the named type arrives."""
    for _ in range(limit):
        frame = cast("dict[str, Any]", socket.receive_json())
        if frame.get("type") == kind:
            return frame
    raise AssertionError(f"no {kind!r} frame arrived")


def _say(socket: WebSocketTestSession, text: str) -> dict[str, Any]:
    """Say one thing and read the seat's reply.

    Every deterministic test here talks while the game pane is showing the screen
    between rounds. That is not a workaround: the loop waits on the participant
    there, so the exchange is not a race with the stepping clock. A message sent
    mid-round is a real case as well, and one test below plays slowly enough to
    send one.
    """
    socket.send_json({"type": "chat", "text": text})
    return _read_until(socket, "chat")


def _states(store: Store) -> list[dict[str, Any]]:
    heads: list[dict[str, Any]] = []
    for _id, state in store.scan_aggregates():
        if isinstance(state, dict):
            heads.append(cast("dict[str, Any]", state))
    return heads


def _schema_name(state: dict[str, Any]) -> str:
    schema = state.get("schema")
    if not isinstance(schema, dict):
        return ""
    name = cast("dict[str, Any]", schema).get("name")
    return name if isinstance(name, str) else ""


def _of_kind(store: Store, name: str) -> list[dict[str, Any]]:
    return [state for state in _states(store) if _schema_name(state) == name]


def _episodes(store: Store) -> list[dict[str, Any]]:
    return [
        state
        for aggregate_id, state in store.scan_aggregates()
        if aggregate_id.startswith("episode_") and isinstance(state, dict)
    ]


def _stream_of(aggregate_id: str) -> str:
    """Return the event stream one aggregate's records land on."""
    return "stream_" + aggregate_id.split("_", 1)[1]


def _artifact(store: Any, ref: dict[str, Any]) -> bytes:
    """Read back one staged artifact's bytes by its recorded reference."""
    return cast("bytes", asyncio.run(store.read_artifact(ref["artifact_id"])))


# -- the composed activity -------------------------------------------------------


def test_one_activity_is_a_game_and_a_conversation_at_once() -> None:
    """The proof: the participant plays and talks in one activity, and both record."""
    store = InMemoryStore()
    study = Study(
        Game("play", _game(), episodes=2, between="Rest", chat=_chat()),
        Page("debrief", "# Thanks"),
    )
    with _client(store, study).websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        delivery = socket.receive_json()["delivery"]
        # A composed activity still steps on the server. What is new is that the
        # client is told to mount a conversation beside the canvas.
        assert delivery["mode"] == "server"
        assert delivery["chat"] == {"placement": "beside"}

        assert _read_until(socket, "interval")["round"] == 2
        assert _say(socket, "go left")["text"] == "heard 1"
        socket.send_json({"type": "interval_done"})
        _read_until(socket, "delivery")

    # Both channels recorded, on one interaction.
    interactions = _of_kind(store, "mug.api-06.interaction")
    assert len(interactions) == 1
    assert sorted(interactions[0]["channels"]) == [_GAME, "talk"]
    assert len(_of_kind(store, "mug.api-08.chat-message")) == 2
    assert len(_episodes(store)) == 2


def test_the_game_channel_and_the_conversation_are_not_ordered_the_same_way() -> None:
    """Each channel of the one interaction records the ordering it really gives."""
    store = InMemoryStore()
    study = Study(Game("play", _game(), chat=_chat()), Page("debrief", "# Thanks"))
    with _client(store, study).websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        socket.receive_json()
        _read_until(socket, "delivery")

    instances = {
        state["channel_key"]: state
        for state in _of_kind(store, "mug.api-06.channel-instance")
    }
    assert instances[_GAME]["channel_type"] == "game"
    assert instances[_GAME]["ordering"] == "per-producer"
    assert instances["talk"]["channel_type"] == "chat"
    assert instances["talk"]["ordering"] == "total"


def test_the_episode_records_what_was_said_before_it_started() -> None:
    """A message said between rounds is placed in the next run, at frame zero.

    That is the true statement rather than a convenient one: the participant said
    it before that run had stepped anything.
    """
    store = InMemoryStore()
    study = Study(
        Game("play", _game(), episodes=2, between="Rest", chat=_chat()),
        Page("debrief", "# Thanks"),
    )
    with _client(store, study).websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        socket.receive_json()
        _read_until(socket, "interval")
        _say(socket, "ready")
        socket.send_json({"type": "interval_done"})
        _read_until(socket, "delivery")

    episodes = sorted(_episodes(store), key=lambda state: state["episode_id"])
    anchored = [state for state in episodes if state.get("anchors") is not None]
    assert len(anchored) == 1, "exactly one run carried what was said"
    anchors = read_anchors(
        _artifact(store, cast("dict[str, Any]", anchored[0]["anchors"]))
    )
    assert [anchor.channel_key for anchor in anchors] == ["talk", "talk"]
    assert {anchor.frame_number for anchor in anchors} == {0}
    assert {anchor.episode_id for anchor in anchors} == {anchored[0]["episode_id"]}


def test_a_message_sent_while_the_game_runs_is_anchored_to_the_frame_it_was_said_at(
) -> None:
    """The anchor that matters: a message mid-round names the frame on screen."""
    store = InMemoryStore()
    slow = replace(mountain_car_spec(), fps=25, max_steps=80, countdown_seconds=0)
    study = Study(Game("play", slow, chat=_chat()), Page("debrief", "# Thanks"))
    with _client(store, study).websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        socket.receive_json()
        # Let the run get going, so the message lands at a frame and not at zero.
        for _ in range(20):
            assert socket.receive_json()["type"] == "render"
        assert _say(socket, "now")["text"] == "heard 1"
        _read_until(socket, "delivery", limit=400)

    episodes = _episodes(store)
    assert len(episodes) == 1
    anchors = read_anchors(
        _artifact(store, cast("dict[str, Any]", episodes[0]["anchors"]))
    )
    # Both the message and the reply were said while the run was playing, and the
    # frame each names is one the run really reached.
    assert len(anchors) == 2
    assert min(anchor.frame_number for anchor in anchors) > 0
    assert max(anchor.frame_number for anchor in anchors) <= episodes[0]["frame_count"]


def test_stepping_does_not_wait_on_the_conversation() -> None:
    """Chat I/O cannot stall the loop: the frames keep coming while a turn runs."""
    store = InMemoryStore()
    slow = replace(mountain_car_spec(), fps=25, max_steps=80, countdown_seconds=0)
    study = Study(
        Game("play", slow, chat=_chat(_seat(_slow_adapter))),
        Page("debrief", "# Thanks"),
    )
    with _client(store, study).websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        socket.receive_json()
        for _ in range(10):
            assert socket.receive_json()["type"] == "render"
        socket.send_json({"type": "chat", "text": "thinking?"})
        # The reply arrives among the render frames rather than after them: the
        # loop went on stepping while the seat composed its turn.
        seen = 0
        for _ in range(200):
            frame = cast("dict[str, Any]", socket.receive_json())
            if frame["type"] == "render":
                seen += 1
            elif frame["type"] == "chat":
                break
        else:
            raise AssertionError("the reply never arrived")
        assert seen > 0, "the loop stopped stepping while the seat was thinking"
        _read_until(socket, "delivery", limit=400)

    assert len(_episodes(store)) == 1


def test_an_activity_with_no_conversation_records_no_anchors() -> None:
    """A run of an ordinary game says it recorded no messages, rather than none."""
    store = InMemoryStore()
    study = Study(Game("play", _game()), Page("debrief", "# Thanks"))
    with _client(store, study).websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        delivery = socket.receive_json()["delivery"]
        assert "chat" not in delivery
        _read_until(socket, "delivery")

    episodes = _episodes(store)
    assert len(episodes) == 1
    assert "anchors" not in episodes[0]
    assert not _of_kind(store, "mug.api-06.channel-instance")


def test_who_may_play_and_who_may_talk_is_recorded_per_channel() -> None:
    """The model seat is in the conversation and is not a player, and it says so."""
    store = InMemoryStore()
    study = Study(Game("play", _game(), chat=_chat()), Page("debrief", "# Thanks"))
    with _client(store, study).websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        socket.receive_json()
        _read_until(socket, "delivery")

    access = {
        (state["actor_id"] == _PARTNER, state["channel_key"]): state["access"]
        for state in _of_kind(store, "mug.api-06.membership")
    }
    # The model talks and does not play; the participant does both. A model that
    # plays as well arrives with W7, and this is what will change when it does.
    assert access[(True, "talk")] == "read_write"
    assert access[(True, _GAME)] == "none"
    assert access[(False, "talk")] == "read_write"
    assert access[(False, _GAME)] == "read_write"


# -- the author's own value is the conversation's scope ---------------------------


def test_one_written_conversation_on_two_activities_is_one_conversation() -> None:
    """The same value passed twice carries the transcript from one round to the next."""
    store = InMemoryStore()
    shared = _chat()
    study = Study(
        Game("practice", _game(), episodes=2, between="Rest", chat=shared),
        Game("real", _game(), episodes=2, between="Rest", chat=shared),
        Page("debrief", "# Thanks"),
    )
    with _client(store, study).websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        socket.receive_json()
        _read_until(socket, "interval")
        assert _say(socket, "first")["text"] == "heard 1"
        socket.send_json({"type": "interval_done"})
        _read_until(socket, "delivery")
        _read_until(socket, "interval")
        # The prompt carries what was said in the practice round as well, which is
        # what it means for one written conversation to be one conversation.
        assert _say(socket, "second")["text"] == "heard 3"
        socket.send_json({"type": "interval_done"})
        _read_until(socket, "delivery")

    # Two activities, two interactions, and one authored channel behind both: a
    # channel instance is one run of a channel, and the definition is the channel.
    instances = [
        state
        for state in _of_kind(store, "mug.api-06.channel-instance")
        if state["channel_key"] == "talk"
    ]
    assert len(instances) == 2
    assert len({state["channel_instance_id"] for state in instances}) == 2
    assert len({state["channel_definition_id"] for state in instances}) == 1

    # Carried in, not said again. The earlier activity's messages reach the second
    # activity's model as context, and are neither delivered nor recorded a second
    # time: four messages were said in total, and each was delivered once.
    assert len(_of_kind(store, "mug.api-08.chat-message")) == 4
    delivered = _of_kind(store, "mug.api-08.delivery-receipt")
    assert len(delivered) == len({state["message_id"] for state in delivered})


def test_two_written_conversations_are_two_conversations() -> None:
    """Two **equal** values written separately start fresh, because they are two.

    The scope is the author's own value, so it has to be identity and not equality.
    These two are written with the same seat and the same settings, so they compare
    equal while being distinct objects -- which is exactly the case that tells the
    two rules apart, and exactly what an author writing ``Chat(...)`` twice means.
    """
    store = InMemoryStore()
    seat = _seat()
    first, second = _chat(seat), _chat(seat)
    assert first == second and first is not second
    study = Study(
        Game("practice", _game(), episodes=2, between="Rest", chat=first),
        Game("real", _game(), episodes=2, between="Rest", chat=second),
        Page("debrief", "# Thanks"),
    )
    with _client(store, study).websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        socket.receive_json()
        _read_until(socket, "interval")
        assert _say(socket, "first")["text"] == "heard 1"
        socket.send_json({"type": "interval_done"})
        _read_until(socket, "delivery")
        _read_until(socket, "interval")
        # One message in the prompt, not three: the second conversation began with
        # nothing said in it, which is what writing it twice asked for.
        assert _say(socket, "second")["text"] == "heard 1"
        socket.send_json({"type": "interval_done"})
        _read_until(socket, "delivery")

    instances = [
        state
        for state in _of_kind(store, "mug.api-06.channel-instance")
        if state["channel_key"] == "talk"
    ]
    assert len({state["channel_definition_id"] for state in instances}) == 2


def test_the_activity_records_both_the_run_and_the_conversation() -> None:
    """Both are on the visit's captured streams, so an export has the pair."""
    store = InMemoryStore()
    study = Study(
        Game("play", _game(), episodes=2, between="Rest", chat=_chat()),
        Page("debrief", "# Thanks"),
    )
    with _client(store, study).websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        socket.receive_json()
        _read_until(socket, "interval")
        _say(socket, "hello")
        socket.send_json({"type": "interval_done"})
        _read_until(socket, "delivery")

    flows = [state for state in _states(store) if "flow" in state]
    assert len(flows) == 1
    flow = cast("dict[str, Any]", json.loads(json.dumps(flows[0])))
    captured = cast("list[str]", flow["flow"]["captured_streams"])
    # Two episode streams and the two message streams beside them.
    assert len(set(captured)) >= 4


def test_a_reply_names_the_message_it_answers() -> None:
    """Each message is its own stream, so the reply says which question it answered.

    ``EventEnvelope.causation_event_id`` has been declared and frozen since the
    contract was written and was hardcoded to None at both producers, so nothing
    related one record to another. NS-06 asks for exactly this: streams that are
    each ordered on their own, related by causation rather than merged.
    """
    store = InMemoryStore()
    study = Study(
        Game("play", _game(), episodes=2, between="Rest", chat=_chat()),
        Page("debrief", "# Thanks"),
    )
    with _client(store, study).websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        socket.receive_json()
        _read_until(socket, "interval")
        _say(socket, "why though")
        socket.send_json({"type": "interval_done"})
        _read_until(socket, "delivery")

    messages = sorted(
        _of_kind(store, "mug.api-08.chat-message"),
        key=lambda state: int(state["sequence"]),
    )
    assert len(messages) == 2
    asked, answered = messages
    events = {
        message["message_id"]: read_ledger(store, _stream_of(message["message_id"]))
        for message in messages
    }
    # The question answers nothing; the reply answers the question, by event.
    assert events[asked["message_id"]][0].causation_event_id is None
    assert (
        events[answered["message_id"]][0].causation_event_id
        == events[asked["message_id"]][0].event_id
    )
