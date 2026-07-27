"""The live P2P room enforces authority at effect time, not at parse time.

``P2PRoom`` is the transport-neutral core of the authenticated browser P2P
vertical. It holds no socket and no wire model: it takes already-authenticated
connection bindings plus a frozen API-06 mesh, and it returns effects for the
server edge to deliver. These tests drive that core directly and prove the
guarantees the vertical claims:

- a signal relays only from a bound member to another member of the same room,
  and the server stamps the source, so a browser cannot choose its identity;
- a stale room generation, a fenced lease, or an expired lease refuses an effect
  even when the frame itself parses;
- the signal path is bounded by payload size, by a rolling window, and by a
  per-peer total, and a repeated request id is idempotent;
- the start barrier releases only after every peer reports the complete mesh;
- a capture finishes only when every peer claim, the owner payload, its
  recomputed digest, and the durable receipt all agree; a conflict aborts;
- a disconnect, a deadline, or an abort fences every lease exactly once, and a
  late frame cannot reopen the room.

The clock, the monotonic counter, and the lease authority are injected, so the
whole room is deterministic with no wall clock and no store.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

import pytest

from mug.game.p2p_capture import VerifiedCapture
from mug.game.p2p_room import P2PRoom, P2PRoomError
from mug.game.p2p_room_types import (
    BoundPeer,
    MeshAbort,
    MeshFinish,
    MeshStart,
    RoomBinding,
    RoomLimits,
    RoomRuntime,
    SignalDelivery,
)
from mug.interactions.types import ConnectionLease, P2PMeshMembership
from mug.kernel import Digest, LeaseRef, VersionStamp, etag

_INTERACTION = "interaction_019b6000-0000-7000-8000-00000000030f"
_GROUP = "group_019b6000-0000-7000-8000-00000000030e"
_EPOCH = "leaseepoch_019b6000-0000-7000-8000-00000000030d"
_START = datetime(2026, 7, 24, tzinfo=timezone.utc)


def _actor(index: int) -> str:
    return f"actor_019b6000-0000-7000-8000-0000000003{index:02x}"


def _lease(index: int, *, generation: int = 1) -> ConnectionLease:
    return ConnectionLease(
        lease=LeaseRef(
            lease_id=f"lease_019b6000-0000-7000-8000-0000000004{index:02x}",
            namespace_epoch_id=_EPOCH,
            generation=generation,
        ),
        interaction_id=_INTERACTION,
        actor_id=_actor(index),
        expires_at="2026-07-24T01:00:00.000000Z",
    )


def _membership(count: int) -> P2PMeshMembership:
    peers = [_actor(index) for index in range(1, count + 1)]
    return P2PMeshMembership(
        interaction_id=_INTERACTION,
        group_id=_GROUP,
        channel_key="p2p-game",
        peer_actor_ids=peers,
        topology="full-mesh",
        membership_generation=1,
        version=VersionStamp(revision=1, etag=etag({"peers": peers})),
    )


class _Authority:
    """A controllable lease authority and clock for one room under test."""

    def __init__(self) -> None:
        self.now = 0.0
        self.utc = _START
        self.fenced: list[str] = []
        self.stale: set[str] = set()

    def monotonic(self) -> float:
        return self.now

    def utc_now(self) -> datetime:
        return self.utc

    def is_current(self, lease: ConnectionLease) -> bool:
        return lease.lease.lease_id not in self.stale

    def fence(self, lease: ConnectionLease) -> ConnectionLease:
        self.fenced.append(lease.lease.lease_id)
        return lease


def _verifier(payload_json: str) -> VerifiedCapture:
    """Derive the trajectory identity a well-formed test payload declares."""
    frames = payload_json.count('"frame"')
    return VerifiedCapture(
        trajectory_digest=Digest(algorithm="sha-256", hex="d" * 64),
        frame_count=frames,
    )


def _payload(frames: int) -> tuple[str, Digest, Digest, int]:
    """Return one capture payload with its raw and trajectory digests."""
    rows = ",".join(f'{{"frame":{index}}}' for index in range(frames))
    payload_json = f"[{rows}]"
    raw = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
    return (
        payload_json,
        Digest(algorithm="sha-256", hex=raw),
        Digest(algorithm="sha-256", hex="d" * 64),
        frames,
    )


def _connection(index: int) -> str:
    return f"handle_connection{index:02d}"


def _room(
    authority: _Authority,
    *,
    count: int = 2,
    limits: RoomLimits | None = None,
) -> P2PRoom:
    """Build one signalling room over ``count`` authenticated members."""
    members = tuple(
        BoundPeer(
            peer_handle=f"handle_peer{index:02d}",
            connection_id=_connection(index),
            enrollment_id=f"enrollment_{index:02d}",
            visit_id=f"visit_{index:02d}",
            seat_key=f"seat-{index}",
            actor_id=_actor(index),
            lease=_lease(index),
        )
        for index in range(1, count + 1)
    )
    room = P2PRoom(
        RoomBinding(
            room_handle="handle_room01",
            interaction_id=_INTERACTION,
            membership=_membership(count),
            members=members,
            negotiation_generation=1,
            seed=7,
        ),
        RoomRuntime(
            limits=limits or RoomLimits(),
            monotonic=authority.monotonic,
            utc_now=authority.utc_now,
            lease_is_current=authority.is_current,
            fence_lease=authority.fence,
            verify_capture=_verifier,
        ),
    )
    room.begin_signalling()
    return room


def _reach_running(room: P2PRoom, count: int = 2) -> MeshStart:
    """Take a signalling room through the readiness barrier to running."""
    handles = room.peer_handles
    effect: MeshStart | MeshAbort | None = None
    for index in range(1, count + 1):
        effect = room.mark_ready(
            connection_id=_connection(index),
            negotiation_generation=1,
            validated_peer_handles=tuple(
                handle for handle in handles if handle != handles[index - 1]
            ),
        )
    assert isinstance(effect, MeshStart)
    return effect


# -- the frozen room shape ------------------------------------------------------


def _bound(index: int, *, connection: int | None = None) -> BoundPeer:
    """Build one authenticated member binding for a shape test."""
    return BoundPeer(
        peer_handle=f"handle_peer{index:02d}",
        connection_id=_connection(connection if connection is not None else index),
        enrollment_id=f"enrollment_{index:02d}",
        visit_id=f"visit_{index:02d}",
        seat_key=f"seat-{index}",
        actor_id=_actor(index),
        lease=_lease(index),
    )


def _build(members: tuple[BoundPeer, ...], peers: int) -> P2PRoom:
    """Build a room from an explicit member tuple and a frozen mesh size."""
    authority = _Authority()
    return P2PRoom(
        RoomBinding(
            room_handle="handle_room01",
            interaction_id=_INTERACTION,
            membership=_membership(peers),
            members=members,
            negotiation_generation=1,
            seed=7,
        ),
        RoomRuntime(
            limits=RoomLimits(),
            monotonic=authority.monotonic,
            utc_now=authority.utc_now,
            lease_is_current=authority.is_current,
            fence_lease=authority.fence,
            verify_capture=_verifier,
        ),
    )


def test_a_room_needs_at_least_two_bound_members() -> None:
    """A room cannot form around one browser, whatever the frozen mesh says."""
    with pytest.raises(ValueError, match="from 2 to 16 members"):
        _build((_bound(1),), peers=2)


def test_a_room_must_cover_its_frozen_mesh_exactly() -> None:
    """Bound members short of the frozen API-06 peer set are refused."""
    with pytest.raises(ValueError, match="cover the complete frozen mesh"):
        _build((_bound(1), _bound(2)), peers=3)


def test_room_bindings_must_be_unique() -> None:
    """Two members cannot share one authenticated connection."""
    with pytest.raises(ValueError, match="must be unique and match"):
        _build((_bound(1), _bound(2, connection=1)), peers=2)


def test_the_capture_owner_is_chosen_deterministically() -> None:
    """The lowest actor owns the capture, so every peer agrees with no message."""
    first = _room(_Authority())
    second = _room(_Authority())
    assert first.capture_owner_handle == second.capture_owner_handle
    assert first.capture_owner_handle in first.peer_handles


# -- signalling authority and bounds --------------------------------------------


def test_the_server_stamps_the_signal_source() -> None:
    """A relayed signal carries the server's source handle, not a client field."""
    room = _room(_Authority())
    target = room.peer_handles[1]

    effect = room.relay_signal(
        connection_id=_connection(1),
        request_id="request_01",
        target_peer_handle=target,
        negotiation_generation=1,
        signal_kind="offer",
        payload_json='{"sdp":"x"}',
    )

    assert isinstance(effect, SignalDelivery)
    assert effect.source_peer_handle == room.peer_handles[0]
    assert effect.target_peer_handle == target
    assert effect.connection_id == _connection(2)
    assert effect.negotiation_generation == 1


