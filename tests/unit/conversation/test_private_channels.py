"""Several model seats, and a channel one participant is not in (NS-05).

``ChatSpec.seat`` was singular, there was no public/private split, and the mount
asked no question about membership before it posted. So a study could not run a
partner model and a coach model in one conversation, and it could not give one
participant a side channel the other does not have.

These tests hold five promises:

- a study declares **several model seats**, each with its own activation rule;
- when two of them answer at once, the **publication order is the declared order**
  and not whichever provider finished first;
- an **activation budget** caps how many models answer one message, and the seats
  over the cap make no provider call at all;
- a **private channel** reaches only the participants who are in it: the other
  participant is not delivered its messages and is never told the channel exists;
- a participant who names a channel they are not in **writes nothing**, because a
  client must not reach a conversation by naming it.
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
from mug.authoring import Chat, Fallback, History, LLMAgent, Provider, Thoughts
from mug.conversation import TurnPolicy
from mug.gateway import Gateway
from mug.kernel import Digest
from mug.participant import ChatMatchmaker
from mug.participant_chat import (
    ChatChannel,
    ChatSeatSpec,
    ChatSpec,
    run_chat_activity,
)
from mug.providers import ModelCall, ModelCompletion, Usage
from mug.realtime import Session
from mug.runtime import CommandContext
from mug.storage import InMemoryStore, Store

_UUID = "019b6000-0000-7000-8000-{:012x}"
_START = datetime(2026, 7, 27, 0, 0, 0, tzinfo=timezone.utc)
_DIGEST = Digest(algorithm="sha-256", hex="a" * 64)
_SECRET = b"a-shared-deployment-secret------"

_PARTNER_ACTOR = "actor_" + _UUID.format(0x310)
_COACH_ACTOR = "actor_" + _UUID.format(0x311)
_THIRD_ACTOR = "actor_" + _UUID.format(0x312)


class _Model(LLMAgent):
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
        chat: Chat,
        thoughts: Thoughts,
    ) -> str:
        return ""


class _Voice:
    """A fake provider that answers in its own voice, after its own delay.

    ``yields`` is how many times the call gives the event loop away before it
    answers, which is how a slow model and a fast one are told apart with no clock
    and no flakiness.
    """

    def __init__(
        self, name: str, *, yields: int = 0, finished: list[str] | None = None
    ) -> None:
        self.name = name
        self.calls = 0
        self.payloads: list[Any] = []
        self._yields = yields
        self._finished = finished

    async def __call__(self, call: ModelCall) -> ModelCompletion:
        self.calls += 1
        self.payloads.append(call.payload)
        for _ in range(self._yields):
            await asyncio.sleep(0)
        if self._finished is not None:
            self._finished.append(self.name)
        return ModelCompletion(
            outcome="completed",
            resolved_model="fake-local",
            usage=Usage(input_tokens=1, output_tokens=1, cost_micros=0),
            output={"text": f"{self.name} says so"},
        )


class _FakeSocket:
    """A socket that replays scripted client frames and records what was sent."""

    def __init__(self, frames: list[Any]) -> None:
        self._inbound = list(frames)
        self.sent: list[dict[str, Any]] = []

    async def receive_text(self) -> str:
        if not self._inbound:
            raise WebSocketDisconnect(code=1000)
        frame = self._inbound.pop(0)
        return frame if isinstance(frame, str) else json.dumps(frame)

    async def send_json(self, payload: dict[str, Any]) -> None:
        self.sent.append(payload)

    def of_type(self, kind: str) -> list[dict[str, Any]]:
        return [frame for frame in self.sent if frame.get("type") == kind]


class _Script:
    """The exact interleaving of two clients' frames, as one ordered list."""

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


class _ScriptedSocket(_FakeSocket):
    """One client's socket, reading its own frames out of the shared script."""

    def __init__(self, script: _Script, who: str) -> None:
        super().__init__([])
        self._script = script
        self._who = who

    async def receive_text(self) -> str:
        frame = await self._script.next_for(self._who)
        return frame if isinstance(frame, str) else json.dumps(frame)


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


def _ids_for(key: str) -> AgentIds:
    return AgentIds(
        agent_version_id="agentver_" + _UUID.format(0x430),
        agent_definition_id="agentdef_" + _UUID.format(0x431),
        agent_key=key,
        version_number=1,
        prompt_version_id="promptver_" + _UUID.format(0x440),
        fallback_policy_key="chat-fallback",
    )


