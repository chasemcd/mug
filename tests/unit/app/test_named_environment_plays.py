"""A study names its environment, and a participant plays it end to end.

``tests/unit/app/test_mount_resolution.py`` proves the resolution; this proves the
run. A study writes one ``Game`` line with the environment it trained in and a
drawing, and nothing else -- no specification, no environment factory of the
platform's own shape, no frame rate, no episode bound, no package pin, no seat map --
and a participant connects, plays, and leaves a recorded run behind.

That is the whole requirement in one test. The study below is what an author writes,
and every line of it is a decision about the study rather than about the platform.
"""

from __future__ import annotations

import functools
import json
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from mug.app import build_study_app
from mug.content import Game, Page, Study, flow_of
from mug.content.players import Human
from mug.export import export_visit
from mug.game.env import StepResult
from mug.game.surface import Surface
from mug.gateway import Gateway
from mug.storage import InMemoryStore

gymnasium = pytest.importorskip("gymnasium", reason="the game extra is not installed")


def hill(rounds_of: int = 4) -> Any:
    """Build MountainCar, as a study author names the environment they trained in.

    ``max_episode_steps`` is bound here because a study author binds what their own
    environment needs. It is short so the test is quick; nothing about the platform
    changes with the number, which is the point -- whatever it is, it is read.
    """
    return functools.partial(
        gymnasium.make, "MountainCar-v0", max_episode_steps=rounds_of
    )


def draw_hill(surface: Surface, step: StepResult) -> None:
    """Draw the car on the hill. This is the only platform-shaped thing left."""
    observed = cast("list[float]", step.observation)
    where = (float(observed[0]) + 1.2) / 1.8
    surface.rect(x=0.0, y=0.9, w=1.0, h=0.1, color="#964b00", object_id="ground")
    surface.circle(x=where, y=0.85, radius=0.03, color="#1b6ac9", object_id="car")


def score(step: StepResult) -> str:
    """Say what the participant is told while they play."""
    return f"Reward so far: {step.reward:.0f}"


def _study(rounds_of: int = 4) -> Study:
    """Return the study an author writes. Read it: this is the whole surface.

    The game is first so the test reaches it on the opening delivery. What comes
    before a game is a form and a page, and neither is what is under test here.
    """
    return Study(
        Game(
            "drive",
            hill(rounds_of),
            seats={"agent": Human()},
            render=draw_hill,
            hud=score,
            caption="Hold the arrow keys to rock the car.",
        ),
        Page("debrief", "# Thank you"),
    )


def _client(store: InMemoryStore, study: Study) -> TestClient:
    return TestClient(build_study_app(study=study, store=store, gateway=Gateway()))


def _flow_id(store: InMemoryStore) -> str:
    found = [
        aggregate_id
        for aggregate_id, _ in store.scan_aggregates()
        if aggregate_id.startswith("visitplan_")
    ]
    assert len(found) == 1
    return found[0]


def _drain(socket: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Read every render frame of one round, and the message that follows them."""
    frames: list[dict[str, Any]] = []
    for _ in range(200):
        message = cast("dict[str, Any]", socket.receive_json())
        if message["type"] != "render":
            return frames, message
        frames.append(message)
    raise AssertionError("the round never ended")


def test_a_study_that_only_names_its_environment_is_played_and_recorded() -> None:
    """The requirement: hand over the environment, and MUG does the rest."""
    store = InMemoryStore()
    client = _client(store, _study())
    with client.websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        assert socket.receive_json()["delivery"]["activity_key"] == "drive"
        frames, after = _drain(socket)
        flow_id = _flow_id(store)

    # The environment stepped, the study's drawing was painted, and the flow moved on.
    assert frames, "the game activity produced no frame at all"
    assert after["delivery"]["activity_key"] == "debrief"
    painted = {
        one["op"] for frame in frames for one in frame["packet"]["commands"]
    }
    assert {"rect", "circle"} <= painted
    # The status line is drawn onto the same surface, so what the participant was told
    # is in the record and in a replay rather than beside it.
    assert "text" in painted

    rows = [
        json.loads(line) for line in export_visit(store, flow_id).jsonl.splitlines()
    ]
    boundaries = [
        row
        for row in rows
        if row["event_schema"]["name"] == "mug.api-07.episode-boundary"
    ]
    assert len(boundaries) == 1

    state = flow_of(store.load_aggregate(flow_id))
    assert state is not None
    assert [one.activity_key for one in state.activities] == ["drive", "debrief"]


def test_the_episode_bound_is_the_environments_own() -> None:
    """The round ends where the environment says, not where the study guessed.

    It was a hand-written field on every specification, and a study that wrote the
    wrong number got a round that ended early or never -- with nothing to compare it
    against, because the number the study wrote *was* the platform's belief.
    """
    assert _study(4).game_activities["drive"].found.max_steps == 4
    assert _study(9).game_activities["drive"].found.max_steps == 9

    store = InMemoryStore()
    client = _client(store, _study(4))
    with client.websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        assert socket.receive_json()["delivery"]["activity_key"] == "drive"
        frames, _after = _drain(socket)

    # The opening frame plus the bound the environment declared, and no more.
    assert len(frames) <= 5


def test_the_frame_rate_is_the_environments_own() -> None:
    """One more field that was written twice and is a fact about the environment."""
    assert _study().game_activities["drive"].found.fps == 30


def test_a_study_still_writes_no_package_pin() -> None:
    """The pin is the installed version, so a browser run cannot ask for another."""
    assert _study().requires == (f"gymnasium=={gymnasium.__version__}",)