def test_a_signal_cannot_target_a_non_member_or_its_own_peer() -> None:
    """The relay refuses a target outside the room and a self-addressed signal."""
    room = _room(_Authority())
    for target in ("handle_outsider", room.peer_handles[0]):
        with pytest.raises(P2PRoomError) as caught:
            room.relay_signal(
                connection_id=_connection(1),
                request_id=f"request_{target}",
                target_peer_handle=target,
                negotiation_generation=1,
                signal_kind="candidate",
                payload_json="{}",
            )
        assert caught.value.code == "p2p.unknown_target"


def test_a_stale_generation_refuses_every_effect() -> None:
    """A frame from an earlier negotiation cannot act on the current room."""
    room = _room(_Authority())
    with pytest.raises(P2PRoomError) as caught:
        room.relay_signal(
            connection_id=_connection(1),
            request_id="request_01",
            target_peer_handle=room.peer_handles[1],
            negotiation_generation=2,
            signal_kind="offer",
            payload_json="{}",
        )
    assert caught.value.code == "lease.stale_generation"


def test_an_unknown_connection_is_not_a_room_member() -> None:
    """An authenticated socket outside this room cannot relay through it."""
    room = _room(_Authority())
    with pytest.raises(P2PRoomError) as caught:
        room.relay_signal(
            connection_id="handle_other",
            request_id="request_01",
            target_peer_handle=room.peer_handles[1],
            negotiation_generation=1,
            signal_kind="offer",
            payload_json="{}",
        )
    assert caught.value.code == "auth.forbidden"