def _seat(actor_id: str, adapter: Any, key: str, **extra: Any) -> ChatSeatSpec:
    return ChatSeatSpec(
        agent=_Model(),
        adapter=adapter,
        ids=_ids_for(key),
        actor_id=actor_id,
        **extra,
    )


def _mention() -> TurnPolicy:
    """Return a policy that speaks only when the seat's own token is said."""
    return TurnPolicy(
        channel_key="chat", activation="mention", max_model_activations_per_turn=1
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
        key=lambda state: (state["channel_key"], int(state["sequence"])),
    )


def _deliveries(store: Store) -> list[dict[str, Any]]:
    return _of_schema(store, "mug.api-08.delivery-receipt")


async def _alone(
    frames: list[Any], spec: ChatSpec
) -> tuple[_FakeSocket, InMemoryStore]:
    """Run one participant through a conversation with several model seats."""
    store = InMemoryStore()
    socket = _FakeSocket(frames)
    await run_chat_activity(
        cast("Any", socket),
        _session("visit_" + _UUID.format(0x61)),
        spec,
        store=store,
        new_context=_Contexts(),
        new_id=_Ids(),
        now=lambda: _START,
    )
    return socket, store


# -- several seats in one channel -------------------------------------------------


async def test_two_model_seats_both_answer_one_message() -> None:
    """A study writes two models into a conversation and both are in it."""
    partner = _Voice("partner")
    coach = _Voice("coach")
    socket, store = await _alone(
        [{"type": "chat", "text": "hello"}, {"type": "chat_end"}],
        ChatSpec(
            seats=(
                _seat(_PARTNER_ACTOR, partner, "partner"),
                _seat(_COACH_ACTOR, coach, "coach"),
            ),
        ),
    )

    assert partner.calls == 1
    assert coach.calls == 1
    assert [frame["text"] for frame in socket.of_type("chat")] == [
        "partner says so",
        "coach says so",
    ]
    assert len(_messages(store)) == 3


async def test_the_declared_order_wins_over_whichever_model_answered_first() -> None:
    """Two models thinking at once must not make the transcript a race."""
    finished: list[str] = []
    slow = _Voice("partner", yields=6, finished=finished)
    fast = _Voice("coach", yields=0, finished=finished)
    _socket, store = await _alone(
        [{"type": "chat", "text": "hello"}, {"type": "chat_end"}],
        ChatSpec(
            seats=(
                _seat(_PARTNER_ACTOR, slow, "partner"),
                _seat(_COACH_ACTOR, fast, "coach"),
            ),
        ),
    )

    # The second seat's provider answered first...
    assert finished == ["coach", "partner"]
    # ...and the channel still records the study's declared order.
    assert [message["author_actor_id"] for message in _messages(store)][1:] == [
        _PARTNER_ACTOR,
        _COACH_ACTOR,
    ]


async def test_the_activation_budget_stops_a_response_storm_before_the_calls() -> None:
    """A guard that spends the calls and throws the replies away is not a guard."""
    voices = [_Voice(name) for name in ("one", "two", "three")]
    _socket, store = await _alone(
        [{"type": "chat", "text": "everybody talk"}, {"type": "chat_end"}],
        ChatSpec(
            seats=(
                _seat(_PARTNER_ACTOR, voices[0], "one"),
                _seat(_COACH_ACTOR, voices[1], "two"),
                _seat(_THIRD_ACTOR, voices[2], "three"),
            ),
            max_activations_per_turn=2,
        ),
    )

    assert [voice.calls for voice in voices] == [1, 1, 0]
    assert len(_messages(store)) == 3


async def test_a_seat_that_stays_quiet_does_not_spend_the_budget() -> None:
    """The budget is for the seats that will speak, not for the ones that will not.

    A seat its policy keeps quiet must not take a slot from a seat that would have
    answered: a budget spent on silence is a study that loses a voice it wrote.
    """
    voices = [_Voice(name) for name in ("quiet", "one", "two")]
    _socket, _store = await _alone(
        [{"type": "chat", "text": "hello everyone"}, {"type": "chat_end"}],
        ChatSpec(
            seats=(
                _seat(
                    _PARTNER_ACTOR,
                    voices[0],
                    "quiet",
                    policy=_mention(),
                    mention_token="quiet",
                ),
                _seat(_COACH_ACTOR, voices[1], "one"),
                _seat(_THIRD_ACTOR, voices[2], "two"),
            ),
            max_activations_per_turn=2,
        ),
    )

    assert [voice.calls for voice in voices] == [0, 1, 1]


