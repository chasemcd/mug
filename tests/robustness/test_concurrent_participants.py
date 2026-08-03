"""Many people at once, which is the only state a deployed study is ever in.

The legacy suite ran six participants in three simultaneous games and twelve in a
waiting-room stress test, and it checked more than "nobody crashed": every pair
that finished had to produce matching data. A platform that pairs the wrong people,
or that lets one room's frames reach another room's participants, passes a test
that counts connections and fails a study.

Both execution modes are held to it here, because they fail differently. A
server-stepped study can cross two tables inside one process; a peer-to-peer study
can cross two rooms in matchmaking and then never notice, because each pair agrees
with itself.

These modules use ASD-STE100 Simplified Technical English.
"""

from __future__ import annotations

from typing import Any

from tests.e2e_native.browser_sim import (
    BrowserSim,
    Link,
    negotiate,
    open_browsers,
    peer_episodes,
    report_and_capture,
    run_room_mesh,
    study_session,
)
from tests.parity._environments import PARTNER, YOU
from tests.robustness._runs import (
    episodes_in,
    people_at,
    play_the_seated_round,
    recorded_frames,
    seated_session,
    seated_study,
)

# Six games at once on the server, and six rooms at once peer to peer. That is the
# scale the legacy stress tests ran at, and it is what a session of a real study
# looks like on the hour.
PAIRS = 6
_LENGTH = 10


def test_six_server_stepped_games_run_at_once_and_each_records_its_own() -> None:
    """Twelve people, six tables, six episodes, and no table sees another's frames."""
    with (
        seated_session(seated_study(_LENGTH)) as (client, store),
        people_at(client, PAIRS * 2) as people,
    ):
        followed = play_the_seated_round(people)
        assert all(one["delivery"]["kind"] == "content" for one in followed)

    recorded = episodes_in(store)
    assert len(recorded) == PAIRS, f"{PAIRS} pairs played, so there are {PAIRS} runs"

    # Each table played its own game to the end, and each one is a distinct
    # interaction. Two tables sharing an interaction would mean the server put four
    # people in one environment.
    assert len({one["interaction_id"] for one in recorded}) == PAIRS
    assert all(one["frame_count"] == _LENGTH for one in recorded)

    for episode in recorded:
        frames = recorded_frames(store, episode)
        assert [frame.frame_number for frame in frames] == list(
            range(1, _LENGTH + 1)
        ), "a table under load lost a frame"
        assert all(set(frame.actions) == {YOU, PARTNER} for frame in frames)


def test_a_crowd_arriving_together_is_paired_and_never_paired_twice() -> None:
    """Nobody is in two rooms, and nobody is left holding a seat alone.

    This is the failure a waiting room has under load: two matchers race, one
    participant is handed to both, and the study records a pair that never played
    together.
    """
    with study_session(participants=PAIRS * 2) as (session, stack):
        browsers = open_browsers(session, stack, count=PAIRS * 2)
        for browser in browsers:
            browser.take_bootstrap()

        rooms: dict[str, list[BrowserSim]] = {}
        for browser in browsers:
            rooms.setdefault(str(browser.bootstrap["room_handle"]), []).append(browser)

    assert len(rooms) == PAIRS, "the crowd did not become the rooms it should have"
    assert all(len(members) == 2 for members in rooms.values())

    # A handle names one participant in one room. Repeat handles would mean two
    # rooms believe they hold the same person.
    handles = [browser.handle for browser in browsers]
    assert len(set(handles)) == len(handles)


def test_every_room_under_load_agrees_with_itself_and_records_one_episode() -> None:
    """Six rooms play side by side, and each pair's two replicas match frame for frame.

    Agreement is checked per room rather than across rooms, which is the point: six
    rooms that all agreed with **each other** would mean the environments were not
    independent.
    """
    with study_session(participants=PAIRS * 2) as (session, stack):
        browsers = open_browsers(session, stack, count=PAIRS * 2)
        for browser in browsers:
            browser.take_bootstrap()
        rooms: dict[str, list[BrowserSim]] = {}
        for browser in browsers:
            rooms.setdefault(str(browser.bootstrap["room_handle"]), []).append(browser)
        assert len(rooms) == PAIRS

        for members in rooms.values():
            negotiate(members)
            for browser in members:
                browser.start = browser.await_frame("p2p_mesh_start")["start"]
            run_room_mesh(members, link=Link(latency=3))
            report_and_capture(members)
            for browser in members:
                browser.await_frame("p2p_mesh_finish")

            first, second = members
            assert first.driver is not None and second.driver is not None
            assert first.driver.frame_hashes() == second.driver.frame_hashes(), (
                "two peers in one room disagreed about the game they played"
            )

        recorded: list[dict[str, Any]] = peer_episodes(session.store)
        finished = [
            browser.finish["trajectory_digest"]["hex"]
            for browser in browsers
            if browser.finish is not None
        ]

    assert len(recorded) == PAIRS
    # Each room played a different game, so each has its own trajectory. One digest
    # shared by every room would mean the rooms were not separate runs.
    assert len(set(finished)) == PAIRS
