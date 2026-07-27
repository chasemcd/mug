"""Route opaque WebRTC signalling messages within one frozen room."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Collection, Mapping
from typing import Any

from mug.game.signalling import SignalChannel, SignallingClosed, SignalMessage

_MAX_MEMBERS = 16
_MAX_MESSAGE_BYTES = 65_536
_MAX_PENDING_PER_PAIR = 64


class SignalRelay:
    """Route opaque messages only between members of one frozen room."""

    def __init__(self, members: Collection[str]) -> None:
        if isinstance(members, str):
            raise ValueError("relay members must be a collection of actor IDs")
        frozen = frozenset(members)
        if (
            len(frozen) < 2
            or len(frozen) > _MAX_MEMBERS
            or len(frozen) != len(members)
            or any(not member for member in frozen)
        ):
            raise ValueError("a signal relay needs 2 to 16 unique members")
        self._members = frozen
        self._inboxes: dict[tuple[str, str], asyncio.Queue[SignalMessage]] = {}
        self._closed = asyncio.Event()

    def _inbox(self, recipient: str, sender: str) -> asyncio.Queue[SignalMessage]:
        key = (recipient, sender)
        queue = self._inboxes.get(key)
        if queue is None:
            queue = asyncio.Queue[SignalMessage](maxsize=_MAX_PENDING_PER_PAIR)
            self._inboxes[key] = queue
        return queue

    async def _route(
        self, sender: str, recipient: str, message: Mapping[str, Any]
    ) -> None:
        if self._closed.is_set():
            raise SignallingClosed("the signalling room is closed")
        stamped: SignalMessage = dict(message)
        stamped["from"] = sender
        stamped["to"] = recipient
        try:
            size = len(
                json.dumps(stamped, ensure_ascii=False, separators=(",", ":")).encode()
            )
        except (TypeError, ValueError) as error:
            raise ValueError("a signalling message must be JSON-compatible") from error
        if size > _MAX_MESSAGE_BYTES:
            raise ValueError("a signalling message exceeds 65536 bytes")
        try:
            self._inbox(recipient, sender).put_nowait(stamped)
        except asyncio.QueueFull as error:
            raise SignallingClosed("the signalling pair inbox is full") from error

    def channel(self, *, local: str, remote: str) -> SignalChannel:
        """Return the pairwise channel from ``local`` to ``remote``."""
        if local == remote:
            raise ValueError("a relay channel needs two different members")
        if local not in self._members or remote not in self._members:
            raise ValueError("both relay endpoints must be room members")
        return _RelayChannel(
            inbound=self._inbox(local, remote),
            send=lambda message: self._route(local, remote, message),
            closed=self._closed,
        )

    def close(self) -> None:
        """Close the room and wake every current or future receiver."""
        if self._closed.is_set():
            return
        for queue in self._inboxes.values():
            while not queue.empty():
                queue.get_nowait()
        self._closed.set()


class _RelayChannel:
    def __init__(
        self,
        *,
        inbound: asyncio.Queue[SignalMessage],
        send: Callable[[Mapping[str, Any]], Awaitable[None]],
        closed: asyncio.Event,
    ) -> None:
        self._inbound = inbound
        self._send = send
        self._closed = closed

    async def send(self, message: Mapping[str, Any]) -> None:
        await self._send(message)

    async def recv(self) -> dict[str, Any] | None:
        if self._closed.is_set():
            return None
        incoming = asyncio.create_task(self._inbound.get())
        closed = asyncio.create_task(self._closed.wait())
        try:
            done, _ = await asyncio.wait(
                (incoming, closed), return_when=asyncio.FIRST_COMPLETED
            )
            return None if closed in done else incoming.result()
        finally:
            incoming.cancel()
            closed.cancel()
            await asyncio.gather(incoming, closed, return_exceptions=True)


__all__ = ["SignalRelay"]
