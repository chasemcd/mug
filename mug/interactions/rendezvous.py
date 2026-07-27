"""Where two participants meet when they are not in the same process (API-06).

``MeshFormationService`` matches the tickets it holds, and it holds them in the
memory of one process. A deployment behind a load balancer puts two participants
on two processes, and two waiting rooms of one each never form a group: each
participant waits for a partner the other process already has. So a study with any
multi-participant activity runs in one process, whatever the deployment says.

This module is the shared waiting room. The tickets live in the store, so every
process sees every participant who is waiting, and the room a group forms into
lives in the store too, so every process can find it.

**The store's own revision is the fence.** A claim reads the waiting list at a
revision and writes it back at that revision; two processes claiming at once means
one of them wrote first and the other must read again. There is no lock to hold, no
lock to lose, and no new durability primitive: this is the same reuse of the store's
optimistic check that the durable jobs runtime makes for its leases.

**A claimed group has an owner.** Matching is not the whole problem. The process
that claims a group is the one that runs what the group does -- it hosts the mesh,
or it holds the room core the browsers signal through -- and the other members'
sockets are held elsewhere. The room record names that owner, so a process holding
a member's socket knows which node to talk to. Getting a message there is
``mug.interactions.bus``; knowing where to send it is here.

**A ticket expires.** A process that dies leaves its participants in the waiting
list, and a group formed around a socket nobody holds would wedge the room. A
ticket carries the instant it was enqueued, and a claim passes over one that is
older than the time to live, so a dead node's tickets fall out of the waiting room
instead of poisoning it.

The module holds no clock and mints no identifier: the caller injects both, as
every other runtime in this layer does.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, cast

from mug.kernel import UtcInstant, compute_digest
from mug.storage import StorageError, Store

_INSTANT = "%Y-%m-%dT%H:%M:%S.%fZ"

# The words that fix the two derived aggregates. They are constants of the module
# rather than secrets: every process must derive the same waiting room for one
# group key, and the same record for one room handle.
_WAITING_ROLE = "mug.api-06.shared-waiting-room"
_ROOM_ROLE = "mug.api-06.shared-room"

_WAITING = "rendezvous.waiting"
_ROOM = "rendezvous.room"

# How long a ticket stays selectable. A node that goes away silently leaves its
# tickets behind; after this they are no longer matched. It is long enough that a
# participant who is genuinely waiting is never dropped from the queue.
_TICKET_TTL_SECONDS = 300.0


def _no_details() -> Mapping[str, Any]:
    """Return the empty, typed extra-details map a plain ticket carries."""
    return {}


@dataclass(frozen=True)
class Ticket:
    """One participant waiting for a group, and the node that holds their socket.

    ``node_id`` is the process to talk to about this participant, and
    ``connection_id`` is which of that process's sockets they are. Both travel with
    the ticket because the process that claims the group has neither.

    ``details`` is whatever else the mount needs to know about this participant and
    cannot look up: who they are as a principal, which activity they are at, which
    browser is theirs. The rendezvous never reads it. It travels here because the
    claiming process has never seen this participant's connection and must build
    their seat from the ticket alone.
    """

    enrollment_id: str
    visit_id: str
    node_id: str
    connection_id: str
    enqueued_at: UtcInstant
    details: Mapping[str, Any] = field(default_factory=_no_details)

    def as_json(self) -> dict[str, Any]:
        """Return the ticket as the object the waiting room holds."""
        return {
            "enrollment_id": self.enrollment_id,
            "visit_id": self.visit_id,
            "node_id": self.node_id,
            "connection_id": self.connection_id,
            "enqueued_at": self.enqueued_at,
            "details": dict(self.details),
        }

    @staticmethod
    def of(held: Any) -> Ticket:
        """Rebuild one ticket from what the waiting room holds."""
        item = cast("dict[str, Any]", held)
        return Ticket(
            enrollment_id=cast("str", item["enrollment_id"]),
            visit_id=cast("str", item["visit_id"]),
            node_id=cast("str", item["node_id"]),
            connection_id=cast("str", item["connection_id"]),
            enqueued_at=cast("str", item["enqueued_at"]),
            details=cast("dict[str, Any]", item.get("details", {})),
        )


@dataclass(frozen=True)
class SharedRoom:
    """One claimed group: who is in it, and which process runs it."""

    room_handle: str
    group_key: str
    owner_node: str
    members: tuple[Ticket, ...]
    closed: bool = False

    def node_of(self, enrollment_id: str) -> str | None:
        """Return the node holding one member's socket, if they are a member."""
        for member in self.members:
            if member.enrollment_id == enrollment_id:
                return member.node_id
        return None

    @property
    def nodes(self) -> tuple[str, ...]:
        """Return every node that holds one of this room's sockets, once each."""
        seen: list[str] = []
        for member in self.members:
            if member.node_id not in seen:
                seen.append(member.node_id)
        return tuple(seen)


