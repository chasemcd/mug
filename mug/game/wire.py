"""The peer-to-peer wire tier: drive one peer engine over a real duplex link.

The rollback engine owns GGPO state. This distributed tier drives one engine over
a duplex link to every peer. A real round trip makes the engine predict late
inputs and roll back when the real values differ.

A ``PeerLink`` carries JSON-safe messages. WebRTC supplies it in production and
an in-process latency link supplies it in tests. The codec keeps engine types out
of the transport. A lossy full-mesh test proves that every peer still reaches the
same canonical trajectory.

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
import json
from collections.abc import Callable, Mapping, Sequence
from itertools import pairwise
from typing import Any, Protocol, cast

from mug.game.mesh import EndPacket, HashPacket, InputPacket, PeerEngine
from mug.kernel import Digest

_MAX_SAFE_INTEGER = 9_007_199_254_740_991
_MAX_INPUT_HISTORY = 32
_MAX_ACTOR_ID_LENGTH = 128
_MAX_DATA_CHANNEL_MESSAGE_BYTES = 65_536


class PeerLink(Protocol):
    """A duplex channel to one peer: send and receive one json-able message.

    A WebRTC data channel satisfies this seam in production; an in-process channel
    satisfies it in a test. ``recv`` returns ``None`` when the link has closed, so a
    receive loop terminates cleanly.
    """

    async def send(self, message: Mapping[str, Any]) -> None: ...
    async def recv(self) -> dict[str, Any] | None: ...


class PeerLinkClosed(RuntimeError):
    """A peer link closed or failed before the mesh node stopped."""


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


def _closed_fields(message: Mapping[str, Any], expected: set[str]) -> None:
    """Reject a packet whose fields do not match its closed wire shape."""
    if set(message) != expected:
        raise ValueError("a peer packet has missing or unknown fields")


def _sender(message: Mapping[str, Any]) -> str:
    """Read one bounded non-empty actor identifier."""
    value = message.get("sender")
    if not isinstance(value, str) or not value or len(value) > _MAX_ACTOR_ID_LENGTH:
        raise ValueError("a peer packet sender must be a bounded string")
    return value


def _integer(value: Any, *, nonnegative: bool) -> int:
    """Read one JSON safe integer with the required sign."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("a peer packet integer field must be an integer")
    minimum = 0 if nonnegative else -_MAX_SAFE_INTEGER
    if value < minimum or value > _MAX_SAFE_INTEGER:
        raise ValueError("a peer packet integer field is outside the safe range")
    return value


def _decode_input(message: Mapping[str, Any]) -> InputPacket:
    """Decode one bounded redundant-input packet."""
    _closed_fields(message, {"kind", "sender", "current_frame", "inputs"})
    raw = message.get("inputs")
    history: Sequence[object] = (
        cast("Sequence[object]", raw) if isinstance(raw, (list, tuple)) else ()
    )
    if not 1 <= len(history) <= _MAX_INPUT_HISTORY:
        raise ValueError("an input packet needs 1 to 32 history entries")
    inputs: list[tuple[int, int]] = []
    for item in history:
        pair: Sequence[object] = (
            cast("Sequence[object]", item) if isinstance(item, (list, tuple)) else ()
        )
        if len(pair) != 2:
            raise ValueError("an input history entry must be a frame-action pair")
        inputs.append(
            (
                _integer(pair[0], nonnegative=True),
                _integer(pair[1], nonnegative=False),
            )
        )
    if any(left[0] >= right[0] for left, right in pairwise(inputs)):
        raise ValueError("input history frames must increase")
    return InputPacket(
        sender=_sender(message),
        current_frame=_integer(message.get("current_frame"), nonnegative=True),
        inputs=tuple(inputs),
    )


