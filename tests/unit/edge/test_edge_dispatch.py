"""The HTTP edge mints a context, dispatches, and maps outcomes to status codes.

These tests drive the edge with FastAPI's test client over a fresh in-memory
store, a deterministic gateway (a fixed clock and counter entropy), and a stub
that resolves the principal from verified auth. A valid enrol returns 200 and an
accepted receipt; a non-participant maps to 403; an unknown command type returns
404; and an envelope that does not validate returns a safe 400 that echoes no
input. The client sends only an untrusted ``WireCommandEnvelope``; it never
carries a principal.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import Request
from fastapi.testclient import TestClient

from mug.edge import build_app
from mug.gateway import Gateway
from mug.kernel import PrincipalRef
from mug.storage import InMemoryStore

_UUID = "019b6000-0000-7000-8000-0000000000{:02x}"
_STUDY = "study_019b6000-0000-7000-8000-000000000001"
_ENROLLMENT = "enrollment_" + _UUID.format(0x50)
_DIGEST = {"algorithm": "sha-256", "hex": "a" * 64}


class _Entropy:
    """A deterministic entropy source: each call yields fresh, distinct bytes."""

    def __init__(self) -> None:
        self._n = 0

    def __call__(self, size: int) -> bytes:
        self._n += 1
        return bytes([self._n % 256]) * size


def _clock() -> datetime:
    return datetime(2026, 8, 2, 12, 0, 0, tzinfo=timezone.utc)


def _auth(kind: str) -> Callable[[Request], PrincipalRef]:
    principal = (
        PrincipalRef(kind="participant", id="participant_" + _UUID.format(0x80))
        if kind == "participant"
        else PrincipalRef(kind="researcher", id="researcher_" + _UUID.format(0x09))
    )

    def authenticate(_request: Request) -> PrincipalRef:
        return principal

    return authenticate


def _envelope(
    command_type: str, *, target: str, data: dict[str, Any]
) -> dict[str, Any]:
    return {
        "schema": {"name": "mug.command-envelope", "version": 0, "digest": _DIGEST},
        "protocol_version": "0.1.0",
        "command": {"name": command_type, "version": 0},
        "request_id": "request_" + _UUID.format(0x01),
        "idempotency_key": "idem_0123456789abcdefghijkA",
        "target": {"id": target},
        "payload": {
            "schema": {"name": "mug.edge.payload", "version": 0, "digest": _DIGEST},
            "data": data,
        },
    }


def _client(kind: str = "participant") -> httpx.Client:
    # starlette's TestClient is an httpx.Client; the base type is fully typed.
    app = build_app(
        InMemoryStore(),
        gateway=Gateway(clock=_clock, entropy=_Entropy()),
        authenticate=_auth(kind),
    )
    return TestClient(app)


def test_enroll_returns_an_accepted_receipt() -> None:
    """A valid enrol mints a context, dispatches, and returns a 200 commit."""
    response = _client().post(
        "/commands/enrollment.enroll",
        json=_envelope(
            "enrollment.enroll", target=_ENROLLMENT, data={"study_id": _STUDY}
        ),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "accepted"
    assert body["receipt_class"] == "commit"
    # The receipt names the client-minted aggregate the envelope targeted.
    assert body["resource"]["id"] == _ENROLLMENT


def test_a_forbidden_actor_maps_to_403() -> None:
    """A rejected receipt maps its authorization category to 403."""
    response = _client(kind="researcher").post(
        "/commands/enrollment.enroll",
        json=_envelope(
            "enrollment.enroll", target=_ENROLLMENT, data={"study_id": _STUDY}
        ),
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "auth.forbidden"


def test_an_unknown_command_type_returns_404() -> None:
    """An unknown command type never reaches a handler."""
    response = _client().post(
        "/commands/nope.unknown",
        json=_envelope("nope.unknown", target=_ENROLLMENT, data={"study_id": _STUDY}),
    )
    assert response.status_code == 404
    assert response.json()["code"] == "resource.not_found"


def test_a_malformed_envelope_returns_a_safe_400() -> None:
    """An envelope without a target does not validate and leaks no input."""
    body = _envelope("enrollment.enroll", target=_ENROLLMENT, data={"study_id": _STUDY})
    del body["target"]
    response = _client().post("/commands/enrollment.enroll", json=body)
    assert response.status_code == 400
    assert response.json()["code"] == "schema.validation_failed"
    assert _STUDY not in response.text
