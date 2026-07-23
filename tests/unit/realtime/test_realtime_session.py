"""The realtime transport serves a session: handshake, acks, and safe errors.

These tests drive ``serve_session`` through FastAPI's test client. A small app
mounts one websocket route over an injected dispatch seam, so the transport is
tested apart from the participant handlers a later milestone wires behind it. The
handshake resolves a principal and reports the resume cursor; a command is acked
``parsed`` then ``accepted`` with its stream position; an unowned or malformed
command answers a safe error.
"""

from __future__ import annotations

import asyncio

from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient

from mug.client import RealtimeCommand
from mug.gateway import Gateway
from mug.kernel import (
    CommandReceipt,
    CommandTypeRef,
    DataHandlingRef,
    Digest,
    PrincipalRef,
    SchemaRef,
    TypedObject,
    WireCommandEnvelope,
)
from mug.realtime import RealtimeDispatch, Session, serve_session
from mug.runtime import commit_command, reject_command, result_ref
from mug.storage import InMemoryStore

_PARTICIPANT = PrincipalRef(
    kind="participant", id="participant_019b6000-0000-7000-8000-0000000000aa"
)
_RESEARCH = DataHandlingRef(privacy_labels=["research"])
_A_DIGEST = Digest(algorithm="sha-256", hex="a" * 64)


def _app(dispatch: RealtimeDispatch) -> TestClient:
    """Mount one websocket route over the dispatch seam and a fixed principal."""
    app = FastAPI()

    def resolve(_websocket: WebSocket) -> PrincipalRef:
        return _PARTICIPANT

    @app.websocket("/ws")
    async def ws(websocket: WebSocket) -> None:  # pyright: ignore[reportUnusedFunction]
        await serve_session(
            websocket,
            resolve_principal=resolve,
            dispatch=dispatch,
            protocol_version="0.1.0",
        )

    return TestClient(app)


def _command_frame() -> dict[str, object]:
    """Build one valid realtime command frame with a small payload."""
    command = RealtimeCommand(
        command_id="command_019b6000-0000-7000-8000-000000000001",
        channel_key="demo.channel",
        intent_schema=SchemaRef(name="mug.demo.intent", version=0, digest=_A_DIGEST),
        payload_digest=_A_DIGEST,
        idempotency_key="idem_0123456789abcdefghijkA",
        submitted_at="2026-07-21T00:00:00.000000Z",
    )
    return {
        "type": "command",
        "command": command.model_dump(mode="json", exclude_none=True),
        "payload": {"note": "hello"},
    }


def _committed_receipt() -> CommandReceipt:
    """Commit a small aggregate through the real spine and return its receipt."""

    async def run() -> CommandReceipt:
        store = InMemoryStore()
        gateway = Gateway()
        envelope = WireCommandEnvelope.model_validate(
            {
                "schema": {
                    "name": "mug.command-envelope",
                    "version": 0,
                    "digest": _A_DIGEST.model_dump(mode="json"),
                },
                "protocol_version": "0.1.0",
                "command": {"name": "visit.start", "version": 0},
                "request_id": "request_019b6000-0000-7000-8000-000000000001",
                "idempotency_key": "idem_0123456789abcdefghijkA",
                "target": {"id": "visit_019b6000-0000-7000-8000-000000000009"},
                "payload": {
                    "schema": {
                        "name": "mug.edge.payload",
                        "version": 0,
                        "digest": _A_DIGEST.model_dump(mode="json"),
                    },
                    "data": {"value": 1},
                },
            }
        )
        context = gateway.mint(
            envelope, principal=_PARTICIPANT, data_handling=_RESEARCH
        )
        return await commit_command(
            context,
            command=CommandTypeRef(name="visit.start", version=0),
            new_state={"visit_id": context.aggregate_id, "value": 1},
            result=TypedObject(
                schema=result_ref("mug.command-result.visit-transition"),
                data={"outcome": "started"},
            ),
            store=store,
        )

    return asyncio.run(run())