async def test_a_seat_that_was_not_named_stays_quiet_while_another_answers() -> None:
    """Each seat has its own activation rule, in one room and one turn."""
    partner = _Voice("partner")
    coach = _Voice("coach")
    socket, _store = await _alone(
        [{"type": "chat", "text": "just chatting"}, {"type": "chat_end"}],
        ChatSpec(
            seats=(
                _seat(_PARTNER_ACTOR, partner, "partner"),
                _seat(
                    _COACH_ACTOR,
                    coach,
                    "coach",
                    policy=_mention(),
                    mention_token="coach",
                ),
            ),
        ),
    )

    assert partner.calls == 1
    assert coach.calls == 0
    assert [frame["text"] for frame in socket.of_type("chat")] == ["partner says so"]


def test_a_seat_that_names_a_channel_the_study_did_not_declare_is_refused() -> None:
    """A seat speaking into nowhere would be silent with nothing to say why."""
    with pytest.raises(ValueError, match="undeclared channels: advice"):
        ChatSpec(
            seats=(_seat(_COACH_ACTOR, _Voice("coach"), "coach", channel="advice"),),
            channels=(ChatChannel(key="chat"),),
        )


# -- a channel one participant is not in ------------------------------------------


def _coached_study() -> ChatSpec:
    """Two participants, a partner everybody shares, and a coach for seat one."""
    return ChatSpec(
        seats=(
            _seat(_PARTNER_ACTOR, _Voice("partner"), "partner"),
            _seat(
                _COACH_ACTOR,
                _Voice("coach"),
                "coach",
                channel="coach",
                hears=("chat",),
            ),
        ),
        channels=(
            ChatChannel(key="chat"),
            ChatChannel(key="coach", visibility="private", seats=("seat-1",)),
        ),
        participants=2,
        max_messages=4,
    )


