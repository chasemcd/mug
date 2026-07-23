"""Automated controllers and scheduling (API-12, layer L1).

This family owns six record types: the ``ControllerPolicy`` and reusable
``FallbackPolicy`` that govern automated seats, the ``DecisionRequest`` and
``DecisionResult`` that carry one decision, the ``SchedulerState`` per seat, and
the ``P2PBotAuthority`` that names which peer decides for a bot. Each record
references the kernel (L0).

``mug.scheduling.runtime`` adds the server-mode scheduler over these records: it
awaits a bound async controller under the request deadline, applies the seat
fallback when a decision misses the deadline or fails, and records the request and
the result on the command spine.
"""

from __future__ import annotations

from mug.scheduling.runtime import (
    AsyncController,
    DecisionContext,
    DecisionOutcome,
    Scheduler,
)
from mug.scheduling.types import (
    ControllerPolicy,
    DecisionRequest,
    DecisionResult,
    FallbackPolicy,
    FallbackRule,
    P2PBotAuthority,
    SchedulerState,
    scheduling_schema,
)

__all__ = [
    "AsyncController",
    "ControllerPolicy",
    "DecisionContext",
    "DecisionOutcome",
    "DecisionRequest",
    "DecisionResult",
    "FallbackPolicy",
    "FallbackRule",
    "P2PBotAuthority",
    "Scheduler",
    "SchedulerState",
    "scheduling_schema",
]
