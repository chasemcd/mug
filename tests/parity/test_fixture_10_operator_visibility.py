"""Fixture 10: an operator watches, and identity and secrets are absent.

A deployment operator's first question is what is happening right now, and their
second is what happened earlier. Both are answered by one read-only projection
over durable state. The parity document adds the condition that makes the
projection safe to open to somebody who is not on the ethics protocol: **the
apart-stored external identity and the secret material stay out of it.**

That condition is easy to pass by accident. A store with no external identity in
it leaks none, so a test that links nobody and then finds no identity has proved
nothing at all. This fixture therefore puts a real recruitment id into the
deployment first -- blinded and linked exactly as ``mug publish`` would -- and only
then reads the operator's view. What is absent is absent because the projection
never reads it, not because there was nothing to read.
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import replace
from typing import Any, cast

from _participant import Participant
from fastapi.testclient import TestClient

from examples.mountain_car.native_env import mountain_car_spec
from mug.app import build_study_app
from mug.content import Game, Page, Study
from mug.gateway import Gateway
from mug.interactions.lifecycle import operator_view
from mug.kernel import PrincipalRef
from mug.linking import provision_identity_link
from mug.storage import InMemoryStore, Store

_SECRET = b"a-shared-deployment-secret------"
_BLINDING = b"a-server-blinding-key-of-some-length"
_RESEARCHER = PrincipalRef(
    kind="researcher", id="researcher_019b6000-0000-7000-8000-0000000000ab"
)
_ENROLLMENT = "enrollment_019b6000-0000-7000-8000-000000000050"
# A realistic recruitment-platform id. It must appear nowhere an operator reads.
_PROLIFIC_PID = "60fd1a2b3c4d5e6f7a8b9c0d"


def _study(episodes: int = 1) -> Study:
    return Study(
        Game(
            "play",
            replace(mountain_car_spec(), fps=0, max_steps=2, countdown_seconds=0),
            episodes=episodes,
            between="Rest a moment",
        ),
        Page("debrief", "# Thank you"),
    )


def _client(store: Store, gateway: Gateway, episodes: int = 1) -> TestClient:
    return TestClient(
        build_study_app(study=_study(episodes), store=store, gateway=gateway)
    )


def _link_a_recruitment_id(store: Store, gateway: Gateway) -> None:
    """Put a real external identity into the deployment, the way a study does.

    It runs on a thread of its own. ``asyncio.run`` refuses to start inside a
    running loop, and another test in the same session may well have left one on
    this thread -- so a fixture that only passed when it was run alone would be a
    fixture that proved nothing about the whole suite.
    """
    failure: list[BaseException] = []

    def link() -> None:
        try:
            asyncio.run(
                provision_identity_link(
                    gateway,
                    store,
                    researcher=_RESEARCHER,
                    enrollment_id=_ENROLLMENT,
                    provider="prolific",
                    external_id=_PROLIFIC_PID,
                    blinding_key=_BLINDING,
                )
            )
        except BaseException as problem:  # re-raised on the calling thread
            failure.append(problem)

    worker = threading.Thread(target=link)
    worker.start()
    worker.join(timeout=30)
    if failure:
        raise failure[0]
    assert not worker.is_alive(), "the identity link never finished"


def _play_one_round(client: TestClient) -> None:
    """Walk one participant through the game to the end of the study."""
    with client, client.websocket_connect("/ws") as socket:
        person = Participant(socket).handshake()
        assert person.delivery("game")["activity_key"] == "play"
        person.frames()


def _operator_reads(client: TestClient) -> dict[str, Any]:
    """Return the body of the operator's read-only view."""
    response = client.get("/operator/interactions")
    assert response.status_code == 200
    return cast("dict[str, Any]", response.json())


