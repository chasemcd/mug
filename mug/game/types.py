"""The records that API-07 owns: environment, game, rendering, and execution.

You construct each object with its data alone; the ``schema`` envelope fills
itself from the frozen bundle. The frozen JSON-Schema corpus stays the authority,
and ``game_schema`` loads it for the conformance test.

This family owns six top-level records: the ``EnvFactory`` that names a study
environment factory, the ``ExecutionMode`` that fixes the run contract, the
normalized ``GameTransition`` that every runtime produces, the ``RenderPacket``
that ships surface commands to a seat, the ``EpisodeBoundary`` that closes an
episode, and the ``P2PFrameFinality`` that records mesh agreement. The family adds
no runtime.

Some rules are not expressible as plain field types and live here as validators:

- an ``EnvFactory`` in browser or p2p mode ships a source bundle; a p2p factory
  also ships the snapshot-restore and state-hash hooks;
- a p2p ``ExecutionMode`` fixes the per-replica writer, the deterministic
  snapshot contract, and the mesh contract; a non-p2p mode fixes the single
  writer and carries no mesh contract;
- a ``GameTransition`` names each applied decision and actor once, and a peer
  transition names the publisher of each recorded decision;
- a ``P2PFrameFinality`` keeps peers, actions, and hashes in canonical order and
  binds them to the frozen mesh, with completeness and agreement per status;
- a p2p ``EpisodeBoundary`` ends on the exclusive minimum of the peer end frames.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field, model_validator

from mug.kernel import (
    ArtifactRef,
    Digest,
    SchemaBundle,
    SchemaRef,
    UtcInstant,
    load_family_schema,
)
from mug.kernel._base import KernelModel
from mug.kernel.ids import ActorInstanceId, DecisionId, EpisodeId, InteractionId
from mug.kernel.refs import NonNegativeSafeInteger, PositiveSafeInteger

_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs/architecture/phase-0/api-07/schemas/v0/game.schema.json"
)


@lru_cache(maxsize=1)
def game_schema() -> SchemaBundle:
    """Return the loaded API-07 bundle (with the shared kernel registered)."""
    return load_family_schema(str(_SCHEMA_PATH))


def _schema_ref(name: str) -> SchemaRef:
    """Build the pinned schema reference for one object from the frozen bundle."""
    digest = Digest(algorithm="sha-256", hex=game_schema().bundle_digest)
    return SchemaRef(name=name, version=0, digest=digest)


_AuthoringKey = Annotated[
    str, Field(pattern=r"^[a-z][a-z0-9]*(?:[-_.][a-z0-9]+)*$", max_length=128)
]
_QualifiedName = Annotated[
    str,
    Field(
        pattern=(
            r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*"
            r":[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$"
        ),
        max_length=512,
    ),
]
_PinnedRequirement = Annotated[
    str,
    Field(
        pattern=r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?==[0-9][A-Za-z0-9._+]*$",
        max_length=128,
    ),
]
_ArgName = Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$", max_length=128)]

ExecutionModeName = Literal["server", "browser", "p2p"]
EnvHook = Literal["snapshot-restore", "state-hash", "per-seat-observation"]
_Number = int | float


class LiteralArgValue(KernelModel):
    """A literal factory argument: a JSON scalar passed straight through."""

    kind: Literal["literal"]
    value: bool | int | float | str | None


class TreatmentPlaceholder(KernelModel):
    """A factory argument bound at assignment time from a treatment key."""

    kind: Literal["treatment"]
    treatment_key: _AuthoringKey


FactoryArgValue = Annotated[
    LiteralArgValue | TreatmentPlaceholder, Field(discriminator="kind")
]
FactoryArgs = Annotated[dict[_ArgName, FactoryArgValue], Field(max_length=64)]


class EnvFactory(KernelModel):
    """A compiled record that names an env factory, never an env instance."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-07.env-factory")
    )
    channel_key: _AuthoringKey
    factory: _QualifiedName
    args: FactoryArgs | None = None
    mode: ExecutionModeName
    requires: Annotated[list[_PinnedRequirement], Field(max_length=256)]
    source_bundle: ArtifactRef | None = None
    hooks: Annotated[list[EnvHook], Field(max_length=3)] | None = None

    @model_validator(mode="after")
    def _mode_requires_bundle_and_hooks(self) -> EnvFactory:
        if self.mode in ("browser", "p2p") and self.source_bundle is None:
            raise ValueError("browser and p2p factories require a source bundle")
        if self.mode == "p2p":
            hooks = self.hooks or []
            if "snapshot-restore" not in hooks or "state-hash" not in hooks:
                raise ValueError(
                    "a p2p factory requires the snapshot-restore and state-hash hooks"
                )
        return self


