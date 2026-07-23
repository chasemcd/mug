"""The participant flow service: materialize a plan, present, and advance.

This service runs the single-participant vertical without a game yet. A study is
an ordered list of activities (forms and content pages). ``materialize_flow``
opens the runtime flow for a visit at the first activity. ``advance_flow`` records
that the participant answered the active form, checks the answers against the form
specification, and moves the pointer to the next activity. ``present`` maps the
active activity to the payload a seat renders.

The study is compiled inline (no build worker yet). The frozen ``FormSpec`` and
``ContentSpec`` records are the authored content; ``FlowState`` is the runtime
progress record the store commits. Raw answers are not captured to the ledger yet;
the capture milestone wires that. The service validates answers, so a malformed
submission is refused before it advances the flow.
"""

from __future__ import annotations

import hashlib
from typing import Annotated, Any, Literal

from pydantic import Field

from mug.content.types import ContentBody, ContentSpec, FormField, FormSpec
from mug.kernel import (
    CommandReceipt,
    CommandTypeRef,
    TypedObject,
    VersionStamp,
    etag,
)
from mug.kernel._base import KernelModel
from mug.kernel.ids import StreamId, VisitId, VisitPlanId
from mug.kernel.refs import NonNegativeSafeInteger, PositiveSafeInteger
from mug.runtime import CommandContext, commit_command, reject_command, result_ref
from mug.storage import Store

_MATERIALIZE_COMMAND = CommandTypeRef(name="flow.materialize", version=0)
_ADVANCE_COMMAND = CommandTypeRef(name="flow.advance", version=0)
_RESULT_SCHEMA_NAME = "mug.command-result.visit-transition"

_AuthoringKey = Annotated[
    str, Field(pattern=r"^[a-z][a-z0-9]*(?:[-_.][a-z0-9]+)*$", max_length=128)
]
_ActivityKind = Literal["form", "content", "game"]


class Activity(KernelModel):
    """One authored study step: a key, a kind, and the content it presents."""

    key: _AuthoringKey
    kind: _ActivityKind
    form: FormSpec | None = None
    content: ContentSpec | None = None


class FlowActivity(KernelModel):
    """One activity in the runtime flow, with its progress status."""

    key: _AuthoringKey
    kind: _ActivityKind
    status: Literal["pending", "active", "completed"]


class FlowState(KernelModel):
    """The runtime progress of one visit through the study, with a pointer."""

    visitplan_id: VisitPlanId
    visit_id: VisitId
    activities: Annotated[list[FlowActivity], Field(min_length=1, max_length=256)]
    pointer: NonNegativeSafeInteger
    status: Literal["in-progress", "completed"]
    captured_streams: Annotated[list[StreamId], Field(max_length=1024)] = Field(
        default_factory=list
    )
    version: VersionStamp


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


# The inline demo study: consent, a short survey, the game, and a debrief.
_STUDY: tuple[Activity, ...] = (
    Activity(key="consent", kind="form", form=_consent_form()),
    Activity(key="survey", kind="form", form=_survey_form()),
    Activity(key="play", kind="game"),
    Activity(key="debrief", kind="content", content=_debrief_content()),
)
_BY_KEY: dict[str, Activity] = {activity.key: activity for activity in _STUDY}


def completion_code(visit_id: str) -> str:
    """Return the stable completion code for one visit.

    The code derives from the visit id, so the completed flow always claims the
    same code and a repeated completion is idempotent. The code carries no secret
    and no participant data, only a digest of the occurrence id.
    """
    body = visit_id.split("_", 1)[1] if "_" in visit_id else visit_id
    return "MUG-" + hashlib.sha256(body.encode()).hexdigest()[:10].upper()


def present(state: FlowState) -> dict[str, Any]:
    """Return the payload the seat renders for the flow's active activity."""
    if state.status == "completed":
        return {
            "kind": "complete",
            "completion_code": completion_code(state.visit_id),
        }
    active = state.activities[state.pointer]
    activity = _BY_KEY[active.key]
    if activity.kind == "form" and activity.form is not None:
        return {
            "kind": "form",
            "activity_key": activity.key,
            "form": activity.form.model_dump(mode="json", exclude_none=True),
        }
    if activity.kind == "content" and activity.content is not None:
        return {
            "kind": "content",
            "activity_key": activity.key,
            "content": activity.content.model_dump(mode="json", exclude_none=True),
        }
    return {"kind": "game", "activity_key": activity.key}


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


async def materialize_flow(
    command: MaterializeFlowCommand,
    *,
    context: CommandContext,
    store: Store,
) -> CommandReceipt:
    """Open the runtime flow for a visit at its first activity."""
    activities = [
        FlowActivity(
            key=activity.key,
            kind=activity.kind,
            status="active" if index == 0 else "pending",
        )
        for index, activity in enumerate(_STUDY)
    ]
    body: dict[str, Any] = {
        "visitplan_id": context.aggregate_id,
        "visit_id": command.visit_id,
        "activities": [item.model_dump(mode="json") for item in activities],
        "pointer": 0,
        "status": "in-progress",
        "captured_streams": [],
    }
    state = FlowState(**body, version=VersionStamp(revision=1, etag=etag(body)))
    return await commit_command(
        context,
        command=_MATERIALIZE_COMMAND,
        new_state=state.model_dump(mode="json", exclude_none=True),
        result=_result(state, "materialized"),
        store=store,
    )


async def advance_flow(
    command: AdvanceFlowCommand,
    *,
    context: CommandContext,
    store: Store,
) -> CommandReceipt:
    """Record the active form answers and advance the flow to the next activity."""
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
    current = FlowState.model_validate(raw)
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
    activity = _BY_KEY[active.key]
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

    activities = [item.model_dump(mode="json") for item in current.activities]
    activities[current.pointer]["status"] = "completed"
    pointer = current.pointer + 1
    status = "in-progress"
    if pointer >= len(activities):
        pointer = current.pointer
        status = "completed"
    else:
        activities[pointer]["status"] = "active"

    body: dict[str, Any] = {
        "visitplan_id": current.visitplan_id,
        "visit_id": current.visit_id,
        "activities": activities,
        "pointer": pointer,
        "status": status,
        "captured_streams": [*current.captured_streams, *command.captured_streams],
    }
    state = FlowState(
        **body,
        version=VersionStamp(
            revision=command.expected_revision + 1, etag=etag(body)
        ),
    )
    return await commit_command(
        context,
        command=_ADVANCE_COMMAND,
        new_state=state.model_dump(mode="json", exclude_none=True),
        result=_result(state, "advanced"),
        store=store,
        expected_revision=command.expected_revision,
    )
