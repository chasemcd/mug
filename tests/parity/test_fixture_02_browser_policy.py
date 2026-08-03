"""Fixture 2: a human and a browser-side policy sharing an environment.

The partner decides **in the participant's own browser**, inside the bundle the
platform ships, beside the environment it acts in. No server steps this game and
no provider is reached; a participant with a working browser has a partner.

What the fixture proves:

- the person and the partner are in one environment, and the partner acts on every
  frame -- a partner that moved on no frame would be a partner in name only;
- the run the browser reports is verified by a server re-execution and captured;
- the partner's determinism is load-bearing rather than incidental. A browser-side
  partner that decided something else makes the whole run fail verification, which
  the last test states by making one do exactly that.
"""

from __future__ import annotations

from typing import Any, cast

from _environments import browser_spec
from _participant import Participant, episodes, honest_browser_run
from fastapi.testclient import TestClient

from mug.app import build_study_app
from mug.content import Game, Page, Study
from mug.game.env import GymEnv
from mug.gateway import Gateway
from mug.storage import InMemoryStore, Store

# The person walks a little way and then waits. They deliberately do not race the
# partner for the crop, so the fixture can watch the partner take it -- and watch
# the person's own field change because of what somebody else did.
_ACTIONS = [4, 4, 2, 2, 0, 0]


def _study() -> Study:
    return Study(
        Page("instructions", "# Gather the crop\n\nYour partner helps."),
        Game("play"),
        Page("debrief", "# Thank you"),
    )


def _client(store: Store) -> TestClient:
    return TestClient(
        build_study_app(
            study=_study(),
            store=store,
            gateway=Gateway(),
            browser_game=browser_spec(),
        )
    )


def _play(person: Participant, actions: list[int]) -> dict[str, Any]:
    """Walk one participant to the game and report an honest run of the bundle."""
    person.delivery("preload")
    assert person.delivery("content")["activity_key"] == "instructions"
    person.advance()
    game = person.delivery("game")
    assert game["mode"] == "browser"
    manifest = cast("dict[str, Any]", game["manifest"])
    run = honest_browser_run(manifest, browser_spec(), actions)
    person.send("game.capture", {"episode": run, "actions": actions, "generation": 1})
    return run


def test_the_partner_runs_in_the_bundle_and_acts_on_every_frame() -> None:
    """The partner is in the shipped source, and it is really in the environment."""
    spec = browser_spec()
    namespace: dict[str, Any] = {}
    exec(spec.source_bundle, namespace)
    assert "partner_action" in namespace, "the policy must ship with the environment"

    env = GymEnv(namespace["make_env"], seed=spec.seed)
    start = env.reset()
    places = [start.observation["places"]["partner"]]
    decided: list[int] = []
    for action in _ACTIONS:
        stepped = env.step(action)
        decided.append(int(stepped.info["partner_action"]))
        places.append(stepped.observation["places"]["partner"])

    assert len(decided) == len(_ACTIONS), "the partner decided on every frame"
    assert all(one != 0 for one in decided), "a partner that stood still is no partner"
    # It moved, so the environment the person plays in is not one they are alone in.
    assert places[0] != places[-1]
    assert spec.requires == (), "a browser partner must need no wheel of its own"


def test_a_person_and_the_browser_partner_share_one_recorded_run() -> None:
    """The capability, end to end: one environment, two actors, one capture."""
    store = InMemoryStore()
    client = _client(store)
    with client, client.websocket_connect("/ws") as socket:
        person = Participant(socket).handshake()
        run = _play(person, _ACTIONS)
        assert person.delivery("content")["activity_key"] == "debrief"

    recorded = episodes(store)
    assert len(recorded) == 1
    assert recorded[0]["channel_key"] == "harvest"
    assert recorded[0]["frame_count"] == len(_ACTIONS)
    transitions = cast("list[dict[str, Any]]", run["transitions"])
    assert {one["authority"] for one in transitions} == {"browser"}


def test_the_partner_scores_in_the_same_field_the_person_plays_in() -> None:
    """One field, one crop: what the partner takes, the person does not.

    This is what "sharing an environment" means, and it is worth stating on its
    own. A partner drawn beside the person but stepping its own copy would pass
    every other test here.
    """
    spec = browser_spec()
    namespace: dict[str, Any] = {}
    exec(spec.source_bundle, namespace)
    env = GymEnv(namespace["make_env"], seed=spec.seed)
    env.reset()
    crops = []
    last = None
    for action in _ACTIONS:
        last = env.step(action)
        crops.append(tuple(last.observation["crop"]))

    assert last is not None
    assert last.observation["scores"]["partner"] >= 1, "the partner never scored"
    # The crop moved when the partner took it, so the person's field changed
    # because of what the partner did.
    assert len(set(crops)) > 1


def test_a_browser_partner_that_decides_differently_fails_verification() -> None:
    """Determinism is the price of a browser-side partner, and it is enforced.

    The server verifies a browser run by executing the shipped bundle again. A
    partner whose decision was not reproducible would make an honest participant's
    run unverifiable, so the platform refuses the run rather than record a
    trajectory it cannot stand behind.
    """
    store = InMemoryStore()
    client = _client(store)
    with client, client.websocket_connect("/ws") as socket:
        person = Participant(socket).handshake()
        person.delivery("preload")
        person.delivery("content")
        person.advance()
        manifest = cast("dict[str, Any]", person.delivery("game")["manifest"])

        # A run that reports the frames of a *different* partner: the shape is
        # right, so it parses, but the re-execution does not produce these states.
        forged = honest_browser_run(manifest, browser_spec(), _ACTIONS)
        other = honest_browser_run(manifest, browser_spec(), [1, 1, 1, 3, 3, 3])
        forged["transitions"][2]["state_digest"] = other["transitions"][2][
            "state_digest"
        ]
        person.send(
            "game.capture",
            {"episode": forged, "actions": _ACTIONS, "generation": 1},
        )
        message = person.read()
        while message.get("type") == "ack":
            message = person.read()

    assert message["type"] == "error"
    assert message["category"] == "validation"
    assert episodes(store) == [], "an unverifiable run must record no episode"
