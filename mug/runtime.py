"""The command-handling spine shared by the family services.

A command handler does the domain work -- it gates the input, assembles the new
aggregate state, and builds the result -- and then calls this spine to make the
change durable. ``commit_command`` appends the command's event at a fresh stream
position, commits the state and the event together, and answers with a durable
commit-class receipt. ``reject_command`` answers a refusal with a no-effect
rejected receipt and a safe error.

The spine takes any backend that satisfies the ``Store`` Protocol. A command
creates an aggregate (``expected_revision`` is None) or
updates one (``expected_revision`` is the revision the caller last saw), and the
store guards the revision either way.
"""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path
from typing import NamedTuple

from mug.events import EventEnvelope
from mug.kernel import (
    CommandReceipt,
    CommandTypeRef,
    DataHandlingRef,
    Digest,
    DomainError,
    IdempotencyKey,
    PrincipalRef,
    ProducerPosition,
    ReceiptDurability,
    ResourceRef,
    RetryDirective,
    SchemaBundle,
    SchemaRef,
    TypedObject,
    compute_digest,
    load_family_schema,
    load_shared_kernel_schema,
)
from mug.kernel._base import KernelModel
from mug.kernel.errors import ErrorCategory, RetryMode
from mug.kernel.ids import (
    CommandId,
    ErrorId,
    EventId,
    ProducerEpochId,
    ReceiptId,
    RegisteredMugId,
    RequestId,
    StreamId,
)
from mug.kernel.refs import (
    CommandReceiptSchemaRef,
    DomainErrorSchemaRef,
    PositiveSafeInteger,
    PublicHandle,
    UtcInstant,
)
from mug.storage import StorageError, Store, UnitOfWorkReceipt

# A store conflict maps to a category and a retry mode. Its code is already a
# kernel code, so the code passes through unchanged.
_STORE_CONFLICT: dict[str, tuple[ErrorCategory, RetryMode]] = {
    "resource.already_exists": ("conflict", "poll_existing"),
    "command.revision_conflict": ("conflict", "refresh_then_new_command"),
    "command.idempotency_conflict": ("conflict", "never"),
    "lease.stale_generation": ("stale", "operator_reconciliation"),
}


class FencingClaim(KernelModel):
    """A producer's fencing token for its stream: an epoch and its generation.

    The coordinator installs a producer with a strictly greater generation. The
    store fences a write whose generation is below the one installed on the
    stream, so a superseded producer never writes after a newer one takes over.
    """

    epoch_id: ProducerEpochId
    generation: PositiveSafeInteger


class CommandContext(KernelModel):
    """The runtime authority a verified gateway supplies for one command.

    The gateway mints the identifiers, resolves the principal, and reads the
    clock; the handler never invents them. ``aggregate_id`` is the identifier of
    the aggregate the command creates or updates. ``public_handle`` is set only
    for a command that issues a public-handle token (a launch ticket); the token
    is keyed by that handle, and ``aggregate_id`` names the resource it admits to.
    """

    command_id: CommandId
    receipt_id: ReceiptId
    error_id: ErrorId
    request_id: RequestId | None = None
    idempotency_key: IdempotencyKey
    event_id: EventId
    stream_id: StreamId
    producer: ProducerPosition
    fencing: FencingClaim | None = None
    aggregate_id: RegisteredMugId
    public_handle: PublicHandle | None = None
    principal: PrincipalRef
    recorded_at: UtcInstant
    event_data_handling: DataHandlingRef
    # The event this command answers, when it answers one. It is what relates two
    # independently ordered streams without inventing one order over both: a model
    # reply names the message it replied to, wherever each of them sits in its own
    # stream. Unset means the command answers nothing in particular.
    causation_event_id: EventId | None = None


def answering(context: CommandContext, event_id: str | None) -> CommandContext:
    """Return the same command context, recording the event it answers.

    A reply names the message that prompted it, wherever the two sit in their own
    streams. What a command answers is not part of what the command **is**, so the
    identifiers are untouched and a retry stays idempotent: this adds a fact about
    the command, not a new command. It mints nothing, so the gateway is still the
    one entropy boundary.
    """
    if event_id is None:
        return context
    return context.model_copy(update={"causation_event_id": event_id})


def _generation(context: CommandContext) -> int | None:
    """Return the producer's fencing generation, or None when it is unfenced."""
    return context.fencing.generation if context.fencing is not None else None


