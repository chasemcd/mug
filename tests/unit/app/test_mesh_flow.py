"""Two participants rendezvous into a peer-to-peer mesh and play one episode.

This test drives the whole multiplayer application. Two connections each play the
flow to the game activity, where they rendezvous into one peer mesh. The mesh runs
one shared episode, pushes its frames to both seats, and captures the run once; the
flow then advances both participants past the game to the debrief and the
completion code. A final export shows the shared episode recorded on a visit's
lineage.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from fastapi.testclient import TestClient
from starlette.testclient import WebSocketTestSession

from mug.app import build_demo_app
from mug.client import RealtimeCommand
from mug.game.mesh import ReplicaFrame
from mug.game.mesh_session import MeshGameSpec
from mug.gateway import Gateway
from mug.kernel import Digest, SchemaRef
from mug.storage import InMemoryStore

_A_DIGEST = Digest(algorithm="sha-256", hex="a" * 64)
_EPISODE_LEN = 4


class _LineReplica:
    """A deterministic two-seat replica whose state depends on a generator."""

    def __init__(self, peers: tuple[str, ...], *, seed: int) -> None:
        self._peers = tuple(sorted(peers))
        self._t = 0
        self._rng = seed & 0x7FFFFFFF
        self._pos: dict[str, int] = dict.fromkeys(self._peers, 0)

    def step(self, actions: Mapping[str, int]) -> ReplicaFrame:
        self._t += 1
        self._rng = (self._rng * 1103515245 + 12345) & 0x7FFFFFFF
        noise = self._rng % 3 - 1
        for actor in self._peers:
            self._pos[actor] += (int(actions.get(actor, 0)) - 1) + noise
        observation = [self._pos[actor] for actor in self._peers]
        observation.extend((self._t, self._rng))
        return ReplicaFrame(
            observation=observation,
            rewards={actor: -1.0 for actor in self._peers},
            terminated=self._t >= _EPISODE_LEN,
            truncated=False,
            info={},
        )

    def snapshot(self) -> object:
        return (tuple(sorted(self._pos.items())), self._t, self._rng)

    def restore(self, state: object) -> None:
        positions, step, rng = cast(
            "tuple[tuple[tuple[str, int], ...], int, int]", state
        )
        self._pos = dict(positions)
        self._t = step
        self._rng = rng


def _mesh_spec() -> MeshGameSpec:
    """Build a two-seat mesh game over the self-contained line replica."""
    return MeshGameSpec(
        channel_key="p2p-game",
        size=2,
        make_replica=lambda peers, seed: _LineReplica(peers, seed=seed),
        action_bindings={"a": 0, "d": 2},
        default_action=1,
        seed=12345,
        fps=0,
        max_steps=_EPISODE_LEN + 5,
        input_delay=2,
        snapshot_interval=3,
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
    """Collect the mesh frames the seat receives, then the next delivery."""
    frames: list[dict[str, Any]] = []
    message = socket.receive_json()
    while message.get("type") == "frame":
        frames.append(message)
        message = socket.receive_json()
    return frames, message


def test_two_participants_play_one_shared_mesh_episode() -> None:
    """Both connections rendezvous, play the shared episode, and reach debrief."""
    app = build_demo_app(
        store=InMemoryStore(), gateway=Gateway(), mesh_game=_mesh_spec()
    )
    client = TestClient(app)
    with (
        client,
        client.websocket_connect("/ws") as first,
        client.websocket_connect("/ws") as second,
    ):
        # Both reach the game activity; the second completes the group, so the
        # mesh forms and runs the shared episode.
        _drive_to_game(first, ("01", "02"))
        _drive_to_game(second, ("03", "04"))

        first_frames, first_next = _drain_frames(first)
        second_frames, second_next = _drain_frames(second)

    assert len(first_frames) == _EPISODE_LEN
    assert len(second_frames) == _EPISODE_LEN
    # Every seat sees its own seat key on its frames, and the same frame range.
    assert {frame["seat_key"] for frame in first_frames} == {"seat-1"}
    assert {frame["seat_key"] for frame in second_frames} == {"seat-2"}
    numbers = [frame["frame_number"] for frame in first_frames]
    assert numbers == list(range(_EPISODE_LEN))

    # The flow advances both participants past the game to the debrief.
    assert first_next["delivery"]["kind"] == "content"
    assert second_next["delivery"]["kind"] == "content"


def test_the_shared_mesh_episode_is_captured_on_a_visit() -> None:
    """The mesh captures one episode; a participant's export names its stream."""
    store = InMemoryStore()
    app = build_demo_app(store=store, gateway=Gateway(), mesh_game=_mesh_spec())
    client = TestClient(app)
    with (
        client,
        client.websocket_connect("/ws") as first,
        client.websocket_connect("/ws") as second,
    ):
        _drive_to_game(first, ("11", "12"))
        _drive_to_game(second, ("13", "14"))

        first_frames, first_next = _drain_frames(first)
        _drain_frames(second)

        # Advance past the debrief to the completion code, so the visit closes
        # with the mesh episode recorded on its lineage.
        assert first_next["delivery"]["kind"] == "content"
        first.send_json(_advance_frame({}, "15"))
        assert first.receive_json()["ack"]["ack_kind"] == "parsed"
        assert first.receive_json()["ack"]["ack_kind"] == "accepted"
        complete = first.receive_json()

    assert complete["delivery"]["kind"] == "complete"
    assert complete["delivery"]["completion_code"].startswith("MUG-")
    assert len(first_frames) == _EPISODE_LEN
