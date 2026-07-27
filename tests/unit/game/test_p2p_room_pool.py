"""The room pool maps waiting browsers onto one frozen mesh and its live room.

``P2PRoomPool`` is the seam between API-06 formation and the live P2P room. It
takes waiting enrollment and connection bindings, forms a group, and returns one
room core plus one placement per connection. These tests prove the pool's own
guarantees:

- a room forms only at the declared size, and every waiting peer is placed once;
- the offer and answer roles come from the frozen actor ids, so both browsers of
  a pair agree with no extra message;
- each placement names every other peer of the room, and no peer names itself;
- the pool refuses a duplicate enrollment and releases a waiting one.

The pool owns no socket, task, or store: the identifier minter, the clocks, and
the monotonic counter are injected.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from mug.game.p2p_capture import VerifiedCapture
from mug.game.p2p_pool import (
    FormedRoom,
    P2PRoomPool,
    RoomPoolConfig,
    RoomPoolRuntime,
    WaitingPeer,
)
from mug.game.p2p_room_types import RoomLimits
from mug.gateway import Gateway
from mug.kernel import Digest
from mug.kernel.refs import StudyVersionRef

_START = datetime(2026, 7, 24, tzinfo=timezone.utc)
_STUDY = StudyVersionRef(
    study_id="study_019b6000-0000-7000-8000-0000000000c0",
    study_version_id="studyver_019b6000-0000-7000-8000-0000000000c1",
    version_number=1,
    manifest_digest=Digest(algorithm="sha-256", hex="0" * 64),
)


def _verifier(payload_json: str) -> VerifiedCapture:
    del payload_json
    return VerifiedCapture(
        trajectory_digest=Digest(algorithm="sha-256", hex="d" * 64), frame_count=0
    )


def _pool(size: int) -> P2PRoomPool:
    gateway = Gateway(clock=lambda: _START)
    return P2PRoomPool(
        RoomPoolConfig(
            channel_key="p2p-browser",
            size=size,
            seed=11,
            study_version=_STUDY,
            limits=RoomLimits(),
            verify_capture=_verifier,
        ),
        RoomPoolRuntime(
            new_id=gateway.new_id,
            new_handle=gateway.new_handle,
            now=lambda: "2026-07-24T00:00:00.000000Z",
            utc_now=lambda: _START,
            monotonic=lambda: 0.0,
        ),
    )


def _peer(index: int) -> WaitingPeer:
    return WaitingPeer(
        connection_id=f"handle_connection{index:02d}",
        enrollment_id=f"enrollment_019b6000-0000-7000-8000-0000000005{index:02x}",
        visit_id=f"visit_019b6000-0000-7000-8000-0000000006{index:02x}",
    )


def _fill(pool: P2PRoomPool, count: int) -> tuple[FormedRoom, ...]:
    """Submit ``count`` waiting peers and return whatever formed on the last one."""
    formed: tuple[FormedRoom, ...] = ()
    for index in range(1, count + 1):
        formed = pool.submit(_peer(index))
    return formed


def test_a_room_forms_only_at_the_declared_size() -> None:
    """A pool below its size forms nothing and holds the waiting peers."""
    pool = _pool(3)

    assert pool.submit(_peer(1)) == ()
    assert pool.submit(_peer(2)) == ()
    formed = pool.submit(_peer(3))

    assert len(formed) == 1
    assert len(formed[0].placements) == 3


def test_every_waiting_connection_is_placed_exactly_once() -> None:
    """Each browser appears in one placement of the room it formed."""
    formed = _fill(_pool(2), 2)

    assert len(formed) == 1
    placements = formed[0].placements
    assert {placement.connection_id for placement in placements} == {
        _peer(1).connection_id,
        _peer(2).connection_id,
    }
    assert len({placement.local_peer_handle for placement in placements}) == 2
    for placement in placements:
        assert placement.room is formed[0].room


def test_the_offer_roles_come_from_the_frozen_actor_order() -> None:
    """Both sides of a pair derive complementary roles with no extra message."""
    formed = _fill(_pool(2), 2)
    first, second = formed[0].placements

    assert [peer.peer_handle for peer in first.remote_peers] == [
        second.local_peer_handle
    ]
    assert [peer.peer_handle for peer in second.remote_peers] == [
        first.local_peer_handle
    ]
    assert {first.remote_peers[0].role, second.remote_peers[0].role} == {
        "offerer",
        "answerer",
    }


def test_a_three_peer_room_names_every_other_peer() -> None:
    """In a full mesh each browser is told about all the other peers, not itself."""
    formed = _fill(_pool(3), 3)
    placements = formed[0].placements
    locals_ = {placement.local_peer_handle for placement in placements}

    for placement in placements:
        remotes = {peer.peer_handle for peer in placement.remote_peers}
        assert len(placement.remote_peers) == 2
        assert remotes == locals_ - {placement.local_peer_handle}

    # Exactly one side of each pair offers.
    roles = {
        (placement.local_peer_handle, peer.peer_handle): peer.role
        for placement in placements
        for peer in placement.remote_peers
    }
    for (left, right), role in roles.items():
        assert roles[(right, left)] != role


def test_the_room_starts_in_signalling_with_a_designated_owner() -> None:
    """A formed room is ready for signals and already knows its capture owner."""
    formed = _fill(_pool(2), 2)
    room = formed[0].room

    assert room.state == "signalling"
    assert room.capture_owner_handle in room.peer_handles
    assert room.negotiation_generation >= 1
    assert room.seed == 11


def test_a_duplicate_enrollment_is_refused() -> None:
    """One enrollment cannot hold two seats in the waiting room."""
    pool = _pool(2)
    pool.submit(_peer(1))

    with pytest.raises(ValueError, match="already waiting"):
        pool.submit(_peer(1))


def test_a_released_enrollment_no_longer_forms_a_room() -> None:
    """A browser that left the waiting room is not matched into a later group."""
    pool = _pool(2)
    pool.submit(_peer(1))

    assert pool.release(_peer(1).enrollment_id) is True
    assert pool.release(_peer(1).enrollment_id) is False
    assert pool.submit(_peer(2)) == ()

    formed = pool.submit(_peer(3))
    assert len(formed) == 1
    assert {placement.connection_id for placement in formed[0].placements} == {
        _peer(2).connection_id,
        _peer(3).connection_id,
    }
