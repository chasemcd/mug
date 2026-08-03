"""The model-provider runtime: run one model call and record it (API-13).

The API-13 family (``mug.providers``) owns four records -- the immutable
``AgentVersion`` build, the ``ProviderRequest`` that dispatches one call, the
``ProviderResponse`` that records its outcome and usage, and the ``ProviderError``
that classifies a failure -- but adds no runtime. This module is that runtime. It
drives the request and its outcome through the shared command spine
(``mug.runtime``), so a model call's lineage is a canonical event stream like any
other aggregate.

The vendor stays out of the core. A study injects the provider *adapter*: an async
callable that takes a rendered payload and a resolved credential and returns a
completion. So the core imports no vendor SDK, and a test runs the whole path with
a deterministic ``FakeProvider`` and no network. A study writes one small adapter
per provider (Anthropic, OpenAI, an HTTP endpoint) behind the same seam.

The secret never enters a record, an event, or a log. A record names the
credential by ``secret_name`` only; the runtime resolves the value through an
injected ``SecretResolver`` at call time, passes it to the adapter, and never
records it. The response records the output by digest alone; the raw output is
returned to the caller and never persisted here.

The call is a producer boundary, so the caller injects the impure parts: the
store, the clock, a model-generation-id minter, and a ``CommandContext`` factory
that mints a fresh context on the call's stream (the one entropy-and-clock
boundary), exactly as every other family service takes an already-minted context.

One idempotency rule protects against a double spend: a model call is expensive
and not repeatable for free, so the runtime records the request *before* it calls
the adapter, and a retry that finds a terminal head returns the recorded outcome
without calling the model again.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, cast

from mug.diagnostics import Diagnostics, NullDiagnostics
from mug.kernel import (
    CommandReceipt,
    CommandTypeRef,
    TypedObject,
    UtcInstant,
    compute_digest,
)
from mug.providers.tape import OutputTape
from mug.providers.types import (
    AgentVersion,
    ProviderError,
    ProviderRequest,
    ProviderResponse,
    Usage,
)
from mug.runtime import CommandContext, commit_command
from mug.storage import Store

# The rendered request payload, the raw model output, and the resolved secret are
# all study-shaped, so the seam types them as ``Any`` (P0 duck-typing). The
# payload and the output must be JSON-serializable; the runtime digests them.
Payload = Any
Output = Any

ErrorClass = Literal["timeout", "rate-limit", "provider-error", "content-filter"]

_Record = ProviderRequest | ProviderResponse | ProviderError

_SUBMIT = CommandTypeRef(name="provider.submit", version=0)
_RESPOND = CommandTypeRef(name="provider.respond", version=0)
_FAIL = CommandTypeRef(name="provider.fail", version=0)

_INSTANT = "%Y-%m-%dT%H:%M:%S.%fZ"


@dataclass(frozen=True)
class ModelCall:
    """What a study's provider adapter receives to run one model call.

    The payload is the study-rendered request (messages, parameters). The secret
    is the resolved credential, held only for the duration of the call and never
    recorded; it is ``None`` for an adapter that needs none (a local endpoint or
    the fake).
    """

    model_selector: str
    payload: Payload
    secret: str | None
    # Why the call is being made. ``decision`` is a call the study asked for.
    # ``warm-up`` is the platform reaching the model once before a round, to load it
    # and to find out that it answers before a participant is looking at a game.
    #
    # An adapter for a real provider does not care: a call is a call. An adapter
    # that answers **by sequence** does -- a script, a simulation, a test double --
    # because a warm-up would otherwise take the first answer meant for a decision
    # and every answer after it would be one behind. So it is named rather than
    # left to be guessed at from the payload.
    purpose: str = "decision"


@dataclass(frozen=True)
class ModelCompletion:
    """What a provider adapter returns from one model call.

    A ``completed`` call carries the raw output; a ``refused`` call carries none;
    an ``error`` names its class and whether a retry may succeed. The usage is the
    token counts and cost the provider reported.
    """

    outcome: Literal["completed", "refused", "error"]
    resolved_model: str
    usage: Usage
    output: Output = None
    error_class: ErrorClass | None = None
    retryable: bool = False


# A provider adapter is an async callable a study injects; the core never imports
# a vendor SDK. A secret resolver maps a credential name to its value at call time.
ProviderAdapter = Callable[[ModelCall], Awaitable[ModelCompletion]]
SecretResolver = Callable[[str], str]
NewContext = Callable[[str], CommandContext]


@dataclass(frozen=True)
class ModelCallResult:
    """The recorded outcome of one model call, plus its transient raw output.

    ``response`` is set for a completed or refused call and ``error`` for a failed
    one; exactly one is set. ``output`` is the raw model output for a completed
    call and ``None`` otherwise; it is never persisted, so a call replayed from a
    terminal head returns ``output=None`` and ``request=None``.
    """

    modelcall_id: str
    request: ProviderRequest | None
    response: ProviderResponse | None
    error: ProviderError | None
    output: Output = None
    replayed: bool = False


class ModelProvider:
    """Run one model call through an injected adapter and record its lineage.

    The provider holds the injected impurity -- the store, the clock, the
    generation-id minter, and the adapter -- and exposes one operation. The caller
    passes the ``AgentVersion`` build, the rendered payload, a secret resolver, and
    a context factory that mints a fresh ``CommandContext`` on the call's stream.
    """

    def __init__(
        self,
        *,
        store: Store,
        adapter: ProviderAdapter,
        now: Callable[[], datetime],
        new_generation_id: Callable[[], str],
        output_tape: OutputTape | None = None,
        diagnostics: Diagnostics | None = None,
    ) -> None:
        self._store = store
        self._adapter = adapter
        self._now = now
        self._new_generation_id = new_generation_id
        # Opt-in durable output tape: when set, a completed output is persisted
        # content-addressed by its digest and rehydrated on a replay, so a decision
        # replays its reply exactly. Unset by default, so nothing is persisted.
        self._output_tape = output_tape
        # Where this call says what it asked and what came back, for a person
        # watching the run. It is every model call the platform makes -- a playing
        # seat's, a conversation's, a generated candidate's -- because they all come
        # through here, which is what makes this the one place worth watching.
        # The default discards, so an unwatched call costs one method call.
        self._diagnostics: Diagnostics = diagnostics or NullDiagnostics()

    async def invoke(
        self,
        *,
        modelcall_id: str,
        agent_version: AgentVersion,
        payload: Payload,
        new_context: NewContext,
        resolve_secret: SecretResolver | None = None,
        secret_name: str | None = None,
        purpose: str = "decision",
    ) -> ModelCallResult:
        """Run one model call, record the request and its outcome, and return both.

        The runtime records the request first, so a retry that finds a terminal
        head (a recorded response or error) returns the recorded outcome without a
        second call to the model. A crash between the request and the outcome
        leaves a request head; a retry skips the create and records the outcome
        against the request revision.
        """
        name = secret_name or agent_version.secret_name
        if name is None:
            raise ValueError(
                "a provider request names a secret; this agent version names none"
            )
        head = self._store.load_aggregate(modelcall_id)
        if head is not None and _is_terminal(head):
            self._diagnostics.note(
                "model.replayed",
                subject=agent_version.agent_key,
                modelcall_id=modelcall_id,
                model=agent_version.model_selector,
            )
            return await self._replay(modelcall_id, head)

        request = ProviderRequest(
            modelcall_id=modelcall_id,
            agent_version_id=agent_version.agent_version_id,
            request_digest=compute_digest(payload),
            secret_name=name,
            submitted_at=self._instant(),
        )
        if head is None:
            await commit_command(
                new_context(modelcall_id),
                command=_SUBMIT,
                new_state=_state(request),
                result=_typed(request),
                store=self._store,
            )
        revision = self._store.revision_of(modelcall_id) or 0

        # What the model was asked. The credential is **named** and never valued,
        # which is the same rule the record follows: the resolved secret is one line
        # below this and is the one thing a note may not carry.
        self._diagnostics.note(
            "model.call",
            subject=agent_version.agent_key,
            modelcall_id=modelcall_id,
            model=agent_version.model_selector,
            agent_version_id=agent_version.agent_version_id,
            secret_name=name,
            payload=payload,
            purpose=purpose,
        )
        secret = resolve_secret(name) if resolve_secret is not None else None
        started = time.perf_counter()
        try:
            completion = await self._adapter(
                ModelCall(
                    model_selector=agent_version.model_selector,
                    payload=payload,
                    secret=secret,
                    purpose=purpose,
                )
            )
        except Exception as raised:
            # An adapter that raises is the failure a study most often has in front
            # of it -- a refused connection, a model that is not pulled, a bad URL --
            # and it is the one the ledger says least about, because the call never
            # reached an outcome to record. So it is written down before it is
            # raised on, and the exception goes on exactly where it went before.
            self._diagnostics.note(
                "model.raised",
                subject=agent_version.agent_key,
                modelcall_id=modelcall_id,
                error=type(raised).__name__,
                message=str(raised),
                took_ms=_since(started),
            )
            raise
        self._note_completion(
            modelcall_id, agent_version, completion, started, purpose
        )
        return await self._record(
            modelcall_id=modelcall_id,
            request=request,
            completion=completion,
            new_context=new_context,
            revision=revision,
        )

    # -- internals --------------------------------------------------------------

    def _note_completion(
        self,
        modelcall_id: str,
        agent_version: AgentVersion,
        completion: ModelCompletion,
        started: float,
        purpose: str,
    ) -> None:
        """Write down what came back: the reply, what it cost, and how long it took.

        A refusal and an error are written under their own kinds rather than as a
        reply with a flag on it, because the three are read differently: a reply is
        read, a refusal is a content filter to look at, and an error is a provider to
        go and fix.
        """
        common: dict[str, Any] = {
            "modelcall_id": modelcall_id,
            "model": completion.resolved_model,
            "took_ms": _since(started),
            # A reader has to be able to tell the platform's own warm-up from a call
            # the study asked for, or the first reply of every round reads as an
            # answer to a question nobody can find in the study.
            "purpose": purpose,
        }
        if completion.outcome == "error":
            self._diagnostics.note(
                "model.error",
                subject=agent_version.agent_key,
                error_class=completion.error_class or "provider-error",
                retryable=completion.retryable,
                **common,
            )
            return
        self._diagnostics.note(
            "model.reply" if completion.outcome == "completed" else "model.refused",
            subject=agent_version.agent_key,
            output=completion.output,
            input_tokens=completion.usage.input_tokens,
            output_tokens=completion.usage.output_tokens,
            cost_micros=completion.usage.cost_micros,
            **common,
        )

    async def _record(
        self,
        *,
        modelcall_id: str,
        request: ProviderRequest,
        completion: ModelCompletion,
        new_context: NewContext,
        revision: int,
    ) -> ModelCallResult:
        """Commit the call's terminal record and return the result with its output.

        A completed or refused call records a ``ProviderResponse``; an errored call
        records a ``ProviderError``. The completed output is digested into the
        response and returned raw to the caller, never persisted.
        """
        if completion.outcome == "error":
            error = ProviderError(
                modelcall_id=modelcall_id,
                error_class=completion.error_class or "provider-error",
                retryable=completion.retryable,
            )
            await self._commit(_FAIL, error, new_context(modelcall_id), revision)
            return ModelCallResult(
                modelcall_id=modelcall_id, request=request, response=None, error=error
            )

        output = completion.output if completion.outcome == "completed" else None
        response = ProviderResponse(
            modelcall_id=modelcall_id,
            generation_id=self._new_generation_id(),
            outcome=completion.outcome,
            resolved_model=completion.resolved_model,
            usage=completion.usage,
            output_digest=compute_digest(output) if output is not None else None,
            completed_at=self._instant(),
        )
        await self._commit(_RESPOND, response, new_context(modelcall_id), revision)
        # Persist the verbatim output on the durable tape, keyed by its digest, so a
        # later replay reads back the exact reply instead of only its digest.
        if (
            self._output_tape is not None
            and output is not None
            and response.output_digest is not None
        ):
            await self._output_tape.put(response.output_digest, output)
        return ModelCallResult(
            modelcall_id=modelcall_id,
            request=request,
            response=response,
            error=None,
            output=output,
        )

    async def _replay(self, modelcall_id: str, head: Any) -> ModelCallResult:
        """Rebuild a terminal outcome from a stored head for an idempotent retry.

        The store keeps only the head, so the original request is not
        reconstructable; the replay returns the recorded outcome with
        ``request=None``. When an output tape is set and the head is a completed
        response, the verbatim output is rehydrated from the tape by the recorded
        digest, so the caller re-derives the reply exactly rather than seeing none.
        """
        if _schema_name(head) == "mug.api-13.provider-error":
            return ModelCallResult(
                modelcall_id=modelcall_id,
                request=None,
                response=None,
                error=ProviderError.model_validate(head),
                replayed=True,
            )
        response = ProviderResponse.model_validate(head)
        output: Output = None
        if self._output_tape is not None and response.output_digest is not None:
            output = await self._output_tape.get(response.output_digest)
        return ModelCallResult(
            modelcall_id=modelcall_id,
            request=None,
            response=response,
            error=None,
            output=output,
            replayed=True,
        )

    async def _commit(
        self,
        command: CommandTypeRef,
        record: ProviderResponse | ProviderError,
        context: CommandContext,
        revision: int,
    ) -> CommandReceipt:
        """Record the call's terminal state as an update against its request."""
        return await commit_command(
            context,
            command=command,
            new_state=_state(record),
            result=_typed(record),
            store=self._store,
            expected_revision=revision,
        )

    def _instant(self) -> UtcInstant:
        """Return the current instant in the canonical wire form."""
        return self._now().astimezone(timezone.utc).strftime(_INSTANT)


