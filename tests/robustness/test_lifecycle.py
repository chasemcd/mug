"""What happens to a study when people behave like people.

The legacy stress tests are the ones worth keeping most: participants play two
rounds back to back, somebody closes the tab in the middle, somebody else leaves
the waiting room before a partner arrives, and one participant walks away after
the game while the other is still answering a survey. Each of those broke
something once.

The load-bearing claim in every test here is **isolation**: one participant's
behaviour changes their own run and nothing else. A platform that let a dropped
connection end a stranger's game, or that let a second round reuse the first
round's state, would pass a test that ran one pair at a time.

These modules use ASD-STE100 Simplified Technical English.
"""

from __future__ import annotations

from typing import Any

from tests.e2e_native.browser_sim import (
    BrowserSim,
    Link,
    negotiate,
    open_browser,
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
    recorded_frames,
    seated_session,
    seated_study,
)

_LENGTH = 10
_TABLES = 3


def test_three_tables_play_two_rounds_back_to_back() -> None:
    """A second round is a second run, not a continuation of the first.

    State that leaked across a round boundary would show as a short second
    episode, a repeated frame number, or one run of twice the length. All three
    are checked, because they are three different bugs.
    """
    with (
        seated_session(seated_study(_LENGTH, rounds=2)) as (client, store),
        people_at(client, _TABLES * 2) as people,
    ):
        for person in people:
            person.delivery("game")
        # Round one, the rest between, then round two.
        for person in people:
            person.rest()
        for person in people:
            _frames, after = person.frames()
            assert after["delivery"]["kind"] == "content"

    recorded = episodes_in(store)
    assert len(recorded) == _TABLES * 2, "three tables, two rounds, six runs"
    assert all(one["frame_count"] == _LENGTH for one in recorded), (
        "a round that carried state from the last one would not be the same length"
    )

    # Each round starts its environment again, so each run is numbered from one.
    for episode in recorded:
        frames = recorded_frames(store, episode)
        assert [frame.frame_number for frame in frames] == list(range(1, _LENGTH + 1))

    # Two rounds at one table are two episodes of one interaction: the pair sat
    # down once. A new interaction per round would split one sitting in two.
    per_table: dict[str, int] = {}
    for episode in recorded:
        key = str(episode["interaction_id"])
        per_table[key] = per_table.get(key, 0) + 1
    assert sorted(per_table.values()) == [2] * _TABLES


def test_one_table_losing_a_participant_does_not_touch_the_others() -> None:
    """Mixed lifecycles in one deployment: two normal tables and one that loses a seat.

    This is the legacy mixed-scenario test. It is not the same as running the
    disconnect on its own: the fault has to happen **while** other people are
    playing, because that is when shared server state can be corrupted by it.
    """
    with (
        seated_session(seated_study(_LENGTH)) as (client, store),
        people_at(client, _TABLES * 2) as people,
    ):
        for person in people:
            person.delivery("game")

        # The last table loses one of its two participants part way through.
        leaving = people[-1]
        leaving.socket.close()

        stayed = [person for person in people[:-1]]
        followed = []
        for person in stayed:
            _frames, after = person.frames()
            followed.append(after)

    # Everybody who stayed was moved on to the page after the game.
    assert all(one["delivery"]["kind"] == "content" for one in followed)

    recorded = episodes_in(store)
    assert len(recorded) == _TABLES, "a table that lost a seat still played its game"

    # The two undisturbed tables recorded whole runs. The empty seat holds no key
    # rather than stopping the environment, so its table records a whole run too.
    for episode in recorded:
        frames = recorded_frames(store, episode)
        assert len(frames) == _LENGTH
        assert all(set(frame.actions) == {YOU, PARTNER} for frame in frames)


def test_a_participant_who_leaves_after_the_game_leaves_the_other_alone() -> None:
    """The legacy scene-isolation test: the survey is not the game.

    One participant closes the tab while the other is on the page after the game.
    The one who stayed must reach the end of the study. A platform that kept the
    pair bound after the run would show them a partner-left screen on a page that
    has no partner in it.
    """
    with (
        seated_session(seated_study(_LENGTH)) as (client, store),
        people_at(client, 2) as people,
    ):
        first, second = people
        for person in people:
            person.delivery("game")
        for person in people:
            _frames, after = person.frames()
            assert after["delivery"]["kind"] == "content"

        second.socket.close()
        first.advance({})
        finished = first.completion()

    assert finished["kind"] == "complete"
    assert len(episodes_in(store)) == 1


# -- the same lifetimes, peer to peer ------------------------------------------------


def test_a_room_that_aborts_does_not_disturb_a_room_that_is_playing() -> None:
    """Two rooms, one fault: the healthy room finishes and records its run.

    A mesh study has no server holding the environment, so an aborting room can
    only reach another room through shared server state -- the coordinator, the
    matchmaker, the capture path. That is what this looks for.
    """
    with study_session(participants=4) as (session, stack):
        browsers = open_browsers(session, stack, count=4)
        for browser in browsers:
            browser.take_bootstrap()
        rooms: dict[str, list[BrowserSim]] = {}
        for browser in browsers:
            rooms.setdefault(str(browser.bootstrap["room_handle"]), []).append(browser)
        assert len(rooms) == 2

        doomed, healthy = list(rooms.values())
        negotiate(doomed)
        for browser in doomed:
            browser.start = browser.await_frame("p2p_mesh_start")["start"]
        doomed[0].socket.close()
        doomed[1].await_frame("p2p_mesh_abort")

        negotiate(healthy)
        for browser in healthy:
            browser.start = browser.await_frame("p2p_mesh_start")["start"]
        run_room_mesh(healthy, link=Link(latency=3))
        report_and_capture(healthy)
        for browser in healthy:
            browser.await_frame("p2p_mesh_finish")

        first, second = healthy
        assert first.driver is not None and second.driver is not None
        assert first.driver.frame_hashes() == second.driver.frame_hashes()
        recorded: list[dict[str, Any]] = peer_episodes(session.store)

    assert doomed[1].abort is not None
    assert doomed[1].abort["reason"] == "peer_disconnected"
    assert len(recorded) == 1, "the room that aborted must record nothing"


def test_somebody_who_leaves_the_waiting_room_is_replaced_by_the_next_arrival() -> None:
    """Waiting-room isolation, which is where a study loses people quietly.

    Somebody joins, waits, and gives up before a partner arrives. The next two
    people to arrive must still be paired with each other rather than one of them
    being handed the seat of somebody who is no longer there.
    """
    with study_session(participants=3) as (session, stack):
        first = open_browser(session, stack, 0)
        coordinator = session.app.state.p2p_coordinator
        assert coordinator.waiting_count() == 1

        first.socket.close()
        _wait_until(lambda: coordinator.waiting_count() == 0)

        second = open_browser(session, stack, 1)
        third = open_browser(session, stack, 2)
        room = [second, third]
        for browser in room:
            browser.take_bootstrap()
        assert len({browser.bootstrap["room_handle"] for browser in room}) == 1

        negotiate(room)
        for browser in room:
            browser.start = browser.await_frame("p2p_mesh_start")["start"]
        run_room_mesh(room)
        report_and_capture(room)
        for browser in room:
            browser.await_frame("p2p_mesh_finish")
        recorded = peer_episodes(session.store)

    assert len(recorded) == 1, "the pair that formed after the walkout played a game"


def _wait_until(ready: Any, tries: int = 200) -> None:
    """Wait for the server to notice something it learns on its own schedule."""
    import time

    for _ in range(tries):
        if ready():
            return
        time.sleep(0.02)
    raise AssertionError("the server never reached the state this test waits for")
