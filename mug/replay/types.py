"""The records that API-16 owns: replay manifests, tapes, and validation.

You build each object with its data alone; the ``schema`` envelope fills itself
from the frozen bundle. The frozen JSON-Schema corpus stays the authority, and
``replay_schema`` loads it for the conformance test.

This family owns six top-level records: the ``ReplayManifest`` that pins one
replay bundle, the ``P2PReplayEvidence`` it carries in peer-to-peer mode, the
``DecisionTape`` of recorded model and bot actions, the two ``StateHashCheck``
outcomes, and the ``ReplayBundleValidation`` verdict. Each record references the
kernel (L0) types and adds no runtime.

Several invariants are not expressible in JSON Schema and live here as
validators:

- a replay must declare at least one capability (visual or deterministic);
- the presence of the determinism, p2p-evidence, and experienced-stream
  sections must agree with the capability, mode, and scope that require them;
- a corrected experienced frame must name a known canonical event;
- frozen peer ids stay canonically sorted, the mesh digest binds the mesh
  artifact, and every p2p evidence artifact closes over the manifest set;
- a verified finality outcome must not lead its confirmed frame;
- a decision tape must not repeat a decision or a bot-action coordinate, and a
  bot must not be its own authority;
- a deterministic state-hash result must agree with the hash comparison;
- a replay that made external calls is not valid, and the validity flag must
  agree with the observed replay effects.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from mug.kernel import (
    ArtifactRef,
    Digest,
    SchemaBundle,
    SchemaRef,
    StreamPosition,
    load_family_schema,
)
from mug.kernel._base import KernelModel
from mug.kernel.ids import (
    ActorInstanceId,
    ArtifactId,
    DecisionId,
    EpisodeId,
    EventId,
    InteractionId,
    ModelInvocationId,
    ToolCallId,
)
from mug.kernel.refs import NonNegativeSafeInteger, PositiveSafeInteger

_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs/architecture/phase-0/api-16/schemas/v0/replay.schema.json"
)


@lru_cache(maxsize=1)
def replay_schema() -> SchemaBundle:
    """Return the loaded API-16 bundle (with the shared kernel registered)."""
    return load_family_schema(str(_SCHEMA_PATH))


def _schema_ref(name: str) -> SchemaRef:
    """Build the pinned schema reference for one object from the frozen bundle."""
    digest = Digest(algorithm="sha-256", hex=replay_schema().bundle_digest)
    return SchemaRef(name=name, version=0, digest=digest)


ExecutionMode = Literal["server", "browser", "p2p"]
"""Where a replay runs: on the server, in the browser, or across a p2p mesh."""

ReproductionScope = Literal["canonical-only", "canonical-and-experienced"]
"""How much of a session a replay reproduces."""

DeliveryKind = Literal["delivered", "speculative", "corrected", "skipped"]
"""How one experienced frame reached the participant."""

_NullableFrame = NonNegativeSafeInteger | None


# --- Determinism declaration ---------------------------------------------


class CapabilityLevels(KernelModel):
    """Which replay capabilities a bundle offers."""

    visual: bool
    deterministic: bool


class EnvHooks(KernelModel):
    """The environment hooks a deterministic replay requires."""

    snapshot_restore: Literal[True]
    state_hash: Literal[True]


class SnapshotCoverage(KernelModel):
    """The closed, codec-neutral coverage a deterministic snapshot requires."""

    environment_state: Literal[True]
    platform_state: Literal[True]
    python_random_state: Literal[True]
    numpy_random_state: Literal[True]
    mug_javascript_rng_state: Literal[True]


class DeterminismDeclaration(KernelModel):
    """The declared basis for a byte-deterministic replay."""

    env_hooks: EnvHooks
    snapshot_coverage: SnapshotCoverage
    state_hash_chain_digest: Digest


# --- Experienced stream replay -------------------------------------------


class ExperiencedFrameLineageEntry(KernelModel):
    """One experienced frame joined to its canonical lineage."""

    stream_position: StreamPosition
    delivery_kind: DeliveryKind
    canonical_event_id: EventId | None = None
    supersedes_experienced_position: StreamPosition | None = None

    @model_validator(mode="after")
    def _corrected_names_lineage(self) -> ExperiencedFrameLineageEntry:
        if self.delivery_kind == "corrected" and (
            self.canonical_event_id is None
            or self.supersedes_experienced_position is None
        ):
            raise ValueError(
                "a corrected frame must name its canonical event and superseded"
                " position"
            )
        return self


class ExperiencedStreamReplay(KernelModel):
    """The experienced stream and its lineage back to the canonical events."""

    experienced_frames_schema: SchemaRef
    experienced_stream: ArtifactRef
    canonical_event_ids: Annotated[
        list[EventId], Field(min_length=1, max_length=4096)
    ]
    experienced_lineage: Annotated[
        list[ExperiencedFrameLineageEntry], Field(min_length=1, max_length=4096)
    ]


# --- P2P finality outcome ------------------------------------------------


class VerifiedFinalityOutcome(KernelModel):
    """A finality outcome verified through a frame by state-hash agreement."""

    status: Literal["verified"]
    confirmed_through_frame: NonNegativeSafeInteger
    verified_through_frame: NonNegativeSafeInteger
    agreed_state_hash_chain_digest: Digest

    @model_validator(mode="after")
    def _verified_not_ahead(self) -> VerifiedFinalityOutcome:
        if self.verified_through_frame > self.confirmed_through_frame:
            raise ValueError(
                "the verified frame must not lead the confirmed frame"
            )
        return self


class ConfirmedOnlyFinalityOutcome(KernelModel):
    """A finality outcome confirmed through a frame but not state-verified."""

    status: Literal["confirmed-only"]
    confirmed_through_frame: NonNegativeSafeInteger


class DisputedFinalityOutcome(KernelModel):
    """A finality outcome disputed from a first frame onward."""

    status: Literal["disputed"]
    confirmed_through_frame: _NullableFrame
    first_disputed_frame: NonNegativeSafeInteger


class PartialFinalityOutcome(KernelModel):
    """A finality outcome that is only partially confirmed."""

    status: Literal["partial"]
    confirmed_through_frame: _NullableFrame


P2PFinalityOutcome = Annotated[
    VerifiedFinalityOutcome
    | ConfirmedOnlyFinalityOutcome
    | DisputedFinalityOutcome
    | PartialFinalityOutcome,
    Field(discriminator="status"),
]
"""The state of frame finality that a p2p replay reproduces."""


# --- P2P replay evidence -------------------------------------------------


class SchemaArtifactBinding(KernelModel):
    """A pinned schema reference paired with the artifact that carries it."""

    schema: SchemaRef  # pyright: ignore[reportIncompatibleMethodOverride]
    artifact: ArtifactRef


class P2PReplayEvidence(KernelModel):
    """The frozen peer-to-peer evidence a p2p replay closes over."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-16.p2p-replay-evidence")
    )
    mesh_membership_digest: Digest
    membership_generation: PositiveSafeInteger
    frozen_peer_actor_ids: Annotated[
        list[ActorInstanceId], Field(min_length=2, max_length=64)
    ]
    mesh_membership: SchemaArtifactBinding
    frame_finality: SchemaArtifactBinding
    episode_boundaries: SchemaArtifactBinding
    bot_authorities: SchemaArtifactBinding
    decision_results: SchemaArtifactBinding
    decision_tape: SchemaArtifactBinding
    finality_outcome: P2PFinalityOutcome


