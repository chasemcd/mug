"""Interactions, channels, groups, and leases (API-06, layer L1).

This family owns the runtime membership records: the ``Interaction`` and its
``MonitoringPolicy``, the ``ChannelInstance`` and per-actor ``Membership``, the
``Group`` and its ``MatchmakingTicket``, the ``P2PMeshMembership`` with its
``MeshLatencyProbe`` evidence, and the ``ConnectionLease``. Each record
references the kernel (L0) types. The ``MeshFormationService`` adds the peer-mesh
formation runtime over these records: match, probe, cast, and fence.
"""

from __future__ import annotations

from mug.interactions.service import (
    FormationResult,
    MeshFormationService,
)
from mug.interactions.types import (
    ChannelInstance,
    ConnectionLease,
    Group,
    Interaction,
    MatchmakingTicket,
    Membership,
    MeshLatencyProbe,
    MonitoringPolicy,
    P2PMeshMembership,
    interactions_schema,
)

__all__ = [
    "ChannelInstance",
    "ConnectionLease",
    "FormationResult",
    "Group",
    "Interaction",
    "MatchmakingTicket",
    "Membership",
    "MeshFormationService",
    "MeshLatencyProbe",
    "MonitoringPolicy",
    "P2PMeshMembership",
    "interactions_schema",
]
