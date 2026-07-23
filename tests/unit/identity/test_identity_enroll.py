"""Behavior of the identity enroll handler on the shared runtime spine.

These tests drive ``enroll`` against the in-memory store. A participant enrols in
a study and the handler commits an ``Enrollment`` at its first revision; a replay
of the same command has no second effect; a non-participant actor is refused; and
a second enrol against the same enrollment id conflicts. The enrollment id, the
participant principal, and the study id come from the frozen minimal fixture.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from mug.identity import EnrollCommand, Enrollment, enroll
from mug.runtime import CommandContext
from mug.storage import InMemoryStore

_FIXTURES = (
    Path(__file__).resolve().parents[3]
    / "docs/architecture/phase-0/api-03/fixtures/v0/valid"
)
_UUID = "019b6000-0000-7000-8000-0000000000{:02x}"
_DIGEST = {"algorithm": "sha-256", "hex": "a" * 64}


def _fixture() -> dict[str, Any]:
    return json.loads(
        (_FIXTURES / "enrollment.minimal-static.json").read_text(encoding="utf-8")
    )


def _context(kind: str = "participant") -> CommandContext:
    fixture = _fixture()
    principal = (
        fixture["principal"]
        if kind == "participant"
        else {"kind": "researcher", "id": "researcher_" + _UUID.format(0x09)}
    )
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
            "aggregate_id": fixture["enrollment_id"],
            "principal": principal,
            "recorded_at": "2026-08-02T12:00:00.000000Z",
            "event_data_handling": {"privacy_labels": ["research", "sensitive"]},
        }
    )


@pytest.mark.asyncio
async def test_enroll_commits_a_new_enrollment() -> None:
    """A participant's enrolment commits an active enrollment at revision 1."""
    store = InMemoryStore()
    context = _context()
    command = EnrollCommand(study_id=_fixture()["study_id"])

    receipt = await enroll(command, context=context, store=store)

    assert receipt.outcome == "accepted"
    assert receipt.receipt_class == "commit"
    assert receipt.version_stamp is not None
    assert receipt.version_stamp.revision == 1
    assert receipt.stream_positions == {context.stream_id: 1}
    assert receipt.result is not None
    assert receipt.result.data["status"] == "active"
    assert receipt.result.data["revision"] == 1
    assert store.revision_of(context.aggregate_id) == 1
    # The persisted state is a valid enrollment of a participant.
    stored = Enrollment.model_validate(store.load_aggregate(context.aggregate_id))
    assert stored.principal.kind == "participant"
    assert stored.status == "active"


@pytest.mark.asyncio
async def test_enroll_is_idempotent_on_replay() -> None:
    """A replay of the same enrol command has no second effect."""
    store = InMemoryStore()
    context = _context()
    command = EnrollCommand(study_id=_fixture()["study_id"])
    await enroll(command, context=context, store=store)

    again = await enroll(command, context=context, store=store)

    assert again.outcome == "accepted"
    assert again.version_stamp is not None
    assert again.version_stamp.revision == 1
    assert again.stream_positions == {context.stream_id: 1}
    assert store.revision_of(context.aggregate_id) == 1


@pytest.mark.asyncio
async def test_enroll_rejects_a_nonparticipant_actor() -> None:
    """An actor that is not a participant may not enrol; no effect follows."""
    store = InMemoryStore()
    context = _context(kind="researcher")

    receipt = await enroll(
        EnrollCommand(study_id=_fixture()["study_id"]), context=context, store=store
    )

    assert receipt.outcome == "rejected"
    assert receipt.error is not None
    assert receipt.error.code == "auth.forbidden"
    assert store.revision_of(context.aggregate_id) is None


@pytest.mark.asyncio
async def test_enroll_rejects_a_duplicate_enrollment() -> None:
    """A second enrol against a live enrollment id conflicts with no effect."""
    store = InMemoryStore()
    context = _context()
    command = EnrollCommand(study_id=_fixture()["study_id"])
    await enroll(command, context=context, store=store)

    duplicate = CommandContext.model_validate(
        {
            **context.model_dump(mode="json"),
            "idempotency_key": "idem_0123456789abcdefghijkQ",
        }
    )
    receipt = await enroll(command, context=duplicate, store=store)

    assert receipt.outcome == "rejected"
    assert receipt.error is not None
    assert receipt.error.code == "resource.already_exists"
    # No second effect: the enrollment stays at its first revision.
    assert store.revision_of(context.aggregate_id) == 1
