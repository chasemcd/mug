"""Behavior of the authoring publish handler: the runtime spine end to end.

These tests drive ``publish_study`` against the in-memory store. They assert the
whole spine: the gate, the minted stream position, the atomic commit, the durable
commit-class receipt, idempotent replay, and the rejected, no-effect path.

The valid sub-objects come from the frozen minimal published-version fixture, so
the test builds real records, not hand-waved ones.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from mug.authoring import PublishStudyCommand, publish_study
from mug.runtime import CommandContext
from mug.storage import InMemoryStore

_FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "docs/architecture/phase-0/api-01/fixtures/v0/valid"
    / "published-version.minimal-static.json"
)

_UUID = "019b6000-0000-7000-8000-0000000006{:02x}"
_DIGEST = {"algorithm": "sha-256", "hex": "a" * 64}

_COMPILER = {
    "name": "mug-study-compiler",
    "version": "0.1.0",
    "artifact_digest": {"algorithm": "sha-256", "hex": "b" * 64},
    "contract": {
        "name": "mug.study.compiler-contract",
        "version": 0,
        "digest": _DIGEST,
    },
    "normalization_profile": "mug-normalization-v0",
}
_POLICY = {
    "unknown_fields": "reject",
    "warnings": "reject",
    "executable_content": "packaged_only",
    "hermetic_build": "required",
    "reproducibility_check": "required",
    "client_disclosure_check": "required",
}


def _version() -> dict[str, Any]:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


def _candidate(version: dict[str, Any], eligibility: str) -> dict[str, Any]:
    return {
        "input_fingerprint": _DIGEST,
        "inputs": {
            "git_provenance": version["git_provenance"],
            "source": version["candidate"],
            "compiler": _COMPILER,
            "schema_registry_digest": _DIGEST,
            "build_context_digest": _DIGEST,
            "target_platform_contract": _COMPILER["contract"],
            "compilation_policy": _POLICY,
        },
        "manifest_set": version["scientific"],
        "validation_report": version["candidate"],
        "scientific_manifest_digest": version["study_version"]["manifest_digest"],
        "release_eligibility": eligibility,
    }


def _command(
    version: dict[str, Any], eligibility: str = "release_candidate"
) -> PublishStudyCommand:
    return PublishStudyCommand.model_validate(
        {
            "study_id": version["study_version"]["study_id"],
            "version_number": version["study_version"]["version_number"],
            "version_string": version["version_string"],
            "candidate": _candidate(version, eligibility),
            "candidate_artifact": version["candidate"],
            "git_provenance": version["git_provenance"],
            "scientific": version["scientific"],
            "clients": version["clients"],
            "server": version["server"],
            "provenance": version["provenance"],
            "warning_acknowledgments": version["warning_acknowledgments"],
        }
    )


def _context(version: dict[str, Any]) -> CommandContext:
    return CommandContext.model_validate(
        {
            "command_id": "command_" + _UUID.format(0x02),
            "receipt_id": "receipt_" + _UUID.format(0x03),
            "error_id": "error_" + _UUID.format(0x04),
            "request_id": "request_" + _UUID.format(0x05),
            "idempotency_key": "idem_0123456789abcdefghijkA",
            "event_id": "event_" + _UUID.format(0x06),
            "stream_id": "stream_" + _UUID.format(0x07),
            "producer": {
                "epoch_id": "prodepoch_" + _UUID.format(0x08),
                "sequence": 1,
                "content_digest": _DIGEST,
            },
            "aggregate_id": version["study_version"]["study_version_id"],
            "principal": version["published_by"],
            "recorded_at": version["published_at"],
            "event_data_handling": version["candidate"]["data_handling"],
        }
    )


@pytest.mark.asyncio
async def test_publish_commits_and_returns_a_commit_receipt() -> None:
    """A valid publish commits state and one event, and returns a commit receipt."""
    version = _version()
    store = InMemoryStore()
    context = _context(version)

    receipt = await publish_study(_command(version), context=context, store=store)

    assert receipt.outcome == "accepted"
    assert receipt.receipt_class == "commit"
    assert receipt.durability.receipt == "transactional"
    assert receipt.stream_positions == {context.stream_id: 1}
    assert receipt.version_stamp is not None
    assert receipt.version_stamp.revision == 1
    assert receipt.result is not None
    assert receipt.result.data["outcome"] == "created"
    # The effect is durable: the aggregate exists and the stream advanced by one.
    assert store.revision_of(context.aggregate_id) == 1
    assert store.stream_head(context.stream_id) == 1
    assert store.committed_event_ids() == (context.event_id,)


@pytest.mark.asyncio
async def test_publish_replay_is_idempotent() -> None:
    """A replay of the same command has no second effect and resolves the version."""
    version = _version()
    store = InMemoryStore()
    context = _context(version)

    first = await publish_study(_command(version), context=context, store=store)
    again = await publish_study(_command(version), context=context, store=store)

    assert first.result is not None and first.result.data["outcome"] == "created"
    assert again.outcome == "accepted"
    assert again.result is not None
    assert again.result.data["outcome"] == "resolved_existing"
    # The replay reports the original position, not a recomputed one.
    assert again.stream_positions == {context.stream_id: 1}
    # No second effect: one revision, one stream position, one committed event.
    assert store.revision_of(context.aggregate_id) == 1
    assert store.stream_head(context.stream_id) == 1
    assert store.committed_event_ids() == (context.event_id,)


@pytest.mark.asyncio
async def test_publish_rejects_an_unpublishable_candidate() -> None:
    """An unpublishable candidate is rejected with no effect and a safe error."""
    version = _version()
    store = InMemoryStore()
    context = _context(version)

    receipt = await publish_study(
        _command(version, "design_unpublishable"), context=context, store=store
    )

    assert receipt.outcome == "rejected"
    assert receipt.result is None
    assert receipt.error is not None
    assert receipt.error.code == "command.state_conflict"
    assert receipt.durability.effect == "none"
    # No effect: nothing committed, the stream stays empty.
    assert store.revision_of(context.aggregate_id) is None
    assert store.stream_head(context.stream_id) == 0