def test_a_fenced_lease_refuses_a_signal() -> None:
    """A lease that is no longer current loses authority even mid-room."""
    authority = _Authority()
    room = _room(authority)
    authority.stale.add(_lease(1).lease.lease_id)

    with pytest.raises(P2PRoomError) as caught:
        room.relay_signal(
            connection_id=_connection(1),
            request_id="request_01",
            target_peer_handle=room.peer_handles[1],
            negotiation_generation=1,
            signal_kind="offer",
            payload_json="{}",
        )
    assert caught.value.code == "lease.stale_generation"


def test_an_expired_lease_refuses_a_signal() -> None:
    """A lease that outlived its expiry cannot produce an effect."""
    authority = _Authority()
    room = _room(authority)
    authority.utc = _START + timedelta(hours=2)

    with pytest.raises(P2PRoomError) as caught:
        room.relay_signal(
            connection_id=_connection(1),
            request_id="request_01",
            target_peer_handle=room.peer_handles[1],
            negotiation_generation=1,
            signal_kind="offer",
            payload_json="{}",
        )
    assert caught.value.code == "lease.expired"


def test_a_stale_target_aborts_the_room_instead_of_relaying() -> None:
    """A signal toward a peer that lost its lease ends the room, it does not route."""
    authority = _Authority()
    room = _room(authority)
    authority.stale.add(_lease(2).lease.lease_id)

    effect = room.relay_signal(
        connection_id=_connection(1),
        request_id="request_01",
        target_peer_handle=room.peer_handles[1],
        negotiation_generation=1,
        signal_kind="offer",
        payload_json="{}",
    )

    assert isinstance(effect, MeshAbort)
    assert effect.reason == "stale_connection"
    assert effect.disposition == "repool"


