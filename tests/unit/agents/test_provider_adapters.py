"""The real provider adapters reach Ollama, Anthropic, and OpenAI over HTTP.

These tests drive ``mug.agents.adapters`` through an injected fake transport, so the
whole request-and-reply path runs with no network. They prove each adapter builds
its provider's request (endpoint, auth header, body), reads a 2xx reply into a
completed ``ModelCompletion`` with usage, and maps every fault -- a non-2xx status, a
transport failure, a content filter, a reply it cannot read -- to an error or refused
completion rather than an exception. One test drives the Ollama adapter through the
built ``ModelProvider`` to prove the real adapter satisfies the injected seam.

A final test reaches a *live* local Ollama runner when one is up, so the adapter is
proven against a real model as well as the fake transport. It skips when no runner
answers, so the suite never depends on a network.
"""

from __future__ import annotations

import itertools
import socket
from typing import Any

import pytest

from mug.agents.adapters import (
    AnthropicAdapter,
    HttpRequest,
    HttpResponse,
    OllamaAdapter,
    OpenAIAdapter,
    TransportFailure,
    adapter_for,
    httpx_transport,
)
from mug.kernel import Digest
from mug.providers import (
    AgentVersion,
    ModelCall,
    ModelProvider,
)
from mug.runtime import CommandContext
from mug.storage import InMemoryStore

_UUID = "019b6000-0000-7000-8000-{:012x}"
_DIGEST = Digest(algorithm="sha-256", hex="a" * 64)

_OLLAMA_REPLY = {
    "model": "gemma:2b",
    "message": {"role": "assistant", "content": "Action: RIGHT"},
    "prompt_eval_count": 12,
    "eval_count": 5,
}
_ANTHROPIC_REPLY = {
    "model": "claude-sonnet-4-5",
    "content": [{"type": "text", "text": "Action: RIGHT"}],
    "usage": {"input_tokens": 12, "output_tokens": 5},
    "stop_reason": "end_turn",
}
_OPENAI_REPLY = {
    "model": "gpt-4o",
    "choices": [
        {
            "message": {"role": "assistant", "content": "Action: RIGHT"},
            "finish_reason": "stop",
        }
    ],
    "usage": {"prompt_tokens": 12, "completion_tokens": 5},
}


class _Transport:
    """A fake transport: record each request, return a scripted reply (or fail)."""

    def __init__(
        self,
        *,
        status: int = 200,
        body: Any = None,
        fail: TransportFailure | None = None,
    ) -> None:
        self._status = status
        self._body = body
        self._fail = fail
        self.requests: list[HttpRequest] = []

    async def __call__(self, request: HttpRequest) -> HttpResponse:
        self.requests.append(request)
        if self._fail is not None:
            raise self._fail
        return HttpResponse(status=self._status, body=self._body)


def _call(*, model: str = "a-model", secret: str | None = None) -> ModelCall:
    return ModelCall(
        model_selector=model,
        payload={"messages": [{"role": "user", "content": "your move?"}]},
        secret=secret,
    )


# -- Ollama -------------------------------------------------------------------


async def test_ollama_builds_a_request_and_reads_the_reply() -> None:
    """The Ollama adapter posts to /api/chat with no auth and reads the content."""
    transport = _Transport(body=_OLLAMA_REPLY)
    adapter = OllamaAdapter(base_url="http://localhost:11434", transport=transport)

    completion = await adapter(_call(model="gemma:2b"))

    request = transport.requests[0]
    assert request.url == "http://localhost:11434/api/chat"
    assert "authorization" not in request.headers
    assert "x-api-key" not in request.headers
    assert request.json["model"] == "gemma:2b"
    assert request.json["stream"] is False
    assert request.json["messages"][0]["content"] == "your move?"
    assert completion.outcome == "completed"
    assert completion.resolved_model == "gemma:2b"
    assert completion.output == {"text": "Action: RIGHT"}
    assert completion.usage.input_tokens == 12
    assert completion.usage.output_tokens == 5


async def test_ollama_carries_a_temperature_into_the_options() -> None:
    """A construction temperature reaches Ollama under the options key."""
    transport = _Transport(body=_OLLAMA_REPLY)
    adapter = OllamaAdapter(
        base_url="http://localhost:11434", transport=transport, temperature=0.2
    )

    await adapter(_call())

    assert transport.requests[0].json["options"]["temperature"] == 0.2


