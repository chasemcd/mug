"""Two browsers play one peer-to-peer episode through the whole application.

This is the native replacement for the legacy browser suite. Each test drives
simulated browsers (``browser_sim``) against the real application: the launch
gate, the flow, matchmaking, the API-09 signalling relay, the start barrier,
capture reconciliation, artifact persistence, and episode recording all run for
real. Only WebRTC and the data channels themselves are simulated, which is what
lets a test *state* a latency or a packet-loss rate instead of hoping for one.

The legacy tests each map onto one below:

| legacy                                        | here                              |
| --------------------------------------------- | --------------------------------- |
| ``test_infrastructure``                        | two browsers reach the game       |
| ``test_multiplayer_basic`` / ``test_p2p_regression`` | one episode end to end      |
| ``test_data_comparison`` / ``test_focus_loss_data_parity`` | the recorded run |
| ``test_latency_injection``                     | latency, asymmetry, and jitter    |
| ``test_network_disruption``                    | packet loss and the hidden tab    |
| ``test_lifecycle_stress``                      | disconnects and re-pooling        |
| ``test_multi_participant`` / ``test_waitroom_stress`` | concurrent rooms and waiting |
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import ExitStack, contextmanager
from dataclasses import replace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from examples.tandem.browser_mesh_env import tandem_mesh_spec
from examples.tandem.study import tandem_study
from mug.app import build_study_app
from mug.content import Form, Game, Likert
from mug.content import Study as AuthoredStudy
from mug.game.browser_mesh import BrowserMeshSpec
from mug.gateway import Gateway
from mug.kernel import PrincipalRef
from mug.launch import provision_launch_ticket
from mug.participant_p2p_types import BrowserP2PConfig
from mug.storage import InMemoryStore, Store
from tests.e2e_native.browser_sim import (
    BrowserSim,
    Link,
    launch_urls,
    negotiate,
    off_thread,
    report_and_capture,
    run_room_mesh,
)

_RESEARCHER = PrincipalRef(
    kind="researcher", id="researcher_019b6000-0000-7000-8000-0000000000ab"
)


def _spec(**changes: Any) -> BrowserMeshSpec:
    """Return a short Tandem run, so a test is quick but still plays a game."""
    return replace(tandem_mesh_spec(), max_steps=24, **changes)


class Study:
    """One running application plus the launch tickets its participants need."""

    def __init__(self, app: FastAPI, client: TestClient, tickets: list[str]) -> None:
        self.app = app
        self.client = client
        self.tickets = tickets
        self.store: Store = app.state.store


def build_study(
    *,
    size: int = 2,
    participants: int = 2,
    spec: BrowserMeshSpec | None = None,
    activities: AuthoredStudy | None = None,
) -> Study:
    """Build the launch-gated browser peer-to-peer application under test.

    ``activities`` is the authored study the participants walk through. With none
    the demo study runs, which is what most of these tests want: they are about
    the game, not about what surrounds it.
    """

    def build() -> Study:
        store: Store = InMemoryStore()
        gateway = Gateway()
        app = build_study_app(
            study=activities,
            store=store,
            gateway=gateway,
            browser_p2p=BrowserP2PConfig(
                channel_key="tandem", size=size, game=spec or _spec(), seed=9
            ),
            require_launch=True,
        )
        app.state.store = store
        tickets = [str(app.state.launch_ticket)]
        for _ in range(participants - 1):
            issued = asyncio.run(
                provision_launch_ticket(gateway, store, researcher=_RESEARCHER)
            )
            tickets.append(issued.ticket_handle)
        return Study(app, TestClient(app), tickets)

    return off_thread(build)


def open_browser(study: Study, stack: ExitStack, index: int) -> BrowserSim:
    """Connect the participant holding that launch ticket and play to the game."""
    url = launch_urls(study.app, study.tickets)[index]
    socket = stack.enter_context(study.client.websocket_connect(url))
    browser = BrowserSim(socket, tag=f"{index + 1}")
    browser.play_to_the_game()
    return browser


def open_browsers(
    study: Study, stack: ExitStack, count: int | None = None
) -> list[BrowserSim]:
    """Connect that many browsers and play each of them up to the game."""
    total = count or len(study.tickets)
    return [open_browser(study, stack, index) for index in range(total)]


@contextmanager
def study_session(**changes: Any) -> Iterator[tuple[Study, ExitStack]]:
    """Run one application and close its websockets before its event loop.

    The order matters: a websocket closed after the test client has exited waits
    on an event loop that is already gone, and the test hangs rather than fails.
    """
    study = build_study(**changes)
    with study.client, ExitStack() as sockets:
        yield study, sockets


def play_one_room(
    browsers: Sequence[BrowserSim], *, link: Link | None = None, **kwargs: Any
) -> None:
    """Take a formed room all the way from bootstrap to the finish frame."""
    for browser in browsers:
        browser.take_bootstrap()
    negotiate(browsers)
    for browser in browsers:
        browser.start = browser.await_frame("p2p_mesh_start")["start"]
    run_room_mesh(browsers, link=link, **kwargs)
    report_and_capture(browsers)
    for browser in browsers:
        browser.await_frame("p2p_mesh_finish")


def wait_until(condition: Callable[[], bool], *, seconds: float = 5.0) -> None:
    """Wait for a server-side condition the client cannot observe directly."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.01)
    raise AssertionError("the server never reached the expected state")


