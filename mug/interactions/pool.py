"""Form many peer meshes at once across group keys (API-06).

``MeshFormationService`` forms one mesh at a time from the waiting tickets of one
group key. A real deployment runs many games at many sizes at once, and a single
sweep of the waiting rooms should form every group that can form -- several groups
of one game, and groups of other games -- not just the first. This module is that
coordinator: it holds one service per group key and drains them all in one sweep.

The pool routes each enrollment's ticket to the service for its group key, and its
``poll_all`` drains every service, forming groups until each waiting room can form no
more, and returns every group that formed. So six waiting for a two-seat game yield
three meshes in one sweep, and two different games form side by side. Each service
keeps its own poisoned-pair memory and its own lease fencing, so the concurrency
adds no shared mutable state beyond the injected identifier minter, which stays
globally unique across services.

The pool holds no clock, socket, or entropy of its own: it injects the same minter,
clock, and study version into every service, exactly as the single service takes
them. So a test drives many concurrent formations with one deterministic minter and
a fixed clock, with no socket and no wall clock.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from mug.interactions.service import (
    Clock,
    FormationResult,
    IdMinter,
    MeshFormationService,
    ProbeFn,
)
from mug.interactions.types import ConnectionLease, MatchmakingTicket, MatchStrategy
from mug.kernel import Duration
from mug.kernel.refs import StudyVersionRef


@dataclass(frozen=True)
class GroupConfig:
    """One game's waiting-room configuration the pool forms meshes for.

    ``group_key`` names the waiting room; ``channel_key`` the game channel the mesh
    forms on; ``size`` the number of seats; ``strategy`` the match rule; ``probe`` the
    latency probe a bounded strategy requires.
    """

    group_key: str
    channel_key: str
    size: int
    strategy: MatchStrategy
    probe: ProbeFn | None = None


class MeshFormationPool:
    """Hold one formation service per group key and form them all in one sweep.

    The pool registers a service per game, routes each ticket to its service, and
    drains every service on ``poll_all`` so one sweep forms every group that can
    form. The services are independent: each owns its queue, its poisoned pairs, and
    its lease fencing, so many meshes form concurrently without shared state.
    """

    def __init__(
        self,
        *,
        new_id: IdMinter,
        now: Clock,
        study_version: StudyVersionRef,
        lease_ttl: Duration | None = None,
    ) -> None:
        self._new_id = new_id
        self._now = now
        self._study_version = study_version
        self._lease_ttl = lease_ttl
        self._services: dict[str, MeshFormationService] = {}

    def register(self, config: GroupConfig) -> None:
        """Add a waiting room for one game; a duplicate group key is refused."""
        if config.group_key in self._services:
            raise ValueError(f"the group key {config.group_key!r} is already present")
        self._services[config.group_key] = MeshFormationService(
            new_id=self._new_id,
            now=self._now,
            study_version=self._study_version,
            group_key=config.group_key,
            channel_key=config.channel_key,
            size=config.size,
            strategy=config.strategy,
            probe=config.probe,
            lease_ttl=self._lease_ttl,
        )

    def service(self, group_key: str) -> MeshFormationService:
        """Return the formation service for one group key, for lease operations."""
        return self._services[group_key]

    def submit(
        self,
        *,
        group_key: str,
        enrollment_id: str,
        visit_id: str,
        match: MatchStrategy | None = None,
    ) -> MatchmakingTicket:
        """Enqueue one enrollment into its game's waiting room and return its ticket."""
        return self._services[group_key].submit(
            enrollment_id=enrollment_id, visit_id=visit_id, match=match
        )

    def poll(self, group_key: str) -> FormationResult:
        """Try to form one group from one game's waiting room."""
        return self._services[group_key].poll()

    def poll_all(self) -> list[FormationResult]:
        """Drain every waiting room, forming every group that can form this sweep.

        Each service is polled until it forms no more (a group of the declared size
        cannot be selected, or a probe rejects the candidate). Every formed group is
        returned, so one sweep forms several meshes of one game and meshes of others.
        """
        formed: list[FormationResult] = []
        for service in self._services.values():
            while True:
                result = service.poll()
                if result.status == "formed":
                    formed.append(result)
                    continue
                break
        return formed

    def waiting(self) -> dict[str, tuple[MatchmakingTicket, ...]]:
        """Return the still-waiting tickets per group key, in arrival order."""
        return {key: service.waiting() for key, service in self._services.items()}

    def reacquire_lease(
        self, group_key: str, interaction_id: str, lease: ConnectionLease
    ) -> ConnectionLease:
        """Re-issue a lease at the next fencing generation through its game service."""
        return self._services[group_key].reacquire_lease(interaction_id, lease)

    def is_current(self, group_key: str, lease: ConnectionLease) -> bool:
        """Return whether a lease holds the current generation in its game service."""
        return self._services[group_key].is_current(lease)

    def group_keys(self) -> Mapping[str, MeshFormationService]:
        """Return the registered services keyed by group key, read-only."""
        return dict(self._services)


__all__ = ["GroupConfig", "MeshFormationPool"]
