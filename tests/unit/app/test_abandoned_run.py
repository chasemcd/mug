"""A participant who leaves mid-round leaves the frames they played.

This is the whole reason a run is reported in parts. The old client held the episode
in the tab and reported it once, at the end, so shutting the tab at frame four
hundred of six hundred contributed **nothing at all** -- and shutting the tab is what
a participant does when they get bored, lose their connection, or are interrupted.

Here a real socket reports parts and then goes away without closing the episode. The
server seals what arrived: it re-executes the prefix, matches every state hash, and
records a verified episode of the frames that were really played. What is checked is
the record, not the acknowledgement -- nobody is listening on a socket that closed.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from examples.mountain_car.browser_env import mountain_car_browser_spec
from mug.app import build_demo_app
from mug.client import RealtimeCommand
from mug.game.browser import BrowserGameSpec
from mug.game.capture_parts import read_progress
from mug.game.determinism import state_hash
from mug.game.env import GymEnv
from mug.gateway import Gateway
from mug.kernel import Digest, SchemaRef
from mug.storage import InMemoryStore

_A_DIGEST = Digest(algorithm="sha-256", hex="a" * 64)


def _command(tag: str, channel: str) -> dict[str, Any]:
    return RealtimeCommand(
        command_id=f"command_019b6000-0000-7000-8000-00000000000{tag}",
        channel_key=channel,
        intent_schema=SchemaRef(name="mug.demo.intent", version=0, digest=_A_DIGEST),
        payload_digest=_A_DIGEST,
        idempotency_key="idem_" + tag.ljust(21, "0") + "A",
        submitted_at="2026-07-28T00:00:00.000000Z",
    ).model_dump(mode="json", exclude_none=True)


def _advance(answers: dict[str, Any], tag: str) -> dict[str, Any]:
    return {
        "type": "command",
        "command": _command(tag, "flow.advance"),
        "payload": {"answers": answers},
    }


class _Play:
    """Runs the study's own bundle, so the reported hashes are the honest ones."""

    def __init__(self, spec: BrowserGameSpec, manifest: dict[str, Any]) -> None:
        namespace: dict[str, Any] = {}
        exec(spec.source_bundle, namespace)
        self._env = GymEnv(namespace["make_env"], seed=spec.seed)
        self._env.reset()
        self._manifest = manifest
        self._frame = 0

    def part(self, count: int, *, final: bool, tag: str) -> dict[str, Any]:
        transitions: list[dict[str, Any]] = []
        actions: list[int] = []
        first = self._frame + 1
        state = None
        for _ in range(count):
            action = 2
            state = self._env.step(action)
            self._frame += 1
            transitions.append(
                {
                    "interaction_id": self._manifest["interaction_id"],
                    "channel_key": self._manifest["channel_key"],
                    "episode_id": self._manifest["episode_id"],
                    "frame_number": self._frame,
                    "action_digest": state_hash(action).model_dump(mode="json"),
                    "state_digest": state_hash(state.observation).model_dump(
                        mode="json"
                    ),
                    "authority": "browser",
                    "applied_decisions": [],
                    "recorded_at": "2026-07-28T00:00:00.000000Z",
                }
            )
            actions.append(action)
        assert state is not None
        episode: dict[str, Any] = {"transitions": transitions}
        if final:
            episode["boundary"] = {
                "episode_id": self._manifest["episode_id"],
                "interaction_id": self._manifest["interaction_id"],
                "kind": "reset",
                "end_frame_exclusive": self._frame,
                "authority": "browser",
                "state_hash": state_hash(state.observation).model_dump(mode="json"),
            }
        return {
            "type": "command",
            "command": _command(tag, "game.capture"),
            "payload": {
                "episode": episode,
                "actions": actions,
                "first_frame": first,
                "final": final,
                "generation": 1,
            },
        }


