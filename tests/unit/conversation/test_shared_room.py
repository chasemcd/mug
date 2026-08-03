"""Two participants and one model hold one conversation (NS-04).

``run_chat_activity`` owned one websocket and minted its own interaction per
connection, so two participants at the same chat activity got two conversations
that could never see each other. ``ConversationChannel`` could always order any
number of authors; what was missing was the thing that holds the connections.

These tests hold four promises:

- two connections are **matched into one interaction**, the way a game group is;
- there is **one canonical order**, assigned by the server, and no client clock
  has a say in it;
- **each participant's delivery differs** -- an author is not delivered their own
  words, so in a room of two each person's deliveries are the other person's
  messages;
- the model's **context snapshot names exactly the ordered messages it saw**;
- a write is valid only while the connection's **lease is the current one**, so a
  connection the room has replaced can no longer speak for its actor.
"""

from __future__ import annotations

import asyncio
import itertools
import json
from datetime import datetime, timezone
from typing import Any, cast

import pytest
from fastapi import WebSocketDisconnect

from mug.agents import AgentIds
from mug.authoring import Fallback, History, LLMAgent, Provider, Thoughts, Transcript
from mug.conversation.room import ChatRoom, RoomChannel, RoomMember
from mug.gateway import Gateway
from mug.kernel import Digest
from mug.participant import ChatMatchmaker
from mug.participant_chat import ChatSeatSpec, ChatSpec, run_chat_activity
from mug.providers import ModelCall, ModelCompletion, Usage
from mug.realtime import Session
from mug.runtime import CommandContext
from mug.storage import InMemoryStore, Store
from tests.support.chat import chat_spec

_UUID = "019b6000-0000-7000-8000-{:012x}"

_START = datetime(2026, 7, 27, 0, 0, 0, tzinfo=timezone.utc)
_DIGEST = Digest(algorithm="sha-256", hex="a" * 64)
_AGENT_ACTOR = "actor_" + _UUID.format(0x300)
_SECRET = b"a-shared-deployment-secret------"


class _Partner(LLMAgent):
    """An author's chat agent: a keyless local runner."""

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


def _said_to(payload: Any) -> str:
    """Return the last thing a participant said, out of what the model was sent.

    The words are read from ``content``, which is where all three providers look for
    them. A double that reads them from anywhere else passes while the real model is
    sent an empty question.
    """
    messages = cast("list[Any]", cast("dict[str, Any]", payload)["messages"])
    spoken = str(cast("dict[str, Any]", messages[-1])["content"])
    lines = [line for line in spoken.splitlines() if line.startswith("user: ")]
    return lines[-1][len("user: ") :] if lines else spoken


class _EchoAdapter:
    """A fake provider that echoes the last thing said and keeps every payload."""

    def __init__(self) -> None:
        self.payloads: list[Any] = []

    async def __call__(self, call: ModelCall) -> ModelCompletion:
        self.payloads.append(call.payload)
        last = _said_to(call.payload)
        return ModelCompletion(
            outcome="completed",
            resolved_model="fake-local",
            usage=Usage(input_tokens=1, output_tokens=1, cost_micros=0),
            output={"text": f"you said {last}"},
        )


class _Script:
    """The exact interleaving of two clients' frames, as one ordered list.

    Two coroutines racing on a shared room is not a test, it is a coin toss. The
    script is the order the frames arrive in: a socket that is not next yields
    until it is, so every run of the test sees the same sequence of posts and the
    assertions are about the room rather than about the scheduler.
    """

    def __init__(self, steps: list[tuple[str, Any]]) -> None:
        self._steps = list(steps)
        self._index = 0

    async def next_for(self, who: str) -> Any:
        spins = 0
        while self._index < len(self._steps):
            speaker, frame = self._steps[self._index]
            if speaker == who:
                self._index += 1
                return frame
            await asyncio.sleep(0)
            spins += 1
            if spins > 10_000:
                raise AssertionError(f"{who!r} waited forever for its turn")
        raise WebSocketDisconnect(code=1000)


class _ScriptedSocket:
    """One client's socket, reading its own frames out of the shared script."""

    def __init__(self, script: _Script, who: str) -> None:
        self._script = script
        self._who = who
        self.sent: list[dict[str, Any]] = []

    async def receive_text(self) -> str:
        frame = await self._script.next_for(self._who)
        return frame if isinstance(frame, str) else json.dumps(frame)

    async def send_json(self, payload: dict[str, Any]) -> None:
        self.sent.append(payload)

    def of_type(self, kind: str) -> list[dict[str, Any]]:
        return [frame for frame in self.sent if frame.get("type") == kind]


