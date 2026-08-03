"""Close a reported run: assemble what arrived, check it, and record it.

A browser-run game arrives in parts while it is played (``mug.game.capture_parts``).
Sealing is the other end of that: the moment the platform stops collecting claims and
decides what actually happened.

It runs at two moments, and the difference between them is the whole reason any of
this exists.

- **The client closed the episode.** The run is complete and is sealed at the
  boundary the client wrote, which is what a single end-of-round report always did.
- **Nobody closed it.** The participant shut the tab, the machine slept, the process
  restarted. The run is sealed at the last frame that arrived, under a boundary the
  server writes for it. Four hundred frames of six hundred is four hundred frames,
  and it used to be nothing.

Verification is unchanged and is not weakened by any of it. The server re-executes
whatever prefix arrived and matches every state hash, so a divergent run still
records no trajectory. That works because re-execution is a function of the seed and
the actions, and a prefix of the actions is as re-executable as the whole.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

from mug.game.browser import (
    BrowserGameSpec,
    ClientEpisodeError,
    capture_browser_episode,
    parse_client_episode,
)
from mug.game.capture_parts import CaptureProgress, assemble, mark_sealed
from mug.kernel import CommandReceipt
from mug.replay.verify import verify_browser_episode
from mug.runtime import CommandContext
from mug.storage import ArtifactStore, Store


@dataclass(frozen=True)
class SealOutcome:
    """What sealing one run decided.

    ``recorded`` is whether an episode was committed. ``frames`` is how many arrived,
    which is not always how many the study asked for -- that is the point. ``reason``
    names why nothing was recorded, and is None when something was.
    """

    recorded: bool
    frames: int
    closed: bool
    verification: str | None = None
    receipt: CommandReceipt | None = None
    reason: str | None = None
    # The stream the episode's own events landed on. The visit records it, so the
    # export finds the run's transitions and its boundary; the progress record sits
    # on a different stream and is not what a reader of the visit is looking for.
    stream_id: str | None = None


def _boundary_for(run: Any, progress: CaptureProgress) -> dict[str, Any] | None:
    """Return the boundary this run closes on, writing one when nobody did.

    A client that closed the episode wrote the boundary and it is used as reported.
    A run that was abandoned has none, so the server writes one at the last frame
    that arrived: it ended without reaching a terminal state, which is exactly what
    ``reset`` means, and its state hash is the last transition's own -- the two are
    the same observation, so the re-execution matches it without any special case.
    """
    if run.boundary is not None:
        return cast("dict[str, Any]", run.boundary)
    if not run.transitions:
        return None
    last = cast("dict[str, Any]", run.transitions[-1])
    return {
        "episode_id": progress.run.episode_id,
        "interaction_id": progress.run.interaction_id,
        "kind": "reset",
        "end_frame_exclusive": progress.high_water,
        "authority": "browser",
        "state_hash": last["state_digest"],
    }


async def seal_run(
    progress: CaptureProgress,
    *,
    spec: BrowserGameSpec,
    capture_context: CommandContext,
    sealed_context: CommandContext,
    epoch_id: str,
    store: Store,
    artifacts: ArtifactStore,
    new_artifact_id: Callable[[], str],
    new_upload_id: Callable[[], str],
    now: Callable[[], str],
) -> SealOutcome:
    """Assemble, verify, and record one reported run. Returns what it decided.

    ``sealed_context`` marks the run sealed afterwards, under a compare-and-set on
    the progress revision, so two processes sweeping at once cannot both record it.
    The mark is written **after** the capture: a process that dies between the two
    leaves a run that the next sweep seals again, and the capture is keyed by its own
    idempotency so the second attempt adds nothing. The other order would lose runs.
    """
    if progress.sealed:
        return SealOutcome(recorded=False, frames=0, closed=progress.closed,
                           reason="already-sealed")
    run = await assemble(progress, artifacts=artifacts)
    if run.frames == 0:
        return SealOutcome(recorded=False, frames=0, closed=False, reason="no-frames")

    boundary = _boundary_for(run, progress)
    try:
        summary = parse_client_episode(
            {"transitions": run.transitions, "boundary": boundary},
            expected_channel_key=progress.run.channel_key,
            expected_episode_id=progress.run.episode_id,
            seat_key=progress.run.seat_key,
        )
    except ClientEpisodeError as refusal:
        return SealOutcome(
            recorded=False,
            frames=run.frames,
            closed=run.closed,
            reason=f"did-not-validate: {refusal}",
        )

    report = verify_browser_episode(
        spec,
        actions=run.actions,
        summary=summary,
        partner_actions=run.partner_actions,
    )
    if report.verification == "deterministic" and not report.verified:
        # Unchanged from the single-report path: a run that does not match its own
        # re-execution records nothing, whether it was closed or abandoned.
        return SealOutcome(
            recorded=False,
            frames=run.frames,
            closed=run.closed,
            verification=report.verification,
            reason=report.reason or "did-not-match-the-re-execution",
        )

    receipt = await capture_browser_episode(
        summary._replace(trajectory=report.trajectory),
        visit_id=progress.run.visit_id,
        context=capture_context,
        epoch_id=epoch_id,
        generation=progress.run.generation,
        store=store,
        verification=report.verification,
        state_hash_chain_digest=report.state_hash_chain_digest,
        artifacts=artifacts,
        new_artifact_id=new_artifact_id,
        new_upload_id=new_upload_id,
        now=now,
        activity_key=progress.run.activity_key,
    )
    if receipt.outcome != "accepted":
        return SealOutcome(
            recorded=False,
            frames=run.frames,
            closed=run.closed,
            verification=report.verification,
            receipt=receipt,
            reason="the capture was not accepted",
        )
    await mark_sealed(progress, context=sealed_context, store=store, now=now)
    return SealOutcome(
        recorded=True,
        frames=run.frames,
        closed=run.closed,
        verification=report.verification,
        receipt=receipt,
        stream_id=capture_context.stream_id,
    )


async def seal_abandoned(
    *,
    spec: BrowserGameSpec,
    before: str,
    store: Store,
    artifacts: ArtifactStore,
    mint: Callable[[str, str], CommandContext],
    new_id: Callable[[str], str],
    now: Callable[[], str],
) -> list[SealOutcome]:
    """Seal every run that stopped reporting and was never closed.

    This is the backstop, and it is what makes the claims worth staging durably: the
    hook on a closing connection covers the ordinary case, but a process that is
    killed mid-round runs no hook at all. The parts are already in the store, so a
    later process -- this one, a replica, a restart -- can still turn them into the
    episode the participant played.

    ``before`` is an instant: a run heard from at or after it is left alone, because
    the participant may still be playing or may be reconnecting. ``mint`` is given
    the aggregate identifier and a purpose and returns a command context, which is
    how this stays free of the gateway and the session.

    A run is marked sealed under a compare-and-set, so two processes sweeping at once
    do not both record it.
    """
    from mug.game.capture_parts import progress_aggregate_id, unsealed_runs

    outcomes: list[SealOutcome] = []
    for progress in unsealed_runs(store, before=before):
        episode_id = progress.run.episode_id
        outcomes.append(
            await seal_run(
                progress,
                spec=spec,
                capture_context=mint(episode_id, "capture"),
                sealed_context=mint(progress_aggregate_id(episode_id), "sealed"),
                epoch_id=new_id("prodepoch"),
                store=store,
                artifacts=artifacts,
                new_artifact_id=lambda: new_id("artifact"),
                new_upload_id=lambda: new_id("upload"),
                now=now,
            )
        )
    return outcomes


__all__ = ["SealOutcome", "seal_abandoned", "seal_run"]
