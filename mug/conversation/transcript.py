"""The durable half of a conversation: what was said, and what is still coming.

The chat channel recorded a message digest and nothing else, and the text lived in
a per-connection transcript that died with the connection. So a participant who
refreshed the page lost the conversation, a model reply that was still being
generated was lost with it, and a late reply from a connection that had already
gone had nowhere to be recorded as discarded. NS-03 asks for exactly those three
things: the committed history restored, the pending turn restored, and an obsolete
result recorded as discarded rather than published.

This module is the state that makes them possible.

**The text is an artifact; the ledger holds the address.** That is the family's
privacy shape and it does not change here: a message is a digest in the canonical
stream, and the words sit in a content-addressed artifact the transcript points at.
A study that must not keep the words keeps no artifact.

**A turn has a generation, and only the current one may publish.** Beginning a turn
raises the generation. A reply carries the generation it was begun under, so a
result from a connection that has since been replaced is refused and recorded as
discarded. Without that number, a slow reply from an abandoned tab would arrive in
someone's conversation minutes later.

**Delivery is evidence, not a hope.** Each frame the participant is actually shown
is recorded as an API-09 ``SeatDelivery`` and an API-10 ``ExperiencedFrame`` beside
the canonical commit, under the capture policy this mount declares. That is what
makes "what they saw" answerable separately from "what was recorded".
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Annotated, Any, Final

from pydantic import Field

from mug.client.types import SeatDelivery, client_schema
from mug.events.types import CapturePolicy, CaptureStreamRule, ExperiencedFrame
from mug.kernel import (
    CommandTypeRef,
    Digest,
    SchemaRef,
    StreamPosition,
    TypedObject,
    UtcInstant,
    VersionStamp,
    etag,
)
from mug.kernel._base import KernelModel
from mug.kernel.ids import ArtifactId, InteractionId, MessageId, VisitId
from mug.kernel.refs import NonNegativeSafeInteger, PositiveSafeInteger
from mug.runtime import CommandContext, commit_command
from mug.storage import Store

# How much of one conversation the transcript holds. A conversation is bounded by
# the mount's own message cap; these bounds are the aggregate's own floor under it,
# so one runaway session cannot grow one record without limit.
MAX_MESSAGES: Final[int] = 512
MAX_EVIDENCE: Final[int] = 1024

_RECORD = CommandTypeRef(name="chat.record", version=0)


def _no_records() -> list[TurnRecord]:
    """Return an empty, typed message list for a transcript's default."""
    return []


def _no_generations() -> list[int]:
    """Return an empty, typed generation list for a transcript's default."""
    return []


def _no_deliveries() -> list[SeatDelivery]:
    """Return an empty, typed delivery list for a transcript's default."""
    return []


def _no_candidates() -> list[CandidateRecord]:
    """Return an empty, typed candidate list for a transcript's default."""
    return []


def _no_frames() -> list[ExperiencedFrame]:
    """Return an empty, typed experienced-frame list for a transcript's default."""
    return []
_CHAT_SEAT = "chat"


class TurnRecord(KernelModel):
    """One message the conversation holds: who wrote it, and where the words are."""

    message_id: MessageId
    author_actor_id: Annotated[str, Field(max_length=61)]
    artifact_id: ArtifactId
    sequence: PositiveSafeInteger


class CandidateRecord(KernelModel):
    """One reply that competed for a turn, and where its words are.

    A reply the participant did not choose is never delivered, so it is in no
    transcript history and nothing else says where its text lives. Without this the
    branch that was not taken would leave the platform as a digest of something
    nobody holds, which is exactly what an export of preference data must not do.
    """

    message_id: MessageId
    artifact_id: ArtifactId
    prompt_message_id: MessageId


class PendingTurn(KernelModel):
    """The model turn that is in flight, and the generation it was begun under."""

    generation: PositiveSafeInteger
    prompt_message_id: MessageId
    started_at: UtcInstant


class TranscriptState(KernelModel):
    """One conversation's durable state: its history, its turn, and its evidence.

    ``generation`` rises every time a turn begins, and a reply may only publish
    under the generation that is current. ``discarded`` names the generations whose
    results arrived too late -- a record of what was *not* shown, which is the only
    place that can be recorded at all.
    """

    visit_id: VisitId
    interaction_id: InteractionId
    channel_key: Annotated[str, Field(max_length=128)]
    capture: CapturePolicy
    generation: NonNegativeSafeInteger = 0
    messages: Annotated[list[TurnRecord], Field(max_length=MAX_MESSAGES)] = Field(
        default_factory=_no_records
    )
    pending: PendingTurn | None = None
    discarded: Annotated[
        list[NonNegativeSafeInteger], Field(max_length=MAX_EVIDENCE)
    ] = Field(default_factory=_no_generations)
    deliveries: Annotated[list[SeatDelivery], Field(max_length=MAX_EVIDENCE)] = Field(
        default_factory=_no_deliveries
    )
    experienced: Annotated[
        list[ExperiencedFrame], Field(max_length=MAX_EVIDENCE)
    ] = Field(default_factory=_no_frames)
    candidates: Annotated[
        list[CandidateRecord], Field(max_length=MAX_EVIDENCE)
    ] = Field(default_factory=_no_candidates)
    version: VersionStamp