def test_a_repeated_request_id_is_idempotent_and_a_changed_one_conflicts() -> None:
    """A retried signal relays once; a mutated retry is an idempotency conflict."""
    room = _room(_Authority())
    target = room.peer_handles[1]
    first = room.relay_signal(
        connection_id=_connection(1),
        request_id="request_01",
        target_peer_handle=target,
        negotiation_generation=1,
        signal_kind="offer",
        payload_json='{"sdp":"x"}',
    )
    repeat = room.relay_signal(
        connection_id=_connection(1),
        request_id="request_01",
        target_peer_handle=target,
        negotiation_generation=1,
        signal_kind="offer",
        payload_json='{"sdp":"x"}',
    )

    assert isinstance(first, SignalDelivery)
    assert repeat is None

    with pytest.raises(P2PRoomError) as caught:
        room.relay_signal(
            connection_id=_connection(1),
            request_id="request_01",
            target_peer_handle=target,
            negotiation_generation=1,
            signal_kind="offer",
            payload_json='{"sdp":"changed"}',
        )
    assert caught.value.code == "command.idempotency_conflict"


def test_an_oversize_signal_payload_is_refused() -> None:
    """A payload over the room bound cannot enter the relay."""
    room = _room(_Authority(), limits=RoomLimits(max_signal_bytes=32))
    with pytest.raises(P2PRoomError) as caught:
        room.relay_signal(
            connection_id=_connection(1),
            request_id="request_01",
            target_peer_handle=room.peer_handles[1],
            negotiation_generation=1,
            signal_kind="offer",
            payload_json="x" * 33,
        )
    assert caught.value.code == "runtime.backpressure"


def test_the_signal_rate_window_and_total_are_both_bounded() -> None:
    """One peer cannot flood a room in a burst or over the whole negotiation."""
    authority = _Authority()
    room = _room(
        authority,
        limits=RoomLimits(max_signals_per_window=2, max_signals_per_peer=3),
    )
    target = room.peer_handles[1]

    for index in range(2):
        room.relay_signal(
            connection_id=_connection(1),
            request_id=f"request_{index}",
            target_peer_handle=target,
            negotiation_generation=1,
            signal_kind="candidate",
            payload_json="{}",
        )
    with pytest.raises(P2PRoomError) as burst:
        room.relay_signal(
            connection_id=_connection(1),
            request_id="request_2",
            target_peer_handle=target,
            negotiation_generation=1,
            signal_kind="candidate",
            payload_json="{}",
        )
    assert burst.value.code == "quota.rate_limited"

    # A later window admits more signals, up to the per-peer total.
    authority.now += 5.0
    room.relay_signal(
        connection_id=_connection(1),
        request_id="request_3",
        target_peer_handle=target,
        negotiation_generation=1,
        signal_kind="candidate",
        payload_json="{}",
    )
    authority.now += 5.0
    with pytest.raises(P2PRoomError) as total:
        room.relay_signal(
            connection_id=_connection(1),
            request_id="request_4",
            target_peer_handle=target,
            negotiation_generation=1,
            signal_kind="candidate",
            payload_json="{}",
        )
    assert total.value.code == "runtime.backpressure"


# -- the readiness barrier ------------------------------------------------------


def test_a_partial_readiness_report_is_refused() -> None:
    """A peer must name every other peer in the room, not a subset."""
    room = _room(_Authority(), count=3)
    with pytest.raises(P2PRoomError) as caught:
        room.mark_ready(
            connection_id=_connection(1),
            negotiation_generation=1,
            validated_peer_handles=(room.peer_handles[1],),
        )
    assert caught.value.code == "schema.validation_failed"


def test_the_start_barrier_waits_for_every_peer() -> None:
    """One missing pair report keeps the room out of start."""
    room = _room(_Authority(), count=3)
    handles = room.peer_handles

    first = room.mark_ready(
        connection_id=_connection(1),
        negotiation_generation=1,
        validated_peer_handles=(handles[1], handles[2]),
    )
    second = room.mark_ready(
        connection_id=_connection(2),
        negotiation_generation=1,
        validated_peer_handles=(handles[0], handles[2]),
    )
    assert first is None
    assert second is None
    assert room.state == "validating"

    third = room.mark_ready(
        connection_id=_connection(3),
        negotiation_generation=1,
        validated_peer_handles=(handles[0], handles[1]),
    )
    assert isinstance(third, MeshStart)
    assert third.seed == 7
    assert third.capture_owner_handle == room.capture_owner_handle
    assert set(third.connection_ids) == {_connection(index) for index in (1, 2, 3)}
    assert room.state == "running"


