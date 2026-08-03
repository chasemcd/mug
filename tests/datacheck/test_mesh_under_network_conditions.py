"""Many peers, a badly-behaved network, and the trajectory that should have been.

The legacy suite connected several browsers and played real games under injected
latency, packet loss and disruption. ``tests/unit/game/test_p2p_rollback.py``
reproduced that as deterministic unit tests and checks that every peer ends with the
same trajectory.

Agreement is not correctness. A rollback that rebuilt the wrong frames the same way
on every replica satisfies a parity check exactly, and so would a prediction that was
never corrected because the correction was also wrong everywhere. What is missing is
an outside statement of what the run *should* have been.

``mesh_bench.oracle_rows`` is that statement: the input schedule is known in full, so
the true trajectory is one bare replica stepped with the complete action set for
every frame -- no engine, no prediction, no rollback, no network. Every peer must
match **it**, under whatever the network did.

Each scenario also asserts that the mechanism it names actually engaged. A test
called "survives packet loss" that happened to lose nothing, or "forces a deep
rollback" that rolled back one frame, is a test of nothing; the rollback counters are
checked so the scenario cannot pass by being easy.

Every condition is seeded, so a failure reproduces exactly rather than sometimes.
"""

from __future__ import annotations

import pytest

from mug.game.desync_repair import resync_peer
from tests.datacheck.mesh_bench import (
    Conditions,
    actor,
    assert_agrees_with_the_oracle,
    oracle_rows,
    run_mesh,
    script_for,
)

_FRAMES = 60
_DELAY = 2

# The ways a peer-to-peer connection misbehaves, and how much rollback each must
# force. ``least_rollbacks`` is what stops a scenario passing because nothing
# actually went wrong.
_CONDITIONS = [
    pytest.param(Conditions(), 0, 0, id="a clean link"),
    pytest.param(Conditions(latency=3), 1, 1, id="latency inside the delay"),
    pytest.param(Conditions(latency=8), 20, 4, id="latency well past the delay"),
    pytest.param(Conditions(latency=4, jitter=3), 10, 2, id="jitter reorders arrivals"),
    pytest.param(Conditions(latency=3, loss=0.2), 10, 2, id="one packet in five lost"),
    pytest.param(Conditions(latency=3, loss=0.5), 15, 3, id="half the packets lost"),
    pytest.param(
        Conditions(latency=5, jitter=4, loss=0.35), 15, 3, id="all three at once"
    ),
]


@pytest.mark.parametrize("conditions,least_rollbacks,least_depth", _CONDITIONS)
def test_two_peers_reach_the_true_trajectory(
    conditions: Conditions, least_rollbacks: int, least_depth: int
) -> None:
    """Whatever the network does, the recorded run is the run the inputs imply."""
    outcome = run_mesh(2, frames=_FRAMES, conditions=conditions, input_delay=_DELAY)

    assert_agrees_with_the_oracle(outcome, frames=_FRAMES, input_delay=_DELAY)
    assert outcome.any_rollback() >= least_rollbacks, (
        f"{conditions.label()} forced only {outcome.any_rollback()} rollbacks, so "
        "this scenario is not exercising what it claims to"
    )
    assert max(outcome.deepest.values()) >= least_depth


@pytest.mark.parametrize("peers", [3, 4, 6])
def test_a_crowded_mesh_reaches_the_true_trajectory(peers: int) -> None:
    """More peers means more predictions to be wrong about, and more to reconcile.

    Every peer predicts every other, so the work grows with the square of the room
    while the answer must not change at all.
    """
    conditions = Conditions(latency=6, jitter=2, loss=0.2, seed=99 + peers)
    outcome = run_mesh(peers, frames=_FRAMES, conditions=conditions, input_delay=_DELAY)

    assert_agrees_with_the_oracle(outcome, frames=_FRAMES, input_delay=_DELAY)
    assert outcome.any_rollback() > 0
    assert len(outcome.rows) == peers