async def test_the_payload_temperature_overrides_the_adapter_default() -> None:
    """A temperature in the call payload wins over the adapter's own default."""
    transport = _Transport(body=_OLLAMA_REPLY)
    adapter = OllamaAdapter(
        base_url="http://localhost:11434", transport=transport, temperature=0.2
    )
    call = ModelCall(
        model_selector="gemma:2b",
        payload={"messages": [{"role": "user", "content": "hi"}], "temperature": 0.9},
        secret=None,
    )

    await adapter(call)

    assert transport.requests[0].json["options"]["temperature"] == 0.9


async def test_ollama_is_told_how_much_to_generate_and_how_long_to_stay_loaded() -> (
    None
):
    """The declared bound reaches the runner, and the model is kept in memory.

    ``max_tokens`` was declared on every adapter and read by exactly one of them, so
    a study that bounded its replies was not bounded on a local runner at all: with
    no ``num_predict`` Ollama generates until the model stops, and a model that
    answers a three-line question with an essay costs the wait for every token of
    it. On a machine with no GPU that is seconds a call.

    ``keep_alive`` is the other half. The runner unloads after five minutes by
    default, which is less time than a participant spends on the consent form and
    the instructions -- so the first call of the first round paid to load the model
    again, in front of somebody who was by then looking at the game.
    """
    transport = _Transport(body=_OLLAMA_REPLY)
    adapter = OllamaAdapter(
        base_url="http://localhost:11434", transport=transport, max_tokens=64
    )

    await adapter(_call())

    sent = transport.requests[0].json
    assert sent["options"]["num_predict"] == 64, (
        "the runner was given no generation bound, so a rambling reply is waited "
        "for in full"
    )
    assert sent["keep_alive"], "the model is left to be unloaded between rounds"


# -- Anthropic ----------------------------------------------------------------


async def test_anthropic_sends_the_key_header_and_reads_the_content() -> None:
    """The Anthropic adapter posts to /v1/messages with the x-api-key header."""
    transport = _Transport(body=_ANTHROPIC_REPLY)
    adapter = AnthropicAdapter(
        base_url="https://api.anthropic.com", transport=transport, max_tokens=256
    )

    completion = await adapter(_call(model="claude-sonnet-4-5", secret="sk-ant"))

    request = transport.requests[0]
    assert request.url == "https://api.anthropic.com/v1/messages"
    assert request.headers["x-api-key"] == "sk-ant"
    assert request.headers["anthropic-version"]
    assert request.json["max_tokens"] == 256
    assert completion.outcome == "completed"
    assert completion.output == {"text": "Action: RIGHT"}
    assert completion.resolved_model == "claude-sonnet-4-5"
    assert completion.usage.output_tokens == 5


async def test_anthropic_refusal_reads_as_refused() -> None:
    """A refusal stop reason becomes a refused completion with no output."""
    body = {**_ANTHROPIC_REPLY, "stop_reason": "refusal", "content": []}
    adapter = AnthropicAdapter(
        base_url="https://api.anthropic.com", transport=_Transport(body=body)
    )

    completion = await adapter(_call(secret="sk-ant"))

    assert completion.outcome == "refused"
    assert completion.output is None


# -- OpenAI -------------------------------------------------------------------


async def test_openai_sends_a_bearer_token_and_reads_the_choice() -> None:
    """The OpenAI adapter posts to /v1/chat/completions with a bearer token."""
    transport = _Transport(body=_OPENAI_REPLY)
    adapter = OpenAIAdapter(base_url="https://api.openai.com", transport=transport)

    completion = await adapter(_call(model="gpt-4o", secret="sk-oai"))

    request = transport.requests[0]
    assert request.url == "https://api.openai.com/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer sk-oai"
    assert completion.outcome == "completed"
    assert completion.output == {"text": "Action: RIGHT"}
    assert completion.resolved_model == "gpt-4o"
    assert completion.usage.input_tokens == 12


async def test_openai_content_filter_reads_as_refused() -> None:
    """A content-filter finish reason becomes a refused completion."""
    body = {
        "model": "gpt-4o",
        "choices": [{"message": {"content": None}, "finish_reason": "content_filter"}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 0},
    }
    adapter = OpenAIAdapter(
        base_url="https://api.openai.com", transport=_Transport(body=body)
    )

    completion = await adapter(_call(secret="sk-oai"))

    assert completion.outcome == "refused"


# -- fault mapping (shared) ---------------------------------------------------


