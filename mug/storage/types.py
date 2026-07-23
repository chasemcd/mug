"""The four persisted objects that API-11 owns.

You construct each object with its data alone; the ``schema`` envelope fills
itself from the frozen bundle. The frozen JSON-Schema corpus stays the authority,
and ``storage_schema`` loads it for the conformance test.

Two invariants are not expressible in JSON Schema and live here as validators:

- a finalized artifact's digest equals its intended digest;
- a confirmed outbox record names at least one event.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from mug.kernel import (
    ArtifactRef,
    DataHandlingRef,
    Digest,
    ReceiptDurability,
    ResourceRef,
    SchemaBundle,
    SchemaRef,
    VersionStamp,
    load_family_schema,
)
from mug.kernel._base import KernelModel
from mug.kernel.ids import CommandId, EventId, UploadId

_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs/architecture/phase-0/api-11/schemas/v0/storage.schema.json"
)


@lru_cache(maxsize=1)
def storage_schema() -> SchemaBundle:
    """Return the loaded API-11 bundle (with the shared kernel registered)."""
    return load_family_schema(str(_SCHEMA_PATH))


def _schema_ref(name: str) -> SchemaRef:
    """Build the pinned schema reference for one object from the frozen bundle."""
    digest = Digest(algorithm="sha-256", hex=storage_schema().bundle_digest)
    return SchemaRef(name=name, version=0, digest=digest)


_Instant = Annotated[
    str,
    Field(
        pattern=(
            r"^[0-9]{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])"
            r"T(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]\.[0-9]{6}Z$"
        )
    ),
]
_MediaType = Annotated[
    str,
    Field(
        pattern=r"^[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*$",
        max_length=127,
    ),
]
_EventIds = Annotated[list[EventId], Field(max_length=256)]


class ArtifactStaging(KernelModel):
    """A staging ticket: an intended digest and size before the bytes finalize."""

    # 'schema' is the contract field name; it shadows BaseModel.schema.
    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-11.artifact-staging")
    )
    upload_id: UploadId
    intended_digest: Digest
    size_bytes: Annotated[int, Field(ge=0, le=9007199254740991)]
    media_type: _MediaType
    status: Literal["staged", "finalized", "aborted"] = "staged"
    data_handling: DataHandlingRef


class FinalizedArtifact(KernelModel):
    """A finalized artifact: the committed reference plus its staging provenance."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-11.finalized-artifact")
    )
    artifact: ArtifactRef
    staged_upload_id: UploadId
    intended_digest: Digest
    finalized_at: _Instant

    @model_validator(mode="after")
    def _digest_matches_intended(self) -> FinalizedArtifact:
        if self.artifact.digest.hex != self.intended_digest.hex:
            raise ValueError(
                "finalized artifact digest does not match the intended digest"
            )
        return self


class OutboxRecord(KernelModel):
    """One outbox entry: a command, a destination, a status, and its events."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-11.outbox-record")
    )
    command_id: CommandId
    destination: Literal["event-bus", "projector", "external-integration"]
    status: Literal["pending", "dispatched", "confirmed"] = "pending"
    attempt: Annotated[int, Field(ge=1, le=9007199254740991)] = 1
    event_ids: _EventIds = Field(default_factory=list)

    @model_validator(mode="after")
    def _confirmed_names_events(self) -> OutboxRecord:
        if self.status == "confirmed" and not self.event_ids:
            raise ValueError("a confirmed outbox record must name at least one event")
        return self


class UnitOfWorkReceipt(KernelModel):
    """The acknowledgment of one atomic relational commit.

    The commit wrote aggregate state, the idempotency record, the canonical
    events, and the outbox entries together.
    """

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-11.unit-of-work-receipt")
    )
    command_id: CommandId
    aggregate_ref: ResourceRef
    aggregate_version: VersionStamp
    committed_event_ids: _EventIds
    outbox_included: bool
    durability: ReceiptDurability
