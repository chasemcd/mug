"""Behavior of the visits advance handler on the shared runtime spine.

These tests drive ``advance_visit`` against the in-memory store. A created visit
is seeded at revision 1; the happy path advances it and commits at revision 2, a
stale seen-revision rejects with a revision conflict, an illegal transition
rejects with a state conflict, and an absent visit rejects as not found. The seed
visit comes from the frozen minimal fixture with its status set to ``created``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from mug.kernel import VersionStamp, etag
from mug.runtime import CommandContext
from mug.storage import InMemoryStore
from mug.visits import AdvanceVisitCommand, Visit, advance_visit

_FIXTURES = (
    Path(__file__).resolve().parents[3]
    / "docs/architecture/phase-0/api-04/fixtures/v0/valid"
)
_UUID = "019b6000-0000-7000-8000-0000000000{:02x}"
_DIGEST = {"algorithm": "sha-256", "hex": "a" * 64}


def _load(name: str) -> dict[str, Any]:
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


def _created_visit() -> Visit:
    data = _load("visit.minimal-static.json")
    body = {k: v for k, v in data.items() if k not in ("schema", "version")}
    body["status"] = "created"
    return Visit(**body, version=VersionStamp(revision=1, etag=etag(body)))


def _context() -> CommandContext:
    return CommandContext.model_validate(
        {
            "command_id": "command_" + _UUID.format(0x02),
            "receipt_id": "receipt_" + _UUID.format(0x03),
            "error_id": "error_" + _UUID.format(0x04),
            "idempotency_key": "idem_0123456789abcdefghijkA",
            "event_id": "event_" + _UUID.format(0x06),
            "stream_id": "stream_" + _UUID.format(0x07),
            "producer": {
                "epoch_id": "prodepoch_" + _UUID.format(0x08),
                "sequence": 1,
                "content_digest": _DIGEST,
            },
            "aggregate_id": _load("visit.minimal-static.json")["visit_id"],
            "principal": {
                "kind": "researcher",
                "id": "researcher_" + _UUID.format(0x09),
            },
            "recorded_at": "2026-07-21T12:00:00.000000Z",
            "event_data_handling": {"privacy_labels": ["research", "sensitive"]},
        }
    )


async def _seed(store: InMemoryStore, context: CommandContext) -> None:
    """Commit a created visit at revision 1, as a prior start command would."""
    visit = _created_visit()
    await store.commit(
        command_id="command_" + _UUID.format(0x20),
        idempotency_key="idem_0123456789abcdefghijkQ",
        aggregate_id=context.aggregate_id,
        expected_revision=None,
        new_state=visit.model_dump(mode="json", exclude_none=True),
        stream_events=[(context.stream_id, "event_" + _UUID.format(0x21))],
        durability_profile="visit.start",
    )


@pytest.mark.asyncio
async def test_advance_commits_at_the_next_revision() -> None:
    """A legal advance commits the new status at the next revision."""
    store = InMemoryStore()
    context = _context()
    await _seed(store, context)

    command = AdvanceVisitCommand(target_status="in-progress", expected_revision=1)
    receipt = await advance_visit(command, context=context, store=store)

    assert receipt.outcome == "accepted"
    assert receipt.receipt_class == "commit"
    assert receipt.version_stamp is not None
    assert receipt.version_stamp.revision == 2
    assert receipt.stream_positions == {context.stream_id: 2}
    assert receipt.result is not None
    assert receipt.result.data["status"] == "in-progress"
    assert receipt.result.data["revision"] == 2
    assert store.revision_of(context.aggregate_id) == 2


@pytest.mark.asyncio
async def test_advance_rejects_a_stale_revision() -> None:
    """An advance against a superseded revision is rejected with no effect."""
    store = InMemoryStore()
    context = _context()
    await _seed(store, context)
    first = _context()
    await advance_visit(
        AdvanceVisitCommand(target_status="in-progress", expected_revision=1),
        context=first,
        store=store,
    )

    stale = CommandContext.model_validate(
        {
            **context.model_dump(mode="json"),
            "idempotency_key": "idem_stale456789abcdefghijw",
        }
    )
    receipt = await advance_visit(
        AdvanceVisitCommand(target_status="completed", expected_revision=1),
        context=stale,
        store=store,
    )

    assert receipt.outcome == "rejected"
    assert receipt.error is not None
    assert receipt.error.code == "command.revision_conflict"
    # No effect: the visit stays at the revision the first advance set.
    assert store.revision_of(context.aggregate_id) == 2


@pytest.mark.asyncio
async def test_advance_rejects_an_illegal_transition() -> None:
    """A move a created visit does not allow is rejected with no effect."""
    store = InMemoryStore()
    context = _context()
    await _seed(store, context)

    receipt = await advance_visit(
        AdvanceVisitCommand(target_status="completed", expected_revision=1),
        context=context,
        store=store,
    )

    assert receipt.outcome == "rejected"
    assert receipt.error is not None
    assert receipt.error.code == "command.state_conflict"
    assert store.revision_of(context.aggregate_id) == 1


@pytest.mark.asyncio
async def test_advance_rejects_an_absent_visit() -> None:
    """An advance of a visit that was never created is rejected as not found."""
    store = InMemoryStore()
    context = _context()

    receipt = await advance_visit(
        AdvanceVisitCommand(target_status="in-progress", expected_revision=1),
        context=context,
        store=store,
    )

    assert receipt.outcome == "rejected"
    assert receipt.error is not None
    assert receipt.error.code == "resource.not_found"
    assert store.revision_of(context.aggregate_id) is None
