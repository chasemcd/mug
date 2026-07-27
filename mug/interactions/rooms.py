"""Form a server-ordered room from waiting tickets: match, cast, and lease (API-06).

``MeshFormationService`` forms the other kind of group: peers that connect to each
other, prove their pairwise latency, and freeze a ``P2PMeshMembership``. A
conversation is not that. Its members never connect to each other -- every message
goes through the server, which is what gives the channel one canonical order -- so
there is no mesh to freeze and no pair to probe. Building one anyway would put a
record of peer connections that do not exist into the ledger.

What a room needs is the rest of it: the FIFO waiting queue, the ``Group``, the
``Interaction`` that casts the members into seats, and one fenced
``ConnectionLease`` per actor. The lease is what makes a write valid: a connection
that presents a fenced lease is a connection the room has already replaced, and its
messages are refused rather than taken as the actor's word.

One room may declare several channels, because ``Interaction.channels`` is a list.
That is what lets a public channel and a private one belong to the same
conversation, and later what lets a game channel and a chat channel belong to the
same interaction.

Like the mesh service, this holds no clock and mints no identifiers: the caller
injects both, so a test forms a room with a fixed clock and no gateway.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from mug.interactions.leases import LeaseBook
from mug.interactions.types import (
    ChannelInstance,
    ConnectionLease,
    FifoMatch,
    Group,
    Interaction,
    MatchmakingTicket,
    MatchStrategy,
)
from mug.kernel import Duration, UtcInstant, VersionStamp, etag
from mug.kernel.refs import StudyVersionRef

IdMinter = Callable[[str], str]
Clock = Callable[[], UtcInstant]


def _empty_cast() -> dict[str, str]:
    """Return the empty seat-to-actor cast for a room that did not form."""
    return {}


@dataclass(frozen=True)
class ChannelSpec:
    """One channel a room declares: its key, its kind, and its definition.

    A composed activity holds a game channel and a chat channel in one
    interaction, and the two are not ordered the same way, so the kind belongs to
    the channel rather than to the room.

    ``definition_id`` is the authored channel this instance is one run of. The
    same authored conversation placed on two activities names one definition and
    mints one instance per activity, which is how a transcript continues across
    them. With none, the formation mints a definition of its own and every room it
    forms names that one.
    """

    key: str
    type: Literal["game", "chat", "annotation"] = "chat"
    definition_id: str | None = None

    @property
    def ordering(self) -> Literal["total", "per-producer"]:
        """Return the ordering this kind of channel guarantees.

        A conversation is totally ordered because every message goes through the
        server. A game channel is ordered per producer, because each seat's own
        frames are in order and no clock puts one seat's frame before another's.
        """
        return "per-producer" if self.type == "game" else "total"


@dataclass
class _Entry:
    """The mutable waiting-queue state behind one immutable ticket record."""

    enrollment_id: str
    visit_id: str
    match: MatchStrategy
    enqueued_at: UtcInstant
    status: Literal["waiting", "matched", "released", "expired"] = "waiting"
    group_id: str | None = None


@dataclass(frozen=True)
class RoomResult:
    """The outcome of one room-formation poll.

    ``formed`` carries the group, the interaction with every declared channel, the
    seat-to-actor cast, and one lease per actor, in the cast's seat order.
    ``insufficient`` means fewer than the declared size are waiting.
    """

    status: Literal["formed", "insufficient"]
    tickets: tuple[MatchmakingTicket, ...] = ()
    group: Group | None = None
    interaction: Interaction | None = None
    instances: tuple[ChannelInstance, ...] = ()
    leases: tuple[ConnectionLease, ...] = ()
    cast: Mapping[str, str] = field(default_factory=_empty_cast)


class RoomFormation:
    """Form one server-ordered room at a time from the tickets of one group key.

    A room of size one forms on the first ticket, which is the ordinary case: one
    participant talking to a model seat is still a room, with one canonical order
    and one lease, so the single-participant path and the several-participant path
    are the same path.
    """

    def __init__(
        self,
        *,
        new_id: IdMinter,
        now: Clock,
        study_version: StudyVersionRef,
        group_key: str,
        channels: Sequence[str | ChannelSpec],
        size: int = 1,
        channel_type: Literal["game", "chat", "annotation"] = "chat",
        strategy: MatchStrategy | None = None,
        lease_ttl: Duration | None = None,
    ) -> None:
        if size < 1:
            raise ValueError("a room needs at least one seat")
        if not channels:
            raise ValueError("a room must declare at least one channel")
        self._new_id = new_id
        self._now = now
        self._study_version = study_version
        self._group_key = group_key
        declared = [
            channel
            if isinstance(channel, ChannelSpec)
            else ChannelSpec(key=channel, type=channel_type)
            for channel in channels
        ]
        self._channels = list({channel.key: channel for channel in declared}.values())
        self._size = size
        self._strategy = strategy or FifoMatch(kind="fifo")
        self._leases = LeaseBook(new_id=new_id, now=now, ttl=lease_ttl)
        # One definition id per channel key, taken from the authored channel where
        # the study named one, and otherwise minted once for the life of the
        # formation. Either way every room of this formation names the same
        # definition per key, which is what makes an instance one run of a channel
        # rather than a channel of its own.
        self._definitions = {
            channel.key: channel.definition_id or new_id("channeldef")
            for channel in self._channels
        }
        self._queue: list[_Entry] = []

    @property
    def size(self) -> int:
        """Return the number of members one room of this formation holds."""
        return self._size

    @property
    def channels(self) -> tuple[str, ...]:
        """Return the channel keys every room of this formation declares."""
        return tuple(channel.key for channel in self._channels)

    def definition_of(self, channel_key: str) -> str | None:
        """Return the authored channel one key's instances are all runs of."""
        return self._definitions.get(channel_key)

    # -- the waiting queue ------------------------------------------------------

    def submit(self, *, enrollment_id: str, visit_id: str) -> MatchmakingTicket:
        """Enqueue one enrollment's request to join a room and return its ticket."""
        entry = _Entry(
            enrollment_id=enrollment_id,
            visit_id=visit_id,
            match=self._strategy,
            enqueued_at=self._now(),
        )
        self._queue.append(entry)
        return self._ticket(entry)

    def release(self, enrollment_id: str) -> MatchmakingTicket | None:
        """Release a waiting ticket, as a server-side waitroom timeout would."""
        for entry in self._queue:
            if entry.enrollment_id == enrollment_id and entry.status == "waiting":
                entry.status = "released"
                return self._ticket(entry)
        return None

    def waiting(self) -> tuple[MatchmakingTicket, ...]:
        """Return the tickets still waiting to be matched, in arrival order."""
        return tuple(
            self._ticket(entry) for entry in self._queue if entry.status == "waiting"
        )

    # -- formation --------------------------------------------------------------

    def poll(self) -> RoomResult:
        """Form one room from the earliest waiting tickets, when enough wait."""
        chosen = [entry for entry in self._queue if entry.status == "waiting"][
            : self._size
        ]
        if len(chosen) < self._size:
            return RoomResult(status="insufficient")

        interaction_id = self._new_id("interaction")
        group_id = self._new_id("group")
        cast = dict(
            sorted(
                (f"seat-{index + 1}", self._new_id("actor"))
                for index in range(len(chosen))
            )
        )
        leases = tuple(
            self._leases.issue(interaction_id, cast[seat_key])
            for seat_key in sorted(cast)
        )
        group = self._build_group(chosen, group_id)
        interaction = self._build_interaction(interaction_id, chosen, cast, group_id)
        instances = tuple(
            self._build_instance(interaction_id, channel) for channel in self._channels
        )
        for entry in chosen:
            entry.status = "matched"
            entry.group_id = group_id
        return RoomResult(
            status="formed",
            tickets=tuple(self._ticket(entry) for entry in chosen),
            group=group,
            interaction=interaction,
            instances=instances,
            leases=leases,
            cast=cast,
        )

    # -- lease fencing ----------------------------------------------------------

    def reacquire_lease(
        self, interaction_id: str, lease: ConnectionLease
    ) -> ConnectionLease:
        """Re-issue a lease at the next fencing generation, fencing the prior one."""
        return self._leases.reacquire(interaction_id, lease)

    def is_current(self, lease: ConnectionLease) -> bool:
        """Return whether the complete bound lease is current and unexpired."""
        return self._leases.is_current(lease)

    # -- record builders --------------------------------------------------------

    def _build_group(self, chosen: list[_Entry], group_id: str) -> Group:
        """Build the formed group record for the matched members."""
        members = [entry.enrollment_id for entry in chosen]
        body = {"group_key": self._group_key, "size": self._size, "members": members}
        return Group(
            group_id=group_id,
            study_version=self._study_version,
            group_key=self._group_key,
            size=self._size,
            members=members,
            status="formed",
            version=VersionStamp(revision=1, etag=etag(body)),
            formed_at=self._now(),
        )

    def _build_interaction(
        self,
        interaction_id: str,
        chosen: list[_Entry],
        cast: Mapping[str, str],
        group_id: str,
    ) -> Interaction:
        """Cast the members into an active interaction over every declared channel."""
        visit_ids = list(dict.fromkeys(entry.visit_id for entry in chosen))
        body = {"cast": dict(cast), "visits": visit_ids, "group": group_id}
        return Interaction(
            interaction_id=interaction_id,
            study_version=self._study_version,
            visit_ids=visit_ids,
            cast=dict(cast),
            channels=[channel.key for channel in self._channels],
            status="active",
            version=VersionStamp(revision=1, etag=etag(body)),
            group_id=group_id,
        )

    def _build_instance(
        self, interaction_id: str, channel: ChannelSpec
    ) -> ChannelInstance:
        """Name one live channel of the room, with the ordering its kind implies.

        The room's own ordering guarantee is not a matter of opinion, and it is
        per channel rather than per room: a composed activity holds a totally
        ordered conversation beside a game ordered per producer, and each record
        says which it is where an analysis can read it.
        """
        return ChannelInstance(
            channel_instance_id=self._new_id("channel"),
            interaction_id=interaction_id,
            channel_definition_id=self._definitions[channel.key],
            channel_key=channel.key,
            channel_type=channel.type,
            ordering=channel.ordering,
        )

    def _ticket(self, entry: _Entry) -> MatchmakingTicket:
        """Build the immutable ticket record for one queue entry."""
        return MatchmakingTicket(
            study_version=self._study_version,
            group_key=self._group_key,
            enrollment_id=entry.enrollment_id,
            match=entry.match,
            enqueued_at=entry.enqueued_at,
            status=entry.status,
            group_id=entry.group_id,
        )


__all__ = ["ChannelSpec", "Clock", "IdMinter", "RoomFormation", "RoomResult"]
