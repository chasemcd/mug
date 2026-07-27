"""Translate between the API-09 P2P wire and the live room coordinator.

The coordinator owns authority and lifetime; it never parses or serializes a
frame. This module is that boundary, and only that boundary. It parses one
already-decoded browser frame into a coordinator call, and it serializes one
room effect into the frame the browser reads. It holds no socket, so a test
drives the whole wire path with plain dictionaries.

Every outbound frame is built from a frozen API-09 model, so a value the server
sends is a value the contract accepts. Every refusal becomes a safe code: the
browser learns that its signal was rejected and why, and it learns nothing about
a principal, an actor, a membership, a lease, or a secret.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from mug.client.p2p import (
    P2PCaptureSubmission,
    P2PMeshAbort,
    P2PMeshBootstrap,
    P2PMeshFinish,
    P2PMeshStart,
    P2PPeer,
    P2PPeerComplete,
    P2PPeerReady,
    P2PSignal,
    P2PSignalAck,
    P2PSignalDelivery,
)
from mug.game.p2p_room import P2PRoomError
from mug.game.p2p_room_types import (
    MeshAbort,
    MeshStart,
    RoomEffect,
    SignalDelivery,
)
from mug.participant_p2p import P2PConnection, P2PCoordinator
from mug.participant_p2p_types import P2PEdgeError, RoomAssignment

# One safe ack code for each refusal the room and the edge can raise. A code the
# map does not name becomes ``invalid_signal``, so a new failure never leaks a
# message the browser must not read.
_ACK_CODES: Mapping[str, str] = {
    "auth.forbidden": "not_a_member",
    "auth.unauthenticated": "not_a_member",
    "command.idempotency_conflict": "invalid_signal",
    "command.state_conflict": "room_closed",
    "lease.expired": "lease_expired",
    "lease.stale_generation": "stale_generation",
    "p2p.unknown_target": "unknown_target",
    "quota.rate_limited": "rate_limited",
    "runtime.backpressure": "payload_too_large",
    "schema.validation_failed": "invalid_signal",
}


class P2PFrameError(ValueError):
    """A browser frame that the edge cannot parse into a coordinator call."""


def bootstrap_frame(assignment: RoomAssignment) -> dict[str, Any]:
    """Build the one bootstrap frame that opens a browser's room."""
    bootstrap = P2PMeshBootstrap(
        room_handle=assignment.room_handle,
        local_peer_handle=assignment.local_peer_handle,
        capture_owner_handle=assignment.capture_owner_handle,
        negotiation_generation=assignment.negotiation_generation,
        peers=tuple(
            P2PPeer(peer_handle=peer.peer_handle, role=peer.role)
            for peer in assignment.peers
        ),
        validation_timeout_ms=assignment.validation_timeout_ms,
        ice_grant_handle=assignment.ice_grant.handle,
        ice_endpoint=assignment.ice_endpoint,
        ice_expires_at=assignment.ice_grant.expires_at,
    )
    return {"type": "p2p_bootstrap", "bootstrap": bootstrap.model_dump(mode="json")}


def effect_frame(effect: RoomEffect) -> dict[str, Any]:
    """Serialize one room effect into the API-09 frame the browser reads."""
    if isinstance(effect, SignalDelivery):
        # An end-of-candidates signal omits the payload; the contract refuses a
        # null one, so the field is absent rather than present and empty.
        fields: dict[str, Any] = {
            "room_handle": effect.room_handle,
            "source_peer_handle": effect.source_peer_handle,
            "negotiation_generation": effect.negotiation_generation,
            "signal_kind": effect.signal_kind,
        }
        if effect.payload_json is not None:
            fields["payload_json"] = effect.payload_json
        delivery = P2PSignalDelivery.model_validate(fields)
        return {
            "type": "p2p_signal_delivery",
            "signal": delivery.model_dump(mode="json"),
        }
    if isinstance(effect, MeshStart):
        start = P2PMeshStart(
            room_handle=effect.room_handle,
            negotiation_generation=effect.negotiation_generation,
            seed=effect.seed,
            start_sequence=effect.start_sequence,
            capture_owner_handle=effect.capture_owner_handle,
        )
        return {"type": "p2p_mesh_start", "start": start.model_dump(mode="json")}
    if isinstance(effect, MeshAbort):
        abort = P2PMeshAbort(
            room_handle=effect.room_handle,
            negotiation_generation=effect.negotiation_generation,
            reason=effect.reason,
            disposition=effect.disposition,
        )
        return {"type": "p2p_mesh_abort", "abort": abort.model_dump(mode="json")}
    finish = P2PMeshFinish(
        room_handle=effect.room_handle,
        negotiation_generation=effect.negotiation_generation,
        trajectory_digest=effect.trajectory_digest,
        frame_count=effect.frame_count,
        capture_receipt=effect.capture_receipt,
    )
    return {"type": "p2p_mesh_finish", "finish": finish.model_dump(mode="json")}


