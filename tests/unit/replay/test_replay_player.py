"""The safe player re-executes a recorded episode and branches it (API-16).

These tests drive ``mug.replay.player`` with a tiny deterministic environment, a
recorded action sequence, and the state hashes that sequence produces. They prove
the player replays a recorded run byte-identically (every frame matches, the run
is valid), refuses a run whose recorded hash diverged (a mismatch invalidates the
bundle), declares a visual fallback when no hashes are supplied (never a faked
match), makes no external call, and branches a replay at a frame under alternate
actions (the prefix is shared, the tail diverges).
"""

from __future__ import annotations

import copy

from mug.game.determinism import state_hash
from mug.kernel import Digest
from mug.replay.player import fork_replay, replay_episode

_INTERACTION = "interaction_019b6000-0000-7000-8000-000000000601"
_EPISODE = "episode_019b6000-0000-7000-8000-000000000701"


class _Accumulator:
    """A deterministic env: it keeps a running sum of the actions applied.

    The state is the whole running position, so a change in any applied action
    changes every later frame hash. It snapshots and restores its position, so a
    branch continues from an exact state.
    """

    def __init__(self) -> None:
        self._position = 0

    def reset(self) -> dict[str, int]:
        self._position = 0
        return {"position": self._position}

    def step(self, action: int) -> dict[str, int]:
        self._position += int(action)
        return {"position": self._position}

    def snapshot(self) -> object:
        return copy.deepcopy({"position": self._position})

    def restore(self, state: object) -> None:
        self._position = int(dict(state)["position"])  # type: ignore[arg-type]


def _recorded_hashes(actions: list[int]) -> list[Digest]:
    """Run the env once to capture the state hash each action produces."""
    env = _Accumulator()
    env.reset()
    return [state_hash(env.step(action)) for action in actions]


def test_the_player_replays_a_recorded_run_byte_identically() -> None:
    """Every re-executed frame matches its recorded hash; the bundle is valid."""
    actions = [1, 2, 3, 4]
    recorded = _recorded_hashes(actions)

    run = replay_episode(
        env=_Accumulator(),
        actions=actions,
        interaction_id=_INTERACTION,
        episode_id=_EPISODE,
        recorded_state_hashes=recorded,
    )

    assert run.verification == "deterministic"
    assert run.verified is True
    assert len(run.checks) == 4
    assert all(check.result == "match" for check in run.checks)  # type: ignore[union-attr]
    assert run.state_hash_chain_digest is not None
    assert run.validation.valid is True
    assert run.validation.external_calls_made is False


def test_the_player_refuses_a_run_whose_recorded_hash_diverged() -> None:
    """A recorded hash that does not match the re-execution invalidates the bundle."""
    actions = [1, 2, 3, 4]
    recorded = _recorded_hashes(actions)
    # Tamper with one recorded frame: the re-execution will not reproduce it.
    recorded[2] = Digest(algorithm="sha-256", hex="b" * 64)

    run = replay_episode(
        env=_Accumulator(),
        actions=actions,
        interaction_id=_INTERACTION,
        episode_id=_EPISODE,
        recorded_state_hashes=recorded,
    )

    assert run.verified is False
    assert run.state_hash_chain_digest is None
    # The replay stayed hermetic (no external call, no modified artifact), so the
    # bundle-integrity verdict is valid; the divergence is the state-hash mismatch.
    assert run.validation.valid is True
    mismatches = [c for c in run.checks if getattr(c, "result", None) == "mismatch"]
    assert len(mismatches) == 1


def test_the_player_declares_a_visual_fallback_without_recorded_hashes() -> None:
    """A visual-only bundle checks nothing deterministic and fakes no match."""
    actions = [1, 2, 3]

    run = replay_episode(
        env=_Accumulator(),
        actions=actions,
        interaction_id=_INTERACTION,
        episode_id=_EPISODE,
        recorded_state_hashes=None,
    )

    assert run.verification == "visual-fallback"
    assert run.verified is False
    assert len(run.checks) == 3
    assert all(check.verification == "visual-fallback" for check in run.checks)
    # A visual replay still made no external call, so it is a valid recording.
    assert run.validation.valid is True


def test_a_branch_shares_its_prefix_and_diverges_under_new_actions() -> None:
    """A fork restores a frame and continues under alternate actions, diverging."""
    actions = [1, 1, 1, 1, 1]
    recorded = _recorded_hashes(actions)

    branch = fork_replay(
        env=_Accumulator(),
        actions=actions,
        fork_frame=1,
        branch_actions=[9, 9, 9],
    )

    # The prefix reproduces the recorded trajectory up to and including the fork.
    assert branch.fork_frame == 1
    assert list(branch.prefix_hashes) == recorded[:2]
    # The branch left the recorded trajectory under the alternate inputs.
    assert branch.diverged is True
    assert list(branch.branch_hashes) != recorded[2:]


def test_a_branch_that_repeats_the_recorded_actions_does_not_diverge() -> None:
    """Re-applying the recorded tail from the fork reproduces it exactly."""
    actions = [2, 3, 4, 5]

    branch = fork_replay(
        env=_Accumulator(),
        actions=actions,
        fork_frame=1,
        branch_actions=[4, 5],
    )

    assert branch.diverged is False
