"""The seven records that API-05 owns: seats, actors, casting, and grouping.

You construct each object with its data alone; the ``schema`` envelope fills
itself from the frozen bundle. The frozen JSON-Schema corpus stays the authority,
and ``casting_schema`` loads it for the conformance test.

This family models the authoring and runtime records for seats, actor instances,
controller bindings, cast declarations, seat-agent bindings, ONNX inference
policies, and match groups. It adds no runtime; matchmaking, lease grants, and
interaction assembly stay with API-06.

Several invariants are not expressible in JSON Schema and live here as validators:

- an actor kind and its subject agree (a human actor names a human subject only,
  a software actor names a software subject only);
- a controller reference is present when the controller is not human input, and
  absent when it is human input;
- a controller kind is allowed for its capability (RP-5 capability map);
- an ONNX argmax policy declares no temperature;
- a latency match declares at least one round-trip-time bound;
- a cast names every declared seat and no other (R-16 cast totality);
- a reused group activity declares its on-missing behavior (R-18).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from mug.kernel import (
    CapabilitySet,
    Digest,
    Duration,
    SchemaBundle,
    SchemaRef,
    SeatKey,
    load_family_schema,
)
from mug.kernel._base import KernelModel
from mug.kernel.ids import (
    ActorInstanceId,
    AgentVersionId,
    ControllerBindingId,
    EnrollmentId,
    InteractionId,
    SeatDefinitionId,
    id_pattern,
)

_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs/architecture/phase-0/api-05/schemas/v0/actor.schema.json"
)


@lru_cache(maxsize=1)
def casting_schema() -> SchemaBundle:
    """Return the loaded API-05 bundle (with the shared kernel registered)."""
    return load_family_schema(str(_SCHEMA_PATH))


def _schema_ref(name: str) -> SchemaRef:
    """Build the pinned schema reference for one object from the frozen bundle."""
    digest = Digest(algorithm="sha-256", hex=casting_schema().bundle_digest)
    return SchemaRef(name=name, version=0, digest=digest)


_AuthoringKey = Annotated[
    str, Field(pattern=r"^[a-z][a-z0-9]*(?:[-_.][a-z0-9]+)*$", max_length=128)
]
_VersionedRef = Annotated[
    str,
    Field(
        pattern=r"^[a-z][a-z0-9]*(?:[-_.][a-z0-9]+)*@[A-Za-z0-9][A-Za-z0-9._-]{0,63}$",
        max_length=192,
    ),
]
_EnvAgentId = Annotated[
    str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$", max_length=128)
]
# The seatbind kind is not in the shared identifier registry; anchor it locally.
_SeatAgentBindingId = Annotated[str, Field(pattern=id_pattern("seatbind"))]

# RP-5 capability map: which controller kinds each capability admits.
_CAPABILITY_CONTROLLERS: dict[str, frozenset[str]] = {
    "game-action": frozenset({"human-input", "scripted-policy", "rl-model"}),
    "chat-message": frozenset({"human-input", "llm"}),
    "annotation": frozenset({"human-input"}),
    "action-plan": frozenset({"rl-model", "llm"}),
}


class SeatDefinition(KernelModel):
    """A named seat: who may take it and which modality capabilities it needs."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-05.seat-definition")
    )
    seat_definition_id: SeatDefinitionId
    seat_key: SeatKey
    occupancy: Literal["human", "software", "either"]
    modality_capabilities: CapabilitySet


class HumanSubject(KernelModel):
    """The enrolled participant behind a human actor instance."""

    enrollment_id: EnrollmentId


class SoftwareSubject(KernelModel):
    """The pinned agent version behind a software actor instance."""

    agent_version_id: AgentVersionId


class ActorInstance(KernelModel):
    """One occupant of one seat in one interaction: human or software."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-05.actor-instance")
    )
    actor_id: ActorInstanceId
    interaction_id: InteractionId
    seat_definition_id: SeatDefinitionId
    seat_key: SeatKey
    kind: Literal["human", "software"]
    human_subject: HumanSubject | None = None
    software_subject: SoftwareSubject | None = None

    @model_validator(mode="after")
    def _subject_agrees_with_kind(self) -> ActorInstance:
        if self.kind == "human":
            if self.human_subject is None or self.software_subject is not None:
                raise ValueError("a human actor names a human subject only")
        elif self.software_subject is None or self.human_subject is not None:
            raise ValueError("a software actor names a software subject only")
        return self


class ControllerBinding(KernelModel):
    """How one channel drives one actor: a capability and a controller kind."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-05.controller-binding")
    )
    binding_id: ControllerBindingId
    actor_id: ActorInstanceId
    channel_key: _AuthoringKey
    capability: Literal["game-action", "chat-message", "annotation", "action-plan"]
    controller_kind: Literal["human-input", "scripted-policy", "rl-model", "llm"]
    controller_ref: AgentVersionId | None = None

    @model_validator(mode="after")
    def _reference_and_capability_agree(self) -> ControllerBinding:
        if self.controller_kind == "human-input":
            if self.controller_ref is not None:
                raise ValueError("human input takes no controller reference")
        elif self.controller_ref is None:
            raise ValueError("a non-human controller must name a reference")
        if self.controller_kind not in _CAPABILITY_CONTROLLERS[self.capability]:
            raise ValueError("controller kind is not allowed for this capability")
        return self


