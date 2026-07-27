"""The participant flow service: materialize a plan, present, and advance.

A study is an ordered list of activities (forms, content pages, and its game),
and the author writes it (``mug.content.study``). This service runs one
participant through it: ``materialize_flow`` opens the runtime flow for a visit at
the first activity, ``present`` maps the active activity to the payload a seat
renders, and ``advance_flow`` checks the answers against the form the author wrote
and moves the pointer on.

The study is a value the caller passes in, not a constant this module holds. That
is what lets a real study put its own consent, its own surveys, and its own
debrief around the game, rather than inherit a demo's. The frozen ``FormSpec`` and
``ContentSpec`` records are the authored content. The service validates answers, so
a malformed submission is refused before it advances the flow, and records them
through the ``on_answers`` seam.

**What the aggregate holds.** The frozen ``VisitPlan`` is the head: the study
version this visit runs, the ordered occurrences with their identifiers and
parameter digests, and the randomization outcomes that were drawn. Beside it sits
one runtime key, ``flow``, holding the pointer and the streams this visit captured
-- the two things that change as a participant walks and that no frozen record
carries. The plan is what happened; the pointer is where they are.
"""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Annotated, Any, Literal

from pydantic import Field

from mug.content.plan import (
    Derive,
    Occurrence,
    PlanDraft,
    Seed,
    activity_for,
    declared_eligibility,
    draft_plan,
    parameter_digest,
    planned_activities,
)
from mug.content.study import Activity, Step, Study
from mug.content.types import ContentBody, ContentSpec, FormField, FormSpec
from mug.kernel import (
    CommandReceipt,
    CommandTypeRef,
    Digest,
    TypedObject,
    VersionStamp,
    compute_digest,
    etag,
)
from mug.kernel._base import KernelModel
from mug.kernel.ids import StreamId, VisitId, VisitPlanId
from mug.kernel.refs import (
    NonNegativeSafeInteger,
    PositiveSafeInteger,
    StudyVersionRef,
)
from mug.runtime import CommandContext, commit_command, reject_command, result_ref
from mug.storage import Store
from mug.visits.types import PlannedActivity, RandomizationOutcome, VisitPlan

_MATERIALIZE_COMMAND = CommandTypeRef(name="flow.materialize", version=0)
_ADVANCE_COMMAND = CommandTypeRef(name="flow.advance", version=0)
_RESULT_SCHEMA_NAME = "mug.command-result.visit-transition"

_AuthoringKey = Annotated[
    str, Field(pattern=r"^[a-z][a-z0-9]*(?:[-_.][a-z0-9]+)*$", max_length=128)
]
_ActivityKind = Literal["form", "content", "game", "comparison"]


class FlowActivity(KernelModel):
    """One occurrence in the runtime flow: what runs, and what it delivers.

    ``key`` names the occurrence and ``activity_key`` names the activity the author
    wrote. They differ only for a within-subject repeat, where one authored activity
    is met once per level and each occurrence needs a name of its own.

    Progress is not here. ``VisitPlan.activities`` carries the status of every
    occurrence, and one record of progress is enough: two would be one too many.
    """

    key: _AuthoringKey
    activity_key: _AuthoringKey
    kind: _ActivityKind
    within: dict[_AuthoringKey, _AuthoringKey] = Field(default_factory=dict)


# Record one validated form submission, and report whether it was recorded. The
# transport injects it; see ``advance_flow``.
RecordAnswers = Callable[[FormSpec, dict[str, Any]], Awaitable[bool]]

# Read what this participant is assigned, assigning anything that has become
# decidable. It is a callable rather than a value because an advance may itself be
# what makes a factor decidable: the form it records is the one a stratified factor
# was waiting for, so the levels have to be read AFTER the answers are recorded.
ReadLevels = Callable[[], Awaitable[Mapping[str, str]]]


