"""Two browsers reach the P2P start barrier over the real application socket.

This test drives the whole browser P2P mount: two websocket connections play the
flow to the game activity, where each is admitted to the browser P2P waiting
room. They form one room, exchange API-09 signalling frames through the server,
report their links validated, and cross the start barrier together. They then
report one agreed trajectory, the designated owner submits the capture, and both
browsers receive one finish with the same durable receipt.

There is no browser and no WebRTC here: the test plays the part of the browser's
edge, so the assertions are about the frames the server sends and accepts. The
data channels themselves are proven separately in the signalling tests.
"""

from __future__ import annotations

import asyncio
import hashlib
from typing import Any

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketTestSession

from mug.app import build_demo_app
from mug.client import RealtimeCommand
from mug.game.p2p_capture import VerifiedCapture
from mug.gateway import Gateway
from mug.kernel import Digest, PrincipalRef, SchemaRef
from mug.launch import provision_launch_ticket
from mug.participant_p2p_types import BrowserP2PConfig
from mug.storage import InMemoryStore, Store

_A_DIGEST = Digest(algorithm="sha-256", hex="a" * 64)
_TRAJECTORY = Digest(algorithm="sha-256", hex="d" * 64)
_RESEARCHER = PrincipalRef(
    kind="researcher", id="researcher_019b6000-0000-7000-8000-0000000000ab"
)


def _verifier(payload_json: str) -> VerifiedCapture:
    """Derive the trajectory identity the test payload declares."""
    return VerifiedCapture(
        trajectory_digest=_TRAJECTORY, frame_count=payload_json.count('"frame"')
    )


def _config() -> BrowserP2PConfig:
    return BrowserP2PConfig(
        channel_key="p2p-browser", size=2, verify_capture=_verifier, seed=11
    )


def _p2p_app() -> tuple[FastAPI, TestClient, str]:
    """Build the launch-gated browser P2P app and return a second entry ticket.

    The mount needs a durable enrollment, so every participant enters with a
    launch ticket. The application provisions the first; a second participant
    needs a second ticket against the same store.
    """
    store: Store = InMemoryStore()
    gateway = Gateway()
    app = build_demo_app(
        store=store, gateway=gateway, browser_p2p=_config(), require_launch=True
    )
    second = asyncio.run(
        provision_launch_ticket(gateway, store, researcher=_RESEARCHER)
    )
    return app, TestClient(app), second.ticket_handle


def _http(client: TestClient) -> httpx.Client:
    # starlette's TestClient is an httpx.Client; the base type is fully typed.
    return client


def _both(client: TestClient, app: FastAPI, second_ticket: str) -> tuple[str, str]:
    """Return the two launch-link query strings the participants connect with."""
    return f"/ws?ticket={app.state.launch_ticket}", f"/ws?ticket={second_ticket}"


def _advance_frame(answers: dict[str, Any], tag: str) -> dict[str, Any]:
    """Build one flow-advance command frame with a unique idempotency key."""
    command = RealtimeCommand(
        command_id=f"command_019b6000-0000-7000-8000-0000000000{tag}",
        channel_key="flow.advance",
        intent_schema=SchemaRef(name="mug.demo.intent", version=0, digest=_A_DIGEST),
        payload_digest=_A_DIGEST,
        idempotency_key="idem_" + tag.ljust(21, "0") + "A",
        submitted_at="2026-07-24T00:00:00.000000Z",
    )
    return {
        "type": "command",
        "command": command.model_dump(mode="json", exclude_none=True),
        "payload": {"answers": answers},
    }


def _drive_to_game(socket: WebSocketTestSession, tags: tuple[str, str]) -> None:
    """Play consent then survey, and return once the game delivery arrives."""
    assert socket.receive_json()["type"] == "handshake_ack"
    assert socket.receive_json()["delivery"]["form"]["form_key"] == "consent"
    socket.send_json(_advance_frame({"agree": "yes"}, tags[0]))
    assert socket.receive_json()["ack"]["ack_kind"] == "parsed"
    assert socket.receive_json()["ack"]["ack_kind"] == "accepted"
    assert socket.receive_json()["delivery"]["form"]["form_key"] == "survey"
    socket.send_json(_advance_frame({"mood": 4}, tags[1]))
    assert socket.receive_json()["ack"]["ack_kind"] == "parsed"
    assert socket.receive_json()["ack"]["ack_kind"] == "accepted"
    assert socket.receive_json()["delivery"]["kind"] == "game"


def _await_frame(socket: WebSocketTestSession, kind: str) -> dict[str, Any]:
    """Read frames until the named P2P frame type arrives."""
    for _ in range(20):
        message: dict[str, Any] = socket.receive_json()
        if message.get("type") == kind:
            return message
    raise AssertionError(f"no {kind} frame arrived")


def _schema(bootstrap: dict[str, Any], name: str) -> dict[str, Any]:
    """Echo the frozen schema reference the server's own bootstrap carried."""
    return {
        "name": name,
        "version": 0,
        "digest": bootstrap["schema"]["digest"],
    }