def episodes_in(store: Store) -> list[dict[str, Any]]:
    """Return every peer-authority episode aggregate the ledger holds."""
    return [
        state
        for _, state in store.scan_aggregates()
        if isinstance(state, dict) and state.get("authority") == "peer"
    ]


# -- the flow ------------------------------------------------------------------


def test_two_browsers_reach_the_game_and_form_one_room() -> None:
    """The infrastructure smoke test: both browsers are placed in one room."""
    with study_session() as (study, stack):
        first, second = open_browsers(study, stack)
        left = first.take_bootstrap()
        right = second.take_bootstrap()

        assert left["room_handle"] == right["room_handle"]
        assert first.handle != second.handle
        assert first.peers == (second.handle,)
        assert first.is_capture_owner != second.is_capture_owner


def test_the_mesh_bundle_arrives_before_the_forms_are_answered() -> None:
    """The runtime downloads during the forms, so no browser holds up its room."""
    with study_session() as (study, stack):
        first, _ = open_browsers(study, stack)

        assert first.manifest["channel_key"] == "tandem"
        assert [module["name"] for module in first.manifest["runtime_modules"]] == [
            "mug.game.mesh",
            "mug.game.wire",
            "mug.game.browser_mesh_driver",
        ]
        assert "def make_replica" in first.manifest["source_bundle"]


# -- one whole episode ---------------------------------------------------------


def test_two_browsers_play_one_episode_and_the_server_records_it() -> None:
    """The end-to-end run: both peers agree, and the ledger holds the episode."""
    with study_session() as (study, stack):
        browsers = open_browsers(study, stack)
        play_one_room(browsers)

        first, second = browsers
        assert first.driver is not None and second.driver is not None
        assert first.driver.frame_hashes() == second.driver.frame_hashes()
        assert first.driver.frame_count() == 24

        # Both browsers were told the same reconciled result.
        assert first.finish is not None and second.finish is not None
        assert first.finish["trajectory_digest"] == second.finish["trajectory_digest"]
        assert first.finish["capture_receipt"] == second.finish["capture_receipt"]
        assert first.finish["frame_count"] == 24

        # And the server wrote the episode under peer authority.
        episodes = episodes_in(study.store)
        assert len(episodes) == 1
        assert episodes[0]["frame_count"] == 24
        assert episodes[0]["channel_key"] == "tandem"
        assert episodes[0]["outcome"] == "reset"


def test_a_study_plays_two_rounds_as_two_rooms_on_one_visit() -> None:
    """A practice round and then the real one: one study, two rooms, two episodes.

    Each round forms its own room and records its own episode. The rounds share
    the participants, the visit, and the mounted game -- what they do not share is
    identity, which is what used to make a second round impossible.
    """
    activities = AuthoredStudy(
        Form("consent", Likert("ready", "Are you ready to start?", scale=5)),
        Game("practice"),
        Form("check", Likert("understood", "Did the practice make sense?", scale=5)),
        Game("play"),
    )
    with study_session(activities=activities) as (study, stack):
        browsers = open_browsers(study, stack)
        play_one_room(browsers)
        practice_room = browsers[0].bootstrap["room_handle"]
        assert _finish_of(browsers[0]) == _finish_of(browsers[1])

        for browser in browsers:
            browser.play_to_the_next_game()
        play_one_room(browsers)

        assert browsers[0].bootstrap["room_handle"] != practice_room
        assert (
            browsers[0].bootstrap["room_handle"] == browsers[1].bootstrap["room_handle"]
        )
        # Both peers agreed on the second round too, and on the same run.
        assert _finish_of(browsers[0]) == _finish_of(browsers[1])

        episodes = episodes_in(study.store)
        assert len(episodes) == 2
        assert len({episode["episode_id"] for episode in episodes}) == 2
        assert all(episode["frame_count"] == 24 for episode in episodes)

    assert browsers[0].answered.count("practice") == 1
    assert browsers[0].answered.count("play") == 1


