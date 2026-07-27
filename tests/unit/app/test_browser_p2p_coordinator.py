"""The browser P2P coordinator forms rooms and owns their whole live lifetime.

``P2PCoordinator`` is the imperative shell above the transport-neutral room core.
It matches authenticated connections into a room, hands each browser its opaque
bootstrap, relays signals, releases the start barrier, persists the reconciled
capture, and ends the room. These tests drive the shell directly, with no socket
and no wire model, and prove:

- two connections form one room, and each receives only its own handles, its
  remote roles, and a one-use ICE grant;
- a relayed signal reaches the bound target with a server-stamped source;
- the start barrier releases to every member once, and the reconciled capture
  produces one durable receipt and one finish;
- a disconnect aborts the room and releases every member with a disposition;
- a replacement connection fences the prior one;
- ICE redemption is bound to the current room, and a grant is used once;
- a negotiation deadline aborts the room by itself.

The clock, the entropy, and the monotonic counter are injected, so every run is
deterministic.
"""

from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timezone
from typing import Any

import pytest

from mug.client.ice import IceGrantError, IceServerConfig, TurnSecret
from mug.game.p2p_capture import VerifiedCapture
from mug.game.p2p_room_types import (
    MeshAbort,
    MeshFinish,
    MeshStart,
    RoomEffect,
    RoomLimits,
    SignalDelivery,
)
from mug.gateway import Gateway
from mug.kernel import Digest, PrincipalRef
from mug.participant_p2p import P2PCoordinator
from mug.participant_p2p_types import (
    BrowserP2PConfig,
    P2PConnectionIdentity,
    P2PEdgeError,
    RoomAssignment,
)
from mug.storage import InMemoryStore

_START = datetime(2026, 7, 24, tzinfo=timezone.utc)
_TRAJECTORY = Digest(algorithm="sha-256", hex="d" * 64)


class _Entropy:
    """A deterministic byte source, so every minted handle is reproducible."""

    def __init__(self) -> None:
        self._counter = 0

    def __call__(self, count: int) -> bytes:
        self._counter += 1
        return hashlib.sha256(self._counter.to_bytes(4, "big")).digest()[:count] * (
            1 + count // 32
        )


class _Monotonic:
    """A controllable monotonic counter, optionally auto-advancing per read."""

    def __init__(self, step: float = 0.0) -> None:
        self.value = 0.0
        self._step = step

    def __call__(self) -> float:
        current = self.value
        self.value += self._step
        return current


class _Socket:
    """One authenticated browser socket: it records the effects it received."""

    def __init__(self, index: int) -> None:
        self.identity = P2PConnectionIdentity(
            browser_session_handle=f"handle_session{index:02d}",
            enrollment_id=f"enrollment_019b6000-0000-7000-8000-0000000005{index:02x}",
            visit_id=f"visit_019b6000-0000-7000-8000-0000000006{index:02x}",
            principal=PrincipalRef(
                kind="participant",
                id=f"participant_019b6000-0000-7000-8000-0000000007{index:02x}",
            ),
        )
        self.received: list[RoomEffect] = []

    async def send(self, effect: RoomEffect) -> None:
        self.received.append(effect)

    def of(self, kind: type[Any]) -> list[Any]:
        """Return every received effect of one kind."""
        return [effect for effect in self.received if isinstance(effect, kind)]


def _verifier(payload_json: str) -> VerifiedCapture:
    """Derive the trajectory identity the test payload declares."""
    return VerifiedCapture(
        trajectory_digest=_TRAJECTORY, frame_count=payload_json.count('"frame"')
    )


def _payload(frames: int) -> tuple[str, Digest, int]:
    """Return one capture payload with its exact raw-byte digest."""
    rows = ",".join(f'{{"frame":{index}}}' for index in range(frames))
    payload_json = f"[{rows}]"
    raw = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
    return payload_json, Digest(algorithm="sha-256", hex=raw), frames


def _config(**overrides: Any) -> BrowserP2PConfig:
    base: dict[str, Any] = {
        "channel_key": "p2p-browser",
        "size": 2,
        "verify_capture": _verifier,
        "seed": 11,
        "ice": IceServerConfig(
            turn_secret=TurnSecret(b"0123456789abcdef"),
            stun_urls=("stun:stun.example:3478",),
            turn_urls=("turn:turn.example:3478",),
        ),
    }
    base.update(overrides)
    return BrowserP2PConfig(**base)


