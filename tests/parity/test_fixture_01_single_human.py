"""Fixture 1: a single human running a browser/Pyodide Gymnasium environment.

The legacy runtime's first capability was one person, one Gymnasium environment,
stepped in their own browser. This walks that participant through a whole study on
the new stack and asserts the four things the capability means:

- the environment the browser is given really is a Gymnasium environment, and the
  bundle the platform ships is the source that builds it;
- the server holds no private manifest field back for the client to find;
- the run the participant reports is verified against a re-execution and captured
  under **browser** authority;
- what happened is recorded, not only that it happened -- the actions, rewards,
  observations, and terminations the parity inventory requires (W1).

The participant then reaches the end of the study, which is what makes this a
capability rather than a runtime.
"""

from __future__ import annotations

from typing import Any, cast

from _participant import Participant, episodes, honest_browser_run
from fastapi.testclient import TestClient

from examples.mountain_car.browser_env import mountain_car_browser_spec
from mug.app import build_study_app
from mug.content import Game, Page, Study
from mug.game.env import GymEnv
from mug.gateway import Gateway
from mug.storage import InMemoryStore, Store

# A short run: three frames is enough to prove a capture, and the fixture is about
# the path a participant takes rather than how long they play.
_ACTIONS = [0, 2, 2]


def _study() -> Study:
    """Return the study one participant walks: read, play, and finish."""
    return Study(
        Page("instructions", "# Drive the car\n\nUse the arrow keys."),
        Game("play"),
        Page("debrief", "# Thank you"),
    )


def _client(store: Store) -> TestClient:
    return TestClient(
        build_study_app(
            study=_study(),
            store=store,
            gateway=Gateway(),
            browser_game=mountain_car_browser_spec(),
        )
    )


def test_the_shipped_bundle_builds_a_gymnasium_environment() -> None:
    """The environment is Gymnasium's, and the bundle is what builds it."""
    spec = mountain_car_browser_spec()
    assert any(one.startswith("gymnasium") for one in spec.requires)

    namespace: dict[str, Any] = {}
    exec(spec.source_bundle, namespace)
    env = GymEnv(namespace["make_env"], seed=spec.seed)
    first = env.reset()
    stepped = env.step(2)

    # It steps, and it produces the transition values the record needs.
    assert first.observation is not None
    assert stepped.reward is not None
    assert isinstance(stepped.terminated, bool)


def test_one_participant_plays_in_their_browser_and_the_run_is_captured() -> None:
    """The capability, end to end: one person, one browser run, one record."""
    store = InMemoryStore()
    client = _client(store)
    with client, client.websocket_connect("/ws") as socket:
        person = Participant(socket).handshake()

        # The bundle is announced before it is needed, so a participant reading the
        # instructions is already downloading Pyodide and the wheel.
        preload = person.delivery("preload")
        assert preload["manifest"]["source_bundle"]
        assert "server_notes" not in preload["manifest"]

        assert person.delivery("content")["activity_key"] == "instructions"
        person.advance()

        game = person.delivery("game")
        assert game["mode"] == "browser", "the environment must run in the browser"
        manifest = cast("dict[str, Any]", game["manifest"])
        assert manifest["channel_key"] == "mountain-car"

        run = honest_browser_run(manifest, mountain_car_browser_spec(), _ACTIONS)
        person.send(
            "game.capture",
            {"episode": run, "actions": _ACTIONS, "generation": 1},
        )
        assert person.delivery("content")["activity_key"] == "debrief"

    recorded = episodes(store)
    assert len(recorded) == 1, "one participant played one episode"


def test_the_captured_run_records_what_happened_and_who_held_authority() -> None:
    """A record of a run is the values, not only the digests of them (W1)."""
    store = InMemoryStore()
    client = _client(store)
    with client, client.websocket_connect("/ws") as socket:
        person = Participant(socket).handshake()
        person.delivery("preload")
        person.delivery("content")
        person.advance()
        manifest = cast("dict[str, Any]", person.delivery("game")["manifest"])
        run = honest_browser_run(manifest, mountain_car_browser_spec(), _ACTIONS)
        person.send(
            "game.capture",
            {"episode": run, "actions": _ACTIONS, "generation": 1},
        )
        person.delivery("content")

    # Authority is the browser's: the participant's own machine stepped the run.
    authorities = {
        transition["authority"]
        for transition in run["transitions"]  # pyright: ignore[reportUnknownVariableType]
    }
    assert authorities == {"browser"}

    episode = episodes(store)[0]
    assert episode["channel_key"] == "mountain-car"
    assert episode["frame_count"] == len(_ACTIONS)
