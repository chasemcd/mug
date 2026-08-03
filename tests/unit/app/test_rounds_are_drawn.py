"""Every round is drawn whole, and the picture is the size the study drew it.

A drawing travels as a delta. A command marked persistent is sent once, kept by the
renderer between frames, and never sent again until it changes -- which is what makes
a room of a thousand static tiles cost one frame rather than every frame. The
server's memory of what the far end already holds is a ``Surface``.

The rest between two rounds throws the far end's drawing away: the client tears the
canvas down, and the round after it builds a new one that holds nothing. A surface
carried across that rest is a memory of a canvas that no longer exists, and it holds
back exactly the things that are drawn once -- the whole room. So the second round
opened with nothing on the floor but the things that move, and a study of several
rounds recorded a participant playing a kitchen they could not see.

It survived a browser walk that watched all three rounds, because the walk asked
whether each round painted **anything**: two chefs on an empty floor are thirteen
thousand pixels and the floor was five hundred. What is asked here instead is that
each round is sent the whole scene.

How large the picture is, is the other half. A drawing is made of relative
coordinates, so it has no size of its own: it fills whatever it is given, and only
the study knows how large that should be.

These modules use ASD-STE100 Simplified Technical English.
"""

from __future__ import annotations

from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketTestSession

from mug.app import build_study_app
from mug.content import Bot, Game, Human, Page, Study
from mug.content.seats import MultiSeatGame
from mug.game.surface import Surface
from mug.gateway import Gateway
from mug.storage import InMemoryStore

_ROUNDS = 3

# What the room is made of: the squares drawn once and kept.
_TILES = 6


def _draw(surface: Surface, state: Any) -> None:
    """Draw a room that is sent once and one thing that moves every frame."""
    for index in range(_TILES):
        surface.rect(
            x=index / _TILES,
            y=0.0,
            w=1 / _TILES,
            h=0.5,
            color="#8b6b3f",
            object_id=f"tile-{index}",
            persistent=True,
        )
    at = float(state.info.get("at", 0)) / 10.0
    surface.circle(x=at, y=0.75, radius=0.05, color="#2d6cdf", object_id="walker")


class _Idle:
    """The other seat, which stands still. It is a bot so one person may play."""

    def decide(self, observation: object) -> int:
        return 1


class _TwoSeats:
    """The smallest two-seat environment: it ends after four frames."""

    AGENTS = ("one", "two")

    def __init__(self) -> None:
        self._t = 0

    def reset(self) -> Any:
        from mug.game.multiseat import MultiStepResult

        self._t = 0
        return MultiStepResult(
            observations={one: [0.0] for one in self.AGENTS},
            rewards=dict.fromkeys(self.AGENTS, 0.0),
            terminated=False,
            truncated=False,
            info={"at": 0},
        )

    def step(self, actions: Any) -> Any:
        from mug.game.multiseat import MultiStepResult

        self._t += 1
        return MultiStepResult(
            observations={one: [float(self._t)] for one in self.AGENTS},
            rewards=dict.fromkeys(self.AGENTS, 0.0),
            terminated=self._t >= 4,
            truncated=False,
            info={"at": self._t},
        )


def _kitchen() -> Any:
    """Return a two-seat environment that ends after a few frames."""
    return MultiSeatGame(
        make_env=_TwoSeats,
        render=_draw,
        channel_key="two-seats",
        fps=0,
        max_steps=4,
        default_action=1,
    )


def _study(*, size: tuple[int, int] | None = None) -> Study:
    return Study(
        Game(
            "play",
            _kitchen(),
            seats={"one": Human(), "two": Bot(_Idle())},
            episodes=_ROUNDS,
            between="Rest",
            size=size,
        ),
        Page("debrief", "# Thanks"),
    )


def _client(store: InMemoryStore, study: Study) -> TestClient:
    return TestClient(build_study_app(study=study, store=store, gateway=Gateway()))


def _read_until(
    socket: WebSocketTestSession, kind: str, limit: int = 400
) -> dict[str, Any]:
    for _ in range(limit):
        frame = cast("dict[str, Any]", socket.receive_json())
        if frame.get("type") == kind:
            return frame
    raise AssertionError(f"no {kind!r} frame arrived")


