"""The conversation runtime: order, deliver, and snapshot one channel (API-08).

The API-08 family (``mug.conversation``) owns six records -- the authored
``ChatMessage``, the ``ConversationSegment`` that groups a contiguous run, the
``ContextSnapshot`` that pins the context of a model request, the ``TurnPolicy``,
the ``DeliveryReceipt``, and the ``CandidateReplySet`` -- but adds no runtime. This
module is the channel runtime over them. It is the chat analog of the game loop:
where the game loop assigns a frame number and records a transition, the channel
assigns a sequence number and records a message, both through the shared command
spine, so a conversation's lineage is a canonical event stream.

The channel is a live, stateful object for one ``(interaction, channel)`` pair -- a
runtime occurrence, not wire data -- so it owns the mutable ordering state: the next
sequence number to assign. A restart calls ``rebuild`` to fold the recorded
messages and restore the counter, exactly as the job queue rebuilds its index, so
ordering survives a restart with no gap and no reuse.

Each message is its own aggregate keyed by its message id, so a duplicate post (the
same content-addressed message id) coalesces on the store's existence guard -- the
idempotency the family needs when a client retries a send. Delivery and context
snapshots are their own aggregates on the same stream discipline.

The turn policy that governs *when a model speaks* is a pure decision in
``mug.conversation.turns``; the model call that produces a reply is composed above,
in ``mug.agents`` (the layer that may import both the provider and the channel),
because the channel sits below scheduling and providers and must not import them --
just as the game loop holds the seat seam but never the scheduler.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any, Literal, cast

from mug.conversation.types import (
    ChatMessage,
    ContextSnapshot,
    ConversationSegment,
    DeliveryReceipt,
)
from mug.kernel import (
    CommandReceipt,
    CommandTypeRef,
    Digest,
    TypedObject,
    UtcInstant,
)
from mug.runtime import CommandContext, commit_command
from mug.storage import Store

_ChannelRecord = ChatMessage | DeliveryReceipt | ContextSnapshot

_POST = CommandTypeRef(name="chat.post", version=0)
_DELIVER = CommandTypeRef(name="chat.deliver", version=0)
_SNAPSHOT = CommandTypeRef(name="chat.snapshot", version=0)

_INSTANT = "%Y-%m-%dT%H:%M:%S.%fZ"


class ConversationChannel:
    """Order, deliver, and snapshot one chat channel through the command spine.

    The channel holds the injected impurity -- the store and the clock -- and the
    mutable ordering state (the next sequence to assign). ``post`` records one
    authored message at the next sequence; ``deliver`` records a receipt; ``snapshot``
    pins the context a model request used; ``segment`` projects a contiguous run.
    Each write takes a ``CommandContext`` the caller minted for the record's
    aggregate.
    """

    def __init__(
        self,
        *,
        store: Store,
        interaction_id: str,
        channel_key: str,
        now: Callable[[], datetime],
    ) -> None:
        self._store = store
        self._interaction_id = interaction_id
        self._channel_key = channel_key
        self._now = now
        self._next_sequence = 1

    @property
    def next_sequence(self) -> int:
        """Return the sequence the next posted message will take."""
        return self._next_sequence

    def rebuild(self, store: Store) -> int:
        """Fold recorded messages of this channel and restore the sequence counter.

        A restart calls this to recover the next sequence with no gap and no reuse:
        it reads the highest sequence any message on this channel reached and sets
        the counter one past it. Return the restored next sequence.
        """
        highest = 0
        for _aggregate_id, state in store.scan_aggregates():
            if _is_message_on(state, self._interaction_id, self._channel_key):
                highest = max(highest, int(cast("dict[str, Any]", state)["sequence"]))
        self._next_sequence = highest + 1
        return self._next_sequence

    async def post(
        self,
        *,
        context: CommandContext,
        message_id: str,
        author_actor_id: str,
        content_digest: Digest,
        visibility: Literal["public", "team", "private"],
        idempotency_key: str,
    ) -> tuple[CommandReceipt, ChatMessage]:
        """Record one authored message at the next channel sequence, and return it.

        The channel assigns the sequence in order, so the messages carry a total
        order the segments and delivery receipts refer to. The message is its own
        aggregate keyed by its id, so a duplicate post of the same content-addressed
        id coalesces with no second effect. A rejected commit does not advance the
        counter, so a refused post leaves no gap.
        """
        message = ChatMessage(
            message_id=message_id,
            interaction_id=self._interaction_id,
            channel_key=self._channel_key,
            author_actor_id=author_actor_id,
            sequence=self._next_sequence,
            content_digest=content_digest,
            visibility=visibility,
            idempotency_key=idempotency_key,
            submitted_at=self._instant(),
        )
        receipt = await commit_command(
            context,
            command=_POST,
            new_state=_state(message),
            result=_typed(message),
            store=self._store,
        )
        if receipt.outcome == "accepted":
            self._next_sequence += 1
        return receipt, message

    async def deliver(
        self,
        *,
        context: CommandContext,
        message: ChatMessage,
        recipient_actor_id: str,
        evidence_stream: Literal["canonical", "experienced"],
    ) -> tuple[CommandReceipt, DeliveryReceipt]:
        """Record proof that one recipient received a message at its sequence."""
        receipt_record = DeliveryReceipt(
            message_id=message.message_id,
            recipient_actor_id=recipient_actor_id,
            delivered_sequence=message.sequence,
            evidence_stream=evidence_stream,
            delivered_at=self._instant(),
        )
        receipt = await commit_command(
            context,
            command=_DELIVER,
            new_state=_state(receipt_record),
            result=_typed(receipt_record),
            store=self._store,
        )
        return receipt, receipt_record

    async def snapshot(
        self,
        *,
        context: CommandContext,
        message_id: str,
        model_request_digest: Digest,
        included_message_ids: list[str],
    ) -> tuple[CommandReceipt, ContextSnapshot]:
        """Record the exact prior context one model request used for a message.

        The snapshot joins a produced message to the request digest and the messages
        the model saw, so a replay reconstructs the same context the model read -- the
        chat analog of a decision's source-observation digest.
        """
        snap = ContextSnapshot(
            message_id=message_id,
            model_request_digest=model_request_digest,
            included_message_ids=included_message_ids,
            captured_at=self._instant(),
        )
        receipt = await commit_command(
            context,
            command=_SNAPSHOT,
            new_state=_state(snap),
            result=_typed(snap),
            store=self._store,
        )
        return receipt, snap

    def segment(
        self, *, message_ids: list[str], start_sequence: int, end_sequence: int
    ) -> ConversationSegment:
        """Project one contiguous run of messages as a segment (a read-model).

        A segment is a projection over recorded messages, not a new fact, so it is a
        pure builder: the caller passes the ids and the span it read, and the record
        validates that the span matches the count.
        """
        return ConversationSegment(
            channel_key=self._channel_key,
            message_ids=message_ids,
            start_sequence=start_sequence,
            end_sequence=end_sequence,
        )

    def _instant(self) -> UtcInstant:
        """Return the current instant in the canonical wire form."""
        return self._now().astimezone(timezone.utc).strftime(_INSTANT)


def _is_message_on(state: Any, interaction_id: str, channel_key: str) -> bool:
    """Return whether a head is a chat message on the given interaction channel."""
    if not isinstance(state, dict):
        return False
    record = cast("dict[str, Any]", state)
    schema = record.get("schema")
    if not isinstance(schema, dict):
        return False
    if cast("dict[str, Any]", schema).get("name") != "mug.api-08.chat-message":
        return False
    return (
        record.get("interaction_id") == interaction_id
        and record.get("channel_key") == channel_key
    )


def _state(record: _ChannelRecord) -> dict[str, Any]:
    """Dump one conversation record to its canonical persisted form."""
    return record.model_dump(mode="json", exclude_none=True)


def _typed(record: _ChannelRecord) -> TypedObject:
    """Wrap one conversation record as the command result carrying its own schema."""
    return TypedObject(schema=record.schema, data=_state(record))


__all__ = ["ConversationChannel"]
