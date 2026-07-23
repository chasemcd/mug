"""Behavior of the identity launch handler and the token spine.

These tests drive ``launch`` against the in-memory store. A launch reads the
target deployment through the store, then issues a ``LaunchTicket`` token keyed
by an opaque handle. An active deployment yields a commit receipt with no version
stamp; an absent deployment rejects as not found; a replay has no second effect;
and a reused handle conflicts. The ticket handle, study, and deployment come from
the frozen launch-ticket fixture; the deployment is seeded straight into the store.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from mug.identity import LaunchCommand, LaunchTicket, launch
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
        (_FIXTURES / "launch-ticket.minimal-static.json").read_text(encoding="utf-8")
    )


def _context() -> CommandContext:
    fixture = _fixture()
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
            "aggregate_id": fixture["deployment"]["deployment_revision_id"],
            "public_handle": fixture["ticket_handle"],
            "principal": {
                "kind": "participant",
                "id": "participant_" + _UUID.format(0x80),
            },
            "recorded_at": "2026-08-02T12:00:00.000000Z",
            "event_data_handling": {"privacy_labels": ["research", "sensitive"]},
        }
    )


def _command() -> LaunchCommand:
    fixture = _fixture()
    return LaunchCommand(
        study_id=fixture["study_id"],
        deployment=fixture["deployment"],
        ttl_seconds=3600,
    )


async def _seed_deployment(store: InMemoryStore) -> None:
    """Commit a deployment aggregate, as a prior deploy command would leave it."""
    revision_id = _fixture()["deployment"]["deployment_revision_id"]
    await store.commit(
        command_id="command_" + _UUID.format(0x40),
        idempotency_key="idem_0123456789abcdefghijkQ",
        aggregate_id=revision_id,
        expected_revision=None,
        new_state={"deployment_revision_id": revision_id, "status": "active"},
        stream_events=[("stream_" + _UUID.format(0x41), "event_" + _UUID.format(0x42))],
        durability_profile="platform.deploy",
    )


@pytest.mark.asyncio
async def test_launch_issues_a_ticket() -> None:
    """A live deployment yields a launch ticket token with no version stamp."""
    store = InMemoryStore()
    context = _context()
    await _seed_deployment(store)

    receipt = await launch(_command(), context=context, store=store)

    assert receipt.outcome == "accepted"
    assert receipt.receipt_class == "commit"
    assert receipt.version_stamp is None
    assert receipt.resource is not None
    assert receipt.resource.id == context.aggregate_id
    assert receipt.stream_positions == {context.stream_id: 1}
    assert receipt.result is not None
    assert receipt.result.data["outcome"] == "issued"
    assert receipt.result.data["ticket_handle"] == context.public_handle
    assert receipt.result.data["expires_at"] == "2026-08-02T13:00:00.000000Z"
    # The token is stored under its handle and is a valid launch ticket.
    stored = LaunchTicket.model_validate(store.load_token(_fixture()["ticket_handle"]))
    assert stored.expires_at == "2026-08-02T13:00:00.000000Z"


@pytest.mark.asyncio
async def test_launch_rejects_an_absent_deployment() -> None:
    """A launch for a deployment that does not exist is rejected as not found."""
    store = InMemoryStore()
    context = _context()

    receipt = await launch(_command(), context=context, store=store)

    assert receipt.outcome == "rejected"
    assert receipt.error is not None
    assert receipt.error.code == "resource.not_found"
    assert store.load_token(_fixture()["ticket_handle"]) is None


@pytest.mark.asyncio
async def test_launch_is_idempotent_on_replay() -> None:
    """A replay of the same launch has no second effect."""
    store = InMemoryStore()
    context = _context()
    await _seed_deployment(store)
    command = _command()
    await launch(command, context=context, store=store)

    again = await launch(command, context=context, store=store)

    assert again.outcome == "accepted"
    assert again.stream_positions == {context.stream_id: 1}


@pytest.mark.asyncio
async def test_launch_rejects_a_reused_handle() -> None:
    """A second launch that reuses a live handle conflicts with no effect."""
    store = InMemoryStore()
    context = _context()
    await _seed_deployment(store)
    await launch(_command(), context=context, store=store)

    reuse = CommandContext.model_validate(
        {
            **context.model_dump(mode="json"),
            "idempotency_key": "idem_0123456789abcdefghijkg",
            "command_id": "command_" + _UUID.format(0x0A),
            "event_id": "event_" + _UUID.format(0x0B),
        }
    )
    receipt = await launch(_command(), context=reuse, store=store)

    assert receipt.outcome == "rejected"
    assert receipt.error is not None
    assert receipt.error.code == "resource.already_exists"
