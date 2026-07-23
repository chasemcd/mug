"""The six objects that API-08 owns: chat, routing, context, and delivery.

You construct each object with its data alone; the ``schema`` envelope fills
itself from the frozen bundle. The frozen JSON-Schema corpus stays the authority,
and ``conversation_schema`` loads it for the conformance test.

Every message, actor, and interaction identity lives in the kernel (layer L0); a
record references those id aliases. This family adds no runtime that mints ids or
routes turns.

Two invariants are not expressible in JSON Schema and live here as validators:

- a conversation segment's sequence span matches its message count;
- a candidate reply set selects one of the presented candidates.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from mug.kernel import (
    Digest,
    IdempotencyKey,
    SchemaBundle,
    SchemaRef,
    UtcInstant,
    load_family_schema,
)
from mug.kernel._base import KernelModel
from mug.kernel.ids import (
    ActorInstanceId,
    InteractionId,
    MessageId,
    PreferenceResponseId,
)
from mug.kernel.refs import PositiveSafeInteger

_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs/architecture/phase-0/api-08/schemas/v0/conversation.schema.json"
)


@lru_cache(maxsize=1)
def conversation_schema() -> SchemaBundle:
    """Return the loaded API-08 bundle (with the shared kernel registered)."""
    return load_family_schema(str(_SCHEMA_PATH))


def _schema_ref(name: str) -> SchemaRef:
    """Build the pinned schema reference for one object from the frozen bundle."""
    digest = Digest(algorithm="sha-256", hex=conversation_schema().bundle_digest)
    return SchemaRef(name=name, version=0, digest=digest)


_AuthoringKey = Annotated[
    str, Field(pattern=r"^[a-z][a-z0-9]*(?:[-_.][a-z0-9]+)*$", max_length=128)
]


class ChatMessage(KernelModel):
    """One authored message in a channel: identity, order, and content digest."""

    # 'schema' is the contract field name; it shadows BaseModel.schema.
    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-08.chat-message")
    )
    message_id: MessageId
    interaction_id: InteractionId
    channel_key: _AuthoringKey
    author_actor_id: ActorInstanceId
    sequence: PositiveSafeInteger
    content_digest: Digest
    visibility: Literal["public", "team", "private"]
    idempotency_key: IdempotencyKey
    submitted_at: UtcInstant


class ConversationSegment(KernelModel):
    """A contiguous run of messages in a channel, keyed by its sequence span."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-08.conversation-segment")
    )
    channel_key: _AuthoringKey
    message_ids: Annotated[list[MessageId], Field(min_length=1, max_length=512)]
    start_sequence: PositiveSafeInteger
    end_sequence: PositiveSafeInteger

    @model_validator(mode="after")
    def _span_matches_message_count(self) -> ConversationSegment:
        span = self.end_sequence - self.start_sequence + 1
        if span != len(self.message_ids):
            raise ValueError(
                "segment sequence span must match its message count"
            )
        return self


class ContextSnapshot(KernelModel):
    """The exact prior context that a model request used, joined to a message."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-08.context-snapshot")
    )
    message_id: MessageId
    model_request_digest: Digest
    included_message_ids: Annotated[
        list[MessageId], Field(min_length=1, max_length=512)
    ]
    captured_at: UtcInstant


class TurnPolicy(KernelModel):
    """How a channel activates a model per turn, and how often it may activate."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-08.turn-policy")
    )
    channel_key: _AuthoringKey
    activation: Literal["free", "round-robin", "mention", "moderated"]
    max_model_activations_per_turn: PositiveSafeInteger


class DeliveryReceipt(KernelModel):
    """Proof that a recipient received a message, and from which stream."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-08.delivery-receipt")
    )
    message_id: MessageId
    recipient_actor_id: ActorInstanceId
    delivered_sequence: PositiveSafeInteger
    evidence_stream: Literal["canonical", "experienced"]
    delivered_at: UtcInstant


class CandidateReplySet(KernelModel):
    """The candidate replies shown for one prompt, and the one the thread kept."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-08.candidate-reply-set")
    )
    channel_key: _AuthoringKey
    prompt_message_id: MessageId
    candidate_message_ids: Annotated[
        list[MessageId], Field(min_length=2, max_length=16)
    ]
    selected_message_id: MessageId
    preference_response_id: PreferenceResponseId
    recorded_at: UtcInstant

    @model_validator(mode="after")
    def _selection_is_presented(self) -> CandidateReplySet:
        if self.selected_message_id not in self.candidate_message_ids:
            raise ValueError(
                "the selected reply must be one of the presented candidates"
            )
        return self
