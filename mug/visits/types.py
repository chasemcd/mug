"""The objects that API-04 owns: visits, plans, treatment, exposure, and state.

You construct each object with its data alone; the ``schema`` envelope fills
itself from the frozen bundle. The frozen JSON-Schema corpus stays the authority,
and ``visits_schema`` loads it for the conformance test.

This family models the visit runtime record, the materialized visit plan, the
treatment design and its placements, the assignment and exposure records, the
allocation counter, and the per-visit state document. It adds no runtime.

Three invariants are not expressible in JSON Schema and live here as validators:

- a plan's planned activities carry distinct ordinals;
- a placement reference names a declared shared treatment, and every crossed
  design factor is placed at one site at least;
- a group assignment names a group and a participant assignment names a visit.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from mug.kernel import (
    Digest,
    SchemaBundle,
    SchemaRef,
    SeatKey,
    UtcInstant,
    VersionStamp,
    load_family_schema,
)
from mug.kernel._base import KernelModel
from mug.kernel.ids import (
    ActivityDefinitionId,
    ActivityOccurrenceId,
    EnrollmentId,
    FlowNodeDefinitionId,
    GroupId,
    StudyId,
    VisitId,
)
from mug.kernel.refs import (
    DeploymentRevisionRef,
    NonNegativeSafeInteger,
    StudyVersionRef,
)

_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs/architecture/phase-0/api-04/schemas/v0/visit-plan.schema.json"
)


@lru_cache(maxsize=1)
def visits_schema() -> SchemaBundle:
    """Return the loaded API-04 bundle (with the shared kernel registered)."""
    return load_family_schema(str(_SCHEMA_PATH))


def _schema_ref(name: str) -> SchemaRef:
    """Build the pinned schema reference for one object from the frozen bundle."""
    digest = Digest(algorithm="sha-256", hex=visits_schema().bundle_digest)
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


class FieldRef(KernelModel):
    """A pointer to one activity field, by activity key and field key."""

    activity_key: _AuthoringKey
    field_key: _AuthoringKey


class AssignRandom(KernelModel):
    """Assign each unit at random, with no balancing constraint."""

    policy: Literal["random"]


class AssignBalanced(KernelModel):
    """Assign to keep the cells balanced across a named unit."""

    policy: Literal["balanced"]
    unit: Literal["groups", "participants"]


class AssignBlocked(KernelModel):
    """Assign in fixed blocks."""

    policy: Literal["blocked"]


class AssignStratified(KernelModel):
    """Assign at random inside strata defined by one activity field."""

    policy: Literal["stratified"]
    by: FieldRef


AssignPolicy = Annotated[
    AssignRandom | AssignBalanced | AssignBlocked | AssignStratified,
    Field(discriminator="policy"),
]


class Treatment(KernelModel):
    """One factor: its levels, its assignment policy, scope, and within order."""

    key: _AuthoringKey
    levels: Annotated[
        list[_AuthoringKey], Field(min_length=1, max_length=64)
    ]
    assign: AssignPolicy
    scope: Literal["participant", "group"]
    within: bool | None = None
    order: Literal["randomized", "counterbalanced"] | None = None


class TreatmentRef(KernelModel):
    """A reference to a declared shared treatment by its key."""

    ref: _AuthoringKey


class CastSlotSite(KernelModel):
    """A placement site at one cast seat of an activity."""

    kind: Literal["cast-slot"]
    activity_key: _AuthoringKey
    seat_key: SeatKey


class ParameterSite(KernelModel):
    """A placement site at one parameter of an activity."""

    kind: Literal["parameter"]
    activity_key: _AuthoringKey
    parameter_key: _AuthoringKey


PlacementSite = Annotated[CastSlotSite | ParameterSite, Field(discriminator="kind")]


class TreatmentPlacement(KernelModel):
    """One effect site and the treatment placed there, inline or by reference."""

    site: PlacementSite
    treatment: Treatment | TreatmentRef


class Design(KernelModel):
    """A crossed design: the factors it crosses and how it assigns cells."""

    cross: Annotated[list[_AuthoringKey], Field(min_length=2, max_length=16)]
    assign: AssignPolicy


class TreatmentPlan(KernelModel):
    """A study's treatment design: shared treatments, placements, and crossing."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-04.treatment-plan")
    )
    study_version: StudyVersionRef
    shared_treatments: Annotated[list[Treatment], Field(max_length=64)]
    placements: Annotated[
        list[TreatmentPlacement], Field(min_length=1, max_length=256)
    ]
    design: Design | None = None

    @model_validator(mode="after")
    def _refs_resolve_and_factors_are_placed(self) -> TreatmentPlan:
        shared_keys = {treatment.key for treatment in self.shared_treatments}
        placed_keys: set[str] = set()
        for placement in self.placements:
            treatment = placement.treatment
            if isinstance(treatment, TreatmentRef):
                if treatment.ref not in shared_keys:
                    raise ValueError(
                        "a placement must reference a declared shared treatment"
                    )
                placed_keys.add(treatment.ref)
            else:
                placed_keys.add(treatment.key)
        if self.design is not None:
            for factor_key in self.design.cross:
                if factor_key not in placed_keys:
                    raise ValueError(
                        "a crossed design factor must be placed at one site at least"
                    )
        return self