class FlowState(KernelModel):
    """The runtime progress of one visit through the study, with a pointer.

    This is the ``flow`` key of the visit-plan aggregate, not the aggregate itself.
    It holds what changes as a participant walks and what the frozen ``VisitPlan``
    has no field for.
    """

    visitplan_id: VisitPlanId
    visit_id: VisitId
    activities: Annotated[list[FlowActivity], Field(min_length=1, max_length=256)]
    pointer: NonNegativeSafeInteger
    status: Literal["in-progress", "completed"]
    captured_streams: Annotated[list[StreamId], Field(max_length=1024)] = Field(
        default_factory=list
    )
    version: VersionStamp


def flow_of(state: Mapping[str, Any] | None) -> FlowState | None:
    """Return the runtime flow held beside a committed visit plan."""
    if not isinstance(state, Mapping):
        return None
    found = state.get("flow")
    if not isinstance(found, Mapping):
        return None
    return FlowState.model_validate(found)


def plan_of(state: Mapping[str, Any] | None) -> VisitPlan | None:
    """Return the visit plan committed on one aggregate, or None for none."""
    if not isinstance(state, Mapping):
        return None
    body = {key: value for key, value in state.items() if key != "flow"}
    try:
        return VisitPlan.model_validate(body)
    except ValueError:
        return None


def _consent_form() -> FormSpec:
    return FormSpec(
        form_key="consent",
        fields=[
            FormField(
                field_key="agree",
                kind="choice",
                label="Do you consent to take part in this study?",
                required=True,
                options=["yes", "no"],
            )
        ],
        version=1,
    )


def _survey_form() -> FormSpec:
    return FormSpec(
        form_key="survey",
        fields=[
            FormField(
                field_key="mood",
                kind="likert",
                label="How do you feel right now?",
                required=True,
                scale=5,
            ),
            FormField(
                field_key="comment",
                kind="text",
                label="Any comments? (optional)",
                required=False,
            ),
        ],
        version=1,
    )


def _debrief_content() -> ContentSpec:
    return ContentSpec(
        content_key="debrief",
        body=ContentBody(
            origin="author",
            source="inline",
            format="markdown",
            executable=False,
            text="# Thank you\n\nYou have finished the study.",
        ),
        response_required=False,
        version=1,
    )


def demo_study() -> Study:
    """Return the study the demos and the tests run: consent, survey, game, debrief.

    It is one study among any others, not the shape a study has to take. A real
    study writes its own (see ``mug.content.study``).
    """
    return Study(
        Step(Activity(key="consent", kind="form", form=_consent_form())),
        Step(Activity(key="survey", kind="form", form=_survey_form())),
        Step(Activity(key="play", kind="game")),
        Step(Activity(key="debrief", kind="content", content=_debrief_content())),
    )


def completion_code(visit_id: str) -> str:
    """Return the stable completion code for one visit.

    The code derives from the visit id, so the completed flow always claims the
    same code and a repeated completion is idempotent. The code carries no secret
    and no participant data, only a digest of the occurrence id.
    """
    body = visit_id.split("_", 1)[1] if "_" in visit_id else visit_id
    return "MUG-" + hashlib.sha256(body.encode()).hexdigest()[:10].upper()


