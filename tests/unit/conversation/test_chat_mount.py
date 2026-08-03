"""The chat mount owns a socket, records a conversation, and survives a bad client.

These tests drive ``mug.participant_chat.run_chat_activity`` directly against a fake
socket, the in-memory store, a fixed clock, and a deterministic fake provider, so the
whole conversation runs with no network and no application. They cover what the
end-to-end flow test can not reach comfortably: a participant who disconnects in the
middle, frames that are not valid json, text that exceeds the bound, a policy with no
moderator, and the transcript the study's prompt composer reads.
"""

from __future__ import annotations

import itertools
import json
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, cast

from fastapi import WebSocketDisconnect

from mug.agents import AgentIds
from mug.authoring import Fallback, History, LLMAgent, Provider, Thoughts, Transcript
from mug.conversation import ChatMessage, TurnPolicy
from mug.kernel import Digest
from mug.participant_chat import ChatSeatSpec, ChatSpec, run_chat_activity
from mug.providers import ModelCall, ModelCompletion, Usage
from mug.providers.runtime import Payload
from mug.realtime import Session
from mug.runtime import CommandContext
from mug.storage import InMemoryStore, StorageError, Store
from tests.support.chat import chat_spec

_UUID = "019b6000-0000-7000-8000-{:012x}"

_START = datetime(2026, 7, 25, 0, 0, 0, tzinfo=timezone.utc)
_DIGEST = Digest(algorithm="sha-256", hex="a" * 64)
_AGENT_ACTOR = "actor_" + _UUID.format(0x300)


class _Partner(LLMAgent):
    """An author's chat agent: a keyless local runner.

    ``get_prompt`` renders the conversation the way the shipped example does, because
    that is the one hook an author writes and the mount has to send what it returns.
    A double whose prompt says nothing would let the mount drop the author's words
    and still pass.
    """

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
        return "\n".join(f"{one.sender}: {one.text}" for one in chat.last(50))


def said_to(payload: Any) -> str:
    """Return the last thing a participant said, read out of what the model was sent.

    An agent with a prompt of its own sends one message holding the whole rendered
    conversation; an agent with none sends the labelled transcript. The double reads
    both, because both are shapes a study really runs.
    """
    messages = cast("list[Any]", cast("dict[str, Any]", payload)["messages"])
    spoken = [
        str(cast("dict[str, Any]", one)["content"])
        for one in messages
        if cast("dict[str, Any]", one).get("role") == "user"
    ]
    if not spoken:
        return ""
    lines = [line for line in spoken[-1].splitlines() if line.startswith("user: ")]
    return lines[-1][len("user: ") :] if lines else spoken[-1]


def prompt_of(payload: Any) -> str:
    """Return the one prompt string a payload carries, in the shape a provider reads.

    Every provider names the words of a message ``content``. Reading it under any
    other name here is what let the mount send a payload no provider could read.
    """
    messages = cast("dict[str, Any]", payload)["messages"]
    return "\n".join(
        str(cast("dict[str, Any]", one)["content"])
        for one in cast("list[Any]", messages)
    )


class _EchoAdapter:
    """A fake provider that echoes the last thing said and keeps every payload."""

    def __init__(self) -> None:
        self.payloads: list[Any] = []

    async def __call__(self, call: ModelCall) -> ModelCompletion:
        self.payloads.append(call.payload)
        return ModelCompletion(
            outcome="completed",
            resolved_model="fake-local",
            usage=Usage(input_tokens=1, output_tokens=1, cost_micros=0),
            output={"text": f"you said {said_to(call.payload)}"},
        )


class _FakeSocket:
    """A socket that replays scripted client frames and records what was sent.

    Once the script runs out the socket raises ``WebSocketDisconnect``, which is
    exactly what a real socket does when the participant closes the tab.
    """

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

    @property
    def chats(self) -> list[dict[str, Any]]:
        """Return only the chat frames the mount pushed."""
        return [frame for frame in self.sent if frame.get("type") == "chat"]


