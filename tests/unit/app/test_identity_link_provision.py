"""The external identity link round-trips through the gateway boundary.

``provision_identity_link`` blinds an external subject id and issues the link
through the real gateway and ``link_identity`` handler. ``resolve_enrollment``
blinds the same id and reads the link back to recover the enrolment. These tests
prove the round-trip, the idempotency of a repeat link, and -- the privacy
invariant -- that the raw external id never lands in a stored record or event.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import pytest

from mug.gateway import Gateway
from mug.kernel import PrincipalRef
from mug.linking import provision_identity_link, resolve_enrollment
from mug.storage import InMemoryStore

_RESEARCHER = PrincipalRef(
    kind="researcher", id="researcher_019b6000-0000-7000-8000-000000000080"
)
_ENROLLMENT = "enrollment_019b6000-0000-7000-8000-000000000050"
_KEY = b"a-server-blinding-key-of-some-length"
# A realistic Prolific participant id -- the value that must never be persisted.
_PROLIFIC_PID = "60fd1a2b3c4d5e6f7a8b9c0d"


def _gateway() -> Gateway:
    def clock() -> datetime:
        return datetime(2026, 8, 2, 12, 0, 0, tzinfo=timezone.utc)

    counter = {"n": 0}

    def entropy(size: int) -> bytes:
        counter["n"] += 1
        return bytes((counter["n"] + i) % 256 for i in range(size))

    return Gateway(clock=clock, entropy=entropy)


def _store_dump(store: InMemoryStore) -> str:
    """Serialize everything the store holds, to scan for a leaked id."""
    return json.dumps(
        {
            "tokens": store._tokens,  # pyright: ignore[reportPrivateUsage]
            "ledger": store._ledger,  # pyright: ignore[reportPrivateUsage]
            "aggregates": store._aggregates,  # pyright: ignore[reportPrivateUsage]
        },
        default=str,
    )


@pytest.mark.asyncio
async def test_link_round_trips_from_external_id() -> None:
    """A linked participant is recovered from the same external id."""
    store = InMemoryStore()
    provision = await provision_identity_link(
        _gateway(),
        store,
        researcher=_RESEARCHER,
        enrollment_id=_ENROLLMENT,
        provider="prolific",
        external_id=_PROLIFIC_PID,
        blinding_key=_KEY,
    )
    assert provision.enrollment_id == _ENROLLMENT
    assert provision.subject_handle.startswith("handle_")

    recovered = resolve_enrollment(
        store, provider="prolific", external_id=_PROLIFIC_PID, blinding_key=_KEY
    )
    assert recovered == _ENROLLMENT


@pytest.mark.asyncio
async def test_unlinked_participant_resolves_to_none() -> None:
    """An external id that was never linked resolves to no enrolment."""
    store = InMemoryStore()
    await provision_identity_link(
        _gateway(),
        store,
        researcher=_RESEARCHER,
        enrollment_id=_ENROLLMENT,
        provider="prolific",
        external_id=_PROLIFIC_PID,
        blinding_key=_KEY,
    )

    recovered = resolve_enrollment(
        store, provider="prolific", external_id="a-different-pid", blinding_key=_KEY
    )
    assert recovered is None


@pytest.mark.asyncio
async def test_repeat_link_has_no_second_effect() -> None:
    """Linking the same external id twice replays with no second effect."""
    store = InMemoryStore()
    common: dict[str, Any] = {
        "researcher": _RESEARCHER,
        "enrollment_id": _ENROLLMENT,
        "provider": "prolific",
        "external_id": _PROLIFIC_PID,
        "blinding_key": _KEY,
    }
    first = await provision_identity_link(_gateway(), store, **common)
    again = await provision_identity_link(_gateway(), store, **common)

    assert again.subject_handle == first.subject_handle
    assert len(store.committed_event_ids()) == 1


@pytest.mark.asyncio
async def test_raw_external_id_never_persists() -> None:
    """The raw external id lands in no stored record or event."""
    store = InMemoryStore()
    await provision_identity_link(
        _gateway(),
        store,
        researcher=_RESEARCHER,
        enrollment_id=_ENROLLMENT,
        provider="prolific",
        external_id=_PROLIFIC_PID,
        blinding_key=_KEY,
    )
    assert _PROLIFIC_PID not in _store_dump(store)