def present(
    state: FlowState, study: Study, levels: Mapping[str, str] | None = None
) -> dict[str, Any]:
    """Return the payload the seat renders for the flow's active activity.

    ``levels`` is what this participant was assigned. It decides which written page
    they read and which specification the game runs, so a study with no treatment
    passes none and reads exactly as it did before treatments existed. The delivery
    names the occurrence, not the authored activity, because a within-subject repeat
    meets the same activity more than once and each occurrence is its own step.
    """
    if state.status == "completed":
        return {
            "kind": "complete",
            "completion_code": completion_code(state.visit_id),
        }
    active = state.activities[state.pointer]
    delivered = {**(levels or {}), **active.within}
    activity = activity_for(study, active.activity_key, delivered)
    # ``activity_key`` is what the author wrote, so a mount looks the game or the
    # comparison up by it; ``occurrence_key`` is this one step, so a repeat records
    # each pass separately. They are equal unless a within-subject factor repeats.
    where = {"activity_key": activity.key, "occurrence_key": active.key}
    if activity.kind == "form" and activity.form is not None:
        return {
            "kind": "form",
            **where,
            "form": activity.form.model_dump(mode="json", exclude_none=True),
        }
    if activity.kind == "content" and activity.content is not None:
        return {
            "kind": "content",
            **where,
            "content": activity.content.model_dump(mode="json", exclude_none=True),
        }
    if activity.kind == "comparison":
        # The question is authored and travels with the activity; the options are
        # this participant's own recorded runs, so the mount that owns the socket
        # sends them once it has resolved and blinded them.
        return {
            "kind": "comparison",
            **where,
            "ask": study.comparison(activity.key).ask,
        }
    return {"kind": "game", **where}


def _answer_refusal(form: FormSpec, answers: dict[str, Any]) -> str | None:
    """Return why the answers do not satisfy the form, or None when they do."""
    for field in form.fields:
        value = answers.get(field.field_key)
        if value is None:
            if field.required:
                return f"the field {field.field_key} is required"
            continue
        if (
            field.kind == "choice"
            and field.options is not None
            and value not in field.options
        ):
            return f"the field {field.field_key} has an invalid option"
        if (
            field.kind == "likert"
            and field.scale is not None
            and (not isinstance(value, int) or not 1 <= value <= field.scale)
        ):
            return f"the field {field.field_key} is off its scale"
    return None


def _result(state: FlowState, outcome: str) -> TypedObject:
    return TypedObject(
        schema=result_ref(_RESULT_SCHEMA_NAME),
        data={
            "outcome": outcome,
            "visit_id": state.visit_id,
            "status": state.status,
            "revision": state.version.revision,
        },
    )


class MaterializeFlowCommand(KernelModel):
    """The domain input to open the runtime flow for one visit."""

    visit_id: VisitId


class AdvanceFlowCommand(KernelModel):
    """The domain input to record a form answer set and advance the pointer.

    ``answers`` is empty for a content activity that requires no response.
    ``expected_revision`` is the revision the caller last saw.
    ``captured_streams`` names any stream a runtime captured for this step (for
    example an episode's transition stream), so the visit records where its
    lineage lives.
    """

    answers: dict[_AuthoringKey, Any] = Field(default_factory=dict)
    expected_revision: PositiveSafeInteger
    captured_streams: Annotated[list[StreamId], Field(max_length=1024)] = Field(
        default_factory=list
    )


def _flow_body(
    draft: PlanDraft,
    *,
    visitplan_id: str,
    visit_id: str,
    pointer: int,
    status: str,
    captured_streams: Sequence[str],
) -> dict[str, Any]:
    """Draft the runtime half of the aggregate: the pointer and the streams."""
    return {
        "visitplan_id": visitplan_id,
        "visit_id": visit_id,
        "activities": [
            {
                "key": one.key,
                "activity_key": one.activity_key,
                "kind": one.kind,
                "within": dict(sorted(one.within.items())),
            }
            for one in draft.occurrences
        ],
        "pointer": pointer,
        "status": status,
        "captured_streams": list(captured_streams),
    }


def _aggregate(plan: VisitPlan, flow: FlowState) -> dict[str, Any]:
    """Draft the state one visit-plan aggregate commits.

    The frozen plan is the head and the runtime pointer sits beside it under one
    key, exactly as a form response keeps its answers artifact beside the record.
    Dropping that one key reads the plan back.
    """
    return {
        **plan.model_dump(mode="json", exclude_none=True),
        "flow": flow.model_dump(mode="json", exclude_none=True),
    }