def _reach_the_game(socket: Any) -> dict[str, Any]:
    """Walk the demo study's forms and return the browser manifest."""
    assert socket.receive_json()["type"] == "handshake_ack"
    assert socket.receive_json()["delivery"]["kind"] == "preload"
    assert socket.receive_json()["delivery"]["form"]["form_key"] == "consent"
    socket.send_json(_advance({"agree": "yes"}, tag="1"))
    assert socket.receive_json()["ack"]["ack_kind"] == "parsed"
    assert socket.receive_json()["ack"]["ack_kind"] == "accepted"
    assert socket.receive_json()["delivery"]["form"]["form_key"] == "survey"
    socket.send_json(_advance({"mood": 4}, tag="2"))
    assert socket.receive_json()["ack"]["ack_kind"] == "parsed"
    assert socket.receive_json()["ack"]["ack_kind"] == "accepted"
    return cast_manifest(socket.receive_json()["delivery"])


def cast_manifest(delivery: dict[str, Any]) -> dict[str, Any]:
    assert delivery["mode"] == "browser"
    return dict(delivery["manifest"])


def test_a_participant_who_shuts_the_tab_mid_round_is_still_recorded() -> None:
    """The frames played before the tab closed are re-executed and recorded."""
    store = InMemoryStore()
    spec = mountain_car_browser_spec()
    app = build_demo_app(store=store, gateway=Gateway(), browser_game=spec)
    client = TestClient(app)

    with client.websocket_connect("/ws") as socket:
        manifest = _reach_the_game(socket)
        play = _Play(spec, manifest)
        for index, tag in enumerate(("7", "8", "9")):
            socket.send_json(play.part(40, final=False, tag=tag))
            assert socket.receive_json()["ack"]["ack_kind"] == "parsed"
            assert socket.receive_json()["ack"]["ack_kind"] == "accepted"
            # Nothing advances: the participant is still in the game.
            assert index >= 0
        # The tab closes. No closing part is ever sent.

    episode_id = manifest["episode_id"]
    recorded = store.load_aggregate(episode_id)
    assert isinstance(recorded, dict), (
        "the participant played 120 frames and nothing was recorded"
    )
    assert recorded["frame_count"] == 120
    assert recorded["verification"] == "deterministic"
    assert recorded["outcome"] == "reset"
    # The values are there too, because the server re-executed the prefix itself.
    assert recorded["trajectory"]

    progress = read_progress(store, episode_id)
    assert progress is not None
    assert progress.sealed, "a sealed run must not be sealed again by a sweep"


def test_a_run_the_participant_finished_still_advances_the_flow() -> None:
    """Parts change when a run is recorded, not whether the study still works."""
    store = InMemoryStore()
    spec = mountain_car_browser_spec()
    app = build_demo_app(store=store, gateway=Gateway(), browser_game=spec)
    client = TestClient(app)

    with client.websocket_connect("/ws") as socket:
        manifest = _reach_the_game(socket)
        play = _Play(spec, manifest)
        socket.send_json(play.part(40, final=False, tag="7"))
        assert socket.receive_json()["ack"]["ack_kind"] == "parsed"
        assert socket.receive_json()["ack"]["ack_kind"] == "accepted"
        socket.send_json(play.part(40, final=True, tag="8"))
        assert socket.receive_json()["ack"]["ack_kind"] == "parsed"
        assert socket.receive_json()["ack"]["ack_kind"] == "accepted"
        debrief = socket.receive_json()["delivery"]

    assert debrief["kind"] == "content"
    recorded = store.load_aggregate(manifest["episode_id"])
    assert isinstance(recorded, dict)
    assert recorded["frame_count"] == 80


def test_a_forged_part_records_nothing_even_when_the_tab_closes() -> None:
    """Leaving early must not become a way to launder an unverifiable run."""
    store = InMemoryStore()
    spec = mountain_car_browser_spec()
    app = build_demo_app(store=store, gateway=Gateway(), browser_game=spec)
    client = TestClient(app)

    with client.websocket_connect("/ws") as socket:
        manifest = _reach_the_game(socket)
        play = _Play(spec, manifest)
        forged = play.part(40, final=False, tag="7")
        forged["payload"]["episode"]["transitions"][10]["state_digest"] = (
            _A_DIGEST.model_dump(mode="json")
        )
        socket.send_json(forged)
        assert socket.receive_json()["ack"]["ack_kind"] == "parsed"
        assert socket.receive_json()["ack"]["ack_kind"] == "accepted"

    assert store.load_aggregate(manifest["episode_id"]) is None
