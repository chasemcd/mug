"""Seats, actors, casting, grouping, and controller bindings (API-05, layer L1).

This family owns seven record types: the ``SeatDefinition`` that names a seat, the
``ActorInstance`` that fills one, the ``ControllerBinding`` that drives one, the
``CastDeclaration`` that maps every seat to who plays it, the ``SeatAgentBinding``
that joins an environment agent handle to an actor, the ``OnnxPolicy`` that
declares a typed inference policy, and the ``Group`` that reunites participants
across activities. Each record references the kernel (L0); the family adds no
runtime.
"""

from __future__ import annotations

from mug.casting.types import (
    ActorInstance,
    AgentActorSpec,
    CastDeclaration,
    ControllerBinding,
    Group,
    OnnxPolicy,
    SeatAgentBinding,
    SeatDefinition,
    casting_schema,
)

__all__ = [
    "ActorInstance",
    "AgentActorSpec",
    "CastDeclaration",
    "ControllerBinding",
    "Group",
    "OnnxPolicy",
    "SeatAgentBinding",
    "SeatDefinition",
    "casting_schema",
]
