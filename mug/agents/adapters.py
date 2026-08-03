"""Real provider adapters: reach Ollama, Anthropic, and OpenAI over HTTP.

The provider runtime (``mug.providers``) drives one model call through an injected
``ProviderAdapter`` and imports no vendor SDK. This module ships the adapters that
seam expects, so a study does not write one. Each adapter speaks the provider's own
chat-completion HTTP API with plain ``httpx`` -- no vendor SDK -- and maps the reply
to a ``ModelCompletion`` the runtime records.

Three providers are built:

- ``OllamaAdapter`` -- a local model runner (``http://localhost:11434``). It needs
  no credential, so a study runs a model for free on its own machine.
- ``AnthropicAdapter`` -- the Anthropic Messages API. It sends the credential as the
  ``x-api-key`` header.
- ``OpenAIAdapter`` -- the OpenAI Chat Completions API. It sends the credential as a
  bearer token.

The adapters share one HTTP seam. The transport is injected: the default sends the
request with ``httpx``, and a test injects a fake transport that returns a canned
reply, so the whole path runs with no network. ``httpx`` is imported only inside the
default transport, so ``import mug.agents`` needs no HTTP library.

The adapter never raises for a provider fault. A non-2xx status, a timeout, or a
reply it cannot read becomes a ``ModelCompletion`` with ``outcome="error"`` (or
``"refused"`` for a content filter), which the runtime records and the scheduler
turns into the seat fallback. So a provider outage degrades to the fallback action,
never to an unhandled exception.

The credential reaches the adapter as ``ModelCall.secret`` and goes only into the
request header for the single call. It is never returned, logged, or recorded, in
keeping with the secret discipline the provider runtime holds.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, ClassVar, Literal, cast

from mug.providers import ModelCall, ModelCompletion, Usage

# The chat messages the controller renders; the adapter forwards them unchanged.
Messages = list[dict[str, Any]]

_JSON_HEADERS = {"content-type": "application/json"}
_ANTHROPIC_VERSION = "2023-06-01"


# -- the HTTP seam ------------------------------------------------------------


@dataclass(frozen=True)
class HttpRequest:
    """One HTTP POST an adapter makes: where to send, the headers, the JSON body."""

    url: str
    headers: dict[str, str]
    json: dict[str, Any]


@dataclass(frozen=True)
class HttpResponse:
    """One HTTP reply: the status code and the parsed JSON body (or raw text)."""

    status: int
    body: Any


class TransportFailure(Exception):
    """The request never produced a reply: it timed out or the network failed.

    ``kind`` is ``"timeout"`` when the request exceeded its deadline and
    ``"network"`` for any other connection fault. The adapter turns both into an
    error completion, so the caller never sees this exception.
    """

    def __init__(self, kind: Literal["timeout", "network"], message: str) -> None:
        super().__init__(message)
        self.kind = kind


# A transport sends one request and returns its reply. It raises ``TransportFailure``
# for a timeout or a network fault; a non-2xx status is returned, not raised.
HttpTransport = Callable[[HttpRequest], Awaitable[HttpResponse]]


def httpx_transport(*, timeout: float = 30.0) -> HttpTransport:
    """Return the default transport, which sends the request with ``httpx``.

    ``httpx`` is imported here, not at module load, so importing this module needs
    no HTTP library. Each call opens a short-lived async client; a timeout or a
    connection fault becomes a ``TransportFailure`` the adapter maps to an error.
    """

    async def send(request: HttpRequest) -> HttpResponse:
        import httpx

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                reply = await client.post(
                    request.url, headers=request.headers, json=request.json
                )
        except httpx.TimeoutException as failure:
            raise TransportFailure("timeout", str(failure)) from failure
        except httpx.HTTPError as failure:
            raise TransportFailure("network", str(failure)) from failure
        return HttpResponse(status=reply.status_code, body=_read_body(reply))

    return send


def _read_body(reply: Any) -> Any:
    """Return the reply body as parsed JSON, or the raw text if it is not JSON."""
    try:
        return reply.json()
    except ValueError:
        return reply.text


# -- the adapters -------------------------------------------------------------


class ChatAdapter:
    """The shared flow for a chat-completion HTTP adapter.

    A subclass builds the request for its provider (``_request``) and reads a 2xx
    reply into a completion (``_complete``). This base runs the transport and maps
    every fault -- a transport failure, a non-2xx status -- to an error completion,
    so the subclass handles only the success shape.
    """

    provider_name: ClassVar[str]

    def __init__(
        self,
        *,
        base_url: str,
        transport: HttpTransport | None = None,
        timeout: float = 30.0,
        temperature: float | None = None,
        max_tokens: int = 1024,
        keep_alive: str = "1h",
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._transport = transport or httpx_transport(timeout=timeout)
        self._default_temperature = temperature
        self._max_tokens = max_tokens
        self._keep_alive = keep_alive

    async def __call__(self, call: ModelCall) -> ModelCompletion:
        """Run one model call: build the request, send it, and read the reply."""
        request = self._request(call)
        try:
            reply = await self._transport(request)
        except TransportFailure as failure:
            return self._transport_error(call, failure)
        if reply.status // 100 != 2:
            return self._status_error(call, reply)
        return self._complete(call, reply)

    # -- subclass hooks --

    def _request(self, call: ModelCall) -> HttpRequest:
        """Build the provider's request for one model call (a subclass overrides)."""
        raise NotImplementedError

    def _complete(self, call: ModelCall, reply: HttpResponse) -> ModelCompletion:
        """Read a 2xx reply into a completion (a subclass overrides)."""
        raise NotImplementedError

    # -- shared error mapping --

    def _status_error(self, call: ModelCall, reply: HttpResponse) -> ModelCompletion:
        """Map a non-2xx status to an error completion, marked retryable or not.

        A 429 is a rate limit and a 5xx is a provider fault; both may succeed on a
        retry. Any other status (a bad request, a bad key) is a provider error that a
        retry will not fix.
        """
        if reply.status == 429:
            return _error(call, "rate-limit", retryable=True)
        if reply.status >= 500:
            return _error(call, "provider-error", retryable=True)
        return _error(call, "provider-error", retryable=False)

    def _transport_error(
        self, call: ModelCall, failure: TransportFailure
    ) -> ModelCompletion:
        """Map a transport failure to a retryable error completion."""
        error_class: Literal["timeout", "provider-error"] = (
            "timeout" if failure.kind == "timeout" else "provider-error"
        )
        return _error(call, error_class, retryable=True)

    # -- shared request helpers --

    def _temperature(self, call: ModelCall) -> float | None:
        """Return the call's temperature: the payload overrides the adapter default."""
        payload = call.payload
        if isinstance(payload, dict):
            value = cast("dict[str, Any]", payload).get("temperature")
            if isinstance(value, (int, float)):
                return float(value)
        return self._default_temperature


