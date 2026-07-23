"""The Postgres backend keeps its data across a restart.

``PgStore.open`` is the deployable factory: it bootstraps the schema when it is
absent and reuses it otherwise, so committed state survives a process restart.
This test commits an aggregate, closes the store without dropping the schema,
reopens it, and reads the state back. The Postgres backend needs a live database;
set ``MUG_PG_DSN`` to run this, otherwise it skips.
"""

from __future__ import annotations

import os

import pytest

_UUID = "019b6000-0000-7000-8000-0000000000{:02x}"
_STREAM = "stream_" + _UUID.format(0x07)
_AGG = "visit_" + _UUID.format(0x21)
_KEY = "idem_0123456789abcdefghijkA"
_EVENT = "event_" + _UUID.format(0x71)
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


@pytest.mark.asyncio
async def test_open_keeps_committed_state_across_a_restart() -> None:
    dsn = os.environ.get("MUG_PG_DSN")
    if not dsn:
        pytest.skip("MUG_PG_DSN is not set; skipping the Postgres backend")
    pytest.importorskip("asyncpg")
    from mug.storage.pg_store import PgStore

    # A clean schema to start, then a commit, then close WITHOUT dropping.
    first = await PgStore.create(dsn)
    try:
        await first.commit(
            command_id="command_" + _UUID.format(0x02),
            idempotency_key=_KEY,
            aggregate_id=_AGG,
            expected_revision=None,
            new_state={"id": _AGG},
            stream_events=[(_STREAM, _EVENT)],
            event_details={_EVENT: _DETAIL},
            producer_generation=None,
            durability_profile="test.commit",
        )
        assert first.load_aggregate(_AGG) == {"id": _AGG}
    finally:
        await first.close()

    # Reopen the same database: the state and the ledger are still there.
    resumed = await PgStore.open(dsn)
    try:
        assert resumed.load_aggregate(_AGG) == {"id": _AGG}
        assert resumed.revision_of(_AGG) == 1
        assert len(resumed.stream_records(_STREAM)) == 1
        assert resumed.positions_for(_KEY) == {_STREAM: 1}
    finally:
        await resumed.aclose()