class P2PSnapshotCoverage(KernelModel):
    """The complete snapshot coverage a p2p run captures every frame."""

    environment_state: Literal[True]
    platform_state: Literal[True]
    python_rng_state: Literal[True]
    numpy_rng_state: Literal[True]
    mug_js_rng_state: Literal[True]


class P2PBotDecisionProtocol(KernelModel):
    """The fixed protocol for the single designated peer that publishes bots."""

    authority: Literal["designated-peer"]
    selection: Literal["highest-eligible-peer-actor-id"]
    tenure: Literal["episode-fixed"]
    unilateral_switch: Literal["forbidden"]
    authority_change: Literal["new-fenced-authority-generation"]
    transport: Literal["peer-input-stream"]
    rollback: Literal["replay-recorded-decision-result"]


class P2PExecutionContract(KernelModel):
    """The fixed full-mesh execution contract for a p2p run."""

    topology: Literal["full-mesh"]
    input_exchange: Literal["every-frozen-peer"]
    confirmation: Literal["complete-peer-action-set"]
    verification: Literal["unanimous-peer-state-hashes"]
    episode_barrier: Literal["minimum-end-frame-exclusive"]
    human_input_delay: Literal["symmetric"]
    reconciliation: Literal["lower-peer-actor-id-defers"]
    snapshot_coverage: P2PSnapshotCoverage
    bot_decisions: P2PBotDecisionProtocol


class ExecutionMode(KernelModel):
    """The execution contract a channel runs under: mode, snapshot, and writer."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-07.execution-mode")
    )
    mode: ExecutionModeName
    snapshot_contract: Literal["none", "keyframe", "deterministic"]
    writer: Literal["single", "per-replica"]
    p2p_contract: P2PExecutionContract | None = None

    @model_validator(mode="after")
    def _mode_fixes_contract(self) -> ExecutionMode:
        if self.mode == "p2p":
            if self.p2p_contract is None:
                raise ValueError("a p2p mode requires the mesh execution contract")
            if self.writer != "per-replica":
                raise ValueError("a p2p mode uses the per-replica writer")
            if self.snapshot_contract != "deterministic":
                raise ValueError("a p2p mode uses the deterministic snapshot contract")
        else:
            if self.p2p_contract is not None:
                raise ValueError("only a p2p mode carries the mesh execution contract")
            if self.writer != "single":
                raise ValueError("a non-p2p mode uses the single writer")
        return self


class AppliedDecision(KernelModel):
    """One recorded external decision applied inside a transition."""

    decision_id: DecisionId
    actor_id: ActorInstanceId
    action_digest: Digest
    decision_result_digest: Digest
    decision_authority: Literal["server", "browser", "peer"]
    publisher_actor_id: ActorInstanceId | None = None
    publisher_generation: PositiveSafeInteger | None = None


class GameTransition(KernelModel):
    """The normalized transition every runtime produces: an action and a state."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-07.game-transition")
    )
    interaction_id: InteractionId
    channel_key: _AuthoringKey
    episode_id: EpisodeId
    frame_number: NonNegativeSafeInteger
    action_digest: Digest
    state_digest: Digest
    authority: Literal["server", "browser", "peer"]
    applied_decisions: Annotated[list[AppliedDecision], Field(max_length=64)]
    replica_actor_id: ActorInstanceId | None = None
    mesh_membership_digest: Digest | None = None
    membership_generation: PositiveSafeInteger | None = None
    recorded_at: UtcInstant

    @model_validator(mode="after")
    def _decisions_unique_and_publisher_matches_authority(self) -> GameTransition:
        decision_ids = [item.decision_id for item in self.applied_decisions]
        if len(decision_ids) != len(set(decision_ids)):
            raise ValueError("each applied decision must appear once")
        actor_ids = [item.actor_id for item in self.applied_decisions]
        if len(actor_ids) != len(set(actor_ids)):
            raise ValueError("each decision actor must appear once")
        if self.authority == "peer":
            for item in self.applied_decisions:
                if item.publisher_actor_id is None or item.publisher_generation is None:
                    raise ValueError(
                        "a peer transition names the publisher of each decision"
                    )
        elif any(
            item.publisher_actor_id is not None for item in self.applied_decisions
        ):
            raise ValueError("only a peer transition names a decision publisher")
        return self