class _Contexts:
    """Mint a fresh command context on one aggregate's stream, keyed by its id."""

    def __init__(self) -> None:
        self._counter = itertools.count(1)

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
                "recorded_at": "2026-07-25T00:00:00.000000Z",
                "event_data_handling": {"privacy_labels": ["research"]},
            }
        )


class _Ids:
    """Mint deterministic runtime-occurrence ids, one counter per kind."""

    def __init__(self) -> None:
        self._counter = itertools.count(1)

    def __call__(self, kind: str) -> str:
        return f"{kind}_" + _UUID.format(0x1000 + next(self._counter))


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


def _session() -> Session:
    session = Session.__new__(Session)
    session.principal = None  # type: ignore[assignment]
    session.cursor = 0
    session.state = {"flow_id": "visitplan_" + _UUID.format(0x50)}
    session.outbox = []
    return session


async def _run(
    frames: list[Any], spec: ChatSpec, store: InMemoryStore | None = None
) -> tuple[_FakeSocket, list[str], InMemoryStore]:
    """Run one chat activity over a scripted socket and return what it produced."""
    store = store or InMemoryStore()
    socket = _FakeSocket(frames)
    streams = await run_chat_activity(
        cast("Any", socket),
        _session(),
        spec,
        store=store,
        new_context=_Contexts(),
        new_id=_Ids(),
        now=lambda: _START,
    )
    return socket, streams, store


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


def _messages(store: Store) -> list[dict[str, Any]]:
    """Return every recorded chat message, in sequence order."""
    found = [
        state
        for state in _states(store)
        if _schema_name(state) == "mug.api-08.chat-message"
    ]
    return sorted(found, key=lambda state: int(state["sequence"]))


async def test_a_disconnect_mid_conversation_keeps_what_was_already_said() -> None:
    """The participant closes the tab: the exchange so far is recorded, not lost."""
    adapter = _EchoAdapter()
    socket, streams, store = await _run(
        [{"type": "chat", "text": "first"}], chat_spec(seat=_seat(adapter))
    )

    # The script ran out, which the socket reports as a disconnect.
    assert len(socket.chats) == 1
    messages = _messages(store)
    assert [message["sequence"] for message in messages] == [1, 2]
    assert len(streams) == 2


async def test_a_disconnect_before_the_first_message_records_nothing() -> None:
    """A participant who leaves at once leaves an empty conversation behind."""
    _socket, streams, store = await _run([], chat_spec(seat=_seat(_EchoAdapter())))

    assert streams == []
    assert _messages(store) == []


async def test_a_malformed_frame_does_not_end_the_activity() -> None:
    """Bad json and non-object frames are dropped; the conversation carries on."""
    adapter = _EchoAdapter()
    socket, _streams, store = await _run(
        [
            "{not json at all",
            "[1, 2, 3]",
            '"a bare string"',
            {"type": "chat", "text": "still here"},
            {"type": "chat_end"},
        ],
        chat_spec(seat=_seat(adapter)),
    )

    assert len(socket.chats) == 1
    assert socket.chats[0]["text"] == "you said still here"
    assert len(_messages(store)) == 2


async def test_an_unknown_frame_type_is_ignored() -> None:
    """A frame the mount does not own costs no turn and produces no reply."""
    adapter = _EchoAdapter()
    socket, _streams, store = await _run(
        [
            {"type": "input", "keys": ["ArrowLeft"]},
            {"type": "chat", "text": "hello"},
            {"type": "chat_end"},
        ],
        chat_spec(seat=_seat(adapter)),
    )

    assert len(socket.chats) == 1
    assert len(_messages(store)) == 2


async def test_a_message_with_no_text_field_is_ignored() -> None:
    """A chat frame that carries no text is dropped rather than posted empty."""
    adapter = _EchoAdapter()
    _socket, streams, store = await _run(
        [{"type": "chat"}, {"type": "chat", "text": 17}, {"type": "chat_end"}],
        chat_spec(seat=_seat(adapter)),
    )

    assert streams == []
    assert _messages(store) == []
    assert adapter.payloads == []