def _finish_of(browser: BrowserSim) -> dict[str, Any]:
    """Return the finish frame the browser was last given."""
    finish = browser.finish
    assert finish is not None
    return finish


def test_both_browsers_leave_the_room_and_finish_the_study() -> None:
    """After the room finishes, each flow advances to the debrief on its own."""
    with study_session() as (study, stack):
        browsers = open_browsers(study, stack)
        play_one_room(browsers)

        for browser in browsers:
            delivery = browser.await_frame("delivery")["delivery"]
            assert delivery["kind"] in {"form", "content", "complete"}


# -- latency, jitter, and loss -------------------------------------------------


@pytest.mark.parametrize("latency", [4, 10, 20])
def test_an_episode_completes_under_fixed_latency(latency: int) -> None:
    """A round trip past the input delay rolls back and still agrees."""
    with study_session() as (study, stack):
        browsers = open_browsers(study, stack)
        play_one_room(browsers, link=Link(latency=latency))

        first, second = browsers
        assert first.driver is not None and second.driver is not None
        assert first.driver.frame_hashes() == second.driver.frame_hashes()
        assert first.driver.rollback_count() > 0
        assert first.finish is not None


def test_an_episode_completes_under_asymmetric_latency() -> None:
    """One slow direction does not split the run."""
    with study_session() as (study, stack):
        browsers = open_browsers(study, stack)
        first, second = browsers
        first.take_bootstrap()
        second.take_bootstrap()
        slow = {(first.handle, second.handle): 18}
        for browser in browsers:
            browser.start = {}
        negotiate(browsers)
        for browser in browsers:
            browser.start = browser.await_frame("p2p_mesh_start")["start"]
        run_room_mesh(browsers, link=Link(latency=2, slow=slow))
        report_and_capture(browsers)
        for browser in browsers:
            browser.await_frame("p2p_mesh_finish")

        assert first.driver is not None and second.driver is not None
        assert first.driver.frame_hashes() == second.driver.frame_hashes()


def test_an_episode_completes_under_jitter() -> None:
    """Packets that arrive out of order do not split the run."""
    with study_session() as (study, stack):
        browsers = open_browsers(study, stack)
        play_one_room(browsers, link=Link(latency=7, jitter=6))

        first, second = browsers
        assert first.driver is not None and second.driver is not None
        assert first.driver.frame_hashes() == second.driver.frame_hashes()


def test_an_episode_completes_under_packet_loss() -> None:
    """A third of the input packets are dropped and the run still agrees."""
    with study_session() as (study, stack):
        browsers = open_browsers(study, stack)
        play_one_room(browsers, link=Link(latency=3, loss=0.33))

        first, second = browsers
        assert first.driver is not None and second.driver is not None
        assert first.driver.frame_hashes() == second.driver.frame_hashes()
        assert first.finish is not None


def test_a_hidden_tab_recovers_and_the_run_still_agrees() -> None:
    """One browser goes quiet, floods its backlog, and the mesh re-converges."""
    with study_session() as (study, stack):
        browsers = open_browsers(study, stack)
        for browser in browsers:
            browser.take_bootstrap()
        negotiate(browsers)
        for browser in browsers:
            browser.start = browser.await_frame("p2p_mesh_start")["start"]
        hidden = Link(latency=1, silent={browsers[0].handle: (5, 18)})
        run_room_mesh(browsers, link=hidden)
        report_and_capture(browsers)
        for browser in browsers:
            browser.await_frame("p2p_mesh_finish")

        first, second = browsers
        assert first.driver is not None and second.driver is not None
        assert first.driver.frame_hashes() == second.driver.frame_hashes()
        assert second.driver.max_rollback_depth() > 5


# -- what the run leaves behind ------------------------------------------------