def _derived(role: str, seed: str, kind: str) -> str:
    """Return the aggregate one role and seed name, in the given frozen kind."""
    raw = bytearray(bytes.fromhex(compute_digest([role, seed]).hex[:32]))
    # Force the version and variant nibbles, so the derived body is UUIDv7-shaped
    # and the identifier passes the kernel pattern for its kind.
    raw[6] = 0x70 | (raw[6] & 0x0F)
    raw[8] = 0x80 | (raw[8] & 0x3F)
    body = raw.hex()
    return f"{kind}_{body[0:8]}-{body[8:12]}-{body[12:16]}-{body[16:20]}-{body[20:32]}"


def waiting_room_id(group_key: str) -> str:
    """Return the aggregate that holds one game's shared waiting list.

    It is a pure function of the group key, so a process that has just started
    finds the participants who are already waiting with no lookup and no registry.
    It carries the ``group`` kind, because a waiting room is what a group forms
    out of and the kernel's identifier kinds are frozen.
    """
    return _derived(_WAITING_ROLE, group_key, "group")


def shared_room_id(room_handle: str) -> str:
    """Return the aggregate that holds one claimed group's membership and owner."""
    return _derived(_ROOM_ROLE, room_handle, "group")


def _fresher_than(instant: UtcInstant, now: UtcInstant, seconds: float) -> bool:
    """Report whether one instant is within the given age of now."""
    try:
        enqueued = datetime.strptime(instant, _INSTANT)
        current = datetime.strptime(now, _INSTANT)
    except ValueError:
        return False
    return current - enqueued <= timedelta(seconds=seconds)