class OllamaAdapter(ChatAdapter):
    """Reach a local Ollama model runner. It needs no credential.

    Ollama runs a model on the study's own machine, so a researcher runs an LLM
    player for free with no key. The adapter posts to ``/api/chat`` and reads the
    single (non-streamed) reply.
    """

    provider_name: ClassVar[str] = "oss"

    def _request(self, call: ModelCall) -> HttpRequest:
        # ``num_predict`` is Ollama's name for the generation bound, and without it
        # the runner generates until the model decides to stop. A study asks for
        # three lines; a model that answers with an essay instead costs the wait for
        # every token of it, and on a machine with no GPU that is seconds a call
        # nobody asked for. The bound was **declared** and dropped here before, so a
        # study that set ``max_tokens`` was not bounded at all.
        options: dict[str, Any] = {"num_predict": self._max_tokens}
        temperature = self._temperature(call)
        if temperature is not None:
            options["temperature"] = temperature
        body: dict[str, Any] = {
            "model": call.model_selector,
            "messages": _messages(call),
            "stream": False,
            "options": options,
            # How long the runner holds the model in memory after a call. The
            # default is five minutes, which is shorter than a participant spends
            # on the consent form and the instructions -- so the first call of the
            # first round pays to load the model again, in front of somebody who is
            # now looking at the game.
            "keep_alive": self._keep_alive,
        }
        return HttpRequest(
            url=f"{self._base_url}/api/chat", headers=dict(_JSON_HEADERS), json=body
        )

    def _complete(self, call: ModelCall, reply: HttpResponse) -> ModelCompletion:
        body = _as_dict(reply.body)
        message = _as_dict(body.get("message"))
        text = message.get("content")
        if not isinstance(text, str):
            return _error(call, "provider-error", retryable=False)
        usage = Usage(
            input_tokens=_as_int(body.get("prompt_eval_count")),
            output_tokens=_as_int(body.get("eval_count")),
            cost_micros=0,
        )
        return ModelCompletion(
            outcome="completed",
            resolved_model=_model(body.get("model"), call),
            usage=usage,
            output={"text": text},
        )