def test_the_persisted_capture_is_the_payload_both_peers_agreed_on() -> None:
    """The stored bytes are the trajectory, not a summary of it."""
    with study_session() as (study, stack):
        browsers = open_browsers(study, stack)
        play_one_room(browsers, link=Link(latency=6))

        first, second = browsers
        assert first.driver is not None and second.driver is not None
        agreed = first.driver.capture_payload()
        assert agreed == second.driver.capture_payload()

        assert first.finish is not None
        token: Any = study.store.load_token(first.finish["capture_receipt"])
        assert token is not None
        assert token["kind"] == "p2p_capture"
        assert token["interaction_id"].startswith("interaction_")

        stored = off_thread(lambda: asyncio.run(_read_artifact(study.store, token)))
        assert json.loads(stored) == agreed


async def _read_artifact(store: Store, token: dict[str, Any]) -> str:
    """Read back the bytes the capture staged, through the artifact store.

    Run it off-thread like the rest: a Playwright test in the same process leaves
    an event loop on this thread, and `asyncio.run` refuses to start inside one.
    """
    from typing import cast

    from mug.storage import ArtifactStore

    artifacts = cast("ArtifactStore", store)
    data = await artifacts.read_artifact(token["artifact"]["artifact_id"])
    return data.decode("utf-8")


def test_the_recorded_episode_names_actors_the_browsers_never_saw() -> None:
    """The browsers reported handles; the ledger holds the server's own actors."""
    with study_session() as (study, stack):
        browsers = open_browsers(study, stack)
        play_one_room(browsers)

        handles = {browser.handle for browser in browsers}
        episode = episodes_in(study.store)[0]
        assert episode["seat_key"] in {"seat-1", "seat-2"}
        assert not any(handle in json.dumps(episode) for handle in handles)


# -- refusals and lifetime -----------------------------------------------------


def test_only_the_capture_owner_may_submit_the_trajectory() -> None:
    """A peer that is not the owner cannot write the room's record."""
    with study_session() as (study, stack):
        browsers = open_browsers(study, stack)
        for browser in browsers:
            browser.take_bootstrap()
        negotiate(browsers)
        for browser in browsers:
            browser.start = browser.await_frame("p2p_mesh_start")["start"]
        run_room_mesh(browsers)
        for browser in browsers:
            browser.send_complete()

        other = next(browser for browser in browsers if not browser.is_capture_owner)
        other.send_capture()
        owner = next(browser for browser in browsers if browser.is_capture_owner)
        owner.send_capture()

        # The refusal did not end the room: the owner's own submission still wins.
        for browser in browsers:
            browser.await_frame("p2p_mesh_finish")


def test_two_peers_that_disagree_abort_the_room_rather_than_pick_a_winner() -> None:
    """A mesh only records a run every peer agrees on, or it records nothing."""
    with study_session() as (study, stack):
        browsers = open_browsers(study, stack)
        for browser in browsers:
            browser.take_bootstrap()
        negotiate(browsers)
        for browser in browsers:
            browser.start = browser.await_frame("p2p_mesh_start")["start"]
        run_room_mesh(browsers)

        browsers[0].send_complete()
        browsers[1].send_complete(trajectory_hex="b" * 64)

        for browser in browsers:
            browser.await_frame("p2p_mesh_abort")
            assert browser.abort is not None
            assert browser.abort["reason"] == "capture_conflict"
        assert episodes_in(study.store) == []


def test_a_forged_payload_is_refused_and_the_room_keeps_running() -> None:
    """The server re-derives the trajectory, so a payload cannot rename itself.

    The owner claims the run the peers agreed on but submits a different one. The
    refusal is a refusal, not a room abort: nothing about the room changed, and
    the owner's honest submission still wins afterwards.
    """
    with study_session() as (study, stack):
        browsers = open_browsers(study, stack)
        for browser in browsers:
            browser.take_bootstrap()
        negotiate(browsers)
        for browser in browsers:
            browser.start = browser.await_frame("p2p_mesh_start")["start"]
        run_room_mesh(browsers)
        for browser in browsers:
            browser.send_complete()

        owner = next(browser for browser in browsers if browser.is_capture_owner)
        assert owner.driver is not None
        forged = owner.driver.capture_payload()
        forged["frames"][0]["rewards"] = {
            handle: 9.0 for handle in forged["frames"][0]["rewards"]
        }
        owner.send_capture(json.dumps(forged, separators=(",", ":"), sort_keys=True))
        owner.send_capture()

        for browser in browsers:
            browser.await_frame("p2p_mesh_finish")
        stored = episodes_in(study.store)
        assert len(stored) == 1
        assert stored[0]["frame_count"] == 24


