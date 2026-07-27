"""Launch-ticket auth gates realtime entry and binds a durable enrollment (API-03).

With the launch gate on, a participant reaches the study only through an opaque
launch ticket. A connection with no ticket, an unknown ticket, or an expired
ticket is refused with a safe authentication error and no session. A valid ticket
enrolls the participant, starts the visit, and opens the flow at the first form. A
returning participant presents the stored return token instead of a ticket and
resumes the same pseudonymous enrollment, so a reconnection never mints a second
research identity.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi.testclient import TestClient

from mug.app import build_demo_app
from mug.client import RealtimeCommand
from mug.gateway import Gateway
from mug.identity import LaunchTicket
from mug.kernel import Digest, SchemaRef
from mug.kernel.refs import DeploymentRevisionRef, StudyVersionRef
from mug.storage import InMemoryStore

_A_DIGEST = Digest(algorithm="sha-256", hex="a" * 64)
_UUID = "019b6000-0000-7000-8000-0000000000{:02x}"


def _advance(answers: dict[str, Any], tag: str) -> dict[str, Any]:
    command = RealtimeCommand(
        command_id=f"command_019b6000-0000-7000-8000-00000000000{tag}",
        channel_key="flow.advance",
        intent_schema=SchemaRef(name="mug.demo.intent", version=0, digest=_A_DIGEST),
        payload_digest=_A_DIGEST,
        idempotency_key="idem_" + tag.ljust(21, "0") + "A",
        submitted_at="2026-07-21T00:00:00.000000Z",
    )
    return {
        "type": "command",
        "command": command.model_dump(mode="json", exclude_none=True),
        "payload": {"answers": answers},
    }


def _expired_ticket() -> LaunchTicket:
    """Build one launch ticket whose expiry is in the past."""
    return LaunchTicket(
        ticket_handle="handle_" + "E" * 21 + "A",
        study_id="study_" + _UUID.format(0x01),
        deployment=DeploymentRevisionRef(
            deployment_id="deploy_" + _UUID.format(0x20),
            deployment_revision_id="deployrev_" + _UUID.format(0x21),
            revision_number=1,
            study_version=StudyVersionRef(
                study_id="study_" + _UUID.format(0x01),
                study_version_id="studyver_" + _UUID.format(0x10),
                version_number=1,
                manifest_digest=_A_DIGEST,
            ),
            manifest_digest=_A_DIGEST,
        ),
        issued_at="2020-01-01T00:00:00.000000Z",
        expires_at="2020-01-01T01:00:00.000000Z",
    )


def test_a_connection_without_a_ticket_is_refused() -> None:
    """No ticket means no session: entry is refused with an authentication error."""
    app = build_demo_app(store=InMemoryStore(), gateway=Gateway(), require_launch=True)
    client = TestClient(app)
    with client.websocket_connect("/ws") as socket:
        refusal = socket.receive_json()

    assert refusal["type"] == "error"
    assert refusal["category"] == "authentication"


def test_an_unknown_ticket_is_refused() -> None:
    """A ticket handle that names no stored token is refused."""
    app = build_demo_app(store=InMemoryStore(), gateway=Gateway(), require_launch=True)
    client = TestClient(app)
    unknown = "handle_" + "Z" * 21 + "A"
    with client.websocket_connect(f"/ws?ticket={unknown}") as socket:
        refusal = socket.receive_json()

    assert refusal["type"] == "error"
    assert refusal["category"] == "authentication"


def test_an_expired_ticket_is_refused() -> None:
    """A ticket past its expiry is refused, even though it is a stored token."""
    store = InMemoryStore()
    ticket = _expired_ticket()
    asyncio.run(
        store.issue_token(
            command_id="command_" + _UUID.format(0x40),
            idempotency_key="idem_0123456789abcdefghijkQ",
            handle=ticket.ticket_handle,
            new_state=ticket.model_dump(mode="json", exclude_none=True),
            stream_events=[
                ("stream_" + _UUID.format(0x41), "event_" + _UUID.format(0x42))
            ],
        )
    )
    app = build_demo_app(store=store, gateway=Gateway(), require_launch=True)
    client = TestClient(app)
    with client.websocket_connect(f"/ws?ticket={ticket.ticket_handle}") as socket:
        refusal = socket.receive_json()

    assert refusal["type"] == "error"
    assert refusal["category"] == "authentication"


def test_a_valid_ticket_enrolls_and_opens_the_flow() -> None:
    """A valid ticket admits the participant and delivers the first form."""
    app = build_demo_app(store=InMemoryStore(), gateway=Gateway(), require_launch=True)
    ticket = app.state.launch_ticket
    assert isinstance(ticket, str)
    client = TestClient(app)
    with client.websocket_connect(f"/ws?ticket={ticket}") as socket:
        handshake = socket.receive_json()
        first = socket.receive_json()

    assert handshake["type"] == "handshake_ack"
    assert handshake["subject"].startswith("participant_")
    # The return token is a signed envelope, not the bare flow id, so a stolen or
    # guessed flow id can not resume the visit.
    resume_token = handshake["resume_token"]
    assert isinstance(resume_token, str)
    assert "." in resume_token and not resume_token.startswith("visitplan_")
    assert first["delivery"]["form"]["form_key"] == "consent"


def test_a_forged_return_token_is_refused() -> None:
    """A gated reconnection with an unsigned return token is refused, not resumed."""
    app = build_demo_app(store=InMemoryStore(), gateway=Gateway(), require_launch=True)
    client = TestClient(app)
    forged = "eyJmbG93X2lkIjoieCJ9.not-a-valid-signature"
    with client.websocket_connect(f"/ws?resume_token={forged}") as socket:
        refusal = socket.receive_json()

    assert refusal["type"] == "error"
    assert refusal["category"] == "authentication"


def test_a_tampered_return_token_is_refused() -> None:
    """A return token whose signature is altered no longer resumes the visit."""
    app = build_demo_app(store=InMemoryStore(), gateway=Gateway(), require_launch=True)
    ticket = app.state.launch_ticket
    client = TestClient(app)

    with client.websocket_connect(f"/ws?ticket={ticket}") as socket:
        token = socket.receive_json()["resume_token"]
        assert socket.receive_json()["delivery"]["form"]["form_key"] == "consent"

    # Flip the last signature character: the mac no longer matches the claims.
    tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
    with client.websocket_connect(f"/ws?resume_token={tampered}") as socket:
        refusal = socket.receive_json()

    assert refusal["type"] == "error"
    assert refusal["category"] == "authentication"


def test_a_return_token_resumes_the_same_enrollment() -> None:
    """A reconnection presents the return token, not the ticket, and keeps identity."""
    store = InMemoryStore()
    app = build_demo_app(store=store, gateway=Gateway(), require_launch=True)
    ticket = app.state.launch_ticket
    client = TestClient(app)

    with client.websocket_connect(f"/ws?ticket={ticket}") as socket:
        handshake = socket.receive_json()
        subject = handshake["subject"]
        token = handshake["resume_token"]
        assert socket.receive_json()["delivery"]["form"]["form_key"] == "consent"
        socket.send_json(_advance({"agree": "yes"}, tag="1"))
        assert socket.receive_json()["ack"]["ack_kind"] == "parsed"
        assert socket.receive_json()["ack"]["ack_kind"] == "accepted"
        assert socket.receive_json()["delivery"]["form"]["form_key"] == "survey"

    # Reconnect with only the return token: the same participant resumes the survey.
    with client.websocket_connect(f"/ws?resume_token={token}") as socket:
        resumed = socket.receive_json()
        assert resumed["resume_token"] == token
        assert resumed["subject"] == subject
        assert socket.receive_json()["delivery"]["form"]["form_key"] == "survey"
