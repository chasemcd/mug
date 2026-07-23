"""A reconnection resumes the visit where it stopped, not from the start.

On the first connection the handshake carries a resume token that names the
visit's flow. When the participant reconnects and presents that token, the server
rehydrates the flow's pointer and re-presents the current activity, so a dropped
connection does not restart the study. An unknown token starts a fresh visit.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from mug.app import build_demo_app
from mug.client import RealtimeCommand
from mug.gateway import Gateway
from mug.kernel import Digest, SchemaRef
from mug.storage import InMemoryStore

_A_DIGEST = Digest(algorithm="sha-256", hex="a" * 64)


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


def test_a_reconnection_resumes_at_the_current_activity() -> None:
    """Answer consent, drop, reconnect with the token: the survey is re-presented."""
    store = InMemoryStore()
    client = TestClient(build_demo_app(store=store, gateway=Gateway()))

    with client.websocket_connect("/ws") as socket:
        handshake = socket.receive_json()
        token = handshake["resume_token"]
        assert socket.receive_json()["delivery"]["form"]["form_key"] == "consent"
        socket.send_json(_advance({"agree": "yes"}, tag="1"))
        assert socket.receive_json()["ack"]["ack_kind"] == "parsed"
        assert socket.receive_json()["ack"]["ack_kind"] == "accepted"
        assert socket.receive_json()["delivery"]["form"]["form_key"] == "survey"

    # Reconnect with the token: the flow resumes at the survey, not consent.
    with client.websocket_connect(f"/ws?resume_token={token}") as socket:
        resumed = socket.receive_json()
        assert resumed["resume_token"] == token
        assert socket.receive_json()["delivery"]["form"]["form_key"] == "survey"


def test_a_reconnection_can_finish_the_resumed_visit() -> None:
    """The resumed visit keeps advancing: survey then onward from where it stopped."""
    store = InMemoryStore()
    client = TestClient(build_demo_app(store=store, gateway=Gateway()))

    with client.websocket_connect("/ws") as socket:
        token = socket.receive_json()["resume_token"]
        assert socket.receive_json()["delivery"]["form"]["form_key"] == "consent"
        socket.send_json(_advance({"agree": "yes"}, tag="1"))
        assert socket.receive_json()["ack"]["ack_kind"] == "parsed"
        assert socket.receive_json()["ack"]["ack_kind"] == "accepted"
        assert socket.receive_json()["delivery"]["form"]["form_key"] == "survey"

    with client.websocket_connect(f"/ws?resume_token={token}") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        assert socket.receive_json()["delivery"]["form"]["form_key"] == "survey"
        # The revision picks up from the resumed state, so the next advance is
        # accepted rather than rejected as a stale revision.
        socket.send_json(_advance({"mood": 4}, tag="2"))
        assert socket.receive_json()["ack"]["ack_kind"] == "parsed"
        assert socket.receive_json()["ack"]["ack_kind"] == "accepted"


def test_an_unknown_token_starts_a_fresh_visit() -> None:
    """A token that names no stored flow falls back to a new visit at consent."""
    store = InMemoryStore()
    client = TestClient(build_demo_app(store=store, gateway=Gateway()))
    unknown = "visitplan_019b6000-0000-7000-8000-000000000999"

    with client.websocket_connect(f"/ws?resume_token={unknown}") as socket:
        handshake = socket.receive_json()
        assert handshake["type"] == "handshake_ack"
        # A fresh flow is opened, with its own token, at the consent form.
        assert handshake["resume_token"] != unknown
        assert socket.receive_json()["delivery"]["form"]["form_key"] == "consent"