def _coordinator(
    *, config: BrowserP2PConfig | None = None, monotonic: _Monotonic | None = None
) -> tuple[P2PCoordinator, InMemoryStore]:
    gateway = Gateway(clock=lambda: _START, entropy=_Entropy())
    store = InMemoryStore()
    return (
        P2PCoordinator(
            gateway, store, config or _config(), monotonic=monotonic or _Monotonic()
        ),
        store,
    )


async def _form(
    coordinator: P2PCoordinator, sockets: tuple[_Socket, ...]
) -> tuple[list[Any], list[RoomAssignment]]:
    """Connect and enqueue every socket, then return the resolved assignments."""
    connections = [
        await coordinator.connect(socket.identity, socket.send) for socket in sockets
    ]
    futures = [await coordinator.enqueue(connection) for connection in connections]
    assignments = [await future for future in futures]
    return connections, assignments


async def _reach_running(
    coordinator: P2PCoordinator,
    connections: list[Any],
    assignments: list[RoomAssignment],
) -> None:
    """Report every pair validated, so the coordinator releases the start."""
    for connection, assignment in zip(connections, assignments, strict=True):
        await coordinator.mark_ready(
            connection,
            assignment.room_handle,
            assignment.negotiation_generation,
            tuple(peer.peer_handle for peer in assignment.peers),
        )


def _owner_index(assignments: list[RoomAssignment]) -> int:
    """Return the index of the member the room designated the capture owner."""
    owner = assignments[0].capture_owner_handle
    return next(
        index
        for index, assignment in enumerate(assignments)
        if assignment.local_peer_handle == owner
    )


# -- formation ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_connections_form_one_room_with_private_handles() -> None:
    """Each browser gets its own opaque bootstrap and complementary offer roles."""
    coordinator, _ = _coordinator()
    sockets = (_Socket(1), _Socket(2))
    connections, assignments = await _form(coordinator, sockets)

    first, second = assignments
    assert first.room_handle == second.room_handle
    assert first.local_peer_handle != second.local_peer_handle
    assert first.negotiation_generation == second.negotiation_generation
    assert first.capture_owner_handle == second.capture_owner_handle
    # Each browser sees only the other peer, and the two roles are complementary.
    assert [peer.peer_handle for peer in first.peers] == [second.local_peer_handle]
    assert [peer.peer_handle for peer in second.peers] == [first.local_peer_handle]
    assert {first.peers[0].role, second.peers[0].role} == {"offerer", "answerer"}
    # Each browser gets its own one-use ICE grant and the same-origin endpoint.
    assert first.ice_grant.handle != second.ice_grant.handle
    assert first.ice_endpoint == "/api/p2p/ice"
    assert first.validation_timeout_ms == 15_000

    await coordinator.abort(first.room_handle, "server_unavailable", "repool")
    del connections


@pytest.mark.asyncio
async def test_a_lone_connection_waits_for_a_partner() -> None:
    """One browser does not form a room by itself."""
    coordinator, _ = _coordinator()
    socket = _Socket(1)
    connection = await coordinator.connect(socket.identity, socket.send)

    future = await coordinator.enqueue(connection)
    await asyncio.sleep(0)

    assert not future.done()
    await coordinator.disconnect(connection)


@pytest.mark.asyncio
async def test_one_enrollment_cannot_wait_twice() -> None:
    """A duplicate enqueue is a state conflict, not a second seat."""
    coordinator, _ = _coordinator()
    socket = _Socket(1)
    connection = await coordinator.connect(socket.identity, socket.send)
    await coordinator.enqueue(connection)

    with pytest.raises(P2PEdgeError) as caught:
        await coordinator.enqueue(connection)
    assert caught.value.code == "command.state_conflict"

    await coordinator.disconnect(connection)


# -- signalling -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_relayed_signal_reaches_only_the_bound_target() -> None:
    """The coordinator stamps the source and delivers to the target's socket."""
    coordinator, _ = _coordinator()
    sockets = (_Socket(1), _Socket(2))
    connections, assignments = await _form(coordinator, sockets)

    await coordinator.relay_signal(
        connections[0],
        room_handle=assignments[0].room_handle,
        request_id="request_01",
        target_peer_handle=assignments[0].peers[0].peer_handle,
        negotiation_generation=assignments[0].negotiation_generation,
        signal_kind="offer",
        payload_json='{"sdp":"x"}',
    )

    assert sockets[0].of(SignalDelivery) == []
    delivered = sockets[1].of(SignalDelivery)
    assert len(delivered) == 1
    assert delivered[0].source_peer_handle == assignments[0].local_peer_handle
    assert delivered[0].target_peer_handle == assignments[1].local_peer_handle
    assert delivered[0].payload_json == '{"sdp":"x"}'

    await coordinator.abort(assignments[0].room_handle, "server_unavailable", "repool")