def test_an_operator_sees_a_finished_interaction_and_why_it_ended() -> None:
    """What happened, and how it ended, for a run a participant really played."""
    store, gateway = InMemoryStore(), Gateway(secret=_SECRET)
    _play_one_round(_client(store, gateway))

    rows = operator_view(store)
    assert len(rows) == 1
    assert rows[0].status == "completed"
    assert rows[0].terminal_reason == "completed"
    assert rows[0].activity_key == "play"
    assert rows[0].participants == 1


def test_an_operator_sees_a_run_that_is_still_going_as_live() -> None:
    """The first question an operator asks is about now, not about last week."""
    store, gateway = InMemoryStore(), Gateway(secret=_SECRET)
    client = _client(store, gateway, episodes=3)
    with client, client.websocket_connect("/ws") as socket:
        person = Participant(socket).handshake()
        assert person.delivery("game")["activity_key"] == "play"
        # Stop between rounds, so the interaction is open while it is read.
        for _ in range(20):
            if person.read().get("type") == "interval":
                break
        live = _operator_reads(client)

    assert live["live"] == 1
    assert live["total"] == 1
    # An open interaction has no closing instant at all, rather than a null one:
    # the projection carries what is known and says nothing about what is not.
    assert live["interactions"][0].get("closed_at") is None
    assert live["interactions"][0].get("terminal_reason") is None


def test_a_participant_who_left_reads_as_abandoned_rather_than_finished() -> None:
    """Leaving is not finishing, and an operator must be able to tell them apart."""
    store, gateway = InMemoryStore(), Gateway(secret=_SECRET)
    client = _client(store, gateway, episodes=3)
    with client, client.websocket_connect("/ws") as socket:
        person = Participant(socket).handshake()
        assert person.delivery("game")["activity_key"] == "play"
        for _ in range(20):
            if person.read().get("type") == "interval":
                break

    rows = operator_view(store)
    assert len(rows) == 1
    assert rows[0].terminal_reason == "abandoned"
    assert rows[0].status == "aborted"


def test_a_linked_recruitment_id_is_absent_from_everything_an_operator_reads() -> None:
    """The condition that makes the view safe, tested against a store that has one.

    The external id is really in this deployment: it was blinded and linked, and
    the enrolment can be resolved from it. None of that reaches the operator,
    because the projection is built from interaction records and reads no identity
    at all.
    """
    store, gateway = InMemoryStore(), Gateway(secret=_SECRET)
    _link_a_recruitment_id(store, gateway)
    client = _client(store, gateway)
    _play_one_round(client)

    body = _operator_reads(client)
    rendered = repr(body)

    assert body["total"] == 1
    assert _PROLIFIC_PID not in rendered
    assert "prolific" not in rendered.lower()
    for forbidden in ("token", "secret", "ticket", "email", "principal", "enrollment"):
        assert forbidden not in rendered.lower(), f"{forbidden!r} reached an operator"


def test_the_projection_carries_only_the_fields_it_declares() -> None:
    """Absence is kept by a whitelist, so a new private field cannot leak by default.

    A projection that copied a record and deleted what it did not want would start
    leaking the day somebody added a field. This one names what it carries.
    """
    store, gateway = InMemoryStore(), Gateway(secret=_SECRET)
    _link_a_recruitment_id(store, gateway)
    client = _client(store, gateway)
    _play_one_round(client)

    row = cast("dict[str, Any]", _operator_reads(client)["interactions"][0])
    assert set(row) == {
        "interaction_id",
        "status",
        "activity_key",
        "channels",
        "participants",
        "opened_at",
        "closed_at",
        "terminal_reason",
    }


def test_the_view_needs_no_participant_and_answers_an_empty_deployment() -> None:
    """A deployment that has run nothing answers nothing, rather than failing."""
    client = TestClient(
        build_study_app(
            study=Study(Page("debrief", "# Thank you")),
            store=InMemoryStore(),
            gateway=Gateway(secret=_SECRET),
        )
    )
    assert _operator_reads(client) == {"live": 0, "total": 0, "interactions": []}