# --- Decision tape -------------------------------------------------------


class ModelOutputTapeEntry(KernelModel):
    """One recorded model output on the decision tape."""

    kind: Literal["model-output"]
    modelcall_id: ModelInvocationId
    output_digest: Digest
    tool_call_ids: Annotated[list[ToolCallId], Field(max_length=64)]


class P2PBotActionTapeEntry(KernelModel):
    """One recorded, replay-only p2p bot action on the decision tape."""

    kind: Literal["p2p-bot-action"]
    decision_id: DecisionId
    decision_result_digest: Digest
    bot_actor_id: ActorInstanceId
    authority_actor_id: ActorInstanceId
    decision_origin: Literal["authority-local", "server-scheduler"]
    episode_id: EpisodeId
    frame_number: NonNegativeSafeInteger
    mesh_membership_digest: Digest
    membership_generation: PositiveSafeInteger
    authority_generation: PositiveSafeInteger
    action_digest: Digest
    output_digest: Digest
    replay_behavior: Literal["apply-recorded-action"]


TapeEntry = Annotated[
    ModelOutputTapeEntry | P2PBotActionTapeEntry, Field(discriminator="kind")
]
"""One entry on the decision tape: a model output or a p2p bot action."""


class DecisionTape(KernelModel):
    """The ordered tape of model and bot decisions a replay applies."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-16.decision-tape")
    )
    interaction_id: InteractionId
    entries: Annotated[list[TapeEntry], Field(max_length=4096)]

    @model_validator(mode="after")
    def _p2p_actions_are_unique_and_delegated(self) -> DecisionTape:
        decisions: set[str] = set()
        coordinates: set[tuple[object, ...]] = set()
        for entry in self.entries:
            if not isinstance(entry, P2PBotActionTapeEntry):
                continue
            if entry.decision_id in decisions:
                raise ValueError("a decision id must not repeat on the tape")
            decisions.add(entry.decision_id)
            coordinate = (
                entry.bot_actor_id,
                entry.episode_id,
                entry.frame_number,
                entry.membership_generation,
                entry.authority_generation,
            )
            if coordinate in coordinates:
                raise ValueError("a bot-action coordinate must not repeat")
            coordinates.add(coordinate)
            if entry.bot_actor_id == entry.authority_actor_id:
                raise ValueError("a bot must not be its own authority")
        return self


# --- State-hash check ----------------------------------------------------


class DeterministicStateHashCheck(KernelModel):
    """A deterministic per-frame state-hash comparison and its result."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-16.state-hash-check")
    )
    episode_id: EpisodeId
    frame_number: NonNegativeSafeInteger
    expected_state_hash: Digest
    observed_state_hash: Digest
    result: Literal["match", "mismatch"]
    verification: Literal["deterministic"]

    @model_validator(mode="after")
    def _result_matches_hashes(self) -> DeterministicStateHashCheck:
        hashes_match = self.expected_state_hash == self.observed_state_hash
        expected = "match" if hashes_match else "mismatch"
        if self.result != expected:
            raise ValueError("the result must agree with the state-hash comparison")
        return self