def ack_frame(request_id: str, code: str | None) -> dict[str, Any]:
    """Build the queued or rejected routing acknowledgement for one signal."""
    ack = (
        P2PSignalAck(request_id=request_id, status="queued")
        if code is None
        else P2PSignalAck(
            request_id=request_id,
            status="rejected",
            error_code=_ACK_CODES.get(code, "invalid_signal"),  # pyright: ignore[reportArgumentType]
        )
    )
    return {"type": "p2p_signal_ack", "ack": ack.model_dump(mode="json")}


def is_p2p_frame(message: Mapping[str, Any]) -> bool:
    """Report whether a decoded browser message claims a P2P frame type."""
    kind = message.get("type")
    return isinstance(kind, str) and kind.startswith("p2p_")


def _body(message: Mapping[str, Any], field: str) -> dict[str, Any]:
    """Read one required object field of a browser frame."""
    value = message.get(field)
    if not isinstance(value, Mapping) or set(message) != {"type", field}:
        raise P2PFrameError(f"a P2P frame needs exactly a type and {field!r}")
    return dict(value)  # pyright: ignore[reportUnknownArgumentType]


async def apply_frame(
    coordinator: P2PCoordinator,
    connection: P2PConnection,
    message: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Route one browser frame to the coordinator and return any direct reply.

    A signal returns its routing acknowledgement, which is not a durable receipt.
    Every other frame returns ``None``: its effects reach the browsers through
    the coordinator's own delivery, not as a reply to the sender.
    """
    kind = message.get("type")
    if kind == "p2p_signal":
        return await _apply_signal(coordinator, connection, message)
    if kind == "p2p_peer_ready":
        ready = P2PPeerReady.model_validate(_body(message, "ready"))
        await coordinator.mark_ready(
            connection,
            ready.room_handle,
            ready.negotiation_generation,
            tuple(ready.validated_peer_handles),
        )
        return None
    if kind == "p2p_peer_complete":
        complete = P2PPeerComplete.model_validate(_body(message, "complete"))
        await coordinator.report_complete(
            connection,
            complete.room_handle,
            complete.negotiation_generation,
            complete.trajectory_digest,
            complete.frame_count,
        )
        return None
    if kind == "p2p_capture_submission":
        submission = P2PCaptureSubmission.model_validate(_body(message, "submission"))
        await coordinator.submit_capture(
            connection,
            room_handle=submission.room_handle,
            generation=submission.negotiation_generation,
            trajectory_digest=submission.trajectory_digest,
            frame_count=submission.frame_count,
            payload_json=submission.payload_json,
            payload_digest=submission.payload_digest,
        )
        return None
    raise P2PFrameError(f"unknown P2P frame type: {kind!r}")


async def _apply_signal(
    coordinator: P2PCoordinator,
    connection: P2PConnection,
    message: Mapping[str, Any],
) -> dict[str, Any]:
    """Relay one signal and answer with its routing acknowledgement."""
    try:
        signal = P2PSignal.model_validate(_body(message, "signal"))
    except (P2PFrameError, ValueError) as error:
        raise P2PFrameError("a malformed P2P signal cannot be acknowledged") from error
    try:
        await coordinator.relay_signal(
            connection,
            room_handle=signal.room_handle,
            request_id=signal.request_id,
            target_peer_handle=signal.target_peer_handle,
            negotiation_generation=signal.negotiation_generation,
            signal_kind=signal.signal_kind,
            payload_json=signal.payload_json,
        )
    except (P2PRoomError, P2PEdgeError) as refusal:
        return ack_frame(signal.request_id, refusal.code)
    return ack_frame(signal.request_id, None)


__all__ = [
    "P2PFrameError",
    "ack_frame",
    "apply_frame",
    "bootstrap_frame",
    "effect_frame",
    "is_p2p_frame",
]
