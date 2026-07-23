"""Behavioral tests for the in-memory storage backend.

These prove the contract behavior: content-addressed finalization rejects a
digest or size mismatch, and the Unit of Work commits atomically with optimistic
concurrency and idempotent replay.
"""

from __future__ import annotations

import pytest

from mug.kernel import DataHandlingRef
from mug.storage import (
    ArtifactStaging,
    InMemoryStore,
    OutboxRecord,
    StorageError,
    digest_of,
)

_UPLOAD = "upload_019b6000-0000-7000-8000-000000000720"
_ARTIFACT = "artifact_019b6000-0000-7000-8000-000000000710"
_COMMAND = "command_019b6000-0000-7000-8000-000000000700"
_AGGREGATE = "visit_019b6000-0000-7000-8000-000000000090"
_EVENT = "event_019b6000-0000-7000-8000-000000000601"
_KEY = "idem_7Gg3L2M1qPv9sXr4Nk8BzQ"
_KEY2 = "idem_AAAAAAAAAAAAAAAAAAAAAA"
_AT = "2026-08-02T12:06:00.000000Z"
_PROFILE = "pg-synchronous-commit"


def _staging(data: bytes, *, size: int | None = None) -> ArtifactStaging:
    return ArtifactStaging(
        upload_id=_UPLOAD,
        intended_digest=digest_of(data),
        size_bytes=len(data) if size is None else size,
        media_type="application/octet-stream",
        data_handling=DataHandlingRef(privacy_labels=["research"]),
    )


async def _create(store: InMemoryStore, *, key: str = _KEY) -> None:
    await store.commit(
        command_id=_COMMAND,
        idempotency_key=key,
        aggregate_id=_AGGREGATE,
        expected_revision=None,
        new_state={"step": 1},
        event_ids=[_EVENT],
        durability_profile=_PROFILE,
    )


async def test_finalize_happy_path() -> None:
    store = InMemoryStore()
    data = b"hello world"
    finalized = await store.finalize_artifact(
        _staging(data), data, artifact_id=_ARTIFACT, finalized_at=_AT
    )
    assert finalized.artifact.digest == finalized.intended_digest
    assert await store.read_artifact(_ARTIFACT) == data


async def test_finalize_rejects_digest_mismatch() -> None:
    store = InMemoryStore()
    with pytest.raises(StorageError) as err:
        await store.finalize_artifact(
            _staging(b"intended"), b"different", artifact_id=_ARTIFACT, finalized_at=_AT
        )
    assert err.value.code == "artifact.integrity_failed"


async def test_finalize_rejects_size_mismatch() -> None:
    store = InMemoryStore()
    data = b"1234"
    with pytest.raises(StorageError):
        await store.finalize_artifact(
            _staging(data, size=999), data, artifact_id=_ARTIFACT, finalized_at=_AT
        )


async def test_commit_creates_then_updates() -> None:
    store = InMemoryStore()
    await _create(store)
    assert store.revision_of(_AGGREGATE) == 1
    updated = await store.commit(
        command_id=_COMMAND,
        idempotency_key=_KEY2,
        aggregate_id=_AGGREGATE,
        expected_revision=1,
        new_state={"step": 2},
        event_ids=[_EVENT],
        durability_profile=_PROFILE,
    )
    assert updated.aggregate_version.revision == 2


async def test_idempotent_replay_returns_original_receipt() -> None:
    store = InMemoryStore()
    await _create(store)
    again = await store.commit(
        command_id=_COMMAND,
        idempotency_key=_KEY,
        aggregate_id=_AGGREGATE,
        expected_revision=None,
        new_state={"step": 1},
        event_ids=[_EVENT],
        durability_profile=_PROFILE,
    )
    assert again.aggregate_version.revision == 1
    # No second effect: the revision did not advance and no extra events landed.
    assert store.revision_of(_AGGREGATE) == 1
    assert store.committed_event_ids() == (_EVENT,)


async def test_idempotency_key_reuse_with_different_content_conflicts() -> None:
    store = InMemoryStore()
    await _create(store)
    with pytest.raises(StorageError) as err:
        await store.commit(
            command_id=_COMMAND,
            idempotency_key=_KEY,
            aggregate_id=_AGGREGATE,
            expected_revision=None,
            new_state={"step": 9},
            event_ids=["event_019b6000-0000-7000-8000-000000000602"],
            durability_profile=_PROFILE,
        )
    assert err.value.code == "command.idempotency_conflict"


async def test_stale_expected_revision_conflicts() -> None:
    store = InMemoryStore()
    await _create(store)
    with pytest.raises(StorageError) as err:
        await store.commit(
            command_id=_COMMAND,
            idempotency_key=_KEY2,
            aggregate_id=_AGGREGATE,
            expected_revision=5,
            new_state={"step": 2},
            event_ids=[_EVENT],
            durability_profile=_PROFILE,
        )
    assert err.value.code == "command.revision_conflict"


async def test_create_on_existing_aggregate_conflicts() -> None:
    store = InMemoryStore()
    await _create(store)
    with pytest.raises(StorageError) as err:
        await _create(store, key=_KEY2)
    assert err.value.code == "resource.already_exists"


async def test_commit_includes_outbox() -> None:
    store = InMemoryStore()
    record = OutboxRecord(
        command_id=_COMMAND, destination="event-bus", event_ids=[_EVENT]
    )
    receipt = await store.commit(
        command_id=_COMMAND,
        idempotency_key=_KEY,
        aggregate_id=_AGGREGATE,
        expected_revision=None,
        new_state={"step": 1},
        event_ids=[_EVENT],
        outbox=[record],
        durability_profile=_PROFILE,
    )
    assert receipt.outbox_included is True
    assert store.outbox_records() == (record,)
