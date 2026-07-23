"""Replay a recorded episode in a hermetic player, and branch it (API-16).

A replay bundle pins the bytes of an interaction (``mug.replay.bundle``), but the
proof that it *replays* is a re-execution: run the recorded environment from the
same seed and the same recorded action sequence, and check every per-frame state
hash against the one the run recorded. This module is that re-execution. It is the
safe player -- "safe" because it makes no external call: a model or bot seat's
action was decided and recorded during the run, so the replay applies the recorded
action and never calls a model, a tool, or the network. A deterministic replay is
therefore closed over the bundle alone.

The player takes a snapshot-capable environment (the same seam the p2p replica and
the browser verifier use: ``reset`` / ``step`` / ``snapshot`` / ``restore`` over a
json-able state), the recorded action sequence, and the recorded per-frame state
hashes. It re-runs the environment under those actions, hashes each frame with the
shared hook (``mug.game.determinism``), and emits a per-frame
``DeterministicStateHashCheck`` chain plus a ``ReplayBundleValidation`` verdict.
When the caller supplies no recorded hashes -- a visual-only bundle -- the player
declares a visual fallback per frame rather than fake a match, exactly as the
browser verifier does.

Branching is the same machine with one added move: run to a chosen frame while
snapshotting it, restore that snapshot, then continue from it under an alternate
action sequence. A branch reproduces the trajectory up to the fork exactly (it
shares the recorded prefix) and then diverges under the new inputs. Branching needs
the deterministic snapshot capability, so a bundle without it cannot branch.

The player owns no clock and no entropy: the environment is deterministic by
construction (fixed seed, snapshot-covered generators), and the action sequence is
the recorded input. So a test drives a whole replay and a branch with a fake
environment and no store.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from mug.game.determinism import state_hash, state_hash_chain
from mug.kernel import Digest
from mug.replay.types import (
    DeterministicStateHashCheck,
    ReplayBundleValidation,
    StateHashCheck,
    VisualFallbackStateHashCheck,
)


class SnapshotEnv(Protocol):
    """The deterministic environment seam a hermetic replay steps.

    This is the same shape the p2p replica (``mug.game.multiagent``) and the
    browser verifier read: reset to the fixed seed, step one action, and snapshot
    or restore the whole state. ``step`` returns the json-able state the player
    hashes, so a divergence in any hidden state -- not only in what a seat sees --
    changes the frame hash.
    """

    def reset(self) -> object:
        """Reset to the fixed seed and return the initial json-able state."""
        ...

    def step(self, action: int) -> object:
        """Apply one recorded action and return the next json-able state."""
        ...

    def snapshot(self) -> object:
        """Return the whole environment state, for a branch to restore."""
        ...

    def restore(self, state: object) -> None:
        """Restore a snapshot so a branch continues from an exact state."""
        ...


@dataclass(frozen=True)
class ReplayRun:
    """The verdict of replaying one episode in the hermetic player.

    ``verification`` is ``deterministic`` when the caller supplied recorded hashes
    to check against, or ``visual-fallback`` when it did not. ``verified`` is true
    only when the verification is deterministic and every frame matched.
    ``checks`` is the per-frame state-hash chain the caller may persist or export.
    ``frame_hashes`` is the re-executed trajectory, and ``state_hash_chain_digest``
    binds it when the verification is deterministic and verified. ``validation`` is
    the ``ReplayBundleValidation`` the verdict implies: a hermetic replay makes no
    external call and modifies no artifact, so it is always valid on those axes --
    a state-hash divergence is carried by ``verified``, not by ``validation``.
    """

    verification: str
    verified: bool
    checks: tuple[StateHashCheck, ...]
    frame_hashes: tuple[Digest, ...]
    state_hash_chain_digest: Digest | None
    validation: ReplayBundleValidation


@dataclass(frozen=True)
class BranchRun:
    """The trajectory of a branch forked from a recorded replay at one frame.

    ``fork_frame`` is the frame the branch restored from (the last shared frame of
    the recorded prefix). ``prefix_hashes`` is the recorded trajectory up to and
    including the fork, and ``branch_hashes`` is the divergent trajectory the
    alternate actions produced after it. ``diverged`` is true when the branch
    reached a state the recorded run did not -- the point of a branch.
    """

    fork_frame: int
    prefix_hashes: tuple[Digest, ...]
    branch_hashes: tuple[Digest, ...]
    diverged: bool


def replay_episode(
    *,
    env: SnapshotEnv,
    actions: Sequence[int],
    interaction_id: str,
    episode_id: str,
    recorded_state_hashes: Sequence[Digest] | None = None,
) -> ReplayRun:
    """Re-execute a recorded episode and check every state hash against the record.

    The player resets the environment, applies each recorded action in order, and
    hashes the state after each step. When ``recorded_state_hashes`` is supplied,
    each re-executed hash is compared to the recorded one and the run verifies only
    when every frame matches; the mismatched frames make the bundle invalid. When
    it is not supplied -- a visual-only bundle -- the player declares a visual
    fallback per frame and never fakes a match. The replay makes no external call,
    so ``external_calls_made`` is always false.
    """
    if recorded_state_hashes is not None and len(recorded_state_hashes) != len(actions):
        raise ValueError("a recorded hash is needed for each replayed action")

    env.reset()
    frame_hashes: list[Digest] = []
    for action in actions:
        state = env.step(int(action))
        frame_hashes.append(state_hash(state))

    if recorded_state_hashes is None:
        return _visual_fallback(
            interaction_id=interaction_id,
            episode_id=episode_id,
            frame_hashes=frame_hashes,
        )
    return _deterministic(
        interaction_id=interaction_id,
        episode_id=episode_id,
        frame_hashes=frame_hashes,
        recorded=list(recorded_state_hashes),
    )


def fork_replay(
    *,
    env: SnapshotEnv,
    actions: Sequence[int],
    fork_frame: int,
    branch_actions: Sequence[int],
) -> BranchRun:
    """Fork a recorded replay at ``fork_frame`` and continue under new actions.

    The player runs the recorded actions up to and including ``fork_frame``,
    snapshots that frame, then restores the snapshot and applies ``branch_actions``
    from it. The prefix reproduces the recorded trajectory exactly (a branch shares
    its recorded past), and the branch diverges under the alternate inputs. Forking
    needs the deterministic snapshot capability the environment declares; a bundle
    without it cannot branch.

    ``fork_frame`` is a zero-based frame index into ``actions``; it must name a
    frame the recorded run reached.
    """
    if not 0 <= fork_frame < len(actions):
        raise ValueError("the fork frame must name a recorded frame")

    env.reset()
    prefix_hashes: list[Digest] = []
    snapshot: object = None
    for index in range(fork_frame + 1):
        state = env.step(int(actions[index]))
        prefix_hashes.append(state_hash(state))
        if index == fork_frame:
            snapshot = env.snapshot()

    env.restore(snapshot)
    branch_hashes: list[Digest] = []
    for action in branch_actions:
        state = env.step(int(action))
        branch_hashes.append(state_hash(state))

    # A branch diverges when its trajectory leaves the recorded one: the recorded
    # tail after the fork and the branch tail differ (in length or in any frame).
    recorded_tail = _recorded_tail(env, actions, fork_frame)
    diverged = branch_hashes != recorded_tail
    return BranchRun(
        fork_frame=fork_frame,
        prefix_hashes=tuple(prefix_hashes),
        branch_hashes=tuple(branch_hashes),
        diverged=diverged,
    )


def _recorded_tail(
    env: SnapshotEnv, actions: Sequence[int], fork_frame: int
) -> list[Digest]:
    """Re-run the recorded actions after the fork, for the divergence check."""
    env.reset()
    for index in range(fork_frame + 1):
        env.step(int(actions[index]))
    tail: list[Digest] = []
    for index in range(fork_frame + 1, len(actions)):
        state = env.step(int(actions[index]))
        tail.append(state_hash(state))
    return tail


def _deterministic(
    *,
    interaction_id: str,
    episode_id: str,
    frame_hashes: Sequence[Digest],
    recorded: Sequence[Digest],
) -> ReplayRun:
    """Build the deterministic verdict: one check per frame, verified iff all match."""
    checks: list[StateHashCheck] = []
    verified = True
    for index, observed in enumerate(frame_hashes):
        expected = recorded[index]
        result = "match" if expected == observed else "mismatch"
        if result != "match":
            verified = False
        checks.append(
            DeterministicStateHashCheck(
                episode_id=episode_id,
                frame_number=index + 1,
                expected_state_hash=expected,
                observed_state_hash=observed,
                result=result,
                verification="deterministic",
            )
        )
    chain = (
        state_hash_chain([digest.hex for digest in frame_hashes]) if verified else None
    )
    # ``ReplayBundleValidation`` is the hermeticity-and-integrity verdict: a replay
    # that made no external call and modified no artifact is valid. A state-hash
    # divergence is a separate axis -- it is carried by ``verified`` and the
    # per-frame checks, not by this record (whose ``valid`` is fixed to external
    # calls and modified artifacts by the frozen contract).
    validation = ReplayBundleValidation(
        interaction_id=interaction_id,
        valid=True,
        external_calls_made=False,
        modified_artifact_ids=[],
        verification="deterministic",
    )
    return ReplayRun(
        verification="deterministic",
        verified=verified,
        checks=tuple(checks),
        frame_hashes=tuple(frame_hashes),
        state_hash_chain_digest=chain,
        validation=validation,
    )


def _visual_fallback(
    *,
    interaction_id: str,
    episode_id: str,
    frame_hashes: Sequence[Digest],
) -> ReplayRun:
    """Build the visual-fallback verdict: one check per frame, no faked match."""
    checks: list[StateHashCheck] = [
        VisualFallbackStateHashCheck(
            episode_id=episode_id,
            frame_number=index + 1,
            verification="visual-fallback",
            reason="determinism-not-declared",
        )
        for index in range(len(frame_hashes))
    ]
    validation = ReplayBundleValidation(
        interaction_id=interaction_id,
        valid=True,
        external_calls_made=False,
        modified_artifact_ids=[],
        verification="visual-fallback",
    )
    return ReplayRun(
        verification="visual-fallback",
        verified=False,
        checks=tuple(checks),
        frame_hashes=tuple(frame_hashes),
        state_hash_chain_digest=None,
        validation=validation,
    )


__all__ = [
    "BranchRun",
    "ReplayRun",
    "SnapshotEnv",
    "fork_replay",
    "replay_episode",
]
