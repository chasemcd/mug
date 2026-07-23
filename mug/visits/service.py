"""The visits command service: the start and advance handlers.

``start_visit`` opens one visit for an enrolled participant. It is the first
command that reads ANOTHER aggregate to gate itself: it loads the enrollment from
the store and refuses when that enrollment is absent or not active. A sibling
family owns the enrollment, so the read goes through the shared store and inspects
the state structurally; the visits family never imports the identity model.

``advance_visit`` moves one visit to a new lifecycle status. It is the first
update command: it reads the current visit, checks the transition, stamps the
next revision, and hands the new state and its result to the runtime spine with
the revision the caller last saw. The spine commits at the next revision when
that revision is still current, or rejects on a stale one.

The command carries the domain input. The runtime ``CommandContext`` carries the
authority a verified gateway derived: the minted identifiers, the principal, the
target stream, and the clock instant.
"""

from __future__ import annotations

from typing import Any, Literal

from mug.kernel import (
    CommandReceipt,
    CommandTypeRef,
    TypedObject,
    VersionStamp,
    etag,
)
from mug.kernel._base import KernelModel
from mug.kernel.ids import EnrollmentId, StudyId
from mug.kernel.refs import (
    DeploymentRevisionRef,
    PositiveSafeInteger,
    StudyVersionRef,
)
from mug.runtime import CommandContext, commit_command, reject_command, result_ref
from mug.storage import Store
from mug.visits.lifecycle import transition_refusal
from mug.visits.types import Visit

_START_COMMAND = CommandTypeRef(name="visit.start", version=0)
_ADVANCE_COMMAND = CommandTypeRef(name="visit.advance", version=0)
_RESULT_SCHEMA_NAME = "mug.command-result.visit-transition"

_VisitStatus = Literal["created", "in-progress", "completed", "abandoned"]


class StartVisitCommand(KernelModel):
    """The domain input to open one visit for an enrolled participant."""

    enrollment_id: EnrollmentId
    study_id: StudyId
    study_version: StudyVersionRef
    deployment: DeploymentRevisionRef


class AdvanceVisitCommand(KernelModel):
    """The domain input to move one visit to a new status.

    ``expected_revision`` is the revision the caller last saw; the commit rejects
    if the visit has moved on since.
    """

    target_status: _VisitStatus
    expected_revision: PositiveSafeInteger


def _result_object(visit: Visit, outcome: str) -> TypedObject:
    return TypedObject(
        schema=result_ref(_RESULT_SCHEMA_NAME),
        data={
            "outcome": outcome,
            "visit_id": visit.visit_id,
            "status": visit.status,
            "revision": visit.version.revision,
        },
    )


async def start_visit(
    command: StartVisitCommand,
    *,
    context: CommandContext,
    store: Store,
) -> CommandReceipt:
    """Open one visit for an active enrollment and return a durable receipt."""
    enrollment = store.load_aggregate(command.enrollment_id)
    if enrollment is None:
        return reject_command(
            context,
            command=_START_COMMAND,
            code="resource.not_found",
            category="not_found",
            message="the enrollment does not exist",
            retry="never",
        )
    if enrollment.get("status") != "active":
        return reject_command(
            context,
            command=_START_COMMAND,
            code="command.state_conflict",
            category="conflict",
            message="the enrollment is not active",
            retry="never",
        )

    body: dict[str, Any] = {
        "visit_id": context.aggregate_id,
        "enrollment_id": command.enrollment_id,
        "study_id": command.study_id,
        "study_version": command.study_version.model_dump(
            mode="json", exclude_none=True
        ),
        "deployment": command.deployment.model_dump(mode="json", exclude_none=True),
        "status": "created",
    }
    visit = Visit(**body, version=VersionStamp(revision=1, etag=etag(body)))
    return await commit_command(
        context,
        command=_START_COMMAND,
        new_state=visit.model_dump(mode="json", exclude_none=True),
        result=_result_object(visit, "started"),
        store=store,
    )


async def advance_visit(
    command: AdvanceVisitCommand,
    *,
    context: CommandContext,
    store: Store,
) -> CommandReceipt:
    """Advance one visit's status and return a durable receipt."""
    raw = store.load_aggregate(context.aggregate_id)
    if raw is None:
        return reject_command(
            context,
            command=_ADVANCE_COMMAND,
            code="resource.not_found",
            category="not_found",
            message="the visit does not exist",
            retry="never",
        )
    current = Visit.model_validate(raw)
    if transition_refusal(current.status, command.target_status) is not None:
        return reject_command(
            context,
            command=_ADVANCE_COMMAND,
            code="command.state_conflict",
            category="conflict",
            message="the visit does not allow this status transition",
            retry="never",
        )

    body = current.model_dump(mode="json", exclude={"schema", "version"})
    body["status"] = command.target_status
    visit = Visit(
        **body,
        version=VersionStamp(
            revision=command.expected_revision + 1, etag=etag(body)
        ),
    )
    return await commit_command(
        context,
        command=_ADVANCE_COMMAND,
        new_state=visit.model_dump(mode="json", exclude_none=True),
        result=_result_object(visit, "advanced"),
        store=store,
        expected_revision=command.expected_revision,
    )
