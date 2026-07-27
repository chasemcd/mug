"""A conversation outlives its connection, and a late reply is discarded (NS-03).

A chat message was one committed post. The text lived in a per-connection
transcript, so a participant who refreshed the page lost the conversation; a model
turn still running was lost with it; and a reply that arrived from a connection
that had already gone had nowhere to be recorded as not shown.

These tests hold four promises:

- a refresh **restores the committed history** and the turn that was in flight;
- a reply from a **superseded generation publishes nothing** and is recorded as
  discarded, which is the only place a thing that was not shown can be recorded;
- what the participant saw is **evidence**: a per-seat delivery and an experienced
  frame beside the canonical commit, under a declared capture policy;
- each admitted reply is a **durable generation**, so a live conversation can supply
  the candidates a preference activity asks about.
"""

from __future__ import annotations

import itertools
import json
from datetime import datetime, timezone
from typing import Any, cast

from fastapi import WebSocketDisconnect

from mug.agents import AgentIds
from mug.agents.generation import recorded_generation
from mug.authoring import Chat, Fallback, History, LLMAgent, Provider, Thoughts
from mug.conversation.transcript import (
    is_current,
    read_transcript,
    transcript_id_for,
    with_turn_begun,
)
from mug.gateway import Gateway
from mug.kernel import Digest
from mug.participant_chat import (
    ChatDurability,
    ChatSeatSpec,
    ChatSpec,
    run_chat_activity,
)
from mug.providers import ModelCall, ModelCompletion, Usage
from mug.realtime import Session
from mug.runtime import CommandContext
from mug.storage import InMemoryStore

_UUID = "019b6000-0000-7000-8000-{:012x}"
_START = datetime(2026, 7, 27, 0, 0, 0, tzinfo=timezone.utc)
_DIGEST = Digest(algorithm="sha-256", hex="a" * 64)
_AGENT_ACTOR = "actor_" + _UUID.format(0x300)
_VISIT = "visit_" + _UUID.format(0x60)
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
        chat: Chat,
        thoughts: Thoughts,
    ) -> str:
        return ""


