"""The mesh-formation service matches, probes, casts, and fences a peer mesh.

These tests drive ``mug.interactions.service.MeshFormationService`` with a scripted
latency probe, a deterministic identifier minter, and a fixed clock, so the whole
formation runs with no socket and no wall clock. They cover the path the runtime
owns: a FIFO match forms a group of the declared size; the all-pairs latency probe
gates formation and, on a pair over the bound, poisons that pair and re-pools the
members; a formed mesh yields the frozen ``P2PMeshMembership`` with its content
digest and one fenced ``ConnectionLease`` per actor; and a re-acquired lease takes
the next fencing generation, so the prior lease is no longer current.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from mug.interactions.service import MeshFormationService
from mug.interactions.types import FifoMatch, LatencyMatch
from mug.kernel import Digest, Duration, LeaseRef, compute_digest
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
    """Build a pinned study version reference for the service."""
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


def _service(
    *, size: int, strategy: object, probe: object = None
) -> MeshFormationService:
    """Build a formation service with a deterministic minter and fixed clock."""
    minter = _Minter()
    return MeshFormationService(
        new_id=minter,
        now=lambda: _NOW,
        study_version=_study_version(minter),
        group_key="overcooked",
        channel_key="p2p-game",
        size=size,
        strategy=strategy,  # type: ignore[arg-type]
        probe=probe,  # type: ignore[arg-type]
    )


def _within(bound: int) -> object:
    """Return a probe that reports every peer pair within the bound."""

    def probe(actors: Sequence[str]) -> Mapping[tuple[str, str], int]:
        return {
            (a, b): bound - 1
            for i, a in enumerate(actors)
            for b in actors[i + 1 :]
        }

    return probe


# -- FIFO matching -------------------------------------------------------------


def test_a_fifo_match_forms_a_group_of_the_declared_size() -> None:
    """Two waiting tickets form a group, cast, mesh, and one lease per actor."""
    service = _service(size=2, strategy=FifoMatch(kind="fifo"))
    service.submit(enrollment_id=_enrollment(1), visit_id=_visit(1))
    assert service.poll().status == "insufficient"
    service.submit(enrollment_id=_enrollment(2), visit_id=_visit(2))

    result = service.poll()

    assert result.status == "formed"
    assert result.group is not None and result.group.status == "formed"
    assert result.interaction is not None and result.interaction.status == "active"
    assert result.membership is not None
    assert result.membership.peer_actor_ids == sorted(result.cast.values())
    assert len(result.leases) == 2
    assert {lease.actor_id for lease in result.leases} == set(result.cast.values())


def test_a_three_peer_fifo_match_forms_a_full_mesh() -> None:
    """Three waiting tickets form one three-peer full mesh."""
    service = _service(size=3, strategy=FifoMatch(kind="fifo"))
    for index in range(1, 4):
        service.submit(enrollment_id=_enrollment(index), visit_id=_visit(index))

    result = service.poll()

    assert result.status == "formed"
    assert result.membership is not None
    assert len(result.membership.peer_actor_ids) == 3
    assert result.membership.topology == "full-mesh"


def test_the_mesh_digest_is_the_membership_content_digest() -> None:
    """The service exposes the mesh digest the rollback engine binds transitions to."""
    service = _service(size=2, strategy=FifoMatch(kind="fifo"))
    service.submit(enrollment_id=_enrollment(1), visit_id=_visit(1))
    service.submit(enrollment_id=_enrollment(2), visit_id=_visit(2))

    result = service.poll()

    assert result.membership is not None
    expected = compute_digest(result.membership.model_dump(mode="json"))
    assert result.mesh_membership_digest == expected


# -- ticket lifecycle ----------------------------------------------------------


def test_a_ticket_moves_from_waiting_to_matched() -> None:
    """A submitted ticket waits, then a formed group marks it matched with a group."""
    service = _service(size=2, strategy=FifoMatch(kind="fifo"))
    first = service.submit(enrollment_id=_enrollment(1), visit_id=_visit(1))
    assert first.status == "waiting" and first.group_id is None
    service.submit(enrollment_id=_enrollment(2), visit_id=_visit(2))

    result = service.poll()

    assert all(ticket.status == "matched" for ticket in result.tickets)
    assert all(ticket.group_id is not None for ticket in result.tickets)
    assert service.waiting() == ()


def test_a_waiting_ticket_can_be_released() -> None:
    """A server-side release marks a waiting ticket released and dequeues it."""
    service = _service(size=2, strategy=FifoMatch(kind="fifo"))
    service.submit(enrollment_id=_enrollment(1), visit_id=_visit(1))

    released = service.release(_enrollment(1))

    assert released is not None and released.status == "released"
    assert service.waiting() == ()
    assert service.poll().status == "insufficient"


# -- the all-pairs latency probe -----------------------------------------------


def test_a_latency_mesh_forms_with_all_pairs_probe_evidence() -> None:
    """A probe within the bound forms the mesh and yields all-pairs evidence."""
    bound = 100_000
    strategy = LatencyMatch(kind="latency", max_p2p_rtt=Duration(microseconds=bound))
    service = _service(size=2, strategy=strategy, probe=_within(bound))
    service.submit(enrollment_id=_enrollment(1), visit_id=_visit(1))
    service.submit(enrollment_id=_enrollment(2), visit_id=_visit(2))

    result = service.poll()

    assert result.status == "formed"
    assert result.probe is not None
    assert len(result.probe.pairwise_rtts) == 1
    assert result.probe.peer_actor_ids == sorted(result.cast.values())


def test_a_probe_over_the_bound_rejects_and_repools_the_members() -> None:
    """A pair over the bound poisons the pair and re-pools; a fresh partner forms.

    The first poll probes the two earliest waiters, finds the pair over the bound,
    poisons it, and returns both to the queue. The second poll skips the poisoned
    pair and matches the first waiter with the third, which the probe passes.
    """
    bound = 100_000
    strategy = LatencyMatch(kind="latency", max_p2p_rtt=Duration(microseconds=bound))
    calls: list[Sequence[str]] = []

    def probe(actors: Sequence[str]) -> Mapping[tuple[str, str], int]:
        calls.append(actors)
        over = len(calls) == 1
        value = bound + 1 if over else bound - 1
        return {
            (a, b): value
            for i, a in enumerate(actors)
            for b in actors[i + 1 :]
        }

    service = _service(size=2, strategy=strategy, probe=probe)
    service.submit(enrollment_id=_enrollment(1), visit_id=_visit(1))
    service.submit(enrollment_id=_enrollment(2), visit_id=_visit(2))
    service.submit(enrollment_id=_enrollment(3), visit_id=_visit(3))

    rejected = service.poll()
    assert rejected.status == "probe_rejected"
    assert len(rejected.over_bound_pairs) == 1
    # The two probed members are back in the queue; the third still waits too.
    assert {ticket.status for ticket in rejected.tickets} == {"waiting"}
    assert {ticket.enrollment_id for ticket in service.waiting()} == {
        _enrollment(1),
        _enrollment(2),
        _enrollment(3),
    }

    formed = service.poll()
    assert formed.status == "formed"
    # Enrollment 1 could not rematch enrollment 2, so it paired with enrollment 3.
    matched = {ticket.enrollment_id for ticket in formed.tickets}
    assert matched == {_enrollment(1), _enrollment(3)}


# -- lease fencing -------------------------------------------------------------


def test_a_reacquired_lease_fences_the_prior_generation() -> None:
    """A re-issued lease takes the next generation; the prior lease is not current."""
    service = _service(size=2, strategy=FifoMatch(kind="fifo"))
    service.submit(enrollment_id=_enrollment(1), visit_id=_visit(1))
    service.submit(enrollment_id=_enrollment(2), visit_id=_visit(2))
    result = service.poll()
    assert result.interaction is not None
    first = result.leases[0]
    assert service.is_current(first)

    second = service.reacquire_lease(result.interaction.interaction_id, first)

    assert second.lease.generation == first.lease.generation + 1
    assert second.lease.lease_id == first.lease.lease_id
    assert service.is_current(second)
    assert not service.is_current(first)


def test_current_lease_checks_every_authoritative_binding() -> None:
    """An actor, interaction, epoch, expiry, or generation substitution is stale."""
    service = _service(size=2, strategy=FifoMatch(kind="fifo"))
    service.submit(enrollment_id=_enrollment(1), visit_id=_visit(1))
    service.submit(enrollment_id=_enrollment(2), visit_id=_visit(2))
    lease = service.poll().leases[0]

    wrong_actor = lease.model_copy(
        update={"actor_id": "actor_019b6000-0000-7000-8000-0000000000ff"}
    )
    wrong_interaction = lease.model_copy(
        update={
            "interaction_id": "interaction_019b6000-0000-7000-8000-0000000000ff"
        }
    )
    wrong_epoch = lease.model_copy(
        update={
            "lease": LeaseRef(
                lease_id=lease.lease.lease_id,
                namespace_epoch_id=(
                    "leaseepoch_019b6000-0000-7000-8000-0000000000ff"
                ),
                generation=lease.lease.generation,
            )
        }
    )
    expired = lease.model_copy(
        update={"expires_at": "2026-07-21T23:59:59.000000Z"}
    )

    assert not service.is_current(wrong_actor)
    assert not service.is_current(wrong_interaction)
    assert not service.is_current(wrong_epoch)
    assert not service.is_current(expired)
    for forged in (wrong_actor, wrong_interaction, wrong_epoch):
        try:
            service.reacquire_lease(lease.interaction_id, forged)
        except ValueError:
            continue
        raise AssertionError("a forged connection lease must not be reacquired")


# -- constructor guards --------------------------------------------------------


def test_a_single_seat_mesh_is_refused() -> None:
    """A mesh needs at least two seats."""
    try:
        _service(size=1, strategy=FifoMatch(kind="fifo"))
    except ValueError:
        return
    raise AssertionError("a single-seat mesh must raise")


def test_a_latency_bound_without_a_probe_is_refused() -> None:
    """A peer-to-peer latency bound must be wired to a probe."""
    strategy = LatencyMatch(
        kind="latency", max_p2p_rtt=Duration(microseconds=100_000)
    )
    try:
        _service(size=2, strategy=strategy)
    except ValueError:
        return
    raise AssertionError("a latency bound without a probe must raise")
