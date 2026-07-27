"""Frozen API-09 records for the authenticated browser P2P edge.

These records expose only scoped public handles. The server derives every
principal, actor, membership, and lease binding from the authenticated
connection. SDP, ICE, and capture payloads stay opaque and bounded on the wire.
"""

from __future__ import annotations

import hashlib
from typing import Annotated, Any, ClassVar, Literal, cast

from pydantic import (
    Field,
    SerializerFunctionWrapHandler,
    model_serializer,
    model_validator,
)

from mug.client.types import client_schema
from mug.kernel import Digest, PublicHandle, SchemaRef, UtcInstant
from mug.kernel._base import KernelModel
from mug.kernel.ids import RequestId
from mug.kernel.refs import (
    NonNegativeSafeInteger,
    PositiveSafeInteger,
)

_SignalKind = Literal["offer", "answer", "candidate", "end_of_candidates"]
_SignalPayload = Annotated[str, Field(min_length=1, max_length=65_536)]
_CapturePayload = Annotated[str, Field(min_length=1, max_length=1_048_576)]
_IceEndpoint = Annotated[
    str,
    Field(
        pattern=r"^/[A-Za-z0-9](?:[A-Za-z0-9._~!$&'()*+,;=:@/-]*[A-Za-z0-9/_~-])?$",
        max_length=256,
    ),
]
_ValidationTimeoutMs = Annotated[int, Field(ge=1_000, le=60_000)]


def _p2p_schema_ref(name: str) -> SchemaRef:
    digest = Digest(algorithm="sha-256", hex=client_schema().bundle_digest)
    return SchemaRef(name=name, version=0, digest=digest)


class _SchemaBoundModel(KernelModel):
    """Require the exact frozen API-09 schema reference on an inbound record."""

    _expected_schema_name: ClassVar[str]
    # The contract field is named ``schema`` and intentionally shadows BaseModel.
    schema: SchemaRef  # pyright: ignore[reportIncompatibleMethodOverride]

    @model_validator(mode="after")
    def _schema_is_exact(self) -> _SchemaBoundModel:
        expected = _p2p_schema_ref(self._expected_schema_name)
        if self.schema != expected:
            raise ValueError(
                f"schema must identify frozen {self._expected_schema_name} version 0"
            )
        return self


class _OmitNoneModel(_SchemaBoundModel):
    @model_serializer(mode="wrap")
    def _serialize_without_none(
        self, handler: SerializerFunctionWrapHandler
    ) -> dict[str, Any]:
        value = cast(dict[str, Any], handler(self))
        return {key: item for key, item in value.items() if item is not None}


class _SignalFields(_OmitNoneModel):
    room_handle: PublicHandle
    negotiation_generation: PositiveSafeInteger
    signal_kind: _SignalKind
    payload_json: _SignalPayload | None = None

    @model_validator(mode="before")
    @classmethod
    def _payload_is_not_null(cls, value: object) -> object:
        result: object = value
        if isinstance(value, dict):
            fields = cast(dict[str, object], value)
            if "payload_json" in fields and fields["payload_json"] is None:
                raise ValueError("payload_json must be omitted, not null")
        return result

    @model_validator(mode="after")
    def _payload_matches_kind(self) -> _SignalFields:
        if self.signal_kind == "end_of_candidates":
            if self.payload_json is not None:
                raise ValueError("end_of_candidates must omit payload_json")
            return self
        if self.payload_json is None:
            raise ValueError(f"{self.signal_kind} requires payload_json")
        if self.signal_kind == "candidate" and len(self.payload_json) > 4_096:
            raise ValueError("candidate payload_json exceeds 4096 characters")
        return self


class P2PPeer(KernelModel):
    """Describe one remote peer and the local browser's assigned link role."""

    peer_handle: PublicHandle
    role: Literal["offerer", "answerer"]