def _signal(
    bootstrap: dict[str, Any], target: str, tag: str, kind: str
) -> dict[str, Any]:
    """Build one browser signalling frame toward a remote peer."""
    signal: dict[str, Any] = {
        "schema": _schema(bootstrap, "mug.api-09.p2p-signal"),
        "room_handle": bootstrap["room_handle"],
        "negotiation_generation": bootstrap["negotiation_generation"],
        "request_id": f"request_019b6000-0000-7000-8000-0000000009{tag}",
        "target_peer_handle": target,
        "signal_kind": kind,
    }
    if kind != "end_of_candidates":
        signal["payload_json"] = '{"sdp":"x"}'
    return {"type": "p2p_signal", "signal": signal}


def _ready(bootstrap: dict[str, Any]) -> dict[str, Any]:
    """Build the all-links-validated report for one browser."""
    return {
        "type": "p2p_peer_ready",
        "ready": {
            "schema": _schema(bootstrap, "mug.api-09.p2p-peer-ready"),
            "room_handle": bootstrap["room_handle"],
            "negotiation_generation": bootstrap["negotiation_generation"],
            "validated_peer_handles": sorted(
                peer["peer_handle"] for peer in bootstrap["peers"]
            ),
        },
    }


def _complete(bootstrap: dict[str, Any], frames: int) -> dict[str, Any]:
    """Build one peer's final replica claim."""
    return {
        "type": "p2p_peer_complete",
        "complete": {
            "schema": _schema(bootstrap, "mug.api-09.p2p-peer-complete"),
            "room_handle": bootstrap["room_handle"],
            "negotiation_generation": bootstrap["negotiation_generation"],
            "trajectory_digest": _TRAJECTORY.model_dump(mode="json"),
            "frame_count": frames,
        },
    }


def _submission(bootstrap: dict[str, Any], frames: int) -> dict[str, Any]:
    """Build the capture owner's bounded payload submission."""
    rows = ",".join(f'{{"frame":{index}}}' for index in range(frames))
    payload_json = f"[{rows}]"
    raw = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
    return {
        "type": "p2p_capture_submission",
        "submission": {
            "schema": _schema(bootstrap, "mug.api-09.p2p-capture-submission"),
            "room_handle": bootstrap["room_handle"],
            "negotiation_generation": bootstrap["negotiation_generation"],
            "trajectory_digest": _TRAJECTORY.model_dump(mode="json"),
            "frame_count": frames,
            "payload_json": payload_json,
            "payload_digest": {"algorithm": "sha-256", "hex": raw},
        },
    }


def test_two_browsers_form_a_room_and_receive_scoped_bootstraps() -> None:
    """Each browser is told only its own handles and the other peer's role."""
    app, client, ticket = _p2p_app()
    left_url, right_url = _both(client, app, ticket)
    with (
        client,
        client.websocket_connect(left_url) as first,
        client.websocket_connect(right_url) as second,
    ):
        _drive_to_game(first, ("01", "02"))
        _drive_to_game(second, ("03", "04"))
        left = _await_frame(first, "p2p_bootstrap")["bootstrap"]
        right = _await_frame(second, "p2p_bootstrap")["bootstrap"]

        assert left["room_handle"] == right["room_handle"]
        assert left["local_peer_handle"] != right["local_peer_handle"]
        assert left["capture_owner_handle"] == right["capture_owner_handle"]
        assert [peer["peer_handle"] for peer in left["peers"]] == [
            right["local_peer_handle"]
        ]
        assert {left["peers"][0]["role"], right["peers"][0]["role"]} == {
            "offerer",
            "answerer",
        }
        # The bootstrap carries the fixed unreliable data-channel configuration.
        assert left["data_channel"] == {
            "label": "mug-mesh-data",
            "ordered": False,
            "max_retransmits": 0,
        }
        # It names no principal, actor, membership, lease, or visit.
        leaked = {"principal", "actor", "membership", "lease", "visit", "enrollment"}
        assert not any(any(term in key for term in leaked) for key in left), sorted(
            left
        )


def test_a_signal_is_relayed_with_a_server_stamped_source() -> None:
    """The browser names a target; the server names the source and acknowledges."""
    app, client, ticket = _p2p_app()
    left_url, right_url = _both(client, app, ticket)
    with (
        client,
        client.websocket_connect(left_url) as first,
        client.websocket_connect(right_url) as second,
    ):
        _drive_to_game(first, ("01", "02"))
        _drive_to_game(second, ("03", "04"))
        left = _await_frame(first, "p2p_bootstrap")["bootstrap"]
        right = _await_frame(second, "p2p_bootstrap")["bootstrap"]

        first.send_json(_signal(left, right["local_peer_handle"], "01", "offer"))

        ack = _await_frame(first, "p2p_signal_ack")["ack"]
        assert ack["status"] == "queued"
        assert "error_code" not in ack
        delivered = _await_frame(second, "p2p_signal_delivery")["signal"]
        assert delivered["source_peer_handle"] == left["local_peer_handle"]
        assert delivered["signal_kind"] == "offer"
        assert delivered["payload_json"] == '{"sdp":"x"}'
        # The delivery carries no target field: the socket it arrived on is the
        # target, so the browser cannot be told to route onward.
        assert "target_peer_handle" not in delivered


