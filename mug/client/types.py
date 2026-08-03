"""The nine records that API-09 owns: the participant client, realtime, and uploads.

You construct each object with its data alone; the ``schema`` envelope fills
itself from the frozen bundle. The frozen JSON-Schema corpus stays the authority,
and ``client_schema`` loads it for the conformance test.

This family models the client-facing records only and adds no runtime. The socket,
the queue, the upload store, and the readiness gate stay deferred. Enforcement is
never client-side: ``MonitoringMeasurement`` only reports samples; the server
evaluates them against API-06's server-authoritative policy (pinned, inert here).

Five invariants live here as validators. Four are not expressible in JSON Schema:

- an ``accepted`` transport ack must carry a stream position;
- a bridge message must not name a reserved identity key;
- a monitoring measurement must not repeat a metric;
- a ``join`` gate op must anchor an interaction.

The fifth reproduces the schema's per-op shape rule for a bridge message, because
Pydantic field types alone cannot express the conditional key/value presence.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field, model_validator

from mug.kernel import (
    CapabilitySet,
    Digest,
    Duration,
    IdempotencyKey,
    PublicHandle,
    SchemaBundle,
    SchemaRef,
    SeatKey,
    StreamPosition,
    UtcInstant,
    load_family_schema,
)
from mug.kernel._base import KernelModel
from mug.kernel.ids import CommandId, UploadId
from mug.kernel.refs import (
    DeploymentRevisionRef,
    NonNegativeSafeInteger,
    PositiveSafeInteger,
    SafeInteger,
)

_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs/architecture/phase-0/api-09/schemas/v0/client.schema.json"
)

# The bridge keys that trusted page JavaScript must never set. They name identity
# or assignment, which the server alone owns (RP invariant ``bridgeUntrusted``).
_RESERVED_BRIDGE_KEYS = frozenset(
    {
        "participant",
        "participant_id",
        "enrollment_id",
        "identity",
        "seat",
        "seat_key",
        "condition",
        "treatment",
        "assignment",
    }
)


@lru_cache(maxsize=1)
def client_schema() -> SchemaBundle:
    """Return the loaded API-09 bundle (with the shared kernel registered)."""
    return load_family_schema(str(_SCHEMA_PATH))


def _schema_ref(name: str) -> SchemaRef:
    """Build the pinned schema reference for one object from the frozen bundle."""
    digest = Digest(algorithm="sha-256", hex=client_schema().bundle_digest)
    return SchemaRef(name=name, version=0, digest=digest)


_AuthoringKey = Annotated[
    str, Field(pattern=r"^[a-z][a-z0-9]*(?:[-_.][a-z0-9]+)*$", max_length=128)
]
_KeyName = Annotated[
    str, Field(pattern=r"^[a-z][a-z0-9]*(?:[-_][a-z0-9]+)*$", max_length=32)
]
# One env action value: a discrete action code or a continuous action vector.
_EnvActionValue = SafeInteger | Annotated[
    list[float], Field(min_length=1, max_length=64)
]
# The no-input fill: an env action value, or the sentinel that repeats the last.
_NoInputFill = _EnvActionValue | Literal["repeat_last"]
class ClientHandshake(KernelModel):
    """The first client frame: it pins the accepted deployment and capabilities."""

    # 'schema' is the contract field name; it shadows BaseModel.schema.
    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-09.client-handshake")
    )
    launch_handle: PublicHandle
    accepted_deployment: DeploymentRevisionRef
    protocol_capabilities: CapabilitySet
    client_build_slot: _AuthoringKey


class RealtimeCommand(KernelModel):
    """One idempotent command a participant submits over the realtime channel."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-09.realtime-command")
    )
    command_id: CommandId
    channel_key: _AuthoringKey
    intent_schema: SchemaRef
    payload_digest: Digest
    idempotency_key: IdempotencyKey
    submitted_at: UtcInstant