def decode(message: Mapping[str, Any]) -> InputPacket | HashPacket | EndPacket:
    """Decode and validate one closed peer-engine packet."""
    kind = message.get("kind")
    if kind == "input":
        return _decode_input(message)
    if kind == "hash":
        _closed_fields(message, {"kind", "sender", "frame_number", "state_hash"})
        raw = message.get("state_hash")
        if not isinstance(raw, Mapping):
            raise ValueError("a hash packet needs a state_hash object")
        return HashPacket(
            sender=_sender(message),
            frame_number=_integer(message.get("frame_number"), nonnegative=True),
            state_hash=Digest.model_validate(raw),
        )
    if kind == "end":
        _closed_fields(message, {"kind", "sender", "end_frame_exclusive"})
        return EndPacket(
            sender=_sender(message),
            end_frame_exclusive=_integer(
                message.get("end_frame_exclusive"), nonnegative=True
            ),
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
        self._inbound: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()
        self._receivers: list[asyncio.Task[None]] = []
        self._receive_failure: Exception | None = None

    @property
    def engine(self) -> PeerEngine:
        """Return the engine this node drives, for reading its trajectory."""
        return self._engine

    def start(self) -> None:
        """Start one background receive loop per link, filling the inbound queue."""
        if self._receivers:
            return
        for remote, link in self._links.items():
            self._receivers.append(asyncio.create_task(self._receive(remote, link)))

    async def _receive(self, remote: str, link: PeerLink) -> None:
        """Bind every received message to the authenticated remote link."""
        try:
            while True:
                message = await link.recv()
                if message is None:
                    raise PeerLinkClosed("a peer data channel closed")
                await self._inbound.put((remote, message))
        except asyncio.CancelledError:
            raise
        except Exception as error:
            if self._receive_failure is None:
                self._receive_failure = error

    def _raise_receive_failure(self) -> None:
        """Raise the first receive failure at the deterministic tick boundary."""
        if self._receive_failure is not None:
            raise self._receive_failure

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
                remote, message = self._inbound.get_nowait()
            except asyncio.QueueEmpty:
                return
            packet = decode(message)
            if packet.sender != remote:
                raise ValueError("a peer packet sender does not match its data channel")
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
        self._raise_receive_failure()
        self._drain_inbound()
        if not self._engine.ended():
            packet = self._engine.submit_local(int(self._action()))
            await self._broadcast(encode_input(packet))
        self._engine.advance()
        await self._gossip()
        await asyncio.sleep(0)
        self._raise_receive_failure()

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


# -- the WebRTC data-channel adapter -------------------------------------------


class DataChannel(Protocol):
    """The subset of a WebRTC data channel the adapter drives.

    An aiortc channel satisfies this seam directly. A browser adapter normalizes its
    event objects and ``addEventListener`` API to this additive ``on`` API. The
    adapter names no vendor type, so a fake channel proves it with no real network.
    """

    @property
    def readyState(self) -> str: ...

    def send(self, data: str) -> None: ...
    def on(self, event: str, handler: Callable[..., Any]) -> Any: ...


class DataChannelLink:
    """Adapt one WebRTC data channel to the ``PeerLink`` seam.

    The link json-frames each message the codec produced and sends it as text, the
    shape a data channel carries. It registers a message handler that enqueues each
    arrived message, so ``recv`` awaits the inbound queue rather than the channel;
    the channel pushes, so no receive loop reads it. A close enqueues a ``None``
    sentinel, so ``recv`` returns ``None`` once the channel has closed and the
    driving node's receive loop ends cleanly.

    The adapter holds no socket and imports no vendor SDK: the study passes the
    concrete ``aiortc`` (or browser-bridged) channel, and a test passes a fake one
    that duck-types the same two methods. So the wire tier reaches a real peer
    process in production and stays deterministic under test.
    """

    def __init__(self, channel: DataChannel) -> None:
        self._channel = channel
        self._failed = False
        self._inbound: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        channel.on("message", self._on_message)
        channel.on("close", self._on_close)
        channel.on("error", self._on_error)

    def _on_message(self, data: str | bytes) -> None:
        """Decode one arrived text (or binary) message onto the inbound queue.

        A non-object message (an array, a bare number, malformed text) is dropped,
        so a stray frame never becomes a half-formed packet the codec must reject.
        """
        try:
            encoded = data if isinstance(data, bytes) else data.encode("utf-8")
            if len(encoded) > _MAX_DATA_CHANNEL_MESSAGE_BYTES:
                self._fail()
                return
            text = encoded.decode("utf-8")
            loaded = json.loads(text)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return
        if isinstance(loaded, dict):
            self._inbound.put_nowait(cast("dict[str, Any]", loaded))

    def _on_close(self) -> None:
        """Enqueue the close sentinel, so ``recv`` reports the channel has closed."""
        self._inbound.put_nowait(None)

    def _on_error(self, *_: object) -> None:
        """Fail the link when its channel reports a transport error."""
        self._fail()

    def _fail(self) -> None:
        """Fail this link and wake its receiver once."""
        if self._failed:
            return
        self._failed = True
        self._inbound.put_nowait(None)

    @property
    def is_open(self) -> bool:
        """Return whether the data channel is open now."""
        return not self._failed and self._channel.readyState == "open"

    async def send(self, message: Mapping[str, Any]) -> None:
        """Send one json-able message to the peer as compact text."""
        text = json.dumps(message, separators=(",", ":"))
        if len(text.encode("utf-8")) > _MAX_DATA_CHANNEL_MESSAGE_BYTES:
            raise ValueError("a peer data-channel message exceeds 65536 bytes")
        self._channel.send(text)

    async def recv(self) -> dict[str, Any] | None:
        """Return the next arrived message, or ``None`` once the channel has closed."""
        return await self._inbound.get()


__all__ = [
    "DataChannel",
    "DataChannelLink",
    "PeerLink",
    "PeerLinkClosed",
    "PeerNode",
    "SeatAction",
    "decode",
    "encode_end",
    "encode_hash",
    "encode_input",
]
