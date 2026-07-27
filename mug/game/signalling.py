"""Open WebRTC data channels through a formed room's signalling relay.

Injected seams carry offer, answer, and ICE messages. A production edge adds
authenticated sockets, current leases, and membership fencing. This module
imports no vendor SDK.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable, Mapping
from typing import Any, Literal, Protocol, cast

from mug.game.wire import DataChannel, DataChannelLink

Role = Literal["offerer", "answerer"]
SignalMessage = dict[str, Any]

_CHANNEL_LABEL = "mug-mesh-data"
_CHANNEL_OPTIONS: Mapping[str, bool | int] = {"ordered": False, "maxRetransmits": 0}


class SignallingClosed(RuntimeError):
    """The signalling or RTC path closed before negotiation completed."""


class SignallingTimeout(RuntimeError):
    """The data channel did not open before the handshake deadline."""


class SignalChannel(Protocol):
    """Carry one handshake through cancellation-cooperative async operations."""

    async def send(self, message: Mapping[str, Any]) -> None: ...
    async def recv(self) -> dict[str, Any] | None: ...


class RtcConnection(Protocol):
    """Expose normalized JSON, additive events, and idempotent async closure.

    Awaitable adapter methods must propagate task cancellation.
    """

    @property
    def connectionState(self) -> str: ...

    def createDataChannel(
        self, label: str, options: Mapping[str, bool | int]
    ) -> DataChannel: ...

    async def createOffer(self) -> Mapping[str, Any]: ...
    async def createAnswer(self) -> Mapping[str, Any]: ...
    async def setLocalDescription(self, description: Mapping[str, Any]) -> None: ...
    async def setRemoteDescription(self, description: Mapping[str, Any]) -> None: ...
    async def addIceCandidate(self, candidate: Mapping[str, Any] | None) -> None: ...
    async def close(self) -> None: ...
    def on(self, event: str, handler: Callable[..., Any]) -> Any: ...


class _Handshake:
    def __init__(
        self, connection: RtcConnection, signal: SignalChannel, role: Role
    ) -> None:
        self.connection = connection
        self.signal = signal
        self.role = role
        self.ready = asyncio.Event()
        self.local_description_sent = asyncio.Event()
        self.local_candidates: asyncio.Queue[SignalMessage] = asyncio.Queue()
        self.pending_remote: list[SignalMessage | None] = []
        self.pending_local = 0
        self.remote_description_set = False
        self.channel_open = False
        self.negotiated = False
        self.completed = False
        self.active = True
        self.accepting_candidates = True
        self.error: BaseException | None = None
        self.link: DataChannelLink | None = None

    def fail(self, error: BaseException) -> None:
        if self.completed or self.error is not None:
            return
        self.error = error
        self.ready.set()

    def finish_if_ready(self) -> None:
        if (
            self.error is None
            and self.link is not None
            and self.channel_open
            and self.negotiated
            and self.pending_local == 0
        ):
            self.ready.set()

    def bind(self, channel: DataChannel) -> None:
        if not self.active:
            return
        if self.link is not None:
            self.fail(RuntimeError("the RTC connection created two data channels"))
            return
        self.link = DataChannelLink(channel)
        channel.on("open", self._opened)
        channel.on("close", self._closed)
        channel.on("error", self._channel_error)
        if channel.readyState == "open":
            self._opened()
        elif channel.readyState == "closed":
            self._closed()

    def local_ice(self, candidate: Mapping[str, Any] | None) -> None:
        if not self.active or not self.accepting_candidates:
            return
        self.pending_local += 1
        message: SignalMessage = {"kind": "end_of_candidates"}
        if candidate is not None:
            message = {"kind": "candidate", "candidate": dict(candidate)}
        self.local_candidates.put_nowait(message)

    def connection_changed(self, *_: object) -> None:
        state = self.connection.connectionState
        if self.active and state in {"closed", "failed"}:
            self.fail(SignallingClosed(f"RTC connection entered {state!r}"))

    def _opened(self, *_: object) -> None:
        self.channel_open = True
        self.finish_if_ready()

    def _closed(self, *_: object) -> None:
        if self.active and not self.completed:
            self.fail(SignallingClosed("data channel closed before negotiation"))

    def _channel_error(self, *_: object) -> None:
        if self.active and not self.completed:
            self.fail(SignallingClosed("data channel failed during negotiation"))

    async def send_candidates(self) -> None:
        try:
            while True:
                message = await self.local_candidates.get()
                await self.local_description_sent.wait()
                await self.signal.send(message)
                self.pending_local -= 1
                self.finish_if_ready()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.fail(error)

    async def pump(self) -> None:
        try:
            while True:
                message = await self.signal.recv()
                if message is None:
                    self.fail(
                        SignallingClosed(
                            "signalling closed before negotiation completed"
                        )
                    )
                    return
                await self.apply(message)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.fail(error)

    async def apply(self, message: Mapping[str, Any]) -> None:
        kind = message.get("kind")
        if kind == "offer":
            if self.role != "answerer" or self.remote_description_set:
                raise ValueError("unexpected signalling offer")
            await self._set_remote(_object_field(message, "description"))
            answer = await self.connection.createAnswer()
            await self.connection.setLocalDescription(answer)
            await self.signal.send({"kind": "answer", "description": dict(answer)})
            self.local_description_sent.set()
            self.negotiated = True
            self.finish_if_ready()
        elif kind == "answer":
            if self.role != "offerer" or self.remote_description_set:
                raise ValueError("unexpected signalling answer")
            await self._set_remote(_object_field(message, "description"))
            self.negotiated = True
            self.finish_if_ready()
        elif kind == "candidate":
            candidate = _object_field(message, "candidate")
            if self.remote_description_set:
                await self.connection.addIceCandidate(candidate)
            else:
                self.pending_remote.append(candidate)
        elif kind == "end_of_candidates":
            if self.remote_description_set:
                await self.connection.addIceCandidate(None)
            else:
                self.pending_remote.append(None)
        else:
            raise ValueError(f"unknown signalling message kind: {kind!r}")

    async def _set_remote(self, description: Mapping[str, Any]) -> None:
        await self.connection.setRemoteDescription(description)
        self.remote_description_set = True
        pending = self.pending_remote
        self.pending_remote = []
        for candidate in pending:
            await self.connection.addIceCandidate(candidate)


def _object_field(message: Mapping[str, Any], field: str) -> dict[str, Any]:
    value = message.get(field)
    if not isinstance(value, Mapping):
        raise ValueError(f"signalling message needs an object field {field!r}")
    result: dict[str, Any] = {}
    for key, item in cast("Mapping[object, object]", value).items():
        if not isinstance(key, str):
            raise ValueError(f"signalling field {field!r} needs string keys")
        result[key] = item
    return result


async def _send_offer(handshake: _Handshake) -> None:
    channel = handshake.connection.createDataChannel(
        _CHANNEL_LABEL, dict(_CHANNEL_OPTIONS)
    )
    handshake.bind(channel)
    offer = await handshake.connection.createOffer()
    await handshake.connection.setLocalDescription(offer)
    await handshake.signal.send({"kind": "offer", "description": dict(offer)})
    handshake.local_description_sent.set()


async def _stop_tasks(*tasks: asyncio.Task[None]) -> None:
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


async def _run_handshake(handshake: _Handshake) -> DataChannelLink:
    pump = asyncio.create_task(handshake.pump())
    candidates = asyncio.create_task(handshake.send_candidates())
    try:
        if handshake.role == "offerer" and handshake.error is None:
            await _send_offer(handshake)
        await handshake.ready.wait()
        if handshake.error is not None:
            raise handshake.error
        if handshake.link is None:
            raise RuntimeError("signalling completed without a data channel")
        return handshake.link
    finally:
        handshake.accepting_candidates = False
        await _stop_tasks(pump, candidates)


def _link_is_ready(connection: RtcConnection, link: DataChannelLink) -> bool:
    return link.is_open and connection.connectionState not in {"closed", "failed"}


async def establish_data_channel(
    *,
    connection: RtcConnection,
    signal: SignalChannel,
    role: Role,
    timeout_seconds: float = 15.0,
) -> DataChannelLink:
    """Negotiate one data channel and return its open ``PeerLink`` adapter."""
    if timeout_seconds <= 0:
        raise ValueError("the signalling timeout must be positive")
    if role not in {"offerer", "answerer"}:
        raise ValueError(f"unknown signalling role: {role!r}")

    handshake = _Handshake(connection, signal, role)
    succeeded = False
    try:
        connection.on("icecandidate", handshake.local_ice)
        connection.on("connectionstatechange", handshake.connection_changed)
        handshake.connection_changed()
        if role == "answerer":
            connection.on("datachannel", handshake.bind)
        link = await asyncio.wait_for(_run_handshake(handshake), timeout_seconds)
        if handshake.error is not None:
            raise handshake.error
        if not _link_is_ready(connection, link):
            raise SignallingClosed("the data channel failed before handoff")
        handshake.completed = True
        succeeded = True
        return link
    except asyncio.TimeoutError as error:
        raise SignallingTimeout("data channel handshake timed out") from error
    finally:
        handshake.active = False
        if not succeeded:
            with contextlib.suppress(Exception):
                await connection.close()


def role_for(local: str, remote: str) -> Role:
    """Assign the lower actor ID to offer and the higher actor ID to answer."""
    if local == remote:
        raise ValueError("a peer cannot open a data channel to itself")
    return "offerer" if local < remote else "answerer"


async def open_peer_links(
    *,
    local: str,
    connections: Mapping[str, RtcConnection],
    signal_for: Callable[[str], SignalChannel],
    timeout_seconds: float = 15.0,
) -> dict[str, DataChannelLink]:
    """Open ``local``'s pairwise links to every remote peer concurrently."""
    if local in connections:
        raise ValueError("the connection map must not contain the local peer")
    if not connections:
        raise ValueError("a peer needs at least one remote connection")

    async def open_one(
        remote: str, connection: RtcConnection
    ) -> tuple[str, DataChannelLink]:
        link = await establish_data_channel(
            connection=connection,
            signal=signal_for(remote),
            role=role_for(local, remote),
            timeout_seconds=timeout_seconds,
        )
        return remote, link

    tasks = [
        asyncio.create_task(open_one(remote, connection))
        for remote, connection in connections.items()
    ]
    try:
        links = dict(await asyncio.gather(*tasks))
        if not all(
            _link_is_ready(connections[remote], link) for remote, link in links.items()
        ):
            raise SignallingClosed("a data channel closed before the mesh was ready")
        return links
    except (Exception, asyncio.CancelledError):
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.gather(
            *(connection.close() for connection in connections.values()),
            return_exceptions=True,
        )
        raise


__all__ = [
    "Role",
    "RtcConnection",
    "SignalChannel",
    "SignalMessage",
    "SignallingClosed",
    "SignallingTimeout",
    "establish_data_channel",
    "open_peer_links",
    "role_for",
]
