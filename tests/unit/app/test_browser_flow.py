"""The browser execution vertical: the client reports a run, the server captures.

This drives the whole application in browser mode. The flow reaches the game and
delivers the public client manifest, not a server loop. The client then reports a
finished episode over ``game.capture``; the server validates it into the
transition contract, commits it under browser authority, and advances to the
debrief. The captured run exports as part of the visit lineage.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi.testclient import TestClient

from examples.mountain_car.browser_env import mountain_car_browser_spec
from mug.admission import AdmissionPolicy, capture_frame_bytes
from mug.app import build_demo_app
from mug.client import RealtimeCommand
from mug.game.browser import BrowserGameSpec
from mug.game.capture_parts import FRAMES_PER_PART
from mug.game.determinism import state_hash
from mug.game.env import GymEnv
from mug.gateway import Gateway
from mug.kernel import Digest, SchemaRef
from mug.storage import InMemoryStore

_A_DIGEST = Digest(algorithm="sha-256", hex="a" * 64)
_ACTIONS = [0, 2, 1]


def _genuine_episode(
    manifest: dict[str, Any], spec: BrowserGameSpec, actions: list[int]
) -> dict[str, Any]:
    """Build the episode an honest client reports, so the server verifies it.

    It re-executes the run the same way the server verifier does, so its state
    hashes match the re-execution and the capture is accepted.
    """
    namespace: dict[str, Any] = {}
    exec(spec.source_bundle, namespace)
    env = GymEnv(namespace["make_env"], seed=spec.seed)
    env.reset()
    transitions: list[dict[str, Any]] = []
    state = None
    for frame, action in enumerate(actions, start=1):
        state = env.step(action)
        transitions.append(
            {
                "interaction_id": manifest["interaction_id"],
                "channel_key": manifest["channel_key"],
                "episode_id": manifest["episode_id"],
                "frame_number": frame,
                "action_digest": state_hash(action).model_dump(mode="json"),
                "state_digest": state_hash(state.observation).model_dump(mode="json"),
                "authority": "browser",
                "applied_decisions": [],
                "recorded_at": "2026-07-21T00:00:00.000000Z",
            }
        )
    assert state is not None
    return {
        "transitions": transitions,
        "boundary": {
            "episode_id": manifest["episode_id"],
            "interaction_id": manifest["interaction_id"],
            "kind": "reset",
            "end_frame_exclusive": len(actions),
            "authority": "browser",
            "state_hash": state_hash(state.observation).model_dump(mode="json"),
        },
    }


def _command(tag: str, channel: str) -> RealtimeCommand:
    return RealtimeCommand(
        command_id=f"command_019b6000-0000-7000-8000-00000000000{tag}",
        channel_key=channel,
        intent_schema=SchemaRef(name="mug.demo.intent", version=0, digest=_A_DIGEST),
        payload_digest=_A_DIGEST,
        idempotency_key="idem_" + tag.ljust(21, "0") + "A",
        submitted_at="2026-07-21T00:00:00.000000Z",
    )


def _advance(answers: dict[str, Any], tag: str) -> dict[str, Any]:
    return {
        "type": "command",
        "command": _command(tag, "flow.advance").model_dump(
            mode="json", exclude_none=True
        ),
        "payload": {"answers": answers},
    }


def _capture_frame(
    manifest: dict[str, Any],
    spec: BrowserGameSpec,
    episode: dict[str, Any] | None = None,
    actions: list[int] | None = None,
) -> dict[str, Any]:
    run = episode or _genuine_episode(manifest, spec, _ACTIONS)
    return {
        "type": "command",
        "command": _command("7", "game.capture").model_dump(
            mode="json", exclude_none=True
        ),
        "payload": {
            "episode": run,
            "actions": _ACTIONS if actions is None else actions,
            "generation": 1,
        },
    }


def test_the_browser_flow_ships_a_manifest_and_captures_the_client_run() -> None:
    """The game ships a public manifest; the client run is captured, then debrief."""
    store = InMemoryStore()
    spec = mountain_car_browser_spec()
    app = build_demo_app(store=store, gateway=Gateway(), browser_game=spec)
    client = TestClient(app)
    with client.websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"

        # The bundle is announced first, so the client can preload Pyodide and the
        # packages during the forms; the announcement carries no private data.
        preload = socket.receive_json()["delivery"]
        assert preload["kind"] == "preload"
        assert preload["manifest"]["source_bundle"]
        assert preload["manifest"]["requires"]
        assert "server_notes" not in preload["manifest"]

        assert socket.receive_json()["delivery"]["form"]["form_key"] == "consent"

        socket.send_json(_advance({"agree": "yes"}, tag="1"))
        assert socket.receive_json()["ack"]["ack_kind"] == "parsed"
        assert socket.receive_json()["ack"]["ack_kind"] == "accepted"
        assert socket.receive_json()["delivery"]["form"]["form_key"] == "survey"

        socket.send_json(_advance({"mood": 4}, tag="2"))
        assert socket.receive_json()["ack"]["ack_kind"] == "parsed"
        assert socket.receive_json()["ack"]["ack_kind"] == "accepted"
        game = socket.receive_json()["delivery"]

        assert game["kind"] == "game"
        assert game["mode"] == "browser"
        assert game["countdown"] == 3
        manifest = game["manifest"]
        assert manifest["channel_key"] == "mountain-car"
        assert manifest["countdown_seconds"] == 3
        assert "server_notes" not in manifest

        socket.send_json(_capture_frame(manifest, spec))
        assert socket.receive_json()["ack"]["ack_kind"] == "parsed"
        assert socket.receive_json()["ack"]["ack_kind"] == "accepted"
        debrief = socket.receive_json()["delivery"]

    assert debrief["kind"] == "content"


def test_a_full_length_run_is_captured_because_it_is_reported_in_parts() -> None:
    """A participant who plays to the end of the episode is recorded.

    Every other test here reports a handful of frames in one command. A real one
    plays as long as the game allows, and a run of any real length does not fit one
    frame -- the process refused the report of a game it had just asked a participant
    to play, at the end, with nothing recorded.

    It is reported in slices now, so the length of the game stops being the size of
    the report. Each slice fits the transport, and the closing one seals the run.
    """
    spec = mountain_car_browser_spec()
    app = build_demo_app(store=InMemoryStore(), gateway=Gateway(), browser_game=spec)
    client = TestClient(app)
    with client.websocket_connect("/ws") as socket:
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
        manifest = socket.receive_json()["delivery"]["manifest"]

        # The server tells the client how often to report, so the cadence is not
        # the client's to choose.
        assert manifest["frames_per_part"] == FRAMES_PER_PART

        # The game runs to its own limit, which is what the study asked for.
        actions = [2] * spec.max_steps
        episode = _genuine_episode(manifest, spec, actions)
        for sent, at in enumerate(range(0, spec.max_steps, FRAMES_PER_PART)):
            slice_end = min(at + FRAMES_PER_PART, spec.max_steps)
            final = slice_end == spec.max_steps
            body: dict[str, Any] = {
                "transitions": episode["transitions"][at:slice_end]
            }
            if final:
                body["boundary"] = episode["boundary"]
            frame = {
                "type": "command",
                "command": _command(str(sent + 3), "game.capture").model_dump(
                    mode="json", exclude_none=True
                ),
                "payload": {
                    "episode": body,
                    "actions": actions[at:slice_end],
                    "first_frame": at + 1,
                    "final": final,
                    "generation": 1,
                },
            }
            # Every report fits the transport, whatever the length of the game.
            assert len(json.dumps(frame)) <= AdmissionPolicy().max_frame_bytes
            socket.send_json(frame)
            assert socket.receive_json()["ack"]["ack_kind"] == "parsed"
            assert socket.receive_json()["ack"]["ack_kind"] == "accepted"
        debrief = socket.receive_json()["delivery"]

    assert debrief["kind"] == "content"


def test_the_allowance_per_frame_holds_the_report_of_a_real_frame() -> None:
    """A run of any length fits the bound derived for it, measured on a real one.

    The allowance is a number, and a number can be too small. So it is checked
    against the report a client really builds -- transitions, actions, and the
    partner's actions beside them -- rather than against a guess of what one costs.
    """
    spec = mountain_car_browser_spec()
    manifest = {
        "interaction_id": "interaction_019b6000-0000-7000-8000-0000000000aa",
        "channel_key": spec.channel_key,
        "episode_id": "episode_019b6000-0000-7000-8000-0000000000bb",
    }
    for frames in (1, 200, 600, 1350):
        actions = [2] * frames
        reported = {
            "type": "command",
            "command": _command("7", "game.capture").model_dump(
                mode="json", exclude_none=True
            ),
            "payload": {
                "episode": _genuine_episode(manifest, spec, actions),
                "actions": actions,
                # A study with a partner reports what it did on every frame too.
                "partner_actions": actions,
                "generation": 1,
            },
        }
        assert len(json.dumps(reported)) <= capture_frame_bytes(frames)


def test_a_run_that_fails_verification_is_refused_without_advancing() -> None:
    """A run whose state hashes do not match the re-execution is refused."""
    spec = mountain_car_browser_spec()
    app = build_demo_app(store=InMemoryStore(), gateway=Gateway(), browser_game=spec)
    client = TestClient(app)
    with client.websocket_connect("/ws") as socket:
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
        manifest = socket.receive_json()["delivery"]["manifest"]

        # A run whose reported state hashes were forged: the shape is valid, so it
        # parses, but the re-execution does not produce these hashes.
        forged = _genuine_episode(manifest, spec, _ACTIONS)
        forged["transitions"][0]["state_digest"] = _A_DIGEST.model_dump(mode="json")
        socket.send_json(_capture_frame(manifest, spec, episode=forged))
        assert socket.receive_json()["ack"]["ack_kind"] == "parsed"
        error = socket.receive_json()

    assert error["type"] == "error"
    assert error["category"] == "validation"


def test_a_malformed_client_run_is_refused_without_advancing() -> None:
    """A run that breaks the contract is refused with a safe validation error."""
    app = build_demo_app(
        store=InMemoryStore(),
        gateway=Gateway(),
        browser_game=mountain_car_browser_spec(),
    )
    client = TestClient(app)
    with client.websocket_connect("/ws") as socket:
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
        assert socket.receive_json()["delivery"]["mode"] == "browser"

        bad: dict[str, Any] = {
            "type": "command",
            "command": _command("7", "game.capture").model_dump(
                mode="json", exclude_none=True
            ),
            "payload": {
                "episode": {"transitions": "not-a-list", "boundary": {}},
                "generation": 1,
            },
        }
        socket.send_json(bad)
        assert socket.receive_json()["ack"]["ack_kind"] == "parsed"
        error = socket.receive_json()

    assert error["type"] == "error"
    assert error["category"] == "validation"