class FakeProvider:
    """A deterministic provider adapter for tests and the ``mug simulate`` runner.

    The fake maps a rendered payload to an output through an injected function and
    reports a fixed usage, so a study drives the whole provider path with no
    network and no credential. It never inspects the secret. The error and refusal
    paths are exercised with a small inline adapter, not through the fake.
    """

    def __init__(
        self,
        respond: Callable[[Payload], Output],
        *,
        resolved_model: str = "fake-model",
        usage: Usage | None = None,
    ) -> None:
        self._respond = respond
        self._resolved_model = resolved_model
        self._usage = usage or Usage(input_tokens=0, output_tokens=0, cost_micros=0)

    async def __call__(self, call: ModelCall) -> ModelCompletion:
        """Return a completed model completion for the call's payload."""
        return ModelCompletion(
            outcome="completed",
            resolved_model=self._resolved_model,
            usage=self._usage,
            output=self._respond(call.payload),
        )


def _since(started: float) -> int:
    """Return how long a call took, in whole milliseconds.

    It is a wall-clock reading and not a recorded instant: how long a model took is
    a fact about this machine and this moment, and nothing replays it.
    """
    return int((time.perf_counter() - started) * 1000)


def _state(record: _Record) -> dict[str, Any]:
    """Dump one provider record to its canonical persisted form."""
    return record.model_dump(mode="json", exclude_none=True)


def _typed(record: _Record) -> TypedObject:
    """Wrap one provider record as the command result that carries its schema."""
    return TypedObject(schema=record.schema, data=_state(record))


def _schema_name(state: Any) -> str | None:
    """Return the schema name of a persisted aggregate state, if it has one."""
    if not isinstance(state, dict):
        return None
    schema = cast("dict[str, Any]", state).get("schema")
    if not isinstance(schema, dict):
        return None
    name = cast("dict[str, Any]", schema).get("name")
    return name if isinstance(name, str) else None


def _is_terminal(state: Any) -> bool:
    """Return whether an aggregate head is a recorded response or error."""
    return _schema_name(state) in (
        "mug.api-13.provider-response",
        "mug.api-13.provider-error",
    )


__all__ = [
    "ErrorClass",
    "FakeProvider",
    "ModelCall",
    "ModelCallResult",
    "ModelCompletion",
    "ModelProvider",
    "NewContext",
    "ProviderAdapter",
    "SecretResolver",
]
