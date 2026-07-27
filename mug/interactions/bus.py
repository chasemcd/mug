"""Carry one message from the process that has it to the process that needs it.

A deployment runs more than one process. A participant's socket is held by
whichever process the load balancer sent them to, and that process is the only one
that can write to it. So when two participants meet, one of the two processes ends
up holding authority for what they are doing together, and it must reach a socket
it does not hold.

This module is that reach, and only that. A **node** is one process; a node has an
address (``node_id``) and a mailbox. ``publish`` puts one message in another node's
mailbox and ``take`` empties one's own. Nothing here knows what a message means.

The surface is **pull**, not push, because that is the surface a durable mailbox
can offer honestly: a store cannot call back into a process. ``NodeLink`` runs the
pump above it, so one place owns the loop, and a test drives a whole cross-node
exchange by calling ``pump_once`` instead of waiting.

Two implementations ship. ``LocalBus`` holds the mailboxes in memory: it is the
default, it is what one process uses, and it adds no store traffic to a deployment
that has no second process. ``StoreBus`` holds each mailbox in the shared store, so
two real processes exchange messages with no broker between them. It writes no
canonical event -- a mailbox is transport, not a record, and the ledger stays the
record of what happened rather than of what was said about it.

``StoreBus`` is the floor, not the ceiling. Every message it carries is a durable
write, so a deployment that moves game frames between nodes should implement
``NodeBus`` over its own broker; the Protocol is four methods wide for exactly that
reason.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any, Protocol, cast

from mug.kernel import compute_digest
from mug.storage import StorageError, Store

# One message on the bus: a JSON object the sending node built and the receiving
# node reads. The bus never looks inside it.
NodeMessage = Mapping[str, Any]

# What one node does with a message addressed to it. A handler that returns an
# object answers a request; one that returns None answers nothing.
Handler = Callable[[NodeMessage], Awaitable[NodeMessage | None]]

# The words that fix a node's mailbox aggregate. It is a constant of the module,
# not a secret: every process must derive the same mailbox for one node id.
_MAILBOX_ROLE = "mug.interactions.node-mailbox"

_MAILBOX = "node.mailbox"


class NodeBus(Protocol):
    """Deliver a message to one node's mailbox and empty one's own."""

    async def publish(self, node_id: str, message: NodeMessage) -> None:
        """Put one message in the named node's mailbox."""
        ...

    async def take(self, node_id: str) -> tuple[NodeMessage, ...]:
        """Empty one node's mailbox and return what was in it, oldest first."""
        ...


class LocalBus:
    """Hold every node's mailbox in this process's memory.

    This is what one process uses, and what a test uses to drive several nodes
    without a store: the nodes share no state except the messages they send each
    other, which is the property the cross-process design rests on.
    """

    def __init__(self) -> None:
        self._boxes: dict[str, deque[NodeMessage]] = defaultdict(deque)

    async def publish(self, node_id: str, message: NodeMessage) -> None:
        """Put one message in the named node's mailbox."""
        self._boxes[node_id].append(dict(message))

    async def take(self, node_id: str) -> tuple[NodeMessage, ...]:
        """Empty one node's mailbox and return what was in it, oldest first."""
        box = self._boxes.get(node_id)
        if not box:
            return ()
        taken = tuple(box)
        box.clear()
        return taken


def mailbox_id(node_id: str) -> str:
    """Return the aggregate that holds one node's mailbox.

    It is a pure function of the node id, so a process that has never heard of a
    node still knows where to write to it, with no lookup and no registry. It
    carries the ``channel`` kind: a mailbox is one node's inbound channel, and the
    kernel's identifier kinds are frozen.
    """
    raw = bytearray(bytes.fromhex(compute_digest([_MAILBOX_ROLE, node_id]).hex[:32]))
    # Force the version and variant nibbles, so the derived body is UUIDv7-shaped
    # and the identifier passes the kernel pattern for a channel id.
    raw[6] = 0x70 | (raw[6] & 0x0F)
    raw[8] = 0x80 | (raw[8] & 0x3F)
    body = raw.hex()
    return f"channel_{body[0:8]}-{body[8:12]}-{body[12:16]}-{body[16:20]}-{body[20:32]}"