def chat_capture_policy() -> CapturePolicy:
    """Return the capture policy a conversation runs under.

    Both streams, and the experienced one is declared explicitly: what a
    participant was shown is a separate claim from what was committed, and a policy
    that named only the canonical stream would be claiming they are the same.
    """
    return CapturePolicy(
        policy_key="chat",
        completeness="best-effort",
        streams=[
            CaptureStreamRule(stream_kind="event", profile="canonical"),
            CaptureStreamRule(stream_kind="experienced", profile="experienced"),
        ],
    )


def transcript_id_for(
    derive: Callable[[str, str], str], visit_id: str, occurrence_key: str
) -> str:
    """Return the aggregate that holds one visit's conversation at one step.

    It derives from the visit and the step, so a participant who refreshes reaches
    the conversation they were having rather than a second empty one.
    """
    return derive("activity", f"transcript:{visit_id}:{occurrence_key}")


def message_artifact_seed(message_id: str) -> str:
    """Return the seed one message's text artifact is addressed by."""
    return f"message:{message_id}"


def read_transcript(store: Store, transcript_id: str) -> TranscriptState | None:
    """Return one conversation's committed state, or None when it has none."""
    raw = store.load_aggregate(transcript_id)
    if not isinstance(raw, Mapping):
        return None
    try:
        return TranscriptState.model_validate(raw)
    except ValueError:
        return None


def _seat_delivery(
    payload_schema: SchemaRef, payload_digest: Digest, position: int
) -> SeatDelivery:
    """Build the per-seat evidence that one payload reached the participant."""
    return SeatDelivery(
        seat_key=_CHAT_SEAT,  # pyright: ignore[reportArgumentType]
        delivery_kind="message",
        payload_schema=payload_schema,
        payload_digest=payload_digest,
        stream_position=StreamPosition(
            stream_id="stream_019b6000-0000-7000-8000-000000000001", sequence=position
        ),
    )


def _experienced(position: int, delivered_at: str, kind: str) -> ExperiencedFrame:
    """Build the experienced-stream frame for one thing the participant saw."""
    return ExperiencedFrame(
        stream_position=StreamPosition(
            stream_id="stream_019b6000-0000-7000-8000-000000000001", sequence=position
        ),
        delivery_kind=kind,  # pyright: ignore[reportArgumentType]
        delivered_at=delivered_at,  # pyright: ignore[reportArgumentType]
    )


def message_schema() -> SchemaRef:
    """Return the pinned API-09 reference a delivered chat payload is typed by."""
    return SchemaRef(
        name="mug.api-09.seat-delivery",
        version=0,
        digest=Digest(algorithm="sha-256", hex=client_schema().bundle_digest),
    )


def opened(
    current: TranscriptState | None,
    *,
    visit_id: str,
    interaction_id: str,
    channel_key: str,
) -> TranscriptState:
    """Return the transcript this conversation starts from, fresh or restored."""
    if current is not None:
        return current
    body: dict[str, Any] = {
        "visit_id": visit_id,
        "interaction_id": interaction_id,
        "channel_key": channel_key,
        "capture": chat_capture_policy().model_dump(mode="json", exclude_none=True),
    }
    return TranscriptState(
        **body,  # pyright: ignore[reportArgumentType]
        version=VersionStamp(revision=1, etag=etag(body)),
    )


def with_message(
    state: TranscriptState,
    *,
    message_id: str,
    author_actor_id: str,
    artifact_id: str,
    sequence: int,
    content_digest: Digest,
    delivered_at: str,
) -> TranscriptState:
    """Return the transcript with one more message, and the evidence it was seen."""
    position = len(state.messages) + 1
    return _next(
        state,
        messages=[
            *state.messages,
            TurnRecord(
                message_id=message_id,  # pyright: ignore[reportArgumentType]
                author_actor_id=author_actor_id,
                artifact_id=artifact_id,  # pyright: ignore[reportArgumentType]
                sequence=sequence,
            ),
        ][-MAX_MESSAGES:],
        deliveries=[
            *state.deliveries,
            _seat_delivery(message_schema(), content_digest, position),
        ][-MAX_EVIDENCE:],
        experienced=[
            *state.experienced,
            _experienced(position, delivered_at, "delivered"),
        ][-MAX_EVIDENCE:],
    )


