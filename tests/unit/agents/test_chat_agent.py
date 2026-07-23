"""The chat agent decides, calls the model, and posts a reply into a channel.

These tests drive ``mug.agents.chat.ChatAgent`` against the in-memory store with a
fixed clock, a deterministic ``FakeProvider``, and hand-built command contexts. They
prove: a turn the policy admits posts a reply whose content digest is the model
output's own digest, and records the context snapshot the model saw; a turn the
policy refuses stays silent and never calls the model; and the activation cap makes a
second free turn stay silent.
"""

from __future__ import annotations

import itertools
from datetime import datetime, timezone

from mug.agents import ChatAgent, ChatTurn
from mug.conversation import ChatMessage, ConversationChannel, TurnPolicy
from mug.kernel import Digest, compute_digest
from mug.providers import AgentVersion, FakeProvider, ModelProvider
from mug.providers.runtime import ModelCall, ModelCompletion
from mug.runtime import CommandContext
from mug.storage import InMemoryStore

_UUID = "019b6000-0000-7000-8000-{:012x}"
_START = datetime(2026, 7, 22, 0, 0, 0, tzinfo=timezone.utc)
_DIGEST = Digest(algorithm="sha-256", hex="a" * 64)
_INTERACTION = "interaction_" + _UUID.format(0x200)
_HUMAN = "actor_" + _UUID.format(0x300)
_AGENT = "actor_" + _UUID.format(0x301)


def _agent_version() -> AgentVersion:
    return AgentVersion(
        agent_version_id="agentver_" + _UUID.format(0x430),
        agent_definition_id="agentdef_" + _UUID.format(0x431),
        agent_key="chat-partner",
        version_number=1,
        provider="anthropic",
        model_selector="claude-sonnet-4-5",
        prompt_version_id="promptver_" + _UUID.format(0x440),
        parameters_digest=_DIGEST,
        tool_version_ids=[],
        fallback_policy_key="chat-fallback",
        secret_name="chat-provider-key",
    )


class _CountingProvider(FakeProvider):
    """A fake provider that counts every model call it answers."""

    def __init__(self) -> None:
        super().__init__(lambda payload: {"text": "a reply"})
        self.calls = 0

    async def __call__(self, call: ModelCall) -> ModelCompletion:
        self.calls += 1
        return await super().__call__(call)


class _Factory:
    """Mint a fresh command context on an aggregate's stream, keyed by its id."""

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
                "recorded_at": "2026-07-22T00:00:00.000000Z",
                "event_data_handling": {"privacy_labels": ["research"]},
            }
        )


def _channel(store: InMemoryStore) -> ConversationChannel:
    return ConversationChannel(
        store=store,
        interaction_id=_INTERACTION,
        channel_key="lobby",
        now=lambda: _START,
    )


def _provider(store: InMemoryStore, adapter: _CountingProvider) -> ModelProvider:
    gens = itertools.count(1)
    return ModelProvider(
        store=store,
        adapter=adapter,  # type: ignore[arg-type]
        now=lambda: _START,
        new_generation_id=lambda: "generation_" + _UUID.format(next(gens)),
    )


def _human_message(seq: int) -> ChatMessage:
    mid = "message_" + _UUID.format(0x100 + seq)
    return ChatMessage(
        message_id=mid,
        interaction_id=_INTERACTION,
        channel_key="lobby",
        author_actor_id=_HUMAN,
        sequence=seq,
        content_digest=compute_digest({"said": seq}),
        visibility="public",
        idempotency_key="idem_" + f"{seq:021d}" + "A",
        submitted_at="2026-07-22T00:00:00.000000Z",
    )


def _turn(tag: int) -> ChatTurn:
    return ChatTurn(
        reply_message_id="message_" + _UUID.format(0x700 + tag),
        snapshot_id="message_" + _UUID.format(0x800 + tag),
        modelcall_id="modelcall_" + _UUID.format(0x900 + tag),
        idempotency_key="idem_" + f"{tag:021d}" + "Q",
    )


def _chat_agent(
    store: InMemoryStore, adapter: _CountingProvider, policy: TurnPolicy
) -> ChatAgent:
    return ChatAgent(
        agent_version=_agent_version(),
        provider=_provider(store, adapter),
        channel=_channel(store),
        policy=policy,
        agent_actor_id=_AGENT,
        compose=lambda recent: {"turns": [m.message_id for m in recent]},
        resolve_secret=lambda _: "sk-secret",
    )


async def test_an_admitted_turn_posts_the_model_reply_by_its_digest() -> None:
    """A free turn posts a reply whose content digest is the model output digest."""
    store, factory = InMemoryStore(), _Factory()
    adapter = _CountingProvider()
    policy = TurnPolicy(
        channel_key="lobby", activation="free", max_model_activations_per_turn=3
    )
    agent = _chat_agent(store, adapter, policy)
    recent = [_human_message(1)]

    reply = await agent.take_turn(turn=_turn(1), recent=recent, new_context=factory)

    assert reply is not None
    assert reply.author_actor_id == _AGENT
    assert reply.content_digest == compute_digest({"text": "a reply"})
    assert adapter.calls == 1
    # The posted message and its snapshot are both recorded.
    assert store.load_aggregate(reply.message_id) is not None
    snap = store.load_aggregate("message_" + _UUID.format(0x801))
    assert snap is not None
    assert snap["included_message_ids"] == [recent[0].message_id]


async def test_a_refused_turn_stays_silent_and_never_calls_the_model() -> None:
    """A mention turn with no mention posts nothing and makes no model call."""
    store, factory = InMemoryStore(), _Factory()
    adapter = _CountingProvider()
    policy = TurnPolicy(
        channel_key="lobby", activation="mention", max_model_activations_per_turn=1
    )
    agent = _chat_agent(store, adapter, policy)

    reply = await agent.take_turn(
        turn=_turn(1),
        recent=[_human_message(1)],
        new_context=factory,
        mentioned=False,
    )

    assert reply is None
    assert adapter.calls == 0


async def test_the_activation_cap_silences_a_second_free_turn() -> None:
    """With a cap of one, the first free turn speaks and the second stays silent."""
    store, factory = InMemoryStore(), _Factory()
    adapter = _CountingProvider()
    policy = TurnPolicy(
        channel_key="lobby", activation="free", max_model_activations_per_turn=1
    )
    agent = _chat_agent(store, adapter, policy)

    first = await agent.take_turn(
        turn=_turn(1), recent=[_human_message(1)], new_context=factory
    )
    second = await agent.take_turn(
        turn=_turn(2), recent=[_human_message(2)], new_context=factory
    )

    assert first is not None
    assert second is None
    assert adapter.calls == 1
