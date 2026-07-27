"""Issue and fence the connection leases of one interaction (API-06).

A ``ConnectionLease`` is what makes a connection authoritative: it names the
interaction, the actor, and a fencing generation. When the same actor reconnects,
the lease is re-issued at the next generation, and every earlier generation stops
being current. A message from a fenced connection is therefore refused instead of
being taken as the actor's word.

The book is the one implementation of that rule. A peer mesh and a server-ordered
room both form groups, both hand out leases, and both have to fence a stale
connection the same way; two copies of this would be two chances to fence
differently. It holds no clock and mints no identifiers -- the caller injects both --
so it stays a pure bookkeeping object below every transport.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

from mug.interactions.types import ConnectionLease
from mug.kernel import Duration, LeaseRef, UtcInstant

_INSTANT_FMT = "%Y-%m-%dT%H:%M:%S.%fZ"


def plus(instant: UtcInstant, microseconds: int) -> UtcInstant:
    """Return the instant advanced by a whole-microsecond duration."""
    moved = datetime.strptime(instant, _INSTANT_FMT) + timedelta(
        microseconds=microseconds
    )
    return moved.strftime(_INSTANT_FMT)


class LeaseBook:
    """Hold the current fencing generation of every lease one formation issued.

    ``issue`` gives an actor its first lease in an interaction. ``reacquire`` moves
    a lease to the next generation, which fences the connection that held the
    previous one. ``is_current`` answers the question every write asks: is this
    lease still the authoritative one for its actor, and has it not expired?
    """

    def __init__(
        self,
        *,
        new_id: Callable[[str], str],
        now: Callable[[], UtcInstant],
        ttl: Duration | None = None,
    ) -> None:
        self._new_id = new_id
        self._now = now
        self._ttl = ttl or Duration(microseconds=3_600_000_000)
        self._generation: dict[str, int] = {}
        self._epoch: dict[str, str] = {}
        self._binding: dict[str, tuple[str, str]] = {}

    def issue(self, interaction_id: str, actor_id: str) -> ConnectionLease:
        """Issue the first fenced connection lease for one actor.

        Every lease of one interaction shares a namespace epoch, so a lease that
        names the right actor but the wrong epoch does not pass the binding check.
        """
        epoch = self._epoch.setdefault(interaction_id, self._new_id("leaseepoch"))
        lease_id = self._new_id("lease")
        self._generation[lease_id] = 1
        self._binding[lease_id] = (interaction_id, actor_id)
        return ConnectionLease(
            lease=LeaseRef(lease_id=lease_id, namespace_epoch_id=epoch, generation=1),
            interaction_id=interaction_id,
            actor_id=actor_id,
            expires_at=plus(self._now(), self._ttl.microseconds),
        )

    def reacquire(
        self, interaction_id: str, lease: ConnectionLease
    ) -> ConnectionLease:
        """Re-issue a lease at the next fencing generation, fencing the prior one.

        Only the complete, current, correctly bound lease may be re-acquired: a
        connection that presents a generation the book has already moved past is
        exactly the stale connection this fences.
        """
        lease_id = lease.lease.lease_id
        current = self._generation.get(lease_id)
        if (
            current is None
            or interaction_id != lease.interaction_id
            or not self._binding_matches(lease)
            or current != lease.lease.generation
        ):
            raise ValueError(
                "only the current bound connection lease can be reacquired"
            )
        generation = current + 1
        self._generation[lease_id] = generation
        return ConnectionLease(
            lease=LeaseRef(
                lease_id=lease_id,
                namespace_epoch_id=lease.lease.namespace_epoch_id,
                generation=generation,
            ),
            interaction_id=interaction_id,
            actor_id=lease.actor_id,
            expires_at=plus(self._now(), self._ttl.microseconds),
        )

    def is_current(self, lease: ConnectionLease) -> bool:
        """Return whether the complete bound lease is current and unexpired."""
        current = self._generation.get(lease.lease.lease_id)
        return (
            self._binding_matches(lease)
            and current == lease.lease.generation
            and lease.expires_at > self._now()
        )

    def _binding_matches(self, lease: ConnectionLease) -> bool:
        """Check the authoritative interaction, actor, and namespace binding."""
        bound = self._binding.get(lease.lease.lease_id)
        epoch = self._epoch.get(lease.interaction_id)
        return (
            bound == (lease.interaction_id, lease.actor_id)
            and epoch == lease.lease.namespace_epoch_id
        )


__all__ = ["LeaseBook", "plus"]
