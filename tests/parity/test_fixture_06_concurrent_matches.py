"""Fixture 6: concurrent matches, with waiting-room and eligibility behaviour.

A deployed study is not one pair of participants. People arrive when they arrive,
some of them should never have been let in, and the ones who are let in have to be
paired with each other without ever being paired twice. This fixture holds the new
stack to all three at once.

- **Concurrent matches.** Four participants arrive together and become two rooms
  that play side by side. Each room records its own episode and its own
  trajectory, so a study running at scale does not merge two pairs into one run.
- **The waiting room.** Somebody who arrives alone waits, and is matched when a
  partner arrives -- rather than starting a game with an empty seat.
- **Eligibility.** A participant the study refuses never reaches the waiting room
  at all. That ordering is the whole point: a refused participant who sat in the
  pool would be matched with a good one, and the good one would wait out the
  timeout for a partner who was never going to play.
"""

from __future__ import annotations

from contextlib import ExitStack
from typing import Any, cast

from mug.content import Choice, Form, Game, Page, Screen, Study, plan_of
from mug.gateway import Gateway
from mug.visits.eligibility import eligibility_id_for, read_decision
from tests.e2e_native.browser_sim import (
    BrowserSim,
    Link,
    Session,
    launch_urls,
    negotiate,
    open_browser,
    open_browsers,
    peer_episodes,
    report_and_capture,
    run_room_mesh,
    study_session,
)


def _refuse_one(session: Session, stack: ExitStack) -> dict[str, Any]:
    """Connect one participant on a poor connection and return how they are refused.

    The refusal is read for rather than counted to: a mesh study announces its
    bundle before it asks anything, so the frame that turns somebody away is not at
    a fixed position in the stream.
    """
    url = launch_urls(session.app, session.tickets)[0]
    socket = stack.enter_context(session.client.websocket_connect(url))
    assert socket.receive_json()["type"] == "handshake_ack"
    socket.send_json({"type": "measurement", "samples": {"rtt": 900_000}})
    for _ in range(8):
        message = cast("dict[str, Any]", socket.receive_json())
        if message.get("type") == "error":
            return message
    raise AssertionError("the study never refused a connection it declared too poor")


def _screened_study() -> Study:
    """Return a two-person study that refuses a participant on a poor connection."""
    return Study(
        Form("consent", Choice("agree", "Do you agree to take part?", ["yes", "no"])),
        Game("play"),
        Page("debrief", "# Thank you"),
        screen=Screen(max_rtt_ms=200, warn_after=1, exclude_after=2),
    )


def _rooms_of(browsers: list[BrowserSim]) -> dict[str, list[BrowserSim]]:
    """Group the browsers by the room the server put each of them in."""
    grouped: dict[str, list[BrowserSim]] = {}
    for browser in browsers:
        grouped.setdefault(str(browser.bootstrap["room_handle"]), []).append(browser)
    return grouped


def test_four_participants_become_two_rooms_that_play_at_the_same_time() -> None:
    """Concurrent matches: two games run side by side and stay separate."""
    with study_session(participants=4) as (session, stack):
        browsers = open_browsers(session, stack, count=4)
        for browser in browsers:
            browser.take_bootstrap()

        rooms = _rooms_of(browsers)
        assert len(rooms) == 2, "four participants make two pairs"
        assert all(len(members) == 2 for members in rooms.values())

        # Every participant is in a room before any room has played a frame, so
        # the two matches really are concurrent rather than one after the other.
        assert len({browser.handle for browser in browsers}) == 4

        for members in rooms.values():
            negotiate(members)
            for browser in members:
                browser.start = browser.await_frame("p2p_mesh_start")["start"]
            run_room_mesh(members, link=Link(latency=3))
            report_and_capture(members)
            for browser in members:
                browser.await_frame("p2p_mesh_finish")

        recorded = peer_episodes(session.store)
        digests = {
            cast("dict[str, Any]", browser.finish)["trajectory_digest"]["hex"]
            for browser in browsers
            if browser.finish is not None
        }

    assert len(recorded) == 2, "two matches, two episodes"
    assert len(digests) == 2, "the two rooms played two different games"


def test_the_two_rooms_are_told_about_their_own_partners_and_nobody_else() -> None:
    """A participant in one match never learns of the other match.

    Concurrency is not only about running at once. Two rooms that could see each
    other's peers would let a participant signal into a game they are not in.
    """
    with study_session(participants=4) as (session, stack):
        browsers = open_browsers(session, stack, count=4)
        for browser in browsers:
            browser.take_bootstrap()
        rooms = _rooms_of(browsers)

        for members in rooms.values():
            mine = {browser.handle for browser in members}
            others = {
                browser.handle
                for browser in browsers
                if browser.handle not in mine
            }
            for browser in members:
                seen = set(browser.peers)
                assert seen <= mine
                assert not seen & others


def test_somebody_who_arrives_alone_waits_for_a_partner() -> None:
    """The waiting room: one person is not a match, and no game starts for them."""
    with study_session(participants=2) as (session, stack):
        first = open_browser(session, stack, 0)
        coordinator = session.app.state.p2p_coordinator
        assert coordinator.waiting_count() == 1, "the lone participant is waiting"
        assert peer_episodes(session.store) == [], "no game started with one seat"

        second = open_browser(session, stack, 1)
        for browser in (first, second):
            browser.take_bootstrap()

        # The pair the server made is one room, and both of them are in it.
        assert len(_rooms_of([first, second])) == 1
        assert coordinator.waiting_count() == 0


def test_a_refused_participant_never_reaches_the_waiting_room() -> None:
    """Eligibility runs before matching, so a refusal costs nobody else their time.

    This is the ordering that matters. If a participant the study refused sat in
    the pool anyway, the next good participant would be matched to them, and would
    then wait out the whole timeout for somebody who was never going to play.
    """
    with study_session(
        participants=1, activities=_screened_study()
    ) as (session, stack):
        coordinator = session.app.state.p2p_coordinator
        refusal = _refuse_one(session, stack)

        assert refusal["code"] == "policy.excluded"
        assert coordinator.waiting_count() == 0, "a refused participant was pooled"
        assert peer_episodes(session.store) == []


def test_the_refusal_is_recorded_with_a_reason_a_reader_can_find() -> None:
    """A participant who was turned away leaves a record saying why."""
    with study_session(
        participants=1, activities=_screened_study()
    ) as (session, stack):
        assert _refuse_one(session, stack)["code"] == "policy.excluded"

        visits = [
            plan.visit_id
            for _aggregate_id, state in session.store.scan_aggregates()
            if (plan := plan_of(state)) is not None
        ]
        assert len(visits) == 1
        gateway: Gateway = session.app.state.gateway
        decision = read_decision(
            session.store, eligibility_id_for(gateway.derived_id, visits[0])
        )

    assert decision is not None
    assert decision.admitted is False
    assert "rtt" in decision.reason
