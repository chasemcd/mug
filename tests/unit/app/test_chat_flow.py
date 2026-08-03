"""A participant holds a recorded conversation over the realtime transport.

This test drives the whole chat mount. One participant plays the flow to the study's
interactive activity, which is a conversation rather than a game: the activity is
delivered in chat mode, the participant writes messages, the study's model seat
answers each one through a deterministic fake provider, and the flow then advances to
the debrief and the completion code.

The assertions are about the two things the mount owes: what the participant sees on
the socket, and what the ledger records. Every message the conversation carries is
recorded as canonical API-08 evidence -- ordered by sequence, named by content digest,
with a delivery receipt per recipient and a context snapshot per model reply -- and
the flow names the streams the conversation wrote.
"""

from __future__ import annotations

from typing import Any, cast

from fastapi.testclient import TestClient
from starlette.testclient import WebSocketTestSession

from mug.agents import AgentIds
from mug.app import build_demo_app
from mug.authoring import Fallback, History, LLMAgent, Provider, Thoughts, Transcript
from mug.client import RealtimeCommand
from mug.content import flow_of
from mug.conversation import TurnPolicy
from mug.gateway import Gateway
from mug.kernel import Digest, SchemaRef, compute_digest
from mug.participant_chat import ChatSeatSpec, ChatSpec
from mug.providers import ModelCall, ModelCompletion, Usage
from mug.storage import InMemoryStore, Store
from tests.support.chat import written_chat

_A_DIGEST = Digest(algorithm="sha-256", hex="a" * 64)

_UUID = "019b6000-0000-7000-8000-{:012x}"
_AGENT_ACTOR = "actor_" + _UUID.format(0x300)


class _Partner(LLMAgent):
    """An author's chat agent: a keyless local runner with a fixed persona."""

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
        # The shape the shipped example writes. A double whose prompt says nothing
        # would let the mount drop the author's words and still pass.
        return "\n".join(f"{one.sender}: {one.text}" for one in chat.last(50))


async def _adapter(call: ModelCall) -> ModelCompletion:
    """Answer with how many messages the model was sent, so replies differ.

    The prompt is read from ``content``, which is where every provider looks for the
    words of a message. A double that reads them from anywhere else passes while the
    real model is sent nothing at all.
    """
    payload: Any = call.payload
    turns = len(
        "\n".join(str(one["content"]) for one in payload["messages"]).splitlines()
    )
    return ModelCompletion(
        outcome="completed",
        resolved_model="fake-local",
        usage=Usage(input_tokens=turns, output_tokens=1, cost_micros=0),
        output={"text": f"I heard {turns} message(s)."},
    )


async def _silent_adapter(call: ModelCall) -> ModelCompletion:
    """Refuse every call, so the turn stays silent and posts nothing."""
    return ModelCompletion(
        outcome="refused",
        resolved_model="fake-local",
        usage=Usage(input_tokens=0, output_tokens=0, cost_micros=0),
    )


def _seat(adapter: Any = _adapter) -> ChatSeatSpec:
    return ChatSeatSpec(
        agent=_Partner(),
        adapter=adapter,
        ids=AgentIds(
            agent_version_id="agentver_" + _UUID.format(0x430),
            agent_definition_id="agentdef_" + _UUID.format(0x431),
            agent_key="chat-partner",
            version_number=1,
            prompt_version_id="promptver_" + _UUID.format(0x440),
            fallback_policy_key="chat-fallback",
        ),
        actor_id=_AGENT_ACTOR,
    )


def _spec(**overrides: Any) -> ChatSpec:
    fields: dict[str, Any] = {"seat": _seat(), "channel_key": "interview"}
    fields.update(overrides)
    return written_chat(**fields)


def _advance_frame(answers: dict[str, Any], tag: str) -> dict[str, Any]:
    command = RealtimeCommand(
        command_id=f"command_019b6000-0000-7000-8000-0000000000{tag}",
        channel_key="flow.advance",
        intent_schema=SchemaRef(name="mug.demo.intent", version=0, digest=_A_DIGEST),
        payload_digest=_A_DIGEST,
        idempotency_key="idem_" + tag.ljust(21, "0") + "A",
        submitted_at="2026-07-25T00:00:00.000000Z",
    )
    return {
        "type": "command",
        "command": command.model_dump(mode="json", exclude_none=True),
        "payload": {"answers": answers},
    }


