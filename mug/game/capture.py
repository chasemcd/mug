"""Commit a played episode: its canonical events, and what actually happened.

The stepping loop produces the normalized ``GameTransition`` per frame and the
closing ``EpisodeBoundary`` but holds no store. This service takes the finished
``EpisodeSummary`` and a minted context and commits the whole run in one atomic
append: one event per transition, then the boundary, all on the episode's stream.
Each event binds its own record digest, so the stream is the ordered, canonical
lineage the export later reads. For single-player the accepted stream is the
experienced stream, so there is no rollback and no decision evidence yet.

An event carries a digest and no payload, which is right for a stream every export
row copies and wrong as the whole record of a study: on its own it says a frame
happened and never what the participant did or what it earned. So when the caller
supplies an artifact store, the run's ``TrajectoryFrame`` per frame -- the executed
actions, the observations, the rewards, the flags, and the environment's own metrics
-- is staged as one content-addressed artifact and named in the episode aggregate.
The ledger keeps the digests and the artifact keeps the values, and
``verify_trajectory`` checks one against the other, so the values stay evidence
rather than a side file.

The service is authority-neutral. The server loop hands it server-authored
transitions; the browser path hands it client-authored transitions with the
same contract. The aggregate records who held authority for the run.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

from mug.game.runtime import EpisodeSummary
from mug.game.trajectory import TRAJECTORY_MEDIA_TYPE, trajectory_bytes
from mug.game.types import EpisodeBoundary, GameTransition
from mug.kernel import (
    ArtifactRef,
    CommandReceipt,
    CommandTypeRef,
    Digest,
    TypedObject,
    compute_digest,
)
from mug.kernel.privacy import DataHandlingRef
from mug.runtime import CommandContext, LedgerEvent, commit_capture, result_ref
from mug.storage import ArtifactStore, Store, stage_artifact

_CAPTURE_COMMAND = CommandTypeRef(name="episode.capture", version=0)
_RESULT_SCHEMA_NAME = "mug.command-result.visit-transition"

# The classification a recorded trajectory carries when the caller names none. It
# is research data, so it is never a client-visible or secret class.
_RESEARCH = DataHandlingRef(privacy_labels=["research"])


def _ledger_event(record: GameTransition | EpisodeBoundary) -> LedgerEvent:
    """Bind one transition or boundary as a canonical event to append."""
    return LedgerEvent(
        event_schema=record.schema,
        payload_digest=compute_digest(
            record.model_dump(mode="json", exclude_none=True)
        ),
    )


def _aggregate(
    summary: EpisodeSummary,
    verification: str | None,
    state_hash_chain_digest: Digest | None,
    trajectory: ArtifactRef | None,
    activity_key: str | None,
    anchors: ArtifactRef | None,
) -> dict[str, Any]:
    """Draft the episode aggregate state the capture commit records.

    A browser capture also records how the server verified the run and, when it
    re-executed the run, the chain digest that binds the verified trajectory. A
    server-run capture passes neither, so the aggregate keeps its original shape.

    ``activity_key`` is the study step the run belongs to. A study that plays a
    practice round and then a real one records two episodes, and only the step each
    one came from tells them apart later; without it a study can say two runs
    happened and never which was which.
    """
    boundary = summary.boundary
    aggregate: dict[str, Any] = {
        "episode_id": boundary.episode_id,
        "interaction_id": boundary.interaction_id,
        "channel_key": summary.channel_key,
        "seat_key": summary.seat_key,
        "authority": boundary.authority,
        "frame_count": summary.frames,
        "outcome": boundary.kind,
        "state_hash": boundary.state_hash.model_dump(mode="json"),
    }
    if verification is not None:
        aggregate["verification"] = verification
    if state_hash_chain_digest is not None:
        aggregate["state_hash_chain_digest"] = state_hash_chain_digest.model_dump(
            mode="json"
        )
    if trajectory is not None:
        aggregate["trajectory"] = trajectory.model_dump(mode="json", exclude_none=True)
    if activity_key is not None:
        aggregate["activity_key"] = activity_key
    if anchors is not None:
        # What was said while this run played, and at which frame. The episode is
        # where it belongs: a replay that has the episode then has the trajectory
        # and the conversation together, with no side channel to look in.
        aggregate["anchors"] = anchors.model_dump(mode="json", exclude_none=True)
    return aggregate


def recorded_activity_key(store: Store, episode_id: str) -> str | None:
    """Return the study step one episode was played for, or None when it named none."""
    state = store.load_aggregate(episode_id)
    if not isinstance(state, dict):
        return None
    key = cast("dict[str, Any]", state).get("activity_key")
    return key if isinstance(key, str) else None


def recorded_trajectory(store: Store, episode_id: str) -> ArtifactRef | None:
    """Return the trajectory artifact an episode recorded, or None when it kept none.

    The capture names the artifact on the episode aggregate, so anything that needs
    the run's values -- a replay bundle, a preference candidate, an export -- finds
    them from the episode alone, with no side channel. A run that recorded nothing
    answers None, and the caller says so rather than assume.
    """
    state = store.load_aggregate(episode_id)
    if not isinstance(state, dict):
        return None
    recorded = cast("dict[str, Any]", state).get("trajectory")
    return None if recorded is None else ArtifactRef.model_validate(recorded)


def recorded_anchors(store: Store, episode_id: str) -> ArtifactRef | None:
    """Return what was said while one episode played, or None when nothing was.

    A run of an activity that carried no conversation has no anchors, and so does a
    run nobody spoke during. Both answer None, and the caller says the episode
    records no messages rather than that none were said.
    """
    state = store.load_aggregate(episode_id)
    if not isinstance(state, dict):
        return None
    recorded = cast("dict[str, Any]", state).get("anchors")
    return None if recorded is None else ArtifactRef.model_validate(recorded)


async def _stage_trajectory(
    summary: EpisodeSummary,
    *,
    artifacts: ArtifactStore | None,
    new_artifact_id: Callable[[], str] | None,
    new_upload_id: Callable[[], str] | None,
    now: Callable[[], str] | None,
    data_handling: DataHandlingRef,
) -> ArtifactRef | None:
    """Stage the run's recorded values as one artifact, or answer that there are none.

    Every part is required together: an artifact store, the three minters, and a run
    that recorded frames. Anything missing means the values were not recorded, and
    the caller must be able to tell that from the episode rather than guess.
    """
    if artifacts is None or not summary.trajectory:
        return None
    if new_artifact_id is None or new_upload_id is None or now is None:
        return None
    return await stage_artifact(
        artifacts,
        data=trajectory_bytes(summary.trajectory),
        media_type=TRAJECTORY_MEDIA_TYPE,
        new_artifact_id=new_artifact_id,
        new_upload_id=new_upload_id,
        now=now,
        data_handling=data_handling,
    )


async def capture_episode(
    summary: EpisodeSummary,
    *,
    visit_id: str,
    context: CommandContext,
    store: Store,
    verification: str | None = None,
    state_hash_chain_digest: Digest | None = None,
    artifacts: ArtifactStore | None = None,
    new_artifact_id: Callable[[], str] | None = None,
    new_upload_id: Callable[[], str] | None = None,
    now: Callable[[], str] | None = None,
    data_handling: DataHandlingRef = _RESEARCH,
    activity_key: str | None = None,
    anchors: ArtifactRef | None = None,
) -> CommandReceipt:
    """Commit an episode's transitions, boundary, and recorded trajectory.

    With an artifact store and its three minters, the run's recorded values are
    staged as one content-addressed artifact and the episode aggregate names it, so
    a study can read what happened and check it against the ledger. Without them --
    or for a run that recorded no trajectory -- only the digests are committed, and
    every consumer can see that the values are absent rather than assume them.

    ``activity_key`` names the study step the run was played for, so a later step
    can ask about one particular run of several.

    ``anchors`` is the artifact saying what was said while this run played, and at
    which frame (``mug.conversation.anchors``). A composed activity -- a game and a
    conversation in one interaction -- records it, so the two orderings can be laid
    against each other without being merged into one. An activity with no
    conversation records none, and a reader can tell that from the episode.
    """
    trajectory = await _stage_trajectory(
        summary,
        artifacts=artifacts,
        new_artifact_id=new_artifact_id,
        new_upload_id=new_upload_id,
        now=now,
        data_handling=data_handling,
    )
    events = [_ledger_event(transition) for transition in summary.transitions]
    events.append(_ledger_event(summary.boundary))
    result = TypedObject(
        schema=result_ref(_RESULT_SCHEMA_NAME),
        data={
            "outcome": "captured",
            "visit_id": visit_id,
            "status": summary.boundary.kind,
            "revision": 1,
        },
    )
    return await commit_capture(
        context,
        command=_CAPTURE_COMMAND,
        new_state=_aggregate(
            summary,
            verification,
            state_hash_chain_digest,
            trajectory,
            activity_key,
            anchors,
        ),
        events=events,
        result=result,
        store=store,
    )


__all__ = [
    "capture_episode",
    "recorded_activity_key",
    "recorded_anchors",
    "recorded_trajectory",
]
