"""Conversation, routing, and delivery (API-08, layer L1).

This family owns six record types: the authored ``ChatMessage``, the
``ConversationSegment`` that groups a contiguous run of messages, the
``ContextSnapshot`` that pins the context of a model request, the ``TurnPolicy``
that governs model activation, the ``DeliveryReceipt`` that proves receipt, and
the ``CandidateReplySet`` that records which reply a thread kept. Each record
references kernel (L0) id aliases.

``mug.conversation.runtime`` adds the channel runtime over these records: the
``ConversationChannel`` orders, delivers, and snapshots a channel through the
command spine (the chat analog of the game loop). ``mug.conversation.turns`` holds
the pure turn-policy decision (``may_activate``) that governs when a model speaks;
the model call that produces a reply is composed above, in ``mug.agents``.
"""

from __future__ import annotations

from mug.conversation.runtime import ConversationChannel
from mug.conversation.turns import may_activate
from mug.conversation.types import (
    CandidateReplySet,
    ChatMessage,
    ContextSnapshot,
    ConversationSegment,
    DeliveryReceipt,
    TurnPolicy,
    conversation_schema,
)

__all__ = [
    "CandidateReplySet",
    "ChatMessage",
    "ContextSnapshot",
    "ConversationChannel",
    "ConversationSegment",
    "DeliveryReceipt",
    "TurnPolicy",
    "conversation_schema",
    "may_activate",
]
