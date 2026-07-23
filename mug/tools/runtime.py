"""The tool runtime: run one gated tool call and record it (API-14).

The API-14 family (``mug.tools``) owns five records -- the immutable
``ToolVersion`` build, the idempotent ``ToolCall``, the human ``ToolApproval``, the
executed ``ToolResult``, and the ``EnvironmentCommandMailbox`` -- but adds no
runtime. This module is that runtime. It drives a tool call's lifecycle through the
shared command spine (``mug.runtime``), so a call's lineage is a canonical event
stream like any other aggregate: the request, an optional approval, and the
terminal result, all on the call's own stream.

The vendor stays out of the core, exactly as it does for a model call. A study
injects the tool *executor*: an async callable that takes an invocation and returns
its output. So the core imports no tool SDK, and a test runs the whole path with a
deterministic ``FakeExecutor`` and no network. A study writes one small executor per
tool behind the same seam.

Three safety rules bind the runtime, from the API standard:

- **Approval.** A tool version with an approval gate does not execute until a human
  approval is recorded. A denied approval records a denied result and never runs the
  tool. A gated call that runs with no approval raises ``ApprovalPending``.
- **Egress.** A tool version names an egress allowlist. A call that names a target
  host outside the allowlist records a failed result and never runs the tool, so a
  forbidden egress produces no side effect.
- **Idempotency.** A tool call is keyed by its own id, and a retry that finds a
  terminal result replays the recorded outcome without running the tool again -- the
  same double-effect guard a mutating tool needs.

The runtime is a producer boundary, so the caller injects the impure parts (the
store and the clock) and mints the ``CommandContext`` for each operation on the
call's stream, exactly as every other family service takes an already-minted
context.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, cast

from mug.kernel import (
    CommandReceipt,
    CommandTypeRef,
    Digest,
    PrincipalRef,
    TypedObject,
    UtcInstant,
    compute_digest,
)
from mug.runtime import CommandContext, commit_command
from mug.storage import Store
from mug.tools.types import (
    EnvironmentCommandMailbox,
    ToolApproval,
    ToolCall,
    ToolResult,
    ToolVersion,
)

_ToolRecord = ToolCall | ToolApproval | ToolResult | EnvironmentCommandMailbox

_REQUEST = CommandTypeRef(name="tool.request", version=0)
_APPROVE = CommandTypeRef(name="tool.approve", version=0)
_EXECUTE = CommandTypeRef(name="tool.execute", version=0)
_ENQUEUE = CommandTypeRef(name="tool.enqueue", version=0)
_DELIVER = CommandTypeRef(name="tool.deliver", version=0)

_INSTANT = "%Y-%m-%dT%H:%M:%S.%fZ"

# The tool arguments and the tool output are study-shaped, so the seam types them
# as ``Any`` (duck-typed); both must be JSON-serializable, since the runtime
# digests them into the arguments digest and the result digest.
Arguments = Any
ToolOutput = Any


class ApprovalPending(Exception):
    """A gated tool call tried to run with no recorded approval decision.

    The tool version has an approval gate, so the call must carry an approval
    before it runs. The caller records the human decision with ``approve`` and
    retries ``execute`` with it.
    """


@dataclass(frozen=True)
class ToolInvocation:
    """What a study's tool executor receives to run one tool call.

    ``arguments`` is the study-shaped input (digested into the call). ``target_hosts``
    names the hosts the run would reach; the broker checks each against the tool
    version's egress allowlist before it runs the tool, so a forbidden egress never
    reaches the executor.
    """

    arguments: Arguments
    target_hosts: tuple[str, ...] = ()


@dataclass(frozen=True)
class ToolExecution:
    """What a tool executor returns from one run: the tool's output.

    The output is digested into the result and returned raw to the caller; it is
    never persisted here, exactly as a model output is recorded by digest alone.
    """

    output: ToolOutput


ToolExecutor = Callable[[ToolInvocation], Awaitable[ToolExecution]]


@dataclass(frozen=True)
class ToolCallResult:
    """The recorded outcome of one tool call, plus its transient raw output.

    ``result`` is the terminal ``ToolResult`` record. ``output`` is the raw tool
    output for an executed call and ``None`` otherwise; it is never persisted, so a
    call replayed from a terminal head returns ``output=None``. ``replayed`` marks a
    result rebuilt from a terminal head for an idempotent retry.
    """

    tool_call_id: str
    result: ToolResult
    output: ToolOutput = None
    replayed: bool = False


class ToolBroker:
    """Drive one tool call's records through the command spine, with the gates.

    The broker holds the injected impurity -- the store, the executor, and the
    clock -- and exposes the call lifecycle: ``request`` records the call,
    ``approve`` records a human decision on a gated call, and ``execute`` runs the
    tool and records its result under the approval and egress gates. Each operation
    takes a ``CommandContext`` the caller minted for the call's aggregate.
    """

    def __init__(
        self,
        *,
        store: Store,
        executor: ToolExecutor,
        now: Callable[[], datetime],
    ) -> None:
        self._store = store
        self._executor = executor
        self._now = now

    async def request(
        self,
        *,
        context: CommandContext,
        tool_call_id: str,
        tool_version: ToolVersion,
        arguments_digest: Digest,
        idempotency_key: str,
    ) -> tuple[CommandReceipt, ToolCall]:
        """Record one tool call, keyed by its id, and return the call record.

        The commit creates the call aggregate. Whether the call needs approval and
        whether it mutates are read from the tool version, so the call carries the
        gate flags the tool declared. An identical retry of the command replays to
        the original receipt with no second effect.
        """
        call = ToolCall(
            tool_call_id=tool_call_id,
            tool_version_id=tool_version.tool_version_id,
            arguments_digest=arguments_digest,
            idempotency_key=idempotency_key,
            mutating=tool_version.mutating,
            approval_required=tool_version.approval_gate,
        )
        receipt = await commit_command(
            context,
            command=_REQUEST,
            new_state=_state(call),
            result=_typed(call),
            store=self._store,
        )
        return receipt, call

    async def approve(
        self,
        *,
        context: CommandContext,
        call: ToolCall,
        approver: PrincipalRef,
        decision: Literal["approved", "denied"],
    ) -> tuple[CommandReceipt, ToolApproval]:
        """Record one human decision on a gated tool call, and return it.

        The approval updates the call aggregate against its current revision, so it
        orders after the request and before the result. Only a gated call needs an
        approval; approving an ungated call is a caller error the broker rejects.
        """
        if not call.approval_required:
            raise ValueError("an ungated tool call needs no approval")
        approval = ToolApproval(
            tool_call_id=call.tool_call_id,
            approver=approver,
            decision=decision,
            decided_at=self._instant(),
        )
        revision = self._store.revision_of(call.tool_call_id) or 0
        receipt = await commit_command(
            context,
            command=_APPROVE,
            new_state=_state(approval),
            result=_typed(approval),
            store=self._store,
            expected_revision=revision,
        )
        return receipt, approval

    async def execute(
        self,
        *,
        context: CommandContext,
        call: ToolCall,
        tool_version: ToolVersion,
        invocation: ToolInvocation,
        approval: ToolApproval | None = None,
    ) -> ToolCallResult:
        """Run the tool under the gates and record its terminal result.

        A retry that finds a terminal result replays it without running the tool
        again. A gated call with no approval raises ``ApprovalPending``; a denied
        approval records a denied result. A target host outside the egress allowlist
        records a failed result, so a forbidden egress runs no tool. Otherwise the
        broker runs the executor and records an executed result that binds the output
        digest (and the approval digest for a gated call).
        """
        call_id = call.tool_call_id
        head = self._store.load_aggregate(call_id)
        if head is not None and _is_result(head):
            return ToolCallResult(
                tool_call_id=call_id,
                result=ToolResult.model_validate(head),
                replayed=True,
            )

        denied = self._gate_denial(call, approval)
        if denied is not None:
            return await self._record(call, denied, context, effect="none")

        forbidden = _egress_forbidden(tool_version, invocation)
        if forbidden:
            failed = self._terminal(call, "failed", approval, result_digest=None)
            return await self._record(call, failed, context, effect="none")

        execution = await self._executor(invocation)
        result_digest = compute_digest(execution.output)
        executed = self._terminal(
            call, "executed", approval, result_digest=result_digest
        )
        return await self._record(
            call,
            executed,
            context,
            effect="mutating" if call.mutating else "none",
            output=execution.output,
        )

    # -- internals --------------------------------------------------------------

    def _gate_denial(
        self, call: ToolCall, approval: ToolApproval | None
    ) -> ToolResult | None:
        """Return a denied result when the approval gate blocks the run, else None.

        A gated call with no approval raises ``ApprovalPending`` (the caller must
        record a decision first). A gated call whose approval was denied returns a
        denied result. An approved or ungated call returns None, so the run proceeds.
        """
        if not call.approval_required:
            return None
        if approval is None:
            raise ApprovalPending(call.tool_call_id)
        if approval.decision == "denied":
            return self._terminal(call, "denied", approval, result_digest=None)
        return None

    def _terminal(
        self,
        call: ToolCall,
        outcome: Literal["executed", "denied", "failed"],
        approval: ToolApproval | None,
        *,
        result_digest: Digest | None,
    ) -> ToolResult:
        """Build one terminal tool result, naming its evidence per the outcome.

        An executed result names its result digest; a gated executed result also
        names the approval digest (the record's own content digest). A denied or
        failed result names no result digest and no effect.
        """
        approval_digest = (
            compute_digest(_state(approval))
            if call.approval_required and approval is not None
            else None
        )
        return ToolResult(
            tool_call_id=call.tool_call_id,
            outcome=outcome,
            effect="mutating" if outcome == "executed" and call.mutating else "none",
            approval_required=call.approval_required,
            approval_digest=approval_digest if outcome == "executed" else None,
            result_digest=result_digest,
            executed_at=self._instant(),
        )

    async def _record(
        self,
        call: ToolCall,
        result: ToolResult,
        context: CommandContext,
        *,
        effect: Literal["none", "mutating"],
        output: ToolOutput = None,
    ) -> ToolCallResult:
        """Commit the terminal result against the call revision and return it."""
        revision = self._store.revision_of(call.tool_call_id) or 0
        await commit_command(
            context,
            command=_EXECUTE,
            new_state=_state(result),
            result=_typed(result),
            store=self._store,
            expected_revision=revision,
        )
        return ToolCallResult(
            tool_call_id=call.tool_call_id, result=result, output=output
        )

    def _instant(self) -> UtcInstant:
        """Return the current instant in the canonical wire form."""
        return self._now().astimezone(timezone.utc).strftime(_INSTANT)


class EnvironmentMailbox:
    """Queue one environment command to an interaction and track its delivery.

    A tool that acts on the environment does not call the environment directly; it
    queues a command in the mailbox, and the interaction loop delivers it and marks
    it delivered. The mailbox is one aggregate per queued command (the caller
    content-addresses its id from the interaction and the command key), so the
    enqueue and the delivery are two states on one stream.
    """

    def __init__(self, *, store: Store, now: Callable[[], datetime]) -> None:
        self._store = store
        self._now = now

    async def enqueue(
        self,
        *,
        context: CommandContext,
        interaction_id: str,
        command_key: str,
    ) -> tuple[CommandReceipt, EnvironmentCommandMailbox]:
        """Record one queued environment command (not yet delivered)."""
        mailbox = EnvironmentCommandMailbox(
            interaction_id=interaction_id,
            command_key=command_key,
            delivered=False,
            enqueued_at=self._instant(),
        )
        receipt = await commit_command(
            context,
            command=_ENQUEUE,
            new_state=_state(mailbox),
            result=_typed(mailbox),
            store=self._store,
        )
        return receipt, mailbox

    async def mark_delivered(
        self, *, context: CommandContext, mailbox: EnvironmentCommandMailbox
    ) -> tuple[CommandReceipt, EnvironmentCommandMailbox]:
        """Record that the queued command reached the interaction."""
        delivered = mailbox.model_copy(update={"delivered": True})
        revision = self._store.revision_of(context.aggregate_id) or 0
        receipt = await commit_command(
            context,
            command=_DELIVER,
            new_state=_state(delivered),
            result=_typed(delivered),
            store=self._store,
            expected_revision=revision,
        )
        return receipt, delivered

    def _instant(self) -> UtcInstant:
        """Return the current instant in the canonical wire form."""
        return self._now().astimezone(timezone.utc).strftime(_INSTANT)


class FakeExecutor:
    """A deterministic tool executor for tests and the ``mug simulate`` runner.

    The fake maps an invocation to an output through an injected function and
    records every invocation it received, so a test asserts the tool ran (or, for a
    blocked egress or a denied approval, that it did not).
    """

    def __init__(self, respond: Callable[[ToolInvocation], ToolOutput]) -> None:
        self._respond = respond
        self.calls: list[ToolInvocation] = []

    async def __call__(self, invocation: ToolInvocation) -> ToolExecution:
        """Return the fake output for the invocation and record that it ran."""
        self.calls.append(invocation)
        return ToolExecution(output=self._respond(invocation))


def _egress_forbidden(tool_version: ToolVersion, invocation: ToolInvocation) -> bool:
    """Return whether the invocation names a host outside the egress allowlist."""
    allowed = set(tool_version.egress_allowlist)
    return any(host not in allowed for host in invocation.target_hosts)


def _state(record: _ToolRecord) -> dict[str, Any]:
    """Dump one tool record to its canonical persisted form."""
    return record.model_dump(mode="json", exclude_none=True)


def _typed(record: _ToolRecord) -> TypedObject:
    """Wrap one tool record as the command result that carries its own schema."""
    return TypedObject(schema=record.schema, data=_state(record))


def _is_result(state: Any) -> bool:
    """Return whether an aggregate head is a recorded terminal tool result."""
    if not isinstance(state, dict):
        return False
    schema = cast("dict[str, Any]", state).get("schema")
    if not isinstance(schema, dict):
        return False
    return cast("dict[str, Any]", schema).get("name") == "mug.api-14.tool-result"


__all__ = [
    "ApprovalPending",
    "Arguments",
    "EnvironmentMailbox",
    "FakeExecutor",
    "ToolBroker",
    "ToolCallResult",
    "ToolExecution",
    "ToolExecutor",
    "ToolInvocation",
    "ToolOutput",
]