def test_a_signal_to_an_unknown_peer_is_rejected_with_a_safe_code() -> None:
    """A browser that invents a target learns only that the target is unknown."""
    app, client, ticket = _p2p_app()
    left_url, right_url = _both(client, app, ticket)
    with (
        client,
        client.websocket_connect(left_url) as first,
        client.websocket_connect(right_url) as second,
    ):
        _drive_to_game(first, ("01", "02"))
        _drive_to_game(second, ("03", "04"))
        left = _await_frame(first, "p2p_bootstrap")["bootstrap"]
        _await_frame(second, "p2p_bootstrap")

        first.send_json(
            _signal(left, "handle_AAAAAAAAAAAAAAAAAAAAAA", "02", "candidate")
        )

        ack = _await_frame(first, "p2p_signal_ack")["ack"]
        assert ack["status"] == "rejected"
        assert ack["error_code"] == "unknown_target"


def test_both_browsers_cross_the_start_barrier_and_finish_together() -> None:
    """Readiness releases one start; the reconciled capture yields one receipt."""
    app, client, ticket = _p2p_app()
    left_url, right_url = _both(client, app, ticket)
    with (
        client,
        client.websocket_connect(left_url) as first,
        client.websocket_connect(right_url) as second,
    ):
        _drive_to_game(first, ("01", "02"))
        _drive_to_game(second, ("03", "04"))
        left = _await_frame(first, "p2p_bootstrap")["bootstrap"]
        right = _await_frame(second, "p2p_bootstrap")["bootstrap"]

        first.send_json(_ready(left))
        second.send_json(_ready(right))
        left_start = _await_frame(first, "p2p_mesh_start")["start"]
        right_start = _await_frame(second, "p2p_mesh_start")["start"]
        assert left_start == right_start
        assert left_start["seed"] == 11
        assert left_start["capture_owner_handle"] == left["capture_owner_handle"]

        first.send_json(_complete(left, 5))
        second.send_json(_complete(right, 5))
        owner, other = (
            (first, left)
            if left["capture_owner_handle"] == left["local_peer_handle"]
            else (second, right)
        )
        owner.send_json(_submission(other, 5))

        left_finish = _await_frame(first, "p2p_mesh_finish")["finish"]
        right_finish = _await_frame(second, "p2p_mesh_finish")["finish"]
        assert left_finish == right_finish
        assert left_finish["frame_count"] == 5
        assert left_finish["trajectory_digest"] == _TRAJECTORY.model_dump(mode="json")
        assert left_finish["capture_receipt"].startswith("handle_")


def test_a_lost_browser_aborts_the_room_for_its_partner() -> None:
    """This vertical does not shrink a mesh: the partner is told to re-pool."""
    app, client, ticket = _p2p_app()
    left_url, right_url = _both(client, app, ticket)
    with client, client.websocket_connect(right_url) as second:
        with client.websocket_connect(left_url) as first:
            _drive_to_game(first, ("01", "02"))
            _drive_to_game(second, ("03", "04"))
            _await_frame(first, "p2p_bootstrap")
            _await_frame(second, "p2p_bootstrap")

        abort = _await_frame(second, "p2p_mesh_abort")["abort"]
        assert abort["reason"] == "peer_disconnected"
        assert abort["disposition"] == "repool"


def test_the_ice_endpoint_answers_once_and_never_caches() -> None:
    """A grant redeems for transient configuration only, with no-store, once."""
    app, client, ticket = _p2p_app()
    left_url, right_url = _both(client, app, ticket)
    with (
        client,
        client.websocket_connect(left_url) as first,
        client.websocket_connect(right_url) as second,
    ):
        _drive_to_game(first, ("01", "02"))
        _drive_to_game(second, ("03", "04"))
        left = _await_frame(first, "p2p_bootstrap")["bootstrap"]
        _await_frame(second, "p2p_bootstrap")
        http = _http(client)
        coordinator: Any = app.state.p2p_coordinator
        visit_id = coordinator.visit_of_peer(left["local_peer_handle"])
        assert isinstance(visit_id, str)

        body = {
            "schema": _schema(left, "mug.api-09.p2p-ice-grant-request"),
            "ice_grant_handle": left["ice_grant_handle"],
        }
        response = http.post(
            left["ice_endpoint"], json=body, headers={"x-mug-visit": visit_id}
        )

        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert set(response.json()) == {"iceServers", "iceTransportPolicy"}
        # The grant is one-use.
        again = http.post(
            left["ice_endpoint"], json=body, headers={"x-mug-visit": visit_id}
        )
        assert again.status_code == 403