async def materialize_flow(
    command: MaterializeFlowCommand,
    *,
    study: Study,
    study_version: StudyVersionRef,
    context: CommandContext,
    store: Store,
    derive: Derive,
    seed: Seed,
    levels: Mapping[str, str] | None = None,
    orders: Mapping[str, Sequence[str]] | None = None,
    materialized_at: str | None = None,
) -> CommandReceipt:
    """Commit the plan this visit will walk, and open its pointer at the first step.

    ``levels`` is what the participant was already assigned; a factor still waiting
    for its input (a stratified one) is simply absent, and the occurrences it touches
    are re-digested on the advance that assigns it. ``orders`` is the order each
    within-subject factor delivers its levels in, which the caller draws because a
    counterbalanced order reads the durable counts.
    """
    draft = draft_plan(
        study, visit_id=command.visit_id, orders=orders or {}, derive=derive, seed=seed
    )
    plan = _plan(
        study,
        draft,
        visit_id=command.visit_id,
        study_version=study_version,
        assigned=dict(levels or {}),
        derive=derive,
        materialized_at=materialized_at or context.recorded_at,
    )
    body = _flow_body(
        draft,
        visitplan_id=context.aggregate_id,
        visit_id=command.visit_id,
        pointer=0,
        status="in-progress",
        captured_streams=[],
    )
    state = FlowState(**body, version=VersionStamp(revision=1, etag=etag(body)))
    return await commit_command(
        context,
        command=_MATERIALIZE_COMMAND,
        new_state=_aggregate(plan, state),
        result=_result(state, "materialized"),
        store=store,
    )


def _plan(
    study: Study,
    draft: PlanDraft,
    *,
    visit_id: str,
    study_version: StudyVersionRef,
    assigned: Mapping[str, str],
    derive: Derive,
    materialized_at: str,
    pointer: int = 0,
    statuses: Sequence[str] | None = None,
) -> VisitPlan:
    """Build the plan for one visit at one point in its walk.

    The ``plan_digest`` covers the occurrences and the orders that were drawn --
    what the participant was given -- and not the pointer, so it stays the same as
    they walk. Two participants in different conditions have different plan digests;
    one participant has one digest from start to finish.
    """
    activities = planned_activities(
        study,
        draft,
        visit_id=visit_id,
        study_version_id=study_version.study_version_id,
        assigned=assigned,
        derive=derive,
        pointer=pointer,
        statuses=statuses,
    )
    outcomes = list(draft.outcomes)
    eligibility = declared_eligibility(
        study, derive=derive, study_version_id=study_version.study_version_id
    )
    return VisitPlan(
        visit_id=visit_id,
        study_version=study_version,
        plan_digest=_plan_digest(activities, outcomes),
        activities=activities,
        randomization_outcomes=outcomes,
        eligibility=eligibility or None,
        materialized_at=materialized_at,
    )


def _plan_digest(
    activities: Sequence[PlannedActivity], outcomes: Sequence[RandomizationOutcome]
) -> Digest:
    """Return the digest of what a plan gives, leaving out how far it has got."""
    return compute_digest(
        {
            "activities": [
                one.model_dump(mode="json", exclude_none=True, exclude={"status"})
                for one in activities
            ],
            "randomization_outcomes": [
                one.model_dump(mode="json", exclude_none=True) for one in outcomes
            ],
        }
    )


