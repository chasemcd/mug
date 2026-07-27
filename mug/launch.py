"""Provision one genuine launch ticket so the demo can gate entry (API-03).

A participant reaches a study through an opaque, expiring ``LaunchTicket`` rather
than a client-supplied identity. This module mints one such ticket for the demo:
it seeds a minimal deployment aggregate, then issues a ticket against it through
the real ``launch`` handler and the token spine, so the handle is opaque and the
redemption path the participant hits is the real one.

The seeded deployment is a minimal stand-in for a full publish/deploy chain
(API-01/API-02), which the demo does not run. The ticket itself is genuine: it is
handle-keyed in the token store, it carries the study and deployment it admits to,
and it expires. The participant establish hook (``mug.participant``) redeems it,
enrolls the participant, starts the visit, and materializes the flow.

The module lives beside the other app-wiring seams, above the gateway. It composes
the identity and platform command families by reference; no inner layer imports it.
"""

from __future__ import annotations

from dataclasses import dataclass

from mug.gateway import Gateway
from mug.identity import LaunchCommand, launch
from mug.kernel import (
    DataHandlingRef,
    Digest,
    PrincipalRef,
    WireCommandEnvelope,
)
from mug.kernel.refs import DeploymentRevisionRef, StudyVersionRef
from mug.storage import Store

_RESEARCH = DataHandlingRef(privacy_labels=["research"])
_ENVELOPE_DIGEST = Digest(algorithm="sha-256", hex="0" * 64)
# A placeholder deployment manifest digest for the seeded stand-in deployment.
_STUB_DIGEST = Digest(algorithm="sha-256", hex="a" * 64)


@dataclass(frozen=True)
class LaunchProvision:
    """The result of provisioning one launch ticket: its handle and its target.

    ``ticket_handle`` is the opaque handle a participant presents to enter.
    ``study_id`` and ``deployment`` name what the ticket admits to; the establish
    hook reads them back from the redeemed ticket, so callers need only the handle.
    """

    ticket_handle: str
    study_id: str
    deployment: DeploymentRevisionRef


def _idem(gateway: Gateway) -> str:
    """Mint one well-formed idempotency key for a server-side command."""
    body = gateway.new_id("request").split("_", 1)[1].replace("-", "")
    return "idem_" + body[:21] + "A"


def _envelope(
    target_id: str, data: dict[str, object], idem: str
) -> WireCommandEnvelope:
    """Build a wire envelope for one server-side launch command."""
    schema = {
        "name": "mug.command-envelope",
        "version": 0,
        "digest": _ENVELOPE_DIGEST.model_dump(mode="json"),
    }
    return WireCommandEnvelope.model_validate(
        {
            "schema": schema,
            "protocol_version": "0.1.0",
            "command": {"name": "launch.issue", "version": 0},
            "request_id": "request_019b6000-0000-7000-8000-000000000001",
            "idempotency_key": idem,
            "target": {"id": target_id},
            "payload": {
                "schema": {
                    "name": "mug.edge.payload",
                    "version": 0,
                    "digest": _ENVELOPE_DIGEST.model_dump(mode="json"),
                },
                "data": data,
            },
        }
    )


async def _seed_deployment(store: Store, revision_id: str, gateway: Gateway) -> None:
    """Commit the deployment revision aggregate the launch gate reads.

    The ``launch`` handler gates on the revision aggregate being present. A revision
    is immutable, and since the study is published its identifier derives from the
    version -- so a restart finds the revision already there and seeds nothing. The
    mutable side of a deployment, which revision is current and whether it is live,
    is the ``Deployment`` record (``mug.platform.deployment``).
    """
    if store.load_aggregate(revision_id) is not None:
        return
    await store.commit(
        command_id=gateway.new_id("command"),
        idempotency_key=_idem(gateway),
        aggregate_id=revision_id,
        expected_revision=None,
        new_state={"deployment_revision_id": revision_id, "status": "active"},
        stream_events=[(gateway.new_id("stream"), gateway.new_id("event"))],
        durability_profile="platform.deploy",
    )


async def provision_launch_ticket(
    gateway: Gateway,
    store: Store,
    *,
    researcher: PrincipalRef,
    study_version: StudyVersionRef | None = None,
    ttl_seconds: int = 3600,
) -> LaunchProvision:
    """Seed a deployment and issue one genuine launch ticket for the study.

    It seeds the deployment the launch gate reads and issues the ticket through the
    real ``launch`` handler, so the returned handle is opaque and redeemable. The
    caller presents the handle in the launch link and gates realtime entry on it.

    ``study_version`` is the version the application published and is about to run
    (``mug.content.publish``), so the ticket, the deployment, and every visit behind
    them name the study that is actually running. With none it falls back to a minted
    identifier and a stub manifest digest, which is what a test that is not about
    publication wants -- and what the whole platform used to do.
    """
    published = study_version is not None
    study_id = study_version.study_id if study_version else gateway.new_id("study")
    version = study_version or StudyVersionRef(
        study_id=study_id,
        study_version_id=gateway.new_id("studyver"),
        version_number=1,
        manifest_digest=_STUB_DIGEST,
    )
    deployment = DeploymentRevisionRef(
        deployment_id=gateway.derived_id("deploy", f"deployment:{study_id}")
        if published
        else gateway.new_id("deploy"),
        deployment_revision_id=gateway.derived_id(
            "deployrev", f"deployrev:{version.study_version_id}"
        )
        if published
        else gateway.new_id("deployrev"),
        revision_number=1,
        study_version=version,
        manifest_digest=version.manifest_digest,
    )
    await _seed_deployment(store, deployment.deployment_revision_id, gateway)

    envelope = _envelope(
        deployment.deployment_revision_id,
        {"study_id": study_id, "deployment": deployment.model_dump(mode="json")},
        _idem(gateway),
    )
    context = gateway.mint(
        envelope, principal=researcher, data_handling=_RESEARCH, issue_handle=True
    )
    receipt = await launch(
        LaunchCommand(
            study_id=study_id, deployment=deployment, ttl_seconds=ttl_seconds
        ),
        context=context,
        store=store,
    )
    if receipt.outcome != "accepted" or context.public_handle is None:
        raise RuntimeError("the demo could not provision a launch ticket")
    return LaunchProvision(
        ticket_handle=context.public_handle,
        study_id=study_id,
        deployment=deployment,
    )
