"""Behavior of the visits start handler and its cross-aggregate read.

These tests drive ``start_visit`` against the in-memory store. Starting a visit
first reads the enrollment aggregate that a sibling family owns: an active
enrollment lets the visit open at revision 1, an absent enrollment rejects as not
found, and an inactive enrollment rejects with a state conflict. A replay of the
same start has no second effect. The enrollment is seeded straight into the store,
as a prior enrol command would leave it; the visit reference data comes from the
frozen minimal fixture, whose enrollment id matches the seeded enrollment.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from mug.runtime import CommandContext
from mug.storage import InMemoryStore
from mug.visits import StartVisitCommand, Visit, start_visit

_ROOT = Path(__file__).resolve().parents[3] / "docs/architecture/phase-0"
_VISIT_FIXTURES = _ROOT / "api-04/fixtures/v0/valid"
_ENROLLMENT_FIXTURES = _ROOT / "api-03/fixtures/v0/valid"
_UUID = "019b6000-0000-7000-8000-0000000000{:02x}"
_DIGEST = {"algorithm": "sha-256", "hex": "a" * 64}


def _visit_fixture() -> dict[str, Any]:
    return json.loads(
        (_VISIT_FIXTURES / "visit.minimal-static.json").read_text(encoding="utf-8")
    )


def _context() -> CommandContext:
    fixture = _visit_fixture()
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
            "aggregate_id": fixture["visit_id"],
            "principal": {
                "kind": "participant",
                "id": "participant_" + _UUID.format(0x80),
            },
            "recorded_at": "2026-08-02T12:00:00.000000Z",
            "event_data_handling": {"privacy_labels": ["research", "sensitive"]},
        }
    )


def _command() -> StartVisitCommand:
    fixture = _visit_fixture()
    return StartVisitCommand(
        enrollment_id=fixture["enrollment_id"],
        study_id=fixture["study_id"],
        study_version=fixture["study_version"],
        deployment=fixture["deployment"],
    )


async def _seed_enrollment(store: InMemoryStore, *, status: str = "active") -> None:
    """Commit the enrollment aggregate, as a prior enrol command would leave it."""
    enrollment = json.loads(
        (_ENROLLMENT_FIXTURES / "enrollment.minimal-static.json").read_text(
            encoding="utf-8"
        )
    )
    enrollment["status"] = status
    await store.commit(
        command_id="command_" + _UUID.format(0x40),
        idempotency_key="idem_0123456789abcdefghijkQ",
        aggregate_id=enrollment["enrollment_id"],
        expected_revision=None,
        new_state=enrollment,
        stream_events=[("stream_" + _UUID.format(0x41), "event_" + _UUID.format(0x42))],
        durability_profile="enrollment.enroll",
    )


@pytest.mark.asyncio
async def test_start_commits_a_created_visit() -> None:
    """An active enrollment lets a visit open at its first revision."""
    store = InMemoryStore()
    context = _context()
    await _seed_enrollment(store)

    receipt = await start_visit(_command(), context=context, store=store)

    assert receipt.outcome == "accepted"
    assert receipt.receipt_class == "commit"
    assert receipt.version_stamp is not None
    assert receipt.version_stamp.revision == 1
    assert receipt.stream_positions == {context.stream_id: 1}
    assert receipt.result is not None
    assert receipt.result.data["outcome"] == "started"
    assert receipt.result.data["status"] == "created"
    assert receipt.result.data["revision"] == 1
    assert store.revision_of(context.aggregate_id) == 1
    # The persisted state is a valid created visit.
    stored = Visit.model_validate(store.load_aggregate(context.aggregate_id))
    assert stored.status == "created"


@pytest.mark.asyncio
async def test_start_rejects_an_absent_enrollment() -> None:
    """A visit for an enrollment that does not exist is rejected as not found."""
    store = InMemoryStore()
    context = _context()

    receipt = await start_visit(_command(), context=context, store=store)

    assert receipt.outcome == "rejected"
    assert receipt.error is not None
    assert receipt.error.code == "resource.not_found"
    assert store.revision_of(context.aggregate_id) is None


@pytest.mark.asyncio
async def test_start_rejects_an_inactive_enrollment() -> None:
    """A visit for a withdrawn enrollment is rejected with no effect."""
    store = InMemoryStore()
    context = _context()
    await _seed_enrollment(store, status="withdrawn")

    receipt = await start_visit(_command(), context=context, store=store)

    assert receipt.outcome == "rejected"
    assert receipt.error is not None
    assert receipt.error.code == "command.state_conflict"
    assert store.revision_of(context.aggregate_id) is None


@pytest.mark.asyncio
async def test_start_is_idempotent_on_replay() -> None:
    """A replay of the same start command has no second effect."""
    store = InMemoryStore()
    context = _context()
    await _seed_enrollment(store)
    command = _command()
    await start_visit(command, context=context, store=store)

    again = await start_visit(command, context=context, store=store)

    assert again.outcome == "accepted"
    assert again.version_stamp is not None
    assert again.version_stamp.revision == 1
    assert again.stream_positions == {context.stream_id: 1}
    assert store.revision_of(context.aggregate_id) == 1
