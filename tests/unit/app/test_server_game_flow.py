"""A participant plays one server-authoritative episode beside a bot.

This test drives the whole server-authoritative application. One connection plays
the flow to the game activity, where the server steps one authoritative multi-seat
environment: the participant plays one seat and the study's bot plays the other.
The server pushes each stepped frame to the participant, captures the run once, and
advances the flow past the game to the debrief and the completion code. A final
export shows the episode recorded on the visit's lineage.

There is no peer mesh and no second connection: the one authoritative environment
runs on the server, so a single participant plays beside a local bot with no
rendezvous.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi.testclient import TestClient
from starlette.testclient import WebSocketTestSession

from mug.app import build_demo_app
from mug.client import RealtimeCommand
from mug.game.multiseat import MultiStepResult
from mug.gateway import Gateway
from mug.kernel import Digest, SchemaRef
from mug.participant import ServerBotSeat, ServerGameSpec
from mug.storage import InMemoryStore

_A_DIGEST = Digest(algorithm="sha-256", hex="a" * 64)
_EPISODE_LEN = 4
_BOT_ACTOR = "actor_019b6000-0000-7000-8000-0000000000b0"


class _PairEnv:
    """A deterministic two-seat environment: each seat moves its own position.

    The episode terminates after ``_EPISODE_LEN`` steps, so the loop ends on the
    environment terminal, not the step cap.
    """

    def __init__(self) -> None:
        self._t = 0
        self._pos = {"player_0": 0, "player_1": 0}

    def reset(self) -> MultiStepResult:
        self._t = 0
        self._pos = {"player_0": 0, "player_1": 0}
        return self._result()

    def step(self, actions: Mapping[str, int]) -> MultiStepResult:
        self._t += 1
        for agent, action in actions.items():
            self._pos[agent] += int(action)
        return self._result()

    def _result(self) -> MultiStepResult:
        return MultiStepResult(
            observations=dict(self._pos),
            rewards={agent: 0.0 for agent in self._pos},
            terminated=self._t >= _EPISODE_LEN,
            truncated=False,
        )


class _HoldRight:
    """A bot controller that always drives its seat one step to the right."""

    def decide(self, observation: object) -> int:
        return 1


def _server_spec() -> ServerGameSpec:
    """Build a server game: the participant on one seat, a bot on the other."""
    return ServerGameSpec(
        channel_key="server-game",
        make_env=_PairEnv,
        human_agent_id="player_0",
        human_seat_key="seat-1",
        bots=(
            ServerBotSeat(
                agent_id="player_1",
                seat_key="seat-2",
                actor_id=_BOT_ACTOR,
                controller=_HoldRight(),
            ),
        ),
        action_bindings={"a": 0, "d": 2},
        default_action=1,
        fps=0,
        max_steps=_EPISODE_LEN + 5,
    )


def _advance_frame(answers: dict[str, Any], tag: str) -> dict[str, Any]:
    """Build one flow-advance command frame with a unique idempotency key."""
    command = RealtimeCommand(
        command_id=f"command_019b6000-0000-7000-8000-0000000000{tag}",
        channel_key="flow.advance",
        intent_schema=SchemaRef(name="mug.demo.intent", version=0, digest=_A_DIGEST),
        payload_digest=_A_DIGEST,
        idempotency_key="idem_" + tag.ljust(21, "0") + "A",
        submitted_at="2026-07-22T00:00:00.000000Z",
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


def _drain_frames(
    socket: WebSocketTestSession,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Collect the server frames the seat receives, then the next delivery."""
    frames: list[dict[str, Any]] = []
    message = socket.receive_json()
    while message.get("type") == "frame":
        frames.append(message)
        message = socket.receive_json()
    return frames, message


def test_participant_plays_a_server_episode_beside_a_bot() -> None:
    """The server steps one shared episode; the participant then reaches debrief."""
    app = build_demo_app(
        store=InMemoryStore(), gateway=Gateway(), server_game=_server_spec()
    )
    client = TestClient(app)
    with client, client.websocket_connect("/ws") as socket:
        _drive_to_game(socket, ("01", "02"))
        frames, following = _drain_frames(socket)

    assert len(frames) == _EPISODE_LEN
    # Each frame names both seats' actions on the one authoritative timeline; the
    # bot always drove action 1, the human held the default action 1.
    assert [frame["frame_number"] for frame in frames] == list(
        range(1, _EPISODE_LEN + 1)
    )
    for frame in frames:
        assert set(frame["actions"]) == {"player_0", "player_1"}
        assert frame["actions"]["player_1"] == 1
    # The flow advances the participant past the game to the debrief.
    assert following["delivery"]["kind"] == "content"


def test_the_server_episode_is_captured_on_the_visit() -> None:
    """The server captures one episode; the visit closes with it on its lineage."""
    store = InMemoryStore()
    app = build_demo_app(store=store, gateway=Gateway(), server_game=_server_spec())
    client = TestClient(app)
    with client, client.websocket_connect("/ws") as socket:
        _drive_to_game(socket, ("11", "12"))
        frames, following = _drain_frames(socket)

        assert following["delivery"]["kind"] == "content"
        socket.send_json(_advance_frame({}, "15"))
        assert socket.receive_json()["ack"]["ack_kind"] == "parsed"
        assert socket.receive_json()["ack"]["ack_kind"] == "accepted"
        complete = socket.receive_json()

    assert len(frames) == _EPISODE_LEN
    assert complete["delivery"]["kind"] == "complete"
    assert complete["delivery"]["completion_code"].startswith("MUG-")
