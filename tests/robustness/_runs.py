"""Whole runs, played for real, for the robustness suite to read afterwards.

Each helper here plays one complete study through the real application -- the
websocket, the flow, matchmaking where there is any, the stepping loop, and the
capture -- and hands back the store it wrote into. Nothing is stubbed on the
server side, because the point of every test in this directory is what the
deployment actually recorded.

These modules use ASD-STE100 Simplified Technical English.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import itertools
from collections.abc import Iterator, Sequence
from contextlib import ExitStack, contextmanager
from typing import Any, cast

from fastapi.testclient import TestClient

from mug.app import build_study_app
from mug.content import Game, Page, Study
from mug.content.seats import Human, MultiSeatGame
from mug.export import discover_streams, export_study_dataset
from mug.export.types import GitProvenanceRef
from mug.game.trajectory import TrajectoryFrame, read_trajectory
from mug.gateway import Gateway
from mug.kernel import compute_digest
from mug.kernel.refs import StudyVersionRef
from mug.runtime import read_ledger
from mug.storage import ArtifactStore, InMemoryStore, Store
from tests.parity._environments import PARTNER, YOU, ServerHarvest
from tests.parity._participant import Participant

# The study version and provenance an export is asked for. They are fixed, so two
# exports of one ledger can be compared byte for byte.
STUDY = StudyVersionRef(
    study_id="study_019b6000-0000-7000-8000-0000000000c1",
    study_version_id="studyver_019b6000-0000-7000-8000-0000000000c2",
    version_number=1,
    manifest_digest=compute_digest({"study": "robustness"}),
)
GIT = GitProvenanceRef(commit="c" * 40, dirty=False)

# The keys a person at a seat can hold, and what each one does. The harvest
# environment reads four directions and a wait.
BINDINGS = {"ArrowUp": 1, "ArrowDown": 2, "ArrowLeft": 3, "ArrowRight": 4}


def seated_game(length: int, *, fps: int = 0) -> MultiSeatGame:
    """Return the two-seat environment the server steps for two people."""
    return MultiSeatGame(
        make_env=lambda: ServerHarvest(length),
        channel_key="harvest",
        action_bindings=dict(BINDINGS),
        default_action=0,
        decision_timeout=1.0,
        fps=fps,
        max_steps=length + 4,
    )


def seated_study(length: int, *, rounds: int = 1, fps: int = 0) -> Study:
    """Return a study of one seated game and the page that follows it."""
    return Study(
        Game(
            "play",
            seated_game(length, fps=fps),
            seats={YOU: Human(), PARTNER: Human()},
            episodes=rounds,
            between="Take a moment, then start the next round.",
        ),
        Page("debrief", "# Thank you"),
    )


@contextmanager
def seated_session(study: Study) -> Iterator[tuple[TestClient, Store]]:
    """Serve one study over the real application and yield its client and store."""
    store: Store = InMemoryStore()
    client = TestClient(build_study_app(study=study, store=store, gateway=Gateway()))
    with client:
        yield client, store


@contextmanager
def people_at(client: TestClient, count: int) -> Iterator[list[Participant]]:
    """Connect that many participants and hand back each one's own socket."""
    with ExitStack() as stack:
        people = []
        for tag in range(1, count + 1):
            socket = stack.enter_context(client.websocket_connect("/ws"))
            people.append(Participant(socket, tag=tag).handshake())
        yield people


def play_the_seated_round(people: Sequence[Participant]) -> list[dict[str, Any]]:
    """Take everybody through one round of a seated game and return what followed."""
    for person in people:
        person.delivery("game")
    followed: list[dict[str, Any]] = []
    for person in people:
        _frames, after = person.frames()
        followed.append(after)
    return followed


# -- reading back what the run recorded ---------------------------------------------


def episodes_in(store: Store) -> list[dict[str, Any]]:
    """Return every episode aggregate the run recorded, oldest identifier first."""
    found = [
        cast("dict[str, Any]", state)
        for aggregate_id, state in store.scan_aggregates()
        if aggregate_id.startswith("episode_") and isinstance(state, dict)
    ]
    return sorted(found, key=lambda one: str(one.get("episode_id")))


def recorded_frames(store: Store, episode: dict[str, Any]) -> list[TrajectoryFrame]:
    """Read one episode's recorded values back out of the artifact it names."""
    reference = episode.get("trajectory")
    assert reference is not None, "the episode recorded no values at all"
    artifacts = cast("ArtifactStore", store)
    artifact_id = cast("dict[str, Any]", reference)["artifact_id"]
    data = off_loop(artifacts.read_artifact(str(artifact_id)))
    return read_trajectory(data)


def ledger_events(store: Store) -> list[Any]:
    """Return every canonical event the run appended, stream by stream."""
    return [
        event
        for stream in discover_streams(store)
        for event in read_ledger(store, stream)
    ]


def exported(store: Store) -> Any:
    """Export the whole ledger, the way the shipped command-line tool does."""
    artifacts = itertools.count(1)
    uploads = itertools.count(1)
    body = "019b6000-0000-7000-8000-{:012x}"
    return off_loop(
        export_study_dataset(
            store=store,
            artifacts=cast("ArtifactStore", store),
            study_version=STUDY,
            git_provenance=GIT,
            new_artifact_id=lambda: "artifact_" + body.format(0xA00 + next(artifacts)),
            new_upload_id=lambda: "upload_" + body.format(0xB00 + next(uploads)),
            now=lambda: "2026-07-28T00:00:00.000000Z",
        )
    )


def off_loop(work: Any) -> Any:
    """Run one coroutine, even where another test left a loop on this thread.

    A Playwright test in the same session leaves a running event loop behind, and
    ``asyncio.run`` refuses to start inside one. Everything run this way is
    self-contained -- a store read, a whole episode -- so it is safe on a worker
    thread; only the loop is in the way.
    """
    running = False
    with contextlib.suppress(RuntimeError):
        asyncio.get_running_loop()
        running = True
    if not running:
        return asyncio.run(work)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: asyncio.run(work)).result()


__all__ = [
    "BINDINGS",
    "GIT",
    "STUDY",
    "episodes_in",
    "exported",
    "ledger_events",
    "off_loop",
    "people_at",
    "play_the_seated_round",
    "recorded_frames",
    "seated_game",
    "seated_session",
    "seated_study",
]
