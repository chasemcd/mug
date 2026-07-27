"""The platform command service: the deploy handler.

``deploy`` checks the deploy bindings against the pinned requirement. When a gap
remains it rejects with an unsatisfied ``SatisfactionReport`` and no effect. When
none remains it mints an immutable ``DeploymentRevision``, pins a satisfied
report, and hands the state and result to the runtime spine, which appends the
event and commits.
"""

from __future__ import annotations

from mug.kernel import (
    ArtifactRef,
    CommandReceipt,
    CommandTypeRef,
    DataHandlingRef,
    TypedObject,
    compute_digest,
)
from mug.kernel._base import KernelModel
from mug.kernel.ids import DeploymentId
from mug.kernel.refs import (
    DeploymentRevisionRef,
    PositiveSafeInteger,
    StudyVersionRef,
)
from mug.platform.deploy import requirement_gaps
from mug.platform.deployment import (
    open_deployment,
    point_deployment,
    recorded_deployment,
)
from mug.platform.types import (
    ClientBuildBinding,
    DeploymentRequirement,
    DeploymentRevision,
    EndpointBinding,
    ExecutionBinding,
    ProviderBinding,
    Region,
    SatisfactionReport,
    SecretBinding,
)
from mug.runtime import CommandContext, commit_command, reject_command
from mug.storage import Store

_DEPLOY_COMMAND = CommandTypeRef(name="platform.deploy", version=0)


def _report_object(report: SatisfactionReport) -> TypedObject:
    # The satisfaction report is a frozen api-02 record; it carries its own
    # schema, so the command result reuses that reference.
    return TypedObject(
        schema=report.schema,
        data=report.model_dump(mode="json", exclude_none=True),
    )


class DeployCommand(KernelModel):
    """The domain input to deploy one study version behind one revision."""

    deployment_id: DeploymentId
    revision_number: PositiveSafeInteger
    study_version: StudyVersionRef
    requirement: DeploymentRequirement
    server_build: ArtifactRef
    client_builds: list[ClientBuildBinding]
    execution_bindings: list[ExecutionBinding]
    provider_bindings: list[ProviderBinding] | None = None
    secret_bindings: list[SecretBinding]
    region: Region
    endpoints: list[EndpointBinding]
    data_handling: DataHandlingRef


async def deploy(
    command: DeployCommand,
    *,
    context: CommandContext,
    store: Store,
    deployment_context: CommandContext | None = None,
) -> CommandReceipt:
    """Deploy one study version and return a durable receipt.

    ``deployment_context`` is what makes the deploy complete. A revision is immutable
    and says nothing about whether it is the one being served; the ``Deployment``
    beside it is the mutable pointer that does (``mug.platform.deployment``). With a
    context for it, an accepted deploy also opens that deployment at this revision or
    moves an existing one to it -- a redeploy and a rollback being the same move.
    Without one, only the revision is recorded, which is what a test that is not
    about the pointer wants.
    """
    requirement_digest = compute_digest(
        command.requirement.model_dump(mode="json", exclude_none=True)
    )
    unbound, missing, region_gaps = requirement_gaps(
        command.requirement,
        region=command.region,
        secret_bindings=command.secret_bindings,
        execution_bindings=command.execution_bindings,
    )
    if unbound or missing or region_gaps:
        report = SatisfactionReport(
            study_version=command.study_version,
            requirement_digest=requirement_digest,
            satisfied=False,
            unbound_secret_requirements=unbound,
            missing_execution_slots=missing,
            region_gaps=region_gaps,
        )
        return reject_command(
            context,
            command=_DEPLOY_COMMAND,
            code="command.state_conflict",
            category="conflict",
            message="the deploy bindings do not satisfy the requirement",
            retry="refresh_then_new_command",
            details=_report_object(report),
        )

    revision = DeploymentRevision(
        deployment_id=command.deployment_id,
        deployment_revision_id=context.aggregate_id,
        revision_number=command.revision_number,
        study_version=command.study_version,
        requirement_digest=requirement_digest,
        server_build=command.server_build,
        client_builds=command.client_builds,
        execution_bindings=command.execution_bindings,
        provider_bindings=command.provider_bindings,
        secret_bindings=command.secret_bindings,
        region=command.region,
        endpoints=command.endpoints,
        data_handling=command.data_handling,
    )
    state = revision.model_dump(mode="json", exclude_none=True)
    revision_ref = DeploymentRevisionRef(
        deployment_id=command.deployment_id,
        deployment_revision_id=context.aggregate_id,
        revision_number=command.revision_number,
        study_version=command.study_version,
        manifest_digest=compute_digest(state),
    )
    report = SatisfactionReport(
        deployment_revision=revision_ref,
        study_version=command.study_version,
        requirement_digest=requirement_digest,
        satisfied=True,
        unbound_secret_requirements=[],
        missing_execution_slots=[],
        region_gaps=[],
    )
    receipt = await commit_command(
        context,
        command=_DEPLOY_COMMAND,
        new_state=state,
        result=_report_object(report),
        store=store,
    )
    if receipt.outcome == "accepted" and deployment_context is not None:
        await _point_at(
            revision_ref,
            study_id=command.study_version.study_id,
            context=deployment_context,
            store=store,
        )
    return receipt


async def _point_at(
    revision: DeploymentRevisionRef,
    *,
    study_id: str,
    context: CommandContext,
    store: Store,
) -> None:
    """Make one accepted revision the deployment's current one.

    A first deploy opens the deployment; a later one moves the pointer. The
    disposition is never touched here, so redeploying a stopped deployment leaves it
    stopped -- starting it again is an operator's decision, not a side effect of a
    build.
    """
    if recorded_deployment(store, revision.deployment_id) is None:
        await open_deployment(
            study_id=study_id, revision=revision, context=context, store=store
        )
        return
    await point_deployment(revision=revision, context=context, store=store)
