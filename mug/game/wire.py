"""The peer-to-peer wire tier: drive one peer engine over a real duplex link.

The rollback engine (``mug.game.mesh``) owns the GGPO contract; the synchronous
coordinator (``mug.game.mesh_session``) hosts every engine in one process and
relays the packets the same tick, so no engine ever predicts. This module is the
distributed tier: it moves one engine to its own peer process and drives it over a
duplex link to each other peer, the shape a WebRTC ``DataChannel`` provides. Now
the round trip is real -- a peer's input arrives a few frames late -- so the engine
predicts the missing input and rolls back when the real input contradicts the
prediction, exactly the path it already owns.

The tier is transport-neutral. A ``PeerLink`` is any duplex channel that sends and
receives one json-able message: a WebRTC data channel in production, an in-process
latency-and-loss channel in a test. The codec turns each engine packet into a
json-able message and back, so the link never sees an engine type. So a test drives
a full mesh of nodes over in-process links that inject latency and drop packets,
with no socket and no real network, and proves the peers still reach a byte-
identical canonical trajectory.

The node re-announces its end frame every tick once its local episode has ended, so
the minimum-end-frame barrier still closes even when a control message is dropped:
the input path tolerates loss through the packet's own redundancy, and the end path
tolerates it through repetition. When every peer's end frame has arrived, the node
finalizes on the shared barrier and its engine holds the same canonical trajectory
every other peer's engine holds.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable, Mapping
from typing import Any, Protocol

from mug.game.mesh import EndPacket, HashPacket, InputPacket, PeerEngine
from mug.kernel import Digest


class PeerLink(Protocol):
    """A duplex channel to one peer: send and receive one json-able message.

    A WebRTC data channel satisfies this seam in production; an in-process channel
    satisfies it in a test. ``recv`` returns ``None`` when the link has closed, so a
    receive loop terminates cleanly.
    """

    async def send(self, message: Mapping[str, Any]) -> None: ...
    async def recv(self) -> dict[str, Any] | None: ...


# -- the packet codec ----------------------------------------------------------


def encode_input(packet: InputPacket) -> dict[str, Any]:
    """Encode one input packet as a json-able wire message."""
    return {
        "kind": "input",
        "sender": packet.sender,
        "current_frame": packet.current_frame,
        "inputs": [[frame, action] for frame, action in packet.inputs],
    }


def encode_hash(packet: HashPacket) -> dict[str, Any]:
    """Encode one state-hash packet as a json-able wire message."""
    return {
        "kind": "hash",
        "sender": packet.sender,
        "frame_number": packet.frame_number,
        "state_hash": {
            "algorithm": packet.state_hash.algorithm,
            "hex": packet.state_hash.hex,
        },
    }


def encode_end(packet: EndPacket) -> dict[str, Any]:
    """Encode one end-frame packet as a json-able wire message."""
    return {
        "kind": "end",
        "sender": packet.sender,
        "end_frame_exclusive": packet.end_frame_exclusive,
    }


def decode(message: Mapping[str, Any]) -> InputPacket | HashPacket | EndPacket:
    """Decode a wire message back into its engine packet.

    The ``kind`` discriminator names the packet. An unknown kind raises, so a
    malformed message never silently becomes an empty packet.
    """
    kind = message.get("kind")
    if kind == "input":
        inputs = tuple(
            (int(frame), int(action)) for frame, action in message["inputs"]
        )
        return InputPacket(
            sender=str(message["sender"]),
            current_frame=int(message["current_frame"]),
            inputs=inputs,
        )
    if kind == "hash":
        raw = message["state_hash"]
        return HashPacket(
            sender=str(message["sender"]),
            frame_number=int(message["frame_number"]),
            state_hash=Digest(algorithm=raw["algorithm"], hex=raw["hex"]),
        )
    if kind == "end":
        return EndPacket(
            sender=str(message["sender"]),
            end_frame_exclusive=int(message["end_frame_exclusive"]),
        )
    raise ValueError(f"unknown wire message kind: {kind!r}")


# The transport supplies the seat's currently held action each tick.
SeatAction = Callable[[], int]


class PeerNode:
    """Drive one peer engine over a duplex link to each other peer.

    The node owns one engine and one ``PeerLink`` per other peer. Each tick it reads
    the seat's held action, submits it, encodes the input packet, and sends it to
    every peer; it drains whatever messages have arrived and routes them into the
    engine; it advances the engine one frame; and it sends the confirmed-frame
    hashes and, once ended, its end packet. A background receive loop per link keeps
    the inbound queue filled, so a late packet is delivered on a later tick and the
    engine predicts and rolls back on its own schedule.
    """

    def __init__(
        self,
        *,
        engine: PeerEngine,
        actor_id: str,
        links: Mapping[str, PeerLink],
        action: SeatAction,
    ) -> None:
        self._engine = engine
        self._actor_id = actor_id
        self._links = dict(links)
        self._action = action
        self._inbound: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._receivers: list[asyncio.Task[None]] = []

    @property
    def engine(self) -> PeerEngine:
        """Return the engine this node drives, for reading its trajectory."""
        return self._engine

    def start(self) -> None:
        """Start one background receive loop per link, filling the inbound queue."""
        if self._receivers:
            return
        for link in self._links.values():
            self._receivers.append(asyncio.create_task(self._receive(link)))

    async def _receive(self, link: PeerLink) -> None:
        """Move every message from one link into the shared inbound queue."""
        while True:
            message = await link.recv()
            if message is None:
                return
            await self._inbound.put(message)

    async def _broadcast(self, message: Mapping[str, Any]) -> None:
        """Send one message to every peer link."""
        for link in self._links.values():
            await link.send(message)

    def _drain_inbound(self) -> None:
        """Route every message that has arrived so far into the engine.

        The drain never awaits, so no packet interleaves an engine step or a
        rollback replay: the engine's atomicity invariant holds over the wire.
        """
        while True:
            try:
                message = self._inbound.get_nowait()
            except asyncio.QueueEmpty:
                return
            packet = decode(message)
            if isinstance(packet, InputPacket):
                self._engine.receive_input(packet)
            elif isinstance(packet, HashPacket):
                self._engine.receive_hash(packet)
            else:
                self._engine.receive_end(packet)

    async def tick(self) -> None:
        """Run one frame: drain, submit the local input, advance, gossip.

        The order matches the coordinator's: this frame's inputs from prior ticks
        are drained first, then the local input is submitted and broadcast, the
        engine advances one frame, and the outbound hashes and end packet are sent.
        A yield to the event loop lets the receive loops enqueue newly arrived
        messages before the next tick drains them.
        """
        self._drain_inbound()
        if not self._engine.ended():
            packet = self._engine.submit_local(int(self._action()))
            await self._broadcast(encode_input(packet))
        self._engine.advance()
        await self._gossip()
        await asyncio.sleep(0)

    async def _gossip(self) -> None:
        """Send the newly confirmed hashes and, once ended, re-announce the end."""
        for hash_packet in self._engine.outbound_hashes():
            await self._broadcast(encode_hash(hash_packet))
        end_packet = self._engine.announce_end()
        if end_packet is not None:
            await self._broadcast(encode_end(end_packet))

    def ready_to_finalize(self) -> bool:
        """Return whether every peer's end frame has arrived, so finalize is ready."""
        return self._engine.ended() and self._engine.all_ends_known()

    def finalize(self) -> None:
        """Close the episode on the shared minimum-end-frame barrier."""
        self._engine.finalize()

    async def stop(self) -> None:
        """Cancel the receive loops; a caller invokes it once the mesh is done."""
        for task in self._receivers:
            task.cancel()
        for task in self._receivers:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._receivers.clear()


__all__ = [
    "PeerLink",
    "PeerNode",
    "SeatAction",
    "decode",
    "encode_end",
    "encode_hash",
    "encode_input",
]