async def test_long_text_is_trimmed_to_the_bound() -> None:
    """A participant can not post an unbounded payload into the ledger."""
    adapter = _EchoAdapter()
    await _run(
        [{"type": "chat", "text": "x" * 5000}, {"type": "chat_end"}],
        chat_spec(seat=_seat(adapter), max_message_length=100),
    )

    assert len(said_to(adapter.payloads[0])) == 100


async def test_a_moderated_policy_stays_silent_with_no_moderator() -> None:
    """The mount carries no moderator, so a moderated channel records no reply."""
    adapter = _EchoAdapter()
    policy = TurnPolicy(
        channel_key="chat", activation="moderated", max_model_activations_per_turn=1
    )
    socket, _streams, store = await _run(
        [{"type": "chat", "text": "hello"}, {"type": "chat_end"}],
        chat_spec(seat=_seat(adapter), policy=policy),
    )

    assert socket.chats == []
    assert adapter.payloads == []
    assert len(_messages(store)) == 1


async def test_the_default_prompt_carries_the_transcript_with_its_roles() -> None:
    """The model reads the conversation so far, each message labelled by author."""
    adapter = _EchoAdapter()
    await _run(
        [
            {"type": "chat", "text": "one"},
            {"type": "chat", "text": "two"},
            {"type": "chat_end"},
        ],
        chat_spec(seat=_seat(adapter)),
    )

    assert len(adapter.payloads) == 2
    assert prompt_of(adapter.payloads[1]).splitlines() == [
        "user: one",
        "assistant: you said one",
        "user: two",
    ]


async def test_the_provider_is_sent_the_prompt_the_author_wrote() -> None:
    """The one hook an author has is the one the mount sends.

    ``LLMAgent.get_prompt`` says what a model is for, and its contract is that MUG
    sends exactly the string it returns. The mount used to send a transcript of its
    own instead, so every instruction an author wrote was dropped on the way to the
    provider and the model answered with no idea what it was there to do.
    """

    class _Instructed(_Partner):
        def get_prompt(
            self,
            env: object,
            agent_id: str,
            history: History,
            chat: Transcript,
            thoughts: Thoughts,
        ) -> str:
            return "ANSWER ONLY IN LATIN\n" + "\n".join(
                f"{one.sender}: {one.text}" for one in chat.last(50)
            )

    adapter = _EchoAdapter()
    seat = replace(_seat(adapter), agent=_Instructed())
    await _run(
        [{"type": "chat", "text": "hello"}, {"type": "chat_end"}], chat_spec(seat=seat)
    )

    sent = cast("dict[str, Any]", adapter.payloads[0])["messages"]
    assert sent == [{"role": "user", "content": "ANSWER ONLY IN LATIN\nuser: hello"}]


async def test_an_agent_that_writes_no_prompt_still_reads_the_conversation() -> None:
    """A model with no instructions is sent the labelled transcript, and talks.

    The words go under ``content`` in this shape too, because that is where every
    provider looks for them: Ollama answers the empty question it was asked and
    Anthropic refuses the request outright.
    """

    class _Silent(LLMAgent):
        provider = Provider.OSS
        model = "fake-local"

    adapter = _EchoAdapter()
    seat = replace(_seat(adapter), agent=_Silent())
    await _run(
        [
            {"type": "chat", "text": "one"},
            {"type": "chat", "text": "two"},
            {"type": "chat_end"},
        ],
        chat_spec(seat=seat),
    )

    assert cast("dict[str, Any]", adapter.payloads[1])["messages"] == [
        {"role": "user", "content": "one"},
        {"role": "assistant", "content": "you said one"},
        {"role": "user", "content": "two"},
    ]


async def test_the_agents_own_temperature_reaches_the_provider() -> None:
    """A field an author sets on the agent is a field the call carries."""

    class _Warm(_Partner):
        temperature = 0.25

    adapter = _EchoAdapter()
    seat = replace(_seat(adapter), agent=_Warm())
    await _run(
        [{"type": "chat", "text": "hello"}, {"type": "chat_end"}], chat_spec(seat=seat)
    )

    assert cast("dict[str, Any]", adapter.payloads[0])["temperature"] == 0.25