def _event_detail(
    context: CommandContext, new_state: object, result: TypedObject
) -> dict[str, object]:
    """Draft the ledger fields for the command's event, minus its position.

    The store assigns the stream position; ``read_ledger`` reads these fields
    back and materializes the canonical event envelope. The payload digest binds
    the committed state, and the event schema is the command result's schema.
    """
    return {
        "producer_position": context.producer.model_dump(mode="json"),
        "event_schema": result.schema.model_dump(mode="json"),
        "payload_digest": compute_digest(new_state).model_dump(mode="json"),
        "recorded_at": context.recorded_at,
        "data_handling": context.event_data_handling.model_dump(mode="json"),
        "causation_event_id": context.causation_event_id,
    }


_COMMAND_RESULTS_PATH = str(
    Path(__file__).resolve().parents[1]
    / "docs/architecture/phase-0/command-results/schemas/v0/command-results.schema.json"
)


def command_results_schema() -> SchemaBundle:
    """Return the frozen command-results bundle (loaded and cached once).

    It holds the schemas for command results that do not mirror a persisted
    record. A result that is a frozen record uses that record's own schema.
    """
    return load_family_schema(_COMMAND_RESULTS_PATH)


def result_ref(name: str) -> SchemaRef:
    """Build a pinned schema reference into the frozen command-results bundle."""
    return SchemaRef(
        name=name,
        version=0,
        digest=Digest(algorithm="sha-256", hex=command_results_schema().bundle_digest),
    )


def _shared_digest() -> Digest:
    return Digest(algorithm="sha-256", hex=load_shared_kernel_schema().bundle_digest)


def _receipt_schema() -> CommandReceiptSchemaRef:
    return CommandReceiptSchemaRef(
        name="mug.command-receipt", version=0, digest=_shared_digest()
    )


async def commit_command(
    context: CommandContext,
    *,
    command: CommandTypeRef,
    new_state: object,
    result: TypedObject,
    store: Store,
    expected_revision: int | None = None,
) -> CommandReceipt:
    """Commit one aggregate and its event, and return a commit-class receipt.

    ``expected_revision`` is None to create an aggregate, or the revision the
    caller last saw to update one; a stale revision becomes a rejected receipt.
    The store assigns the event its stream position and records it under the key,
    so a replay reports the same position with no second effect. A store conflict
    becomes a rejected, no-effect receipt. The durability profile is the command
    name, so the receipt names the command that made the change.
    """
    try:
        uow = await store.commit(
            command_id=context.command_id,
            idempotency_key=context.idempotency_key,
            aggregate_id=context.aggregate_id,
            expected_revision=expected_revision,
            new_state=new_state,
            stream_events=[(context.stream_id, context.event_id)],
            event_details={context.event_id: _event_detail(context, new_state, result)},
            producer_generation=_generation(context),
            durability_profile=command.name,
        )
    except StorageError as error:
        category, retry = _STORE_CONFLICT.get(error.code, ("internal", "never"))
        return reject_command(
            context,
            command=command,
            code=error.code,
            category=category,
            message=error.code,
            retry=retry,
        )
    return _accepted_receipt(context, command, uow, store, result)


def _accepted_receipt(
    context: CommandContext,
    command: CommandTypeRef,
    uow: UnitOfWorkReceipt,
    store: Store,
    result: TypedObject,
) -> CommandReceipt:
    """Assemble the accepted commit receipt shared by the commit paths."""
    return CommandReceipt(
        schema=_receipt_schema(),
        receipt_id=context.receipt_id,
        command_id=context.command_id,
        command=command,
        idempotency_key=context.idempotency_key,
        outcome="accepted",
        receipt_class="commit",
        durability=uow.durability,
        recorded_at=context.recorded_at,
        resource=uow.aggregate_ref,
        version_stamp=uow.aggregate_version,
        stream_positions=store.positions_for(context.idempotency_key),
        result=result,
    )


class LedgerEvent(NamedTuple):
    """One canonical event to append: its schema and its content digest."""

    event_schema: SchemaRef
    payload_digest: Digest