def _drive_to_chat(
    socket: WebSocketTestSession, tags: tuple[str, str]
) -> dict[str, Any]:
    """Play the forms and return the delivery that opens the chat activity."""
    assert socket.receive_json()["type"] == "handshake_ack"
    assert socket.receive_json()["delivery"]["form"]["form_key"] == "consent"
    socket.send_json(_advance_frame({"agree": "yes"}, tags[0]))
    assert socket.receive_json()["ack"]["ack_kind"] == "parsed"
    assert socket.receive_json()["ack"]["ack_kind"] == "accepted"
    assert socket.receive_json()["delivery"]["form"]["form_key"] == "survey"
    socket.send_json(_advance_frame({"mood": 4}, tags[1]))
    assert socket.receive_json()["ack"]["ack_kind"] == "parsed"
    assert socket.receive_json()["ack"]["ack_kind"] == "accepted"
    delivery: dict[str, Any] = socket.receive_json()["delivery"]
    return delivery


def _say(socket: WebSocketTestSession, text: str) -> dict[str, Any]:
    """Send one participant message and read the reply the seat sends back."""
    socket.send_json({"type": "chat", "text": text})
    reply: dict[str, Any] = socket.receive_json()
    return reply


def _states(store: Store) -> list[dict[str, Any]]:
    """Return every recorded aggregate head, as typed mappings."""
    heads: list[dict[str, Any]] = []
    for _id, state in store.scan_aggregates():
        if isinstance(state, dict):
            heads.append(cast("dict[str, Any]", state))
    return heads


def _schema_name(state: dict[str, Any]) -> str:
    """Return the schema name one recorded aggregate carries, or an empty name."""
    schema = state.get("schema")
    if not isinstance(schema, dict):
        return ""
    name = cast("dict[str, Any]", schema).get("name")
    return name if isinstance(name, str) else ""


def _messages_of(store: Store, channel_key: str) -> list[dict[str, Any]]:
    """Return every recorded chat message of one channel, in sequence order."""
    found = [
        state
        for state in _states(store)
        if _schema_name(state) == "mug.api-08.chat-message"
        and state.get("channel_key") == channel_key
    ]
    return sorted(found, key=lambda state: int(state["sequence"]))


def _of_kind(store: Store, name: str) -> list[dict[str, Any]]:
    """Return every recorded aggregate whose schema carries the given name."""
    return [state for state in _states(store) if _schema_name(state) == name]


def _flows(store: Store) -> list[dict[str, Any]]:
    """Return the recorded flow states (the heads that track captured streams)."""
    return [state for state in _states(store) if "flow" in state]


def test_the_chat_activity_is_delivered_in_chat_mode() -> None:
    """A study with a chat spec delivers its activity as chat, not as a game."""
    app = build_demo_app(store=InMemoryStore(), gateway=Gateway(), chat=_spec())
    client = TestClient(app)
    with client, client.websocket_connect("/ws") as socket:
        delivery = _drive_to_chat(socket, ("01", "02"))

        assert delivery["kind"] == "game"
        assert delivery["mode"] == "chat"
        # No client manifest and no server stepping loop: the socket waits for text.
        assert "manifest" not in delivery
        socket.send_json({"type": "chat_end"})
        assert socket.receive_json()["delivery"]["kind"] == "content"


def test_a_conversation_records_every_message_in_order() -> None:
    """Both authors' messages land on one channel with one total sequence order."""
    store = InMemoryStore()
    app = build_demo_app(store=store, gateway=Gateway(), chat=_spec())
    client = TestClient(app)
    with client, client.websocket_connect("/ws") as socket:
        _drive_to_chat(socket, ("01", "02"))

        first = _say(socket, "Hello there")
        assert first["type"] == "chat"
        assert first["text"] == "I heard 1 message(s)."
        assert first["author_actor_id"] == _AGENT_ACTOR
        assert first["sequence"] == 2

        # The second turn sees the whole transcript, so the reply counts three.
        second = _say(socket, "How are you?")
        assert second["text"] == "I heard 3 message(s)."
        assert second["sequence"] == 4

        socket.send_json({"type": "chat_end"})
        assert socket.receive_json()["delivery"]["kind"] == "content"

    messages = _messages_of(store, "interview")
    assert [message["sequence"] for message in messages] == [1, 2, 3, 4]
    # The channel alternates authors and never holds the text, only its digest.
    assert [message["author_actor_id"] == _AGENT_ACTOR for message in messages] == [
        False,
        True,
        False,
        True,
    ]
    assert messages[0]["content_digest"] == compute_digest("Hello there").model_dump(
        mode="json"
    )
    assert all("text" not in message for message in messages)