def _rejected_receipt() -> CommandReceipt:
    """Build a rejected, no-effect receipt through the real spine."""

    async def run() -> CommandReceipt:
        gateway = Gateway()
        envelope = WireCommandEnvelope.model_validate(
            {
                "schema": {
                    "name": "mug.command-envelope",
                    "version": 0,
                    "digest": _A_DIGEST.model_dump(mode="json"),
                },
                "protocol_version": "0.1.0",
                "command": {"name": "visit.advance", "version": 0},
                "request_id": "request_019b6000-0000-7000-8000-000000000002",
                "idempotency_key": "idem_0123456789abcdefghijkA",
                "target": {"id": "visit_019b6000-0000-7000-8000-000000000009"},
                "payload": {
                    "schema": {
                        "name": "mug.edge.payload",
                        "version": 0,
                        "digest": _A_DIGEST.model_dump(mode="json"),
                    },
                    "data": {},
                },
            }
        )
        context = gateway.mint(
            envelope, principal=_PARTICIPANT, data_handling=_RESEARCH
        )
        return reject_command(
            context,
            command=CommandTypeRef(name="visit.advance", version=0),
            code="resource.not_found",
            category="not_found",
            message="the visit does not exist",
            retry="never",
        )

    return asyncio.run(run())


def test_handshake_resolves_a_principal_and_reports_the_cursor() -> None:
    """The handshake names the subject and echoes the requested resume cursor."""

    async def dispatch(
        _command: RealtimeCommand, _payload: object, _session: Session
    ) -> CommandReceipt | None:
        return None

    with _app(dispatch).websocket_connect("/ws?resume_from=5") as socket:
        message = socket.receive_json()
    assert message["type"] == "handshake_ack"
    assert message["protocol_version"] == "0.1.0"
    assert message["subject"].startswith("participant_")
    assert message["resume_cursor"] == 5


def test_a_command_is_acked_parsed_then_accepted() -> None:
    """A committed command is acknowledged parsed, then accepted with a position."""
    receipt = _committed_receipt()

    async def dispatch(
        _command: RealtimeCommand, _payload: object, _session: Session
    ) -> CommandReceipt | None:
        return receipt

    with _app(dispatch).websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        socket.send_json(_command_frame())
        parsed = socket.receive_json()
        accepted = socket.receive_json()

    assert parsed["type"] == "ack"
    assert parsed["ack"]["ack_kind"] == "parsed"
    assert accepted["ack"]["ack_kind"] == "accepted"
    assert accepted["ack"]["stream_position"]["sequence"] >= 1


def test_an_unowned_command_returns_a_safe_error() -> None:
    """A command no handler owns is acked parsed, then answered a safe error."""

    async def dispatch(
        _command: RealtimeCommand, _payload: object, _session: Session
    ) -> CommandReceipt | None:
        return None

    with _app(dispatch).websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        socket.send_json(_command_frame())
        assert socket.receive_json()["ack"]["ack_kind"] == "parsed"
        error = socket.receive_json()

    assert error["type"] == "error"
    assert error["code"] == "command.unsupported"


def test_a_rejected_command_maps_to_its_safe_error() -> None:
    """A rejected receipt answers the transport with its safe domain error."""
    receipt = _rejected_receipt()

    async def dispatch(
        _command: RealtimeCommand, _payload: object, _session: Session
    ) -> CommandReceipt | None:
        return receipt

    with _app(dispatch).websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        socket.send_json(_command_frame())
        assert socket.receive_json()["ack"]["ack_kind"] == "parsed"
        error = socket.receive_json()

    assert error["type"] == "error"
    assert error["code"] == "resource.not_found"
    assert error["category"] == "not_found"


def test_a_malformed_command_frame_returns_a_validation_error() -> None:
    """A command that does not validate answers a safe error before any ack."""

    async def dispatch(
        _command: RealtimeCommand, _payload: object, _session: Session
    ) -> CommandReceipt | None:
        return None

    with _app(dispatch).websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        socket.send_json({"type": "command", "command": {}})
        error = socket.receive_json()

    assert error["type"] == "error"
    assert error["code"] == "schema.validation_failed"
