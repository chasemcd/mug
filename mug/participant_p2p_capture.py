"""Persist one verified P2P capture and record the episode it reports.

The browser peers agree on a trajectory and one of them submits it. Two durable
things follow. The bytes are staged as an artifact under an opaque receipt, which
is what the room hands back to every peer. The trajectory is also read into the
API-07 records the platform holds for any other episode, so a browser mesh run
exports exactly as a server-hosted one does.

The server is the writer of the record. The browser reports public handles, and
this module binds them back to the interaction, the episode, the actors, and the
frozen membership it holds itself. So a participant never names an identity.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timezone
from typing import Any, cast

from mug.game.browser_mesh import MeshCaptureBinding, mesh_episode_summary
from mug.game.capture import capture_episode
from mug.gateway import Gateway
from mug.kernel import DataHandlingRef, Digest, PrincipalRef, WireCommandEnvelope
from mug.replay.bundle import stage_artifact
from mug.storage import ArtifactStore, Store

_INSTANT = "%Y-%m-%dT%H:%M:%S.%fZ"
_RESEARCH = DataHandlingRef(privacy_labels=["research"])
_ENVELOPE_DIGEST = Digest(algorithm="sha-256", hex="0" * 64)


@dataclass(frozen=True)
class P2PCaptureWrite:
    """Bind persisted payload bytes to one verified live room claim."""

    room_handle: str
    interaction_id: str
    negotiation_generation: int
    payload_digest: Digest
    payload_json: str


async def persist_p2p_capture(
    gateway: Gateway, store: Store, write: P2PCaptureWrite
) -> str:
    """Persist verified bytes and issue one handle-keyed capture receipt."""
    artifact = await stage_artifact(
        cast("ArtifactStore", store),
        data=write.payload_json.encode("utf-8"),
        media_type="application/json",
        new_artifact_id=lambda: gateway.new_id("artifact"),
        new_upload_id=lambda: gateway.new_id("upload"),
        now=lambda: _now(gateway),
        data_handling=_RESEARCH,
    )
    receipt = gateway.new_handle()
    await store.issue_token(
        command_id=gateway.new_id("command"),
        idempotency_key=_fresh_idempotency_key(gateway),
        handle=receipt,
        new_state={
            "kind": "p2p_capture",
            "room_handle": write.room_handle,
            "interaction_id": write.interaction_id,
            "negotiation_generation": write.negotiation_generation,
            "payload_digest": write.payload_digest.model_dump(mode="json"),
            "artifact": artifact.model_dump(mode="json"),
        },
    )
    return receipt


@dataclass(frozen=True)
class P2PEpisodeWrite:
    """Bind one reported trajectory to the identities only the server holds."""

    interaction_id: str
    episode_id: str
    channel_key: str
    membership_generation: int
    mesh_membership_digest: Digest
    actor_by_handle: Mapping[str, str]
    seat_by_handle: Mapping[str, str]
    reference_handle: str
    reference_visit_id: str
    reference_principal: PrincipalRef
    payload_json: str


async def record_p2p_episode(
    gateway: Gateway, store: Store, write: P2PEpisodeWrite
) -> str:
    """Commit the reported mesh trajectory as one peer-authority episode.

    The mesh runs one agreed trajectory, so the group's run is captured once,
    from the designated reference peer. Every peer's own claim already had to
    match that trajectory before the room accepted it, so the single record
    stands for the whole mesh. The returned value is the episode's stream.
    """
    summary = mesh_episode_summary(
        write.payload_json,
        binding=MeshCaptureBinding(
            interaction_id=write.interaction_id,
            episode_id=write.episode_id,
            channel_key=write.channel_key,
            actor_by_handle=write.actor_by_handle,
            seat_by_handle=write.seat_by_handle,
            reference_handle=write.reference_handle,
            mesh_membership_digest=write.mesh_membership_digest,
            membership_generation=write.membership_generation,
            recorded_at=_now(gateway),
        ),
    )
    context = gateway.mint(
        _envelope(
            "episode.capture",
            write.episode_id,
            {"episode_id": write.episode_id},
            _fresh_idempotency_key(gateway),
        ),
        principal=write.reference_principal,
        data_handling=_RESEARCH,
    )
    await capture_episode(
        summary, visit_id=write.reference_visit_id, context=context, store=store
    )
    return context.stream_id


def _envelope(
    command_name: str, target_id: str, data: dict[str, Any], idem: str
) -> WireCommandEnvelope:
    """Build the wire envelope for one server-side capture command."""
    schema = {
        "name": "mug.command-envelope",
        "version": 0,
        "digest": _ENVELOPE_DIGEST.model_dump(mode="json"),
    }
    return WireCommandEnvelope.model_validate(
        {
            "schema": schema,
            "protocol_version": "0.1.0",
            "command": {"name": command_name, "version": 0},
            "request_id": "request_019b6000-0000-7000-8000-000000000001",
            "idempotency_key": idem,
            "target": {"id": target_id},
            "payload": {
                "schema": {
                    "name": "mug.edge.payload",
                    "version": 0,
                    "digest": _ENVELOPE_DIGEST.model_dump(mode="json"),
                },
                "data": data,
            },
        }
    )


def _fresh_idempotency_key(gateway: Gateway) -> str:
    body = gateway.new_id("request").split("_", 1)[1].replace("-", "")
    return "idem_" + body[:21] + "A"


def _now(gateway: Gateway) -> str:
    value = gateway.clock()
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime(_INSTANT)


__all__ = [
    "P2PCaptureWrite",
    "P2PEpisodeWrite",
    "persist_p2p_capture",
    "record_p2p_episode",
]
