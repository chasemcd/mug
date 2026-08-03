"""Fixture 3: a human and a heuristic policy in both browser and server execution.

The legacy runtime could run a study's environment on the server or in the
participant's browser, and a researcher chose between them without rewriting the
study. This fixture holds the new stack to that, and to the part that makes the
choice safe: **the same heuristic, in both modes, decides the same thing.**

The environment core and the partner's decision function are written once, in
``_environments.py``, and both modes are built from those two strings. Browser
execution runs the policy inside the shipped bundle; server execution seats it as
a ``Bot`` over the loop's own seat seam. Neither has a copy of its own.

The last test is the one that matters. It plays the same run in both modes and
compares the partner's actions frame by frame. If the two ever drift, a researcher
who moved a study from one mode to the other would silently change their
manipulation, and no other test here would notice.
"""

from __future__ import annotations

from typing import Any, cast

from _environments import (
    PARTNER,
    YOU,
    ServerHarvest,
    browser_spec,
    partner_controller,
    partner_policy,
)
from _participant import Participant, episodes, honest_browser_run
from fastapi.testclient import TestClient

from mug.app import build_study_app
from mug.content import Game, Page, Study
from mug.content.seats import Bot, Human, MultiSeatGame
from mug.game.env import GymEnv
from mug.gateway import Gateway
from mug.storage import InMemoryStore, Store

_LENGTH = 12
# The person holds no key for the whole run. That is not laziness: it is what lets
# the two modes be compared, because the only actor deciding anything is the
# heuristic, and any difference between the modes is the heuristic's.
_IDLE = [0] * _LENGTH


def _server_game() -> MultiSeatGame:
    """Return the environment the server loop steps, with nobody in it yet."""
    return MultiSeatGame(
        make_env=lambda: ServerHarvest(_LENGTH),
        channel_key="harvest",
        action_bindings={"ArrowUp": 1, "ArrowDown": 2, "ArrowLeft": 3, "ArrowRight": 4},
        default_action=0,
        decision_timeout=1.0,
        fps=0,
        max_steps=_LENGTH + 4,
    )


def _server_client(store: Store) -> TestClient:
    seats = {YOU: Human(), PARTNER: Bot(partner_controller())}
    study = Study(
        Game("play", _server_game(), seats=seats),
        Page("debrief", "# Thank you"),
    )
    return TestClient(build_study_app(study=study, store=store, gateway=Gateway()))


def _browser_client(store: Store) -> TestClient:
    study = Study(Game("play"), Page("debrief", "# Thank you"))
    return TestClient(
        build_study_app(
            study=study,
            store=store,
            gateway=Gateway(),
            browser_game=browser_spec(),
        )
    )


def _server_partner_actions(store: Store) -> list[int]:
    """Play the server run and return what the heuristic did on each frame."""
    client = _server_client(store)
    with client, client.websocket_connect("/ws") as socket:
        person = Participant(socket).handshake()
        assert person.delivery("game")["mode"] != "browser"
        frames, following = person.frames()
        assert following["delivery"]["kind"] == "content"
    return [int(frame["actions"][PARTNER]) for frame in frames]


def _browser_partner_actions() -> list[int]:
    """Run the shipped bundle and return what the heuristic did on each frame."""
    spec = browser_spec()
    namespace: dict[str, Any] = {}
    exec(spec.source_bundle, namespace)
    env = GymEnv(namespace["make_env"], seed=spec.seed)
    env.reset()
    return [int(env.step(action).info["partner_action"]) for action in _IDLE]


def test_the_heuristic_is_one_function_that_both_modes_are_built_from() -> None:
    """Neither mode carries a copy, so neither can drift from the other."""
    spec = browser_spec()
    namespace: dict[str, Any] = {}
    exec(spec.source_bundle, namespace)

    # The bundle the browser runs and the controller the server seats are built
    # from the same source text.
    assert "def partner_action(" in spec.source_bundle
    shipped = namespace["partner_action"]
    written = partner_policy()
    field = {"places": {"partner": [6, 6]}, "crop": [3, 3]}
    assert shipped(field) == written(field)
    assert partner_controller().decide(field) == written(field)


def test_a_person_plays_beside_the_heuristic_under_server_execution() -> None:
    """The server steps the run, and the heuristic supplies its seat's action."""
    store = InMemoryStore()
    actions = _server_partner_actions(store)

    assert len(actions) == _LENGTH, "the server stepped the whole run"
    assert all(one != 0 for one in actions), "the heuristic decided on every frame"
    assert len(episodes(store)) == 1


def test_a_person_plays_beside_the_heuristic_under_browser_execution() -> None:
    """The browser steps the run, and the same heuristic supplies the same seat."""
    store = InMemoryStore()
    client = _browser_client(store)
    with client, client.websocket_connect("/ws") as socket:
        person = Participant(socket).handshake()
        person.delivery("preload")
        game = person.delivery("game")
        assert game["mode"] == "browser"
        manifest = cast("dict[str, Any]", game["manifest"])
        run = honest_browser_run(manifest, browser_spec(), _IDLE)
        person.send("game.capture", {"episode": run, "actions": _IDLE, "generation": 1})
        assert person.delivery("content")["activity_key"] == "debrief"

    assert len(episodes(store)) == 1
    assert episodes(store)[0]["frame_count"] == _LENGTH


def test_the_two_modes_decide_the_same_thing_on_every_frame() -> None:
    """The parity claim itself: one study, two execution modes, one behaviour.

    A researcher moves a study from server execution to browser execution to take
    the load off their machines. If the partner behaved differently afterwards,
    they would have changed their experiment and nothing would have told them.
    """
    server = _server_partner_actions(InMemoryStore())
    browser = _browser_partner_actions()

    assert server == browser
    assert len(set(server)) > 1, "a constant policy would compare equal by accident"
