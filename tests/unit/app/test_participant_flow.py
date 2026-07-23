"""The runnable vertical: a participant plays the flow over the websocket.

This test drives the whole demo application. On connect the server opens the flow
and delivers the consent form. The participant answers consent, which advances the
flow and delivers the survey. The transport acks the command parsed then accepted.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from fastapi.testclient import TestClient

from examples.mountain_car.native_env import mountain_car_spec
from mug.app import build_demo_app
from mug.client import RealtimeCommand
from mug.gateway import Gateway
from mug.kernel import Digest, SchemaRef
from mug.storage import InMemoryStore

_A_DIGEST = Digest(algorithm="sha-256", hex="a" * 64)


def _advance_frame(answers: dict[str, Any], tag: str = "1") -> dict[str, Any]:
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


def test_a_participant_plays_consent_then_survey() -> None:
    """Connect, receive the consent form, answer it, receive the survey."""
    client = TestClient(build_demo_app(store=InMemoryStore(), gateway=Gateway()))
    with client.websocket_connect("/ws") as socket:
        handshake = socket.receive_json()
        first = socket.receive_json()

        socket.send_json(_advance_frame({"agree": "yes"}))
        parsed = socket.receive_json()
        accepted = socket.receive_json()
        second = socket.receive_json()

    assert handshake["type"] == "handshake_ack"
    assert first["type"] == "delivery"
    assert first["delivery"]["kind"] == "form"
    assert first["delivery"]["form"]["form_key"] == "consent"

    assert parsed["ack"]["ack_kind"] == "parsed"
    assert accepted["ack"]["ack_kind"] == "accepted"
    assert second["type"] == "delivery"
    assert second["delivery"]["form"]["form_key"] == "survey"


def test_an_invalid_answer_keeps_the_participant_on_consent() -> None:
    """An answer outside the options is refused and does not advance the flow."""
    client = TestClient(build_demo_app(store=InMemoryStore(), gateway=Gateway()))
    with client.websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        assert socket.receive_json()["delivery"]["form"]["form_key"] == "consent"

        socket.send_json(_advance_frame({"agree": "maybe"}))
        assert socket.receive_json()["ack"]["ack_kind"] == "parsed"
        error = socket.receive_json()

    assert error["type"] == "error"
    assert error["category"] == "validation"


def test_the_flow_reaches_the_game_and_plays_a_short_episode() -> None:
    """Consent then survey reaches the game; the server plays it, then debriefs."""
    spec = replace(mountain_car_spec(), fps=0, max_steps=3, countdown_seconds=0)
    client = TestClient(
        build_demo_app(store=InMemoryStore(), gateway=Gateway(), game=spec)
    )
    with client.websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        assert socket.receive_json()["delivery"]["form"]["form_key"] == "consent"

        socket.send_json(_advance_frame({"agree": "yes"}, tag="1"))
        assert socket.receive_json()["ack"]["ack_kind"] == "parsed"
        assert socket.receive_json()["ack"]["ack_kind"] == "accepted"
        assert socket.receive_json()["delivery"]["form"]["form_key"] == "survey"

        socket.send_json(_advance_frame({"mood": 4}, tag="2"))
        assert socket.receive_json()["ack"]["ack_kind"] == "parsed"
        assert socket.receive_json()["ack"]["ack_kind"] == "accepted"
        game = socket.receive_json()

        renders = [socket.receive_json() for _ in range(4)]
        debrief = socket.receive_json()

    assert game["delivery"]["kind"] == "game"
    assert game["delivery"]["countdown"] == 0
    assert all(frame["type"] == "render" for frame in renders)
    assert renders[0]["packet"]["keyframe"] is True
    assert renders[-1]["packet"]["frame_number"] == 3
    assert debrief["delivery"]["kind"] == "content"


def test_the_flow_completes_with_a_code_and_a_return_link() -> None:
    """The whole slice ends on a completion code and the deployment return link."""
    spec = replace(mountain_car_spec(), fps=0, max_steps=3, countdown_seconds=0)
    client = TestClient(
        build_demo_app(
            store=InMemoryStore(),
            gateway=Gateway(),
            game=spec,
            return_url="https://example.test/return",
        )
    )
    with client.websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        assert socket.receive_json()["delivery"]["form"]["form_key"] == "consent"

        socket.send_json(_advance_frame({"agree": "yes"}, tag="1"))
        assert socket.receive_json()["ack"]["ack_kind"] == "parsed"
        assert socket.receive_json()["ack"]["ack_kind"] == "accepted"
        assert socket.receive_json()["delivery"]["form"]["form_key"] == "survey"

        socket.send_json(_advance_frame({"mood": 4}, tag="2"))
        assert socket.receive_json()["ack"]["ack_kind"] == "parsed"
        assert socket.receive_json()["ack"]["ack_kind"] == "accepted"
        assert socket.receive_json()["delivery"]["kind"] == "game"
        for _ in range(4):
            socket.receive_json()
        assert socket.receive_json()["delivery"]["kind"] == "content"

        socket.send_json(_advance_frame({}, tag="3"))
        assert socket.receive_json()["ack"]["ack_kind"] == "parsed"
        assert socket.receive_json()["ack"]["ack_kind"] == "accepted"
        complete = socket.receive_json()

    assert complete["delivery"]["kind"] == "complete"
    assert complete["delivery"]["completion_code"].startswith("MUG-")
    assert complete["delivery"]["return_url"] == "https://example.test/return"
