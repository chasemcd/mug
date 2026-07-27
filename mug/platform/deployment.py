"""A deployment's current state: which revision is live, and whether it is.

``platform.deploy`` commits a ``DeploymentRevision`` -- immutable, correct, and only
half the model. The frozen ``Deployment`` (``mug.api-02.deployment``) is the mutable
pointer beside it: the study it deploys, the revision it currently serves, and its
disposition. Nothing wrote one, so nothing recorded which revision a deployment was
serving and there was no way to stop one; the launch gate hand-rolled
``{"deployment_revision_id": ..., "status": "active"}`` as a stand-in for exactly
this record, and said so in a comment.

This module is the pointer. It has three operations and one rule between them:

- ``open_deployment`` records a deployment at its first revision, live;
- ``point_deployment`` moves a live deployment to another revision (a redeploy, or
  a rollback to a revision that already exists -- both are the same move);
- ``set_disposition`` stops a deployment, or starts a stopped one again.

The rule is that a stopped deployment admits no new participant. Stopping is not
deleting: the revisions stay, the visits already running are not touched, and
starting it again serves the same revision it was serving. That is what a
researcher means by pausing recruitment, and it is what the disposition is for.

The projection a client receives (``ClientDeploymentProjection``) is built from the
same record, so what a browser is told about the deployment and what the operator
reads are the same fact rather than two that can drift.
"""

from __future__ import annotations

from typing import Any, cast

from mug.kernel import CommandReceipt, CommandTypeRef, TypedObject
from mug.kernel.refs import DeploymentRevisionRef
from mug.platform.types import (
    ClientDeploymentProjection,
    Deployment,
    DeploymentDisposition,
    ParticipantEndpoint,
)
from mug.runtime import CommandContext, commit_command, reject_command
from mug.storage import Store

_OPEN = CommandTypeRef(name="deployment.open", version=0)
_POINT = CommandTypeRef(name="deployment.point", version=0)
_DISPOSE = CommandTypeRef(name="deployment.set-disposition", version=0)


def recorded_deployment(store: Store, deployment_id: str) -> Deployment | None:
    """Return the deployment this identifier records, or None when none is."""
    state = store.load_aggregate(deployment_id)
    if not isinstance(state, dict):
        return None
    try:
        return Deployment.model_validate(state)
    except ValueError:
        return None


def is_live(store: Store, deployment_id: str) -> bool:
    """Report whether this deployment currently admits participants.

    A deployment nothing recorded is live: an ungated demo runs without ever
    deploying, and refusing it would take every such run down. What this refuses is
    a deployment that was recorded and then **stopped**, which is a decision someone
    made rather than a state nobody wrote.
    """
    found = recorded_deployment(store, deployment_id)
    return found is None or found.disposition == "live"


async def open_deployment(
    *,
    study_id: str,
    revision: DeploymentRevisionRef,
    context: CommandContext,
    store: Store,
) -> tuple[CommandReceipt, Deployment | None]:
    """Record one deployment at its first revision, live.

    A deployment that is already recorded is left alone and returned as it stands,
    so a restart does not reopen a deployment an operator stopped. That is the whole
    point of a durable disposition: it must survive the process that set it.
    """
    existing = recorded_deployment(store, revision.deployment_id)
    if existing is not None:
        return _replayed(context), existing
    deployment = Deployment(
        deployment_id=revision.deployment_id,
        study_id=study_id,
        disposition="live",
        current_revision=revision,
    )
    receipt = await commit_command(
        context,
        command=_OPEN,
        new_state=_state(deployment),
        result=_typed(deployment),
        store=store,
    )
    return receipt, (deployment if receipt.outcome == "accepted" else None)


async def point_deployment(
    *,
    revision: DeploymentRevisionRef,
    context: CommandContext,
    store: Store,
) -> tuple[CommandReceipt, Deployment | None]:
    """Point a recorded deployment at another revision, keeping its disposition.

    A redeploy and a rollback are the same move: both name a revision and make it
    the current one. The disposition is untouched, so redeploying a stopped
    deployment does not quietly start it again.
    """
    existing = recorded_deployment(store, revision.deployment_id)
    if existing is None:
        return _refuse(context, _POINT, "no such deployment"), None
    moved = existing.model_copy(update={"current_revision": revision})
    receipt = await commit_command(
        context,
        command=_POINT,
        new_state=_state(moved),
        result=_typed(moved),
        store=store,
        expected_revision=store.revision_of(revision.deployment_id),
    )
    return receipt, (moved if receipt.outcome == "accepted" else None)


async def set_disposition(
    *,
    deployment_id: str,
    disposition: DeploymentDisposition,
    context: CommandContext,
    store: Store,
) -> tuple[CommandReceipt, Deployment | None]:
    """Stop a deployment, or start a stopped one again.

    Setting the disposition it already has is a no-op that reports the record as it
    stands, so stopping twice is not an error and a retry after a lost receipt costs
    nothing.
    """
    existing = recorded_deployment(store, deployment_id)
    if existing is None:
        return _refuse(context, _DISPOSE, "no such deployment"), None
    if existing.disposition == disposition:
        return _replayed(context), existing
    changed = existing.model_copy(update={"disposition": disposition})
    receipt = await commit_command(
        context,
        command=_DISPOSE,
        new_state=_state(changed),
        result=_typed(changed),
        store=store,
        expected_revision=store.revision_of(deployment_id),
    )
    return receipt, (changed if receipt.outcome == "accepted" else None)


def client_projection(
    deployment: Deployment,
    *,
    region: str,
    endpoints: list[ParticipantEndpoint],
    protocol_capabilities: list[str],
) -> ClientDeploymentProjection:
    """Build what a participant's client is told about this deployment.

    It is a positive allowlist: the revision the client is running against, where to
    reach it, and which protocol capabilities are in play. The disposition is not in
    it -- a client that is connected is by definition running against a live
    deployment, and a stopped one is refused at the door rather than described.
    """
    return ClientDeploymentProjection(
        deployment=deployment.current_revision,
        region=cast("Any", region),
        endpoints=endpoints,
        protocol_capabilities=protocol_capabilities,
    )


def _state(deployment: Deployment) -> dict[str, Any]:
    """Dump one deployment to its canonical persisted form."""
    return deployment.model_dump(mode="json", exclude_none=True)


def _typed(deployment: Deployment) -> TypedObject:
    """Wrap one deployment as the command result that carries its schema."""
    return TypedObject(schema=deployment.schema, data=_state(deployment))


def _replayed(context: CommandContext) -> CommandReceipt:
    """Report that the recorded state already satisfies the command."""
    return reject_command(
        context,
        command=_DISPOSE,
        code="command.replayed",
        category="conflict",
        message="the deployment already records this state",
        retry="never",
    )


def _refuse(
    context: CommandContext, command: CommandTypeRef, message: str
) -> CommandReceipt:
    """Refuse a command that names a deployment nothing recorded."""
    return reject_command(
        context,
        command=command,
        code="resource.not_found",
        category="not_found",
        message=message,
        retry="never",
    )


__all__ = [
    "client_projection",
    "is_live",
    "open_deployment",
    "point_deployment",
    "recorded_deployment",
    "set_disposition",
]