class SurfaceCommand(KernelModel):
    """One drawing command in a render packet's surface command list."""

    op: Literal["rect", "circle", "ellipse", "line", "polygon", "arc", "text", "image"]
    id: Annotated[str, Field(max_length=128)] | None = None
    persistent: bool | None = None
    relative: bool | None = None
    depth: _Number | None = None
    tween_duration: NonNegativeSafeInteger | None = None
    x: _Number | None = None
    y: _Number | None = None
    w: _Number | None = None
    h: _Number | None = None
    x2: _Number | None = None
    y2: _Number | None = None
    radius: _Number | None = None
    rx: _Number | None = None
    ry: _Number | None = None
    points: Annotated[list[tuple[_Number, _Number]], Field(max_length=4096)] | None = (
        None
    )
    start_angle: _Number | None = None
    end_angle: _Number | None = None
    angle: _Number | None = None
    color: Annotated[str, Field(max_length=64)] | None = None
    alpha: Annotated[float, Field(ge=0, le=1)] | None = None
    fill: bool | None = None
    text: Annotated[str, Field(max_length=4096)] | None = None
    font_size: _Number | None = None
    image_name: Annotated[str, Field(max_length=128)] | None = None
    frame: NonNegativeSafeInteger | None = None
    extras: Annotated[dict[str, Any], Field(max_length=64)] | None = None


class RenderPacket(KernelModel):
    """The surface commands one seat renders for one frame."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-07.render-packet")
    )
    episode_id: EpisodeId
    seat_key: _AuthoringKey
    frame_number: NonNegativeSafeInteger
    render_digest: Digest
    keyframe: bool
    commands: Annotated[list[SurfaceCommand], Field(max_length=4096)]


class P2PPeerEndFrame(KernelModel):
    """The end frame one peer proposes for the episode barrier."""

    peer_actor_id: ActorInstanceId
    end_frame_exclusive: NonNegativeSafeInteger


class P2PEpisodeBarrier(KernelModel):
    """The mesh-bound barrier that ends a p2p episode on the minimum end frame."""

    mesh_membership_digest: Digest
    membership_generation: PositiveSafeInteger
    frozen_peer_actor_ids: Annotated[
        list[ActorInstanceId], Field(min_length=2, max_length=64)
    ]
    rule: Literal["minimum-end-frame-exclusive"]
    peer_end_frames: Annotated[
        list[P2PPeerEndFrame], Field(min_length=2, max_length=64)
    ]


class EpisodeBoundary(KernelModel):
    """The record that closes an episode by reset or terminal."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-07.episode-boundary")
    )
    episode_id: EpisodeId
    interaction_id: InteractionId
    kind: Literal["reset", "terminal"]
    end_frame_exclusive: NonNegativeSafeInteger
    authority: Literal["server", "browser", "peer"]
    state_hash: Digest
    p2p_barrier: P2PEpisodeBarrier | None = None

    @model_validator(mode="after")
    def _barrier_is_the_complete_exclusive_minimum(self) -> EpisodeBoundary:
        barrier = self.p2p_barrier
        if barrier is None:
            return self
        peers = barrier.frozen_peer_actor_ids
        end_ids = [item.peer_actor_id for item in barrier.peer_end_frames]
        if peers != sorted(peers) or end_ids != sorted(end_ids):
            raise ValueError("the barrier keeps peers in canonical order")
        if len(end_ids) != len(set(end_ids)) or set(end_ids) != set(peers):
            raise ValueError("the barrier names every frozen peer once")
        minimum = min(item.end_frame_exclusive for item in barrier.peer_end_frames)
        if self.end_frame_exclusive != minimum:
            raise ValueError("the episode ends on the exclusive minimum end frame")
        return self