@pytest.mark.parametrize(
    ("status", "error_class", "retryable"),
    [
        (429, "rate-limit", True),
        (503, "provider-error", True),
        (400, "provider-error", False),
        (401, "provider-error", False),
    ],
)
async def test_a_non_2xx_status_maps_to_an_error(
    status: int, error_class: str, retryable: bool
) -> None:
    """A non-2xx status becomes an error completion, marked retryable or not."""
    adapter = OpenAIAdapter(
        base_url="https://api.openai.com",
        transport=_Transport(status=status, body={"error": "no"}),
    )

    completion = await adapter(_call(secret="sk-oai"))

    assert completion.outcome == "error"
    assert completion.error_class == error_class
    assert completion.retryable is retryable
    assert completion.output is None


async def test_a_transport_timeout_maps_to_a_retryable_timeout() -> None:
    """A transport timeout becomes a retryable timeout error, not an exception."""
    transport = _Transport(fail=TransportFailure("timeout", "too slow"))
    adapter = OllamaAdapter(base_url="http://localhost:11434", transport=transport)

    completion = await adapter(_call())

    assert completion.outcome == "error"
    assert completion.error_class == "timeout"
    assert completion.retryable is True


async def test_a_network_failure_maps_to_a_retryable_provider_error() -> None:
    """A network failure becomes a retryable provider error."""
    transport = _Transport(fail=TransportFailure("network", "no route"))
    adapter = OllamaAdapter(base_url="http://localhost:11434", transport=transport)

    completion = await adapter(_call())

    assert completion.outcome == "error"
    assert completion.error_class == "provider-error"
    assert completion.retryable is True


async def test_a_malformed_reply_maps_to_an_error_not_a_crash() -> None:
    """A 2xx reply with no readable content becomes an error, never an exception."""
    adapter = OllamaAdapter(
        base_url="http://localhost:11434", transport=_Transport(body={"nonsense": 1})
    )

    completion = await adapter(_call())

    assert completion.outcome == "error"
    assert completion.error_class == "provider-error"


# -- the words of a message reach the provider --------------------------------
#
# All three providers name the words of a message ``content``. A caller that names
# them anything else sends a message the provider reads as empty, and each provider
# fails differently and quietly: Ollama answers the empty question it was asked, and
# Anthropic refuses the request, which the adapter maps to silence. Neither reaches
# the participant as a fault, so the study looks broken with nothing in the logs.
#
# The chat mount really did this. It composed every message as ``text``, and every
# test of it used a double that read ``text`` back, so the whole suite passed while
# no conversation on any provider could work. These tests are at the one boundary
# that faces the provider, and they read only what a provider reads.


@pytest.mark.parametrize(
    "adapter",
    [
        OllamaAdapter(base_url="http://x", transport=None),
        AnthropicAdapter(base_url="http://x", transport=None),
        OpenAIAdapter(base_url="http://x", transport=None),
    ],
    ids=["ollama", "anthropic", "openai"],
)
async def test_every_message_reaches_the_provider_with_its_words(
    adapter: Any,
) -> None:
    """No adapter may send a message with nothing in the field a provider reads."""
    transport = _Transport(status=500, body={})
    adapter._transport = transport
    call = ModelCall(
        model_selector="a-model",
        payload={
            "messages": [
                {"role": "user", "content": "what I said"},
                {"role": "assistant", "content": "what it said"},
            ]
        },
        secret=None,
    )

    await adapter(call)

    sent = transport.requests[0].json["messages"]
    assert [one["content"] for one in sent] == ["what I said", "what it said"]


async def test_a_message_that_names_its_words_text_still_carries_them() -> None:
    """A composer that writes ``text`` is repaired rather than sent empty.

    ``ChatSpec.compose`` is an author seam, and the shape the platform itself wrote
    for a year was ``text``. A study that copied it must not be answered by a model
    that was told nothing, so the words are put where the provider looks for them.
    """
    transport = _Transport(body=_OLLAMA_REPLY)
    adapter = OllamaAdapter(base_url="http://localhost:11434", transport=transport)

    await adapter(
        ModelCall(
            model_selector="a-model",
            payload={"messages": [{"role": "user", "text": "what I said"}]},
            secret=None,
        )
    )

    assert transport.requests[0].json["messages"] == [
        {"role": "user", "content": "what I said"}
    ]