class _Contexts:
    """Mint a fresh command context on one aggregate's stream, keyed by its id."""

    def __init__(self, start: int = 1) -> None:
        self._counter = itertools.count(start)

    def __call__(self, aggregate_id: str) -> CommandContext:
        n = next(self._counter)
        body = _UUID.format(n)
        return CommandContext.model_validate(
            {
                "command_id": "command_" + body,
                "receipt_id": "receipt_" + body,
                "error_id": "error_" + body,
                "idempotency_key": "idem_" + f"{n:021d}" + "A",
                "event_id": "event_" + body,
                "stream_id": "stream_" + aggregate_id.split("_", 1)[1],
                "producer": {
                    "epoch_id": "prodepoch_" + _UUID.format(9),
                    "sequence": n,
                    "content_digest": _DIGEST.model_dump(mode="json"),
                },
                "aggregate_id": aggregate_id,
                "principal": {"kind": "service", "id": "service_" + _UUID.format(0xA)},
                "recorded_at": "2026-07-27T00:00:00.000000Z",
                "event_data_handling": {"privacy_labels": ["research"]},
            }
        )


class _Ids:
    """Mint deterministic runtime-occurrence ids from one shared counter."""

    def __init__(self, start: int = 0x1000) -> None:
        self._counter = itertools.count(start)

    def __call__(self, kind: str) -> str:
        return f"{kind}_" + _UUID.format(next(self._counter))


def _seat(adapter: Any) -> ChatSeatSpec:
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


def _session(visit: str) -> Session:
    session = Session.__new__(Session)
    session.principal = None  # type: ignore[assignment]
    session.cursor = 0
    session.state = {
        "flow_id": "visitplan_" + _UUID.format(0x50),
        "visit_id": visit,
        "game_activity_key": "talk",
    }
    session.outbox = []
    return session


def _states(store: Store) -> list[dict[str, Any]]:
    heads: list[dict[str, Any]] = []
    for _id, state in store.scan_aggregates():
        if isinstance(state, dict):
            heads.append(cast("dict[str, Any]", state))
    return heads