def with_candidates(
    state: TranscriptState,
    *,
    prompt_message_id: str,
    written: Sequence[tuple[str, str]],
) -> TranscriptState:
    """Return the transcript knowing where each candidate reply's words live.

    Every candidate is recorded, the chosen one included, because which of them the
    thread kept is the ``CandidateReplySet``'s to say and not this record's. A
    candidate already known is not written twice, so a reconnection that reads the
    turn again leaves the transcript as it found it.
    """
    known = {record.message_id for record in state.candidates}
    fresh = [
        CandidateRecord(
            message_id=message_id,  # pyright: ignore[reportArgumentType]
            artifact_id=artifact_id,  # pyright: ignore[reportArgumentType]
            prompt_message_id=prompt_message_id,  # pyright: ignore[reportArgumentType]
        )
        for message_id, artifact_id in written
        if message_id not in known
    ]
    if not fresh:
        return state
    return _next(state, candidates=[*state.candidates, *fresh][-MAX_EVIDENCE:])


def with_turn_begun(
    state: TranscriptState, *, prompt_message_id: str, started_at: str
) -> TranscriptState:
    """Return the transcript with a model turn in flight at the next generation."""
    generation = state.generation + 1
    return _next(
        state,
        generation=generation,
        pending=PendingTurn(
            generation=generation,  # pyright: ignore[reportArgumentType]
            prompt_message_id=prompt_message_id,  # pyright: ignore[reportArgumentType]
            started_at=started_at,  # pyright: ignore[reportArgumentType]
        ),
    )


def with_turn_ended(state: TranscriptState) -> TranscriptState:
    """Return the transcript with no turn in flight."""
    return _next(state, pending=None)


def with_discarded(
    state: TranscriptState, generation: int, *, discarded_at: str
) -> TranscriptState:
    """Return the transcript with one obsolete generation recorded as discarded.

    The record of what was *not* shown is the only place it can be recorded: the
    reply was never posted, so no message names it and no delivery receipt does.
    """
    if generation in state.discarded:
        return state
    return _next(
        state,
        discarded=[*state.discarded, generation][-MAX_EVIDENCE:],
        experienced=[
            *state.experienced,
            _experienced(len(state.messages) + 1, discarded_at, "skipped"),
        ][-MAX_EVIDENCE:],
    )


def _next(state: TranscriptState, **changes: Any) -> TranscriptState:
    """Return the transcript one change later, at the next revision."""
    updated = state.model_copy(update=changes)
    body = updated.model_dump(mode="json", exclude_none=True, exclude={"version"})
    return updated.model_copy(
        update={
            "version": VersionStamp(
                revision=state.version.revision + 1, etag=etag(body)
            )
        }
    )


def is_current(state: TranscriptState, generation: int) -> bool:
    """Return whether a reply begun at this generation may still publish.

    A turn begun on a connection that has since been replaced is not current, and a
    reply under it publishes nothing. This is the whole fence.
    """
    return state.generation == generation


async def record_transcript(
    state: TranscriptState,
    *,
    transcript_id: str,
    expected_revision: int | None,
    context: CommandContext,
    store: Store,
) -> bool:
    """Commit one conversation's state at the revision the caller read."""
    receipt = await commit_command(
        context,
        command=_RECORD,
        new_state=state.model_dump(mode="json", exclude_none=True),
        result=TypedObject(
            schema=state.capture.schema,
            data={
                "outcome": "recorded",
                "visit_id": state.visit_id,
                "messages": len(state.messages),
                "generation": state.generation,
            },
        ),
        store=store,
        expected_revision=expected_revision,
    )
    return receipt.outcome == "accepted"


def history(state: TranscriptState) -> Sequence[TurnRecord]:
    """Return the messages a reconnecting participant is owed, oldest first."""
    return tuple(state.messages)


__all__ = [
    "MAX_EVIDENCE",
    "MAX_MESSAGES",
    "CandidateRecord",
    "PendingTurn",
    "TranscriptState",
    "TurnRecord",
    "chat_capture_policy",
    "history",
    "is_current",
    "message_artifact_seed",
    "message_schema",
    "opened",
    "read_transcript",
    "record_transcript",
    "transcript_id_for",
    "with_candidates",
    "with_discarded",
    "with_message",
    "with_turn_begun",
    "with_turn_ended",
]
