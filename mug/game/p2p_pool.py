"""Form transport-neutral authenticated browser P2P rooms.

The pool maps waiting enrollment and connection bindings onto API-06 actors and
full connection leases. It creates one room core per formed group. It owns no
socket, task, artifact store, or API-09 wire model.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from mug.game.p2p_capture import CaptureVerifier
from mug.game.p2p_room import P2PRoom
from mug.game.p2p_room_types import (
    BoundPeer,
    RoomBinding,
    RoomLimits,
    RoomRuntime,
)
from mug.interactions import FormationResult, MeshFormationService
from mug.interactions.types import ConnectionLease, FifoMatch
from mug.kernel.refs import StudyVersionRef


@dataclass(frozen=True)
class RoomPoolConfig:
    """Configure one homogeneous P2P waiting room."""

    channel_key: str
    size: int
    seed: int
    study_version: StudyVersionRef
    limits: RoomLimits
    verify_capture: CaptureVerifier


@dataclass(frozen=True)
class RoomPoolRuntime:
    """Supply the pool's only entropy and clock boundaries."""

    new_id: Callable[[str], str]
    new_handle: Callable[[], str]
    now: Callable[[], str]
    utc_now: Callable[[], datetime]
    monotonic: Callable[[], float]


@dataclass(frozen=True)
class WaitingPeer:
    """Bind one waiting enrollment to one authenticated live connection."""

    connection_id: str
    enrollment_id: str
    visit_id: str


@dataclass(frozen=True)
class RemotePeer:
    """Assign the deterministic WebRTC negotiation role for one remote peer."""

    peer_handle: str
    role: Literal["offerer", "answerer"]


@dataclass(frozen=True)
class RoomPlacement:
    """Place one waiting connection into one formed room and local peer."""

    connection_id: str
    room: P2PRoom
    local_peer_handle: str
    remote_peers: tuple[RemotePeer, ...]


@dataclass(frozen=True)
class FormedRoom:
    """Return one room and every authenticated per-connection placement."""

    room: P2PRoom
    placements: tuple[RoomPlacement, ...]


class P2PRoomPool:
    """Form live room cores from a FIFO enrollment waiting room."""

    def __init__(self, config: RoomPoolConfig, runtime: RoomPoolRuntime) -> None:
        self._config = config
        self._runtime = runtime
        self._formation = MeshFormationService(
            new_id=runtime.new_id,
            now=runtime.now,
            study_version=config.study_version,
            group_key=config.channel_key,
            channel_key=config.channel_key,
            size=config.size,
            strategy=FifoMatch(kind="fifo"),
        )
        self._waiting: dict[str, WaitingPeer] = {}

    def submit(self, peer: WaitingPeer) -> tuple[FormedRoom, ...]:
        """Submit one unique enrollment and drain every group that can form."""
        if peer.enrollment_id in self._waiting:
            raise ValueError("the enrollment is already waiting")
        self._formation.submit(
            enrollment_id=peer.enrollment_id,
            visit_id=peer.visit_id,
        )
        self._waiting[peer.enrollment_id] = peer
        formed: list[FormedRoom] = []
        while True:
            result = self._formation.poll()
            if result.status != "formed":
                return tuple(formed)
            formed.append(self._form(result))

    def release(self, enrollment_id: str) -> bool:
        """Release one waiting enrollment and return whether it was present."""
        peer = self._waiting.pop(enrollment_id, None)
        if peer is None:
            return False
        self._formation.release(enrollment_id)
        return True

    def _form(self, result: FormationResult) -> FormedRoom:
        assert result.group is not None
        assert result.interaction is not None
        assert result.membership is not None
        waiting = [self._waiting.pop(member) for member in result.group.members]
        lease_by_actor = {lease.actor_id: lease for lease in result.leases}
        room_handle = self._runtime.new_handle()
        members = tuple(
            self._bound_peer(index, peer, result, lease_by_actor)
            for index, peer in enumerate(waiting, start=1)
        )
        room = P2PRoom(
            RoomBinding(
                room_handle=room_handle,
                interaction_id=result.interaction.interaction_id,
                membership=result.membership,
                members=members,
                negotiation_generation=result.membership_generation,
                seed=self._config.seed,
            ),
            RoomRuntime(
                limits=self._config.limits,
                monotonic=self._runtime.monotonic,
                utc_now=self._runtime.utc_now,
                lease_is_current=self._formation.is_current,
                fence_lease=lambda lease: self._formation.reacquire_lease(
                    lease.interaction_id, lease
                ),
                verify_capture=self._config.verify_capture,
            ),
        )
        room.begin_signalling()
        return FormedRoom(
            room=room,
            placements=tuple(
                self._placement(room, member, members) for member in members
            ),
        )

    def _bound_peer(
        self,
        index: int,
        peer: WaitingPeer,
        result: FormationResult,
        lease_by_actor: Mapping[str, ConnectionLease],
    ) -> BoundPeer:
        seat_key = f"seat-{index}"
        actor_id = result.cast[seat_key]
        lease = lease_by_actor[actor_id]
        return BoundPeer(
            peer_handle=self._runtime.new_handle(),
            connection_id=peer.connection_id,
            enrollment_id=peer.enrollment_id,
            visit_id=peer.visit_id,
            seat_key=seat_key,
            actor_id=actor_id,
            lease=lease,
        )

    @staticmethod
    def _placement(
        room: P2PRoom, local: BoundPeer, members: tuple[BoundPeer, ...]
    ) -> RoomPlacement:
        remotes = tuple(
            RemotePeer(
                peer_handle=remote.peer_handle,
                role="offerer" if local.actor_id < remote.actor_id else "answerer",
            )
            for remote in sorted(members, key=lambda item: item.actor_id)
            if remote is not local
        )
        return RoomPlacement(
            connection_id=local.connection_id,
            room=room,
            local_peer_handle=local.peer_handle,
            remote_peers=remotes,
        )


__all__ = [
    "FormedRoom",
    "P2PRoomPool",
    "RemotePeer",
    "RoomPlacement",
    "RoomPoolConfig",
    "RoomPoolRuntime",
    "WaitingPeer",
]