class P2PPeerAction(KernelModel):
    """One peer's action digest for a frame."""

    peer_actor_id: ActorInstanceId
    action_digest: Digest


class P2PPeerHashEvidence(KernelModel):
    """One peer's state hash for a frame."""

    peer_actor_id: ActorInstanceId
    state_hash: Digest


class P2PFrameFinality(KernelModel):
    """The mesh-bound agreement record for one frame, keyed by finality status."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-07.p2p-frame-finality")
    )
    interaction_id: InteractionId
    channel_key: _AuthoringKey
    episode_id: EpisodeId
    frame_number: NonNegativeSafeInteger
    mesh_membership_digest: Digest
    membership_generation: PositiveSafeInteger
    status: Literal["speculative", "confirmed", "verified", "disputed"]
    frozen_peer_actor_ids: Annotated[
        list[ActorInstanceId], Field(min_length=2, max_length=64)
    ]
    actions: Annotated[list[P2PPeerAction], Field(max_length=64)]
    hash_evidence: Annotated[list[P2PPeerHashEvidence], Field(max_length=64)]
    agreed_state_hash: Digest | None = None
    recorded_at: UtcInstant

    @model_validator(mode="after")
    def _finality_is_ordered_complete_and_agreed(self) -> P2PFrameFinality:
        peers = self.frozen_peer_actor_ids
        peer_set = set(peers)
        if peers != sorted(peers):
            raise ValueError("frozen peers stay in canonical order")

        action_ids = [item.peer_actor_id for item in self.actions]
        if action_ids != sorted(action_ids):
            raise ValueError("peer actions stay in canonical order")
        if len(action_ids) != len(set(action_ids)) or not set(action_ids) <= peer_set:
            raise ValueError("peer actions name frozen peers once")

        hash_ids = [item.peer_actor_id for item in self.hash_evidence]
        if hash_ids != sorted(hash_ids):
            raise ValueError("peer hashes stay in canonical order")
        if len(hash_ids) != len(set(hash_ids)) or not set(hash_ids) <= peer_set:
            raise ValueError("peer hashes name frozen peers once")

        if self.status in ("confirmed", "verified", "disputed") and (
            set(action_ids) != peer_set
        ):
            raise ValueError("a confirmed frame carries the complete peer action set")
        if self.status in ("verified", "disputed") and set(hash_ids) != peer_set:
            raise ValueError("a verified frame carries the complete peer hash set")

        hash_values = [item.state_hash for item in self.hash_evidence]
        if self.status == "verified" and len(set(hash_values)) != 1:
            raise ValueError("a verified frame carries unanimous peer hashes")
        if (
            self.status == "verified"
            and hash_values
            and self.agreed_state_hash != hash_values[0]
        ):
            raise ValueError("the agreed hash matches the unanimous peer hash")
        if self.status == "disputed" and len(set(hash_values)) < 2:
            raise ValueError("a disputed frame carries at least two distinct hashes")
        return self
