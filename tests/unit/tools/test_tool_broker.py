"""The tool runtime runs one gated call through an executor and records it.

These tests drive ``mug.tools.runtime.ToolBroker`` against the in-memory store with
a fixed clock, a deterministic ``FakeExecutor``, and hand-built command contexts.
They prove the runtime properties: an ungated call runs and records an executed
result with its output by digest; a gated call runs only after an approval and binds
the approval digest; a denied approval records a denied result and runs no tool; a
target host outside the egress allowlist records a failed result and runs no tool; a
retry replays the terminal result without running the tool again; and the
environment mailbox tracks a queued command from enqueue to delivered.
"""

from __future__ import annotations

import itertools
from datetime import datetime, timezone

from mug.kernel import Digest, PrincipalRef, compute_digest
from mug.runtime import CommandContext
from mug.storage import InMemoryStore
from mug.tools import (
    ApprovalPending,
    EnvironmentMailbox,
    FakeExecutor,
    ToolBroker,
    ToolInvocation,
    ToolVersion,
)

_UUID = "019b6000-0000-7000-8000-{:012x}"
_START = datetime(2026, 7, 22, 0, 0, 0, tzinfo=timezone.utc)
_DIGEST = Digest(algorithm="sha-256", hex="a" * 64)
_ARGS = Digest(algorithm="sha-256", hex="b" * 64)


def _tool_version(
    *,
    mutating: bool = False,
    approval_gate: bool = False,
    egress: list[str] | None = None,
) -> ToolVersion:
    return ToolVersion(
        tool_version_id="toolver_" + _UUID.format(0x100),
        tool_definition_id="tooldef_" + _UUID.format(0x110),
        tool_kind="native",
        mutating=mutating,
        approval_gate=approval_gate,
        egress_allowlist=egress if egress is not None else [],
    )


def _approver() -> PrincipalRef:
    return PrincipalRef(kind="researcher", id="researcher_" + _UUID.format(0x900))


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


def _broker(store: InMemoryStore, executor: FakeExecutor) -> ToolBroker:
    return ToolBroker(store=store, executor=executor, now=lambda: _START)


def _call_id(seed: str) -> str:
    return "toolcall_" + _UUID.format(int(compute_digest(seed).hex[:8], 16) & 0xFFFF)


async def test_an_ungated_call_runs_and_records_an_executed_result() -> None:
    """An ungated call runs the tool and records an executed result by digest."""
    store, factory = InMemoryStore(), _Factory()
    executor = FakeExecutor(respond=lambda inv: {"echo": inv.arguments})
    broker = _broker(store, executor)
    version = _tool_version(mutating=True)
    call_id = _call_id("search")

    _, call = await broker.request(
        context=factory(call_id),
        tool_call_id=call_id,
        tool_version=version,
        arguments_digest=_ARGS,
        idempotency_key="idem_" + "0" * 21 + "A",
    )
    result = await broker.execute(
        context=factory(call_id),
        call=call,
        tool_version=version,
        invocation=ToolInvocation(arguments={"q": "hi"}),
    )

    assert result.result.outcome == "executed"
    assert result.result.effect == "mutating"
    assert result.result.result_digest == compute_digest({"echo": {"q": "hi"}})
    assert len(executor.calls) == 1
    head = store.load_aggregate(call_id)
    assert head is not None
    assert head["schema"]["name"] == "mug.api-14.tool-result"


async def test_a_gated_call_runs_only_after_approval_and_binds_the_digest() -> None:
    """A gated call needs an approval; the executed result names its digest."""
    store, factory = InMemoryStore(), _Factory()
    executor = FakeExecutor(respond=lambda inv: {"ran": True})
    broker = _broker(store, executor)
    version = _tool_version(approval_gate=True)
    call_id = _call_id("delete")

    _, call = await broker.request(
        context=factory(call_id),
        tool_call_id=call_id,
        tool_version=version,
        arguments_digest=_ARGS,
        idempotency_key="idem_" + "1" * 21 + "A",
    )

    # Running before an approval is recorded is refused.
    raised = False
    try:
        await broker.execute(
            context=factory(call_id),
            call=call,
            tool_version=version,
            invocation=ToolInvocation(arguments={}),
        )
    except ApprovalPending:
        raised = True
    assert raised is True
    assert executor.calls == []

    _, approval = await broker.approve(
        context=factory(call_id), call=call, approver=_approver(), decision="approved"
    )
    result = await broker.execute(
        context=factory(call_id),
        call=call,
        tool_version=version,
        invocation=ToolInvocation(arguments={}),
        approval=approval,
    )

    assert result.result.outcome == "executed"
    assert result.result.approval_required is True
    assert result.result.approval_digest is not None
    assert len(executor.calls) == 1