class UploadTicket(KernelModel):
    """A capability to upload one artifact: media type, size cap, and expiry."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-09.upload-ticket")
    )
    upload_id: UploadId
    grant_handle: PublicHandle
    media_type: Annotated[
        str,
        Field(
            pattern=r"^[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*$",
            max_length=127,
        ),
    ]
    max_size_bytes: PositiveSafeInteger
    expires_at: UtcInstant


class TransportAck(KernelModel):
    """The transport acknowledgement of one command: how far it has progressed."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-09.transport-ack")
    )
    command_id: CommandId
    ack_kind: Literal["parsed", "queued", "accepted"]
    stream_position: StreamPosition | None = None

    @model_validator(mode="after")
    def _accepted_names_position(self) -> TransportAck:
        if self.ack_kind == "accepted" and self.stream_position is None:
            raise ValueError("an accepted ack must carry a stream position")
        return self


class InputScheme(KernelModel):
    """One seat's key bindings: how key names map to env action values."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-09.input-scheme")
    )
    seat_key: SeatKey
    mode: Literal["pressed_keys", "single_keystroke"]
    bindings: Annotated[
        dict[_KeyName, _EnvActionValue], Field(min_length=1, max_length=128)
    ]
    on_no_input: _NoInputFill
    input_delay: NonNegativeSafeInteger | None = None


class SeatDelivery(KernelModel):
    """One payload the server delivers to a seat, pinned to its payload schema."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-09.seat-delivery")
    )
    seat_key: SeatKey
    delivery_kind: Literal["render_packet", "message"]
    payload_schema: SchemaRef
    payload_digest: Digest
    stream_position: StreamPosition


class BridgeMessage(KernelModel):
    """One page-JavaScript bridge op over the participant response and env state."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-09.bridge-message")
    )
    op: Literal[
        "response.set", "response.get", "state.set", "state.get", "advance"
    ]
    key: _AuthoringKey | None = None
    value: Any = None

    @model_validator(mode="after")
    def _op_shape(self) -> BridgeMessage:
        if self.op in ("response.set", "state.set"):
            if self.key is None or self.value is None:
                raise ValueError("a set op must carry a key and a value")
        elif self.op in ("response.get", "state.get"):
            if self.key is None or self.value is not None:
                raise ValueError("a get op must carry a key and no value")
        elif self.key is not None or self.value is not None:
            raise ValueError("an advance op carries no key and no value")
        return self

    @model_validator(mode="after")
    def _key_is_not_reserved(self) -> BridgeMessage:
        if self.key in _RESERVED_BRIDGE_KEYS:
            raise ValueError("a bridge message must not name a reserved identity key")
        return self


class MonitoringPolicyRef(KernelModel):
    """An inert pin to API-06's server-authoritative policy; never recomputed here."""

    name: Literal["mug.api-06.interaction"]
    version: Literal[0]
    digest: Digest


class QualityMeasurement(KernelModel):
    """One typed client quality sample: the metric and its observed duration."""

    metric: Literal["rtt", "hidden"]
    observed: Duration


class MonitoringMeasurement(KernelModel):
    """A batch of client quality samples the server evaluates against the policy."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-09.monitoring-measurement")
    )
    policy: MonitoringPolicyRef
    seat_key: SeatKey
    measurements: Annotated[
        list[QualityMeasurement], Field(min_length=1, max_length=16)
    ]
    measured_at: UtcInstant

    @model_validator(mode="after")
    def _metrics_are_unique(self) -> MonitoringMeasurement:
        metrics = [sample.metric for sample in self.measurements]
        if len(metrics) != len(set(metrics)):
            raise ValueError("a measurement batch must not repeat a metric")
        return self


class GateAnchor(KernelModel):
    """The interaction or flow node a gate op blocks or unblocks."""

    anchor_kind: Literal["interaction", "flow_node"]
    anchor_key: _AuthoringKey


class GateOp(KernelModel):
    """One readiness gate op that blocks or unblocks advancing or joining."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-09.gate-op")
    )
    gate_id: Annotated[
        str,
        Field(
            pattern=(
                r"^gate_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}"
                r"-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
            )
        ),
    ]
    target: Literal["advance", "join"]
    action: Literal["block", "unblock"]
    anchor: GateAnchor
    requested_at: UtcInstant

    @model_validator(mode="after")
    def _join_anchors_interaction(self) -> GateOp:
        if self.target == "join" and self.anchor.anchor_kind != "interaction":
            raise ValueError("a join gate op must anchor an interaction")
        return self
