"""Two processes mint the same command identity only when they share one secret.

This is the property a deployment of more than one process rests on. A client that
retries a command may land on any process behind the load balancer, and the retry is
idempotent only if every process derives the identical command identity from the
identical envelope. The identity is content-addressed from the idempotency key and
the payload, seeded by the gateway's secret -- so the secret is the deployment-wide
part, and these tests pin both directions of that.

They stand in for a second process by building a second gateway: a gateway holds
nothing else that a process does, so two gateways are two processes for this
purpose.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from mug.gateway import Gateway
from mug.kernel import DataHandlingRef, Digest, PrincipalRef, WireCommandEnvelope
from mug.storage import InMemoryStore, StorageError

_A_DIGEST = Digest(algorithm="sha-256", hex="a" * 64)
_RESEARCH = DataHandlingRef(privacy_labels=["research"])
_PARTICIPANT = PrincipalRef(
    kind="participant", id="participant_019b6000-0000-7000-8000-0000000000aa"
)
_SECRET = b"one deployment-wide secret, shared by every process"


def _clock() -> datetime:
    return datetime(2026, 7, 26, 12, 0, 0, tzinfo=timezone.utc)


def _envelope() -> WireCommandEnvelope:
    """Build one client envelope: the same bytes a retry would send again."""
    return WireCommandEnvelope.model_validate(
        {
            "schema": {
                "name": "mug.command-envelope",
                "version": 0,
                "digest": _A_DIGEST.model_dump(mode="json"),
            },
            "protocol_version": "0.1.0",
            "command": {"name": "visit.start", "version": 0},
            "request_id": "request_019b6000-0000-7000-8000-000000000001",
            "idempotency_key": "idem_0123456789abcdefghijkA",
            "target": {"id": "visit_019b6000-0000-7000-8000-000000000009"},
            "payload": {
                "schema": {
                    "name": "mug.edge.payload",
                    "version": 0,
                    "digest": _A_DIGEST.model_dump(mode="json"),
                },
                "data": {"value": 1},
            },
        }
    )


def _process(secret: bytes | None) -> Gateway:
    """Stand in for one process: a gateway with its own or the shared secret."""
    return Gateway(clock=_clock, secret=secret)


def test_two_processes_sharing_a_secret_mint_one_command_identity() -> None:
    """A retry that lands on another process is the same command, not a new one."""
    first = _process(_SECRET).mint(
        _envelope(), principal=_PARTICIPANT, data_handling=_RESEARCH
    )
    second = _process(_SECRET).mint(
        _envelope(), principal=_PARTICIPANT, data_handling=_RESEARCH
    )

    assert second.command_id == first.command_id
    assert second.receipt_id == first.receipt_id
    assert second.event_id == first.event_id


def test_two_processes_with_their_own_secrets_do_not() -> None:
    """The per-process default is what makes several processes unsafe."""
    first = _process(None).mint(
        _envelope(), principal=_PARTICIPANT, data_handling=_RESEARCH
    )
    second = _process(None).mint(
        _envelope(), principal=_PARTICIPANT, data_handling=_RESEARCH
    )

    assert second.command_id != first.command_id


async def test_a_retry_on_a_second_process_replays_when_the_secret_is_shared() -> None:
    """The store recognizes the retry and gives back the first commit's positions."""
    store = InMemoryStore()
    envelope = _envelope()
    contexts = [
        _process(_SECRET).mint(
            envelope, principal=_PARTICIPANT, data_handling=_RESEARCH
        )
        for _ in range(2)
    ]

    receipts = [
        await store.commit(
            command_id=context.command_id,
            idempotency_key=context.idempotency_key,
            aggregate_id=context.aggregate_id,
            expected_revision=None,
            new_state={"value": 1},
            stream_events=[(context.stream_id, context.event_id)],
            durability_profile="visit.start",
        )
        for context in contexts
    ]

    # The second commit had no effect: it is the first receipt, replayed.
    assert receipts[1] == receipts[0]
    assert store.revision_of(contexts[0].aggregate_id) == 1


async def test_a_retry_on_a_second_process_conflicts_when_it_is_not() -> None:
    """Without a shared secret the retry is refused, which is the failure to avoid.

    The idempotency key is the client's and does not change, but the command identity
    does, so the store sees one key with two contents. Refusing is correct -- the
    fault is the deployment's, not the client's.
    """
    store = InMemoryStore()
    envelope = _envelope()
    contexts = [
        _process(None).mint(envelope, principal=_PARTICIPANT, data_handling=_RESEARCH)
        for _ in range(2)
    ]

    await store.commit(
        command_id=contexts[0].command_id,
        idempotency_key=contexts[0].idempotency_key,
        aggregate_id=contexts[0].aggregate_id,
        expected_revision=None,
        new_state={"value": 1},
        stream_events=[(contexts[0].stream_id, contexts[0].event_id)],
        durability_profile="visit.start",
    )

    with pytest.raises(StorageError) as refused:
        await store.commit(
            command_id=contexts[1].command_id,
            idempotency_key=contexts[1].idempotency_key,
            aggregate_id=contexts[1].aggregate_id,
            expected_revision=None,
            new_state={"value": 1},
            stream_events=[(contexts[1].stream_id, contexts[1].event_id)],
            durability_profile="visit.start",
        )

    assert refused.value.code == "command.idempotency_conflict"


def test_each_process_keeps_its_own_producer_epoch() -> None:
    """Sharing the secret does not merge the producer epochs, and must not.

    A producer position orders one process's writes. Two processes that shared an
    epoch would claim positions in one sequence they cannot coordinate, so each draws
    its own epoch from its own entropy even when the identifier secret is shared.
    """
    first = _process(_SECRET).mint(
        _envelope(), principal=_PARTICIPANT, data_handling=_RESEARCH
    )
    second = _process(_SECRET).mint(
        _envelope(), principal=_PARTICIPANT, data_handling=_RESEARCH
    )

    assert first.producer.epoch_id != second.producer.epoch_id
