"""Every backend satisfies the Store Protocol with identical semantics.

Each scenario runs against the in-memory backend, the sqlite backend, and -- when
``MUG_PG_DSN`` names a reachable database -- the Postgres backend, so the backends
never drift on receipts, idempotent replay, the revision and existence guards,
fencing, tokens, positions, the event ledger, the object store, or the outbox.

The Postgres backend needs a live database; set ``MUG_PG_DSN`` to run it. Without
that variable the Postgres scenarios skip and the other two still run.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

import pytest
import pytest_asyncio

from mug.kernel import DataHandlingRef
from mug.storage import (
    ArtifactStaging,
    InMemoryStore,
    OutboxRecord,
    SqliteStore,
    StorageError,
    Store,
    digest_of,
)

if TYPE_CHECKING:
    from mug.storage.pg_store import PgStore

    _AnyStore = InMemoryStore | SqliteStore | PgStore

_UUID = "019b6000-0000-7000-8000-0000000000{:02x}"
_STREAM = "stream_" + _UUID.format(0x07)
_DETAIL = {
    "producer_position": {
        "epoch_id": "prodepoch_" + _UUID.format(0x08),
        "sequence": 1,
        "content_digest": {"algorithm": "sha-256", "hex": "b" * 64},
    },
    "event_schema": {
        "name": "mug.test.result",
        "version": 0,
        "digest": {"algorithm": "sha-256", "hex": "a" * 64},
    },
    "payload_digest": {"algorithm": "sha-256", "hex": "c" * 64},
    "recorded_at": "2026-08-02T12:00:00.000000Z",
    "data_handling": {"privacy_labels": ["research"]},
    "causation_event_id": None,
}

_KINDS = ["in_memory", "sqlite", "pg"]


@pytest_asyncio.fixture(params=_KINDS)
async def store(request: pytest.FixtureRequest) -> AsyncIterator[_AnyStore]:
    """Yield a fresh backend of the parametrized kind, ready and isolated."""
    kind: str = request.param
    if kind == "in_memory":
        yield InMemoryStore()
    elif kind == "sqlite":
        yield SqliteStore()
    else:
        dsn = os.environ.get("MUG_PG_DSN")
        if not dsn:
            pytest.skip("MUG_PG_DSN is not set; skipping the Postgres backend")
        pytest.importorskip("asyncpg")
        from mug.storage.pg_store import PgStore

        backend = await PgStore.create(dsn)
        try:
            yield backend
        finally:
            await backend.aclose()


async def _commit(
    store: Store,
    *,
    aggregate: str,
    key: str,
    event: str,
    gen: int | None = None,
    expected: int | None = None,
) -> Any:
    return await store.commit(
        command_id="command_" + _UUID.format(0x02),
        idempotency_key=key,
        aggregate_id=aggregate,
        expected_revision=expected,
        new_state={"id": aggregate},
        stream_events=[(_STREAM, event)],
        event_details={event: _DETAIL},
        producer_generation=gen,
        durability_profile="test.commit",
    )


@pytest.mark.asyncio
async def test_commit_replay_and_conflicts(store: _AnyStore) -> None:
    agg = "visit_" + _UUID.format(0x11)
    first = await _commit(
        store,
        aggregate=agg,
        key="idem_0123456789abcdefghijkA",
        event="event_" + _UUID.format(0x61),
    )
    assert first.aggregate_version.revision == 1
    assert store.revision_of(agg) == 1
    assert store.positions_for("idem_0123456789abcdefghijkA") == {_STREAM: 1}
    assert store.load_aggregate(agg) == {"id": agg}

    # Replay: same key and content returns the original receipt, no new event.
    replay = await _commit(
        store,
        aggregate=agg,
        key="idem_0123456789abcdefghijkA",
        event="event_" + _UUID.format(0x61),
    )
    assert replay.aggregate_version.revision == 1
    assert store.stream_head(_STREAM) == 1

    # A second create for the same aggregate under a new key conflicts.
    with pytest.raises(StorageError) as exists:
        await _commit(
            store,
            aggregate=agg,
            key="idem_0123456789abcdefghijkQ",
            event="event_" + _UUID.format(0x62),
        )
    assert exists.value.code == "resource.already_exists"


@pytest.mark.asyncio
async def test_fencing_and_ledger(store: _AnyStore) -> None:
    await _commit(
        store,
        aggregate="visit_" + _UUID.format(0x11),
        key="idem_0123456789abcdefghijkA",
        event="event_" + _UUID.format(0x61),
        gen=2,
    )
    with pytest.raises(StorageError) as fenced:
        await _commit(
            store,
            aggregate="visit_" + _UUID.format(0x12),
            key="idem_0123456789abcdefghijkQ",
            event="event_" + _UUID.format(0x62),
            gen=1,
        )
    assert fenced.value.code == "lease.stale_generation"

    records = store.stream_records(_STREAM)
    assert [r["sequence"] for r in records] == [1]
    assert records[0]["event_schema"]["name"] == "mug.test.result"


@pytest.mark.asyncio
async def test_token_issue_and_reuse(store: _AnyStore) -> None:
    handle = "handle_AAAAAAAAAAAAAAAAAAAAAA"
    positions = await store.issue_token(
        command_id="command_" + _UUID.format(0x02),
        idempotency_key="idem_0123456789abcdefghijkA",
        handle=handle,
        new_state={"ticket_handle": handle},
        stream_events=[(_STREAM, "event_" + _UUID.format(0x61))],
        event_details={"event_" + _UUID.format(0x61): _DETAIL},
    )
    assert positions == {_STREAM: 1}
    assert store.load_token(handle) == {"ticket_handle": handle}

    with pytest.raises(StorageError) as reuse:
        await store.issue_token(
            command_id="command_" + _UUID.format(0x0A),
            idempotency_key="idem_0123456789abcdefghijkQ",
            handle=handle,
            new_state={"ticket_handle": handle},
            stream_events=[(_STREAM, "event_" + _UUID.format(0x62))],
        )
    assert reuse.value.code == "resource.already_exists"


@pytest.mark.asyncio
async def test_object_store_and_outbox(store: _AnyStore) -> None:
    data = b"artifact-bytes"
    staging = ArtifactStaging(
        upload_id="upload_" + _UUID.format(0x20),
        intended_digest=digest_of(data),
        size_bytes=len(data),
        media_type="application/octet-stream",
        data_handling=DataHandlingRef(privacy_labels=["research"]),
    )
    artifact = "artifact_" + _UUID.format(0x21)
    finalized = await store.finalize_artifact(
        staging, data, artifact_id=artifact, finalized_at="2026-08-02T12:00:00.000000Z"
    )
    assert finalized.artifact.digest == finalized.intended_digest
    assert await store.read_artifact(artifact) == data

    # A digest mismatch never finalizes; the object stays absent.
    absent = "artifact_" + _UUID.format(0x22)
    with pytest.raises(StorageError) as bad:
        await store.finalize_artifact(
            staging,
            b"artifact-bytez",
            artifact_id=absent,
            finalized_at="2026-08-02T12:00:00.000000Z",
        )
    assert bad.value.code == "artifact.integrity_failed"
    with pytest.raises(StorageError) as missing:
        await store.read_artifact(absent)
    assert missing.value.code == "artifact.unavailable"

    # A commit persists its outbox entries and flags the receipt.
    record = OutboxRecord(
        command_id="command_" + _UUID.format(0x02), destination="event-bus"
    )
    receipt = await store.commit(
        command_id="command_" + _UUID.format(0x0C),
        idempotency_key="idem_0123456789abcdefghijkg",
        aggregate_id="visit_" + _UUID.format(0x31),
        expected_revision=None,
        new_state={"id": "visit"},
        stream_events=[(_STREAM, "event_" + _UUID.format(0x62))],
        event_details={"event_" + _UUID.format(0x62): _DETAIL},
        outbox=[record],
        durability_profile="test.commit",
    )
    assert receipt.outbox_included is True
    assert store.outbox_records() == (record,)
