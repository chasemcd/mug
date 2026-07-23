"""Assemble a peer-to-peer replay bundle from the mesh evidence (API-16).

A p2p replay is not reproducible from a single canonical stream: it happened
across a mesh of peers, each running its own deterministic replica, and its
canonical trajectory is the agreement the peers reached, not one authority's log.
So a p2p replay bundle closes over the *evidence* of that agreement -- the mesh
membership the peers froze, the per-frame finality the rollback engine settled,
the episode boundary the minimum-end barrier fixed, the bot authority and decision
results a p2p bot seat produced, and the decision tape of the recorded actions --
and pins each as a content-addressed artifact.

This module assembles that bundle. It takes the records the mesh produced (the
``PeerEngine`` emits the frame finalities and the episode boundary; the formation
service froze the membership; the agent runtime produced the bot authority and the
decision results), persists each evidence group as an artifact through the object
store, and binds them into a ``P2PReplayEvidence`` inside a p2p ``ReplayManifest``.
It also derives the one ``P2PFinalityOutcome`` the whole episode reached from the
per-frame finalities: every frame verified is a verified episode, a dispute is a
disputed episode, and anything short of a complete verified set is confirmed-only
or partial.

The manifest enforces the p2p invariants (``mug.replay.types``): the frozen peer
set stays canonically sorted, the mesh digest binds the mesh artifact, and every
evidence artifact closes over the manifest's artifact set. This assembler builds
the records so those invariants hold: the mesh membership digest is the digest of
the persisted membership artifact, and every binding names an artifact that is also
in the manifest's artifact refs.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import cast

from mug.game.determinism import state_hash_chain
from mug.game.types import EpisodeBoundary, P2PFrameFinality
from mug.interactions.types import P2PMeshMembership
from mug.kernel import ArtifactRef, DataHandlingRef, SchemaRef, compute_digest
from mug.kernel._base import KernelModel
from mug.replay.bundle import ReplayBundle, json_bytes, stage_artifact
from mug.replay.types import (
    CapabilityLevels,
    ConfirmedOnlyFinalityOutcome,
    DecisionTape,
    DeterminismDeclaration,
    DisputedFinalityOutcome,
    P2PFinalityOutcome,
    P2PReplayEvidence,
    PartialFinalityOutcome,
    ReplayBundleValidation,
    ReplayManifest,
    SchemaArtifactBinding,
    VerifiedFinalityOutcome,
    replay_schema,
)
from mug.scheduling.types import DecisionResult, P2PBotAuthority
from mug.storage import ArtifactStore

_JSON = "application/json"


async def build_p2p_replay_bundle(
    *,
    artifacts: ArtifactStore,
    interaction_id: str,
    mesh_membership: P2PMeshMembership,
    frame_finalities: Sequence[P2PFrameFinality],
    episode_boundaries: Sequence[EpisodeBoundary],
    decision_tape: DecisionTape,
    bot_authorities: Sequence[P2PBotAuthority] = (),
    decision_results: Sequence[DecisionResult] = (),
    new_artifact_id: Callable[[], str],
    new_upload_id: Callable[[], str],
    now: Callable[[], str],
    data_handling: DataHandlingRef,
    determinism: DeterminismDeclaration | None = None,
) -> ReplayBundle:
    """Assemble one p2p replay bundle from a mesh episode's evidence.

    Each evidence group -- the mesh membership, the per-frame finalities, the
    episode boundaries, the bot authorities, the decision results, and the decision
    tape -- is persisted as a content-addressed artifact and bound into a
    ``P2PReplayEvidence``. The mesh membership digest is the digest of its persisted
    artifact, so the manifest's mesh-binding invariant holds. The one episode
    finality outcome is derived from the per-frame finalities. ``determinism`` set
    turns on the deterministic capability; unset leaves a visual-only p2p bundle.

    A bot-less mesh passes no bot authorities or decision results; their artifacts
    hold an empty set, so the evidence is complete either way.
    """
    if not frame_finalities:
        raise ValueError("a p2p replay must carry at least one frame finality")

    refs: list[ArtifactRef] = []

    async def stage_json(data: bytes) -> ArtifactRef:
        ref = await stage_artifact(
            artifacts,
            data=data,
            media_type=_JSON,
            new_artifact_id=new_artifact_id,
            new_upload_id=new_upload_id,
            now=now,
            data_handling=data_handling,
        )
        refs.append(ref)
        return ref

    membership_ref = await stage_json(_dump_one(mesh_membership))
    finality_ref = await stage_json(_dump_many(frame_finalities))
    boundary_ref = await stage_json(_dump_many(episode_boundaries))
    authority_ref = await stage_json(_dump_many(bot_authorities))
    results_ref = await stage_json(_dump_many(decision_results))
    tape_ref = await stage_json(_dump_one(decision_tape))

    evidence = P2PReplayEvidence(
        mesh_membership_digest=membership_ref.digest,
        membership_generation=mesh_membership.membership_generation,
        frozen_peer_actor_ids=list(mesh_membership.peer_actor_ids),
        mesh_membership=SchemaArtifactBinding(
            schema=mesh_membership.schema, artifact=membership_ref
        ),
        frame_finality=SchemaArtifactBinding(
            schema=_schema_ref_of(P2PFrameFinality), artifact=finality_ref
        ),
        episode_boundaries=SchemaArtifactBinding(
            schema=_schema_ref_of(EpisodeBoundary), artifact=boundary_ref
        ),
        bot_authorities=SchemaArtifactBinding(
            schema=_schema_ref_of(P2PBotAuthority), artifact=authority_ref
        ),
        decision_results=SchemaArtifactBinding(
            schema=_schema_ref_of(DecisionResult), artifact=results_ref
        ),
        decision_tape=SchemaArtifactBinding(
            schema=decision_tape.schema, artifact=tape_ref
        ),
        finality_outcome=_finality_outcome(frame_finalities),
    )

    schema_bundle = await stage_artifact(
        artifacts,
        data=json_bytes(
            {"family": "mug.api-16", "bundle_digest": replay_schema().bundle_digest}
        ),
        media_type=_JSON,
        new_artifact_id=new_artifact_id,
        new_upload_id=new_upload_id,
        now=now,
        data_handling=data_handling,
    )
    refs.append(schema_bundle)

    integrity = compute_digest(
        {
            "interaction_id": interaction_id,
            "execution_mode": "p2p",
            "artifacts": sorted(ref.digest.hex for ref in refs),
            "schema_bundle": schema_bundle.digest.hex,
            "mesh_membership": membership_ref.digest.hex,
            "deterministic": determinism is not None,
        }
    )
    manifest = ReplayManifest(
        interaction_id=interaction_id,
        execution_mode="p2p",
        capability_levels=CapabilityLevels(
            visual=True, deterministic=determinism is not None
        ),
        reproduction_scope="canonical-only",
        determinism=determinism,
        p2p_replay_evidence=evidence,
        artifact_refs=refs,
        schema_bundle=schema_bundle,
        integrity_digest=integrity,
    )
    validation = ReplayBundleValidation(
        interaction_id=interaction_id,
        valid=True,
        external_calls_made=False,
        modified_artifact_ids=[],
        verification="deterministic" if determinism is not None else "visual-fallback",
    )
    event_count = (
        len(frame_finalities)
        + len(episode_boundaries)
        + len(bot_authorities)
        + len(decision_results)
    )
    return ReplayBundle(
        manifest=manifest,
        validation=validation,
        decision_tape=decision_tape,
        stream_artifacts={
            "mesh_membership": membership_ref,
            "frame_finality": finality_ref,
            "episode_boundaries": boundary_ref,
            "bot_authorities": authority_ref,
            "decision_results": results_ref,
        },
        event_count=event_count,
    )


def _finality_outcome(
    finalities: Sequence[P2PFrameFinality],
) -> P2PFinalityOutcome:
    """Derive the one episode finality outcome from its per-frame finalities.

    Every frame verified (a complete, unanimous peer hash set) is a verified
    episode, and its agreed state hashes chain into one digest. A disputed frame
    makes the episode disputed from the first disputed frame; the frames before it
    that were at least confirmed set the confirmed-through frame. An episode that is
    fully confirmed but not fully verified is confirmed-only, and anything short of
    that is partial.
    """
    ordered = sorted(finalities, key=lambda final: final.frame_number)
    disputed = [final for final in ordered if final.status == "disputed"]
    if disputed:
        first = disputed[0].frame_number
        prior = [
            final.frame_number
            for final in ordered
            if final.frame_number < first and final.status in ("confirmed", "verified")
        ]
        return DisputedFinalityOutcome(
            status="disputed",
            confirmed_through_frame=max(prior) if prior else None,
            first_disputed_frame=first,
        )

    if all(final.status == "verified" for final in ordered):
        last = ordered[-1].frame_number
        agreed = state_hash_chain(
            [
                final.agreed_state_hash.hex
                for final in ordered
                if final.agreed_state_hash is not None
            ]
        )
        return VerifiedFinalityOutcome(
            status="verified",
            confirmed_through_frame=last,
            verified_through_frame=last,
            agreed_state_hash_chain_digest=agreed,
        )

    confirmed = [
        final.frame_number
        for final in ordered
        if final.status in ("confirmed", "verified")
    ]
    if confirmed and len(confirmed) == len(ordered):
        return ConfirmedOnlyFinalityOutcome(
            status="confirmed-only", confirmed_through_frame=max(confirmed)
        )
    return PartialFinalityOutcome(
        status="partial",
        confirmed_through_frame=max(confirmed) if confirmed else None,
    )


def _schema_ref_of(model_cls: type[KernelModel]) -> SchemaRef:
    """Return a record type's own pinned schema reference without an instance.

    A possibly-empty evidence group (a bot-less mesh) has no record to read the
    schema from, so the reference comes from the type's ``schema`` default factory,
    the single source of truth every instance would use.
    """
    factory = model_cls.model_fields["schema"].default_factory
    if factory is None:  # pragma: no cover - every evidence record pins its schema
        raise TypeError(f"{model_cls.__name__} does not pin a schema reference")
    return cast("Callable[[], SchemaRef]", factory)()


def _dump_one(record: KernelModel) -> bytes:
    """Serialize one record to canonical, sorted-key JSON bytes."""
    return json_bytes(record.model_dump(mode="json", exclude_none=True))


def _dump_many(records: Sequence[KernelModel]) -> bytes:
    """Serialize a group of records to one canonical JSON array."""
    return json_bytes(
        [record.model_dump(mode="json", exclude_none=True) for record in records]
    )


__all__ = ["build_p2p_replay_bundle"]