def test_the_start_effect_is_emitted_once() -> None:
    """A repeated ready report after start does not start the room twice."""
    room = _room(_Authority())
    _reach_running(room)
    repeat = room.mark_ready(
        connection_id=_connection(1),
        negotiation_generation=1,
        validated_peer_handles=(room.peer_handles[1],),
    )
    assert repeat is None


# -- capture reconciliation -----------------------------------------------------


def test_a_reconciled_capture_finishes_the_room() -> None:
    """Matching peer claims, the owner payload, and a receipt produce one finish."""
    authority = _Authority()
    room = _room(authority)
    _reach_running(room)
    payload_json, payload_digest, trajectory, frames = _payload(4)

    assert (
        room.report_complete(
            connection_id=_connection(1),
            negotiation_generation=1,
            trajectory_digest=trajectory,
            frame_count=frames,
        )
        is None
    )
    assert (
        room.report_complete(
            connection_id=_connection(2),
            negotiation_generation=1,
            trajectory_digest=trajectory,
            frame_count=frames,
        )
        is None
    )
    fence = room.submit_capture(
        connection_id=_connection(1),
        negotiation_generation=1,
        trajectory_digest=trajectory,
        frame_count=frames,
        payload_json=payload_json,
        payload_digest=payload_digest,
    )
    assert fence is not None and not isinstance(fence, MeshAbort)
    assert room.capture_payload() == payload_json

    finish = room.set_capture_receipt(fence, "handle_receipt01")

    assert isinstance(finish, MeshFinish)
    assert finish.trajectory_digest == trajectory
    assert finish.frame_count == frames
    assert finish.capture_receipt == "handle_receipt01"
    assert room.state == "complete"
    # A finish fences every lease exactly once.
    assert sorted(authority.fenced) == sorted(
        [_lease(1).lease.lease_id, _lease(2).lease.lease_id]
    )


def test_only_the_capture_owner_may_submit_the_payload() -> None:
    """A non-owner peer cannot write the room's scientific record."""
    room = _room(_Authority())
    _reach_running(room)
    payload_json, payload_digest, trajectory, frames = _payload(2)
    owner_index = 1 if room.capture_owner_handle == room.peer_handles[0] else 2
    other_index = 2 if owner_index == 1 else 1

    with pytest.raises(P2PRoomError) as caught:
        room.submit_capture(
            connection_id=_connection(other_index),
            negotiation_generation=1,
            trajectory_digest=trajectory,
            frame_count=frames,
            payload_json=payload_json,
            payload_digest=payload_digest,
        )
    assert caught.value.code == "auth.forbidden"


def test_a_payload_whose_digest_does_not_match_is_refused() -> None:
    """The server recomputes SHA-256 over the exact payload bytes."""
    room = _room(_Authority())
    _reach_running(room)
    payload_json, _, trajectory, frames = _payload(3)

    with pytest.raises(P2PRoomError) as caught:
        room.submit_capture(
            connection_id=_connection(1),
            negotiation_generation=1,
            trajectory_digest=trajectory,
            frame_count=frames,
            payload_json=payload_json,
            payload_digest=Digest(algorithm="sha-256", hex="e" * 64),
        )
    assert caught.value.code == "artifact.integrity_failed"


def test_conflicting_peer_claims_abort_the_room() -> None:
    """The server never picks a winner between two disagreeing replicas."""
    room = _room(_Authority())
    _reach_running(room)
    _, _, trajectory, _ = _payload(4)

    room.report_complete(
        connection_id=_connection(1),
        negotiation_generation=1,
        trajectory_digest=trajectory,
        frame_count=4,
    )
    effect = room.report_complete(
        connection_id=_connection(2),
        negotiation_generation=1,
        trajectory_digest=Digest(algorithm="sha-256", hex="f" * 64),
        frame_count=4,
    )

    assert isinstance(effect, MeshAbort)
    assert effect.reason == "capture_conflict"
    assert effect.disposition == "terminal"
    assert room.state == "abort"