class StoreBus:
    """Hold every node's mailbox in the shared store, so two processes exchange.

    One aggregate per node holds the messages waiting for it. A publish appends
    under the revision it read and a take empties under the revision it read, so
    two processes writing to one mailbox at once make one of them read again
    rather than lose a message. The retry is the whole of the fencing: the store's
    own optimistic check is the shared lock, and no new durability primitive
    appears.

    The write is deliberately not a command. It appends no canonical event and
    mints no receipt of its own, because a mailbox is how two processes talk and
    not part of what happened to a participant.
    """

    def __init__(self, store: Store, *, new_id: Callable[[str], str]) -> None:
        self._store = store
        self._new_id = new_id

    async def publish(self, node_id: str, message: NodeMessage) -> None:
        """Append one message to the named node's durable mailbox."""
        await self._update(node_id, lambda held: [*held, dict(message)])

    async def take(self, node_id: str) -> tuple[NodeMessage, ...]:
        """Empty one node's durable mailbox and return what was in it."""
        aggregate = mailbox_id(node_id)
        while True:
            revision = self._store.revision_of(aggregate)
            held = self._held(aggregate)
            if not held:
                return ()
            if await self._write(aggregate, revision, []):
                return tuple(held)

    async def _update(
        self,
        node_id: str,
        change: Callable[[Sequence[NodeMessage]], list[NodeMessage]],
    ) -> None:
        """Apply one change to a mailbox, re-reading whenever it loses the race."""
        aggregate = mailbox_id(node_id)
        while True:
            revision = self._store.revision_of(aggregate)
            held = self._held(aggregate)
            if await self._write(aggregate, revision, change(held)):
                return

    def _held(self, aggregate: str) -> list[NodeMessage]:
        """Read what is waiting in one mailbox right now."""
        head = self._store.load_aggregate(aggregate)
        if head is None:
            return []
        return list(cast("dict[str, Any]", head).get("messages", []))

    async def _write(
        self, aggregate: str, revision: int | None, messages: list[NodeMessage]
    ) -> bool:
        """Write one mailbox at the revision that was read; report whether it held."""
        command_id = self._new_id("command")
        try:
            await self._store.commit(
                command_id=command_id,
                idempotency_key=command_id,
                aggregate_id=aggregate,
                expected_revision=revision,
                new_state={"messages": messages},
                durability_profile=_MAILBOX,
            )
        except StorageError as error:
            if error.code in {"resource.already_exists", "command.revision_conflict"}:
                return False
            raise
        return True


class NodeLink:
    """One node's end of the bus: its address, its handlers, and its pump.

    A message names an ``op``, and a handler is registered per op. A handler that
    returns an object answers the node that asked; ``ask`` waits for that answer,
    so a node that must read something another node holds does it in one call.

    The pump is explicit. ``run`` drains the mailbox until it is stopped, and
    ``pump_once`` drains it exactly once, so a test moves a whole cross-node
    exchange forward step by step instead of sleeping and hoping.
    """

    def __init__(
        self,
        bus: NodeBus,
        node_id: str,
        *,
        new_id: Callable[[str], str],
        poll_interval: float = 0.005,
    ) -> None:
        self.node_id = node_id
        self._bus = bus
        self._new_id = new_id
        self._poll = poll_interval
        self._handlers: dict[str, Handler] = {}
        self._waiting: dict[str, asyncio.Future[NodeMessage]] = {}
        self._task: asyncio.Task[None] | None = None

    def on(self, op: str, handler: Handler) -> None:
        """Register what this node does with one kind of message."""
        self._handlers[op] = handler

    async def tell(self, node_id: str, op: str, body: NodeMessage) -> None:
        """Send one message to another node and do not wait for an answer."""
        await self._bus.publish(node_id, {"op": op, **body})

    async def ask(
        self, node_id: str, op: str, body: NodeMessage, *, timeout: float = 10.0
    ) -> NodeMessage:
        """Send one message to another node and wait for its answer.

        The answer comes back as an ordinary message on this node's own mailbox,
        so a reply crosses the same path as a request and needs no second channel.
        """
        correlation = self._new_id("correlation")
        future: asyncio.Future[NodeMessage] = asyncio.get_running_loop().create_future()
        self._waiting[correlation] = future
        try:
            await self._bus.publish(
                node_id,
                {
                    "op": op,
                    "reply_to": self.node_id,
                    "correlation": correlation,
                    **body,
                },
            )
            return await asyncio.wait_for(asyncio.shield(future), timeout)
        finally:
            self._waiting.pop(correlation, None)

    async def pump_once(self) -> int:
        """Handle everything waiting in this node's mailbox; return how much."""
        messages = await self._bus.take(self.node_id)
        for message in messages:
            await self._handle(message)
        return len(messages)

    async def run(self) -> None:
        """Drain this node's mailbox until the task is cancelled."""
        while True:
            if await self.pump_once() == 0:
                await asyncio.sleep(self._poll)

    def start(self) -> None:
        """Start the pump as a background task, if it is not already running."""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self.run())

    async def stop(self) -> None:
        """Stop the pump and wait for it to finish."""
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def _handle(self, message: NodeMessage) -> None:
        """Route one taken message to its handler, or to the caller that asked."""
        op = message.get("op")
        if op == "reply":
            waiting = self._waiting.get(cast("str", message.get("correlation")))
            if waiting is not None and not waiting.done():
                waiting.set_result(cast("NodeMessage", message.get("body", {})))
            return
        handler = self._handlers.get(cast("str", op))
        if handler is None:
            return
        answer = await handler(message)
        reply_to = message.get("reply_to")
        if reply_to is None:
            return
        await self._bus.publish(
            cast("str", reply_to),
            {
                "op": "reply",
                "correlation": message.get("correlation"),
                "body": answer or {},
            },
        )


__all__ = [
    "Handler",
    "LocalBus",
    "NodeBus",
    "NodeLink",
    "NodeMessage",
    "StoreBus",
    "mailbox_id",
]