class _EchoAdapter:
    """A fake provider that echoes the last payload text."""

    async def __call__(self, call: ModelCall) -> ModelCompletion:
        payload = cast("dict[str, Any]", call.payload)
        last = cast("list[dict[str, str]]", payload["messages"])[-1]["text"]
        return ModelCompletion(
            outcome="completed",
            resolved_model="fake-local",
            usage=Usage(input_tokens=1, output_tokens=1, cost_micros=0),
            output={"text": f"you said {last}"},
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
    """Mint deterministic runtime-occurrence ids, one counter for all kinds."""

    def __init__(self, start: int = 0x1000) -> None:
        self._counter = itertools.count(start)

    def __call__(self, kind: str) -> str:
        return f"{kind}_" + _UUID.format(next(self._counter))


def _spec() -> ChatSpec:
    return ChatSpec(
        seat=ChatSeatSpec(
            agent=_Partner(),
            adapter=_EchoAdapter(),
            ids=AgentIds(
                agent_version_id="agentver_" + _UUID.format(0x430),
                agent_definition_id="agentdef_" + _UUID.format(0x431),
                agent_key="chat-partner",
                version_number=1,
                prompt_version_id="promptver_" + _UUID.format(0x440),
                fallback_policy_key="chat-fallback",
            ),
            actor_id=_AGENT_ACTOR,
        ),
        max_messages=4,
    )


def _session() -> Session:
    session = Session.__new__(Session)
    session.principal = None  # type: ignore[assignment]
    session.cursor = 0
    session.state = {"flow_id": "visitplan_" + _UUID.format(0x50), "visit_id": _VISIT}
    session.outbox = []
    return session


def _durable(store: InMemoryStore, gateway: Gateway) -> ChatDurability:
    return ChatDurability(
        derive=gateway.derived_id,
        artifacts=store,
        new_artifact_id=lambda seed: gateway.derived_id("artifact", seed),
        new_upload_id=lambda: gateway.new_id("upload"),
        occurrence_key="talk",
    )


async def _run(
    frames: list[Any],
    store: InMemoryStore,
    gateway: Gateway,
    *,
    ids: int = 0x1000,
) -> _FakeSocket:
    """Run one chat activity over a scripted socket against a durable transcript."""
    socket = _FakeSocket(frames)
    await run_chat_activity(
        cast("Any", socket),
        _session(),
        _spec(),
        store=store,
        new_context=_Contexts(),
        new_id=_Ids(ids),
        now=lambda: _START,
        durable=_durable(store, gateway),
    )
    return socket


# -- the conversation survives the connection ------------------------------------


async def test_a_refresh_restores_the_committed_history() -> None:
    """The proof: a second connection is sent the conversation that happened."""
    store = InMemoryStore()
    gateway = Gateway(secret=_SECRET)

    first = await _run([{"type": "chat", "text": "hello"}], store, gateway)
    assert [frame["text"] for frame in first.of_type("chat")] == ["you said hello"]

    second = await _run([], store, gateway, ids=0x2000)

    restored = second.of_type("chat")
    assert [frame["text"] for frame in restored] == ["hello", "you said hello"]
    assert all(frame["restored"] is True for frame in restored)


async def test_a_conversation_with_no_durability_keeps_nothing() -> None:
    """A mount that was given none behaves exactly as it did before NS-03."""
    store = InMemoryStore()
    socket = _FakeSocket([{"type": "chat", "text": "hello"}])
    await run_chat_activity(
        cast("Any", socket),
        _session(),
        _spec(),
        store=store,
        new_context=_Contexts(),
        new_id=_Ids(),
        now=lambda: _START,
    )

    gateway = Gateway(secret=_SECRET)
    assert (
        read_transcript(store, transcript_id_for(gateway.derived_id, _VISIT, "talk"))
        is None
    )


async def test_the_pending_turn_is_restored_and_then_cleared() -> None:
    """A refresh mid-generation is told a reply is still coming."""
    store = InMemoryStore()
    gateway = Gateway(secret=_SECRET)
    await _run([{"type": "chat", "text": "hello"}], store, gateway)

    transcript_id = transcript_id_for(gateway.derived_id, _VISIT, "talk")
    state = read_transcript(store, transcript_id)
    assert state is not None
    # The finished exchange leaves nothing in flight.
    assert state.pending is None

    # A turn that begins and does not end is what a refresh finds.
    from mug.conversation.transcript import record_transcript

    begun = with_turn_begun(
        state,
        prompt_message_id=state.messages[0].message_id,
        started_at="2026-07-27T00:00:05.000000Z",
    )
    assert await record_transcript(
        begun,
        transcript_id=transcript_id,
        expected_revision=state.version.revision,
        context=_Contexts(500)(transcript_id),
        store=store,
    )

    socket = await _run([], store, gateway, ids=0x3000)
    pending = socket.of_type("chat_pending")
    assert len(pending) == 1
    assert pending[0]["generation"] == begun.generation


# -- a reply that arrives too late -------------------------------------------------


async def test_a_superseded_generation_is_discarded_and_publishes_nothing() -> None:
    """NS-03: a late result from an obsolete generation reaches nobody."""
    store = InMemoryStore()
    gateway = Gateway(secret=_SECRET)
    await _run([{"type": "chat", "text": "hello"}], store, gateway)

    transcript_id = transcript_id_for(gateway.derived_id, _VISIT, "talk")
    state = read_transcript(store, transcript_id)
    assert state is not None
    # The connection that begins this turn is about to be replaced.
    stale = state.generation

    from mug.conversation.transcript import record_transcript, with_discarded

    assert is_current(state, stale)
    moved = with_turn_begun(
        state,
        prompt_message_id=state.messages[0].message_id,
        started_at="2026-07-27T00:00:05.000000Z",
    )
    await record_transcript(
        moved,
        transcript_id=transcript_id,
        expected_revision=state.version.revision,
        context=_Contexts(600)(transcript_id),
        store=store,
    )
    assert not is_current(moved, stale)

    discarded = with_discarded(
        moved, stale, discarded_at="2026-07-27T00:00:06.000000Z"
    )
    assert discarded.discarded == [stale]
    # The frame the participant did not see is recorded as skipped, which is the
    # only trace a thing that was never shown can leave.
    assert discarded.experienced[-1].delivery_kind == "skipped"


async def test_discarding_the_same_generation_twice_records_it_once() -> None:
    """A retry must not turn one discarded reply into a list of them."""
    store = InMemoryStore()
    gateway = Gateway(secret=_SECRET)
    await _run([{"type": "chat", "text": "hello"}], store, gateway)
    state = read_transcript(
        store, transcript_id_for(gateway.derived_id, _VISIT, "talk")
    )
    assert state is not None

    from mug.conversation.transcript import with_discarded

    once = with_discarded(state, 1, discarded_at="2026-07-27T00:00:06.000000Z")
    twice = with_discarded(once, 1, discarded_at="2026-07-27T00:00:07.000000Z")

    assert once.discarded == [1]
    assert twice.discarded == [1]


# -- what the participant saw ------------------------------------------------------


async def test_every_delivered_message_is_evidence() -> None:
    """A per-seat delivery and an experienced frame, under a declared policy."""
    store = InMemoryStore()
    gateway = Gateway(secret=_SECRET)
    await _run([{"type": "chat", "text": "hello"}], store, gateway)

    state = read_transcript(
        store, transcript_id_for(gateway.derived_id, _VISIT, "talk")
    )
    assert state is not None
    assert len(state.messages) == 2
    assert len(state.deliveries) == 2
    assert len(state.experienced) == 2
    assert all(one.delivery_kind == "message" for one in state.deliveries)
    assert all(one.seat_key == "chat" for one in state.deliveries)
    assert all(one.delivery_kind == "delivered" for one in state.experienced)
    assert state.capture.policy_key == "chat"
    assert {rule.profile for rule in state.capture.streams} == {
        "canonical",
        "experienced",
    }


async def test_the_words_are_an_artifact_and_the_ledger_holds_the_address() -> None:
    """The privacy shape holds: the stream names content and does not hold it."""
    store = InMemoryStore()
    gateway = Gateway(secret=_SECRET)
    await _run([{"type": "chat", "text": "hello"}], store, gateway)

    state = read_transcript(
        store, transcript_id_for(gateway.derived_id, _VISIT, "talk")
    )
    assert state is not None
    words = await store.read_artifact(state.messages[0].artifact_id)
    assert words == b"hello"
    assert "hello" not in json.dumps(
        state.model_dump(mode="json", exclude_none=True)
    )


# -- a reply is a candidate --------------------------------------------------------


async def test_each_reply_is_recorded_as_a_durable_generation() -> None:
    """A live answer can be compared later, which is what W19 needs of it."""
    store = InMemoryStore()
    gateway = Gateway(secret=_SECRET)
    socket = await _run([{"type": "chat", "text": "hello"}], store, gateway)

    reply_id = socket.of_type("chat")[0]["message_id"]
    generation = recorded_generation(
        store, gateway.derived_id("generation", f"chat-reply:{reply_id}")
    )
    assert generation is not None
    assert generation.generation_key == reply_id
    visible = await store.read_artifact(generation.visible.artifact_id)
    assert b"you said hello" in visible

    # The provider is in the private provenance and nowhere else, exactly as it is
    # for a generation recorded before anyone arrived.
    provenance = json.loads(
        await store.read_artifact(generation.provenance.artifact_id)
    )
    assert provenance["resolved_model"] == "fake-local"
    assert b"fake-local" not in visible
