"""Form a peer mesh from waiting tickets: match, probe, cast, and lease (API-06).

The frozen API-06 records model who is matched, how a group forms, how a mesh
proves its latency, and how a lease fences a connection -- but they add no runtime.
This module is that runtime for the peer-to-peer path. It takes the tickets that
enrollments enqueue, matches them into a group, probes the all-pairs latency of the
candidate mesh, and -- when the probe passes -- casts the members into an
interaction, freezes the peer mesh, and issues one fenced connection lease per
actor.

The service is deterministic and side-effect free at its boundary. It never reads a
wall clock, opens a socket, or mints an identifier itself: the caller injects an
identifier minter (the gateway's ``new_id``), a clock, and a latency probe. So a
test drives the whole formation with a scripted probe and a fixed clock, and the
production wiring passes the real gateway and a WebRTC probe. The service lives in
the interactions layer and imports no outer layer, so the gateway reaches it only
through the injected callable.

The formation gate is the all-pairs latency probe. Under a latency strategy that
bounds the peer-to-peer round trip, the service probes every peer pair; if a pair
is over the bound, it poisons that pair (so a later poll does not reselect it),
returns the candidate tickets to the waiting queue, and forms no group -- the
legacy failed-pair memory, made server-authoritative. A pair within the bound
yields the ``MeshLatencyProbe`` evidence the mesh forms against.

Estimated-round-trip pre-filtering (the cheaper first stage the legacy matchmaker
runs before the probe) and turn-based casting stay out of this slice; the probe is
the authoritative gate this runtime owns.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from mug.interactions.leases import LeaseBook
from mug.interactions.types import (
    ConnectionLease,
    Group,
    Interaction,
    LatencyMatch,
    MatchmakingTicket,
    MatchStrategy,
    MeshLatencyProbe,
    MeshPairwiseRtt,
    P2PMeshMembership,
)
from mug.kernel import (
    Digest,
    Duration,
    UtcInstant,
    VersionStamp,
    compute_digest,
    etag,
)
from mug.kernel.refs import StudyVersionRef

# The caller injects these three boundary capabilities, so the service holds no
# clock, socket, or entropy of its own.
IdMinter = Callable[[str], str]
Clock = Callable[[], UtcInstant]
# A probe measures the round trip of every peer pair. It takes the sorted actor
# ids and returns the microseconds for each sorted ``(a, b)`` pair.
ProbeFn = Callable[[Sequence[str]], Mapping[tuple[str, str], int]]

def _empty_cast() -> dict[str, str]:
    """Return the empty seat-to-actor cast for a non-formed result."""
    return {}


@dataclass
class _Entry:
    """The mutable waiting-queue state behind one immutable ticket record."""

    enrollment_id: str
    visit_id: str
    match: MatchStrategy
    enqueued_at: UtcInstant
    status: Literal["waiting", "probing", "matched", "released", "expired"] = "waiting"
    group_id: str | None = None


@dataclass(frozen=True)
class FormationResult:
    """The outcome of one formation poll.

    ``formed`` carries the group, the interaction, the frozen mesh and its content
    digest, the probe evidence, and one lease per actor. ``probe_rejected`` carries
    the re-pooled tickets and the peer pairs that failed the bound. ``insufficient``
    means no group of the declared size could be selected.
    """

    status: Literal["formed", "probe_rejected", "insufficient"]
    tickets: tuple[MatchmakingTicket, ...] = ()
    group: Group | None = None
    interaction: Interaction | None = None
    membership: P2PMeshMembership | None = None
    mesh_membership_digest: Digest | None = None
    membership_generation: int = 1
    probe: MeshLatencyProbe | None = None
    leases: tuple[ConnectionLease, ...] = ()
    cast: Mapping[str, str] = field(default_factory=_empty_cast)
    over_bound_pairs: tuple[tuple[str, str], ...] = ()


class MeshFormationService:
    """Form one peer mesh at a time from the waiting tickets of one group key.

    One service holds the queue for one ``group_key`` at one declared size. It
    enqueues tickets, forms a group when enough compatible members wait, probes the
    candidate mesh, and issues the fenced leases. A re-acquired lease takes the next
    fencing generation, so a stale connection is refused.
    """

    def __init__(
        self,
        *,
        new_id: IdMinter,
        now: Clock,
        study_version: StudyVersionRef,
        group_key: str,
        channel_key: str,
        size: int,
        strategy: MatchStrategy,
        probe: ProbeFn | None = None,
        lease_ttl: Duration | None = None,
    ) -> None:
        if size < 2:
            raise ValueError("a peer mesh needs at least two seats")
        bound = isinstance(strategy, LatencyMatch) and strategy.max_p2p_rtt is not None
        if bound and probe is None:
            raise ValueError("a peer-to-peer latency bound requires a probe")
        self._new_id = new_id
        self._now = now
        self._study_version = study_version
        self._group_key = group_key
        self._channel_key = channel_key
        self._size = size
        self._strategy = strategy
        self._probe = probe
        self._leases = LeaseBook(new_id=new_id, now=now, ttl=lease_ttl)

        self._queue: list[_Entry] = []
        self._failed_pairs: set[frozenset[str]] = set()

    # -- the waiting queue ------------------------------------------------------

    def submit(
        self,
        *,
        enrollment_id: str,
        visit_id: str,
        match: MatchStrategy | None = None,
    ) -> MatchmakingTicket:
        """Enqueue one enrollment's request to be matched and return its ticket."""
        entry = _Entry(
            enrollment_id=enrollment_id,
            visit_id=visit_id,
            match=match or self._strategy,
            enqueued_at=self._now(),
        )
        self._queue.append(entry)
        return self._ticket(entry)

    def release(self, enrollment_id: str) -> MatchmakingTicket | None:
        """Release a waiting ticket, as a server-side waitroom timeout would."""
        entry = self._waiting_entry(enrollment_id)
        if entry is None:
            return None
        entry.status = "released"
        return self._ticket(entry)

    def waiting(self) -> tuple[MatchmakingTicket, ...]:
        """Return the tickets still waiting to be matched, in arrival order."""
        return tuple(
            self._ticket(entry) for entry in self._queue if entry.status == "waiting"
        )

    # -- formation --------------------------------------------------------------

    def poll(self) -> FormationResult:
        """Try to form one group from the waiting tickets.

        It selects the earliest-arriving members whose pairs are not poisoned,
        probes the candidate mesh under a latency bound, and forms the interaction,
        the mesh, and the leases when the probe passes. It returns ``insufficient``
        when no clean group of the declared size is available.
        """
        chosen = self._select()
        if chosen is None:
            return FormationResult(status="insufficient")

        interaction_id = self._new_id("interaction")
        group_id = self._new_id("group")
        seats = {
            f"seat-{index + 1}": self._new_id("actor") for index in range(len(chosen))
        }
        cast = dict(sorted(seats.items()))
        actor_ids = tuple(sorted(cast.values()))

        probe_evidence = self._run_probe(chosen, actor_ids, interaction_id, group_id)
        if probe_evidence is not None and probe_evidence.rejected:
            return probe_evidence.result

        group = self._build_group(chosen, group_id)
        membership = self._build_membership(interaction_id, group_id, actor_ids)
        mesh_digest = compute_digest(membership.model_dump(mode="json"))
        interaction = self._build_interaction(interaction_id, chosen, cast, group_id)
        leases = tuple(self._issue_lease(interaction_id, actor) for actor in actor_ids)
        for entry in chosen:
            entry.status = "matched"
            entry.group_id = group_id

        return FormationResult(
            status="formed",
            tickets=tuple(self._ticket(entry) for entry in chosen),
            group=group,
            interaction=interaction,
            membership=membership,
            mesh_membership_digest=mesh_digest,
            membership_generation=membership.membership_generation,
            probe=probe_evidence.probe if probe_evidence is not None else None,
            leases=leases,
            cast=cast,
        )

    # -- lease fencing ----------------------------------------------------------

    def reacquire_lease(
        self, interaction_id: str, lease: ConnectionLease
    ) -> ConnectionLease:
        """Re-issue a lease at the next fencing generation, fencing the prior one."""
        return self._leases.reacquire(interaction_id, lease)

    def is_current(self, lease: ConnectionLease) -> bool:
        """Return whether the complete bound lease is current and unexpired."""
        return self._leases.is_current(lease)

    # -- selection and probing --------------------------------------------------

    def _select(self) -> list[_Entry] | None:
        """Pick the earliest waiting members with no poisoned pair among them."""
        chosen: list[_Entry] = []
        for entry in self._queue:
            if entry.status != "waiting":
                continue
            if any(
                frozenset((entry.enrollment_id, picked.enrollment_id))
                in self._failed_pairs
                for picked in chosen
            ):
                continue
            chosen.append(entry)
            if len(chosen) == self._size:
                return chosen
        return None

    def _run_probe(
        self,
        chosen: list[_Entry],
        actor_ids: tuple[str, ...],
        interaction_id: str,
        group_id: str,
    ) -> _ProbeOutcome | None:
        """Probe the candidate mesh, or return None when no bound applies.

        A pair over the bound poisons that enrollment pair and returns the members
        to the waiting queue; a mesh within the bound yields the probe evidence.
        """
        strategy = self._strategy
        if not isinstance(strategy, LatencyMatch) or strategy.max_p2p_rtt is None:
            return None
        assert self._probe is not None
        bound = strategy.max_p2p_rtt.microseconds
        measured = self._probe(actor_ids)
        entry_of_actor = dict(zip(actor_ids, chosen, strict=True))

        for entry in chosen:
            entry.status = "probing"
        pairs = list(itertools.combinations(actor_ids, 2))
        over = tuple(pair for pair in pairs if measured.get(pair, bound + 1) > bound)
        if over:
            for low, high in over:
                self._failed_pairs.add(
                    frozenset(
                        (
                            entry_of_actor[low].enrollment_id,
                            entry_of_actor[high].enrollment_id,
                        )
                    )
                )
            for entry in chosen:
                entry.status = "waiting"
            return _ProbeOutcome(
                rejected=True,
                probe=None,
                result=FormationResult(
                    status="probe_rejected",
                    tickets=tuple(self._ticket(entry) for entry in chosen),
                    over_bound_pairs=over,
                ),
            )
        return _ProbeOutcome(
            rejected=False,
            probe=self._build_probe(
                actor_ids, measured, strategy, interaction_id, group_id
            ),
            result=FormationResult(status="insufficient"),
        )

    # -- record builders --------------------------------------------------------

    def _build_group(self, chosen: list[_Entry], group_id: str) -> Group:
        """Build the formed group record for the matched members."""
        body = {
            "group_key": self._group_key,
            "size": self._size,
            "members": [entry.enrollment_id for entry in chosen],
        }
        return Group(
            group_id=group_id,
            study_version=self._study_version,
            group_key=self._group_key,
            size=self._size,
            members=[entry.enrollment_id for entry in chosen],
            status="formed",
            version=VersionStamp(revision=1, etag=etag(body)),
            formed_at=self._now(),
        )

    def _build_membership(
        self, interaction_id: str, group_id: str, actor_ids: tuple[str, ...]
    ) -> P2PMeshMembership:
        """Freeze the full-mesh peer set for the interaction's game channel."""
        body = {"peers": list(actor_ids), "generation": 1}
        return P2PMeshMembership(
            interaction_id=interaction_id,
            group_id=group_id,
            channel_key=self._channel_key,
            peer_actor_ids=list(actor_ids),
            topology="full-mesh",
            membership_generation=1,
            version=VersionStamp(revision=1, etag=etag(body)),
        )

    def _build_interaction(
        self,
        interaction_id: str,
        chosen: list[_Entry],
        cast: Mapping[str, str],
        group_id: str,
    ) -> Interaction:
        """Cast the members into an active interaction on the game channel."""
        visit_ids = list(dict.fromkeys(entry.visit_id for entry in chosen))
        body = {"cast": dict(cast), "visits": visit_ids, "group": group_id}
        return Interaction(
            interaction_id=interaction_id,
            study_version=self._study_version,
            visit_ids=visit_ids,
            cast=dict(cast),
            channels=[self._channel_key],
            status="active",
            version=VersionStamp(revision=1, etag=etag(body)),
            group_id=group_id,
        )

    def _build_probe(
        self,
        actor_ids: tuple[str, ...],
        measured: Mapping[tuple[str, str], int],
        strategy: LatencyMatch,
        interaction_id: str,
        group_id: str,
    ) -> MeshLatencyProbe:
        """Build the all-pairs probe evidence for a mesh within the bound."""
        assert strategy.max_p2p_rtt is not None
        pairwise = [
            MeshPairwiseRtt(
                peers=list(pair),
                rtt=Duration(microseconds=measured[pair]),
            )
            for pair in itertools.combinations(actor_ids, 2)
        ]
        body = {"peers": list(actor_ids), "interaction": interaction_id}
        return MeshLatencyProbe(
            interaction_id=interaction_id,
            group_id=group_id,
            channel_key=self._channel_key,
            peer_actor_ids=list(actor_ids),
            max_p2p_rtt=strategy.max_p2p_rtt,
            pairwise_rtts=pairwise,
            membership_generation=1,
            version=VersionStamp(revision=1, etag=etag(body)),
        )

    def _issue_lease(self, interaction_id: str, actor_id: str) -> ConnectionLease:
        """Issue the first fenced connection lease for one actor."""
        return self._leases.issue(interaction_id, actor_id)

    # -- helpers ----------------------------------------------------------------

    def _waiting_entry(self, enrollment_id: str) -> _Entry | None:
        """Return the waiting entry for an enrollment, if one is queued."""
        for entry in self._queue:
            if entry.enrollment_id == enrollment_id and entry.status == "waiting":
                return entry
        return None

    def _ticket(self, entry: _Entry) -> MatchmakingTicket:
        """Build the immutable ticket record for one queue entry."""
        return MatchmakingTicket(
            study_version=self._study_version,
            group_key=self._group_key,
            enrollment_id=entry.enrollment_id,
            match=entry.match,
            enqueued_at=entry.enqueued_at,
            status=entry.status,
            group_id=entry.group_id,
        )


@dataclass(frozen=True)
class _ProbeOutcome:
    """The internal outcome of a probe: the evidence, or a rejection result."""

    rejected: bool
    probe: MeshLatencyProbe | None
    result: FormationResult


__all__ = ["Clock", "FormationResult", "IdMinter", "MeshFormationService", "ProbeFn"]
