"""A deployment has a current state, and a client pins the one it accepted.

`platform.deploy` committed a `DeploymentRevision` -- immutable, correct, and only
half the model. The frozen `Deployment` is the mutable pointer beside it: the
revision being served and whether the deployment is live. Nothing wrote one, so
nothing recorded which revision was current, there was no way to pause recruitment,
and the launch gate hand-rolled a stand-in dict. On the client side nothing pinned
the revision a build was made for, so a stale client ran on quietly against a newer
deployment.

These tests drive the real application: the deployment it opens, the disposition an
operator sets, the door a stopped deployment closes, and the refusal a client meets
when it pins a revision that is not the one being served.
"""

from __future__ import annotations

from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from mug.app import build_study_app, derived_idempotency_key
from mug.content import Page, Study
from mug.gateway import Gateway
from mug.kernel import DataHandlingRef, Digest, PrincipalRef, WireCommandEnvelope
from mug.kernel.refs import DeploymentRevisionRef
from mug.platform.deployment import (
    is_live,
    open_deployment,
    point_deployment,
    recorded_deployment,
    set_disposition,
)
from mug.storage import InMemoryStore

_SECRET = b"a shared deployment secret"
_ZERO = Digest(algorithm="sha-256", hex="0" * 64)


def _study() -> Study:
    return Study(Page("intro", "# Hello"), Page("debrief", "# Thank you"))


def _app(store: InMemoryStore, gateway: Gateway | None = None) -> TestClient:
    return TestClient(
        build_study_app(
            study=_study(),
            store=store,
            gateway=gateway or Gateway(secret=_SECRET),
            require_launch=True,
        )
    )


def _deployment_id(client: TestClient) -> str:
    revision = cast(
        "DeploymentRevisionRef",
        getattr(client.app, "state").deployment,  # noqa: B009
    )
    return revision.deployment_id


def _ticket(client: TestClient) -> str:
    return cast("str", getattr(client.app, "state").launch_ticket)  # noqa: B009


def _context(gateway: Gateway, target: str, seed: str) -> Any:
    """Mint one operator context on a deployment's stream."""
    zero = _ZERO.model_dump(mode="json")
    envelope = WireCommandEnvelope.model_validate(
        {
            "schema": {"name": "mug.command-envelope", "version": 0, "digest": zero},
            "protocol_version": "0.1.0",
            "command": {"name": "deployment.set-disposition", "version": 0},
            "request_id": "request_019b6000-0000-7000-8000-000000000001",
            "idempotency_key": derived_idempotency_key(gateway, seed),
            "target": {"id": target},
            "payload": {
                "schema": {"name": "mug.edge.payload", "version": 0, "digest": zero},
                "data": {},
            },
        }
    )
    return gateway.mint(
        envelope,
        principal=PrincipalRef(kind="researcher", id=gateway.new_id("researcher")),
        data_handling=DataHandlingRef(privacy_labels=["research"]),
    )


# -- the pointer -----------------------------------------------------------------


def test_a_running_application_records_the_deployment_it_serves() -> None:
    """The revision alone never said which one was current. Now something does."""
    store = InMemoryStore()
    client = _app(store)

    deployment = recorded_deployment(store, _deployment_id(client))
    assert deployment is not None
    assert deployment.disposition == "live"
    revision = cast(
        "DeploymentRevisionRef",
        getattr(client.app, "state").deployment,  # noqa: B009
    )
    assert (
        deployment.current_revision.deployment_revision_id
        == revision.deployment_revision_id
    )
    # And it names the study version that was published, not a stub.
    assert deployment.current_revision.manifest_digest.hex != "a" * 64


async def test_a_stopped_deployment_stays_stopped_across_a_restart() -> None:
    """A disposition that a restart undoes is not a disposition."""
    store = InMemoryStore()
    gateway = Gateway(secret=_SECRET)
    deployment_id = _deployment_id(_app(store, gateway))

    await set_disposition(
        deployment_id=deployment_id,
        disposition="stopped",
        context=_context(gateway, deployment_id, "stop"),
        store=store,
    )
    assert is_live(store, deployment_id) is False

    # The application starts again over the same store.
    _app(store, Gateway(secret=_SECRET))
    assert is_live(store, deployment_id) is False


async def test_a_stopped_deployment_admits_no_participant() -> None:
    """Pausing recruitment is the whole point of the disposition."""
    store = InMemoryStore()
    gateway = Gateway(secret=_SECRET)
    client = _app(store, gateway)
    ticket = _ticket(client)
    deployment_id = _deployment_id(client)

    with client.websocket_connect(f"/ws?ticket={ticket}") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"

    await set_disposition(
        deployment_id=deployment_id,
        disposition="stopped",
        context=_context(gateway, deployment_id, "stop"),
        store=store,
    )

    with client.websocket_connect(f"/ws?ticket={ticket}") as socket:
        refusal = socket.receive_json()
    assert refusal["type"] == "error"
    assert "not accepting participants" in refusal["message"]


async def test_starting_a_stopped_deployment_serves_the_same_revision() -> None:
    """Stopping is not deleting: what it was serving is what it serves again."""
    store = InMemoryStore()
    gateway = Gateway(secret=_SECRET)
    client = _app(store, gateway)
    deployment_id = _deployment_id(client)
    before = recorded_deployment(store, deployment_id)
    assert before is not None

    for disposition, seed in (("stopped", "stop"), ("live", "start")):
        await set_disposition(
            deployment_id=deployment_id,
            disposition=cast("Any", disposition),
            context=_context(gateway, deployment_id, seed),
            store=store,
        )

    after = recorded_deployment(store, deployment_id)
    assert after is not None
    assert after.disposition == "live"
    assert after.current_revision == before.current_revision

    with client.websocket_connect(f"/ws?ticket={_ticket(client)}") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"


