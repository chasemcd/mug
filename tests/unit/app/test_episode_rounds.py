"""One game activity plays several rounds, with a screen between them.

Parity keeps "multiple episodes, reset transitions, limits, and inter-episode UI".
The platform ran one episode per game activity, so three rounds of one task meant
three activities -- three keys, three specifications to keep in step, and three
activities in the data where the study had one.

These tests hold four promises: three rounds are three episodes on **one**
activity; the participant reads a screen between them and the next round waits for
them; each round starts from the environment's own initial state rather than where
the last one stopped; and the three export as three trajectories.
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from examples.mountain_car.native_env import mountain_car_spec
from mug.app import build_study_app
from mug.content import Game, Page, Study, flow_of
from mug.export import export_visit
from mug.gateway import Gateway
from mug.storage import InMemoryStore


def _game() -> Any:
    """A three-step round that runs as fast as the loop allows."""
    return replace(mountain_car_spec(), fps=0, max_steps=3, countdown_seconds=0)


def _study(*, episodes: int, between: str | None = None) -> Study:
    return Study(
        Game("play", _game(), episodes=episodes, between=between),
        Page("debrief", "# Thank you"),
    )


def _client(store: InMemoryStore, study: Study) -> TestClient:
    return TestClient(build_study_app(study=study, store=store, gateway=Gateway()))


def _drain_round(socket: Any) -> list[dict[str, Any]]:
    """Read one round's render frames, up to the frame that follows them."""
    frames: list[dict[str, Any]] = []
    for _ in range(12):
        frame = cast("dict[str, Any]", socket.receive_json())
        if frame["type"] != "render":
            return [*frames, frame]
        frames.append(frame)
    raise AssertionError("the round never ended")


def _flow_id(store: InMemoryStore) -> str:
    found = [
        aggregate_id
        for aggregate_id, _ in store.scan_aggregates()
        if aggregate_id.startswith("visitplan_")
    ]
    assert len(found) == 1
    return found[0]


def _episodes(store: InMemoryStore) -> list[str]:
    return sorted(
        aggregate_id
        for aggregate_id, _ in store.scan_aggregates()
        if aggregate_id.startswith("episode_")
    )


def _trajectories(store: InMemoryStore, flow_id: str) -> list[dict[str, Any]]:
    """Return the trajectory rows one visit's export carries."""
    rows: list[dict[str, Any]] = [
        json.loads(line) for line in export_visit(store, flow_id).jsonl.splitlines()
    ]
    return [
        row
        for row in rows
        if row["event_schema"]["name"] == "mug.api-07.episode-boundary"
    ]


# -- several rounds, one activity ------------------------------------------------


def test_three_rounds_are_three_episodes_on_one_activity() -> None:
    """The proof: one activity, three episodes, three trajectories."""
    store = InMemoryStore()
    client = _client(store, _study(episodes=3, between="Rest a moment"))
    with client.websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        assert socket.receive_json()["delivery"]["activity_key"] == "play"
        # The screen names the round that is about to start, which is what a
        # participant reading "Round 2 of 3" is being told.
        for round_number in (2, 3):
            interval = _drain_round(socket)[-1]
            assert interval["type"] == "interval"
            assert interval["round"] == round_number
            assert interval["of"] == 3
            assert interval["markdown"] == "Rest a moment"
            socket.send_json({"type": "interval_done"})
        debrief = _drain_round(socket)[-1]
        flow_id = _flow_id(store)

    assert debrief["delivery"]["kind"] == "content"
    assert len(_episodes(store)) == 3
    assert len(_trajectories(store, flow_id)) == 3

    # All three are on the one activity the author wrote, which is the point.
    state = flow_of(store.load_aggregate(flow_id))
    assert state is not None
    assert [one.activity_key for one in state.activities] == ["play", "debrief"]
    assert len(set(state.captured_streams)) == 3


def test_one_round_is_what_a_study_that_says_nothing_gets() -> None:
    """Every study that predates rounds plays exactly one, and reads no screen."""
    store = InMemoryStore()
    client = _client(store, _study(episodes=1))
    with client.websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        assert socket.receive_json()["delivery"]["activity_key"] == "play"
        after = _drain_round(socket)[-1]

    assert after["type"] == "delivery"
    assert after["delivery"]["kind"] == "content"
    assert len(_episodes(store)) == 1


def test_the_next_round_waits_for_the_participant() -> None:
    """The interval is participant-paced: nothing steps while they are reading."""
    store = InMemoryStore()
    client = _client(store, _study(episodes=2, between="Take your time"))
    with client.websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        assert socket.receive_json()["delivery"]["activity_key"] == "play"
        assert _drain_round(socket)[-1]["type"] == "interval"

        # The second round has not run: one episode is recorded, not two.
        assert len(_episodes(store)) == 1

        socket.send_json({"type": "interval_done"})
        assert _drain_round(socket)[-1]["delivery"]["kind"] == "content"

    assert len(_episodes(store)) == 2


def test_each_round_starts_the_environment_again() -> None:
    """The reset protocol: a round begins where the environment begins."""
    store = InMemoryStore()
    client = _client(store, _study(episodes=2, between="Again"))
    with client.websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        assert socket.receive_json()["delivery"]["activity_key"] == "play"
        first = _drain_round(socket)
        socket.send_json({"type": "interval_done"})
        second = _drain_round(socket)

    # Both rounds count their own frames from zero, and both reach the same cap.
    def frames(round_frames: list[dict[str, Any]]) -> list[int]:
        return [
            one["packet"]["frame_number"]
            for one in round_frames
            if one["type"] == "render"
        ]

    assert frames(first) == [0, 1, 2, 3]
    assert frames(second) == [0, 1, 2, 3]


def test_a_participant_who_leaves_in_the_interval_keeps_what_they_played() -> None:
    """A round already played is already recorded; leaving costs the rest, not it."""
    store = InMemoryStore()
    client = _client(store, _study(episodes=3, between="Rest"))
    with client.websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        assert socket.receive_json()["delivery"]["activity_key"] == "play"
        assert _drain_round(socket)[-1]["type"] == "interval"

    assert len(_episodes(store)) == 1


def test_a_study_that_asks_for_no_rounds_is_refused() -> None:
    """An activity that plays zero times is an activity nobody meets."""
    with pytest.raises(ValueError, match="at least one round"):
        Study(Game("play", episodes=0), Page("debrief", "# Thank you"))