class P2PDataChannel(KernelModel):
    """Pin the unreliable ordered-independent DataChannel configuration."""

    label: Literal["mug-mesh-data"] = "mug-mesh-data"
    ordered: Literal[False] = False
    max_retransmits: Literal[0] = 0


class P2PMeshBootstrap(_SchemaBoundModel):
    """Give one authenticated browser its scoped full-mesh bootstrap view."""

    _expected_schema_name = "mug.api-09.p2p-mesh-bootstrap"
    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _p2p_schema_ref("mug.api-09.p2p-mesh-bootstrap")
    )
    room_handle: PublicHandle
    local_peer_handle: PublicHandle
    capture_owner_handle: PublicHandle
    negotiation_generation: PositiveSafeInteger
    peers: Annotated[tuple[P2PPeer, ...], Field(min_length=1, max_length=15)]
    data_channel: P2PDataChannel = Field(default_factory=P2PDataChannel)
    validation_timeout_ms: _ValidationTimeoutMs
    ice_grant_handle: PublicHandle
    ice_endpoint: _IceEndpoint
    ice_expires_at: UtcInstant

    @model_validator(mode="after")
    def _handles_are_scoped_and_distinct(self) -> P2PMeshBootstrap:
        peers = [peer.peer_handle for peer in self.peers]
        if len(peers) != len(set(peers)):
            raise ValueError("bootstrap peer handles must be unique")
        if self.local_peer_handle in peers:
            raise ValueError("local_peer_handle must not appear in peers")
        participants = {self.local_peer_handle, *peers}
        if self.capture_owner_handle not in participants:
            raise ValueError("capture_owner_handle must name one mesh participant")
        reserved = {self.room_handle, self.ice_grant_handle}
        if len(reserved) != 2 or reserved.intersection(participants):
            raise ValueError("room and ICE grant handles must be separately scoped")
        return self


class P2PIceGrantRequest(_SchemaBoundModel):
    """Redeem one scoped ICE grant without exposing its deployment secret."""

    _expected_schema_name = "mug.api-09.p2p-ice-grant-request"
    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _p2p_schema_ref("mug.api-09.p2p-ice-grant-request")
    )
    ice_grant_handle: PublicHandle


class P2PSignal(_SignalFields):
    """Carry one bounded opaque SDP or ICE signal to a server-resolved peer."""

    _expected_schema_name = "mug.api-09.p2p-signal"
    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _p2p_schema_ref("mug.api-09.p2p-signal")
    )
    request_id: RequestId
    target_peer_handle: PublicHandle


class P2PSignalDelivery(_SignalFields):
    """Deliver an opaque signal with the source handle stamped by the server."""

    _expected_schema_name = "mug.api-09.p2p-signal-delivery"
    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _p2p_schema_ref("mug.api-09.p2p-signal-delivery")
    )
    source_peer_handle: PublicHandle


class P2PSignalAck(_OmitNoneModel):
    """Acknowledge signal routing without claiming a durable command receipt."""

    _expected_schema_name = "mug.api-09.p2p-signal-ack"
    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _p2p_schema_ref("mug.api-09.p2p-signal-ack")
    )
    request_id: RequestId
    status: Literal["queued", "rejected"]
    error_code: (
        Literal[
            "invalid_signal",
            "lease_expired",
            "not_a_member",
            "payload_too_large",
            "rate_limited",
            "room_closed",
            "stale_generation",
            "unknown_target",
        ]
        | None
    ) = None

    @model_validator(mode="before")
    @classmethod
    def _error_is_not_null(cls, value: object) -> object:
        result: object = value
        if isinstance(value, dict):
            fields = cast(dict[str, object], value)
            if "error_code" in fields and fields["error_code"] is None:
                raise ValueError("error_code must be omitted, not null")
        return result

    @model_validator(mode="after")
    def _error_matches_ack(self) -> P2PSignalAck:
        if self.status == "queued" and self.error_code is not None:
            raise ValueError("a queued signal ack must omit error_code")
        if self.status == "rejected" and self.error_code is None:
            raise ValueError("a rejected signal ack requires error_code")
        return self