def test_a_capture_cannot_be_submitted_before_the_room_runs() -> None:
    """A payload that arrives during negotiation has no episode to describe."""
    room = _room(_Authority())
    payload_json, payload_digest, trajectory, frames = _payload(2)
    with pytest.raises(P2PRoomError) as caught:
        room.submit_capture(
            connection_id=_connection(1),
            negotiation_generation=1,
            trajectory_digest=trajectory,
            frame_count=frames,
            payload_json=payload_json,
            payload_digest=payload_digest,
        )
    assert caught.value.code == "command.state_conflict"


def test_a_stale_persistence_fence_cannot_finish_the_room() -> None:
    """A capture write that outlived its attempt cannot attach its receipt."""
    room = _room(_Authority())
    _reach_running(room)
    payload_json, payload_digest, trajectory, frames = _payload(2)
    for index in (1, 2):
        room.report_complete(
            connection_id=_connection(index),
            negotiation_generation=1,
            trajectory_digest=trajectory,
            frame_count=frames,
        )
    fence = room.submit_capture(
        connection_id=_connection(1),
        negotiation_generation=1,
        trajectory_digest=trajectory,
        frame_count=frames,
        payload_json=payload_json,
        payload_digest=payload_digest,
    )
    assert fence is not None and not isinstance(fence, MeshAbort)
    stale = type(fence)(
        room_handle=fence.room_handle,
        negotiation_generation=fence.negotiation_generation + 1,
        payload_digest=fence.payload_digest,
    )

    with pytest.raises(P2PRoomError) as caught:
        room.set_capture_receipt(stale, "handle_receipt01")
    assert caught.value.code == "lease.stale_generation"


# -- termination ----------------------------------------------------------------


def test_a_disconnect_aborts_the_whole_room() -> None:
    """This vertical does not shrink a mesh; one lost peer ends the room."""
    authority = _Authority()
    room = _room(authority)
    _reach_running(room)

    effect = room.disconnect(_connection(2))

    assert isinstance(effect, MeshAbort)
    assert effect.reason == "peer_disconnected"
    assert effect.disposition == "repool"
    assert len(authority.fenced) == 2


def test_a_disconnect_from_an_unbound_connection_does_nothing() -> None:
    """A socket that never joined the room cannot abort it."""
    room = _room(_Authority())
    assert room.disconnect("handle_other") is None
    assert room.state == "signalling"


def test_the_deadline_aborts_negotiation_and_then_capture() -> None:
    """The room expires with the reason that matches the stage it reached."""
    authority = _Authority()
    negotiating = _room(authority)
    assert negotiating.expire() is None  # the deadline has not passed
    authority.now = negotiating.deadline + 1.0
    timed_out = negotiating.expire()
    assert isinstance(timed_out, MeshAbort)
    assert timed_out.reason == "negotiation_timeout"

    running_authority = _Authority()
    running = _room(running_authority)
    _reach_running(running)
    running_authority.now = running.deadline + 1.0
    late = running.expire()
    assert isinstance(late, MeshAbort)
    assert late.reason == "capture_timeout"


def test_a_closed_room_refuses_every_late_frame_and_aborts_once() -> None:
    """An abort is terminal: no late frame reopens it and no second abort fires."""
    authority = _Authority()
    room = _room(authority)
    first = room.abort("room_replaced", "repool")
    assert isinstance(first, MeshAbort)
    assert room.abort("peer_disconnected", "repool") is None
    assert len(authority.fenced) == 2

    with pytest.raises(P2PRoomError) as caught:
        room.relay_signal(
            connection_id=_connection(1),
            request_id="request_late",
            target_peer_handle=room.peer_handles[1],
            negotiation_generation=1,
            signal_kind="offer",
            payload_json="{}",
        )
    assert caught.value.code == "command.state_conflict"
