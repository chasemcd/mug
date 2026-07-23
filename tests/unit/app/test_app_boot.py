"""The composition root boots: it serves the shell, the assets, and the handshake.

These tests drive the whole application through FastAPI's test client over a fresh
in-memory store. The root serves the client shell, the static mount serves the
shell's module, the websocket answers a handshake ack, and the edge command
surface is composed in (an unknown command still routes to the edge's safe 404).
"""

from __future__ import annotations

import httpx
from fastapi.testclient import TestClient

from mug.app import build_demo_app
from mug.gateway import Gateway
from mug.storage import InMemoryStore


def _build() -> TestClient:
    return TestClient(build_demo_app(store=InMemoryStore(), gateway=Gateway()))


def _http() -> httpx.Client:
    # starlette's TestClient is an httpx.Client; the base type is fully typed.
    return _build()


def test_root_serves_the_client_shell() -> None:
    """The root returns the HTML shell that loads the client module."""
    response = _http().get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "/static/main.js" in response.text


def test_static_mount_serves_the_client_module() -> None:
    """The static mount serves the shell's ES module and the renderer module."""
    client = _http()
    main = client.get("/static/main.js")
    assert main.status_code == 200
    assert "WebSocket" in main.text

    renderer = client.get("/static/renderer.js")
    assert renderer.status_code == 200
    assert "createRenderer" in renderer.text


def test_websocket_answers_a_handshake_ack() -> None:
    """The websocket accepts a connection and returns one handshake ack."""
    with _build().websocket_connect("/ws") as socket:
        message = socket.receive_json()
    assert message["type"] == "handshake_ack"
    assert message["protocol_version"] == "0.1.0"


def test_edge_command_surface_is_composed_in() -> None:
    """The edge routes are mounted, so an unknown command hits its safe 404."""
    response = _http().post(
        "/commands/nope.unknown",
        json={
            "schema": {
                "name": "mug.command-envelope",
                "version": 0,
                "digest": {"algorithm": "sha-256", "hex": "a" * 64},
            },
            "protocol_version": "0.1.0",
            "command": {"name": "nope.unknown", "version": 0},
            "request_id": "request_019b6000-0000-7000-8000-000000000001",
            "idempotency_key": "idem_0123456789abcdefghijkA",
            "target": {"id": "study_019b6000-0000-7000-8000-000000000001"},
            "payload": {
                "schema": {
                    "name": "mug.edge.payload",
                    "version": 0,
                    "digest": {"algorithm": "sha-256", "hex": "a" * 64},
                },
                "data": {},
            },
        },
    )
    assert response.status_code == 404
    assert response.json()["code"] == "resource.not_found"