def test_a_reply_is_recorded_by_the_model_output_digest() -> None:
    """The reply's content digest is the digest of the model's own output."""
    store = InMemoryStore()
    app = build_demo_app(store=store, gateway=Gateway(), chat=_spec())
    client = TestClient(app)
    with client, client.websocket_connect("/ws") as socket:
        _drive_to_chat(socket, ("01", "02"))
        _say(socket, "Hello there")
        socket.send_json({"type": "chat_end"})
        socket.receive_json()

    reply = _messages_of(store, "interview")[1]
    expected = compute_digest({"text": "I heard 1 message(s)."})
    assert reply["content_digest"] == expected.model_dump(mode="json")


def test_each_exchange_records_its_deliveries_and_its_snapshot() -> None:
    """One exchange records two delivery receipts and one context snapshot."""
    store = InMemoryStore()
    app = build_demo_app(store=store, gateway=Gateway(), chat=_spec())
    client = TestClient(app)
    with client, client.websocket_connect("/ws") as socket:
        _drive_to_chat(socket, ("01", "02"))
        _say(socket, "Hello there")
        socket.send_json({"type": "chat_end"})
        socket.receive_json()

    messages = _messages_of(store, "interview")
    deliveries = _of_kind(store, "mug.api-08.delivery-receipt")
    snapshots = _of_kind(store, "mug.api-08.context-snapshot")

    # The participant's message is delivered to the seat, the reply back again.
    assert len(deliveries) == 2
    assert {receipt["recipient_actor_id"] for receipt in deliveries} == {
        _AGENT_ACTOR,
        messages[0]["author_actor_id"],
    }
    assert all(receipt["evidence_stream"] == "canonical" for receipt in deliveries)
    # The snapshot pins the reply to the messages the model actually read.
    assert len(snapshots) == 1
    assert snapshots[0]["message_id"] == messages[1]["message_id"]
    assert snapshots[0]["included_message_ids"] == [messages[0]["message_id"]]


def test_the_flow_records_the_streams_the_conversation_wrote() -> None:
    """The activity advances carrying the streams its messages committed on."""
    store = InMemoryStore()
    app = build_demo_app(store=store, gateway=Gateway(), chat=_spec())
    client = TestClient(app)
    with client, client.websocket_connect("/ws") as socket:
        _drive_to_chat(socket, ("01", "02"))
        _say(socket, "Hello there")
        _say(socket, "And again")
        socket.send_json({"type": "chat_end"})
        socket.receive_json()

    flows = _flows(store)
    assert len(flows) == 1
    # Four messages, so four streams, and each is named once.
    captured = cast("list[str]", flows[0]["flow"]["captured_streams"])
    assert len(captured) == 4
    assert len(set(captured)) == 4


def test_an_empty_message_is_ignored_and_never_reaches_the_model() -> None:
    """Blank text costs no turn: nothing is posted and the model is not called."""
    store = InMemoryStore()
    app = build_demo_app(store=store, gateway=Gateway(), chat=_spec())
    client = TestClient(app)
    with client, client.websocket_connect("/ws") as socket:
        _drive_to_chat(socket, ("01", "02"))
        socket.send_json({"type": "chat", "text": "   "})
        # The blank message produces no reply, so the next frame is the real one.
        reply = _say(socket, "Hello there")
        assert reply["sequence"] == 2
        socket.send_json({"type": "chat_end"})
        socket.receive_json()

    assert len(_messages_of(store, "interview")) == 2


