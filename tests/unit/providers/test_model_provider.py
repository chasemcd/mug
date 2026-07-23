"""The model-provider runtime runs one call through an adapter and records it.

These tests drive ``mug.providers.runtime.ModelProvider`` against the in-memory
store with a fixed clock, a deterministic ``FakeProvider``, and hand-built command
contexts. They prove the runtime properties: a completed call records a response
with its output by digest, the resolved secret reaches the adapter but never a
record, a refusal and an error record their own terminal state, a retry replays the
recorded outcome without a second model call, and an agent version that names no
secret is refused.
"""

from __future__ import annotations

import itertools
import json
from datetime import datetime, timezone

from mug.kernel import Digest, compute_digest
from mug.providers import (
    AgentVersion,
    FakeProvider,
    InMemoryOutputTape,
    ModelCall,
    ModelCompletion,
    ModelProvider,
    Usage,
)
from mug.runtime import CommandContext
from mug.storage import InMemoryStore

_UUID = "019b6000-0000-7000-8000-{:012x}"
_START = datetime(2026, 7, 22, 0, 0, 0, tzinfo=timezone.utc)
_DIGEST = Digest(algorithm="sha-256", hex="a" * 64)
_SECRET = "sk-live-do-not-record-0123456789"


def _agent(*, secret_name: str | None = "chat-provider-key") -> AgentVersion:
    return AgentVersion(
        agent_version_id="agentver_" + _UUID.format(0x430),
        agent_definition_id="agentdef_" + _UUID.format(0x431),
        agent_key="llm-partner",
        version_number=2,
        provider="anthropic",
        model_selector="claude-sonnet-4-5",
        prompt_version_id="promptver_" + _UUID.format(0x440),
        parameters_digest=_DIGEST,
        tool_version_ids=[],
        fallback_policy_key="chat-fallback",
        secret_name=secret_name,
    )


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


def _provider(store: InMemoryStore, adapter: object) -> ModelProvider:
    gens = itertools.count(1)
    return ModelProvider(
        store=store,
        adapter=adapter,  # type: ignore[arg-type]
        now=lambda: _START,
        new_generation_id=lambda: "generation_" + _UUID.format(next(gens)),
    )


def _modelcall_id(seed: str) -> str:
    return "modelcall_" + _UUID.format(int(compute_digest(seed).hex[:8], 16) & 0xFFFF)


async def test_a_completed_call_records_a_response_with_its_output() -> None:
    """A completed call records a response, and returns the raw output by digest."""
    store, factory = InMemoryStore(), _Factory()
    provider = _provider(store, FakeProvider(lambda payload: {"reply": payload["ask"]}))
    modelcall_id = _modelcall_id("greeting")

    result = await provider.invoke(
        modelcall_id=modelcall_id,
        agent_version=_agent(),
        payload={"ask": "hello"},
        new_context=factory,
        resolve_secret=lambda _: _SECRET,
    )

    assert result.response is not None
    assert result.response.outcome == "completed"
    assert result.output == {"reply": "hello"}
    assert result.response.output_digest == compute_digest({"reply": "hello"})
    head = store.load_aggregate(modelcall_id)
    assert head is not None
    assert head["schema"]["name"] == "mug.api-13.provider-response"


async def test_the_resolved_secret_reaches_the_adapter_but_never_a_record() -> None:
    """The adapter receives the resolved secret; no record carries its value."""
    store, factory = InMemoryStore(), _Factory()
    seen: list[ModelCall] = []

    async def adapter(call: ModelCall) -> ModelCompletion:
        seen.append(call)
        return ModelCompletion(
            outcome="completed",
            resolved_model="vendor-mini",
            usage=Usage(input_tokens=3, output_tokens=1, cost_micros=10),
            output={"ok": True},
        )

    provider = _provider(store, adapter)
    modelcall_id = _modelcall_id("secretcheck")
    result = await provider.invoke(
        modelcall_id=modelcall_id,
        agent_version=_agent(),
        payload={"ask": "hi"},
        new_context=factory,
        resolve_secret=lambda name: _SECRET if name == "chat-provider-key" else "",
    )

    # The secret reached the adapter, proving resolution by name.
    assert seen[0].secret == _SECRET
    # The secret value appears in no record: the head, nor the request it carries.
    head = store.load_aggregate(modelcall_id)
    assert result.request is not None
    assert result.request.secret_name == "chat-provider-key"
    recorded = json.dumps(head) + json.dumps(result.request.model_dump(mode="json"))
    assert _SECRET not in recorded


async def test_a_refusal_records_a_response_with_no_output() -> None:
    """A refused call records a response whose outcome is refused and has no output."""
    store, factory = InMemoryStore(), _Factory()

    async def adapter(_: ModelCall) -> ModelCompletion:
        return ModelCompletion(
            outcome="refused",
            resolved_model="vendor-mini",
            usage=Usage(input_tokens=3, output_tokens=0, cost_micros=5),
        )

    provider = _provider(store, adapter)
    result = await provider.invoke(
        modelcall_id=_modelcall_id("refusal"),
        agent_version=_agent(),
        payload={"ask": "no"},
        new_context=factory,
        resolve_secret=lambda _: _SECRET,
    )

    assert result.response is not None
    assert result.response.outcome == "refused"
    assert result.response.output_digest is None
    assert result.output is None


