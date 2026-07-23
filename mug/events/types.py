"""The three objects that API-10 owns: events, capture policy, and provenance.

You construct each object with its data alone; the ``schema`` envelope fills
itself from the frozen bundle. The frozen JSON-Schema corpus stays the authority,
and ``events_schema`` loads it for the conformance test.

The stream and producer position types live in the kernel (layer L0); an event
envelope references them. This family adds no runtime that mints positions -- that
producer-epoch machinery stays deferred (ADR-0009/0010).

Three invariants are not expressible in JSON Schema and live here as validators:

- a capture stream rule's profile agrees with its stream kind;
- a policy that captures the experienced stream also captures the canonical one;
- a corrected experienced frame names the canonical frame that superseded it.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from mug.kernel import (
    DataHandlingRef,
    Digest,
    ProducerPosition,
    SchemaBundle,
    SchemaRef,
    StreamPosition,
    UtcInstant,
    load_family_schema,
)
from mug.kernel._base import KernelModel
from mug.kernel.ids import EventId

_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs/architecture/phase-0/api-10/schemas/v0/evidence.schema.json"
)


@lru_cache(maxsize=1)
def events_schema() -> SchemaBundle:
    """Return the loaded API-10 bundle (with the shared kernel registered)."""
    return load_family_schema(str(_SCHEMA_PATH))


def _schema_ref(name: str) -> SchemaRef:
    """Build the pinned schema reference for one object from the frozen bundle."""
    digest = Digest(algorithm="sha-256", hex=events_schema().bundle_digest)
    return SchemaRef(name=name, version=0, digest=digest)


_AuthoringKey = Annotated[
    str, Field(pattern=r"^[a-z][a-z0-9]*(?:[-_.][a-z0-9]+)*$", max_length=128)
]


class EventEnvelope(KernelModel):
    """One immutable, append-only canonical event: identity, order, and payload."""

    # 'schema' is the contract field name; it shadows BaseModel.schema.
    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-10.event-envelope")
    )
    event_id: EventId
    stream_position: StreamPosition
    producer_position: ProducerPosition
    event_schema: SchemaRef
    payload_digest: Digest
    recorded_at: UtcInstant
    causation_event_id: EventId | None = None
    data_handling: DataHandlingRef


class CaptureStreamRule(KernelModel):
    """One per-stream capture rule inside a policy: a stream kind and a profile."""

    stream_kind: Literal["trajectory", "event", "render", "experienced"]
    profile: Literal["canonical", "experienced"]


class CapturePolicy(KernelModel):
    """Which streams a session captures, under which profile, and how completely."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-10.capture-policy")
    )
    policy_key: _AuthoringKey
    completeness: Literal["complete", "best-effort"]
    streams: Annotated[list[CaptureStreamRule], Field(min_length=1, max_length=64)]

    @model_validator(mode="after")
    def _profiles_agree_and_cover_canonical(self) -> CapturePolicy:
        for rule in self.streams:
            experienced = rule.stream_kind == "experienced"
            if experienced != (rule.profile == "experienced"):
                raise ValueError(
                    "capture profile must agree with the experienced stream kind"
                )
        profiles = {rule.profile for rule in self.streams}
        if "experienced" in profiles and "canonical" not in profiles:
            raise ValueError(
                "capturing the experienced stream requires capturing the canonical one"
            )
        return self


class ExperiencedFrame(KernelModel):
    """What a participant was actually rendered, joinable to the canonical stream."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-10.experienced-frame")
    )
    stream_position: StreamPosition
    canonical_event_id: EventId | None = None
    supersedes_experienced_position: StreamPosition | None = None
    delivery_kind: Literal["delivered", "speculative", "corrected", "skipped"]
    delivered_at: UtcInstant

    @model_validator(mode="after")
    def _corrected_names_canonical(self) -> ExperiencedFrame:
        if self.delivery_kind == "corrected" and self.canonical_event_id is None:
            raise ValueError("a corrected frame must name its canonical event")
        return self
