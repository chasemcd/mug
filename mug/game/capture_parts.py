"""What a browser reported so far, kept where a later process can still seal it.

A browser-run game is written by the participant's own client. The client used to
hold the whole run in the tab and report it once, at the end, as a single command.
That made the report all-or-nothing at the worst moment in the round: a participant
who closed the tab at frame four hundred of six hundred contributed **nothing** --
not four hundred frames, nothing at all.

This module is the other half. The client reports slices as it plays, and each slice
is staged as a content-addressed artifact: what the client *claimed*, which is not
yet what the platform believes. A small progress aggregate names those artifacts in
frame order, so a run can be assembled and sealed later by any process, including one
that never saw the participant.

**Nothing here writes a transition to the ledger**, and that is the point. The ledger
holds records the server has checked by re-executing them, and a claim is not one of
those until the run is sealed. So a divergent run still records no trajectory
(``mug.replay.verify`` decides that, exactly as before), and an abandoned run records
the part that was really played.

The progress aggregate's identifier is a pure function of the episode identifier, so
a process holding no memory of the run finds it with no lookup and no index -- the
same device ``mug.workers.attempt_aggregate_id`` uses for a job's attempt.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, cast

from mug.kernel import ArtifactRef, CommandReceipt, CommandTypeRef, compute_digest
from mug.kernel.privacy import DataHandlingRef
from mug.runtime import CommandContext, commit_command, result_ref
from mug.storage import ArtifactStore, Store, stage_artifact

# The media type one reported slice is staged under. It is the study's own research
# data: a claim about what a participant did, held until the run is sealed.
CLAIM_MEDIA_TYPE = "application/vnd.mug.episode-claim+json"

_RESEARCH = DataHandlingRef(privacy_labels=["research"])
_PART_COMMAND = CommandTypeRef(name="episode.report_part", version=0)
_RESULT_SCHEMA_NAME = "mug.command-result.visit-transition"

# The identifier body is derived from this role and the episode, so every process
# derives the same one. It is a constant of the family and not a secret.
_PROGRESS_ROLE = "mug.game.capture-progress"

# How many frames one report carries. Two things bound it. Below, a part must be
# small enough to fit the transport's own frame bound (``AdmissionPolicy``), which
# is what a part-sized report lets that bound go back to being: a constant, rather
# than a number derived from how long the longest study runs. Above, losing the last
# unreported part is what a participant who leaves costs us, and at thirty frames a
# second this is under two seconds of play.
#
# ``tests/unit/game/test_capture_parts.py`` holds it to the first of those, so
# raising it cannot quietly start refusing every report again.
FRAMES_PER_PART = 50


def progress_aggregate_id(episode_id: str) -> str:
    """Return the identifier of the aggregate holding one run's reported parts.

    A pure function of the episode identifier, so a process that never saw the run
    -- a sweep after a restart, a second replica -- finds it with no index.

    It carries the ``upload`` kind, because that is what it is: a run the client is
    still sending. Deliberately **not** the ``episode`` kind, which would be the
    obvious choice and is a trap -- an episode aggregate is what a recorded run is,
    and several readers find those by the prefix on the identifier. A progress record
    wearing that prefix would be counted as a run that happened.
    """
    seed = compute_digest([_PROGRESS_ROLE, episode_id]).hex[:32]
    raw = bytearray(bytes.fromhex(seed))
    # Force the version and variant nibbles, so the derived body is UUIDv7-shaped
    # and passes the kernel pattern for the identifier kind.
    raw[6] = 0x70 | (raw[6] & 0x0F)
    raw[8] = 0x80 | (raw[8] & 0x3F)
    body = raw.hex()
    return f"upload_{body[0:8]}-{body[8:12]}-{body[12:16]}-{body[16:20]}-{body[20:32]}"


@dataclass(frozen=True)
class RunIdentity:
    """Everything a seal needs to know about a run, and nowhere else to read it.

    This is written onto the progress aggregate rather than held in the session,
    because the process that seals an abandoned run is not always the process that
    watched it. A sweep after a restart has the episode identifier and nothing else,
    so what it needs must be in the record it can find.
    """

    episode_id: str
    interaction_id: str
    channel_key: str
    visit_id: str
    seat_key: str
    activity_key: str | None
    generation: int


@dataclass(frozen=True)
class ClaimedPart:
    """One slice of a run, as the client reported it.

    ``first_frame`` is the frame number of the first transition, counting from one.
    A part is ``final`` when the client closed the episode, and only then does it
    carry the closing ``boundary``.
    """

    first_frame: int
    transitions: list[dict[str, Any]]
    actions: list[int]
    partner_actions: list[int]
    final: bool
    boundary: dict[str, Any] | None = None

    @property
    def frames(self) -> int:
        """How many frames this part reports."""
        return len(self.transitions)

    @property
    def last_frame(self) -> int:
        """The frame number of the last transition in this part."""
        return self.first_frame + self.frames - 1


def claim_bytes(part: ClaimedPart) -> bytes:
    """Serialize one claimed part, with sorted keys so its digest is its identity."""
    return json.dumps(
        {
            "first_frame": part.first_frame,
            "transitions": part.transitions,
            "actions": part.actions,
            "partner_actions": part.partner_actions,
            "final": part.final,
            "boundary": part.boundary,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def parse_claim(data: bytes) -> ClaimedPart:
    """Read back one staged claim."""
    loaded = cast("dict[str, Any]", json.loads(data.decode("utf-8")))
    return ClaimedPart(
        first_frame=int(loaded["first_frame"]),
        transitions=list(loaded["transitions"]),
        actions=[int(one) for one in loaded["actions"]],
        partner_actions=[int(one) for one in loaded["partner_actions"]],
        final=bool(loaded["final"]),
        boundary=loaded.get("boundary"),
    )


@dataclass(frozen=True)
class CaptureProgress:
    """What one run has reported so far, and whether the client closed it.

    ``high_water`` is the highest frame reported in an unbroken run from frame one.
    A part that arrives out of order is refused rather than stored, so the parts are
    always a contiguous prefix of the episode and the seal never has to guess what
    is missing.
    """

    run: RunIdentity
    parts: tuple[ArtifactRef, ...]
    high_water: int
    closed: bool
    sealed: bool
    updated_at: str
    revision: int


def _state(progress: CaptureProgress) -> dict[str, Any]:
    """Draft the aggregate state one progress record commits."""
    run = progress.run
    return {
        "episode_id": run.episode_id,
        "interaction_id": run.interaction_id,
        "channel_key": run.channel_key,
        "visit_id": run.visit_id,
        "seat_key": run.seat_key,
        "activity_key": run.activity_key,
        "generation": run.generation,
        "high_water": progress.high_water,
        "closed": progress.closed,
        "sealed": progress.sealed,
        "updated_at": progress.updated_at,
        "parts": [
            ref.model_dump(mode="json", exclude_none=True) for ref in progress.parts
        ],
    }


def read_progress(store: Store, episode_id: str) -> CaptureProgress | None:
    """Return what one run has reported, or None when it has reported nothing."""
    aggregate_id = progress_aggregate_id(episode_id)
    state = store.load_aggregate(aggregate_id)
    if not isinstance(state, dict):
        return None
    held = cast("dict[str, Any]", state)
    revision = store.revision_of(aggregate_id)
    return CaptureProgress(
        run=RunIdentity(
            episode_id=str(held["episode_id"]),
            interaction_id=str(held["interaction_id"]),
            channel_key=str(held["channel_key"]),
            visit_id=str(held["visit_id"]),
            seat_key=str(held["seat_key"]),
            activity_key=held.get("activity_key"),
            generation=int(held["generation"]),
        ),
        parts=tuple(
            ArtifactRef.model_validate(one)
            for one in cast("list[Any]", held.get("parts", []))
        ),
        high_water=int(held["high_water"]),
        closed=bool(held["closed"]),
        sealed=bool(held.get("sealed", False)),
        updated_at=str(held["updated_at"]),
        revision=revision if revision is not None else 0,
    )


class PartOutOfOrder(ValueError):
    """A reported part does not continue the run from where it had reached.

    The parts must be a contiguous prefix, so the seal never has to guess what is
    missing. A repeat of the part already held is not this: it is the client
    retrying after a lost acknowledgement, and it is accepted with no effect.
    """


async def record_part(
    part: ClaimedPart,
    *,
    run: RunIdentity,
    context: CommandContext,
    store: Store,
    artifacts: ArtifactStore,
    new_artifact_id: Callable[[], str],
    new_upload_id: Callable[[], str],
    now: Callable[[], str],
) -> CommandReceipt:
    """Stage one reported part and record it against the run.

    A part already held is accepted and stages nothing: a client that did not see
    its acknowledgement sends the same part again, and a second artifact of identical
    bytes would move nothing. It does refresh how recently the run was heard from,
    which is what stops a sweep reaping a participant who is alive and retrying.
    Raises ``PartOutOfOrder`` when the part does not continue the run.

    The artifact is staged **before** the aggregate names it, so a failure between
    the two leaves an artifact nobody points at rather than a record pointing at
    nothing. The first is waste; the second is a run that cannot be sealed.
    """
    held = read_progress(store, run.episode_id)
    reached = 0 if held is None else held.high_water
    if part.first_frame <= reached:
        # Already held, in whole or in part. A client repeating its last part is
        # the ordinary case and must cost nothing but a heartbeat.
        if part.last_frame <= reached and held is not None:
            return await _touch(held, context=context, store=store, now=now)
        raise PartOutOfOrder(
            f"the part starts at frame {part.first_frame} and the run has reached "
            f"{reached}; a part may not overlap what was already reported"
        )
    if part.first_frame != reached + 1:
        raise PartOutOfOrder(
            f"the part starts at frame {part.first_frame} and the run has reached "
            f"{reached}; the parts of a run must be contiguous"
        )
    if part.frames == 0 and not part.final:
        raise PartOutOfOrder("a part that does not close the run carries no frames")

    staged = await stage_artifact(
        artifacts,
        data=claim_bytes(part),
        media_type=CLAIM_MEDIA_TYPE,
        new_artifact_id=new_artifact_id,
        new_upload_id=new_upload_id,
        now=now,
        data_handling=_RESEARCH,
    )
    progress = CaptureProgress(
        run=run,
        parts=((held.parts if held is not None else ()) + (staged,)),
        # A run whose length divides evenly by the reporting cadence closes on a
        # part carrying the boundary and no frames at all. It is still staged,
        # because the boundary is what it came to say.
        high_water=part.last_frame if part.frames else reached,
        closed=part.final,
        sealed=False,
        updated_at=now(),
        revision=0,
    )
    return await commit_command(
        context,
        command=_PART_COMMAND,
        new_state=_state(progress),
        result=_typed_result(run, progress),
        store=store,
        expected_revision=held.revision if held is not None else None,
    )


async def _touch(
    held: CaptureProgress,
    *,
    context: CommandContext,
    store: Store,
    now: Callable[[], str],
) -> CommandReceipt:
    """Record that a run was heard from, without changing what it has reported."""
    refreshed = CaptureProgress(
        run=held.run,
        parts=held.parts,
        high_water=held.high_water,
        closed=held.closed,
        sealed=held.sealed,
        updated_at=now(),
        revision=held.revision,
    )
    return await commit_command(
        context,
        command=_PART_COMMAND,
        new_state=_state(refreshed),
        result=_typed_result(held.run, refreshed),
        store=store,
        expected_revision=held.revision,
    )


def _typed_result(run: RunIdentity, progress: CaptureProgress) -> Any:
    """The receipt body one reported part answers with."""
    from mug.kernel import TypedObject

    return TypedObject(
        schema=result_ref(_RESULT_SCHEMA_NAME),
        data={
            "outcome": "captured",
            "visit_id": run.visit_id,
            "status": "closed" if progress.closed else "open",
            "revision": 1,
        },
    )


@dataclass(frozen=True)
class AssembledRun:
    """Every part of one run, joined back into the whole the client reported."""

    transitions: list[dict[str, Any]]
    actions: list[int]
    partner_actions: list[int]
    boundary: dict[str, Any] | None
    closed: bool

    @property
    def frames(self) -> int:
        """How many frames the run reported."""
        return len(self.transitions)


async def assemble(
    progress: CaptureProgress, *, artifacts: ArtifactStore
) -> AssembledRun:
    """Read every staged part in frame order and join them into one run.

    The order is the order the parts were recorded, which the contiguity check makes
    the frame order too. What comes out is exactly the shape the whole-run report used
    to arrive in, so verification and capture are unchanged by any of this.
    """
    transitions: list[dict[str, Any]] = []
    actions: list[int] = []
    partner_actions: list[int] = []
    boundary: dict[str, Any] | None = None
    closed = False
    for ref in progress.parts:
        part = parse_claim(await artifacts.read_artifact(ref.artifact_id))
        transitions.extend(part.transitions)
        actions.extend(part.actions)
        partner_actions.extend(part.partner_actions)
        if part.final:
            boundary = part.boundary
            closed = True
    return AssembledRun(
        transitions=transitions,
        actions=actions,
        partner_actions=partner_actions,
        boundary=boundary,
        closed=closed,
    )


def unsealed_runs(store: Store, *, before: str) -> list[CaptureProgress]:
    """Return every run that has reported parts and has not been sealed.

    ``before`` is an instant in the canonical wire form: a run last touched at or
    after it is left alone, because the participant may still be playing or may be
    reconnecting. This is what a sweep reads, and it is why the run's identity lives
    on the aggregate -- the sweeping process has no session and no memory.
    """
    found: list[CaptureProgress] = []
    for aggregate_id, state in store.scan_aggregates():
        if not isinstance(state, dict):
            continue
        held = cast("dict[str, Any]", state)
        if held.get("sealed") is not False or "high_water" not in held:
            continue
        if str(held.get("updated_at", "")) >= before:
            continue
        progress = read_progress(store, str(held["episode_id"]))
        if progress is not None and progress_aggregate_id(
            progress.run.episode_id
        ) == aggregate_id:
            found.append(progress)
    return found


async def mark_sealed(
    progress: CaptureProgress,
    *,
    context: CommandContext,
    store: Store,
    now: Callable[[], str],
) -> CommandReceipt:
    """Record that a run has been sealed, so no sweep seals it twice.

    The compare-and-set on the revision is what makes that true when two processes
    sweep at once: the second reads a revision that has moved and is refused, rather
    than committing a second capture of the same run.
    """
    sealed = CaptureProgress(
        run=progress.run,
        parts=progress.parts,
        high_water=progress.high_water,
        closed=progress.closed,
        sealed=True,
        updated_at=now(),
        revision=progress.revision,
    )
    return await commit_command(
        context,
        command=_PART_COMMAND,
        new_state=_state(sealed),
        result=_typed_result(progress.run, sealed),
        store=store,
        expected_revision=progress.revision,
    )


def parts_of(frames: Sequence[Any], *, size: int = FRAMES_PER_PART) -> list[range]:
    """Return the frame ranges one run is reported in, for a client or a test."""
    return [
        range(at, min(at + size, len(frames)))
        for at in range(0, len(frames), size)
    ]


__all__ = [
    "CLAIM_MEDIA_TYPE",
    "FRAMES_PER_PART",
    "AssembledRun",
    "CaptureProgress",
    "ClaimedPart",
    "PartOutOfOrder",
    "RunIdentity",
    "assemble",
    "claim_bytes",
    "mark_sealed",
    "parse_claim",
    "parts_of",
    "progress_aggregate_id",
    "read_progress",
    "record_part",
    "unsealed_runs",
]