class VisualFallbackStateHashCheck(KernelModel):
    """A visual-fallback per-frame check when a state hash is unavailable."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-16.state-hash-check")
    )
    episode_id: EpisodeId
    frame_number: NonNegativeSafeInteger
    verification: Literal["visual-fallback"]
    reason: Literal[
        "determinism-not-declared", "snapshot-unavailable", "state-hash-unavailable"
    ]


StateHashCheck = Annotated[
    DeterministicStateHashCheck | VisualFallbackStateHashCheck,
    Field(discriminator="verification"),
]
"""One per-frame state-hash check: deterministic or visual-fallback."""


# --- Replay bundle validation --------------------------------------------


class ReplayBundleValidation(KernelModel):
    """The verdict of replaying a bundle in a hermetic environment."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-16.replay-bundle-validation")
    )
    interaction_id: InteractionId
    valid: bool
    external_calls_made: bool
    modified_artifact_ids: Annotated[list[ArtifactId], Field(max_length=256)]
    verification: Literal["deterministic", "visual-fallback"]

    @model_validator(mode="after")
    def _validity_is_consistent(self) -> ReplayBundleValidation:
        if self.external_calls_made:
            raise ValueError("a replay that made external calls is not valid")
        expected = not self.external_calls_made and not self.modified_artifact_ids
        if self.valid != expected:
            raise ValueError("valid must agree with the observed replay effects")
        return self


# --- Replay manifest -----------------------------------------------------


class ReplayManifest(KernelModel):
    """The manifest that pins one replay bundle and its capabilities."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-16.replay-manifest")
    )
    interaction_id: InteractionId
    execution_mode: ExecutionMode
    capability_levels: CapabilityLevels
    reproduction_scope: ReproductionScope
    experienced_stream_replay: ExperiencedStreamReplay | None = None
    determinism: DeterminismDeclaration | None = None
    p2p_replay_evidence: P2PReplayEvidence | None = None
    artifact_refs: Annotated[
        list[ArtifactRef], Field(min_length=1, max_length=4096)
    ]
    schema_bundle: ArtifactRef
    integrity_digest: Digest

    @model_validator(mode="after")
    def _conditional_sections_present(self) -> ReplayManifest:
        deterministic = self.capability_levels.deterministic
        if deterministic and self.determinism is None:
            raise ValueError("a deterministic replay must declare its determinism")
        if not deterministic and self.determinism is not None:
            raise ValueError("a non-deterministic replay must not declare determinism")
        p2p = self.execution_mode == "p2p"
        if p2p and self.p2p_replay_evidence is None:
            raise ValueError("a p2p replay must carry its p2p evidence")
        if not p2p and self.p2p_replay_evidence is not None:
            raise ValueError("only a p2p replay may carry p2p evidence")
        experienced = self.reproduction_scope == "canonical-and-experienced"
        if experienced and self.experienced_stream_replay is None:
            raise ValueError("an experienced-scope replay must carry its stream")
        if not experienced and self.experienced_stream_replay is not None:
            raise ValueError("only an experienced-scope replay may carry a stream")
        return self

    @model_validator(mode="after")
    def _semantic_invariants(self) -> ReplayManifest:
        levels = self.capability_levels
        if not (levels.visual or levels.deterministic):
            raise ValueError("a replay must declare at least one capability")
        replay = self.experienced_stream_replay
        if replay is not None:
            known = set(replay.canonical_event_ids)
            for frame in replay.experienced_lineage:
                if (
                    frame.delivery_kind == "corrected"
                    and frame.canonical_event_id not in known
                ):
                    raise ValueError(
                        "a corrected frame must name a known canonical event"
                    )
        evidence = self.p2p_replay_evidence
        if evidence is not None:
            peers = evidence.frozen_peer_actor_ids
            if list(peers) != sorted(peers):
                raise ValueError("frozen peer actor ids must be canonically sorted")
            mesh_digest = evidence.mesh_membership.artifact.digest
            if evidence.mesh_membership_digest != mesh_digest:
                raise ValueError("mesh digest must bind the mesh membership artifact")
            root = {ref.artifact_id: ref for ref in self.artifact_refs}
            bindings = (
                evidence.mesh_membership,
                evidence.frame_finality,
                evidence.episode_boundaries,
                evidence.bot_authorities,
                evidence.decision_results,
                evidence.decision_tape,
            )
            for binding in bindings:
                if root.get(binding.artifact.artifact_id) != binding.artifact:
                    raise ValueError(
                        "every p2p evidence artifact must close over the manifest set"
                    )
        return self
