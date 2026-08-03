"""Fixture 4: two humans complete a rollback-enabled P2P game under fault.

The legacy suite proved this with two real Chromium windows and a hopeful network.
The replacement drives the real application -- the launch gate, the flow,
matchmaking, the API-09 signalling relay, the start barrier, capture
reconciliation, and episode recording -- with simulated browsers over data
channels whose faults the fixture *states* rather than hopes for.

The parity document asks for one run under **latency, packet loss, and focus
loss**, and that is what this is: all three at once, not one at a time. Each fault
on its own has its own test in ``tests/e2e_native``; a study in the field gets
them together, and a rollback scheme that survives each alone can still fail on
the combination.

What the fixture proves: two participants play one game to the end and both walk
out of the study; the two replicas agree frame for frame; the rollback really
fired, so the agreement was reached rather than assumed; and the server records
one peer-authority episode for the run.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from fastapi.testclient import TestClient

from examples.tandem.study import tandem_study
from tests.e2e_native.browser_sim import (
    BrowserSim,
    Link,
    open_browsers,
    peer_episodes,
    play_one_room,
    study_session,
)

# Every fault the parity document names, at once. The silent window is one
# participant's tab going to the background: it sends nothing for nine ticks and
# then floods its backlog, which is the worst case for a rollback buffer.
_UNDER_FAULT = Link(latency=6, jitter=3, loss=0.2, silent={"1": (5, 14)})


def _hidden_tab(browsers: list[BrowserSim]) -> Link:
    """Return the fault profile, with the silent window on the first browser."""
    return Link(
        latency=_UNDER_FAULT.latency,
        jitter=_UNDER_FAULT.jitter,
        loss=_UNDER_FAULT.loss,
        silent={browsers[0].handle: (5, 14)},
    )


def test_two_participants_finish_a_p2p_game_under_every_fault_at_once() -> None:
    """The capability: latency, loss, and a hidden tab, and the run still agrees."""
    with study_session(activities=tandem_study()) as (session, stack):
        browsers = open_browsers(session, stack)
        play_one_room(browsers, link=_hidden_tab)

        first, second = browsers
        assert first.driver is not None and second.driver is not None

        # The two replicas agree on every frame of the run. This is the whole
        # point: no authoritative server said what happened, and yet there is one
        # answer to what happened.
        assert first.driver.frame_hashes() == second.driver.frame_hashes()

        # The agreement was reached, not assumed. Under this much latency a peer
        # must mispredict and roll back; a run with no rollback would mean the
        # faults never reached the game.
        assert first.driver.rollback_count() > 0
        assert second.driver.rollback_count() > 0

        # The hidden tab's partner had to unwind further than the input delay,
        # which is what recovering from a backlog flood looks like.
        assert second.driver.max_rollback_depth() > 5

        # Both participants finished the game and were told so.
        assert first.finish is not None
        assert second.finish is not None
        assert first.abort is None and second.abort is None


def test_both_participants_walk_out_of_the_study_after_the_faulty_run() -> None:
    """A game that survived the faults must not strand the people who played it."""
    with study_session(activities=tandem_study()) as (session, stack):
        browsers = open_browsers(session, stack)
        play_one_room(browsers, link=_hidden_tab)

        for browser in browsers:
            delivery = browser.await_frame("delivery")["delivery"]
            assert delivery["kind"] in {"form", "content", "complete"}


def test_the_faulty_run_is_recorded_once_under_peer_authority() -> None:
    """One game is one episode, whatever the network did to it."""
    with study_session(activities=tandem_study()) as (session, stack):
        browsers = open_browsers(session, stack)
        play_one_room(browsers, link=_hidden_tab)
        recorded: list[dict[str, Any]] = peer_episodes(session.store)

    assert len(recorded) == 1, "two peers played one game, so there is one episode"
    assert recorded[0]["authority"] == "peer"


def test_the_faults_shorten_nothing_and_the_whole_game_is_played() -> None:
    """The run goes the distance under fault, rather than ending early or stalling.

    Note what is **not** claimed here: that a faulty link reaches the same
    trajectory as a clean one. It does not, and it should not. A dropped input
    packet is a real event -- the action was not delivered, so the game the peers
    agree on is a different game from the one they would have played on a perfect
    link. What must hold is that both peers agree on which game that was, and that
    the faults cost frames rather than the whole run.
    """

    Profile = Link | Callable[[Sequence[BrowserSim]], Link] | None

    def frames_played(link: Profile) -> int:
        with study_session(activities=tandem_study()) as (session, stack):
            browsers = open_browsers(session, stack)
            play_one_room(browsers, link=link)
            first, second = browsers
            assert first.driver is not None and second.driver is not None
            assert first.driver.frame_hashes() == second.driver.frame_hashes()
            return len(first.driver.frame_hashes())

    clean = frames_played(None)
    faulty = frames_played(_hidden_tab)

    assert clean > 0
    assert faulty == clean, "the faults must cost no frames of the authored run"


def test_a_test_client_is_not_what_makes_this_pass() -> None:
    """The simulator speaks the real wire, so the fixture is about the platform.

    Only WebRTC and the data channels are simulated. Everything the server does --
    the launch gate, matchmaking, signalling relay, the start barrier, capture
    reconciliation -- runs for real, which is what makes a fault injected here
    mean something about a deployment.
    """
    with study_session(activities=tandem_study()) as (session, stack):
        assert isinstance(session.client, TestClient)
        browsers = open_browsers(session, stack)
        # A room formed because the server matched them, and each browser was told
        # who its peers are by the server rather than by the harness.
        for browser in browsers:
            browser.take_bootstrap()
            assert browser.peers, "the server never named this browser's peers"
        handles = {browser.handle for browser in browsers}
        assert len(handles) == 2, "two participants, two distinct room handles"
