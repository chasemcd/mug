"""A study may play more than one game, and each round is its own episode.

A practice round before the real one is an ordinary study design, and it used to
be refused: every game activity shared one run identity, so a second round would
have been recorded over the first. These tests drive the whole application over
studies with two game activities and check what the ledger holds afterwards --
two episodes, two identities, both on the visit -- in the two single-participant
execution modes.

Each round may also run its own settings. The study names them on the activity
(``Game("practice", spec)``), so a short practice round and a full round are one
study and one mount.
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

from fastapi.testclient import TestClient

from examples.mountain_car.browser_env import mountain_car_browser_spec
from examples.mountain_car.native_env import mountain_car_spec
from mug.app import build_study_app
from mug.client import RealtimeCommand
from mug.content import Choice, Form, Game, Page, Study, flow_of
from mug.export import export_visit
from mug.game.browser import BrowserGameSpec
from mug.game.determinism import state_hash
from mug.game.env import GymEnv
from mug.gateway import Gateway
from mug.kernel import Digest, SchemaRef
from mug.storage import InMemoryStore

_A_DIGEST = Digest(algorithm="sha-256", hex="a" * 64)
_PRACTICE_ACTIONS = [1, 0]
_REAL_ACTIONS = [0, 2, 1]


def _two_round_study() -> Study:
    """The study under test: instructions, practice, a check, then the real round."""
    return Study(
        Page("instructions", "# You will play twice"),
        Game("practice"),
        Form("check", Choice("ready", "Ready for the real round?", ["yes", "no"])),
        Game("play"),
        Page("debrief", "# Thank you"),
    )


def _command(tag: str, channel: str) -> dict[str, Any]:
    return RealtimeCommand(
        command_id=f"command_019b6000-0000-7000-8000-00000000000{tag}",
        channel_key=channel,
        intent_schema=SchemaRef(name="mug.demo.intent", version=0, digest=_A_DIGEST),
        payload_digest=_A_DIGEST,
        idempotency_key="idem_" + tag.ljust(21, "0") + "A",
        submitted_at="2026-07-21T00:00:00.000000Z",
    ).model_dump(mode="json", exclude_none=True)


def _advance(answers: dict[str, Any], tag: str) -> dict[str, Any]:
    return {
        "type": "command",
        "command": _command(tag, "flow.advance"),
        "payload": {"answers": answers},
    }


# -- the server execution mode --------------------------------------------------


def test_two_server_rounds_are_two_episodes_on_one_visit() -> None:
    """The participant plays twice; the visit carries both runs, not one."""
    store = InMemoryStore()
    game = replace(mountain_car_spec(), fps=0, max_steps=3, countdown_seconds=0)
    client = TestClient(
        build_study_app(
            study=_two_round_study(), store=store, gateway=Gateway(), game=game
        )
    )
    with client.websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        assert socket.receive_json()["delivery"]["kind"] == "content"

        socket.send_json(_advance({}, tag="1"))
        assert socket.receive_json()["ack"]["ack_kind"] == "parsed"
        assert socket.receive_json()["ack"]["ack_kind"] == "accepted"
        practice = socket.receive_json()["delivery"]
        practice_frames = [socket.receive_json() for _ in range(4)]
        assert socket.receive_json()["delivery"]["form"]["form_key"] == "check"

        socket.send_json(_advance({"ready": "yes"}, tag="2"))
        assert socket.receive_json()["ack"]["ack_kind"] == "parsed"
        assert socket.receive_json()["ack"]["ack_kind"] == "accepted"
        real = socket.receive_json()["delivery"]
        real_frames = [socket.receive_json() for _ in range(4)]
        debrief = socket.receive_json()["delivery"]

        flow_id = _flow_id(store)

    assert practice["activity_key"] == "practice"
    assert real["activity_key"] == "play"
    assert all(frame["type"] == "render" for frame in [*practice_frames, *real_frames])
    assert debrief["kind"] == "content"

    # Both rounds were captured, each on its own stream under its own identity.
    assert len(_recorded_episodes(store)) == 2
    assert len(set(_captured_streams(store, flow_id))) == 2
    assert _boundaries(store, flow_id) == 2


def test_a_practice_round_runs_the_settings_its_activity_names() -> None:
    """``Game("practice", spec)`` is how one round differs from another."""
    game = replace(mountain_car_spec(), fps=0, max_steps=5, countdown_seconds=0)
    study = Study(
        Game("practice", replace(game, max_steps=2)),
        Game("play"),
        Page("debrief", "# Thank you"),
    )
    client = TestClient(
        build_study_app(
            study=study, store=InMemoryStore(), gateway=Gateway(), game=game
        )
    )
    with client.websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        assert socket.receive_json()["delivery"]["activity_key"] == "practice"
        practice = [socket.receive_json() for _ in range(3)]
        assert socket.receive_json()["delivery"]["activity_key"] == "play"
        real = [socket.receive_json() for _ in range(6)]
        debrief = socket.receive_json()["delivery"]

    # The practice round stops at its own step cap; the real round runs the
    # mounted one. A shared specification would have made the two the same length.
    assert practice[-1]["packet"]["frame_number"] == 2
    assert real[-1]["packet"]["frame_number"] == 5
    assert debrief["kind"] == "content"


def test_a_study_may_name_the_game_itself_and_mount_nothing() -> None:
    """The whole game may live on the activity, so the study is the one place."""
    game = replace(mountain_car_spec(), fps=0, max_steps=2, countdown_seconds=0)
    study = Study(Game("play", game), Page("debrief", "# Thank you"))
    client = TestClient(
        build_study_app(study=study, store=InMemoryStore(), gateway=Gateway())
    )
    with client.websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        assert socket.receive_json()["delivery"]["activity_key"] == "play"
        frames = [socket.receive_json() for _ in range(3)]
        debrief = socket.receive_json()["delivery"]

    assert frames[-1]["packet"]["frame_number"] == 2
    assert debrief["kind"] == "content"


# -- the browser execution mode -------------------------------------------------


def _genuine_episode(
    manifest: dict[str, Any], spec: BrowserGameSpec, actions: list[int]
) -> dict[str, Any]:
    """Build the episode an honest client reports for one manifest."""
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


def _capture(
    manifest: dict[str, Any], spec: BrowserGameSpec, actions: list[int], tag: str
) -> dict[str, Any]:
    return {
        "type": "command",
        "command": _command(tag, "game.capture"),
        "payload": {
            "episode": _genuine_episode(manifest, spec, actions),
            "actions": actions,
            "generation": 1,
        },
    }


def test_two_browser_rounds_report_under_two_identities() -> None:
    """Each round announces its own episode, so the second is not the first again.

    This is the defect the single refusal used to stand in for: one identity for
    the whole connection meant a second reported run would have been written over
    the first.
    """
    store = InMemoryStore()
    spec = mountain_car_browser_spec()
    practice_spec = replace(spec, max_steps=2, countdown_seconds=0)
    study = Study(
        Game("practice", practice_spec),
        Game("play"),
        Page("debrief", "# Thank you"),
    )
    client = TestClient(
        build_study_app(study=study, store=store, gateway=Gateway(), browser_game=spec)
    )
    with client.websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"

        # The runtime is announced for the first game activity, so it boots ahead
        # of the round rather than at it.
        preload = socket.receive_json()["delivery"]
        first = socket.receive_json()["delivery"]

        socket.send_json(
            _capture(first["manifest"], practice_spec, _PRACTICE_ACTIONS, "3")
        )
        assert socket.receive_json()["ack"]["ack_kind"] == "parsed"
        assert socket.receive_json()["ack"]["ack_kind"] == "accepted"
        second = socket.receive_json()["delivery"]

        socket.send_json(_capture(second["manifest"], spec, _REAL_ACTIONS, "4"))
        assert socket.receive_json()["ack"]["ack_kind"] == "parsed"
        assert socket.receive_json()["ack"]["ack_kind"] == "accepted"
        debrief = socket.receive_json()["delivery"]

        flow_id = _flow_id(store)

    assert preload["kind"] == "preload"
    assert preload["manifest"]["episode_id"] == first["manifest"]["episode_id"]
    assert first["activity_key"] == "practice"
    assert second["activity_key"] == "play"
    assert first["manifest"]["episode_id"] != second["manifest"]["episode_id"], (
        "the second round announced the first round's episode"
    )
    assert first["manifest"]["max_steps"] == 2, "the practice round ran the real spec"
    assert second["manifest"]["max_steps"] == spec.max_steps
    # The practice round starts at once and the real one counts down, because each
    # round is announced from its own specification.
    assert (first["countdown"], second["countdown"]) == (0, spec.countdown_seconds)
    assert debrief["kind"] == "content"

    assert _recorded_episodes(store) == sorted(
        {first["manifest"]["episode_id"], second["manifest"]["episode_id"]}
    )
    assert len(set(_captured_streams(store, flow_id))) == 2
    assert _boundaries(store, flow_id) == 2


# -- reading what was recorded --------------------------------------------------


def _flow_id(store: InMemoryStore) -> str:
    """Return the one flow the run opened."""
    flows = [
        aggregate_id
        for aggregate_id, _ in store.scan_aggregates()
        if aggregate_id.startswith("visitplan_")
    ]
    assert len(flows) == 1
    return flows[0]


def _recorded_episodes(store: InMemoryStore) -> list[str]:
    """Return every episode the run committed, in order."""
    return sorted(
        aggregate_id
        for aggregate_id, _ in store.scan_aggregates()
        if aggregate_id.startswith("episode_")
    )


def _captured_streams(store: InMemoryStore, flow_id: str) -> list[str]:
    """Return the streams the visit recorded its runs on."""
    state = flow_of(store.load_aggregate(flow_id))
    assert state is not None
    return list(state.captured_streams)


def _boundaries(store: InMemoryStore, flow_id: str) -> int:
    """Return how many episode boundaries the visit's export carries.

    The export is payload-free -- a row is an event envelope, not its value -- so
    a round shows up as its boundary event on its own stream, not as an id to read
    out of the document.
    """
    rows: list[dict[str, Any]] = [
        json.loads(line) for line in export_visit(store, flow_id).jsonl.splitlines()
    ]
    boundary = "mug.api-07.episode-boundary"
    return sum(1 for row in rows if row["event_schema"]["name"] == boundary)