async def test_a_denied_approval_records_a_denied_result_and_runs_no_tool() -> None:
    """A denied approval records a denied result; the tool never runs."""
    store, factory = InMemoryStore(), _Factory()
    executor = FakeExecutor(respond=lambda inv: {"ran": True})
    broker = _broker(store, executor)
    version = _tool_version(approval_gate=True)
    call_id = _call_id("wipe")

    _, call = await broker.request(
        context=factory(call_id),
        tool_call_id=call_id,
        tool_version=version,
        arguments_digest=_ARGS,
        idempotency_key="idem_" + "2" * 21 + "A",
    )
    _, approval = await broker.approve(
        context=factory(call_id), call=call, approver=_approver(), decision="denied"
    )
    result = await broker.execute(
        context=factory(call_id),
        call=call,
        tool_version=version,
        invocation=ToolInvocation(arguments={}),
        approval=approval,
    )

    assert result.result.outcome == "denied"
    assert result.result.effect == "none"
    assert result.result.result_digest is None
    assert executor.calls == []


async def test_a_host_outside_the_allowlist_records_a_failed_result() -> None:
    """A forbidden egress host records a failed result and runs no tool."""
    store, factory = InMemoryStore(), _Factory()
    executor = FakeExecutor(respond=lambda inv: {"ran": True})
    broker = _broker(store, executor)
    version = _tool_version(egress=["api.allowed.example"])
    call_id = _call_id("fetch")

    _, call = await broker.request(
        context=factory(call_id),
        tool_call_id=call_id,
        tool_version=version,
        arguments_digest=_ARGS,
        idempotency_key="idem_" + "3" * 21 + "A",
    )
    result = await broker.execute(
        context=factory(call_id),
        call=call,
        tool_version=version,
        invocation=ToolInvocation(
            arguments={}, target_hosts=("evil.example", "api.allowed.example")
        ),
    )

    assert result.result.outcome == "failed"
    assert result.result.effect == "none"
    assert executor.calls == []


async def test_a_retry_replays_the_terminal_result_without_running_the_tool() -> None:
    """A second execute of a terminal call replays the result, no second run."""
    store, factory = InMemoryStore(), _Factory()
    executor = FakeExecutor(respond=lambda inv: {"n": len(executor.calls)})
    broker = _broker(store, executor)
    version = _tool_version()
    call_id = _call_id("idem")

    _, call = await broker.request(
        context=factory(call_id),
        tool_call_id=call_id,
        tool_version=version,
        arguments_digest=_ARGS,
        idempotency_key="idem_" + "4" * 21 + "A",
    )
    first = await broker.execute(
        context=factory(call_id),
        call=call,
        tool_version=version,
        invocation=ToolInvocation(arguments={}),
    )
    replay = await broker.execute(
        context=factory(call_id),
        call=call,
        tool_version=version,
        invocation=ToolInvocation(arguments={}),
    )

    assert replay.replayed is True
    assert replay.result.result_digest == first.result.result_digest
    assert len(executor.calls) == 1


async def test_the_environment_mailbox_tracks_a_queued_command() -> None:
    """The mailbox records a queued environment command, then marks it delivered."""
    store, factory = InMemoryStore(), _Factory()
    mailbox = EnvironmentMailbox(store=store, now=lambda: _START)
    box_id = "toolcall_" + _UUID.format(0x777)  # a content-addressed mailbox stream

    _, queued = await mailbox.enqueue(
        context=factory(box_id),
        interaction_id="interaction_" + _UUID.format(0x200),
        command_key="reset-round",
    )
    assert queued.delivered is False

    _, delivered = await mailbox.mark_delivered(context=factory(box_id), mailbox=queued)
    assert delivered.delivered is True
    head = store.load_aggregate(box_id)
    assert head is not None
    assert head["delivered"] is True