class P2PPeerReady(_SchemaBoundModel):
    """Report the remote links that passed bidirectional application validation."""

    _expected_schema_name = "mug.api-09.p2p-peer-ready"
    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _p2p_schema_ref("mug.api-09.p2p-peer-ready")
    )
    room_handle: PublicHandle
    negotiation_generation: PositiveSafeInteger
    validated_peer_handles: Annotated[
        tuple[PublicHandle, ...], Field(min_length=1, max_length=15)
    ]

    @model_validator(mode="after")
    def _validated_peers_are_unique(self) -> P2PPeerReady:
        if len(self.validated_peer_handles) != len(set(self.validated_peer_handles)):
            raise ValueError("validated_peer_handles must be unique")
        return self


class P2PMeshStart(_SchemaBoundModel):
    """Release one validated mesh across the server-authoritative start barrier."""

    _expected_schema_name = "mug.api-09.p2p-mesh-start"
    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _p2p_schema_ref("mug.api-09.p2p-mesh-start")
    )
    room_handle: PublicHandle
    negotiation_generation: PositiveSafeInteger
    seed: NonNegativeSafeInteger
    start_sequence: PositiveSafeInteger
    capture_owner_handle: PublicHandle


class P2PMeshAbort(_SchemaBoundModel):
    """Close one mesh attempt with a safe reason and an explicit disposition."""

    _expected_schema_name = "mug.api-09.p2p-mesh-abort"
    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _p2p_schema_ref("mug.api-09.p2p-mesh-abort")
    )
    room_handle: PublicHandle
    negotiation_generation: PositiveSafeInteger
    reason: Literal[
        "capture_conflict",
        "capture_timeout",
        "negotiation_timeout",
        "peer_disconnected",
        "room_replaced",
        "server_unavailable",
        "stale_connection",
        "validation_failed",
    ]
    disposition: Literal[
        "repool",
        "resume_flow",
        "terminal",
    ]


class P2PPeerComplete(_SchemaBoundModel):
    """Report one peer's final trajectory digest and frame count."""

    _expected_schema_name = "mug.api-09.p2p-peer-complete"
    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _p2p_schema_ref("mug.api-09.p2p-peer-complete")
    )
    room_handle: PublicHandle
    negotiation_generation: PositiveSafeInteger
    trajectory_digest: Digest
    frame_count: NonNegativeSafeInteger


class P2PCaptureSubmission(_SchemaBoundModel):
    """Submit the capture owner's bounded trajectory payload and integrity pins."""

    _expected_schema_name = "mug.api-09.p2p-capture-submission"
    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _p2p_schema_ref("mug.api-09.p2p-capture-submission")
    )
    room_handle: PublicHandle
    negotiation_generation: PositiveSafeInteger
    trajectory_digest: Digest
    frame_count: NonNegativeSafeInteger
    payload_json: _CapturePayload
    payload_digest: Digest

    @model_validator(mode="after")
    def _payload_digest_matches(self) -> P2PCaptureSubmission:
        digest = hashlib.sha256(self.payload_json.encode("utf-8")).hexdigest()
        if digest != self.payload_digest.hex:
            raise ValueError("payload_digest does not match payload_json UTF-8 bytes")
        return self


class P2PMeshFinish(_SchemaBoundModel):
    """Confirm the reconciled mesh capture with an opaque durable receipt handle."""

    _expected_schema_name = "mug.api-09.p2p-mesh-finish"
    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _p2p_schema_ref("mug.api-09.p2p-mesh-finish")
    )
    room_handle: PublicHandle
    negotiation_generation: PositiveSafeInteger
    trajectory_digest: Digest
    frame_count: NonNegativeSafeInteger
    capture_receipt: PublicHandle
