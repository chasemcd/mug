"""Verify a browser-reported run by re-executing it (API-16 state-hash check).

In the browser execution mode the environment steps in the participant browser
and the client writes the episode. So a client-reported state hash is a claim,
not evidence. This module turns the claim into evidence: it re-executes the run
on the server from the fixed seed and the client's own action sequence, computes
each state hash with the shared hook, and compares the re-execution against what
the client reported. The result is a per-frame ``StateHashCheck`` chain and one
honest verdict.

The run is deterministic by construction: the seed is fixed, the environment
source bundle is the same code the browser ran (through Pyodide, which is CPython
and numpy), and the state hash uses only the standard library, so both sides
compute it the same way. The action sequence is the client's claim of its inputs;
the state hashes are the verifiable consequence of running the real environment
under those inputs. A client that fakes a solved outcome must supply an action
sequence that genuinely reaches it -- which is a genuine solve.

When the server cannot re-execute the run -- the environment package is not
installed, or the bundle does not build -- it does not fake a match. It declares a
visual fallback, and the caller commits the run as recorded but unverified, per
the API-16 boundary: replay either verifies deterministic state or declares a
visual fallback, never a faked match.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from mug.game.browser import BrowserGameSpec
from mug.game.determinism import state_hash, state_hash_chain
from mug.game.runtime import EpisodeSummary
from mug.game.trajectory import TrajectoryFrame
from mug.kernel import Digest
from mug.replay.types import (
    DeterministicStateHashCheck,
    StateHashCheck,
    VisualFallbackStateHashCheck,
)


@dataclass(frozen=True)
class VerificationReport:
    """The verdict of re-executing and checking a browser-reported run.

    ``verification`` is ``deterministic`` when the server re-executed the run, or
    ``visual-fallback`` when it could not. ``verified`` is true only when the
    verification is deterministic and every state hash matched. ``checks`` is the
    per-frame state-hash chain the caller may persist or export.
    ``state_hash_chain_digest`` binds the re-executed trajectory when the
    verification is deterministic. ``reason`` names the fallback cause otherwise.

    ``trajectory`` is what the re-execution saw: the action, the observation, the
    reward, the flags, and the environment's metrics per frame. A browser reports
    digests and its own actions, never the values, so a server that verifies a run
    is the only place those values exist -- and dropping them would leave a
    browser-run study with no data. A fallback verifies nothing and records none.
    """

    verification: str
    verified: bool
    checks: tuple[StateHashCheck, ...]
    state_hash_chain_digest: Digest | None
    reason: str | None
    trajectory: Sequence[TrajectoryFrame] = ()


@dataclass(frozen=True)
class _ReferenceRun:
    """The server re-execution of a run: the hashes the client should report."""

    frame_hashes: list[Digest]
    action_hashes: list[Digest]
    final_hash: Digest
    trajectory: list[TrajectoryFrame]


def _reference_run(
    spec: BrowserGameSpec,
    actions: list[int],
    seat_key: str,
    partner_actions: Sequence[int] = (),
) -> _ReferenceRun:
    """Re-execute the run from the seed and actions, returning the true hashes.

    The environment comes from the same source bundle the browser ran, so the
    server checks the real environment, not a second copy that could drift. It
    imports the environment adapter lazily, so this module loads without the game
    extra and only needs it to actually verify.

    A run with an exported partner is re-executed under **both** action sequences.
    The partner is scored by the browser's own inference runtime, which the server
    has no copy of, so its decisions travel with the run the way the participant's
    do and are handed back to the bundle here. What that verifies is unchanged in
    kind: the state hashes are the consequence of running the real environment
    under the reported inputs, and a client that reports inputs the environment
    would not have produced this trajectory from fails.
    """
    from mug.game.env import GymEnv

    # The bundle is trusted study code -- the same source the browser ran, and no
    # worse than importing a study's server-side factory.
    namespace: dict[str, object] = {}
    exec(spec.source_bundle, namespace)
    factory = namespace["make_env"]
    env = GymEnv(factory, seed=spec.seed)  # pyright: ignore[reportArgumentType]
    partner_acts = namespace.get("partner_acts") if spec.partner is not None else None

    state = env.reset()
    frame_hashes: list[Digest] = []
    action_hashes: list[Digest] = []
    trajectory: list[TrajectoryFrame] = []
    for index, action in enumerate(actions, start=1):
        if callable(partner_acts) and index <= len(partner_actions):
            partner_acts(int(partner_actions[index - 1]))
        state = env.step(action)
        frame_hashes.append(state_hash(state.observation))
        action_hashes.append(state_hash(action))
        # The browser's transition digests commit to the whole action and
        # observation set for the seat, so the recorded values are keyed the same
        # way the digests were taken.
        trajectory.append(
            TrajectoryFrame(
                frame_number=index,
                actions={seat_key: int(action)},
                observations={seat_key: state.observation},
                rewards={seat_key: state.reward},
                terminated=state.terminated,
                truncated=state.truncated,
                info=dict(state.info),
            )
        )
    final_hash = state_hash(state.observation)
    return _ReferenceRun(frame_hashes, action_hashes, final_hash, trajectory)


def _visual_fallback(summary: EpisodeSummary, reason: str) -> VerificationReport:
    """Build a visual-fallback verdict: one check per frame, no faked match."""
    episode_id = summary.boundary.episode_id
    checks: list[StateHashCheck] = [
        VisualFallbackStateHashCheck(
            episode_id=episode_id,
            frame_number=transition.frame_number,
            verification="visual-fallback",
            reason="state-hash-unavailable",
        )
        for transition in summary.transitions
    ]
    return VerificationReport(
        verification="visual-fallback",
        verified=False,
        checks=tuple(checks),
        state_hash_chain_digest=None,
        reason=reason,
    )


def verify_browser_episode(
    spec: BrowserGameSpec,
    *,
    actions: list[int],
    summary: EpisodeSummary,
    partner_actions: Sequence[int] = (),
) -> VerificationReport:
    """Re-execute a browser-reported run and check every state hash against it.

    The server re-runs the environment from the fixed seed and the client's own
    action sequence and compares each re-computed state hash to the client's
    report. It verifies only when every frame's state hash and action digest
    match and the closing boundary hash matches. Any divergence, a wrong action
    count, or an environment it cannot re-execute leaves ``verified`` false, so
    the caller refuses a divergent run and never commits a faked match.
    """
    if spec.verification != "deterministic":
        # The study has said its environment does not repeat. Re-executing it would
        # produce a different trajectory from an honest run and refuse it, so every
        # participant's round would be discarded at the end with nothing recorded.
        # What is recorded instead is the run as reported, carrying the verdict that
        # says it was not checked -- which a reader can act on, unlike an absence.
        return _visual_fallback(summary, "environment-not-reproducible")
    if len(actions) != len(summary.transitions):
        return VerificationReport(
            verification="deterministic",
            verified=False,
            checks=(),
            state_hash_chain_digest=None,
            reason="action-count-mismatch",
        )
    if spec.partner is not None and len(partner_actions) != len(actions):
        # A partner that acted on every frame reported an action for every frame.
        # A run that says otherwise cannot be re-executed as it was played, so it
        # is refused rather than re-executed against a partner that stood still.
        return VerificationReport(
            verification="deterministic",
            verified=False,
            checks=(),
            state_hash_chain_digest=None,
            reason="partner-action-count-mismatch",
        )

    try:
        reference = _reference_run(spec, actions, summary.seat_key, partner_actions)
    except Exception:
        # Any re-execution failure -- a missing package, a bundle that does not
        # build -- declares a visual fallback rather than a faked match.
        return _visual_fallback(summary, "re-execution-unavailable")

    episode_id = summary.boundary.episode_id
    checks: list[StateHashCheck] = []
    verified = True
    for index, transition in enumerate(summary.transitions):
        expected = reference.frame_hashes[index]
        observed = transition.state_digest
        result = "match" if expected == observed else "mismatch"
        checks.append(
            DeterministicStateHashCheck(
                episode_id=episode_id,
                frame_number=transition.frame_number,
                expected_state_hash=expected,
                observed_state_hash=observed,
                result=result,
                verification="deterministic",
            )
        )
        if result != "match":
            verified = False
        if transition.action_digest != reference.action_hashes[index]:
            verified = False

    if summary.boundary.state_hash != reference.final_hash:
        verified = False

    chain = state_hash_chain([digest.hex for digest in reference.frame_hashes])
    return VerificationReport(
        verification="deterministic",
        verified=verified,
        checks=tuple(checks),
        state_hash_chain_digest=chain if verified else None,
        reason=None,
        # A run that did not verify is not this trajectory, so the values are
        # withheld: recording them would attach a re-execution to a run that
        # diverged from it.
        trajectory=reference.trajectory if verified else (),
    )


__all__ = ["VerificationReport", "verify_browser_episode"]
