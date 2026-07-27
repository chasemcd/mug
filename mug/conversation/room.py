"""One conversation that several connections share: order, visibility, delivery.

``ConversationChannel`` orders one channel. It has always been able to order any
number of authors -- what was missing is the thing that holds several connections,
several channels, and the rule about who may see and say what. That is this room.

Three things it is responsible for.

**One canonical order.** Every message goes through the server, so the sequence a
message takes is assigned here and never by a client. Posts are serialized on the
room's lock, so two participants who send at the same instant get two different
sequence numbers in a definite order, and neither client's clock has a say in it.

**Membership, and write validity from the lease.** A member may read and write only
the channels its membership names, so a private channel is invisible to whoever is
not in it -- not hidden by the client, but never sent and never delivered. A
participant's write is valid only while its ``ConnectionLease`` is the current one:
a connection the room has already replaced presents a fenced lease, and its
messages are refused rather than taken as the actor's word. A model seat carries no
lease, because a lease fences a *connection* and a seat has none.

**Per-member delivery.** One canonical order is not one delivery. Each member has
its own watermark per channel, and a message is delivered -- and its
``DeliveryReceipt`` recorded -- at the moment it actually reaches that member. A
participant who is away when a message is posted is delivered it when they come
back, and the receipt says so. So the canonical order is one order and the
deliveries are many.

**The words.** The ledger records a content digest and never the text: that is the
family's privacy shape. But a room has to give participant A's words to participant
B, so the live room holds the text for the life of the conversation, exactly as one
connection's working transcript did before there was more than one connection. The
durable copy is an artifact the transcript points at
(``mug.conversation.transcript``); this cache is not durable and is not meant to be.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol

from mug.conversation.runtime import ConversationChannel
from mug.conversation.types import ChatMessage
from mug.interactions.types import ConnectionLease
from mug.kernel import CommandReceipt, Digest, compute_digest
from mug.runtime import CommandContext
from mug.storage import Store

# Push one message, with its words, to one member. The room holds no socket: the
# mount supplies the sink, so a model seat's sink and a browser's sink look alike.
Sink = Callable[[ChatMessage, str], Awaitable[None]]
# Told about each message as the room takes it into its order. It is how something
# that knows about more than the conversation -- a composed activity that also knows
# which frame of the game is on screen -- writes the two down against each other.
Watcher = Callable[[ChatMessage], None]
NewContext = Callable[[str], CommandContext]
NewId = Callable[[str], str]

# A room keeps the words of this many messages. A conversation past the bound keeps
# the most recent, which is what a reconnection and a model context both read.
MAX_REMEMBERED = 512


@dataclass(frozen=True)
class Posted:
    """One message the room took, and the stream its commit wrote to.

    The stream is what a flow records as the conversation's lineage, so the caller
    is told it rather than left to derive it from the message id. ``event_id`` is
    the canonical event the commit wrote, which is what a reply to this message
    names as its cause.
    """

    message: ChatMessage
    stream_id: str | None = None
    event_id: str | None = None


@dataclass(frozen=True)
class RoomChannel:
    """One channel of a room: its key and how widely its messages are meant to go.

    ``visibility`` is what every message posted here carries. It is recorded on the
    message, so an analysis can tell a message the whole room saw from one only a
    part of it did, without having to reconstruct the membership.
    """

    key: str
    visibility: Literal["public", "team", "private"] = "public"


def _no_watermarks() -> dict[str, int]:
    """Return an empty, typed per-channel delivery watermark map."""
    return {}


@dataclass
class RoomMember:
    """One actor in a room: what it may see, what fences it, and where to push.

    ``channels`` is the whole of what this member may read and write. ``lease`` is
    the connection lease a participant's writes are checked against; a model seat
    has none. ``sink`` is set while a live connection is attached and cleared when
    it goes away, which is what makes a delivery wait for the member to come back.
    """

    actor_id: str
    channels: tuple[str, ...]
    kind: Literal["participant", "model"] = "participant"
    lease: ConnectionLease | None = None
    sink: Sink | None = None
    delivered_through: dict[str, int] = field(default_factory=_no_watermarks)

    def may_see(self, channel_key: str) -> bool:
        """Return whether this member may read and write the named channel."""
        return channel_key in self.channels


class LeaseAuthority(Protocol):
    """The one question a room asks about a lease. ``RoomFormation`` answers it."""

    def is_current(self, lease: ConnectionLease) -> bool:
        """Return whether the lease is the current one for its actor."""
        ...


class ChatRoom:
    """One live conversation over one interaction, shared by several connections."""

    def __init__(
        self,
        *,
        store: Store,
        interaction_id: str,
        channels: Sequence[RoomChannel],
        now: Callable[[], datetime],
        leases: LeaseAuthority | None = None,
    ) -> None:
        if not channels:
            raise ValueError("a room must declare at least one channel")
        self._interaction_id = interaction_id
        self._declared = {channel.key: channel for channel in channels}
        self._channels = {
            channel.key: ConversationChannel(
                store=store,
                interaction_id=interaction_id,
                channel_key=channel.key,
                now=now,
            )
            for channel in channels
        }
        self._leases = leases
        self._members: dict[str, RoomMember] = {}
        self._order: dict[str, list[ChatMessage]] = {
            channel.key: [] for channel in channels
        }
        self._text: dict[str, str] = {}
        self._arrival: dict[str, int] = {}
        self._watchers: list[Watcher] = []
        self._lock = asyncio.Lock()

    # -- what the room is -------------------------------------------------------

    @property
    def interaction_id(self) -> str:
        """Return the interaction every channel of this room belongs to."""
        return self._interaction_id

    @property
    def channel_keys(self) -> tuple[str, ...]:
        """Return every channel this room declares, in declaration order."""
        return tuple(self._declared)

    def channel(self, channel_key: str) -> ConversationChannel:
        """Return the ordering channel for one key.

        A model seat posts through its channel directly, because its reply is
        recorded by the model output's own digest. It is the same object the room
        orders with, so there is one sequence per channel however a message arrives.
        """
        return self._channels[channel_key]

    def visibility_of(self, channel_key: str) -> Literal["public", "team", "private"]:
        """Return the visibility every message of one channel carries."""
        return self._declared[channel_key].visibility

    # -- membership -------------------------------------------------------------

    def add_member(self, member: RoomMember) -> RoomMember:
        """Place one actor in the room, keeping only the channels the room has."""
        held = RoomMember(
            actor_id=member.actor_id,
            channels=tuple(key for key in member.channels if key in self._declared),
            kind=member.kind,
            lease=member.lease,
            sink=member.sink,
        )
        self._members[member.actor_id] = held
        return held

    def member(self, actor_id: str) -> RoomMember | None:
        """Return one member of the room, or None when the actor is not in it."""
        return self._members.get(actor_id)

    def members(self) -> tuple[RoomMember, ...]:
        """Return every member, in the order they joined."""
        return tuple(self._members.values())

    def visible_channels(self, actor_id: str) -> tuple[str, ...]:
        """Return the channels one actor may see, in the room's declared order.

        This is what a client is told the conversation is. A channel a participant
        is not in is absent from it, so their client never knows the channel exists.
        """
        member = self._members.get(actor_id)
        if member is None:
            return ()
        return tuple(key for key in self._declared if member.may_see(key))

    def recipients(self, channel_key: str) -> tuple[RoomMember, ...]:
        """Return every member that may see one channel, in join order."""
        return tuple(
            member for member in self._members.values() if member.may_see(channel_key)
        )

    def attach(self, actor_id: str, sink: Sink) -> None:
        """Give one member a live connection to push to."""
        member = self._members.get(actor_id)
        if member is not None:
            member.sink = sink

    def detach(self, actor_id: str) -> None:
        """Take away one member's live connection; their deliveries now wait."""
        member = self._members.get(actor_id)
        if member is not None:
            member.sink = None

    # -- the words --------------------------------------------------------------

    def remember(self, message_id: str, text: str) -> None:
        """Hold one message's words for the life of the conversation."""
        self._text[message_id] = text
        if len(self._text) > MAX_REMEMBERED:
            for stale in list(self._text)[: len(self._text) - MAX_REMEMBERED]:
                del self._text[stale]

    def text_of(self, message_id: str) -> str:
        """Return the words of one message the room is holding."""
        return self._text.get(message_id, "")

    def history(
        self, channel_key: str, *, limit: int | None = None
    ) -> list[ChatMessage]:
        """Return one channel's messages in canonical order, most recent last."""
        messages = self._order.get(channel_key, [])
        return list(messages if limit is None else messages[-limit:])

    def context_for(self, actor_id: str, *, limit: int) -> list[ChatMessage]:
        """Return what one member has seen, across its channels, in one order.

        A model seat in two channels reads one conversation, not two: the messages
        interleave by the order the room took them in, which is one order across
        channels where a per-channel sequence is not. This is what a context
        snapshot then names, so the snapshot lists exactly the messages the model
        saw, in the order it saw them.
        """
        member = self._members.get(actor_id)
        if member is None:
            return []
        seen = [
            message
            for key in member.channels
            for message in self._order.get(key, [])
        ]
        seen.sort(key=lambda message: self._arrival.get(message.message_id, 0))
        return seen[-limit:]

    # -- posting ----------------------------------------------------------------

    def may_write(self, actor_id: str, channel_key: str) -> bool:
        """Return whether one actor may post to one channel right now.

        Membership decides what is reachable; the lease decides whether this
        connection is still the one that speaks for the actor. A model seat holds no
        lease, so only its membership is asked about.
        """
        member = self._members.get(actor_id)
        if member is None or not member.may_see(channel_key):
            return False
        if member.kind == "model":
            return True
        if self._leases is None:
            # A room formed with no lease authority fences nothing, because there is
            # nothing to fence: one connection, and no second one to replace it.
            return True
        return member.lease is not None and self._leases.is_current(member.lease)

    async def post(
        self,
        *,
        actor_id: str,
        channel_key: str,
        text: str,
        message_id: str,
        new_context: NewContext,
        content_digest: Digest | None = None,
    ) -> Posted | None:
        """Order one message into the room, or return None when it is refused.

        The refusals are the room's rule: an actor that is not a member, a channel
        the member may not see, and a connection whose lease has been fenced. A
        refused commit is dropped whole -- the channel does not advance its sequence,
        so a refused post leaves no gap and no local record either.
        """
        if not self.may_write(actor_id, channel_key):
            return None
        async with self._lock:
            context = new_context(message_id)
            receipt, message = await self._channels[channel_key].post(
                context=context,
                message_id=message_id,
                author_actor_id=actor_id,
                content_digest=content_digest or compute_digest(text),
                visibility=self.visibility_of(channel_key),
                idempotency_key=context.idempotency_key,
            )
            if receipt.outcome != "accepted":
                return None
            self.adopt(message, text)
            return Posted(
                message=message,
                stream_id=_stream_of(receipt),
                event_id=context.event_id,
            )

    def adopt(self, message: ChatMessage, text: str) -> None:
        """Take a message posted through a channel into the room's order and cache.

        A model seat's reply is posted by the agent runtime, because its content
        digest is the model output's own digest rather than a digest of the rendered
        text. The room still has to hold it, so the agent's caller hands it over
        here. It is the same channel object, so the sequence is already the room's.

        **A posted message the room never adopts reaches nobody.** That is the one
        rule an unchosen candidate reply depends on (W19): it is committed to the
        channel and its caller does not hand it over here, so it is in no order, no
        flush walks it, and no member can ever be delivered it. One enforcement
        point, rather than two to keep in step.
        """
        held = self._order.setdefault(message.channel_key, [])
        # The words are held **before** the watchers are told. A watcher is given
        # the message, so the first thing it asks the room is what that message
        # said; telling it first and remembering after hands it an empty string.
        self.remember(message.message_id, text)
        if all(one.message_id != message.message_id for one in held):
            held.append(message)
            self._arrival[message.message_id] = len(self._arrival) + 1
            for watcher in self._watchers:
                watcher(message)

    def watch(self, watcher: Watcher) -> None:
        """Tell one watcher about each message as the room takes it.

        A composed activity watches the conversation to say which frame of the game
        each message was said at. That belongs outside the room: the room orders a
        conversation and knows nothing about an episode, and a watcher is how
        something that knows about both writes the two down together.
        """
        self._watchers.append(watcher)

    def carry(self, message: ChatMessage, text: str) -> None:
        """Take a message from an earlier run of this channel into the room.

        One written conversation placed on two activities is one conversation, and
        each activity is still its own interaction. The earlier interaction's
        messages are real records of this same conversation, so they are carried
        in: a model then reads the conversation it is actually in, and its context
        snapshot names messages that were really said rather than stand-ins.

        They are not delivered again and not recorded again -- they already
        happened -- and no watcher is told about them, because a message said in an
        earlier activity was not said at any frame of this one.

        Not delivering them again is what the watermarks are moved for. A carried
        message reached its members when it was said; leaving it behind the
        watermark would make the next flush deliver the whole earlier conversation
        a second time, record a second delivery receipt for each of it, and write
        it into the durable transcript twice.
        """
        held = self._order.setdefault(message.channel_key, [])
        if all(one.message_id != message.message_id for one in held):
            held.append(message)
            self._arrival[message.message_id] = len(self._arrival) + 1
        for member in self._members.values():
            if member.may_see(message.channel_key):
                member.delivered_through[message.channel_key] = max(
                    member.delivered_through.get(message.channel_key, 0),
                    message.sequence,
                )
        self.remember(message.message_id, text)

    # -- delivery ---------------------------------------------------------------

    async def deliver(
        self,
        message: ChatMessage,
        *,
        new_context: NewContext,
        new_id: NewId,
    ) -> tuple[str, ...]:
        """Push one message to every member that may see it, and record each receipt.

        Each recipient is delivered to on its own: the push happens first and the
        receipt is recorded after, so a receipt says the message reached that member
        rather than that the server meant it to. A member with no live connection is
        not delivered to and keeps its watermark, so the message is waiting for them
        when they come back.
        """
        reached: list[str] = []
        for member in self.recipients(message.channel_key):
            if await self._deliver_to(member, message, new_context, new_id):
                reached.append(member.actor_id)
        return tuple(reached)

    async def flush(
        self,
        actor_id: str,
        *,
        new_context: NewContext,
        new_id: NewId,
    ) -> tuple[ChatMessage, ...]:
        """Deliver everything one member missed while it had no connection."""
        member = self._members.get(actor_id)
        if member is None or member.sink is None:
            return ()
        sent: list[ChatMessage] = []
        for key in member.channels:
            for message in self._order.get(key, []):
                if message.sequence <= member.delivered_through.get(key, 0):
                    continue
                if await self._deliver_to(member, message, new_context, new_id):
                    sent.append(message)
        return tuple(sent)

    async def _deliver_to(
        self,
        member: RoomMember,
        message: ChatMessage,
        new_context: NewContext,
        new_id: NewId,
    ) -> bool:
        """Push one message to one member and record that member's own receipt.

        The author is not delivered their own message. A delivery receipt is proof
        that a message reached somebody who did not write it, and an author already
        has their own words; sending them back would also make every client render
        them twice. So in a room of two, each participant's delivery is the other's
        messages, which is why one canonical order is many deliveries.
        """
        if member.actor_id == message.author_actor_id:
            return False
        if member.sink is None and member.kind == "participant":
            return False
        if member.sink is not None:
            await member.sink(message, self.text_of(message.message_id))
        await self._channels[message.channel_key].deliver(
            context=new_context(new_id("message")),
            message=message,
            recipient_actor_id=member.actor_id,
            evidence_stream="canonical",
        )
        member.delivered_through[message.channel_key] = max(
            member.delivered_through.get(message.channel_key, 0), message.sequence
        )
        return True


def _stream_of(receipt: CommandReceipt) -> str | None:
    """Return the stream one accepted commit wrote to, or None when it wrote none."""
    positions = receipt.stream_positions
    if not positions:
        return None
    return max(positions.items(), key=lambda item: item[1])[0]


__all__ = [
    "MAX_REMEMBERED",
    "ChatRoom",
    "LeaseAuthority",
    "NewContext",
    "NewId",
    "Posted",
    "RoomChannel",
    "RoomMember",
    "Sink",
]
