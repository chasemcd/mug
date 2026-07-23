"""The identity command service: the enroll and launch handlers.

``enroll`` records one participant in a study. It is a create command: it checks
that the actor is a participant, assembles the ``Enrollment`` at its first
revision, and hands the new state and its result to the runtime spine, which
appends the event and commits.

``launch`` issues a ``LaunchTicket`` that admits a participant to a deployment.
The ticket is a public-handle token, not a versioned aggregate: it has no
revision and its identity is an opaque handle. So the handler reads the target
deployment through the store to confirm it exists, then issues the token through
the token spine. The receipt names the deployment and carries no version stamp.

The command carries the domain input. The runtime ``CommandContext`` carries the
authority a verified gateway derived: the minted identifiers and handle, the
principal, the target stream, and the clock instant.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from mug.identity.types import (
    Enrollment,
    ExternalIdentityLink,
    LaunchTicket,
    identity_schema,
)
from mug.kernel import (
    CommandReceipt,
    CommandTypeRef,
    DataHandlingRef,
    Digest,
    PublicHandle,
    SchemaRef,
    TypedObject,
    VersionStamp,
    etag,
)
from mug.kernel._base import KernelModel
from mug.kernel.ids import EnrollmentId, StudyId
from mug.kernel.refs import DeploymentRevisionRef, PositiveSafeInteger
from mug.runtime import (
    CommandContext,
    commit_command,
    issue_token_command,
    reject_command,
    result_ref,
)
from mug.storage import Store

_ENROLL_COMMAND = CommandTypeRef(name="enrollment.enroll", version=0)
_LAUNCH_COMMAND = CommandTypeRef(name="launch.issue", version=0)
_LINK_COMMAND = CommandTypeRef(name="identity.link", version=0)
_ENROLLMENT_RESULT = "mug.command-result.enrollment"
_LAUNCH_RESULT = "mug.command-result.launch"
_LINK_SCHEMA = "mug.api-03.external-identity-link"
_INSTANT = "%Y-%m-%dT%H:%M:%S.%fZ"


def _link_ref() -> SchemaRef:
    """Build the pinned schema reference for the external identity link record."""
    digest = Digest(algorithm="sha-256", hex=identity_schema().bundle_digest)
    return SchemaRef(name=_LINK_SCHEMA, version=0, digest=digest)


class EnrollCommand(KernelModel):
    """The domain input to enrol a participant in one study."""

    study_id: StudyId


def _result(name: str, data: dict[str, Any]) -> TypedObject:
    return TypedObject(schema=result_ref(name), data=data)


async def enroll(
    command: EnrollCommand,
    *,
    context: CommandContext,
    store: Store,
) -> CommandReceipt:
    """Enrol the acting participant in one study and return a durable receipt."""
    if context.principal.kind != "participant":
        return reject_command(
            context,
            command=_ENROLL_COMMAND,
            code="auth.forbidden",
            category="authorization",
            message="only a participant may enrol in a study",
            retry="never",
        )

    body: dict[str, Any] = {
        "enrollment_id": context.aggregate_id,
        "study_id": command.study_id,
        "principal": context.principal.model_dump(mode="json", exclude_none=True),
        "status": "active",
        "created_at": context.recorded_at,
    }
    enrollment = Enrollment(
        **body, version=VersionStamp(revision=1, etag=etag(body))
    )
    return await commit_command(
        context,
        command=_ENROLL_COMMAND,
        new_state=enrollment.model_dump(mode="json", exclude_none=True),
        result=_result(
            _ENROLLMENT_RESULT,
            {
                "outcome": "enrolled",
                "enrollment_id": enrollment.enrollment_id,
                "study_id": enrollment.study_id,
                "status": enrollment.status,
                "revision": enrollment.version.revision,
            },
        ),
        store=store,
    )


class LaunchCommand(KernelModel):
    """The domain input to issue a launch ticket for one deployment.

    ``ttl_seconds`` sets how long the ticket admits from the clock instant.
    """

    study_id: StudyId
    deployment: DeploymentRevisionRef
    ttl_seconds: PositiveSafeInteger


async def launch(
    command: LaunchCommand,
    *,
    context: CommandContext,
    store: Store,
) -> CommandReceipt:
    """Issue a launch ticket for a live deployment and return a receipt."""
    if store.load_aggregate(command.deployment.deployment_revision_id) is None:
        return reject_command(
            context,
            command=_LAUNCH_COMMAND,
            code="resource.not_found",
            category="not_found",
            message="the deployment does not exist",
            retry="never",
        )
    handle = context.public_handle
    if handle is None:
        return reject_command(
            context,
            command=_LAUNCH_COMMAND,
            code="protocol.invalid_envelope",
            category="protocol",
            message="a launch requires an issued ticket handle",
            retry="never",
        )

    issued = datetime.strptime(context.recorded_at, _INSTANT).replace(
        tzinfo=timezone.utc
    )
    expires_at = (issued + timedelta(seconds=command.ttl_seconds)).strftime(_INSTANT)
    ticket = LaunchTicket(
        ticket_handle=handle,
        study_id=command.study_id,
        deployment=command.deployment,
        issued_at=context.recorded_at,
        expires_at=expires_at,
    )
    return await issue_token_command(
        context,
        command=_LAUNCH_COMMAND,
        new_state=ticket.model_dump(mode="json", exclude_none=True),
        result=_result(
            _LAUNCH_RESULT,
            {
                "outcome": "issued",
                "ticket_handle": handle,
                "study_id": command.study_id,
                "expires_at": expires_at,
            },
        ),
        store=store,
    )


class LinkIdentityCommand(KernelModel):
    """The domain input to link one enrolment to an external subject handle.

    The handle is the blinded external subject id, never the raw external id;
    the boundary blinds the id before it mints the command, so no raw external
    id reaches this handler or the record it writes.
    """

    enrollment_id: EnrollmentId
    provider: Literal["prolific", "mturk", "oidc", "institution", "contact"]
    external_subject_handle: PublicHandle
    data_handling: DataHandlingRef


async def link_identity(
    command: LinkIdentityCommand,
    *,
    context: CommandContext,
    store: Store,
) -> CommandReceipt:
    """Record one external identity link and return a durable receipt.

    The link is a handle-keyed token, like a launch ticket: it has no revision,
    and its key is the blinded external subject handle. So a second link of the
    same external id (which blinds to the same handle) redeems to the same record,
    and a lookup by that handle recovers the enrolment. The gateway sets the
    token handle to the blinded value; the handler rejects a command that carries
    a handle other than the one the token is keyed by.
    """
    handle = context.public_handle
    if handle is None or handle != command.external_subject_handle:
        return reject_command(
            context,
            command=_LINK_COMMAND,
            code="protocol.invalid_envelope",
            category="protocol",
            message="a link requires its blinded subject handle as the token handle",
            retry="never",
        )
    link = ExternalIdentityLink(
        enrollment_id=command.enrollment_id,
        provider=command.provider,
        external_subject_handle=command.external_subject_handle,
        data_handling=command.data_handling,
    )
    return await issue_token_command(
        context,
        command=_LINK_COMMAND,
        new_state=link.model_dump(mode="json", exclude_none=True),
        result=TypedObject(
            schema=_link_ref(),
            data=link.model_dump(mode="json", exclude_none=True),
        ),
        store=store,
    )
