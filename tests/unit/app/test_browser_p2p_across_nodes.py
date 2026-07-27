"""Two browsers on two server processes negotiate one peer-to-peer room.

``P2PCoordinator`` matched the connections one process held, so a deployment of two
replicas put two browsers in two waiting rooms and neither ever formed. These tests
give each coordinator a ``Node``: two processes, two coordinators, two sockets, one
store and one bus between them.

The browsers still talk to each other directly once they are connected -- only the
negotiation crosses the boundary. So what these tests prove is exactly that: the
match is made across the processes, one process holds the room core, the other
relays its browser's frames to it and writes back the effects it is given, and the
room reaches the same start, capture, and finish it reaches in one process.

The clock, the entropy, and the monotonic counter are injected, and no socket is
opened.
"""

from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timezone
from typing import Any, cast

import pytest

from mug.client.ice import IceServerConfig, TurnSecret
from mug.game.p2p_capture import VerifiedCapture
from mug.game.p2p_room import P2PRoomError
from mug.game.p2p_room_types import (
    MeshAbort,
    MeshFinish,
    MeshStart,
    RoomEffect,
    SignalDelivery,
)
from mug.gateway import Gateway
from mug.interactions.bus import NodeLink, StoreBus
from mug.interactions.rendezvous import DurableRendezvous
from mug.kernel import Digest, PrincipalRef
from mug.nodes import Node
from mug.participant_p2p import P2PCoordinator
from mug.participant_p2p_types import (
    BrowserP2PConfig,
    P2PConnectionIdentity,
    P2PEdgeError,
    RoomAssignment,
)
from mug.storage import InMemoryStore

_START = datetime(2026, 7, 27, tzinfo=timezone.utc)
_TRAJECTORY = Digest(algorithm="sha-256", hex="d" * 64)
_SECRET = b"w18-shared-deployment-secret"


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


def _config(size: int = 2) -> BrowserP2PConfig:
    """Build the browser mesh mount of the given size the processes share."""
    return BrowserP2PConfig(
        channel_key="p2p-browser",
        size=size,
        verify_capture=_verifier,
        seed=11,
        ice=IceServerConfig(
            turn_secret=TurnSecret(b"0123456789abcdef"),
            stun_urls=("stun:stun.example:3478",),
            turn_urls=("turn:turn.example:3478",),
        ),
    )


class _Process:
    """One process of the deployment: its own gateway, node, and coordinator."""

    def __init__(
        self, node_id: str, store: InMemoryStore, bus: StoreBus, size: int = 2
    ) -> None:
        self.gateway = Gateway(clock=lambda: _START, secret=_SECRET)
        # The pump yields instead of sleeping, so a test settles the deployment by
        # yielding the loop rather than by waiting on a wall clock.
        self.link = NodeLink(
            bus, node_id, new_id=self.gateway.new_id, poll_interval=0.0
        )
        self.node = Node(
            node_id=node_id,
            link=self.link,
            rendezvous=DurableRendezvous(
                store,
                new_id=self.gateway.new_id,
                now=lambda: _START.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            ),
        )
        self.coordinator = P2PCoordinator(
            self.gateway, store, _config(size), node=self.node
        )


def _deployment(
    count: int = 2, size: int = 2
) -> tuple[InMemoryStore, list[_Process]]:
    """Build one store, one durable bus over it, and ``count`` processes."""
    store = InMemoryStore()
    gateway = Gateway(clock=lambda: _START, secret=_SECRET)
    bus = StoreBus(store, new_id=gateway.new_id)
    return store, [
        _Process(f"node-{index}", store, bus, size) for index in range(count)
    ]


async def _form(
    processes: list[_Process], sockets: list[_Socket]
) -> tuple[list[Any], list[RoomAssignment]]:
    """Connect one browser to each process and wait for the shared room to form."""
    for process in processes:
        process.link.start()
    connections = [
        await process.coordinator.connect(socket.identity, socket.send)
        for process, socket in zip(processes, sockets, strict=True)
    ]
    futures = [
        await process.coordinator.enqueue(connection)
        for process, connection in zip(processes, connections, strict=True)
    ]
    assignments = list(await asyncio.wait_for(asyncio.gather(*futures), 5.0))
    return connections, assignments


async def _settle() -> None:
    """Yield the loop until every message in flight has been delivered."""
    for _ in range(200):
        await asyncio.sleep(0)


async def _stop(processes: list[_Process]) -> None:
    """Let the bus drain, then stop every process's pump."""
    await _settle()
    for process in processes:
        await process.link.stop()