class DurableRendezvous:
    """The shared waiting list and room registry every process reads and writes.

    ``submit`` puts one participant in a game's waiting room. ``claim`` takes the
    first ``size`` who are still fresh, and takes them exactly once however many
    processes call it at the same moment. ``open_room`` records who was claimed and
    which process runs them, and ``room`` reads that back anywhere.
    """

    def __init__(
        self,
        store: Store,
        *,
        new_id: Callable[[str], str],
        now: Callable[[], UtcInstant],
        ticket_ttl_seconds: float = _TICKET_TTL_SECONDS,
    ) -> None:
        self._store = store
        self._new_id = new_id
        self._now = now
        self._ttl = ticket_ttl_seconds

    async def submit(self, group_key: str, ticket: Ticket) -> None:
        """Add one participant to a game's shared waiting room.

        A participant already waiting is replaced rather than added again, so a
        reconnection moves their socket to the node that now holds it instead of
        putting them in the queue twice.
        """
        aggregate = waiting_room_id(group_key)
        while True:
            revision = self._store.revision_of(aggregate)
            held = [
                item
                for item in self._tickets(aggregate)
                if item.enrollment_id != ticket.enrollment_id
            ]
            if await self._write_waiting(aggregate, revision, [*held, ticket]):
                return

    async def release(self, group_key: str, enrollment_id: str) -> bool:
        """Take one participant out of a game's waiting room; report if they were in."""
        aggregate = waiting_room_id(group_key)
        while True:
            revision = self._store.revision_of(aggregate)
            held = self._tickets(aggregate)
            kept = [item for item in held if item.enrollment_id != enrollment_id]
            if len(kept) == len(held):
                return False
            if await self._write_waiting(aggregate, revision, kept):
                return True

    async def claim(self, group_key: str, size: int) -> tuple[Ticket, ...]:
        """Take the first ``size`` fresh tickets, or take nothing.

        Two processes calling this at the same moment do not both get the group:
        the write names the revision that was read, so the one that lost reads
        again and finds the tickets gone. That is the whole of the fencing, and it
        is the store's own check rather than a lock this module invented.
        """
        if size <= 0:
            return ()
        aggregate = waiting_room_id(group_key)
        while True:
            revision = self._store.revision_of(aggregate)
            now = self._now()
            fresh = [
                item
                for item in self._tickets(aggregate)
                if _fresher_than(item.enqueued_at, now, self._ttl)
            ]
            if len(fresh) < size:
                # Nothing forms, but a stale ticket that was passed over is still
                # in the list; writing the fresh ones back is what removes it.
                stale = len(self._tickets(aggregate)) != len(fresh)
                if stale:
                    await self._write_waiting(aggregate, revision, fresh)
                return ()
            claimed, kept = fresh[:size], fresh[size:]
            if await self._write_waiting(aggregate, revision, kept):
                return tuple(claimed)

    async def waiting(self, group_key: str) -> tuple[Ticket, ...]:
        """Return who is waiting for one game right now, in arrival order."""
        return tuple(self._tickets(waiting_room_id(group_key)))

    async def open_room(
        self,
        *,
        room_handle: str,
        group_key: str,
        owner_node: str,
        members: Sequence[Ticket],
    ) -> SharedRoom:
        """Record one claimed group, and which process runs it."""
        room = SharedRoom(
            room_handle=room_handle,
            group_key=group_key,
            owner_node=owner_node,
            members=tuple(members),
        )
        await self._write_room(room, expected=None)
        return room

    async def close_room(self, room_handle: str) -> None:
        """Record that one room has ended, so a late message finds it closed."""
        aggregate = shared_room_id(room_handle)
        while True:
            revision = self._store.revision_of(aggregate)
            found = await self.room(room_handle)
            if found is None or found.closed:
                return
            closed = SharedRoom(
                room_handle=found.room_handle,
                group_key=found.group_key,
                owner_node=found.owner_node,
                members=found.members,
                closed=True,
            )
            if await self._write_room(closed, expected=revision):
                return

    async def room(self, room_handle: str) -> SharedRoom | None:
        """Return one claimed group as any process sees it, or None if unknown."""
        head = self._store.load_aggregate(shared_room_id(room_handle))
        if head is None:
            return None
        item = cast("dict[str, Any]", head)
        return SharedRoom(
            room_handle=cast("str", item["room_handle"]),
            group_key=cast("str", item["group_key"]),
            owner_node=cast("str", item["owner_node"]),
            members=tuple(
                Ticket.of(member)
                for member in cast("list[Any]", item.get("members", []))
            ),
            closed=bool(item.get("closed", False)),
        )

    def _tickets(self, aggregate: str) -> list[Ticket]:
        """Read one waiting room's tickets in arrival order."""
        head = self._store.load_aggregate(aggregate)
        if head is None:
            return []
        return [
            Ticket.of(item) for item in cast("dict[str, Any]", head).get("tickets", [])
        ]

    async def _write_waiting(
        self, aggregate: str, revision: int | None, tickets: Sequence[Ticket]
    ) -> bool:
        """Write one waiting room at the revision read; report whether it held."""
        return await self._write(
            aggregate,
            revision,
            {"tickets": [ticket.as_json() for ticket in tickets]},
            _WAITING,
        )

    async def _write_room(self, room: SharedRoom, *, expected: int | None) -> bool:
        """Write one room record; report whether the revision guard held."""
        return await self._write(
            shared_room_id(room.room_handle),
            expected,
            {
                "room_handle": room.room_handle,
                "group_key": room.group_key,
                "owner_node": room.owner_node,
                "members": [member.as_json() for member in room.members],
                "closed": room.closed,
            },
            _ROOM,
        )

    async def _write(
        self,
        aggregate: str,
        revision: int | None,
        state: dict[str, Any],
        profile: str,
    ) -> bool:
        """Commit one rendezvous aggregate, reporting whether it lost the race.

        The write appends no canonical event. A waiting room is how the processes
        of one deployment find each other, not part of what happened to a
        participant: what happened is the interaction the group forms into, and
        that is recorded where every other interaction is.
        """
        command_id = self._new_id("command")
        try:
            await self._store.commit(
                command_id=command_id,
                idempotency_key=command_id,
                aggregate_id=aggregate,
                expected_revision=revision,
                new_state=state,
                durability_profile=profile,
            )
        except StorageError as error:
            if error.code in {"resource.already_exists", "command.revision_conflict"}:
                return False
            raise
        return True


__all__ = [
    "DurableRendezvous",
    "SharedRoom",
    "Ticket",
    "shared_room_id",
    "waiting_room_id",
]