def _derive_event_id(base_event_id: str, index: int) -> str:
    """Derive one valid, distinct event id from the context event id and index.

    A captured run appends many events under one minted context, yet each event
    needs its own id. The id derives purely from the context event id body and
    the event index, so a replay of the same content re-derives the same ids and
    the store recognizes the replay. No new entropy enters here; the gateway
    stays the single entropy boundary.
    """
    body = base_event_id.split("_", 1)[1]
    raw = bytearray(hashlib.sha256(f"{body}:{index}".encode()).digest()[:16])
    raw[6] = 0x70 | (raw[6] & 0x0F)
    raw[8] = 0x80 | (raw[8] & 0x3F)
    hexed = raw.hex()
    return (
        f"event_{hexed[0:8]}-{hexed[8:12]}-{hexed[12:16]}-{hexed[16:20]}-{hexed[20:32]}"
    )


# How many committed events one unit-of-work receipt can name (API-11 caps the
# list at 256). A run with more frames than this is committed in consecutive parts.
_EVENTS_PER_RECEIPT = 256


def _derive_idempotency_key(base_key: str, part: int) -> str:
    """Derive the idempotency key for one part of a batched capture.

    The first part keeps the key the gateway minted, so a capture that fits in one
    commit is unchanged. Each later part derives its own key from that one and the
    part number, so a repeat of the whole capture re-derives the same keys and the
    store recognizes every part as the repeat it is. No new entropy enters here; the
    gateway stays the single entropy boundary.
    """
    if part == 0:
        return base_key
    body = base_key.split("_", 1)[1]
    raw = hashlib.sha256(f"{body}:part{part}".encode()).digest()[:16]
    return "idem_" + base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _captured_detail(context: CommandContext, event: LedgerEvent) -> dict[str, object]:
    """Draft the ledger fields for one captured event under the context."""
    return {
        "producer_position": context.producer.model_dump(mode="json"),
        "event_schema": event.event_schema.model_dump(mode="json"),
        "payload_digest": event.payload_digest.model_dump(mode="json"),
        "recorded_at": context.recorded_at,
        "data_handling": context.event_data_handling.model_dump(mode="json"),
        "causation_event_id": context.causation_event_id,
    }


async def commit_capture(
    context: CommandContext,
    *,
    command: CommandTypeRef,
    new_state: object,
    events: list[LedgerEvent],
    result: TypedObject,
    store: Store,
    expected_revision: int | None = None,
) -> CommandReceipt:
    """Commit one aggregate and a batch of canonical events on its stream.

    The single-event ``commit_command`` appends the command's own event; a
    captured run appends one event per recorded record -- a transition per frame
    and the closing boundary -- all on the aggregate's stream. Each event binds its
    own record digest, so the stream is the full, ordered lineage of the run. A
    store conflict becomes a no-effect rejection.

    **A run longer than one receipt can name is committed in parts.** A unit-of-work
    receipt names at most ``_EVENTS_PER_RECEIPT`` committed events (API-11), and an
    episode has one event per frame, so a game of a few thousand frames is more than
    one commit can report. The parts are consecutive appends to the one stream in
    frame order, each with its own derived idempotency key, so a repeat of the whole
    capture re-derives the same keys and the same event ids and adds nothing. The
    aggregate head is the finished run and is written by every part, because the
    capture runs after the episode ended and the head is already known.
    """
    revision = expected_revision
    uow = None
    for part, start in enumerate(range(0, max(len(events), 1), _EVENTS_PER_RECEIPT)):
        batch = events[start : start + _EVENTS_PER_RECEIPT]
        event_ids = [
            _derive_event_id(context.event_id, start + index)
            for index in range(len(batch))
        ]
        stream_events = [(context.stream_id, event_id) for event_id in event_ids]
        event_details = {
            event_id: _captured_detail(context, event)
            for event_id, event in zip(event_ids, batch, strict=True)
        }
        try:
            uow = await store.commit(
                command_id=context.command_id,
                idempotency_key=_derive_idempotency_key(context.idempotency_key, part),
                aggregate_id=context.aggregate_id,
                expected_revision=revision,
                new_state=new_state,
                stream_events=stream_events,
                event_details=event_details,
                producer_generation=_generation(context),
                durability_profile=command.name,
            )
        except StorageError as error:
            category, retry = _STORE_CONFLICT.get(error.code, ("internal", "never"))
            return reject_command(
                context,
                command=command,
                code=error.code,
                category=category,
                message=error.code,
                retry=retry,
            )
        revision = uow.aggregate_version.revision if uow.aggregate_version else None
    assert uow is not None
    return _accepted_receipt(context, command, uow, store, result)


