"""The formation pool forms many peer meshes at once, across group keys.

These tests drive ``mug.interactions.pool.MeshFormationPool`` with a deterministic
identifier minter and a fixed clock, with no socket and no wall clock. They prove
the coordinator forms every group that can form in one sweep, where the single
service formed only one:

- one waiting room with six waiting for a two-seat game yields three meshes in one
  ``poll_all`` sweep, with distinct interactions and non-overlapping members;
- two different games form side by side in the same sweep;
- a partial waiting room forms the groups it can and leaves the remainder waiting.
"""

from __future__ import annotations

from mug.interactions.pool import GroupConfig, MeshFormationPool
from mug.interactions.service import FormationResult
from mug.interactions.types import FifoMatch
from mug.kernel import Digest
from mug.kernel.refs import StudyVersionRef

_NOW = "2026-07-22T00:00:00.000000Z"
_DIGEST = Digest(algorithm="sha-256", hex="a" * 64)


class _Minter:
    """A deterministic identifier minter that yields valid UUIDv7-shaped ids."""

    def __init__(self) -> None:
        self._n = 0

    def __call__(self, prefix: str) -> str:
        self._n += 1
        return f"{prefix}_019b6000-0000-7000-8000-{self._n:012x}"


def _study_version(minter: _Minter) -> StudyVersionRef:
    """Build a pinned study version reference for the pool."""
    return StudyVersionRef(
        study_id=minter("study"),
        study_version_id=minter("studyver"),
        version_number=1,
        manifest_digest=_DIGEST,
    )


def _enrollment(index: int) -> str:
    """Return a valid enrollment id for one waiting participant."""
    return f"enrollment_019b6000-0000-7000-8000-0000000002{index:02x}"


def _visit(index: int) -> str:
    """Return a valid visit id for one waiting participant."""
    return f"visit_019b6000-0000-7000-8000-0000000003{index:02x}"


def _pool() -> MeshFormationPool:
    """Build a formation pool with a deterministic minter and fixed clock."""
    minter = _Minter()
    return MeshFormationPool(
        new_id=minter,
        now=lambda: _NOW,
        study_version=_study_version(minter),
    )


def _members(result: FormationResult) -> set[str]:
    """Return the set of enrolment ids in one formed group."""
    group = result.group
    assert group is not None
    return set(group.members)


def test_one_room_forms_many_meshes_in_one_sweep() -> None:
    """Six waiting for a two-seat game form three meshes in one poll-all sweep."""
    pool = _pool()
    pool.register(
        GroupConfig(
            group_key="overcooked",
            channel_key="p2p-game",
            size=2,
            strategy=FifoMatch(kind="fifo"),
        )
    )
    for i in range(6):
        pool.submit(
            group_key="overcooked", enrollment_id=_enrollment(i), visit_id=_visit(i)
        )

    formed = pool.poll_all()

    assert len(formed) == 3
    interactions = {result.interaction.interaction_id for result in formed}  # type: ignore[union-attr]
    assert len(interactions) == 3  # every mesh is a distinct interaction
    seen: set[str] = set()
    for result in formed:
        members = _members(result)
        assert len(members) == 2
        assert seen.isdisjoint(members)  # no participant is in two meshes
        seen |= members
    assert pool.waiting()["overcooked"] == ()


def test_two_games_form_side_by_side() -> None:
    """Two different games each form their meshes in the same sweep."""
    pool = _pool()
    pool.register(
        GroupConfig("overcooked", "p2p-overcooked", 2, FifoMatch(kind="fifo"))
    )
    pool.register(GroupConfig("racer", "p2p-racer", 3, FifoMatch(kind="fifo")))
    for i in range(4):
        pool.submit(
            group_key="overcooked", enrollment_id=_enrollment(i), visit_id=_visit(i)
        )
    for i in range(6, 12):
        pool.submit(
            group_key="racer", enrollment_id=_enrollment(i), visit_id=_visit(i)
        )

    formed = pool.poll_all()

    by_channel: dict[str, int] = {}
    for result in formed:
        interaction = result.interaction
        assert interaction is not None
        for channel in interaction.channels:
            by_channel[channel] = by_channel.get(channel, 0) + 1
    assert by_channel == {"p2p-overcooked": 2, "p2p-racer": 2}


def test_a_partial_room_leaves_the_remainder_waiting() -> None:
    """Five waiting for a two-seat game form two meshes and leave one waiting."""
    pool = _pool()
    pool.register(GroupConfig("overcooked", "p2p-game", 2, FifoMatch(kind="fifo")))
    for i in range(5):
        pool.submit(
            group_key="overcooked", enrollment_id=_enrollment(i), visit_id=_visit(i)
        )

    formed = pool.poll_all()

    assert len(formed) == 2
    remaining = pool.waiting()["overcooked"]
    assert len(remaining) == 1
    assert remaining[0].enrollment_id == _enrollment(4)


def test_a_duplicate_group_key_is_refused() -> None:
    """A group key may be registered only once."""
    pool = _pool()
    pool.register(GroupConfig("overcooked", "p2p-game", 2, FifoMatch(kind="fifo")))
    try:
        pool.register(GroupConfig("overcooked", "p2p-game", 2, FifoMatch(kind="fifo")))
    except ValueError:
        return
    raise AssertionError("a duplicate group key must raise")
