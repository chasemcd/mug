"""One deployment, several processes, and what has to cross between them.

A deployment behind a load balancer is several processes, and a participant's
socket belongs to exactly one of them. Everything a study does with one person at a
time is unaffected. Everything a study does with two people at once is not: they
have to be matched, one process has to run what they do together, and the frames of
that run have to reach a socket that process does not hold.

Three things solve it, and they are deliberately separate.

- **Where they meet.** ``mug.interactions.rendezvous`` puts the waiting list and the
  room registry in the shared store, so a match is made from everyone who is
  waiting rather than from everyone this process happens to hold.
- **How a message gets there.** ``mug.interactions.bus`` carries one message from
  one process to another.
- **Who is doing what.** This module. It names a process (``Node``), and it holds
  the two proxies that let one node run something on another node's behalf: a seat
  whose person is somewhere else, and a socket that is somewhere else.

**The owner runs it; every other node relays.** When a group is claimed, the
claiming process owns the room: it holds the engines, or the room core, and it is
the only place the authority lives. A process holding another member's socket keeps
no state about the run at all -- it passes what its participant did to the owner and
writes what the owner sends back. So there is one authority per room and no
agreement to reach.

**What it costs is one hop.** A remote seat's action and a remote seat's frame each
cross the bus once. Over ``LocalBus`` (one process) that is a function call. Over
``StoreBus`` it is a durable write, which is honest for signalling and slow for
frames; a deployment that runs stepped games across processes should implement
``NodeBus`` over its own broker. The seam is there so that is a mount, not a
rewrite.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import asdict, dataclass
from typing import Any, cast

from mug.client.ice import IceGrant
from mug.game.p2p_room_types import (
    MeshAbort,
    MeshFinish,
    MeshStart,
    RoomEffect,
    SignalDelivery,
)
from mug.interactions.bus import NodeLink
from mug.interactions.rendezvous import DurableRendezvous
from mug.kernel import Digest
from mug.participant_p2p_types import PeerAssignment, RoomAssignment, RoomEnd

# What the owner tells a node holding one of its sockets, and what comes back.
SEATED = "mesh.seated"
INPUT = "mesh.input"
FRAME = "mesh.frame"
ENDED = "mesh.ended"


@dataclass(frozen=True)
class Node:
    """One process of a deployment: its address, its bus, and the shared room.

    A mount that is given a ``Node`` spans processes; a mount that is not given one
    keeps everything in memory and behaves exactly as it did before. That is the
    whole of the switch, so a single-process deployment pays nothing.
    """

    node_id: str
    link: NodeLink
    rendezvous: DurableRendezvous

    def owns(self, owner_node: str) -> bool:
        """Report whether this process is the one that runs a given room."""
        return owner_node == self.node_id


class RemoteSeat:
    """The owner's stand-in for a seat whose person is on another node.

    ``action`` is what the mesh reads each tick. It returns the last action that
    node published, which is exactly what a local seat's own held action means: the
    input that was current when the tick came round. A seat that has published
    nothing yet holds the game's default, so a mesh starts without waiting for
    anyone's first keystroke.

    ``send`` is the frame sink. It puts the frame on the bus addressed to the node
    that holds the socket, and does not wait to hear that it arrived: a frame is
    worth less the later it lands, and a run must not stall on one slow node.
    """

    def __init__(
        self,
        link: NodeLink,
        *,
        node_id: str,
        room_handle: str,
        connection_id: str,
        default_action: int,
    ) -> None:
        self._link = link
        self._node_id = node_id
        self._room_handle = room_handle
        self._connection_id = connection_id
        self._held = default_action

    def apply(self, action: int) -> None:
        """Record the action that node's participant is now holding."""
        self._held = action

    def action(self) -> int:
        """Return the action this seat is holding, as the mesh reads it."""
        return self._held

    async def send(self, frame: dict[str, Any]) -> None:
        """Put one frame on the bus for the node that holds this seat's socket."""
        await self._link.tell(
            self._node_id,
            FRAME,
            {
                "room_handle": self._room_handle,
                "connection_id": self._connection_id,
                "frame": dict(frame),
            },
        )


class SeatRelay:
    """The other node's side: sample the local input, and write what comes back.

    The owner needs this seat's action every tick and cannot call into this
    process to get it, so the relay samples the held action at the game's own rate
    and publishes it **when it changes**. A participant holding a key still sends
    one message, not one per tick.
    """

    def __init__(
        self,
        link: NodeLink,
        *,
        owner_node: str,
        room_handle: str,
        connection_id: str,
        action: Callable[[], int],
        send: Callable[[dict[str, Any]], Awaitable[None]],
        fps: int,
    ) -> None:
        self._link = link
        self._owner = owner_node
        self._room_handle = room_handle
        self._connection_id = connection_id
        self._action = action
        self.send = send
        self._interval = 1.0 / fps if fps > 0 else 0.02
        self._task: asyncio.Task[None] | None = None
        self._last: int | None = None

    def start(self) -> None:
        """Begin sampling this seat's input for the node that runs the room."""
        if self._task is None:
            self._task = asyncio.create_task(self._sample())

    async def stop(self) -> None:
        """Stop sampling, and wait for the sampler to finish."""
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def publish(self, action: int) -> None:
        """Tell the owner this seat is now holding one action."""
        self._last = action
        await self._link.tell(
            self._owner,
            INPUT,
            {
                "room_handle": self._room_handle,
                "connection_id": self._connection_id,
                "action": action,
            },
        )

    async def _sample(self) -> None:
        """Publish this seat's held action whenever it changes, at the game rate."""
        while True:
            held = self._action()
            if held != self._last:
                await self.publish(held)
            await asyncio.sleep(self._interval)