def _walk(socket: WebSocketTestSession) -> list[list[dict[str, Any]]]:
    """Play every round, and return the render packets of each one in order."""
    assert socket.receive_json()["type"] == "handshake_ack"
    rounds: list[list[dict[str, Any]]] = [[]]
    for _ in range(600):
        frame = cast("dict[str, Any]", socket.receive_json())
        if frame.get("type") == "render":
            rounds[-1].append(frame["packet"])
        elif frame.get("type") == "interval":
            rounds.append([])
            socket.send_json({"type": "interval_done"})
        elif frame.get("type") == "delivery" and (
            frame["delivery"].get("kind") != "game"
        ):
            break
    return [one for one in rounds if one]


def _room_in(packet: dict[str, Any]) -> int:
    """Count the squares of the room one packet carries."""
    return sum(
        1
        for command in packet["commands"]
        if str(command.get("id", "")).startswith("tile-")
    )


def test_every_round_opens_with_the_whole_scene() -> None:
    """A round the participant has just started is sent the room, not only the walker.

    The far end holds nothing when a round opens -- the rest between rounds took its
    drawing away with the canvas. A round after the first that is sent a delta is
    sent the moving parts alone, and the participant plays a game with no floor.
    """
    store = InMemoryStore()
    with _client(store, _study()).websocket_connect("/ws") as socket:
        rounds = _walk(socket)

    assert len(rounds) == _ROUNDS, f"{len(rounds)} rounds were drawn, not {_ROUNDS}"
    for number, packets in enumerate(rounds, start=1):
        opening = packets[0]
        assert opening["keyframe"] is True, (
            f"round {number} opened on a delta. The client mounts a new drawing for "
            "every round, so a round that opens on a delta opens on a canvas that "
            "holds nothing to apply it to"
        )
        assert _room_in(opening) == _TILES, (
            f"round {number} opened with {_room_in(opening)} of {_TILES} squares of "
            "the room. Everything drawn once was held back as already sent, to a "
            "canvas that had been torn down at the rest before it"
        )


def test_a_round_still_sends_only_what_changed_after_it_has_opened() -> None:
    """The delta is not given up to fix the rest between rounds.

    Sending the whole scene every frame would make this pass and would cost every
    static square of every frame of every round. What the opening keyframe buys is
    that the far end **holds** the room; the frames after it must go on saying only
    what moved.
    """
    store = InMemoryStore()
    with _client(store, _study()).websocket_connect("/ws") as socket:
        rounds = _walk(socket)

    for number, packets in enumerate(rounds, start=1):
        assert len(packets) > 1, f"round {number} drew one frame and stopped"
        for packet in packets[1:]:
            assert packet["keyframe"] is False, (
                f"round {number} sent a keyframe after it had opened"
            )
            assert _room_in(packet) == 0, (
                f"round {number} sent the room again on a frame where nothing about "
                "it changed"
            )


def test_the_study_says_how_large_its_picture_is() -> None:
    """A game that says its picture is 225 by 180 delivers that, and one that says
    nothing delivers nothing and the screen keeps its own 600 by 400."""
    store = InMemoryStore()
    with _client(store, _study(size=(225, 180))).websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        delivery = _read_until(socket, "delivery")["delivery"]
    assert delivery["size"] == [225, 180], (
        f"the game was delivered as {delivery.get('size')!r}, so the screen could "
        "not draw the kitchen at the size the study drew it for"
    )

    store = InMemoryStore()
    with _client(store, _study()).websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        delivery = _read_until(socket, "delivery")["delivery"]
    assert "size" not in delivery


def test_a_size_that_describes_no_picture_is_refused() -> None:
    """A width of nought is a canvas nobody can see, so it is refused at once."""
    with pytest.raises(ValueError, match="above nought"):
        Game(
            "play",
            _kitchen(),
            seats={"one": Human(), "two": Bot(_Idle())},
            size=(0, 180),
        )
