"""Producer-epoch fencing in the store and through the runtime spine.

A producer installs itself on a stream with a strictly greater generation. A
write from a superseded generation is fenced and leaves no effect, while an equal
or greater generation proceeds. The spine turns a fenced write into a rejected
receipt carrying ``lease.stale_generation``.
"""

from __future__ import annotations

import pytest

from mug.kernel import CommandTypeRef, Digest, SchemaRef, TypedObject
from mug.runtime import CommandContext, commit_command
from mug.storage import InMemoryStore, StorageError

_UUID = "019b6000-0000-7000-8000-0000000000{:02x}"
_STREAM = "stream_" + _UUID.format(0x07)
_KEY = "idem_0123456789abcdefghij{}"


async def _commit(
    store: InMemoryStore, *, aggregate: str, key: str, gen: int
) -> None:
    await store.commit(
        command_id="command_" + _UUID.format(0x02),
        idempotency_key=key,
        aggregate_id=aggregate,
        expected_revision=None,
        new_state={"id": aggregate},
        stream_events=[(_STREAM, "event_" + _UUID.format(0x06))],
        producer_generation=gen,
        durability_profile="test.commit",
    )


@pytest.mark.asyncio
async def test_store_fences_a_superseded_generation() -> None:
    """A newer generation installs; an older one is fenced with no effect."""
    store = InMemoryStore()
    first = "visit_" + _UUID.format(0x11)
    await _commit(store, aggregate=first, key=_KEY.format("kA"), gen=2)
    assert store.installed_generation(_STREAM) == 2

    stale = "visit_" + _UUID.format(0x12)
    with pytest.raises(StorageError) as caught:
        await _commit(store, aggregate=stale, key=_KEY.format("kQ"), gen=1)
    assert caught.value.code == "lease.stale_generation"
    # No effect: the fenced aggregate was never written and the head held.
    assert store.revision_of(stale) is None
    assert store.installed_generation(_STREAM) == 2


@pytest.mark.asyncio
async def test_store_admits_an_equal_or_greater_generation() -> None:
    """The same generation continues; a greater one takes over the stream."""
    store = InMemoryStore()
    same = "visit_" + _UUID.format(0x11)
    again = "visit_" + _UUID.format(0x12)
    newer = "visit_" + _UUID.format(0x13)
    await _commit(store, aggregate=same, key=_KEY.format("kA"), gen=3)
    await _commit(store, aggregate=again, key=_KEY.format("kQ"), gen=3)
    await _commit(store, aggregate=newer, key=_KEY.format("kg"), gen=4)
    assert store.installed_generation(_STREAM) == 4


def _context(gen: int, *, aggregate: str, key: str) -> CommandContext:
    epoch = "prodepoch_" + _UUID.format(0x08)
    return CommandContext.model_validate(
        {
            "command_id": "command_" + _UUID.format(0x02),
            "receipt_id": "receipt_" + _UUID.format(0x03),
            "error_id": "error_" + _UUID.format(0x04),
            "idempotency_key": key,
            "event_id": "event_" + _UUID.format(0x06),
            "stream_id": _STREAM,
            "producer": {
                "epoch_id": epoch,
                "sequence": 1,
                "content_digest": {"algorithm": "sha-256", "hex": "a" * 64},
            },
            "fencing": {"epoch_id": epoch, "generation": gen},
            "aggregate_id": aggregate,
            "principal": {
                "kind": "researcher",
                "id": "researcher_" + _UUID.format(0x09),
            },
            "recorded_at": "2026-08-02T12:00:00.000000Z",
            "event_data_handling": {"privacy_labels": ["research"]},
        }
    )


@pytest.mark.asyncio
async def test_spine_rejects_a_fenced_producer() -> None:
    """The spine turns a fenced write into a rejected receipt with no effect."""
    store = InMemoryStore()
    command = CommandTypeRef(name="test.write", version=0)
    result = TypedObject(
        schema=SchemaRef(
            name="mug.test.result",
            version=0,
            digest=Digest(algorithm="sha-256", hex="a" * 64),
        ),
        data={},
    )
    await commit_command(
        _context(2, aggregate="visit_" + _UUID.format(0x11), key=_KEY.format("kA")),
        command=command,
        new_state={"id": "one"},
        result=result,
        store=store,
    )

    fenced = "visit_" + _UUID.format(0x12)
    receipt = await commit_command(
        _context(1, aggregate=fenced, key=_KEY.format("kQ")),
        command=command,
        new_state={"id": "two"},
        result=result,
        store=store,
    )

    assert receipt.outcome == "rejected"
    assert receipt.error is not None
    assert receipt.error.code == "lease.stale_generation"
    assert receipt.error.category == "stale"
    assert store.revision_of(fenced) is None
