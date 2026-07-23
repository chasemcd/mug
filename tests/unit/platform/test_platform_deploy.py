"""Behavior of the platform deploy handler on the shared runtime spine.

These tests drive ``deploy`` against the in-memory store: the satisfied path that
mints a revision and commits, the unsatisfied path that rejects with a report and
no effect, and idempotent replay. The bindings come from the frozen minimal
revision fixture, which satisfies the frozen minimal requirement exactly.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from mug.platform import DeployCommand, deploy
from mug.runtime import CommandContext
from mug.storage import InMemoryStore

_FIXTURES = (
    Path(__file__).resolve().parents[3]
    / "docs/architecture/phase-0/api-02/fixtures/v0/valid"
)
_UUID = "019b6000-0000-7000-8000-0000000000{:02x}"
_DIGEST = {"algorithm": "sha-256", "hex": "a" * 64}


def _load(name: str) -> dict[str, Any]:
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


def _command(*, satisfied: bool = True) -> DeployCommand:
    revision = _load("deployment-revision.minimal-static.json")
    requirement = _load("deployment-requirement.minimal-static.json")
    return DeployCommand.model_validate(
        {
            "deployment_id": revision["deployment_id"],
            "revision_number": revision["revision_number"],
            "study_version": revision["study_version"],
            "requirement": {"data": requirement["data"]},
            "server_build": revision["server_build"],
            "client_builds": revision["client_builds"],
            "execution_bindings": revision["execution_bindings"],
            "provider_bindings": revision["provider_bindings"],
            # Dropping the secret binding leaves a required secret unbound.
            "secret_bindings": revision["secret_bindings"] if satisfied else [],
            "region": revision["region"],
            "endpoints": revision["endpoints"],
            "data_handling": revision["server_build"]["data_handling"],
        }
    )


def _context() -> CommandContext:
    revision = _load("deployment-revision.minimal-static.json")
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
            "aggregate_id": revision["deployment_revision_id"],
            "principal": {
                "kind": "researcher",
                "id": "researcher_" + _UUID.format(0x09),
            },
            "recorded_at": "2026-07-18T12:00:00.000000Z",
            "event_data_handling": revision["server_build"]["data_handling"],
        }
    )


@pytest.mark.asyncio
async def test_deploy_mints_a_revision_and_commits() -> None:
    """A satisfied deploy mints a revision and returns a commit receipt."""
    store = InMemoryStore()
    context = _context()

    receipt = await deploy(_command(), context=context, store=store)

    assert receipt.outcome == "accepted"
    assert receipt.receipt_class == "commit"
    assert receipt.stream_positions == {context.stream_id: 1}
    assert receipt.version_stamp is not None
    assert receipt.version_stamp.revision == 1
    assert receipt.result is not None
    assert receipt.result.data["satisfied"] is True
    revision = receipt.result.data["deployment_revision"]
    assert revision["deployment_revision_id"] == context.aggregate_id
    assert store.revision_of(context.aggregate_id) == 1
    assert store.stream_head(context.stream_id) == 1


@pytest.mark.asyncio
async def test_deploy_rejects_unsatisfied_bindings() -> None:
    """An unsatisfied deploy is rejected with a report and no effect."""
    store = InMemoryStore()
    context = _context()

    receipt = await deploy(_command(satisfied=False), context=context, store=store)

    assert receipt.outcome == "rejected"
    assert receipt.error is not None
    assert receipt.error.code == "command.state_conflict"
    assert receipt.error.details is not None
    assert receipt.error.details.data["satisfied"] is False
    unbound = receipt.error.details.data["unbound_secret_requirements"]
    assert "chat-provider-key" in unbound
    # No effect: nothing committed, the stream stays empty.
    assert store.revision_of(context.aggregate_id) is None
    assert store.stream_head(context.stream_id) == 0


@pytest.mark.asyncio
async def test_deploy_replay_is_idempotent() -> None:
    """A replay of the same deploy has no second effect and reports one position."""
    store = InMemoryStore()
    context = _context()

    first = await deploy(_command(), context=context, store=store)
    again = await deploy(_command(), context=context, store=store)

    assert first.outcome == "accepted"
    assert again.outcome == "accepted"
    assert again.stream_positions == {context.stream_id: 1}
    assert store.revision_of(context.aggregate_id) == 1
    assert store.stream_head(context.stream_id) == 1