@pytest.mark.asyncio
async def test_a_signal_for_another_room_is_refused() -> None:
    """A room handle the connection is not bound to cannot be signalled through."""
    coordinator, _ = _coordinator()
    sockets = (_Socket(1), _Socket(2))
    connections, assignments = await _form(coordinator, sockets)

    with pytest.raises(Exception, match="not a room member"):
        await coordinator.relay_signal(
            connections[0],
            room_handle="handle_elsewhere",
            request_id="request_01",
            target_peer_handle=assignments[0].peers[0].peer_handle,
            negotiation_generation=1,
            signal_kind="offer",
            payload_json="{}",
        )

    await coordinator.abort(assignments[0].room_handle, "server_unavailable", "repool")


# -- start, capture, and finish -------------------------------------------------


@pytest.mark.asyncio
async def test_the_room_starts_once_and_finishes_with_a_durable_receipt() -> None:
    """Every peer starts together, and the owner's capture becomes one receipt."""
    coordinator, _ = _coordinator()
    sockets = (_Socket(1), _Socket(2))
    connections, assignments = await _form(coordinator, sockets)
    await _reach_running(coordinator, connections, assignments)

    starts = [socket.of(MeshStart) for socket in sockets]
    assert [len(found) for found in starts] == [1, 1]
    assert starts[0][0].seed == 11
    assert starts[0][0].capture_owner_handle == assignments[0].capture_owner_handle

    payload_json, payload_digest, frames = _payload(5)
    for connection, assignment in zip(connections, assignments, strict=True):
        await coordinator.report_complete(
            connection,
            assignment.room_handle,
            assignment.negotiation_generation,
            _TRAJECTORY,
            frames,
        )
    owner = _owner_index(assignments)
    await coordinator.submit_capture(
        connections[owner],
        room_handle=assignments[owner].room_handle,
        generation=assignments[owner].negotiation_generation,
        trajectory_digest=_TRAJECTORY,
        frame_count=frames,
        payload_json=payload_json,
        payload_digest=payload_digest,
    )

    finishes = [socket.of(MeshFinish) for socket in sockets]
    assert [len(found) for found in finishes] == [1, 1]
    finish = finishes[0][0]
    assert finish.trajectory_digest == _TRAJECTORY
    assert finish.frame_count == frames
    assert finish.capture_receipt.startswith("handle_")
    # Every member's flow resumes with the finish disposition.
    for assignment in assignments:
        end = await assignment.ended
        assert end.kind == "finish"
        assert end.disposition == "resume_flow"
        assert end.capture_receipt == finish.capture_receipt


@pytest.mark.asyncio
async def test_a_conflicting_completion_claim_aborts_the_room() -> None:
    """The coordinator never chooses between two disagreeing replicas."""
    coordinator, _ = _coordinator()
    sockets = (_Socket(1), _Socket(2))
    connections, assignments = await _form(coordinator, sockets)
    await _reach_running(coordinator, connections, assignments)

    await coordinator.report_complete(
        connections[0],
        assignments[0].room_handle,
        assignments[0].negotiation_generation,
        _TRAJECTORY,
        5,
    )
    await coordinator.report_complete(
        connections[1],
        assignments[1].room_handle,
        assignments[1].negotiation_generation,
        Digest(algorithm="sha-256", hex="e" * 64),
        5,
    )

    aborts = sockets[0].of(MeshAbort)
    assert len(aborts) == 1
    assert aborts[0].reason == "capture_conflict"
    assert aborts[0].disposition == "terminal"
    end = await assignments[0].ended
    assert end.kind == "abort"
    assert end.disposition == "terminal"


# -- termination ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_disconnect_aborts_the_room_and_releases_the_partner() -> None:
    """A lost browser re-pools the peer that is still connected."""
    coordinator, _ = _coordinator()
    sockets = (_Socket(1), _Socket(2))
    connections, assignments = await _form(coordinator, sockets)

    await coordinator.disconnect(connections[0])

    aborts = sockets[1].of(MeshAbort)
    assert len(aborts) == 1
    assert aborts[0].reason == "peer_disconnected"
    assert aborts[0].disposition == "repool"
    end = await assignments[1].ended
    assert end.kind == "abort"
    assert end.disposition == "repool"