class OnnxPreprocessing(KernelModel):
    """A declared observation-preprocessing rule from a closed vocabulary (RP-5)."""

    transform: Literal[
        "identity", "normalize", "standardize", "clip", "flatten", "one-hot"
    ]


class OnnxPolicy(KernelModel):
    """A typed ONNX inference policy: no inline code, only declared structure."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-05.onnx-policy")
    )
    policy_ref: _VersionedRef
    preprocessing: OnnxPreprocessing
    selection_mode: Literal["argmax", "sample"]
    temperature: Annotated[float, Field(gt=0, le=100)] | None = None

    @model_validator(mode="after")
    def _argmax_takes_no_temperature(self) -> OnnxPolicy:
        if self.selection_mode != "sample" and self.temperature is not None:
            raise ValueError("an argmax policy declares no temperature")
        return self


class HumanActorSpec(KernelModel):
    """A cast slot filled by a human participant."""

    kind: Literal["human"]


class AgentActorSpec(KernelModel):
    """A cast slot filled by a pinned agent version."""

    kind: Literal["agent"]
    agent_ref: _VersionedRef


ActorSpec = Annotated[
    HumanActorSpec | AgentActorSpec, Field(discriminator="kind")
]


class CastTreatment(KernelModel):
    """A between-subject treatment: a keyed set of two or more actor levels."""

    kind: Literal["treatment"]
    treatment_key: _AuthoringKey
    levels: Annotated[
        dict[_AuthoringKey, ActorSpec], Field(min_length=2, max_length=64)
    ]


CastSlot = Annotated[
    HumanActorSpec | AgentActorSpec | CastTreatment, Field(discriminator="kind")
]


class CastDeclaration(KernelModel):
    """A total mapping from every seat of an activity to who fills it."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-05.cast-declaration")
    )
    activity_key: _AuthoringKey
    seats: Annotated[list[_AuthoringKey], Field(min_length=1, max_length=64)]
    cast: Annotated[dict[_AuthoringKey, CastSlot], Field(min_length=1, max_length=64)]

    @model_validator(mode="after")
    def _cast_names_every_seat(self) -> CastDeclaration:
        if sorted(self.cast) != sorted(self.seats):
            raise ValueError("a cast must name every seat and no other")
        return self


class SeatAgentBinding(KernelModel):
    """The stable join from an environment agent handle to an actor and seat."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-05.seat-agent-binding")
    )
    seat_agent_binding_id: _SeatAgentBindingId
    interaction_id: InteractionId
    actor_id: ActorInstanceId
    seat_key: SeatKey
    env_agent_id: _EnvAgentId


class MatchFifo(KernelModel):
    """First-in first-out match: fill the group in arrival order."""

    strategy: Literal["fifo"]


class MatchLatency(KernelModel):
    """A round-trip-time match bounded by an estimate and a peer-to-peer probe."""

    strategy: Literal["latency"]
    max_estimated_rtt: Duration | None = None
    max_p2p_rtt: Duration | None = None

    @model_validator(mode="after")
    def _declares_one_bound(self) -> MatchLatency:
        if self.max_estimated_rtt is None and self.max_p2p_rtt is None:
            raise ValueError("a latency match declares at least one round-trip bound")
        return self


class MatchCustom(KernelModel):
    """A custom match delegated to a pinned matchmaker version."""

    strategy: Literal["custom"]
    matchmaker_ref: _VersionedRef


MatchStrategy = Annotated[
    MatchFifo | MatchLatency | MatchCustom, Field(discriminator="strategy")
]


class GroupActivity(KernelModel):
    """One activity a group runs, with its behavior when a member is missing."""

    activity_key: _AuthoringKey
    on_missing_member: Literal["wait", "regroup"] | None = None


class Group(KernelModel):
    """A persistent set of co-located participants that reunites across activities."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-05.group")
    )
    group_key: _AuthoringKey
    size: Annotated[int, Field(ge=1, le=64)]
    match: MatchStrategy | None = None
    wait: Duration | None = None
    on_timeout: Literal["release"] | None = None
    activities: Annotated[list[GroupActivity], Field(min_length=1, max_length=128)]

    @model_validator(mode="after")
    def _reused_activity_declares_on_missing(self) -> Group:
        for activity in self.activities[1:]:
            if activity.on_missing_member is None:
                raise ValueError("a reused activity must declare on-missing behavior")
        return self
