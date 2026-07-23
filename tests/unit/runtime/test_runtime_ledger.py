"""Canonical event-envelope materialization from the store ledger.

Each committed command appends one event; the store keeps its raw fields with
the position it assigns. ``read_ledger`` wraps those records into ordered
``EventEnvelope`` objects. A read after a sequence returns only later events.
"""

from __future__ import annotations

import pytest

from mug.kernel import CommandTypeRef, Digest, SchemaRef, TypedObject
from mug.runtime import CommandContext, commit_command, read_ledger
from mug.storage import InMemoryStore

_UUID = "019b6000-0000-7000-8000-0000000000{:02x}"
_STREAM = "stream_" + _UUID.format(0x07)
_EPOCH = "prodepoch_" + _UUID.format(0x08)
_KEY = "idem_0123456789abcdefghij{}"
_RESULT = TypedObject(
    schema=SchemaRef(
        name="mug.test.result",
        version=0,
        digest=Digest(algorithm="sha-256", hex="a" * 64),
    ),
    data={},
)


def _context(*, aggregate: str, key: str, event: str) -> CommandContext:
    return CommandContext.model_validate(
        {
            "command_id": "command_" + _UUID.format(0x02),
            "receipt_id": "receipt_" + _UUID.format(0x03),
            "error_id": "error_" + _UUID.format(0x04),
            "idempotency_key": key,
            "event_id": event,
            "stream_id": _STREAM,
            "producer": {
                "epoch_id": _EPOCH,
                "sequence": 1,
                "content_digest": {"algorithm": "sha-256", "hex": "b" * 64},
            },
            "aggregate_id": aggregate,
            "principal": {
                "kind": "researcher",
                "id": "researcher_" + _UUID.format(0x09),
            },
            "recorded_at": "2026-08-02T12:00:00.000000Z",
            "event_data_handling": {"privacy_labels": ["research"]},
        }
    )


async def _write(store: InMemoryStore, *, aggregate: str, key: str, event: str) -> None:
    await commit_command(
        _context(aggregate=aggregate, key=key, event=event),
        command=CommandTypeRef(name="test.write", version=0),
        new_state={"id": aggregate},
        result=_RESULT,
        store=store,
    )


@pytest.mark.asyncio
async def test_ledger_materializes_ordered_envelopes() -> None:
    """Two commits on a stream materialize two envelopes in sequence order."""
    store = InMemoryStore()
    first_event = "event_" + _UUID.format(0x61)
    second_event = "event_" + _UUID.format(0x62)
    await _write(
        store, aggregate="visit_" + _UUID.format(0x11), key=_KEY.format("kA"),
        event=first_event,
    )
    await _write(
        store, aggregate="visit_" + _UUID.format(0x12), key=_KEY.format("kQ"),
        event=second_event,
    )

    envelopes = read_ledger(store, _STREAM)

    assert [e.stream_position.sequence for e in envelopes] == [1, 2]
    assert [e.event_id for e in envelopes] == [first_event, second_event]
    head = envelopes[0]
    assert head.stream_position.stream_id == _STREAM
    assert head.producer_position.epoch_id == _EPOCH
    assert head.event_schema.name == "mug.test.result"
    assert head.payload_digest.algorithm == "sha-256"
    assert head.data_handling.privacy_labels == ["research"]


@pytest.mark.asyncio
async def test_ledger_read_after_a_sequence_skips_earlier_events() -> None:
    """A read after sequence 1 returns only the later event."""
    store = InMemoryStore()
    await _write(
        store, aggregate="visit_" + _UUID.format(0x11), key=_KEY.format("kA"),
        event="event_" + _UUID.format(0x61),
    )
    await _write(
        store, aggregate="visit_" + _UUID.format(0x12), key=_KEY.format("kQ"),
        event="event_" + _UUID.format(0x62),
    )

    later = read_ledger(store, _STREAM, after_sequence=1)

    assert len(later) == 1
    assert later[0].stream_position.sequence == 2