class Visit(KernelModel):
    """One participation runtime record, pinned to a study version and revision."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-04.visit")
    )
    visit_id: VisitId
    enrollment_id: EnrollmentId
    study_id: StudyId
    study_version: StudyVersionRef
    deployment: DeploymentRevisionRef
    status: Literal["created", "in-progress", "completed", "abandoned"]
    version: VersionStamp


class RandomizationOutcome(KernelModel):
    """The recorded outcome of one randomization rule, with its seed commitment."""

    flow_node_id: FlowNodeDefinitionId
    rule_key: _AuthoringKey
    chosen: Annotated[list[_AuthoringKey], Field(min_length=1, max_length=64)]
    seed_commitment: Digest


class PlannedActivity(KernelModel):
    """One activity occurrence in a plan, with its order and parameter digest."""

    occurrence_id: ActivityOccurrenceId
    activity_definition_id: ActivityDefinitionId
    flow_node_id: FlowNodeDefinitionId
    ordinal: NonNegativeSafeInteger
    status: Literal["pending", "active", "completed", "skipped"]
    parameter_digest: Digest


class EligibilityCallback(KernelModel):
    """A flow-level screening callback, fail-closed by default on error."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-04.eligibility-callback")
    )
    flow_node_id: FlowNodeDefinitionId
    rule_key: _AuthoringKey
    callback: _QualifiedName
    on_error: Literal["fail_closed", "fail_open"] | None = None


class VisitPlan(KernelModel):
    """The materialized plan for one visit: activities and randomization outcomes."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-04.visit-plan")
    )
    visit_id: VisitId
    study_version: StudyVersionRef
    plan_digest: Digest
    activities: Annotated[
        list[PlannedActivity], Field(min_length=1, max_length=1024)
    ]
    randomization_outcomes: Annotated[
        list[RandomizationOutcome], Field(max_length=256)
    ]
    eligibility: Annotated[
        list[EligibilityCallback], Field(max_length=256)
    ] | None = None
    materialized_at: UtcInstant

    @model_validator(mode="after")
    def _ordinals_are_distinct(self) -> VisitPlan:
        seen: set[int] = set()
        for activity in self.activities:
            if activity.ordinal in seen:
                raise ValueError("planned activity ordinals must be distinct")
            seen.add(activity.ordinal)
        return self


class TreatmentAssignment(KernelModel):
    """The intent to expose one unit to a treatment level, by scope."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-04.treatment-assignment")
    )
    treatment_key: _AuthoringKey
    level_key: _AuthoringKey
    scope: Literal["participant", "group"]
    visit_id: VisitId | None = None
    group_id: GroupId | None = None
    assigned_at: UtcInstant
    assignment_digest: Digest

    @model_validator(mode="after")
    def _scope_matches_reference(self) -> TreatmentAssignment:
        if self.scope == "group":
            if self.group_id is None or self.visit_id is not None:
                raise ValueError("a group assignment names a group, never a visit")
        elif self.visit_id is None or self.group_id is not None:
            raise ValueError("a participant assignment names a visit, never a group")
        return self


class TreatmentExposure(KernelModel):
    """The actual delivery of one treatment level at one activity occurrence."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-04.treatment-exposure")
    )
    visit_id: VisitId
    treatment_key: _AuthoringKey
    level_key: _AuthoringKey
    occurrence_id: ActivityOccurrenceId
    exposed_at: UtcInstant
    exposure_digest: Digest


class CellLevel(KernelModel):
    """One coordinate of an allocation cell: a treatment key and its level."""

    treatment_key: _AuthoringKey
    level_key: _AuthoringKey


class AllocationCellCount(KernelModel):
    """A running count of groups and participants placed in one design cell."""

    cell: Annotated[list[CellLevel], Field(min_length=1, max_length=16)]
    groups: NonNegativeSafeInteger
    participants: NonNegativeSafeInteger


class AllocationState(KernelModel):
    """The current allocation counter across a study version's design cells."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-04.allocation-state")
    )
    study_version: StudyVersionRef
    cells: Annotated[list[AllocationCellCount], Field(max_length=4096)]
    version: VersionStamp


class StateDocument(KernelModel):
    """One per-visit state namespace, pinned to a content schema and digest."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-04.state-document")
    )
    visit_id: VisitId
    namespace: _AuthoringKey
    content_schema: SchemaRef
    content_digest: Digest
    version: VersionStamp
