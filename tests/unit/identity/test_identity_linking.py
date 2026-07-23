"""Behavior of the external identity blinding and the link handler.

The blinding maps an external subject id to an opaque public handle: the same id
always blinds to the same handle (so a link round-trips), the handle does not
reveal the id, and two providers with a shared raw id blind apart. The
``link_identity`` handler records the ``ExternalIdentityLink`` token keyed by the
blinded handle: a live link redeems to the record, a replay has no second effect,
and a command whose handle does not match its token handle is refused.
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from mug.identity import (
    ExternalIdentityLink,
    LinkIdentityCommand,
    blind_external_id,
    link_identity,
)
from mug.identity.linking import BLINDED_PROVIDERS
from mug.kernel import DataHandlingRef
from mug.runtime import CommandContext
from mug.storage import InMemoryStore

_KEY = b"a-server-blinding-key-of-some-length"
_UUID = "019b6000-0000-7000-8000-0000000000{:02x}"
_HANDLE_PATTERN = re.compile(r"^handle_[A-Za-z0-9_-]{21}[AQgw]$")
_DIGEST = {"algorithm": "sha-256", "hex": "a" * 64}


def test_blinding_is_a_valid_public_handle() -> None:
    """A blinded id is a well-formed public handle."""
    handle = blind_external_id(_KEY, "prolific", "60fd1a2b3c4d5e6f7a8b9c0d")
    assert _HANDLE_PATTERN.match(handle)


def test_blinding_is_deterministic() -> None:
    """The same provider and id always blind to the same handle."""
    first = blind_external_id(_KEY, "prolific", "participant-42")
    second = blind_external_id(_KEY, "prolific", "participant-42")
    assert first == second


def test_blinding_is_provider_scoped() -> None:
    """A shared raw id blinds apart under two providers."""
    prolific = blind_external_id(_KEY, "prolific", "shared-id")
    oidc = blind_external_id(_KEY, "oidc", "shared-id")
    assert prolific != oidc


def test_blinding_is_key_scoped() -> None:
    """A different server key blinds the same id to a different handle."""
    one = blind_external_id(_KEY, "prolific", "participant-42")
    other = blind_external_id(
        b"a-different-server-key-value", "prolific", "participant-42"
    )
    assert one != other


def test_blinding_hides_the_external_id() -> None:
    """The external id does not appear in its blinded handle."""
    external = "60fd1a2b3c4d5e6f7a8b9c0d"
    handle = blind_external_id(_KEY, "prolific", external)
    assert external not in handle


def test_blinding_rejects_an_unknown_provider() -> None:
    """A provider outside the enum is refused."""
    with pytest.raises(ValueError, match="unknown external identity provider"):
        blind_external_id(_KEY, "facebook", "id")


def test_all_providers_blind() -> None:
    """Every link provider blinds to a valid handle."""
    for provider in BLINDED_PROVIDERS:
        assert _HANDLE_PATTERN.match(blind_external_id(_KEY, provider, "id"))


def _context(handle: str) -> CommandContext:
    enrollment_id = "enrollment_" + _UUID.format(0x50)
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
            "aggregate_id": enrollment_id,
            "public_handle": handle,
            "principal": {
                "kind": "researcher",
                "id": "researcher_" + _UUID.format(0x80),
            },
            "recorded_at": "2026-08-02T12:00:00.000000Z",
            "event_data_handling": {"privacy_labels": ["research", "pii"]},
        }
    )


def _command(handle: str) -> LinkIdentityCommand:
    return LinkIdentityCommand(
        enrollment_id="enrollment_" + _UUID.format(0x50),
        provider="prolific",
        external_subject_handle=handle,
        data_handling=DataHandlingRef(privacy_labels=["research", "pii"]),
    )


@pytest.mark.asyncio
async def test_link_records_the_blinded_handle() -> None:
    """A link issues a token keyed by the blinded handle with no version stamp."""
    store = InMemoryStore()
    handle = blind_external_id(_KEY, "prolific", "participant-42")
    context = _context(handle)

    receipt = await link_identity(_command(handle), context=context, store=store)

    assert receipt.outcome == "accepted"
    assert receipt.receipt_class == "commit"
    assert receipt.version_stamp is None
    stored: dict[str, Any] | None = store.load_token(handle)
    assert stored is not None
    link = ExternalIdentityLink.model_validate(stored)
    assert link.external_subject_handle == handle
    assert link.enrollment_id == context.aggregate_id
    assert "pii" in link.data_handling.privacy_labels


@pytest.mark.asyncio
async def test_link_is_idempotent_on_replay() -> None:
    """A replay of the same link has no second effect."""
    store = InMemoryStore()
    handle = blind_external_id(_KEY, "prolific", "participant-42")
    context = _context(handle)
    command = _command(handle)
    await link_identity(command, context=context, store=store)

    again = await link_identity(command, context=context, store=store)

    assert again.outcome == "accepted"
    assert again.stream_positions == {context.stream_id: 1}


@pytest.mark.asyncio
async def test_link_refuses_a_mismatched_handle() -> None:
    """A command whose handle differs from the token handle is refused."""
    store = InMemoryStore()
    handle = blind_external_id(_KEY, "prolific", "participant-42")
    other = blind_external_id(_KEY, "prolific", "someone-else")
    context = _context(handle)

    receipt = await link_identity(_command(other), context=context, store=store)

    assert receipt.outcome == "rejected"
    assert receipt.error is not None
    assert receipt.error.code == "protocol.invalid_envelope"
    assert store.load_token(handle) is None
