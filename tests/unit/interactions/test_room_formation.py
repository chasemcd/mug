"""Match connections into a server-ordered room: group, cast, channels, lease.

``MeshFormationService`` forms the other kind of group -- peers that connect to each
other and prove their pairwise latency. A conversation is not that: its members
never connect to each other, so a ``P2PMeshMembership`` would be a record of peer
connections that do not exist. ``RoomFormation`` is the rest of it.

These tests hold what a room needs of a formation: it waits until the declared size
is there, it casts the members into one interaction over every declared channel, and
it hands out one fenced lease each -- and re-acquiring a lease fences whatever the
previous connection still holds.
"""

from __future__ import annotations

import itertools

import pytest

from mug.interactions.rooms import RoomFormation
from mug.kernel import Digest
from mug.kernel.refs import StudyVersionRef

_UUID = "019b6000-0000-7000-8000-{:012x}"
_NOW = "2026-07-27T00:00:00.000000Z"

_STUDY = StudyVersionRef(
    study_id="study_" + _UUID.format(0xC0),
    study_version_id="studyver_" + _UUID.format(0xC1),
    version_number=1,
    manifest_digest=Digest(algorithm="sha-256", hex="0" * 64),
)


class _Ids:
    """Mint deterministic runtime-occurrence ids from one shared counter."""

    def __init__(self) -> None:
        self._counter = itertools.count(1)

    def __call__(self, kind: str) -> str:
        return f"{kind}_" + _UUID.format(next(self._counter))


def _formation(size: int = 2, channels: tuple[str, ...] = ("chat",)) -> RoomFormation:
    return RoomFormation(
        new_id=_Ids(),
        now=lambda: _NOW,
        study_version=_STUDY,
        group_key="talk",
        channels=channels,
        size=size,
    )


def _submit(formation: RoomFormation, index: int) -> str:
    enrollment_id = "enrollment_" + _UUID.format(0x200 + index)
    formation.submit(
        enrollment_id=enrollment_id, visit_id="visit_" + _UUID.format(0x300 + index)
    )
    return enrollment_id


def test_a_room_waits_until_its_declared_size_is_there() -> None:
    """One person is not a pair, and a half-formed room casts nobody."""
    formation = _formation(size=2)
    _submit(formation, 1)

    assert formation.poll().status == "insufficient"

    _submit(formation, 2)
    assert formation.poll().status == "formed"


def test_a_room_of_one_forms_at_once() -> None:
    """One participant and a model seat is a room too: one order and one lease."""
    formation = _formation(size=1)
    _submit(formation, 1)

    result = formation.poll()

    assert result.status == "formed"
    assert list(result.cast) == ["seat-1"]
    assert len(result.leases) == 1


def test_a_formed_room_casts_every_member_into_the_one_interaction() -> None:
    """The group, the cast, and the visits are one interaction, not two."""
    formation = _formation(size=2)
    _submit(formation, 1)
    _submit(formation, 2)

    result = formation.poll()

    assert result.interaction is not None and result.group is not None
    assert sorted(result.cast) == ["seat-1", "seat-2"]
    assert len(result.interaction.visit_ids) == 2
    assert result.interaction.group_id == result.group.group_id
    assert result.interaction.status == "active"
    assert len(set(result.cast.values())) == 2


def test_the_interaction_declares_every_channel_the_room_holds() -> None:
    """A public channel and a private one belong to the same conversation."""
    formation = _formation(size=1, channels=("chat", "coach"))
    _submit(formation, 1)

    result = formation.poll()

    assert result.interaction is not None
    assert result.interaction.channels == ["chat", "coach"]


def test_every_member_gets_its_own_current_lease() -> None:
    """A lease is per actor, and every one of them starts out current."""
    formation = _formation(size=2)
    _submit(formation, 1)
    _submit(formation, 2)

    result = formation.poll()

    assert len(result.leases) == 2
    assert len({lease.lease.lease_id for lease in result.leases}) == 2
    assert all(formation.is_current(lease) for lease in result.leases)


def test_reacquiring_a_lease_fences_the_connection_that_held_it() -> None:
    """A refresh takes the lease on; the connection it replaced stops being current."""
    formation = _formation(size=1)
    _submit(formation, 1)
    result = formation.poll()
    stale = result.leases[0]

    fresh = formation.reacquire_lease(stale.interaction_id, stale)

    assert fresh.lease.generation == stale.lease.generation + 1
    assert formation.is_current(fresh)
    assert not formation.is_current(stale)


def test_a_lease_that_is_not_the_current_one_can_not_be_reacquired() -> None:
    """Only the connection that holds the room may hand it on."""
    formation = _formation(size=1)
    _submit(formation, 1)
    stale = formation.poll().leases[0]
    formation.reacquire_lease(stale.interaction_id, stale)

    with pytest.raises(ValueError, match="current bound connection lease"):
        formation.reacquire_lease(stale.interaction_id, stale)


def test_a_released_ticket_is_not_matched_into_a_room() -> None:
    """A waitroom timeout takes a connection out of the queue, not into a group."""
    formation = _formation(size=2)
    first = _submit(formation, 1)
    _submit(formation, 2)
    formation.release(first)

    assert formation.poll().status == "insufficient"
    assert [ticket.enrollment_id for ticket in formation.waiting()] != [first]


def test_a_room_with_no_channel_is_refused() -> None:
    """A conversation with nowhere to say anything is not a conversation."""
    with pytest.raises(ValueError, match="at least one channel"):
        RoomFormation(
            new_id=_Ids(),
            now=lambda: _NOW,
            study_version=_STUDY,
            group_key="talk",
            channels=(),
        )