async def _reach_running(
    processes: list[_Process],
    connections: list[Any],
    assignments: list[RoomAssignment],
) -> None:
    """Report every pair validated, so the room releases the start."""
    for process, connection, assignment in zip(
        processes, connections, assignments, strict=True
    ):
        await process.coordinator.mark_ready(
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


async def test_two_browsers_on_two_processes_form_one_room() -> None:
    """The whole point: the match crosses, and both browsers get one room."""
    _, processes = _deployment()
    sockets = [_Socket(0), _Socket(1)]
    _, assignments = await _form(processes, sockets)
    await _stop(processes)

    assert assignments[0].room_handle == assignments[1].room_handle
    # Each browser is told its own handle and only its own.
    assert assignments[0].local_peer_handle != assignments[1].local_peer_handle
    assert assignments[0].peers[0].peer_handle == assignments[1].local_peer_handle
    # The two roles are complementary, so exactly one browser makes the offer.
    assert {assignments[0].peers[0].role, assignments[1].peers[0].role} == {
        "offerer",
        "answerer",
    }
    # Each holds a grant of its own, redeemable only where it was issued.
    assert assignments[0].ice_grant.handle != assignments[1].ice_grant.handle


async def test_exactly_one_process_holds_the_room() -> None:
    """One process runs the room core; the other holds a socket and relays."""
    store, processes = _deployment()
    sockets = [_Socket(0), _Socket(1)]
    await _form(processes, sockets)
    await _stop(processes)

    rooms: list[dict[str, Any]] = [
        cast("dict[str, Any]", state)
        for _, state in store.scan_aggregates()
        if isinstance(state, dict) and "owner_node" in state
    ]
    assert len(rooms) == 1
    assert rooms[0]["owner_node"] == "node-1"
    members = cast("list[dict[str, Any]]", rooms[0]["members"])
    assert {member["node_id"] for member in members} == {
        "node-0",
        "node-1",
    }


async def test_a_signal_crosses_the_process_boundary() -> None:
    """A browser's offer reaches the browser its peer holds, on the other node."""
    _, processes = _deployment()
    sockets = [_Socket(0), _Socket(1)]
    connections, assignments = await _form(processes, sockets)

    await processes[0].coordinator.relay_signal(
        connections[0],
        room_handle=assignments[0].room_handle,
        request_id="request_019b6000-0000-7000-8000-000000000901",
        target_peer_handle=assignments[0].peers[0].peer_handle,
        negotiation_generation=assignments[0].negotiation_generation,
        signal_kind="offer",
        payload_json='{"sdp":"one"}',
    )
    await _stop(processes)

    delivered = sockets[1].of(SignalDelivery)
    assert len(delivered) == 1
    assert delivered[0].payload_json == '{"sdp":"one"}'
    # The server stamps the source, so a browser cannot claim to be its peer.
    assert delivered[0].source_peer_handle == assignments[0].local_peer_handle
    # The sender is never delivered its own signal.
    assert not sockets[0].of(SignalDelivery)


async def test_the_start_barrier_releases_on_both_processes() -> None:
    """The room starts once both browsers report, whichever node holds each."""
    _, processes = _deployment()
    sockets = [_Socket(0), _Socket(1)]
    connections, assignments = await _form(processes, sockets)

    await processes[0].coordinator.mark_ready(
        connections[0],
        assignments[0].room_handle,
        assignments[0].negotiation_generation,
        (assignments[0].peers[0].peer_handle,),
    )
    await _settle()
    # One report is not a barrier: nothing has started yet.
    assert not sockets[0].of(MeshStart)
    assert not sockets[1].of(MeshStart)

    await processes[1].coordinator.mark_ready(
        connections[1],
        assignments[1].room_handle,
        assignments[1].negotiation_generation,
        (assignments[1].peers[0].peer_handle,),
    )
    await _stop(processes)

    assert len(sockets[0].of(MeshStart)) == 1
    assert len(sockets[1].of(MeshStart)) == 1
    assert sockets[0].of(MeshStart)[0].seed == sockets[1].of(MeshStart)[0].seed


async def test_the_capture_is_persisted_once_and_both_browsers_finish() -> None:
    """A room that ran across two processes leaves one record and ends for both."""
    _, processes = _deployment()
    sockets = [_Socket(0), _Socket(1)]
    connections, assignments = await _form(processes, sockets)
    await _reach_running(processes, connections, assignments)
    payload_json, payload_digest, frames = _payload(3)

    for process, connection, assignment in zip(
        processes, connections, assignments, strict=True
    ):
        await process.coordinator.report_complete(
            connection,
            assignment.room_handle,
            assignment.negotiation_generation,
            _TRAJECTORY,
            frames,
        )
    owner = _owner_index(assignments)
    await processes[owner].coordinator.submit_capture(
        connections[owner],
        room_handle=assignments[owner].room_handle,
        generation=assignments[owner].negotiation_generation,
        trajectory_digest=_TRAJECTORY,
        frame_count=frames,
        payload_json=payload_json,
        payload_digest=payload_digest,
    )
    await _stop(processes)

    for socket in sockets:
        assert len(socket.of(MeshFinish)) == 1
        assert socket.of(MeshFinish)[0].capture_receipt
    # One room, one receipt, whichever process the owner's browser was on.
    assert (
        sockets[0].of(MeshFinish)[0].capture_receipt
        == sockets[1].of(MeshFinish)[0].capture_receipt
    )
    # And every member's wait ends with the same disposition.
    ends = [assignment.ended for assignment in assignments]
    resolved = await asyncio.wait_for(asyncio.gather(*ends), 5.0)
    assert [end.kind for end in resolved] == ["finish", "finish"]


async def test_a_browser_that_leaves_ends_the_room_for_the_other_process() -> None:
    """A departure on one node aborts the room for the browser on the other."""
    _, processes = _deployment()
    sockets = [_Socket(0), _Socket(1)]
    connections, _ = await _form(processes, sockets)

    await processes[0].coordinator.disconnect(connections[0])
    await _stop(processes)

    aborts = sockets[1].of(MeshAbort)
    assert len(aborts) == 1
    assert aborts[0].reason == "peer_disconnected"


async def test_ice_is_redeemed_where_the_grant_was_issued() -> None:
    """A grant issued by the process that runs the room is redeemable from either.

    The browser's credential request goes wherever the load balancer sends it. The
    grant is one-use and bound to one room and one peer, so the request has to
    reach the process that issued it rather than be answered locally.
    """
    _, processes = _deployment()
    sockets = [_Socket(0), _Socket(1)]
    _, assignments = await _form(processes, sockets)

    credentials = await processes[0].coordinator.redeem_ice(
        sockets[0].identity.browser_session_handle,
        assignments[0].ice_grant.handle,
    )
    assert credentials.turn_urls
    assert credentials.username is not None

    # One use. The second attempt is refused by the process that issued it, and
    # the refusal comes back to the process that asked.
    with pytest.raises(P2PEdgeError):
        await processes[0].coordinator.redeem_ice(
            sockets[0].identity.browser_session_handle,
            assignments[0].ice_grant.handle,
        )
    await _stop(processes)


async def test_a_refusal_reaches_the_browser_that_earned_it() -> None:
    """A signal to a peer that is not in the room is refused across the boundary."""
    _, processes = _deployment()
    sockets = [_Socket(0), _Socket(1)]
    connections, assignments = await _form(processes, sockets)

    with pytest.raises(P2PRoomError) as refused:
        await processes[0].coordinator.relay_signal(
            connections[0],
            room_handle=assignments[0].room_handle,
            request_id="request_019b6000-0000-7000-8000-000000000902",
            target_peer_handle="handle_notapeer00",
            negotiation_generation=assignments[0].negotiation_generation,
            signal_kind="offer",
            payload_json='{"sdp":"one"}',
        )
    await _stop(processes)
    assert refused.value.code == "p2p.unknown_target"


async def test_one_process_is_unchanged() -> None:
    """Both browsers on one node still form and run without touching the bus."""
    _, processes = _deployment(1)
    sockets = [_Socket(0), _Socket(1)]
    process = processes[0]
    process.link.start()
    connections = [
        await process.coordinator.connect(socket.identity, socket.send)
        for socket in sockets
    ]
    futures = [await process.coordinator.enqueue(one) for one in connections]
    assignments = list(await asyncio.wait_for(asyncio.gather(*futures), 5.0))
    await _reach_running([process, process], connections, assignments)
    await _stop([process])

    assert assignments[0].room_handle == assignments[1].room_handle
    assert len(sockets[0].of(MeshStart)) == 1
    assert len(sockets[1].of(MeshStart)) == 1


async def test_one_node_relaying_two_browsers_keeps_them_apart() -> None:
    """A node holding two browsers of one room delivers each its own effects.

    A deployment does not hand out one browser per replica. A process commonly
    holds several of a room's participants, and an effect written to the wrong one
    would hand a browser another participant's signalling -- a peer handle it must
    not have and an offer it cannot answer.
    """
    _, processes = _deployment(2, size=3)
    sockets = [_Socket(0), _Socket(1), _Socket(2)]
    holders = [processes[0], processes[0], processes[1]]
    for process in processes:
        process.link.start()
    connections = [
        await process.coordinator.connect(socket.identity, socket.send)
        for process, socket in zip(holders, sockets, strict=True)
    ]
    futures = [
        await process.coordinator.enqueue(connection)
        for process, connection in zip(holders, connections, strict=True)
    ]
    assignments = list(await asyncio.wait_for(asyncio.gather(*futures), 5.0))

    # The browser on the other node offers to exactly one of the two this node
    # holds, naming its peer handle.
    target = assignments[1].local_peer_handle
    await processes[1].coordinator.relay_signal(
        connections[2],
        room_handle=assignments[2].room_handle,
        request_id="request_019b6000-0000-7000-8000-000000000903",
        target_peer_handle=target,
        negotiation_generation=assignments[2].negotiation_generation,
        signal_kind="offer",
        payload_json='{"sdp":"for-the-second"}',
    )
    await _stop(processes)

    delivered = sockets[1].of(SignalDelivery)
    assert len(delivered) == 1
    assert delivered[0].payload_json == '{"sdp":"for-the-second"}'
    # The other browser this node holds is in the same room and was not addressed.
    assert not sockets[0].of(SignalDelivery)