async def _two_participants(
    steps: list[tuple[str, Any]], spec: ChatSpec, store: InMemoryStore
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


def _seat_of(socket: _ScriptedSocket) -> str:
    return str(socket.of_type("chat_room")[0]["seat"])


def _by_seat(
    first: _ScriptedSocket, second: _ScriptedSocket
) -> tuple[_ScriptedSocket, _ScriptedSocket]:
    """Return the sockets as (the coached participant, the other one)."""
    return (first, second) if _seat_of(first) == "seat-1" else (second, first)


async def test_only_the_coached_participant_is_told_the_channel_exists() -> None:
    """The client manifest is per participant: it does not name what is not theirs."""
    store = InMemoryStore()
    first, second = await _two_participants(
        [
            ("a", {"type": "chat", "text": "hello"}),
            ("a", {"type": "chat_end"}),
            ("b", {"type": "chat_end"}),
        ],
        _coached_study(),
        store,
    )
    coached, other = _by_seat(first, second)

    assert coached.of_type("chat_room")[0]["channels"] == ["chat", "coach"]
    assert other.of_type("chat_room")[0]["channels"] == ["chat"]


async def test_a_private_message_never_reaches_the_other_participant() -> None:
    """Not hidden by the client: never sent, and no receipt says it was."""
    store = InMemoryStore()
    first, second = await _two_participants(
        [
            ("a", {"type": "chat", "text": "how am I doing"}),
            ("a", {"type": "chat_end"}),
            ("b", {"type": "chat_end"}),
        ],
        _coached_study(),
        store,
    )
    coached, other = _by_seat(first, second)

    private = [
        message for message in _messages(store) if message["channel_key"] == "coach"
    ]
    assert private, "the coach answered on its own channel"
    assert all(message["visibility"] == "private" for message in private)

    coach_ids = {message["message_id"] for message in private}
    reached = {
        receipt["recipient_actor_id"]
        for receipt in _deliveries(store)
        if receipt["message_id"] in coach_ids
    }
    # One recipient: the participant the channel is for. Not the other person, and
    # not the partner model, neither of which is a member of it.
    assert len(reached) == 1
    assert _PARTNER_ACTOR not in reached
    assert _COACH_ACTOR not in reached  # and not the author of its own message

    # The other participant read no coach message on their socket...
    assert all(frame.get("channel") != "coach" for frame in other.of_type("chat"))
    # ...and the coached participant did.
    assert any(frame.get("channel") == "coach" for frame in coached.of_type("chat"))
    # The frame that names the channels carries no internal actor id.
    assert "actor_id" not in other.of_type("chat_room")[0]


async def test_a_model_seat_never_reads_a_channel_it_is_not_in() -> None:
    """What a seat is prompted with is what it may see, not what the room holds.

    The partner model is not in the coaching channel. If the room handed it the
    whole conversation, a private exchange would reach a model the study never put
    in it -- and from there, back out into the public channel.
    """
    store = InMemoryStore()
    partner = _Voice("partner")
    coach = _Voice("coach")
    spec = ChatSpec(
        seats=(
            _seat(_PARTNER_ACTOR, partner, "partner"),
            _seat(_COACH_ACTOR, coach, "coach", channel="coach", hears=("chat",)),
        ),
        channels=(
            ChatChannel(key="chat"),
            ChatChannel(key="coach", visibility="private", seats=("seat-1",)),
        ),
        participants=2,
        max_messages=4,
    )
    await _two_participants(
        [
            ("a", {"type": "chat", "text": "first"}),
            ("a", {"type": "chat", "text": "second"}),
            ("a", {"type": "chat_end"}),
            ("b", {"type": "chat_end"}),
        ],
        spec,
        store,
    )

    said: list[str] = []
    for payload in partner.payloads:
        lines = cast("dict[str, Any]", payload)["messages"]
        said += [line["text"] for line in cast("list[dict[str, str]]", lines)]
    assert "first" in said, "the partner read the public channel"
    assert coach.calls >= 1, "the coach answered on its private channel"
    assert not any("coach says so" in line for line in said)


async def test_who_was_in_which_channel_is_recorded_and_not_only_remembered(
) -> None:
    """A private channel that leaves no evidence is a claim, not a finding.

    The room's membership map is memory: it is gone when the process is. So the
    formation writes it down -- one ``ChannelInstance`` per channel with its
    ordering guarantee, and one ``Membership`` per actor per channel, including
    the ``none`` that says who was kept out.
    """
    store = InMemoryStore()
    first, second = await _two_participants(
        [
            ("a", {"type": "chat", "text": "hello"}),
            ("a", {"type": "chat_end"}),
            ("b", {"type": "chat_end"}),
        ],
        _coached_study(),
        store,
    )
    _coached, _other = _by_seat(first, second)

    instances = _of_schema(store, "mug.api-06.channel-instance")
    assert {one["channel_key"] for one in instances} == {"chat", "coach"}
    # Every message goes through the server, so a chat channel is totally ordered.
    assert {one["ordering"] for one in instances} == {"total"}
    assert {one["channel_type"] for one in instances} == {"chat"}

    memberships = _of_schema(store, "mug.api-06.membership")
    access = {
        (one["actor_id"], one["channel_key"]): one["access"] for one in memberships
    }
    # Two participants and two model seats, over two channels.
    assert len(access) == 8
    coach_access = {
        actor: value for (actor, key), value in access.items() if key == "coach"
    }
    # Exactly one participant and the coach seat are in it; the rest are recorded
    # as having no access at all, which is what makes the exclusion evidence.
    assert sorted(coach_access.values()) == ["none", "none", "read_write", "read_write"]
    assert coach_access[_COACH_ACTOR] == "read_write"
    assert coach_access[_PARTNER_ACTOR] == "none"


async def test_a_participant_naming_a_channel_they_are_not_in_writes_nothing(
) -> None:
    """A client must not reach a conversation it was never put in by naming it."""
    store = InMemoryStore()
    first, second = await _two_participants(
        [
            ("b", {"type": "chat", "text": "let me in", "channel": "coach"}),
            ("a", {"type": "chat_end"}),
            ("b", {"type": "chat_end"}),
        ],
        _coached_study(),
        store,
    )
    _coached, _other = _by_seat(first, second)

    assert [
        message for message in _messages(store) if message["channel_key"] == "coach"
    ] == []
    assert _messages(store) == []
