"""The memory runtime reads and compare-and-swaps one agent-memory value.

These tests drive ``mug.memory.runtime.MemoryLedger`` against the in-memory store
with a fixed clock and hand-built command contexts. They prove the runtime
properties: a first commit on an empty memory advances one revision; a commit off
the fresh base advances again and records its provenance; a proposal whose base is no
longer current raises ``StaleMemoryVersion`` rather than retrying; a read projects the
current value; and a scope declaration records its treatment mode.
"""

from __future__ import annotations

import itertools
from datetime import datetime, timezone

from mug.kernel import Digest, compute_digest
from mug.memory import MemoryLedger, MemoryScope, StaleMemoryVersion
from mug.runtime import CommandContext
from mug.storage import InMemoryStore

_UUID = "019b6000-0000-7000-8000-{:012x}"
_START = datetime(2026, 7, 22, 0, 0, 0, tzinfo=timezone.utc)
_DIGEST = Digest(algorithm="sha-256", hex="a" * 64)
_DECISION = "decision_" + _UUID.format(0x300)


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


def _ledger(store: InMemoryStore) -> MemoryLedger:
    return MemoryLedger(store=store, now=lambda: _START)


def _memory_id() -> str:
    return "memory_" + _UUID.format(0x500)


async def test_a_first_commit_on_an_empty_memory_reaches_revision_one() -> None:
    """A first commit reads the empty base and advances one revision past it."""
    store, factory = InMemoryStore(), _Factory()
    ledger = _ledger(store)
    memory_id = _memory_id()

    read = ledger.read(memory_id=memory_id, scope_kind="working")
    assert read.base_version.revision == 1

    proposal = ledger.propose(
        memory_id=memory_id,
        scope_kind="working",
        proposed_digest=compute_digest({"note": "first"}),
        base_version=read.base_version,
        decision_id=_DECISION,
    )
    receipt, commit = await ledger.commit(context=factory(memory_id), proposal=proposal)

    assert receipt.outcome == "accepted"
    assert commit.new_version.revision == 2
    assert commit.prior_version.revision == 1
    assert commit.committed_digest == compute_digest({"note": "first"})


async def test_a_second_commit_advances_and_records_provenance() -> None:
    """A commit off the fresh base advances one revision and names its decision."""
    store, factory = InMemoryStore(), _Factory()
    ledger = _ledger(store)
    memory_id = _memory_id()

    first = ledger.propose(
        memory_id=memory_id,
        scope_kind="episodic",
        proposed_digest=compute_digest({"v": 1}),
        base_version=ledger.current(memory_id)[1],
        decision_id=_DECISION,
    )
    await ledger.commit(context=factory(memory_id), proposal=first)

    content, version = ledger.current(memory_id)
    assert content == compute_digest({"v": 1})
    assert version.revision == 2

    second_decision = "decision_" + _UUID.format(0x301)
    second = ledger.propose(
        memory_id=memory_id,
        scope_kind="episodic",
        proposed_digest=compute_digest({"v": 2}),
        base_version=version,
        decision_id=second_decision,
    )
    _, commit = await ledger.commit(context=factory(memory_id), proposal=second)

    assert commit.new_version.revision == 3
    assert commit.provenance_decision_id == second_decision


async def test_a_stale_proposal_is_refused_not_retried() -> None:
    """A proposal whose base is behind the current version raises, not retries."""
    store, factory = InMemoryStore(), _Factory()
    ledger = _ledger(store)
    memory_id = _memory_id()

    stale_base = ledger.current(memory_id)[1]  # the empty base

    # Someone else commits, advancing the memory one revision.
    ahead = ledger.propose(
        memory_id=memory_id,
        scope_kind="longitudinal",
        proposed_digest=compute_digest({"who": "other"}),
        base_version=stale_base,
        decision_id=_DECISION,
    )
    await ledger.commit(context=factory(memory_id), proposal=ahead)

    # Our proposal still names the empty base; the swap must be refused.
    ours = ledger.propose(
        memory_id=memory_id,
        scope_kind="longitudinal",
        proposed_digest=compute_digest({"who": "me"}),
        base_version=stale_base,
        decision_id=_DECISION,
    )
    raised = False
    try:
        await ledger.commit(context=factory(memory_id), proposal=ours)
    except StaleMemoryVersion:
        raised = True

    assert raised is True
    # The value is still the other agent's commit; our stale swap changed nothing.
    assert ledger.current(memory_id)[0] == compute_digest({"who": "other"})


async def test_a_scope_declaration_records_its_treatment_mode() -> None:
    """A scope declaration records its kind, treatment mode, and owner."""
    store, factory = InMemoryStore(), _Factory()
    ledger = _ledger(store)
    scope_id = "memory_" + _UUID.format(0x5A0)

    scope = MemoryScope(
        scope_kind="working",
        treatment_mode="ablated",
        owner_enrollment_id="enrollment_" + _UUID.format(0x600),
    )
    receipt = await ledger.declare_scope(context=factory(scope_id), scope=scope)

    assert receipt.outcome == "accepted"
    head = store.load_aggregate(scope_id)
    assert head is not None
    assert head["treatment_mode"] == "ablated"