def frame_of(message: Mapping[str, Any]) -> dict[str, Any]:
    """Read the frame out of one relayed message."""
    return cast("dict[str, Any]", message.get("frame", {}))


# -- the browser peer-to-peer tunnel -------------------------------------------
#
# A browser mesh needs far less across the boundary than a stepped game does: the
# browsers hold the engines and talk to each other directly, so only the
# negotiation crosses. What crosses is the API-09 exchange itself -- one browser's
# frame in, one room effect out -- so the node that holds the socket needs no room
# state at all and the node that runs the room needs no socket.

P2P_SEATED = "p2p.seated"
P2P_CALL = "p2p.call"
P2P_EFFECT = "p2p.effect"
P2P_END = "p2p.end"
P2P_ICE = "p2p.ice"

_EFFECTS: Mapping[str, type[RoomEffect]] = {
    "signal": SignalDelivery,
    "start": MeshStart,
    "abort": MeshAbort,
    "finish": MeshFinish,
}


def effect_as_json(effect: RoomEffect) -> dict[str, Any]:
    """Serialize one room effect so another node can deliver it to its socket."""
    kind = next(name for name, cls in _EFFECTS.items() if isinstance(effect, cls))
    body = asdict(effect)
    if isinstance(effect, MeshFinish):
        body["trajectory_digest"] = effect.trajectory_digest.model_dump(mode="json")
    return {"kind": kind, "effect": body}


def effect_of_json(body: Mapping[str, Any]) -> RoomEffect:
    """Rebuild one room effect from what the node that runs the room sent."""
    kind = cast("str", body["kind"])
    fields = dict(cast("Mapping[str, Any]", body["effect"]))
    for name in ("connection_ids",):
        if name in fields:
            fields[name] = tuple(cast("list[Any]", fields[name]))
    if kind == "finish":
        fields["trajectory_digest"] = Digest.model_validate(fields["trajectory_digest"])
    return _EFFECTS[kind](**fields)


def assignment_as_json(assignment: RoomAssignment) -> dict[str, Any]:
    """Serialize one room assignment, without the future the sender waits on.

    The wait belongs to whichever node holds the socket, so the receiver makes its
    own future. Everything else is what the browser is told, and it is told the
    same thing wherever it happens to be connected.
    """
    return {
        "room_handle": assignment.room_handle,
        "local_peer_handle": assignment.local_peer_handle,
        "capture_owner_handle": assignment.capture_owner_handle,
        "negotiation_generation": assignment.negotiation_generation,
        "peers": [
            {"peer_handle": peer.peer_handle, "role": peer.role}
            for peer in assignment.peers
        ],
        "validation_timeout_ms": assignment.validation_timeout_ms,
        "ice_grant": {
            "handle": assignment.ice_grant.handle,
            "expires_at": assignment.ice_grant.expires_at,
        },
        "ice_endpoint": assignment.ice_endpoint,
    }


def assignment_of_json(body: Mapping[str, Any]) -> RoomAssignment:
    """Rebuild one room assignment on the node that holds the browser's socket."""
    grant = cast("Mapping[str, Any]", body["ice_grant"])
    return RoomAssignment(
        room_handle=cast("str", body["room_handle"]),
        local_peer_handle=cast("str", body["local_peer_handle"]),
        capture_owner_handle=cast("str", body["capture_owner_handle"]),
        negotiation_generation=int(cast("int", body["negotiation_generation"])),
        peers=tuple(
            PeerAssignment(
                peer_handle=cast("str", peer["peer_handle"]),
                role=cast("Any", peer["role"]),
            )
            for peer in cast("list[Mapping[str, Any]]", body["peers"])
        ),
        validation_timeout_ms=int(cast("int", body["validation_timeout_ms"])),
        ice_grant=IceGrant(
            handle=cast("str", grant["handle"]),
            expires_at=cast("str", grant["expires_at"]),
        ),
        ice_endpoint=cast("str", body["ice_endpoint"]),
        ended=asyncio.get_running_loop().create_future(),
    )


def end_as_json(end: RoomEnd) -> dict[str, Any]:
    """Serialize how one room ended, for the node that must tell its browser."""
    return {
        "kind": end.kind,
        "disposition": end.disposition,
        "capture_receipt": end.capture_receipt,
    }


def end_of_json(body: Mapping[str, Any]) -> RoomEnd:
    """Rebuild how one room ended from what the node that ran it sent."""
    return RoomEnd(
        kind=cast("Any", body["kind"]),
        disposition=cast("Any", body["disposition"]),
        capture_receipt=cast("str | None", body.get("capture_receipt")),
    )


__all__ = [
    "ENDED",
    "FRAME",
    "INPUT",
    "P2P_CALL",
    "P2P_EFFECT",
    "P2P_END",
    "P2P_ICE",
    "P2P_SEATED",
    "SEATED",
    "Node",
    "RemoteSeat",
    "SeatRelay",
    "assignment_as_json",
    "assignment_of_json",
    "effect_as_json",
    "effect_of_json",
    "end_as_json",
    "end_of_json",
    "frame_of",
]