class AnthropicAdapter(ChatAdapter):
    """Reach the Anthropic Messages API with the ``x-api-key`` credential."""

    provider_name: ClassVar[str] = "anthropic"

    def _request(self, call: ModelCall) -> HttpRequest:
        headers = dict(_JSON_HEADERS)
        headers["anthropic-version"] = _ANTHROPIC_VERSION
        if call.secret is not None:
            headers["x-api-key"] = call.secret
        body: dict[str, Any] = {
            "model": call.model_selector,
            "max_tokens": self._max_tokens,
            "messages": _messages(call),
        }
        temperature = self._temperature(call)
        if temperature is not None:
            body["temperature"] = temperature
        return HttpRequest(
            url=f"{self._base_url}/v1/messages", headers=headers, json=body
        )

    def _complete(self, call: ModelCall, reply: HttpResponse) -> ModelCompletion:
        body = _as_dict(reply.body)
        blocks = body.get("content")
        text = _anthropic_text(blocks)
        usage = _as_dict(body.get("usage"))
        counts = Usage(
            input_tokens=_as_int(usage.get("input_tokens")),
            output_tokens=_as_int(usage.get("output_tokens")),
            cost_micros=0,
        )
        model = _model(body.get("model"), call)
        if body.get("stop_reason") == "refusal":
            return ModelCompletion(
                outcome="refused", resolved_model=model, usage=counts
            )
        if text is None:
            return _error(call, "provider-error", retryable=False)
        return ModelCompletion(
            outcome="completed",
            resolved_model=model,
            usage=counts,
            output={"text": text},
        )


class OpenAIAdapter(ChatAdapter):
    """Reach the OpenAI Chat Completions API with a bearer-token credential."""

    provider_name: ClassVar[str] = "openai"

    def _request(self, call: ModelCall) -> HttpRequest:
        headers = dict(_JSON_HEADERS)
        if call.secret is not None:
            headers["authorization"] = f"Bearer {call.secret}"
        body: dict[str, Any] = {
            "model": call.model_selector,
            "messages": _messages(call),
            "max_completion_tokens": self._max_tokens,
        }
        temperature = self._temperature(call)
        if temperature is not None:
            body["temperature"] = temperature
        return HttpRequest(
            url=f"{self._base_url}/v1/chat/completions", headers=headers, json=body
        )

    def _complete(self, call: ModelCall, reply: HttpResponse) -> ModelCompletion:
        body = _as_dict(reply.body)
        choices = body.get("choices")
        choice = _as_dict(choices[0]) if isinstance(choices, list) and choices else {}
        message = _as_dict(choice.get("message"))
        text = message.get("content")
        usage = _as_dict(body.get("usage"))
        counts = Usage(
            input_tokens=_as_int(usage.get("prompt_tokens")),
            output_tokens=_as_int(usage.get("completion_tokens")),
            cost_micros=0,
        )
        model = _model(body.get("model"), call)
        if choice.get("finish_reason") == "content_filter":
            return ModelCompletion(
                outcome="refused", resolved_model=model, usage=counts
            )
        if not isinstance(text, str):
            return _error(call, "provider-error", retryable=False)
        return ModelCompletion(
            outcome="completed",
            resolved_model=model,
            usage=counts,
            output={"text": text},
        )


# -- the registry -------------------------------------------------------------

_ADAPTERS: dict[str, type[ChatAdapter]] = {
    "oss": OllamaAdapter,
    "anthropic": AnthropicAdapter,
    "openai": OpenAIAdapter,
}

_DEFAULT_BASE: dict[str, str] = {
    "oss": "http://localhost:11434",
    "anthropic": "https://api.anthropic.com",
    "openai": "https://api.openai.com",
}