async def test_a_message_whose_content_is_a_block_list_is_passed_through() -> None:
    """An Anthropic content array is content already, and is not flattened."""
    transport = _Transport(body=_ANTHROPIC_REPLY)
    adapter = AnthropicAdapter(
        base_url="https://api.anthropic.com", transport=transport
    )
    blocks = [{"type": "text", "text": "look at this"}]

    await adapter(
        ModelCall(
            model_selector="a-model",
            payload={"messages": [{"role": "user", "content": blocks}]},
            secret="k",
        )
    )

    assert transport.requests[0].json["messages"][0]["content"] == blocks


# -- the registry -------------------------------------------------------------


def test_adapter_for_picks_the_adapter_by_provider_name() -> None:
    """The registry maps a provider name to its built adapter and defaults its host."""
    assert isinstance(adapter_for("oss"), OllamaAdapter)
    assert isinstance(adapter_for("anthropic"), AnthropicAdapter)
    assert isinstance(adapter_for("openai"), OpenAIAdapter)


def test_adapter_for_rejects_an_unknown_provider() -> None:
    """An unknown provider name is refused with a clear message."""
    with pytest.raises(ValueError, match="no built adapter"):
        adapter_for("mystery")


# -- through the provider runtime ---------------------------------------------


def _context(aggregate_id: str, n: int) -> CommandContext:
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


def _agent_version() -> AgentVersion:
    return AgentVersion(
        agent_version_id="agentver_" + _UUID.format(0x430),
        agent_definition_id="agentdef_" + _UUID.format(0x431),
        agent_key="grid-runner",
        version_number=1,
        provider="oss",
        model_selector="gemma:2b",
        prompt_version_id="promptver_" + _UUID.format(0x440),
        parameters_digest=_DIGEST,
        tool_version_ids=[],
        fallback_policy_key="grid-fallback",
        secret_name="chat-provider-key",
    )


async def test_the_ollama_adapter_runs_through_the_provider_runtime() -> None:
    """A real adapter satisfies the injected seam: a call records a response."""
    from datetime import datetime, timezone

    store = InMemoryStore()
    counter = itertools.count(1)
    provider = ModelProvider(
        store=store,
        adapter=OllamaAdapter(
            base_url="http://localhost:11434",
            transport=_Transport(body=_OLLAMA_REPLY),
        ),
        now=lambda: datetime(2026, 7, 22, tzinfo=timezone.utc),
        new_generation_id=lambda: "generation_" + _UUID.format(next(counter)),
    )

    result = await provider.invoke(
        modelcall_id="modelcall_" + _UUID.format(0xC01),
        agent_version=_agent_version(),
        payload={"messages": [{"role": "user", "content": "your move?"}]},
        new_context=lambda agg: _context(agg, next(counter)),
        resolve_secret=lambda _: "sk-unused-by-ollama",
    )

    assert result.response is not None
    assert result.response.outcome == "completed"
    assert result.output == {"text": "Action: RIGHT"}


# -- live Ollama (skipped when no runner answers) -----------------------------


def _ollama_is_up(host: str = "localhost", port: int = 11434) -> bool:
    """Return whether a local Ollama runner accepts a connection."""
    try:
        with socket.create_connection((host, port), timeout=0.25):
            return True
    except OSError:
        return False


@pytest.mark.skipif(not _ollama_is_up(), reason="no local Ollama runner")
async def test_a_live_ollama_runner_answers() -> None:
    """When a local Ollama runner is up, the adapter reaches a real model.

    This proves the default httpx transport against a real endpoint. It reads the
    installed models and asks one for a single word, so it stays fast and needs no
    fixed model name. It skips when no runner is up, so the suite never depends on
    a network.
    """
    import httpx

    async with httpx.AsyncClient(timeout=5.0) as client:
        tags = await client.get("http://localhost:11434/api/tags")
    models = [m["name"] for m in tags.json().get("models", [])]
    if not models:
        pytest.skip("Ollama is up but has no installed model")

    adapter = OllamaAdapter(
        base_url="http://localhost:11434", transport=httpx_transport(timeout=120.0)
    )
    call = ModelCall(
        model_selector=models[0],
        payload={"messages": [{"role": "user", "content": "Reply with the word OK."}]},
        secret=None,
    )

    completion = await adapter(call)

    assert completion.outcome == "completed"
    assert isinstance(completion.output, dict)
    assert isinstance(completion.output["text"], str)
    assert completion.output["text"]