def test_a_silent_model_still_records_what_the_participant_said() -> None:
    """A refused call posts no reply, and the participant's message is still kept."""
    store = InMemoryStore()
    app = build_demo_app(
        store=store, gateway=Gateway(), chat=_spec(seat=_seat(_silent_adapter))
    )
    client = TestClient(app)
    with client, client.websocket_connect("/ws") as socket:
        _drive_to_chat(socket, ("01", "02"))
        socket.send_json({"type": "chat", "text": "Anyone there?"})
        socket.send_json({"type": "chat_end"})
        # No reply frame arrives, but the participant is told why.
        assert socket.receive_json()["type"] == "chat_notice"
        assert socket.receive_json()["delivery"]["kind"] == "content"

    messages = _messages_of(store, "interview")
    assert len(messages) == 1
    assert messages[0]["author_actor_id"] != _AGENT_ACTOR


def test_the_message_bound_ends_the_activity_by_itself() -> None:
    """A participant who never leaves still reaches the next activity."""
    store = InMemoryStore()
    app = build_demo_app(store=store, gateway=Gateway(), chat=_spec(max_messages=2))
    client = TestClient(app)
    with client, client.websocket_connect("/ws") as socket:
        _drive_to_chat(socket, ("01", "02"))
        _say(socket, "one")
        _say(socket, "two")
        # The bound is reached, so the flow advances with no end frame sent.
        assert socket.receive_json()["delivery"]["kind"] == "content"

    assert len(_messages_of(store, "interview")) == 4


def test_a_greeting_opens_the_conversation_before_the_participant_writes() -> None:
    """A study's opener is posted, delivered, and recorded at the first sequence."""
    store = InMemoryStore()
    app = build_demo_app(
        store=store, gateway=Gateway(), chat=_spec(greeting="Welcome. Say hello.")
    )
    client = TestClient(app)
    with client, client.websocket_connect("/ws") as socket:
        _drive_to_chat(socket, ("01", "02"))
        opener = socket.receive_json()
        assert opener["type"] == "chat"
        assert opener["text"] == "Welcome. Say hello."
        assert opener["author_actor_id"] == _AGENT_ACTOR
        assert opener["sequence"] == 1
        socket.send_json({"type": "chat_end"})
        socket.receive_json()

    messages = _messages_of(store, "interview")
    assert len(messages) == 1
    assert messages[0]["content_digest"] == compute_digest(
        "Welcome. Say hello."
    ).model_dump(mode="json")


def test_a_mention_policy_keeps_the_model_quiet_until_it_is_named() -> None:
    """Under a mention policy the seat answers only the message that names it."""
    store = InMemoryStore()
    policy = TurnPolicy(
        channel_key="interview", activation="mention", max_model_activations_per_turn=1
    )
    app = build_demo_app(
        store=store,
        gateway=Gateway(),
        chat=_spec(policy=policy, mention_token="partner"),
    )
    client = TestClient(app)
    with client, client.websocket_connect("/ws") as socket:
        _drive_to_chat(socket, ("01", "02"))
        socket.send_json({"type": "chat", "text": "thinking out loud"})
        reply = _say(socket, "partner, are you there?")
        assert reply["type"] == "chat"
        socket.send_json({"type": "chat_end"})
        socket.receive_json()

    messages = _messages_of(store, "interview")
    # Two participant messages, one reply: the unnamed message got no answer.
    assert [message["author_actor_id"] == _AGENT_ACTOR for message in messages] == [
        False,
        False,
        True,
    ]


def test_the_visit_completes_after_the_conversation() -> None:
    """The chat activity is one step of the flow, and the visit finishes normally."""
    store = InMemoryStore()
    app = build_demo_app(store=store, gateway=Gateway(), chat=_spec())
    client = TestClient(app)
    with client, client.websocket_connect("/ws") as socket:
        _drive_to_chat(socket, ("01", "02"))
        _say(socket, "Hello there")
        socket.send_json({"type": "chat_end"})
        assert socket.receive_json()["delivery"]["kind"] == "content"
        socket.send_json(_advance_frame({}, "03"))
        assert socket.receive_json()["ack"]["ack_kind"] == "parsed"
        assert socket.receive_json()["ack"]["ack_kind"] == "accepted"
        complete = socket.receive_json()["delivery"]
        assert complete["kind"] == "complete"
        assert complete["completion_code"].startswith("MUG-")

    flow = flow_of(_flows(store)[0])
    assert flow is not None
    assert flow.status == "completed"
