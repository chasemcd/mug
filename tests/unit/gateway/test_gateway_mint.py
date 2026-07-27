"""The gateway derives a trusted context from an untrusted envelope.

These tests drive the gateway with a fixed clock and a counter entropy source, so
the mint is deterministic. They pin the parts that are easy to get wrong: the
minted identifiers validate against their kinds (the context construction
enforces this), the event stream shares the aggregate identifier body, the ticket
handle appears only for a token command, and the producer sequence advances by one
each mint while the epoch stays fixed.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import TypeAdapter

from mug.gateway import Gateway
from mug.kernel import DataHandlingRef, PrincipalRef, PublicHandle, WireCommandEnvelope

_UUID = "019b6000-0000-7000-8000-0000000000{:02x}"
_ENROLLMENT = "enrollment_" + _UUID.format(0x50)
_DIGEST = {"algorithm": "sha-256", "hex": "a" * 64}
_HANDLING = DataHandlingRef(privacy_labels=["research"])
_PRINCIPAL = PrincipalRef(kind="participant", id="participant_" + _UUID.format(0x80))


class _Entropy:
    def __init__(self) -> None:
        self._n = 0

    def __call__(self, size: int) -> bytes:
        self._n += 1
        return bytes([self._n % 256]) * size


def _clock() -> datetime:
    return datetime(2026, 8, 2, 12, 0, 0, tzinfo=timezone.utc)


def _gateway() -> Gateway:
    return Gateway(clock=_clock, entropy=_Entropy())


def _envelope(target: str, data: dict[str, Any]) -> WireCommandEnvelope:
    return WireCommandEnvelope.model_validate(
        {
            "schema": {"name": "mug.command-envelope", "version": 0, "digest": _DIGEST},
            "protocol_version": "0.1.0",
            "command": {"name": "enrollment.enroll", "version": 0},
            "request_id": "request_" + _UUID.format(0x01),
            "idempotency_key": "idem_0123456789abcdefghijkA",
            "target": {"id": target},
            "payload": {
                "schema": {"name": "mug.edge.payload", "version": 0, "digest": _DIGEST},
                "data": data,
            },
        }
    )


def test_mint_derives_a_valid_context() -> None:
    """A mint carries the target aggregate and passes through wire identities."""
    context = _gateway().mint(
        _envelope(_ENROLLMENT, {"study_id": "study_" + _UUID.format(0x01)}),
        principal=_PRINCIPAL,
        data_handling=_HANDLING,
    )
    # The four minted identifiers validate against their kinds; the context would
    # not construct otherwise. The event stream shares the aggregate body.
    assert context.command_id.startswith("command_")
    assert context.aggregate_id == _ENROLLMENT
    assert context.stream_id == "stream_" + _ENROLLMENT.split("_", 1)[1]
    assert context.recorded_at == "2026-08-02T12:00:00.000000Z"
    # The wire supplies the idempotency key and the request id; auth the principal.
    assert context.idempotency_key == "idem_0123456789abcdefghijkA"
    assert context.principal == _PRINCIPAL
    assert context.public_handle is None


def test_mint_issues_a_handle_only_for_a_token_command() -> None:
    """A token command mints a ticket handle; an ordinary command mints none."""
    gateway = _gateway()
    envelope = _envelope(_ENROLLMENT, {"study_id": "study_" + _UUID.format(0x01)})
    assert (
        gateway.mint(
            envelope, principal=_PRINCIPAL, data_handling=_HANDLING, issue_handle=True
        ).public_handle
        is not None
    )
    assert (
        gateway.mint(
            envelope, principal=_PRINCIPAL, data_handling=_HANDLING, issue_handle=False
        ).public_handle
        is None
    )


def test_gateway_mints_distinct_transient_public_handles() -> None:
    """A transient room capability uses the kernel public-handle format."""
    gateway = _gateway()
    first = gateway.new_handle()
    second = gateway.new_handle()

    assert TypeAdapter(PublicHandle).validate_python(first) == first
    assert first != second


def test_mint_advances_the_producer_sequence() -> None:
    """The producer epoch is fixed and its sequence advances by one each mint."""
    gateway = _gateway()
    envelope = _envelope(_ENROLLMENT, {"study_id": "study_" + _UUID.format(0x01)})
    first = gateway.mint(envelope, principal=_PRINCIPAL, data_handling=_HANDLING)
    second = gateway.mint(envelope, principal=_PRINCIPAL, data_handling=_HANDLING)
    assert first.producer.epoch_id == second.producer.epoch_id
    assert second.producer.sequence == first.producer.sequence + 1


def test_mint_content_addresses_the_command_identifiers() -> None:
    """The same key and payload re-mint the identical command, receipt, and event.

    The identifiers are derived from the client idempotency key and the payload,
    so a retry reproduces them and the store recognizes the replay (NS-10). The
    epoch sequence still advances, but that field never enters the idempotency
    fingerprint.
    """
    gateway = _gateway()
    envelope = _envelope(_ENROLLMENT, {"study_id": "study_" + _UUID.format(0x01)})
    first = gateway.mint(
        envelope, principal=_PRINCIPAL, data_handling=_HANDLING, issue_handle=True
    )
    retry = gateway.mint(
        envelope, principal=_PRINCIPAL, data_handling=_HANDLING, issue_handle=True
    )
    assert retry.command_id == first.command_id
    assert retry.receipt_id == first.receipt_id
    assert retry.error_id == first.error_id
    assert retry.event_id == first.event_id
    assert retry.public_handle == first.public_handle


def test_mint_derives_distinct_identifiers_for_a_different_payload() -> None:
    """The same key with a different payload mints a different command identity.

    So a conflicting payload under a live key reaches the store with a different
    fingerprint and is rejected, rather than replaying the first command.
    """
    gateway = _gateway()
    first = gateway.mint(
        _envelope(_ENROLLMENT, {"study_id": "study_" + _UUID.format(0x01)}),
        principal=_PRINCIPAL,
        data_handling=_HANDLING,
    )
    other = gateway.mint(
        _envelope(_ENROLLMENT, {"study_id": "study_" + _UUID.format(0x02)}),
        principal=_PRINCIPAL,
        data_handling=_HANDLING,
    )
    assert other.command_id != first.command_id
    assert other.event_id != first.event_id