async def test_pointing_a_deployment_moves_it_and_keeps_its_disposition() -> None:
    """A redeploy and a rollback are one move, and neither restarts a stopped study."""
    store = InMemoryStore()
    gateway = Gateway(secret=_SECRET)
    client = _app(store, gateway)
    deployment_id = _deployment_id(client)
    first = recorded_deployment(store, deployment_id)
    assert first is not None

    await set_disposition(
        deployment_id=deployment_id,
        disposition="stopped",
        context=_context(gateway, deployment_id, "stop"),
        store=store,
    )
    next_revision = first.current_revision.model_copy(
        update={
            "deployment_revision_id": gateway.new_id("deployrev"),
            "revision_number": 2,
        }
    )
    await point_deployment(
        revision=next_revision,
        context=_context(gateway, deployment_id, "point"),
        store=store,
    )

    moved = recorded_deployment(store, deployment_id)
    assert moved is not None
    assert moved.current_revision.revision_number == 2
    assert moved.disposition == "stopped", "a redeploy quietly restarted the study"


async def test_opening_a_deployment_twice_keeps_the_first() -> None:
    """A restart must not reopen a deployment an operator stopped."""
    store = InMemoryStore()
    gateway = Gateway(secret=_SECRET)
    client = _app(store, gateway)
    deployment_id = _deployment_id(client)
    revision = cast(
        "DeploymentRevisionRef",
        getattr(client.app, "state").deployment,  # noqa: B009
    )

    await set_disposition(
        deployment_id=deployment_id,
        disposition="stopped",
        context=_context(gateway, deployment_id, "stop"),
        store=store,
    )
    _, again = await open_deployment(
        study_id=revision.study_version.study_id,
        revision=revision,
        context=_context(gateway, deployment_id, "reopen"),
        store=store,
    )
    assert again is not None
    assert again.disposition == "stopped"


# -- what the client pins --------------------------------------------------------


def test_the_handshake_tells_the_client_which_revision_it_is_running_against() -> None:
    """A client cannot pin what it was never told."""
    store = InMemoryStore()
    client = _app(store)
    with client.websocket_connect(f"/ws?ticket={_ticket(client)}") as socket:
        handshake = socket.receive_json()

    revision = cast(
        "DeploymentRevisionRef",
        getattr(client.app, "state").deployment,  # noqa: B009
    )
    assert (
        handshake["deployment"]["deployment_revision_id"]
        == revision.deployment_revision_id
    )


def test_a_client_built_for_a_superseded_revision_is_refused() -> None:
    """A stale build must not run on quietly against a study it was not built for."""
    store = InMemoryStore()
    client = _app(store)
    with client.websocket_connect(f"/ws?ticket={_ticket(client)}") as socket:
        socket.receive_json()
        socket.send_json(
            {
                "type": "client_handshake",
                "accepted_deployment": {
                    "deployment_id": "deploy_019b6000-0000-7000-8000-000000000001",
                    "deployment_revision_id": (
                        "deployrev_019b6000-0000-7000-8000-0000000000ff"
                    ),
                    "revision_number": 1,
                },
            }
        )
        refusal = _next_error(socket)

    assert refusal["type"] == "error"
    assert "not current" in refusal["message"]


def test_a_client_that_pins_the_current_revision_continues() -> None:
    """The check refuses a stale build and nothing else."""
    store = InMemoryStore()
    client = _app(store)
    with client.websocket_connect(f"/ws?ticket={_ticket(client)}") as socket:
        handshake = socket.receive_json()
        socket.send_json(
            {
                "type": "client_handshake",
                "accepted_deployment": handshake["deployment"],
            }
        )
        delivery = socket.receive_json()

    assert delivery["type"] == "delivery"
    assert delivery["delivery"]["activity_key"] == "intro"


def _next_error(socket: Any) -> dict[str, Any]:
    """Read frames until the refusal.

    The server speaks first, so the opening activity is already on its way when the
    client pins what it accepted. The refusal follows it.
    """
    for _ in range(8):
        frame = cast("dict[str, Any]", socket.receive_json())
        if frame.get("type") == "error":
            return frame
    raise AssertionError("the connection was not refused")


# -- the operator's verb ---------------------------------------------------------


async def test_the_command_line_stops_and_starts_a_deployment() -> None:
    """``mug stop`` was an honest refusal; it is now the operation it named."""
    from mug.cli.commands import CliError, run_stop
    from mug.cli.session import CliSession, DurableStore

    store = InMemoryStore()
    client = _app(store)
    deployment_id = _deployment_id(client)
    session = CliSession.open(
        store=cast("DurableStore", store), gateway=Gateway(secret=_SECRET)
    )

    stopped = await run_stop(session, deployment_id)
    assert stopped.disposition == "stopped"
    assert is_live(store, deployment_id) is False

    started = await run_stop(session, deployment_id, start=True)
    assert started.disposition == "live"
    assert is_live(store, deployment_id) is True

    with pytest.raises(CliError):
        await run_stop(session, "deploy_019b6000-0000-7000-8000-0000000000aa")


def test_an_ungated_run_is_live_without_any_deployment_record() -> None:
    """An open demo deploys nothing, and refusing it would take every such run down."""
    store = InMemoryStore()
    client = TestClient(
        build_study_app(study=_study(), store=store, gateway=Gateway(secret=_SECRET))
    )
    assert is_live(store, "deploy_019b6000-0000-7000-8000-000000000001") is True
    with client.websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