async def advance_flow(
    command: AdvanceFlowCommand,
    *,
    study: Study,
    context: CommandContext,
    store: Store,
    on_answers: RecordAnswers | None = None,
    levels: ReadLevels | None = None,
) -> CommandReceipt:
    """Record the active form answers and advance the flow to the next activity.

    ``on_answers`` is how the answers become evidence. This layer holds no entropy,
    no clock, and no object store, so the transport above it injects a recorder that
    writes the values and commits the ``FormResponse`` that binds them
    (``mug.content.forms``). It runs after validation and before the flow moves, and
    the flow does **not** move when it fails: advancing past a form whose answers
    were not recorded would lose them silently, which is the failure this seam
    exists to end. With no recorder injected the flow advances as before, which is
    what a test that is not about answers wants.

    ``levels`` reads what the participant is assigned, and it is read **after** the
    answers are recorded, because this advance may be what makes a factor decidable:
    a stratified factor waits for exactly the form this step just answered. The
    occurrences it touches are re-digested here, so the plan's parameter digests
    always state the condition the participant will meet and never a placeholder.
    """
    raw = store.load_aggregate(context.aggregate_id)
    if raw is None:
        return reject_command(
            context,
            command=_ADVANCE_COMMAND,
            code="resource.not_found",
            category="not_found",
            message="the flow does not exist",
            retry="never",
        )
    plan = plan_of(raw)
    current = flow_of(raw)
    if plan is None or current is None:
        return reject_command(
            context,
            command=_ADVANCE_COMMAND,
            code="resource.not_found",
            category="not_found",
            message="the flow does not exist",
            retry="never",
        )
    if current.status == "completed":
        return reject_command(
            context,
            command=_ADVANCE_COMMAND,
            code="command.state_conflict",
            category="conflict",
            message="the flow is already complete",
            retry="never",
        )

    active = current.activities[current.pointer]
    activity = study.activity(active.activity_key)
    if activity.kind == "form" and activity.form is not None:
        refusal = _answer_refusal(activity.form, command.answers)
        if refusal is not None:
            return reject_command(
                context,
                command=_ADVANCE_COMMAND,
                code="schema.validation_failed",
                category="validation",
                message=refusal,
                retry="never",
            )
        if on_answers is not None and not await on_answers(
            activity.form, command.answers
        ):
            return reject_command(
                context,
                command=_ADVANCE_COMMAND,
                code="command.state_conflict",
                category="conflict",
                message="the answers were not recorded",
                retry="refresh_then_new_command",
            )

    pointer = current.pointer + 1
    status = "in-progress"
    if pointer >= len(current.activities):
        pointer = current.pointer
        status = "completed"

    statuses = [
        "completed" if index <= current.pointer else "pending"
        for index in range(len(current.activities))
    ]
    if status == "in-progress":
        statuses[pointer] = "active"

    body: dict[str, Any] = {
        "visitplan_id": current.visitplan_id,
        "visit_id": current.visit_id,
        "activities": [
            one.model_dump(mode="json", exclude_none=True) for one in current.activities
        ],
        "pointer": pointer,
        "status": status,
        "captured_streams": [*current.captured_streams, *command.captured_streams],
    }
    state = FlowState(
        **body,
        version=VersionStamp(revision=command.expected_revision + 1, etag=etag(body)),
    )
    return await commit_command(
        context,
        command=_ADVANCE_COMMAND,
        new_state=_aggregate(
            _moved(
                study,
                plan,
                current,
                statuses=statuses,
                assigned=await levels() if levels is not None else {},
            ),
            state,
        ),
        result=_result(state, "advanced"),
        store=store,
        expected_revision=command.expected_revision,
    )


def _moved(
    study: Study,
    plan: VisitPlan,
    flow: FlowState,
    *,
    statuses: Sequence[str],
    assigned: Mapping[str, str],
) -> VisitPlan:
    """Return the plan with its progress moved on, and its parameters restated.

    Every identifier the plan holds was decided when it was materialized, and an
    advance never redecides one: it writes the statuses and re-digests the
    parameters, because a factor assigned since (a stratified one, waiting for its
    input) changes what the steps ahead will deliver.
    """
    occurrences = {
        index: Occurrence(
            key=one.key,
            activity_key=one.activity_key,
            kind=one.kind,
            within=dict(one.within),
        )
        for index, one in enumerate(flow.activities)
    }
    activities = [
        one.model_copy(
            update={
                "status": statuses[one.ordinal],
                "parameter_digest": parameter_digest(
                    study, occurrences[one.ordinal], assigned
                ),
            }
        )
        for one in plan.activities
    ]
    return plan.model_copy(
        update={
            "activities": activities,
            "plan_digest": _plan_digest(activities, plan.randomization_outcomes),
        }
    )