async def issue_token_command(
    context: CommandContext,
    *,
    command: CommandTypeRef,
    new_state: object,
    result: TypedObject,
    store: Store,
) -> CommandReceipt:
    """Issue one public-handle token and return a commit-class receipt.

    A token is keyed by ``context.public_handle`` and has no revision, so the
    receipt carries no version stamp; its ``resource`` names the aggregate the
    token admits to (``context.aggregate_id``). The store appends the issuance
    event, so a replay reports the same position with no second effect.
    """
    handle = context.public_handle
    if handle is None:
        return reject_command(
            context,
            command=command,
            code="protocol.invalid_envelope",
            category="protocol",
            message="a token command requires an issued handle",
            retry="never",
        )
    try:
        positions = await store.issue_token(
            command_id=context.command_id,
            idempotency_key=context.idempotency_key,
            handle=handle,
            new_state=new_state,
            stream_events=[(context.stream_id, context.event_id)],
            event_details={context.event_id: _event_detail(context, new_state, result)},
            producer_generation=_generation(context),
        )
    except StorageError as error:
        category, retry = _STORE_CONFLICT.get(error.code, ("internal", "never"))
        return reject_command(
            context,
            command=command,
            code=error.code,
            category=category,
            message=error.code,
            retry=retry,
        )
    return CommandReceipt(
        schema=_receipt_schema(),
        receipt_id=context.receipt_id,
        command_id=context.command_id,
        command=command,
        idempotency_key=context.idempotency_key,
        outcome="accepted",
        receipt_class="commit",
        durability=ReceiptDurability(
            receipt="transactional", effect="transactional", profile=command.name
        ),
        recorded_at=context.recorded_at,
        resource=ResourceRef(id=context.aggregate_id),
        stream_positions=positions,
        result=result,
    )


def _envelope(record: dict[str, object]) -> EventEnvelope:
    """Materialize one canonical event envelope from a stored ledger record.

    The stored record keeps the stream id and sequence flat; the envelope nests
    them as a stream position. The ``schema`` envelope fills itself.
    """
    return EventEnvelope.model_validate(
        {
            "event_id": record["event_id"],
            "stream_position": {
                "stream_id": record["stream_id"],
                "sequence": record["sequence"],
            },
            "producer_position": record["producer_position"],
            "event_schema": record["event_schema"],
            "payload_digest": record["payload_digest"],
            "recorded_at": record["recorded_at"],
            "causation_event_id": record["causation_event_id"],
            "data_handling": record["data_handling"],
        }
    )


def read_ledger(
    store: Store, stream_id: str, after_sequence: int = 0
) -> list[EventEnvelope]:
    """Return one stream's canonical event envelopes after a sequence, in order.

    The store keeps the raw event fields with the position it assigned; this
    read-model wraps each into an ``EventEnvelope``. The store never builds the
    envelope itself, since the events family is an independent sibling.
    """
    return [
        _envelope(record) for record in store.stream_records(stream_id, after_sequence)
    ]


def reject_command(
    context: CommandContext,
    *,
    command: CommandTypeRef,
    code: str,
    category: ErrorCategory,
    message: str,
    retry: RetryMode,
    details: TypedObject | None = None,
) -> CommandReceipt:
    """Build a rejected, no-effect receipt carrying a safe domain error."""
    error = DomainError(
        schema=DomainErrorSchemaRef(
            name="mug.domain-error", version=0, digest=_shared_digest()
        ),
        error_id=context.error_id,
        request_id=context.request_id,
        recorded_at=context.recorded_at,
        command=command,
        code=code,
        category=category,
        safe_message=message,
        retry=RetryDirective(mode=retry),
        details=details,
        support_reference=context.error_id,
    )
    return CommandReceipt(
        schema=_receipt_schema(),
        receipt_id=context.receipt_id,
        command_id=context.command_id,
        command=command,
        idempotency_key=context.idempotency_key,
        outcome="rejected",
        receipt_class="ingress",
        durability=ReceiptDurability(
            receipt="runtime", effect="none", profile=command.name
        ),
        recorded_at=context.recorded_at,
        stream_positions={},
        error=error,
    )
