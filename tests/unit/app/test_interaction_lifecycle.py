"""An interaction says how it ended, and an operator can read what is happening.

Nothing committed an ``Interaction`` to the store, so there were no terminal
reasons, no durable lifecycle projection, and no operator view: the legacy admin
dashboard was the only thing that had ever answered "how many people are playing
right now". A study could not say whether a session ended because the participant
finished or because their partner dropped.

These tests hold four promises: an interaction is recorded when it opens; it
finalizes with a reason from a closed set; a partner who drops mid-game ends the
interaction as ``partner_lost`` rather than as a completion; and an operator reads
the live and the completed interactions with **no external identity and no secret**
anywhere in the projection (parity fixture 10).
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any, cast

import httpx
import pytest
from fastapi.testclient import TestClient

from examples.mountain_car.native_env import mountain_car_spec
from mug.app import build_study_app
from mug.content import Game, Page, Study
from mug.gateway import Gateway
from mug.interactions.lifecycle import (
    TERMINAL_REASONS,
    finalize_interaction,
    interaction_of,
    lifecycle_of,
    open_interaction,
    operator_view,
)
from mug.interactions.types import Interaction
from mug.kernel import (
    DataHandlingRef,
    Digest,
    PrincipalRef,
    VersionStamp,
    WireCommandEnvelope,
    etag,
)
from mug.kernel.refs import StudyVersionRef
from mug.storage import InMemoryStore

_A_DIGEST = Digest(algorithm="sha-256", hex="a" * 64)
_RESEARCH = DataHandlingRef(privacy_labels=["research"])
_PARTICIPANT = PrincipalRef(
    kind="participant", id="participant_019b6000-0000-7000-8000-0000000000aa"
)
_VERSION = StudyVersionRef(
    study_id="study_019b6000-0000-7000-8000-0000000000c1",
    study_version_id="studyver_019b6000-0000-7000-8000-0000000000c2",
    version_number=1,
    manifest_digest=_A_DIGEST,
)
_INTERACTION = "interaction_019b6000-0000-7000-8000-0000000000d1"
_FIRST_VISIT = "visit_019b6000-0000-7000-8000-0000000000b1"
_SECOND_VISIT = "visit_019b6000-0000-7000-8000-0000000000b2"


def _get(client: TestClient, path: str) -> httpx.Response:
    """Fetch one path, typed, so an assertion reads a known response.

    The test client's own ``get`` is loosely typed, so the one cast is here rather
    than at every call site.
    """
    fetch = cast("Any", client).get
    return cast("httpx.Response", fetch(path))


def _two_seat_interaction() -> Interaction:
    body = {"interaction": _INTERACTION}
    return Interaction(
        interaction_id=_INTERACTION,
        study_version=_VERSION,
        visit_ids=[_FIRST_VISIT, _SECOND_VISIT],
        cast={
            "seat-1": "actor_019b6000-0000-7000-8000-0000000000e1",
            "seat-2": "actor_019b6000-0000-7000-8000-0000000000e2",
        },
        channels=["game"],
        status="active",
        version=VersionStamp(revision=1, etag=etag(body)),
    )


def _context(gateway: Gateway, aggregate_id: str, command: str, tag: str) -> Any:
    return gateway.mint(
        WireCommandEnvelope.model_validate(
            {
                "schema": {
                    "name": "mug.command-envelope",
                    "version": 0,
                    "digest": _A_DIGEST.model_dump(mode="json"),
                },
                "protocol_version": "0.1.0",
                "command": {"name": command, "version": 0},
                "request_id": "request_019b6000-0000-7000-8000-000000000001",
                "idempotency_key": "idem_" + tag * 21 + "A",
                "target": {"id": aggregate_id},
                "payload": {
                    "schema": {
                        "name": "mug.edge.payload",
                        "version": 0,
                        "digest": _A_DIGEST.model_dump(mode="json"),
                    },
                    "data": {"interaction_id": aggregate_id},
                },
            }
        ),
        principal=_PARTICIPANT,
        data_handling=_RESEARCH,
    )


# -- the record itself -----------------------------------------------------------


async def test_an_interaction_is_recorded_when_it_opens() -> None:
    """The frozen record is the head; when it opened sits beside it."""
    store = InMemoryStore()
    gateway = Gateway(secret=b"a-shared-deployment-secret------")

    assert await open_interaction(
        _two_seat_interaction(),
        activity_key="play",
        opened_at="2026-07-27T00:00:00.000000Z",
        context=_context(gateway, _INTERACTION, "interaction.open", "a"),
        store=store,
    )

    state = store.load_aggregate(_INTERACTION)
    interaction = interaction_of(state)
    lifecycle = lifecycle_of(state)
    assert interaction is not None
    assert interaction.status == "active"
    assert lifecycle is not None
    assert lifecycle.activity_key == "play"
    assert lifecycle.closed_at is None
    assert [one.visit_id for one in lifecycle.members] == [_FIRST_VISIT, _SECOND_VISIT]


async def test_a_partner_who_drops_is_told_apart_from_one_who_finished() -> None:
    """The reason names who left, so a dropout is not read as a bystander."""
    store = InMemoryStore()
    gateway = Gateway(secret=b"a-shared-deployment-secret------")
    await open_interaction(
        _two_seat_interaction(),
        activity_key="play",
        opened_at="2026-07-27T00:00:00.000000Z",
        context=_context(gateway, _INTERACTION, "interaction.open", "a"),
        store=store,
    )

    assert await finalize_interaction(
        interaction_id=_INTERACTION,
        reason="partner_lost",
        closed_at="2026-07-27T00:01:00.000000Z",
        context=_context(gateway, _INTERACTION, "interaction.finalize", "b"),
        store=store,
        left=[_SECOND_VISIT],
    )

    lifecycle = lifecycle_of(store.load_aggregate(_INTERACTION))
    interaction = interaction_of(store.load_aggregate(_INTERACTION))
    assert lifecycle is not None
    assert lifecycle.terminal_reason == "partner_lost"
    assert {one.visit_id: one.reason for one in lifecycle.members} == {
        _FIRST_VISIT: "completed",
        _SECOND_VISIT: "partner_lost",
    }
    assert interaction is not None
    assert interaction.status == "aborted"


async def test_the_first_ending_is_the_ending() -> None:
    """A second reason written over the first would be a story about the process."""
    store = InMemoryStore()
    gateway = Gateway(secret=b"a-shared-deployment-secret------")
    await open_interaction(
        _two_seat_interaction(),
        activity_key="play",
        opened_at="2026-07-27T00:00:00.000000Z",
        context=_context(gateway, _INTERACTION, "interaction.open", "a"),
        store=store,
    )
    await finalize_interaction(
        interaction_id=_INTERACTION,
        reason="partner_lost",
        closed_at="2026-07-27T00:01:00.000000Z",
        context=_context(gateway, _INTERACTION, "interaction.finalize", "b"),
        store=store,
        left=[_SECOND_VISIT],
    )

    assert not await finalize_interaction(
        interaction_id=_INTERACTION,
        reason="completed",
        closed_at="2026-07-27T00:02:00.000000Z",
        context=_context(gateway, _INTERACTION, "interaction.finalize", "c"),
        store=store,
    )

    lifecycle = lifecycle_of(store.load_aggregate(_INTERACTION))
    assert lifecycle is not None
    assert lifecycle.terminal_reason == "partner_lost"


async def test_a_reason_nobody_declared_is_refused() -> None:
    """Free text would become free text, and counting reasons is the point."""
    with pytest.raises(ValueError, match="not a terminal reason"):
        await finalize_interaction(
            interaction_id=_INTERACTION,
            reason="the wifi was bad",
            closed_at="2026-07-27T00:01:00.000000Z",
            context=_context(Gateway(), _INTERACTION, "interaction.finalize", "b"),
            store=InMemoryStore(),
        )


def test_the_terminal_reasons_are_a_closed_set() -> None:
    """What can happen to an interaction, stated once."""
    assert set(TERMINAL_REASONS) == {
        "completed",
        "partner_lost",
        "excluded",
        "abandoned",
        "timed_out",
        "operator_stopped",
        "error",
    }


# -- a real run ------------------------------------------------------------------


def _study(episodes: int = 1) -> Study:
    return Study(
        Game(
            "play",
            replace(mountain_car_spec(), fps=0, max_steps=2, countdown_seconds=0),
            episodes=episodes,
            between="Rest",
        ),
        Page("debrief", "# Thank you"),
    )


def _client(store: InMemoryStore) -> TestClient:
    return TestClient(
        build_study_app(study=_study(), store=store, gateway=Gateway())
    )


def _drain(socket: Any, until: str) -> dict[str, Any]:
    for _ in range(12):
        frame = cast("dict[str, Any]", socket.receive_json())
        if frame["type"] == until:
            return frame
    raise AssertionError(f"no {until} frame arrived")


def test_a_finished_game_records_a_completed_interaction() -> None:
    """A single-participant round is still an interaction, and it says it finished."""
    store = InMemoryStore()
    with _client(store).websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        assert socket.receive_json()["delivery"]["activity_key"] == "play"
        _drain(socket, "delivery")

    rows = operator_view(store)
    assert len(rows) == 1
    assert rows[0].status == "completed"
    assert rows[0].terminal_reason == "completed"
    assert rows[0].activity_key == "play"
    assert rows[0].participants == 1


def test_a_participant_who_leaves_between_rounds_ends_as_abandoned() -> None:
    """Leaving is not finishing, and the record is the difference."""
    store = InMemoryStore()
    client = TestClient(
        build_study_app(
            study=_study(episodes=3), store=store, gateway=Gateway()
        )
    )
    with client.websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        assert socket.receive_json()["delivery"]["activity_key"] == "play"
        assert _drain(socket, "interval")["type"] == "interval"

    rows = operator_view(store)
    assert len(rows) == 1
    assert rows[0].terminal_reason == "abandoned"
    assert rows[0].status == "aborted"


# -- what an operator reads -------------------------------------------------------


def test_the_operator_view_shows_the_live_and_the_completed() -> None:
    """The first question is what is happening; it is useful beside what happened."""
    store = InMemoryStore()
    client = _client(store)
    with client.websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        assert socket.receive_json()["delivery"]["activity_key"] == "play"
        _drain(socket, "delivery")

    response = _get(client, "/operator/interactions")
    body = cast("dict[str, Any]", response.json())

    assert body["total"] == 1
    assert body["live"] == 0
    assert body["interactions"][0]["terminal_reason"] == "completed"


def test_the_operator_view_carries_no_identity_and_no_secret() -> None:
    """Parity fixture 10: the projection is safe to read because it holds nothing.

    Every value in it is an internal pseudonymous identifier, a key the author
    wrote, a count, an instant, or a terminal reason. A participant's own text,
    their external identity, and any credential are all absent -- not redacted,
    absent, because the projection never reads them.
    """
    store = InMemoryStore()
    client = _client(store)
    with client.websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        assert socket.receive_json()["delivery"]["activity_key"] == "play"
        _drain(socket, "delivery")

    response = _get(client, "/operator/interactions")
    row = cast("dict[str, Any]", response.json())["interactions"][0]

    assert set(row) <= {
        "interaction_id",
        "status",
        "activity_key",
        "channels",
        "participants",
        "opened_at",
        "closed_at",
        "terminal_reason",
    }
    rendered = repr(row)
    for forbidden in ("prolific", "token", "secret", "ticket", "email", "principal"):
        assert forbidden not in rendered.lower()


def test_a_deployment_that_has_run_nothing_shows_nothing() -> None:
    """An empty answer is an answer, not an error."""
    client = TestClient(
        build_study_app(
            study=Study(Page("debrief", "# Thank you")),
            store=InMemoryStore(),
            gateway=Gateway(),
        )
    )

    response = _get(client, "/operator/interactions")
    assert response.json() == {
        "live": 0,
        "total": 0,
        "interactions": [],
    }


def test_an_open_interaction_reads_as_live() -> None:
    """A round still running is what an operator most wants to see."""
    store = InMemoryStore()
    gateway = Gateway(secret=b"a-shared-deployment-secret------")
    asyncio.run(
        open_interaction(
            _two_seat_interaction(),
            activity_key="play",
            opened_at="2026-07-27T00:00:00.000000Z",
            context=_context(gateway, _INTERACTION, "interaction.open", "a"),
            store=store,
        )
    )

    rows = operator_view(store)
    assert len(rows) == 1
    assert rows[0].closed_at is None
    assert rows[0].status == "active"
    assert rows[0].participants == 2