def test_a_browser_that_leaves_mid_game_aborts_its_partner() -> None:
    """The partner learns at once and is told to look for another room."""
    with study_session() as (study, stack):
        browsers = open_browsers(study, stack)
        for browser in browsers:
            browser.take_bootstrap()
        negotiate(browsers)
        for browser in browsers:
            browser.start = browser.await_frame("p2p_mesh_start")["start"]

        browsers[0].socket.close()
        remaining = browsers[1]
        remaining.await_frame("p2p_mesh_abort")

        assert remaining.abort is not None
        assert remaining.abort["reason"] == "peer_disconnected"
        assert remaining.abort["disposition"] == "repool"
        assert episodes_in(study.store) == []


def test_a_browser_that_leaves_the_waiting_room_does_not_hold_up_the_others() -> None:
    """A three-seat room forms from whoever is still waiting when the third joins."""
    with study_session(size=3, participants=4) as (study, stack):
        first = open_browser(study, stack, 0)
        second = open_browser(study, stack, 1)
        coordinator = study.app.state.p2p_coordinator
        assert coordinator.waiting_count() == 2

        first.socket.close()
        # The socket closes on the client; the server learns of it on its own
        # schedule. Waiting for that is the point of the test, not a workaround.
        wait_until(lambda: coordinator.waiting_count() == 1)

        third = open_browser(study, stack, 2)
        fourth = open_browser(study, stack, 3)

        room = [second, third, fourth]
        for browser in room:
            browser.take_bootstrap()
        assert len({browser.bootstrap["room_handle"] for browser in room}) == 1
        assert len({browser.handle for browser in room}) == 3


def test_two_rooms_form_and_play_side_by_side() -> None:
    """Four browsers make two rooms, and each room records its own episode."""
    with study_session(participants=4) as (study, stack):
        browsers = open_browsers(study, stack, count=4)
        for browser in browsers:
            browser.take_bootstrap()
        rooms: dict[str, list[BrowserSim]] = {}
        for browser in browsers:
            rooms.setdefault(str(browser.bootstrap["room_handle"]), []).append(browser)
        assert len(rooms) == 2

        for members in rooms.values():
            negotiate(members)
            for browser in members:
                browser.start = browser.await_frame("p2p_mesh_start")["start"]
            run_room_mesh(members, link=Link(latency=3))
            report_and_capture(members)
            for browser in members:
                browser.await_frame("p2p_mesh_finish")

        assert len(episodes_in(study.store)) == 2
        digests = {
            browser.finish["trajectory_digest"]["hex"]
            for browser in browsers
            if browser.finish is not None
        }
        assert len(digests) == 2


# -- an author's own study -----------------------------------------------------


def test_two_participants_walk_a_real_study_around_the_game() -> None:
    """The game is one activity among the author's own consent and surveys.

    This is the study a researcher writes (``examples/tandem/study.py``): their
    own two-part consent, their own instructions page, a pre-survey, the game, a
    post-survey about the partner, and a debrief. Nothing about the game changes
    because of what surrounds it, and nothing about the surrounding activities
    changes because the game is peer-to-peer.
    """
    with study_session(activities=tandem_study()) as (study, stack):
        browsers = open_browsers(study, stack)

        # Everything the author wrote before the game, in the order written.
        for browser in browsers:
            assert browser.answered == [
                "consent",
                "instructions",
                "pre-survey",
                "play",
            ]

        play_one_room(browsers, link=Link(latency=5))

        # And everything after it, ending at the completion code.
        for browser in browsers:
            completion = browser.finish_the_study()
            assert browser.answered[-3:] == ["post-survey", "debrief", "complete"]
            assert completion["completion_code"].startswith("MUG-")

        assert len(episodes_in(study.store)) == 1


def test_a_study_may_put_the_game_first_or_last() -> None:
    """The order is the author's, not the platform's."""
    game_first = AuthoredStudy(
        Game("play"),
        Form("after", Likert("teamwork", "How did that go?", scale=5)),
    )
    with study_session(activities=game_first) as (study, stack):
        browsers = open_browsers(study, stack)

        assert browsers[0].answered == ["play"]
        play_one_room(browsers)
        for browser in browsers:
            browser.finish_the_study()
            assert browser.answered[-2:] == ["after", "complete"]