def adapter_for(
    provider: str,
    *,
    base_url: str | None = None,
    transport: HttpTransport | None = None,
    timeout: float = 30.0,
    temperature: float | None = None,
    max_tokens: int = 1024,
) -> ChatAdapter:
    """Return the built adapter for one internal provider name.

    ``provider`` is the name an ``AgentVersion`` carries (``"oss"`` for Ollama,
    ``"anthropic"``, ``"openai"``). The wiring picks the adapter by that name, so a
    study author only sets the provider on the agent and never chooses an adapter.
    ``base_url`` overrides the provider's default endpoint (a self-hosted proxy, a
    non-default Ollama host).
    """
    try:
        cls = _ADAPTERS[provider]
    except KeyError:
        supported = ", ".join(sorted(_ADAPTERS))
        raise ValueError(
            f"no built adapter for provider {provider!r}; built: {supported}"
        ) from None
    return cls(
        base_url=base_url or _DEFAULT_BASE[provider],
        transport=transport,
        timeout=timeout,
        temperature=temperature,
        max_tokens=max_tokens,
    )


# -- shared helpers -----------------------------------------------------------


def _messages(call: ModelCall) -> Messages:
    """Return the chat messages the caller rendered, in the shape a provider reads.

    Every one of the three providers names the words of a message ``content``. A
    message that names them something else is a message the provider reads as empty,
    which is worse than an error: Ollama answers the empty question it was asked and
    Anthropic refuses the request, and either way the participant is answered by a
    model that was never told what they said. So the words are put where the provider
    looks for them here, at the one place every adapter passes through.
    """
    payload = call.payload
    if isinstance(payload, dict):
        messages = cast("dict[str, Any]", payload).get("messages")
        if isinstance(messages, list):
            return [_message(one) for one in cast("list[Any]", messages)]
    return []


def _message(one: Any) -> dict[str, Any]:
    """Return one message with its words under ``content`` and a role beside them.

    Anything else the caller put on the message is kept, because a provider reads
    more than two fields -- an Anthropic ``content`` is a list of blocks as often as
    it is a string. Only an absent ``content`` is filled in, from ``text``.
    """
    mapping = dict(_as_dict(one))
    if "content" not in mapping:
        text = mapping.pop("text", None)
        mapping["content"] = text if isinstance(text, str) else ""
    if not isinstance(mapping.get("role"), str):
        mapping["role"] = "user"
    return mapping


def _anthropic_text(blocks: Any) -> str | None:
    """Join the text of every text block in an Anthropic content array."""
    if not isinstance(blocks, list):
        return None
    parts: list[str] = []
    for block in cast("list[Any]", blocks):
        mapping = _as_dict(block)
        text = mapping.get("text")
        if mapping.get("type") == "text" and isinstance(text, str):
            parts.append(text)
    joined = "".join(parts)
    return joined or None


def _model(reported: Any, call: ModelCall) -> str:
    """Return the model the provider reported, or the requested selector if none."""
    return reported if isinstance(reported, str) and reported else call.model_selector


def _as_dict(value: Any) -> dict[str, Any]:
    """Return the value as a mapping, or an empty one when the shape is wrong."""
    return cast("dict[str, Any]", value) if isinstance(value, dict) else {}


def _as_int(value: Any) -> int:
    """Return the value as a non-negative int, or 0 when it is missing or wrong."""
    return value if isinstance(value, int) and value >= 0 else 0


def _error(
    call: ModelCall,
    error_class: Literal["timeout", "rate-limit", "provider-error", "content-filter"],
    *,
    retryable: bool,
) -> ModelCompletion:
    """Build an error completion for one failed call, with zero usage."""
    return ModelCompletion(
        outcome="error",
        resolved_model=call.model_selector,
        usage=Usage(input_tokens=0, output_tokens=0, cost_micros=0),
        error_class=error_class,
        retryable=retryable,
    )


__all__ = [
    "AnthropicAdapter",
    "ChatAdapter",
    "HttpRequest",
    "HttpResponse",
    "HttpTransport",
    "OllamaAdapter",
    "OpenAIAdapter",
    "TransportFailure",
    "adapter_for",
    "httpx_transport",
]