def test_a_peer_that_goes_away_and_comes_back_still_lands_on_the_truth() -> None:
    """A closed lid, a changed network: nothing for a while, then everything at once.

    This is the deepest rollback the engine ever performs, because the whole silent
    window arrives together and every frame in it was predicted.
    """
    away = actor(0)
    conditions = Conditions(latency=3, partitions={away: (18, 42)})
    outcome = run_mesh(2, frames=_FRAMES, conditions=conditions, input_delay=_DELAY)

    assert_agrees_with_the_oracle(outcome, frames=_FRAMES, input_delay=_DELAY)
    # The silence was 24 ticks, so the rollback must reach back across most of it.
    assert max(outcome.deepest.values()) >= 15, (
        "the silent window did not force a deep rollback, so this proves nothing "
        "about recovering from one"
    )


def test_two_peers_going_away_at_different_times_still_land_on_the_truth() -> None:
    """Overlapping outages: each peer is predicting a peer that is itself behind."""
    first, second = actor(0), actor(1)
    conditions = Conditions(
        latency=4,
        jitter=2,
        partitions={first: (12, 30), second: (24, 44)},
        seed=4242,
    )
    outcome = run_mesh(3, frames=_FRAMES, conditions=conditions, input_delay=_DELAY)

    assert_agrees_with_the_oracle(outcome, frames=_FRAMES, input_delay=_DELAY)
    assert max(outcome.deepest.values()) >= 10


def test_a_diverged_peer_is_repaired_back_onto_the_true_trajectory() -> None:
    """A peer whose replica went wrong is detected, repaired, and correct again.

    The existing repair test checks that the repaired peer matches the authority.
    That is the agreement-is-not-correctness gap again: it would pass just as well
    if the authority were the wrong one. Here the repaired mesh is checked against
    the oracle, so the claim is that the run is right and not merely shared.
    """
    wrong = actor(1)
    outcome = run_mesh(
        2, frames=_FRAMES, conditions=Conditions(), input_delay=_DELAY, corrupt=wrong
    )
    actors = sorted(outcome.rows)
    good = outcome.engines[actors[0]]
    bad = outcome.engines[wrong]

    # The broken replica played a run of its own. The hash exchange is what says so.
    for packet in good.outbound_hashes():
        bad.receive_hash(packet)
    for packet in bad.outbound_hashes():
        good.receive_hash(packet)
    assert bad.disputed_frames(), "a diverged peer was not detected at all"
    assert outcome.rows[wrong] != outcome.rows[actors[0]]

    # Repair from the healthy peer, then let the repaired one re-derive its frames.
    resync_peer(diverged=bad, authority=good, target_frame=bad.disputed_frames()[0])
    assert bad.repair_count() == 1
    for _ in range(_FRAMES + 20):
        if len(bad.canonical_trajectory()) >= _FRAMES:
            break
        bad.advance()

    scripts = {one: script_for(index, _FRAMES) for index, one in enumerate(actors)}
    truth = oracle_rows(actors, scripts, _FRAMES, input_delay=_DELAY)
    repaired = [record.canonical() for record in bad.canonical_trajectory()]
    assert repaired == truth, (
        "the repaired peer rejoined the mesh on a trajectory that is not the one "
        "the inputs imply"
    )


def test_the_oracle_would_notice_if_the_mesh_were_wrong() -> None:
    """The comparison must be able to fail, or every check above is decoration.

    A trajectory built from a different input delay is a plausible, self-consistent,
    wrong answer -- exactly the shape of a rollback fault that every peer shares. The
    oracle must reject it.
    """
    outcome = run_mesh(2, frames=_FRAMES, conditions=Conditions(latency=6))
    actors = sorted(outcome.rows)
    scripts = {one: script_for(index, _FRAMES) for index, one in enumerate(actors)}

    right = oracle_rows(actors, scripts, _FRAMES, input_delay=_DELAY)
    shifted = oracle_rows(actors, scripts, _FRAMES, input_delay=_DELAY + 1)

    assert outcome.rows[actors[0]] == right
    assert right != shifted, "the oracle is insensitive to the schedule it checks"