@pytest.mark.asyncio
async def test_a_replacement_connection_fences_the_prior_one() -> None:
    """One browser session has one live connection; the old one loses authority."""
    coordinator, _ = _coordinator()
    sockets = (_Socket(1), _Socket(2))
    connections, assignments = await _form(coordinator, sockets)

    replacement_socket = _Socket(1)
    await coordinator.connect(replacement_socket.identity, replacement_socket.send)

    aborts = sockets[1].of(MeshAbort)
    assert len(aborts) == 1
    assert aborts[0].reason == "room_replaced"
    # The fenced connection can no longer act on the room.
    with pytest.raises(Exception, match=r"stale|closed|not a room member"):
        await coordinator.mark_ready(
            connections[0],
            assignments[0].room_handle,
            assignments[0].negotiation_generation,
            (assignments[0].peers[0].peer_handle,),
        )


@pytest.mark.asyncio
async def test_a_negotiation_that_never_validates_expires() -> None:
    """The validation deadline ends a room with no live peer report."""
    coordinator, _ = _coordinator(
        config=_config(limits=RoomLimits(validation_timeout_seconds=1.0)),
        monotonic=_Monotonic(step=10.0),
    )
    sockets = (_Socket(1), _Socket(2))
    _, assignments = await _form(coordinator, sockets)

    end = await asyncio.wait_for(assignments[0].ended, timeout=2.0)

    assert end.kind == "abort"
    assert end.disposition == "repool"
    aborts = sockets[0].of(MeshAbort)
    assert aborts and aborts[0].reason == "negotiation_timeout"


# -- ICE redemption -------------------------------------------------------------


@pytest.mark.asyncio
async def test_ice_redeems_once_for_the_current_room_binding() -> None:
    """The grant works for its own browser, once, and not for another session."""
    coordinator, _ = _coordinator()
    sockets = (_Socket(1), _Socket(2))
    connections, assignments = await _form(coordinator, sockets)

    response = await coordinator.redeem_ice(
        sockets[0].identity.browser_session_handle, assignments[0].ice_grant.handle
    )
    assert response.as_json()["iceTransportPolicy"] == "all"

    with pytest.raises(IceGrantError) as reused:
        await coordinator.redeem_ice(
            sockets[0].identity.browser_session_handle,
            assignments[0].ice_grant.handle,
        )
    assert reused.value.code == "command.state_conflict"

    with pytest.raises(IceGrantError) as stolen:
        await coordinator.redeem_ice(
            sockets[1].identity.browser_session_handle,
            assignments[0].ice_grant.handle,
        )
    assert stolen.value.code == "auth.forbidden"

    await coordinator.abort(assignments[0].room_handle, "server_unavailable", "repool")
    del connections


@pytest.mark.asyncio
async def test_ice_redeems_on_the_grant_alone_when_the_browser_is_unnamed() -> None:
    """A deployment with no same-origin session still redeems, once.

    The client is never told its own visit, so it cannot name itself. Without a
    deployment session to name it, the grant does: it is unguessable, one-use, and
    only redeemable while the browser it was issued to is seated in a live room.
    """
    coordinator, _ = _coordinator()
    sockets = (_Socket(1), _Socket(2))
    connections, assignments = await _form(coordinator, sockets)

    response = await coordinator.redeem_ice(None, assignments[0].ice_grant.handle)
    assert response.as_json()["iceTransportPolicy"] == "all"

    with pytest.raises(IceGrantError) as reused:
        await coordinator.redeem_ice(None, assignments[0].ice_grant.handle)
    assert reused.value.code == "command.state_conflict"

    with pytest.raises(P2PEdgeError) as invented:
        await coordinator.redeem_ice(None, "handle_neverIssuedAnywhere")
    assert invented.value.code == "resource.not_found"

    await coordinator.abort(assignments[0].room_handle, "server_unavailable", "repool")
    del connections


@pytest.mark.asyncio
async def test_ice_is_refused_without_a_live_room() -> None:
    """A browser that is still waiting has no room to scope a credential to."""
    coordinator, _ = _coordinator()
    socket = _Socket(1)
    connection = await coordinator.connect(socket.identity, socket.send)

    with pytest.raises(P2PEdgeError) as caught:
        await coordinator.redeem_ice(
            socket.identity.browser_session_handle, "handle_guess"
        )
    assert caught.value.code == "auth.forbidden"

    await coordinator.disconnect(connection)
