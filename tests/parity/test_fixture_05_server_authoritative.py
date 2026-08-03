"""Fixture 5: two humans complete a server-authoritative game, with reconnect.

Peer-to-peer is not always the right answer. A study with an environment too heavy
for a browser, or one that must not trust a participant's machine, runs the loop on
the server: the server steps the environment, reads each seat's input, and pushes
every frame. This fixture proves that mode carries two people through a whole run,
and that it survives the thing that actually happens in the field -- one of them
loses their connection in the middle.

The reconnection is the load-bearing part. The run belongs to the **table**, not to
either websocket, so:

- the participant who stayed plays on while the other is away, and the empty seat
  holds no key rather than stopping the game;
- the participant who comes back is given the seat they already had, not a new one,
  so their trajectory is one run and not two;
- the visit advances **once**, from the connection that is still there.

A platform that restarted the episode on reconnect, or seated the returning
participant somewhere else, would pass a test that only counted frames.
"""

from __future__ import annotations

from typing import Any, cast

from _environments import PARTNER, YOU, ServerHarvest
from _participant import Participant, episodes, heads
from fastapi.testclient import TestClient

from mug.app import build_study_app
from mug.content import Game, Page, Study
from mug.content.seats import Human, MultiSeatGame
from mug.gateway import Gateway
from mug.storage import InMemoryStore, Store

# Long enough, and slow enough, that a connection can be dropped while the server
# is still stepping the run.
_LENGTH = 40
_FPS = 25


def _game() -> MultiSeatGame:
    return MultiSeatGame(
        make_env=lambda: ServerHarvest(_LENGTH),
        channel_key="harvest",
        action_bindings={"ArrowUp": 1, "ArrowDown": 2, "ArrowLeft": 3, "ArrowRight": 4},
        default_action=0,
        decision_timeout=1.0,
        fps=_FPS,
        max_steps=_LENGTH + 4,
    )


def _client(store: Store) -> TestClient:
    study = Study(
        Game("play", _game(), seats={YOU: Human(), PARTNER: Human()}),
        Page("debrief", "# Thank you"),
    )
    return TestClient(build_study_app(study=study, store=store, gateway=Gateway()))


def _players_on(store: Store) -> set[str]:
    """Return the actors the game channel recorded as playing seats."""
    return {
        cast("str", one["actor_id"])
        for one in heads(store, "mug.api-06.membership")
        if one["channel_key"] == "harvest" and one["access"] == "read_write"
    }


def test_two_participants_play_one_server_stepped_run() -> None:
    """The server holds the environment, and both people watch one timeline."""
    store = InMemoryStore()
    client = _client(store)
    with (
        client,
        client.websocket_connect("/ws") as one,
        client.websocket_connect("/ws") as two,
    ):
        first = Participant(one, tag=1).handshake()
        second = Participant(two, tag=2).handshake()
        assert first.delivery("game")["mode"] != "browser"
        assert second.delivery("game")["mode"] != "browser"
        first_frames, after_first = first.frames()
        second_frames, after_second = second.frames()

    # One run, watched twice: the frame numbers are the same list.
    assert len(episodes(store)) == 1
    assert [one["frame_number"] for one in first_frames] == [
        one["frame_number"] for one in second_frames
    ]
    # Both seats were stepped on every frame.
    assert all(set(frame["actions"]) == {YOU, PARTNER} for frame in first_frames)
    assert after_first["delivery"]["kind"] == "content"
    assert after_second["delivery"]["kind"] == "content"
    assert len(_players_on(store)) == 2


def test_a_participant_who_drops_mid_run_comes_back_to_the_seat_they_left() -> None:
    """The capability the field needs: a dropped connection is not a lost run."""
    store = InMemoryStore()
    client = _client(store)
    with client, client.websocket_connect("/ws") as two:
        second = Participant(two, tag=2).handshake()

        with client.websocket_connect("/ws") as one:
            first = Participant(one, tag=1).handshake()
            assert first.delivery("game")["kind"] == "game"
            assert second.delivery("game")["kind"] == "game"
            # Let the server get the run under way, then drop this connection.
            for _ in range(3):
                assert first.read()["type"] == "frame"
            token = first.resume_token
        assert token is not None

        with client.websocket_connect(f"/ws?resume_token={token}") as back:
            returned = Participant(back, tag=3).handshake()
            assert returned.delivery("game")["kind"] == "game"
            _, after_return = returned.frames()
            _, after_stayed = second.frames()

    # One episode: the run carried on while the participant was away, and the one
    # they came back to is the one they left.
    assert len(episodes(store)) == 1
    # Two players, not three. A reconnection that seated a new actor would have
    # made this a three-person record of a two-person study.
    assert len(_players_on(store)) == 2
    # Both participants moved on from the game exactly once.
    assert after_return["delivery"]["kind"] == "content"
    assert after_stayed["delivery"]["kind"] == "content"


def test_the_participant_who_stayed_is_not_held_up_by_the_one_who_left() -> None:
    """An empty seat holds no key; it does not stop the environment.

    A loop that waited for every seat's input would turn one person's dropped
    connection into a game that stops for everybody. The seat that was left
    supplies the default action and the run goes on.
    """
    store = InMemoryStore()
    client = _client(store)
    with client, client.websocket_connect("/ws") as two:
        second = Participant(two, tag=2).handshake()
        with client.websocket_connect("/ws") as one:
            first = Participant(one, tag=1).handshake()
            first.delivery("game")
            second.delivery("game")
            for _ in range(3):
                assert first.read()["type"] == "frame"
        # The other connection is gone now, and this one keeps being pushed frames
        # until the run ends by itself.
        frames, following = second.frames()

    assert len(frames) > 3, "the run stopped when one participant left"
    assert following["delivery"]["kind"] == "content"
    recorded: list[dict[str, Any]] = episodes(store)
    assert len(recorded) == 1
    assert recorded[0]["frame_count"] == _LENGTH
