"""Phase 1 acceptance: the selected parity fixtures and the Phase 1 gate.

These tests wire the Phase 1 reference fixtures as automated acceptance checks and
assert the Phase 1 gate (``roadmap.md``):

- Fixture 1 -- a single human running a browser/Pyodide Gymnasium environment: the
  browser run is captured under browser authority in the normalized transition
  contract; the server run is captured under server authority in the same
  contract, so the demo also meets the fixture shape under server execution.
- Fixture 7 -- a static/form flow with completion and redirect: the participant
  answers the forms and reaches completion with a completion code and a return
  link.
- Gate: every runtime produces the same normalized transition contract (one record
  type, validated against the one frozen API-07 schema), and private manifest data
  cannot reach a client (the client manifest is a public projection).
"""

from __future__ import annotations

from typing import Any, cast

from fastapi.testclient import TestClient

from examples.mountain_car.browser_env import mountain_car_browser_spec
from mug.app import build_demo_app
from mug.client import RealtimeCommand
from mug.game import GameTransition, game_schema
from mug.game.browser import client_manifest, parse_client_episode
from mug.game.env import EnvFactory, GymEnv, StepResult
from mug.game.runtime import InputState, run_episode
from mug.game.surface import Surface
from mug.gateway import Gateway
from mug.kernel import Digest, SchemaRef
from mug.storage import InMemoryStore

_A_DIGEST = Digest(algorithm="sha-256", hex="a" * 64)
_TRANSITION_DEF = "GameTransition"
_EPISODE = "episode_019b6000-0000-7000-8000-00000000000e"
_INTERACTION = "interaction_019b6000-0000-7000-8000-00000000000f"


class _FakeEnv:
    def __init__(self) -> None:
        self._t = 0

    def reset(self, *, seed: int | None = None) -> tuple[list[float], dict[str, Any]]:
        self._t = 0
        return [0.0], {}

    def step(
        self, action: int
    ) -> tuple[list[float], float, bool, bool, dict[str, Any]]:
        self._t += 1
        return [float(self._t)], -1.0, self._t >= 2, False, {}


def _render(surface: Surface, _state: StepResult) -> None:
    surface.circle(x=0.5, y=0.5, radius=0.02, color="#f00", object_id="dot")


async def _server_transition() -> GameTransition:
    async def sink(_packet: Any) -> None:
        return None

    summary = await run_episode(
        GymEnv(cast("EnvFactory", lambda: _FakeEnv())),
        render=_render,
        channel_key="mountain-car",
        episode_id=_EPISODE,
        interaction_id=_INTERACTION,
        seat_key="player",
        input_state=InputState({"ArrowRight": 2}, 1),
        sink=sink,
        now=lambda: "2026-07-21T00:00:00.000000Z",
        fps=0,
        max_steps=10,
    )
    return summary.transitions[0]


def _browser_transition() -> GameTransition:
    payload: dict[str, Any] = {
        "transitions": [
            {
                "interaction_id": _INTERACTION,
                "channel_key": "mountain-car",
                "episode_id": _EPISODE,
                "frame_number": 1,
                "action_digest": _A_DIGEST.model_dump(mode="json"),
                "state_digest": _A_DIGEST.model_dump(mode="json"),
                "authority": "browser",
                "applied_decisions": [],
                "recorded_at": "2026-07-21T00:00:00.000000Z",
            }
        ],
        "boundary": {
            "episode_id": _EPISODE,
            "interaction_id": _INTERACTION,
            "kind": "terminal",
            "end_frame_exclusive": 1,
            "authority": "browser",
            "state_hash": _A_DIGEST.model_dump(mode="json"),
        },
    }
    summary = parse_client_episode(
        payload,
        expected_channel_key="mountain-car",
        expected_episode_id=_EPISODE,
        seat_key="player",
    )
    return summary.transitions[0]


async def test_fixture_1_every_runtime_produces_the_same_transition_contract() -> None:
    """Server and browser runs produce one record type, one frozen schema."""
    server = await _server_transition()
    browser = _browser_transition()

    # One source: both paths produce the same record class.
    assert type(server) is GameTransition
    assert type(browser) is GameTransition

    # One contract: both validate against the one frozen API-07 schema.
    schema = game_schema()
    assert schema.is_valid(
        _TRANSITION_DEF, server.model_dump(mode="json", exclude_none=True)
    )
    assert schema.is_valid(
        _TRANSITION_DEF, browser.model_dump(mode="json", exclude_none=True)
    )

    # They differ only in who held authority for the run.
    assert server.authority == "server"
    assert browser.authority == "browser"


def test_fixture_1_private_manifest_data_cannot_reach_a_client() -> None:
    """The browser client manifest is a public projection, never the private data."""
    from dataclasses import replace

    spec = replace(mountain_car_browser_spec(), server_notes="private server data")
    manifest = client_manifest(
        spec, episode_id=_EPISODE, interaction_id=_INTERACTION, seat_key="player"
    )
    assert "server_notes" not in manifest
    assert "private server data" not in str(manifest)
    assert manifest["mode"] == "browser"


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


def _drain_to_complete(socket: Any) -> dict[str, Any]:
    """Read frames until the completion delivery, and return it."""
    while True:
        message = socket.receive_json()
        if message.get("type") != "delivery":
            continue
        if message["delivery"]["kind"] == "complete":
            return message["delivery"]


def test_fixture_7_static_form_flow_completes_with_a_code_and_a_redirect() -> None:
    """A form flow reaches completion with a completion code and a return link."""
    client = TestClient(
        build_demo_app(
            store=InMemoryStore(),
            gateway=Gateway(),
            return_url="https://example.test/return",
        )
    )
    with client.websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        assert socket.receive_json()["delivery"]["form"]["form_key"] == "consent"
        socket.send_json(_advance({"agree": "yes"}, tag="1"))
        socket.send_json(_advance({"mood": 3}, tag="2"))
        socket.send_json(_advance({}, tag="3"))
        completion = _drain_to_complete(socket)

    assert completion["completion_code"].startswith("MUG-")
    assert completion["return_url"] == "https://example.test/return"