def _of_schema(store: Store, name: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for state in _states(store):
        schema = state.get("schema")
        if not isinstance(schema, dict):
            continue
        if cast("dict[str, Any]", schema).get("name") == name:
            found.append(state)
    return found


def _messages(store: Store) -> list[dict[str, Any]]:
    return sorted(
        _of_schema(store, "mug.api-08.chat-message"),
        key=lambda state: int(state["sequence"]),
    )


def _deliveries(store: Store) -> list[dict[str, Any]]:
    return _of_schema(store, "mug.api-08.delivery-receipt")


def _snapshots(store: Store) -> list[dict[str, Any]]:
    return _of_schema(store, "mug.api-08.context-snapshot")


async def _two_participants(
    steps: list[tuple[str, Any]],
    *,
    spec: ChatSpec,
    store: InMemoryStore,
) -> tuple[_ScriptedSocket, _ScriptedSocket]:
    """Run two connections through one matched room and return both sockets."""
    gateway = Gateway(secret=_SECRET)
    rendezvous = ChatMatchmaker(gateway, store, spec)
    script = _Script(steps)
    sockets = {who: _ScriptedSocket(script, who) for who in ("a", "b")}
    contexts = {"a": _Contexts(1), "b": _Contexts(500)}
    ids = {"a": _Ids(0x1000), "b": _Ids(0x2000)}

    async def drive(who: str, visit: str) -> None:
        await run_chat_activity(
            cast("Any", sockets[who]),
            _session(visit),
            spec,
            store=store,
            new_context=contexts[who],
            new_id=ids[who],
            now=lambda: _START,
            rendezvous=rendezvous,
        )

    await asyncio.wait_for(
        asyncio.gather(
            drive("a", "visit_" + _UUID.format(0x61)),
            drive("b", "visit_" + _UUID.format(0x62)),
        ),
        timeout=20,
    )
    return sockets["a"], sockets["b"]


# -- what the room is -------------------------------------------------------------


async def test_two_participants_and_one_model_hold_one_conversation() -> None:
    """The proof: one interaction, one order, and both people in it."""
    store = InMemoryStore()
    spec = chat_spec(seat=_seat(_EchoAdapter()), participants=2, max_messages=4)
    first, second = await _two_participants(
        [
            ("a", {"type": "chat", "text": "one"}),
            ("b", {"type": "chat", "text": "two"}),
            ("a", {"type": "chat_end"}),
            ("b", {"type": "chat_end"}),
        ],
        spec=spec,
        store=store,
    )

    messages = _messages(store)
    assert len({message["interaction_id"] for message in messages}) == 1
    # Two participant messages and one model reply to each of them.
    assert [message["sequence"] for message in messages] == [1, 2, 3, 4]
    # Both connections were told what the conversation is, and both are in it.
    assert first.of_type("chat_room")[0]["channels"] == ["chat"]
    assert {
        first.of_type("chat_room")[0]["seat"],
        second.of_type("chat_room")[0]["seat"],
    } == {"seat-1", "seat-2"}


async def test_the_canonical_order_is_one_order_with_no_gap() -> None:
    """The server assigns the sequence, so the order is one order for everybody."""
    store = InMemoryStore()
    spec = chat_spec(seat=_seat(_EchoAdapter()), participants=2, max_messages=4)
    await _two_participants(
        [
            ("a", {"type": "chat", "text": "one"}),
            ("b", {"type": "chat", "text": "two"}),
            ("a", {"type": "chat", "text": "three"}),
            ("a", {"type": "chat_end"}),
            ("b", {"type": "chat_end"}),
        ],
        spec=spec,
        store=store,
    )

    sequences = [message["sequence"] for message in _messages(store)]
    assert sequences == list(range(1, len(sequences) + 1))
    assert len(set(sequences)) == len(sequences)


async def test_each_participant_reads_the_other_and_never_their_own_echo() -> None:
    """One order, many deliveries: what each person received is not the same set."""
    store = InMemoryStore()
    spec = chat_spec(seat=_seat(_EchoAdapter()), participants=2, max_messages=4)
    first, second = await _two_participants(
        [
            ("a", {"type": "chat", "text": "from a"}),
            ("b", {"type": "chat", "text": "from b"}),
            ("a", {"type": "chat_end"}),
            ("b", {"type": "chat_end"}),
        ],
        spec=spec,
        store=store,
    )

    to_first = [frame["text"] for frame in first.of_type("chat")]
    to_second = [frame["text"] for frame in second.of_type("chat")]
    assert "from b" in to_first
    assert "from a" not in to_first
    assert "from a" in to_second
    assert "from b" not in to_second
    assert to_first != to_second


async def test_every_delivery_names_the_one_recipient_it_reached() -> None:
    """A delivery receipt is per member, so a room of three writes three of them."""
    store = InMemoryStore()
    spec = chat_spec(seat=_seat(_EchoAdapter()), participants=2, max_messages=4)
    await _two_participants(
        [
            ("a", {"type": "chat", "text": "hello"}),
            ("a", {"type": "chat_end"}),
            ("b", {"type": "chat_end"}),
        ],
        spec=spec,
        store=store,
    )

    first_message = _messages(store)[0]
    for_first = [
        receipt
        for receipt in _deliveries(store)
        if receipt["message_id"] == first_message["message_id"]
    ]
    recipients = {receipt["recipient_actor_id"] for receipt in for_first}
    # The other participant and the model seat, and never the author.
    assert _AGENT_ACTOR in recipients
    assert first_message["author_actor_id"] not in recipients
    assert len(recipients) == 2


async def test_the_snapshot_names_exactly_the_messages_the_model_saw() -> None:
    """A replay reconstructs the model's context only if the snapshot is exact.

    Two participants type when they like, so how many messages a given turn read is
    a matter of who got there first -- and that is the point. Whatever the model
    read, the snapshot must name it: the messages of the conversation so far, in the
    canonical order, with nothing skipped, nothing reordered, and nothing from
    after the turn began. That is the invariant a replay depends on, and it does
    not depend on the scheduler.
    """
    store = InMemoryStore()
    adapter = _EchoAdapter()
    spec = chat_spec(seat=_seat(adapter), participants=2, max_messages=4)
    await _two_participants(
        [
            ("a", {"type": "chat", "text": "one"}),
            ("b", {"type": "chat", "text": "two"}),
            ("a", {"type": "chat_end"}),
            ("b", {"type": "chat_end"}),
        ],
        spec=spec,
        store=store,
    )

    order = [message["message_id"] for message in _messages(store)]
    snapshots = _snapshots(store)
    assert len(snapshots) == 2
    for snapshot in snapshots:
        seen = snapshot["included_message_ids"]
        assert seen, "a turn that read nothing is a turn with no context"
        # Exactly a prefix of the canonical order: in order and with no gap.
        assert seen == order[: len(seen)]
        # And never the reply the turn is about to write.
        assert snapshot["message_id"] not in seen


# -- write validity comes from the lease ------------------------------------------


def _room_of_one(store: InMemoryStore) -> tuple[ChatRoom, str]:
    """Build a bare room with one participant and no lease authority."""
    room = ChatRoom(
        store=store,
        interaction_id="interaction_" + _UUID.format(0x70),
        channels=[RoomChannel(key="chat")],
        now=lambda: _START,
    )
    actor_id = "actor_" + _UUID.format(0x71)
    room.add_member(RoomMember(actor_id=actor_id, channels=("chat",)))
    return room, actor_id


async def test_a_stranger_can_not_post_to_a_room_they_are_not_in() -> None:
    """Membership is the first gate: an actor the room never cast writes nothing."""
    store = InMemoryStore()
    room, _actor = _room_of_one(store)

    posted = await room.post(
        actor_id="actor_" + _UUID.format(0x99),
        channel_key="chat",
        text="let me in",
        message_id="message_" + _UUID.format(0x100),
        new_context=_Contexts(),
    )

    assert posted is None
    assert _messages(store) == []


async def test_a_fenced_connection_can_no_longer_speak_for_its_actor() -> None:
    """A refresh takes the lease on; whatever the old connection holds is refused."""
    store = InMemoryStore()
    gateway = Gateway(secret=_SECRET)
    spec = chat_spec(seat=_seat(_EchoAdapter()), participants=1)
    rendezvous = ChatMatchmaker(gateway, store, spec)

    visit = "visit_" + _UUID.format(0x63)
    seat = await rendezvous.join(visit_id=visit, activity_key="talk")
    stale = seat.lease
    assert stale is not None
    assert seat.room.may_write(seat.actor_id, "chat")

    # The participant refreshes: the same seat comes back at the next generation.
    again = await rendezvous.join(visit_id=visit, activity_key="talk")
    assert again.lease is not None
    assert again.lease.lease.generation == stale.lease.generation + 1
    assert again.room is seat.room
    assert seat.room.may_write(again.actor_id, "chat")

    # The connection that was replaced presents what it still holds.
    member = seat.room.member(seat.actor_id)
    assert member is not None
    member.lease = stale
    assert not seat.room.may_write(seat.actor_id, "chat")
    posted = await seat.room.post(
        actor_id=seat.actor_id,
        channel_key="chat",
        text="am I still here",
        message_id="message_" + _UUID.format(0x101),
        new_context=_Contexts(),
    )
    assert posted is None


async def test_a_room_holds_its_conversation_for_the_members_who_are_away() -> None:
    """A member with no live connection is delivered to when they come back."""
    store = InMemoryStore()
    room, first = _room_of_one(store)
    second = "actor_" + _UUID.format(0x72)
    room.add_member(RoomMember(actor_id=second, channels=("chat",)))
    contexts = _Contexts()
    ids = _Ids(0x3000)

    posted = await room.post(
        actor_id=first,
        channel_key="chat",
        text="are you there",
        message_id=ids("message"),
        new_context=contexts,
    )
    assert posted is not None
    # Nobody is attached, so nothing is delivered and nothing is recorded.
    assert await room.deliver(posted.message, new_context=contexts, new_id=ids) == ()
    assert _deliveries(store) == []

    arrived: list[str] = []

    async def sink(_message: Any, text: str) -> None:
        arrived.append(text)

    room.attach(second, sink)
    sent = await room.flush(second, new_context=contexts, new_id=ids)

    assert arrived == ["are you there"]
    assert [message.message_id for message in sent] == [posted.message.message_id]
    assert len(_deliveries(store)) == 1
    # And a second flush delivers it again to nobody: the watermark moved.
    assert await room.flush(second, new_context=contexts, new_id=ids) == ()


def test_a_room_with_no_channels_is_refused() -> None:
    """A conversation with nowhere to say anything is not a conversation."""
    with pytest.raises(ValueError, match="at least one channel"):
        ChatRoom(
            store=InMemoryStore(),
            interaction_id="interaction_" + _UUID.format(0x73),
            channels=[],
            now=lambda: _START,
        )