async def test_the_context_window_bounds_what_the_model_reads() -> None:
    """A long conversation sends only the most recent messages to the model."""
    adapter = _EchoAdapter()
    await _run(
        [
            {"type": "chat", "text": "one"},
            {"type": "chat", "text": "two"},
            {"type": "chat", "text": "three"},
            {"type": "chat_end"},
        ],
        chat_spec(seat=_seat(adapter), context_messages=2),
    )

    read = prompt_of(adapter.payloads[2]).splitlines()
    assert len(read) == 2
    assert read[-1] == "user: three"


async def test_a_study_may_replace_the_prompt_and_the_reply_rendering() -> None:
    """Both study seams are honoured: the payload shape and the reply text."""

    def compose(recent: list[ChatMessage]) -> Payload:
        return {"turns": len(recent)}

    def render(output: Any) -> str:
        return f"[{cast('dict[str, Any]', output)['echo']}]"

    async def adapter(call: ModelCall) -> ModelCompletion:
        payload = cast("dict[str, Any]", call.payload)
        return ModelCompletion(
            outcome="completed",
            resolved_model="fake-local",
            usage=Usage(input_tokens=1, output_tokens=1, cost_micros=0),
            output={"echo": payload["turns"]},
        )

    socket, _streams, _store = await _run(
        [{"type": "chat", "text": "hello"}, {"type": "chat_end"}],
        chat_spec(seat=_seat(adapter), compose=compose, render_reply=render),
    )

    assert socket.chats[0]["text"] == "[1]"


async def test_the_conversation_runs_on_one_interaction() -> None:
    """Every message of one activity belongs to the same interaction."""
    adapter = _EchoAdapter()
    _socket, _streams, store = await _run(
        [
            {"type": "chat", "text": "one"},
            {"type": "chat", "text": "two"},
            {"type": "chat_end"},
        ],
        chat_spec(seat=_seat(adapter), channel_key="interview"),
    )

    messages = _messages(store)
    assert len({message["interaction_id"] for message in messages}) == 1
    assert {message["channel_key"] for message in messages} == {"interview"}


class _RefusingStore(InMemoryStore):
    """A store that refuses to commit a chat message, and takes everything else."""

    async def commit(self, **kwargs: Any) -> Any:
        state = kwargs.get("new_state")
        if isinstance(state, dict):
            name = _schema_name(cast("dict[str, Any]", state))
            if name == "mug.api-08.chat-message":
                raise StorageError("command.state_conflict", "the aggregate conflicts")
        return await super().commit(**kwargs)


async def test_a_refused_post_is_dropped_whole_and_never_reaches_the_model() -> None:
    """A message the ledger would not take is not held locally and costs no call.

    The channel does not advance its sequence for a refused post, so a message kept
    in the transcript but missing from the ledger would put the model's context and
    the recorded evidence permanently out of step.
    """
    adapter = _EchoAdapter()
    socket, streams, store = await _run(
        [{"type": "chat", "text": "hello"}, {"type": "chat_end"}],
        chat_spec(seat=_seat(adapter)),
        store=_RefusingStore(),
    )

    assert streams == []
    assert socket.chats == []
    assert adapter.payloads == []
    assert _messages(store) == []


async def test_an_activity_with_no_flow_records_nothing() -> None:
    """A connection that carries no flow is not a visit, so nothing is recorded."""
    store = InMemoryStore()
    session = _session()
    session.state = {}
    streams = await run_chat_activity(
        cast("Any", _FakeSocket([{"type": "chat", "text": "hello"}])),
        session,
        chat_spec(seat=_seat(_EchoAdapter())),
        store=store,
        new_context=_Contexts(),
        new_id=_Ids(),
        now=lambda: _START,
    )

    assert streams == []
    assert _messages(store) == []
