"""Real Chromium peers, a bad connection, and the run their inputs imply.

The legacy suite connected several browsers and played real games under injected
latency, packet loss and disruption, because that is where a networked game
actually breaks. ``tests/datacheck/test_mesh_under_network_conditions.py``
reproduces those conditions against the engine in one process, which is fast and
exact and does not run a browser at all. ``test_browser_mesh_browser.py`` runs the
browsers, but on a perfect link, with no keys pressed, and asserts only that a
record exists.

This file is the missing one. Every peer is a real Chromium context running the
shipped rollback engine in Pyodide over a real ``RTCPeerConnection``; the link
under each of them misbehaves on purpose; both participants press real keys; and
what the room recorded is compared against an outside statement of what the
episode should have been.

That statement is possible because each peer says what its inputs were, on the
wire, as it plays them. The true trajectory is one bare replica of the study's
own bundle stepped with those inputs -- no engine, no prediction, no rollback, no
network. The mesh must land on it.

It is slow and it needs the network (Pyodide comes from a CDN), so it is marked
``e2e`` and ``slow`` and runs outside the fast gate::

    uv run pytest tests/e2e_native/test_browser_mesh_under_network_conditions.py

Two Chromium contexts on one machine reach each other over host ICE candidates,
so no STUN or TURN server is needed here.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Page

from tests.e2e_native.browser_mesh_bench import (
    Impairment,
    MeshBench,
    assert_agrees_with_the_oracle,
    corrections,
    impairment_counts,
    install_impairment,
    oracle_frames,
    play_with_the_keys,
    read_and_continue,
    recorded_captures,
    recorded_episodes,
    sent_inputs,
    serve_mesh,
    take_packets,
    wait_for_the_game,
)

pytestmark = [pytest.mark.e2e, pytest.mark.slow]

_STEPS = 60
_FPS = 15

# How each connection misbehaves, and what that must cost the mesh. ``least_hurt``
# is what stops a scenario passing because nothing actually went wrong: it counts
# the packets that were lost, held back, or delayed past the point where they could
# still reach a peer in time for the frame they belong to. Every one of those makes
# a peer predict an input and then correct itself.
# ``least_corrected`` is the second half of the same idea, and the half the wire
# cannot supply: how many times the **engine** must have rolled back and replayed.
# A packet that was late proves the link misbehaved; only a rollback proves the
# mesh noticed. A run whose input delay swallowed every impairment would still land
# on the true trajectory and pass every other check here.
#
# The floors are set well under what two real browsers measured, because a real
# browser is not a simulation and the count moves with it:
#
#     clean            corrections [0, 0]    packets hurt 0
#     latency 60ms     corrections [0, 0]    packets hurt 0
#     latency 220ms    corrections [18, 0]   packets hurt 251
#     jitter 120ms     corrections [10, 11]  packets hurt 166
#     loss 0.3         corrections [4, 0]    packets hurt 51
#     all three        corrections [17, 17]  packets hurt 234
#
# The first two rows are the finding worth keeping: latency **inside** the input
# delay costs nothing at all, which is what the input delay is for. Past it, the
# same engine rolls back eighteen times in sixty frames.
_CONDITIONS = [
    pytest.param(Impairment(), 0, 0, id="a clean link"),
    pytest.param(Impairment(latency_ms=60), 0, 0, id="latency inside the delay"),
    pytest.param(Impairment(latency_ms=220), 20, 5, id="latency well past the delay"),
    pytest.param(
        Impairment(latency_ms=150, jitter_ms=120), 10, 3, id="jitter reorders arrivals"
    ),
    pytest.param(Impairment(latency_ms=60, loss=0.3), 20, 1, id="three in ten lost"),
    pytest.param(
        Impairment(latency_ms=200, jitter_ms=90, loss=0.25), 20, 5, id="all three"
    ),
]


@contextmanager
def _peers(
    browser: Browser, bench: MeshBench, impairments: Sequence[Impairment]
) -> Iterator[list[Page]]:
    """Open one browser context per peer, each behind its own bad connection."""
    contexts = [browser.new_context() for _ in bench.links]
    try:
        for context, impairment in zip(contexts, impairments, strict=True):
            install_impairment(context, impairment, late_ms=bench.late_millis())
        pages = [context.new_page() for context in contexts]
        for page, link in zip(pages, bench.links, strict=True):
            page.goto(link)
        yield pages
    finally:
        for context in contexts:
            context.close()


def _play_one_round(
    bench: MeshBench, pages: Sequence[Page], heading: str
) -> dict[str, dict[int, int]]:
    """Walk one page, play one episode with the keys, and take what was sent."""
    for page in pages:
        read_and_continue(page, heading)
    for page in pages:
        wait_for_the_game(page)
    # Pressing starts as soon as the canvas is there and ends when the client
    # reports the barrier closed. The room still has to form and the runtime to
    # finish downloading, so the keys before the first frame simply do nothing.
    play_with_the_keys(pages)
    return sent_inputs(take_packets(pages))


# -- the conditions ---------------------------------------------------------------


@pytest.mark.parametrize("impairment,least_hurt,least_corrected", _CONDITIONS)
def test_two_real_browsers_reach_the_true_trajectory(
    browser: Browser,
    tmp_path: Path,
    impairment: Impairment,
    least_hurt: int,
    least_corrected: int,
) -> None:
    """Whatever the connection does, the recorded run is the run the keys imply."""
    with serve_mesh(tmp_path, peers=2, max_steps=_STEPS, fps=_FPS) as bench:
        with _peers(browser, bench, [impairment, impairment]) as pages:
            schedules = _play_one_round(bench, pages, "Working together")
            counts = [impairment_counts(page) for page in pages]
            corrected = [corrections(page) for page in pages]
        captures = recorded_captures(bench)

    assert len(captures) == 1, "the room did not record exactly one episode"
    assert len(captures[0]["frames"]) == _STEPS
    assert_agrees_with_the_oracle(bench, captures[0], schedules)

    total = {key: sum(count[key] for count in counts) for key in counts[0]}
    assert total["sent"] >= 2 * _STEPS - 20, (
        "the peers barely spoke, so the shim was hardly on the path at all"
    )
    hurt = total["late"] + total["dropped"] + total["held"]
    assert hurt >= least_hurt, (
        f"{impairment.label()} cost the mesh nothing: no packet was lost, held, or "
        "late for its frame, so this scenario is not exercising what it claims to"
    )
    if impairment == Impairment():
        # The clean link is the control. If it were quietly impaired, every other
        # row would be measuring the wrong thing.
        assert total["dropped"] == total["held"] == total["delayed"] == 0
        assert total["passed"] == total["sent"]
    elif impairment.latency_ms or impairment.jitter_ms:
        assert total["delayed"] >= _STEPS, "the shim delayed almost nothing"

    # What the engine did about it. This is the assertion that tells a mesh which
    # rolled back and replayed apart from one which never had to.
    assert max(corrected) >= least_corrected, (
        f"{impairment.label()} made the peers correct themselves {corrected} times, "
        f"and this scenario claims at least {least_corrected}. Either the engine did "
        "not roll back or it was not the engine being driven."
    )
    if impairment == Impairment():
        assert corrected == [0, 0], (
            f"a clean link corrected itself {corrected} times, so the control is "
            "not a control"
        )


def test_a_crowded_mesh_reaches_the_true_trajectory(
    browser: Browser, tmp_path: Path
) -> None:
    """Three real browsers, each behind its own bad link.

    Every peer predicts every other, so the work grows with the square of the
    room while the answer must not change at all.
    """
    impairments = [
        Impairment(latency_ms=180, jitter_ms=60, seed=11),
        Impairment(latency_ms=90, loss=0.2, seed=22),
        Impairment(latency_ms=140, jitter_ms=40, loss=0.1, seed=33),
    ]
    with serve_mesh(tmp_path, peers=3, max_steps=_STEPS, fps=_FPS) as bench:
        with _peers(browser, bench, impairments) as pages:
            schedules = _play_one_round(bench, pages, "Working together")
            counts = [impairment_counts(page) for page in pages]
        captures = recorded_captures(bench)

    assert len(captures) == 1
    assert len(captures[0]["frozen_peer_handles"]) == 3
    assert_agrees_with_the_oracle(bench, captures[0], schedules)
    assert sum(count["late"] + count["dropped"] for count in counts) > 0


def test_a_peer_that_goes_away_and_comes_back_still_lands_on_the_truth(
    browser: Browser, tmp_path: Path
) -> None:
    """One browser says nothing for a while, then everything at once.

    A closed lid or a changed network. It is the deepest rollback the engine ever
    performs, because the whole silent window arrives together and every frame in
    it was predicted.
    """
    away = Impairment(latency_ms=40, partition_ms=(900, 2400))
    with serve_mesh(tmp_path, peers=2, max_steps=_STEPS, fps=_FPS) as bench:
        with _peers(browser, bench, [away, Impairment(latency_ms=40)]) as pages:
            schedules = _play_one_round(bench, pages, "Working together")
            counts = [impairment_counts(page) for page in pages]
        captures = recorded_captures(bench)

    assert len(captures) == 1
    assert len(captures[0]["frames"]) == _STEPS
    assert_agrees_with_the_oracle(bench, captures[0], schedules)
    assert counts[0]["held"] >= 10, (
        "the peer was never really away, so this proves nothing about coming back"
    )


def test_several_rounds_are_each_recorded_and_each_true(
    browser: Browser, tmp_path: Path
) -> None:
    """A study is not one episode. Every round is its own run, and each is right.

    A second round starts a new room over the same connections. It is where a
    peer would carry state it should have left behind: a replica that kept the
    first round's generator, an engine that kept its frame counter, a room that
    reused the first membership. Each round is checked on its own.
    """
    impairment = Impairment(latency_ms=170, jitter_ms=70, loss=0.15, seed=7)
    with serve_mesh(tmp_path, peers=2, rounds=2, max_steps=_STEPS, fps=_FPS) as bench:
        with _peers(browser, bench, [impairment, impairment]) as pages:
            first = _play_one_round(bench, pages, "Working together")
            second = _play_one_round(bench, pages, "Between rounds")
            for page in pages:
                page.wait_for_selector("text=Thank you", timeout=60_000)
        captures = recorded_captures(bench)
        episodes = recorded_episodes(bench)

    assert len(captures) == 2, "a two-round study did not record two episodes"
    assert len(episodes) == 2
    assert len({episode["episode_id"] for episode in episodes}) == 2, (
        "the two rounds were recorded under one episode identity"
    )
    for capture, schedules in ((captures[0], first), (captures[1], second)):
        assert len(capture["frames"]) == _STEPS
        assert_agrees_with_the_oracle(bench, capture, schedules)


def test_the_oracle_would_notice_if_the_mesh_were_wrong(
    browser: Browser, tmp_path: Path
) -> None:
    """The comparison must be able to fail, or every check above is decoration.

    A trajectory in which every input landed one frame later than it was played is
    a plausible, self-consistent and wrong answer. Every peer would share it, so a
    peer-against-peer comparison holds throughout and the room records the run.
    The oracle must reject it.
    """
    with serve_mesh(tmp_path, peers=2, max_steps=_STEPS, fps=_FPS) as bench:
        with _peers(browser, bench, [Impairment(latency_ms=200)] * 2) as pages:
            schedules = _play_one_round(bench, pages, "Working together")
        captures = recorded_captures(bench)

    capture = captures[0]
    peers = sorted(capture["frozen_peer_handles"])
    frames = list(capture["frames"])
    right = oracle_frames(bench, peers, schedules, len(frames))
    assert frames == right

    # The counterfactual: every peer's input applied one frame later than it was
    # played. It is the off-by-one a rollback gets wrong, and every peer would
    # share it, so peer-against-peer parity would hold throughout.
    shifted = {
        peer: {
            frame: schedule.get(frame - 1, bench.spec.default_action)
            for frame in schedule
        }
        for peer, schedule in schedules.items()
    }
    assert _differs(schedules, shifted, len(frames)), (
        "the participants never varied their input, so this scenario cannot say "
        "whether the oracle reads the schedule at all"
    )
    assert right != oracle_frames(bench, peers, shifted, len(frames)), (
        "the oracle is insensitive to the schedule it checks"
    )


def _differs(
    left: Mapping[str, Mapping[int, int]],
    right: Mapping[str, Mapping[int, int]],
    frames: int,
) -> bool:
    """Whether two input schedules disagree anywhere inside the played frames."""
    return any(
        left[peer].get(frame) != right[peer].get(frame)
        for peer in left
        for frame in range(frames)
    )