async def test_an_error_records_a_classified_provider_error() -> None:
    """An errored call records a provider error, classified and marked retryable."""
    store, factory = InMemoryStore(), _Factory()

    async def adapter(_: ModelCall) -> ModelCompletion:
        return ModelCompletion(
            outcome="error",
            resolved_model="vendor-mini",
            usage=Usage(input_tokens=0, output_tokens=0, cost_micros=0),
            error_class="rate-limit",
            retryable=True,
        )

    provider = _provider(store, adapter)
    modelcall_id = _modelcall_id("error")
    result = await provider.invoke(
        modelcall_id=modelcall_id,
        agent_version=_agent(),
        payload={"ask": "again"},
        new_context=factory,
        resolve_secret=lambda _: _SECRET,
    )

    assert result.error is not None
    assert result.error.error_class == "rate-limit"
    assert result.error.retryable is True
    head = store.load_aggregate(modelcall_id)
    assert head is not None
    assert head["schema"]["name"] == "mug.api-13.provider-error"


async def test_a_retry_replays_the_recorded_outcome_without_a_second_call() -> None:
    """A second invoke of the same call id replays and does not call the model."""
    store, factory = InMemoryStore(), _Factory()
    calls = itertools.count(1)

    def respond(payload: object) -> dict[str, int]:
        return {"n": next(calls)}

    provider = _provider(store, FakeProvider(respond))
    modelcall_id = _modelcall_id("idem")

    first = await provider.invoke(
        modelcall_id=modelcall_id,
        agent_version=_agent(),
        payload={"ask": "once"},
        new_context=factory,
        resolve_secret=lambda _: _SECRET,
    )
    second = await provider.invoke(
        modelcall_id=modelcall_id,
        agent_version=_agent(),
        payload={"ask": "once"},
        new_context=factory,
        resolve_secret=lambda _: _SECRET,
    )

    assert first.replayed is False
    assert second.replayed is True
    assert second.response is not None
    assert first.response is not None
    assert second.response.output_digest == first.response.output_digest
    # The model ran exactly once: the replay did not call the adapter again.
    assert next(calls) == 2


async def test_the_output_tape_rehydrates_the_verbatim_output_on_replay() -> None:
    """With an output tape, a replayed call returns the exact recorded output.

    Without a tape a replay returns the outcome by digest only (``output=None``);
    with one, the provider persists the completed output content-addressed by its
    digest and reads it back on the replay, so the caller re-derives the reply
    exactly. The model still runs exactly once.
    """
    store, factory = InMemoryStore(), _Factory()
    calls = itertools.count(1)
    tape = InMemoryOutputTape()

    def respond(_payload: object) -> dict[str, object]:
        return {"reply": "carry this thought", "n": next(calls)}

    provider = ModelProvider(
        store=store,
        adapter=FakeProvider(respond),
        now=lambda: _START,
        new_generation_id=lambda: "generation_" + _UUID.format(1),
        output_tape=tape,
    )
    modelcall_id = _modelcall_id("tape")

    first = await provider.invoke(
        modelcall_id=modelcall_id,
        agent_version=_agent(),
        payload={"ask": "once"},
        new_context=factory,
        resolve_secret=lambda _: _SECRET,
    )
    second = await provider.invoke(
        modelcall_id=modelcall_id,
        agent_version=_agent(),
        payload={"ask": "once"},
        new_context=factory,
        resolve_secret=lambda _: _SECRET,
    )

    assert first.replayed is False
    assert second.replayed is True
    # The replay rehydrated the exact recorded output, not None.
    assert second.output == first.output
    assert second.output == {"reply": "carry this thought", "n": 1}
    # The model still ran exactly once; the replay read the tape, not the adapter.
    assert next(calls) == 2


async def test_a_replay_without_a_tape_still_returns_no_output() -> None:
    """The default provider persists nothing, so a replay yields no output."""
    store, factory = InMemoryStore(), _Factory()
    provider = _provider(store, FakeProvider(lambda _: {"reply": "hi"}))
    modelcall_id = _modelcall_id("notape")

    await provider.invoke(
        modelcall_id=modelcall_id,
        agent_version=_agent(),
        payload={"ask": "once"},
        new_context=factory,
        resolve_secret=lambda _: _SECRET,
    )
    replayed = await provider.invoke(
        modelcall_id=modelcall_id,
        agent_version=_agent(),
        payload={"ask": "once"},
        new_context=factory,
        resolve_secret=lambda _: _SECRET,
    )

    assert replayed.replayed is True
    assert replayed.output is None


async def test_an_agent_that_names_no_secret_is_refused() -> None:
    """A provider request names a secret; an agent with none is refused."""
    store, factory = InMemoryStore(), _Factory()
    provider = _provider(store, FakeProvider(lambda _: {"ok": True}))

    try:
        await provider.invoke(
            modelcall_id=_modelcall_id("nosecret"),
            agent_version=_agent(secret_name=None),
            payload={"ask": "hi"},
            new_context=factory,
        )
    except ValueError:
        return
    raise AssertionError("expected a ValueError for an agent that names no secret")
