"""What happened in an episode: the values behind the digests the ledger records.

A canonical event binds a ``payload_digest`` and carries no payload, and a
``GameTransition`` binds an action digest and a state digest and carries neither the
action nor the state. That is right for the ledger -- it keeps research values out of
an append-only stream that is copied into every export row -- but on its own it
leaves the study with no data: nobody can say what the participant did, what it
earned, or why the episode ended.

This module is the other half. One ``TrajectoryFrame`` per stepped frame keeps the
executed actions, the resulting observations, the per-seat rewards, the termination
and truncation flags, and the environment's own ``info`` metrics. The frames become
one newline-delimited artifact in the content-addressed store, and the ledger keeps
the digests, so the two are checkable against each other: digesting a frame's actions
must give the transition's ``action_digest``, and digesting its observations must give
the ``state_digest``. Evidence that cannot be checked against the ledger is not
evidence, so ``verify_trajectory`` is what makes the artifact trustworthy.

The frames are also what a deterministic replay re-executes. ``actions_for`` reads one
seat's action per frame out of a recorded trajectory, which is what the replay player
steps; before this existed the player could only be driven by a caller that already
held the actions, so no recorded run could be replayed.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from mug.game.types import GameTransition
from mug.kernel import compute_digest
from mug.storage import jsonl_bytes, read_jsonl

# The media type of a recorded trajectory: one JSON object per stepped frame.
TRAJECTORY_MEDIA_TYPE = "application/x-ndjson"


@dataclass(frozen=True)
class TrajectoryFrame:
    """One stepped frame: what every seat did, and what the environment answered.

    ``actions`` and ``observations`` are keyed by the environment's agent id, exactly
    as the transition's digests commit to them. ``info`` is the environment's own
    metrics for the frame; an environment that reports none leaves it empty.
    """

    frame_number: int
    actions: dict[str, int]
    observations: dict[str, Any]
    rewards: dict[str, float]
    terminated: bool
    truncated: bool
    info: dict[str, Any]

    def as_row(self) -> dict[str, Any]:
        """Render the frame as the artifact row that records it."""
        return {
            "frame_number": self.frame_number,
            "actions": self.actions,
            "observations": self.observations,
            "rewards": self.rewards,
            "terminated": self.terminated,
            "truncated": self.truncated,
            "info": self.info,
        }

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> TrajectoryFrame:
        """Read one recorded row back into a frame."""
        return cls(
            frame_number=int(row["frame_number"]),
            actions=dict(row["actions"]),
            observations=dict(row["observations"]),
            rewards=dict(row["rewards"]),
            terminated=bool(row["terminated"]),
            truncated=bool(row["truncated"]),
            info=dict(row.get("info", {})),
        )


def trajectory_bytes(frames: Sequence[TrajectoryFrame]) -> bytes:
    """Serialize a recorded trajectory as the artifact's newline-delimited JSON.

    The rows are in frame order and their keys are sorted, so one recorded episode
    always gives one artifact digest.
    """
    return jsonl_bytes([frame.as_row() for frame in frames])


def read_trajectory(data: bytes) -> list[TrajectoryFrame]:
    """Read a recorded trajectory artifact back into its frames, in order."""
    return [TrajectoryFrame.from_row(row) for row in read_jsonl(data)]


def actions_for(frames: Sequence[TrajectoryFrame], seat_key: str) -> list[int]:
    """Return one seat's executed action per frame, in order.

    This is what a deterministic replay steps. A frame that recorded no action for
    the seat is a gap in the record, and raises rather than replay a made-up action.
    """
    actions: list[int] = []
    for frame in frames:
        if seat_key not in frame.actions:
            raise KeyError(f"frame {frame.frame_number} recorded no action for a seat")
        actions.append(int(frame.actions[seat_key]))
    return actions


def verify_trajectory(
    transitions: Sequence[GameTransition], frames: Sequence[TrajectoryFrame]
) -> list[int]:
    """Return the frame numbers whose recorded values disagree with the ledger.

    A transition commits to the whole action set and the whole observation set by
    digest. Re-digesting the recorded values must reproduce both, or the artifact is
    not the run the ledger recorded. An empty list means every frame agrees.

    A trajectory of a different length disagrees everywhere it cannot be compared,
    so the missing frame numbers are reported too.
    """
    by_number = {frame.frame_number: frame for frame in frames}
    mismatched: list[int] = []
    for transition in transitions:
        frame = by_number.get(transition.frame_number)
        if frame is None:
            mismatched.append(transition.frame_number)
            continue
        actions_agree = compute_digest(frame.actions) == transition.action_digest
        state_agrees = compute_digest(frame.observations) == transition.state_digest
        if not (actions_agree and state_agrees):
            mismatched.append(transition.frame_number)
    return mismatched


__all__ = [
    "TRAJECTORY_MEDIA_TYPE",
    "TrajectoryFrame",
    "actions_for",
    "read_trajectory",
    "trajectory_bytes",
    "verify_trajectory",
]
